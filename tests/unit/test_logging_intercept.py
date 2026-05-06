"""
Regression tests for the stdlib ``logging`` → loguru intercept.

Many older modules (``services/media_actions/*``, ``services/contact_share/*``,
``event_bus``) use ``logging.getLogger(__name__)`` and expect their records
to surface in the unified device log file. Without an intercept handler
those records are silently dropped after ``init_logging`` clears the root
handlers, which is exactly how the auto-contact-share failure went
unnoticed in production for several iterations.

These tests pin the contract so the bridge cannot regress accidentally.
"""

from __future__ import annotations

import io
import logging

import pytest
from loguru import logger as _loguru_logger

from wecom_automation.core.logging import install_stdlib_intercept


@pytest.fixture
def capture_loguru_sink():
    """Add a temporary loguru sink that captures records into a buffer.

    Yields the underlying ``io.StringIO`` so tests can assert on the
    formatted output.
    """
    buffer = io.StringIO()
    sink_id = _loguru_logger.add(
        buffer,
        format="{level} | {extra[module]} | {message}",
        level="DEBUG",
    )
    try:
        yield buffer
    finally:
        _loguru_logger.remove(sink_id)


def test_stdlib_logger_is_routed_to_loguru(capture_loguru_sink):
    """A vanilla ``logging.getLogger`` warning must reach the loguru sink."""
    install_stdlib_intercept(level="DEBUG")

    stdlib_logger = logging.getLogger("wecom_automation.services.contact_share.test_marker")
    stdlib_logger.warning("attach button not found after %d attempts", 3)

    output = capture_loguru_sink.getvalue()
    assert "attach button not found after 3 attempts" in output
    assert "WARNING" in output
    assert "wecom_automation.services.contact_share.test_marker" in output


def test_intercept_preserves_module_name_in_extra(capture_loguru_sink):
    """The originating stdlib logger name should land in ``extra[module]``.

    This matters because the file format used by ``add_device_sink`` reads
    ``{name}`` (loguru auto-binds module from extra), so any drift here would
    show every legacy log as just ``root``.
    """
    install_stdlib_intercept(level="DEBUG")

    logging.getLogger("wecom_automation.services.media_actions.event_bus").error(
        "Action %s.execute raised: %s", "auto_contact_share", "boom"
    )

    output = capture_loguru_sink.getvalue()
    assert "wecom_automation.services.media_actions.event_bus" in output
    assert "auto_contact_share" in output
    assert "boom" in output


def test_intercept_is_idempotent(capture_loguru_sink):
    """Calling ``install_stdlib_intercept`` twice must not duplicate records."""
    install_stdlib_intercept(level="DEBUG")
    install_stdlib_intercept(level="DEBUG")

    logging.getLogger("wecom_automation.services.contact_share.idempotent").info("once")

    output = capture_loguru_sink.getvalue()
    occurrences = output.count("once")
    assert occurrences == 1, (
        f"Expected exactly one record, got {occurrences}. "
        "If this fails, the intercept is being installed multiple times "
        "and creating duplicate handlers on the root logger."
    )
