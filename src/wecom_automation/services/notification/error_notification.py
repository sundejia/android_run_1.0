"""
Error notification service — centralized error-to-email dispatcher.

Captures errors from loguru sinks and FastAPI middleware, applies rate
limiting and deduplication, then dispatches email notifications via SMTP.

Designed for use from both the main FastAPI process (async) and child
subprocess scripts (sync).
"""

from __future__ import annotations

import hashlib
import logging
import re
import smtplib
import threading
import traceback
from datetime import datetime, timedelta, timezone
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any


# ---------------------------------------------------------------------------
# Error fingerprint — normalizes messages for dedup
# ---------------------------------------------------------------------------

class ErrorFingerprint:
    """Generates a stable fingerprint from an error for rate-limited dedup."""

    # Patterns to strip from messages so that identical errors at different
    # times / on different devices still produce the same fingerprint.
    _NORMALIZE_PATTERNS: list[tuple[str, str]] = [
        (r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?", "<ts>"),
        (r"\d{2}:\d{2}:\d{2}(?:\.\d+)?", "<time>"),
        (r"R58M\w+|adb[-_]\w+|emulator-\d+", "<serial>"),
        (r"0x[0-9a-fA-F]+", "<hex>"),
        (r"\d{4,}", "<num>"),
        (r"/tmp/[\w./\-]+", "<tmpfile>"),
        (r"[A-Z]:\\[^\s]+", "<winpath>"),
        (r"line \d+", "line <n>"),
    ]

    @staticmethod
    def generate(message: str, source: str = "", level: str = "ERROR") -> str:
        """Return a 12-char hex fingerprint for deduplication."""
        normalized = message
        for pattern, replacement in ErrorFingerprint._NORMALIZE_PATTERNS:
            normalized = re.sub(pattern, replacement, normalized)

        payload = f"{level}:{source}:{normalized}"
        return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Rate limiter — per-fingerprint time window
# ---------------------------------------------------------------------------

class ErrorRateLimiter:
    """Thread-safe rate limiter keyed by error fingerprint."""

    def __init__(self, default_interval_minutes: int = 30):
        self._last_sent: dict[str, datetime] = {}
        self._interval = timedelta(minutes=max(1, default_interval_minutes))
        self._lock = threading.Lock()

    def should_send(self, fingerprint: str) -> bool:
        """True if enough time has passed since the last notification."""
        with self._lock:
            last = self._last_sent.get(fingerprint)
            if last is None:
                return True
            return datetime.now(timezone.utc) - last >= self._interval

    def record_sent(self, fingerprint: str) -> None:
        with self._lock:
            self._last_sent[fingerprint] = datetime.now(timezone.utc)

    def cleanup(self, max_age_hours: int = 24) -> None:
        """Remove expired entries to prevent unbounded memory growth."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        with self._lock:
            self._last_sent = {
                k: v for k, v in self._last_sent.items() if v > cutoff
            }


# ---------------------------------------------------------------------------
# ErrorNotificationService
# ---------------------------------------------------------------------------

class ErrorNotificationService:
    """Centralized error notification dispatcher.

    Subscribes to error events from multiple sources (loguru sink,
    FastAPI middleware), applies rate limiting and deduplication,
    formats error emails, and dispatches to notification channels.
    """

    def __init__(
        self,
        *,
        smtp_server: str,
        smtp_port: int,
        sender_email: str,
        sender_password: str,
        sender_name: str,
        receiver_email: str,
        error_rate_limit_minutes: int = 30,
        error_notify_min_level: str = "ERROR",
    ):
        self._smtp_server = smtp_server
        self._smtp_port = smtp_port
        self._sender_email = sender_email
        self._sender_password = sender_password
        self._sender_name = sender_name
        self._receiver_email = receiver_email
        self._rate_limiter = ErrorRateLimiter(
            default_interval_minutes=error_rate_limit_minutes,
        )
        self._min_level = getattr(logging, error_notify_min_level, logging.ERROR)
        self._logger = logging.getLogger(__name__)

    # ---- Factory ----------------------------------------------------------

    @classmethod
    def from_settings(cls, settings: Any) -> ErrorNotificationService | None:
        """Create from an EmailSettings-like object.  Returns None if disabled."""
        if not getattr(settings, "enabled", False):
            return None
        if not getattr(settings, "notify_on_error", False):
            return None
        if not getattr(settings, "sender_email", "") or not getattr(settings, "receiver_email", ""):
            return None
        return cls(
            smtp_server=getattr(settings, "smtp_server", "smtp.qq.com"),
            smtp_port=getattr(settings, "smtp_port", 465),
            sender_email=settings.sender_email,
            sender_password=settings.sender_password,
            sender_name=getattr(settings, "sender_name", "WeCom System"),
            receiver_email=settings.receiver_email,
            error_rate_limit_minutes=getattr(settings, "error_rate_limit_minutes", 30),
            error_notify_min_level=getattr(settings, "error_notify_min_level", "ERROR"),
        )

    # ---- Public API -------------------------------------------------------

    def notify_error(
        self,
        message: str,
        level: str = "ERROR",
        source: str = "",
        traceback_str: str = "",
        extra: dict[str, Any] | None = None,
    ) -> bool:
        """Sync entry point (for loguru sink / subprocess)."""
        level_value = getattr(logging, level, logging.ERROR)
        if level_value < self._min_level:
            return False

        fingerprint = ErrorFingerprint.generate(message, source, level)
        if not self._rate_limiter.should_send(fingerprint):
            return False

        subject = f"[WeCom Error] {message[:60]}"
        html = self._format_error_email(
            message=message,
            level=level,
            source=source,
            traceback_str=traceback_str,
            extra=extra or {},
        )
        success = self._send_email(subject, html)
        if success:
            self._rate_limiter.record_sent(fingerprint)
        return success

    async def notify_error_async(
        self,
        message: str,
        level: str = "ERROR",
        source: str = "",
        traceback_str: str = "",
        extra: dict[str, Any] | None = None,
    ) -> bool:
        """Async entry point (for FastAPI middleware)."""
        import asyncio
        return await asyncio.to_thread(
            self.notify_error,
            message=message,
            level=level,
            source=source,
            traceback_str=traceback_str,
            extra=extra,
        )

    # ---- Email formatting -------------------------------------------------

    def _format_error_email(
        self,
        message: str,
        level: str,
        source: str,
        traceback_str: str,
        extra: dict[str, Any],
    ) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        device = extra.get("device", "")
        tb_html = ""
        if traceback_str:
            # Keep last 20 lines for readability
            lines = traceback_str.strip().splitlines()
            if len(lines) > 20:
                lines = ["... (truncated)"] + lines[-20:]
            escaped = "<br>".join(
                line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                for line in lines
            )
            tb_html = f"""
            <div class="info-row" style="background:#2d2d2d;color:#f8f8f2;font-family:monospace;
                font-size:12px;padding:12px;border-radius:5px;white-space:pre-wrap;
                max-height:300px;overflow:auto;">{escaped}</div>"""

        device_row = ""
        if device:
            device_row = f"""
            <div class="info-row">
                <div class="label">Device</div>
                <div class="value">{device}</div>
            </div>"""

        level_color = "#dc3545" if level == "CRITICAL" else "#fd7e14"

        return f"""
        <html><head><meta charset="utf-8"><style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
            .container {{ max-width: 640px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, {level_color} 0%, #c0392b 100%);
                       color: white; padding: 20px; border-radius: 10px 10px 0 0; text-align: center; }}
            .content {{ background: #f8f9fa; padding: 20px; border: 1px solid #e9ecef; }}
            .info-row {{ margin: 8px 0; padding: 10px; background: white; border-radius: 5px; }}
            .label {{ color: #6c757d; font-size: 12px; }}
            .value {{ font-size: 14px; color: #333; word-break: break-all; }}
            .msg-box {{ background: #fff5f5; border-left: 4px solid {level_color};
                        padding: 12px; margin: 12px 0; border-radius: 4px;
                        font-size: 14px; color: #333; }}
            .footer {{ background: #e9ecef; padding: 15px; border-radius: 0 0 10px 10px;
                       text-align: center; font-size: 12px; color: #6c757d; }}
        </style></head><body>
        <div class="container">
            <div class="header">
                <h2 style="margin:0;">System Error Alert</h2>
            </div>
            <div class="content">
                <div class="info-row">
                    <div class="label">Level</div>
                    <div class="value" style="color:{level_color};font-weight:bold;">{level}</div>
                </div>
                <div class="info-row">
                    <div class="label">Source</div>
                    <div class="value">{source or "unknown"}</div>
                </div>
                {device_row}
                <div class="info-row">
                    <div class="label">Time</div>
                    <div class="value">{now}</div>
                </div>
                <div class="msg-box">{message}</div>
                {tb_html}
            </div>
            <div class="footer">This is an automated alert from WeCom Sync System</div>
        </div>
        </body></html>"""

    # ---- SMTP dispatch ----------------------------------------------------

    def _send_email(self, subject: str, html_content: str) -> bool:
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = formataddr([self._sender_name, self._sender_email])
            msg["To"] = formataddr(["", self._receiver_email])
            msg["Subject"] = Header(subject, "utf-8")
            msg.attach(MIMEText(html_content, "html", "utf-8"))

            if self._smtp_port == 465:
                server = smtplib.SMTP_SSL(self._smtp_server, self._smtp_port, timeout=10)
            else:
                server = smtplib.SMTP(self._smtp_server, self._smtp_port, timeout=10)
                server.starttls()

            server.login(self._sender_email, self._sender_password)
            server.sendmail(self._sender_email, [self._receiver_email], msg.as_string())
            server.quit()
            return True
        except Exception as e:
            self._logger.warning("Error notification email failed: %s", e)
            return False
