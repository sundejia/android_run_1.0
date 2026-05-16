"""
Loguru error-notification sink.

A custom loguru sink that intercepts ERROR+ records and dispatches them
to ``ErrorNotificationService`` for email delivery.  Works in both the
main FastAPI process and isolated subprocess scripts.
"""

from __future__ import annotations

import time
import traceback

from loguru import logger as _loguru_logger

from wecom_automation.services.notification.error_notification import (
    ErrorNotificationService,
)

# ---------------------------------------------------------------------------
# Module-level singleton (lazy init + periodic refresh)
# ---------------------------------------------------------------------------

_service: ErrorNotificationService | None = None
_last_init_time: float = 0
_INIT_REFRESH_INTERVAL = 300  # re-read settings every 5 min


def _get_or_create_service() -> ErrorNotificationService | None:
    """Lazily create or refresh the ErrorNotificationService from DB settings."""
    global _service, _last_init_time

    now = time.time()
    if _service is not None and (now - _last_init_time) < _INIT_REFRESH_INTERVAL:
        return _service

    try:
        from wecom_automation.core.config import get_default_db_path

        db_path = str(get_default_db_path())

        # The backend settings service may not be importable from a plain
        # subprocess context (it lives under wecom-desktop/backend/).
        # Try the backend service first; fall back to reading DB directly.
        try:
            import sys
            from pathlib import Path

            backend_dir = Path(db_path).parent.parent / "wecom-desktop" / "backend"
            if str(backend_dir) not in sys.path:
                sys.path.insert(0, str(backend_dir))
            from services.settings.service import SettingsService

            svc = SettingsService(db_path)
            email_settings = svc.get_email_settings()
        except Exception:
            # Minimal fallback: read email settings from the settings table
            import sqlite3

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT key, value_string, value_int, value_bool "
                    "FROM settings WHERE category = 'email'"
                ).fetchall()
                data: dict = {}
                for r in rows:
                    if r["value_string"] is not None:
                        data[r["key"]] = r["value_string"]
                    elif r["value_int"] is not None:
                        data[r["key"]] = r["value_int"]
                    elif r["value_bool"] is not None:
                        data[r["key"]] = bool(r["value_bool"])
                from types import SimpleNamespace

                email_settings = SimpleNamespace(**data)
            finally:
                conn.close()

        _service = ErrorNotificationService.from_settings(email_settings)
    except Exception:
        _service = None

    _last_init_time = now
    return _service


def _reset_service() -> None:
    """Force re-initialization on next error. Useful after settings change."""
    global _service, _last_init_time
    _service = None
    _last_init_time = 0


# ---------------------------------------------------------------------------
# Sink callable
# ---------------------------------------------------------------------------

def error_notification_sink(message) -> None:  # noqa: ANN001 — loguru passes Message
    """Loguru custom sink: capture ERROR+ and send email notification."""
    record = message.record
    level_name = record["level"].name

    if level_name not in ("ERROR", "CRITICAL"):
        return

    service = _get_or_create_service()
    if service is None:
        return

    error_message = str(record["message"])
    source = record["extra"].get("module", record.get("name", "unknown"))

    tb_str = ""
    exc = record.get("exception")
    if exc:
        try:
            tb_str = "".join(traceback.format_exception(*exc))
        except Exception:
            tb_str = str(exc)

    try:
        service.notify_error(
            message=error_message,
            level=level_name,
            source=source,
            traceback_str=tb_str,
            extra=dict(record["extra"]),
        )
    except Exception:
        pass  # never let notification failure propagate back to loguru


def _error_filter(record: dict) -> bool:
    """Only pass ERROR and CRITICAL records to the sink."""
    return record["level"].no >= 40  # loguru: ERROR=40, CRITICAL=50


def install_error_notification_sink() -> int | None:
    """Install the error notification sink into loguru.

    Call after ``init_logging()`` in both main and subprocess contexts.
    Returns the sink ID or ``None`` on failure.
    """
    try:
        return _loguru_logger.add(
            error_notification_sink,
            level="ERROR",
            filter=_error_filter,
            enqueue=True,
        )
    except Exception:
        return None
