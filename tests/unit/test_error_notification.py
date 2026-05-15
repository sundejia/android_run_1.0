"""Unit tests for error notification service, rate limiter, and fingerprint."""

import logging
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from wecom_automation.services.notification.error_notification import (
    ErrorFingerprint,
    ErrorNotificationService,
    ErrorRateLimiter,
)


# ---------------------------------------------------------------------------
# ErrorFingerprint
# ---------------------------------------------------------------------------

class TestErrorFingerprint:
    def test_identical_messages_same_fingerprint(self):
        a = ErrorFingerprint.generate("Device disconnected", "adb", "ERROR")
        b = ErrorFingerprint.generate("Device disconnected", "adb", "ERROR")
        assert a == b

    def test_different_messages_different_fingerprint(self):
        a = ErrorFingerprint.generate("Device disconnected", "adb", "ERROR")
        b = ErrorFingerprint.generate("AI call failed", "ai", "ERROR")
        assert a != b

    def test_timestamps_normalized(self):
        a = ErrorFingerprint.generate(
            "Error at 2026-05-15 14:32:01.123 device R58M35ABCD", "sync", "ERROR"
        )
        b = ErrorFingerprint.generate(
            "Error at 2026-05-16 09:00:00.000 device R58M35XYZ1", "sync", "ERROR"
        )
        assert a == b

    def test_different_level_different_fingerprint(self):
        a = ErrorFingerprint.generate("msg", "src", "ERROR")
        b = ErrorFingerprint.generate("msg", "src", "CRITICAL")
        assert a != b

    def test_fingerprint_length(self):
        fp = ErrorFingerprint.generate("test message")
        assert len(fp) == 12


# ---------------------------------------------------------------------------
# ErrorRateLimiter
# ---------------------------------------------------------------------------

class TestErrorRateLimiter:
    def test_first_send_allowed(self):
        limiter = ErrorRateLimiter(default_interval_minutes=30)
        assert limiter.should_send("fp1") is True

    def test_second_send_blocked(self):
        limiter = ErrorRateLimiter(default_interval_minutes=30)
        limiter.should_send("fp1")
        limiter.record_sent("fp1")
        assert limiter.should_send("fp1") is False

    def test_different_fingerprint_allowed(self):
        limiter = ErrorRateLimiter(default_interval_minutes=30)
        limiter.record_sent("fp1")
        assert limiter.should_send("fp2") is True

    def test_allowed_after_window(self):
        limiter = ErrorRateLimiter(default_interval_minutes=1)
        limiter.record_sent("fp1")
        # Simulate time passing by manually setting last_sent
        limiter._last_sent["fp1"] = datetime.now(timezone.utc) - timedelta(minutes=2)
        assert limiter.should_send("fp1") is True

    def test_cleanup_removes_old_entries(self):
        limiter = ErrorRateLimiter(default_interval_minutes=1)
        limiter.record_sent("fp1")
        limiter._last_sent["fp1"] = datetime.now(timezone.utc) - timedelta(hours=2)
        limiter.cleanup(max_age_hours=1)
        assert "fp1" not in limiter._last_sent

    def test_cleanup_keeps_recent_entries(self):
        limiter = ErrorRateLimiter(default_interval_minutes=1)
        limiter.record_sent("fp1")
        limiter.cleanup(max_age_hours=1)
        assert "fp1" in limiter._last_sent

    def test_min_interval_1_minute(self):
        limiter = ErrorRateLimiter(default_interval_minutes=0)
        assert limiter._interval >= timedelta(minutes=1)


# ---------------------------------------------------------------------------
# ErrorNotificationService
# ---------------------------------------------------------------------------

def _make_settings(**overrides):
    defaults = {
        "enabled": True,
        "notify_on_error": True,
        "smtp_server": "smtp.test.com",
        "smtp_port": 465,
        "sender_email": "sender@test.com",
        "sender_password": "pass",
        "sender_name": "Test",
        "receiver_email": "recv@test.com",
        "error_rate_limit_minutes": 30,
        "error_notify_min_level": "ERROR",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestErrorNotificationServiceFromSettings:
    def test_disabled_when_not_enabled(self):
        settings = _make_settings(enabled=False)
        assert ErrorNotificationService.from_settings(settings) is None

    def test_disabled_when_notify_on_error_false(self):
        settings = _make_settings(notify_on_error=False)
        assert ErrorNotificationService.from_settings(settings) is None

    def test_disabled_when_no_sender(self):
        settings = _make_settings(sender_email="")
        assert ErrorNotificationService.from_settings(settings) is None

    def test_disabled_when_no_receiver(self):
        settings = _make_settings(receiver_email="")
        assert ErrorNotificationService.from_settings(settings) is None

    def test_enabled_returns_service(self):
        settings = _make_settings()
        svc = ErrorNotificationService.from_settings(settings)
        assert svc is not None
        assert isinstance(svc, ErrorNotificationService)


class TestErrorNotificationServiceNotify:
    def test_level_below_minimum_skipped(self):
        svc = ErrorNotificationService(
            smtp_server="s", smtp_port=465, sender_email="a@b",
            sender_password="p", sender_name="n", receiver_email="r@b",
            error_notify_min_level="CRITICAL",
        )
        with patch.object(svc, "_send_email", return_value=True) as mock:
            result = svc.notify_error(message="test", level="ERROR")
            assert result is False
            mock.assert_not_called()

    def test_rate_limit_blocks_duplicate(self):
        svc = ErrorNotificationService(
            smtp_server="s", smtp_port=465, sender_email="a@b",
            sender_password="p", sender_name="n", receiver_email="r@b",
            error_rate_limit_minutes=30,
        )
        with patch.object(svc, "_send_email", return_value=True):
            assert svc.notify_error(message="same error") is True
            assert svc.notify_error(message="same error") is False

    def test_rate_limit_allows_different_error(self):
        svc = ErrorNotificationService(
            smtp_server="s", smtp_port=465, sender_email="a@b",
            sender_password="p", sender_name="n", receiver_email="r@b",
            error_rate_limit_minutes=30,
        )
        with patch.object(svc, "_send_email", return_value=True):
            assert svc.notify_error(message="error A") is True
            assert svc.notify_error(message="error B") is True

    def test_send_failure_not_recorded(self):
        svc = ErrorNotificationService(
            smtp_server="s", smtp_port=465, sender_email="a@b",
            sender_password="p", sender_name="n", receiver_email="r@b",
            error_rate_limit_minutes=30,
        )
        with patch.object(svc, "_send_email", return_value=False):
            assert svc.notify_error(message="fail") is False
            # Should be allowed again since record_sent was not called
            with patch.object(svc, "_send_email", return_value=True):
                assert svc.notify_error(message="fail") is True


class TestErrorNotificationServiceSendEmail:
    def test_send_email_ssl(self):
        svc = ErrorNotificationService(
            smtp_server="s", smtp_port=465, sender_email="a@b",
            sender_password="p", sender_name="n", receiver_email="r@b",
        )
        with patch("wecom_automation.services.notification.error_notification.smtplib.SMTP_SSL") as mock_smtp:
            mock_instance = MagicMock()
            mock_smtp.return_value = mock_instance
            result = svc._send_email("Test Subject", "<html>body</html>")
            assert result is True
            mock_smtp.assert_called_once_with("s", 465, timeout=10)
            mock_instance.login.assert_called_once()
            mock_instance.sendmail.assert_called_once()
            mock_instance.quit.assert_called_once()

    def test_send_email_tls(self):
        svc = ErrorNotificationService(
            smtp_server="s", smtp_port=587, sender_email="a@b",
            sender_password="p", sender_name="n", receiver_email="r@b",
        )
        with patch("wecom_automation.services.notification.error_notification.smtplib.SMTP") as mock_smtp:
            mock_instance = MagicMock()
            mock_smtp.return_value = mock_instance
            result = svc._send_email("Test Subject", "<html>body</html>")
            assert result is True
            mock_smtp.assert_called_once_with("s", 587, timeout=10)
            mock_instance.starttls.assert_called_once()

    def test_send_email_failure_returns_false(self):
        svc = ErrorNotificationService(
            smtp_server="s", smtp_port=465, sender_email="a@b",
            sender_password="p", sender_name="n", receiver_email="r@b",
        )
        with patch("wecom_automation.services.notification.error_notification.smtplib.SMTP_SSL", side_effect=Exception("conn refused")):
            result = svc._send_email("Test Subject", "<html>body</html>")
            assert result is False


class TestErrorNotificationServiceFormatEmail:
    def test_format_contains_message(self):
        svc = ErrorNotificationService(
            smtp_server="s", smtp_port=465, sender_email="a@b",
            sender_password="p", sender_name="n", receiver_email="r@b",
        )
        html = svc._format_error_email(
            message="test error message",
            level="ERROR",
            source="test.module",
            traceback_str="",
            extra={},
        )
        assert "test error message" in html
        assert "ERROR" in html
        assert "test.module" in html

    def test_format_contains_traceback(self):
        svc = ErrorNotificationService(
            smtp_server="s", smtp_port=465, sender_email="a@b",
            sender_password="p", sender_name="n", receiver_email="r@b",
        )
        html = svc._format_error_email(
            message="err",
            level="ERROR",
            source="mod",
            traceback_str="Traceback:\n  File 'x', line 1\n    raise Error",
            extra={},
        )
        assert "Traceback" in html
        assert "File 'x'" in html

    def test_format_contains_device(self):
        svc = ErrorNotificationService(
            smtp_server="s", smtp_port=465, sender_email="a@b",
            sender_password="p", sender_name="n", receiver_email="r@b",
        )
        html = svc._format_error_email(
            message="err",
            level="ERROR",
            source="mod",
            traceback_str="",
            extra={"device": "R58M35ABCD"},
        )
        assert "R58M35ABCD" in html

    def test_critical_level_has_different_color(self):
        svc = ErrorNotificationService(
            smtp_server="s", smtp_port=465, sender_email="a@b",
            sender_password="p", sender_name="n", receiver_email="r@b",
        )
        html = svc._format_error_email(
            message="err", level="CRITICAL", source="mod",
            traceback_str="", extra={},
        )
        assert "#dc3545" in html
