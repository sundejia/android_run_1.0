"""Regression tests for ``SidecarSession.send_message`` last-resort dedup.

Locks in the Layer 4 fix from the
``sidecar-duplicate-send-perfect-fix`` plan. This is the panic-button
defense: even if Layers 1-3 all fail to block a duplicate send, the
session itself refuses to drive the device with the same exact text
twice within a sliding window.

Properties verified here:

* Identical text inside the dedup window does NOT call
  ``self.service.send_message`` a second time, but still returns True
  so callers do not retry.
* Identical text after the window IS sent normally.
* A failed first send does NOT poison the dedup window, so the next
  attempt for the same text is still allowed.

Usage:
    pytest wecom-desktop/backend/tests/test_sidecar_session_dedup.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
sys.path.insert(0, str(backend_dir.parent.parent / "src"))

mock_droidrun = MagicMock()
mock_droidrun.tools = MagicMock()
mock_droidrun.tools.adb = MagicMock()
mock_droidrun.tools.adb.AdbTools = MagicMock()
sys.modules.setdefault("droidrun", mock_droidrun)
sys.modules.setdefault("droidrun.tools", mock_droidrun.tools)
sys.modules.setdefault("droidrun.tools.adb", mock_droidrun.tools.adb)

from routers import sidecar as sidecar_module  # noqa: E402


class FakeADB:
    def __init__(self):
        self.is_connected = False

    async def connect(self):
        self.is_connected = True


class FakeWeComService:
    """Counts calls to ``send_message`` so we can assert dedup."""

    def __init__(self, success: bool = True):
        self.adb = FakeADB()
        self.send_calls: list[str] = []
        self._success = success

    async def send_message(self, text: str) -> tuple[bool, str]:
        self.send_calls.append(text)
        return self._success, text


@pytest.fixture
def session(monkeypatch):
    """Build a SidecarSession backed by a FakeWeComService."""

    fake_service = FakeWeComService(success=True)
    monkeypatch.setattr(sidecar_module, "WeComService", lambda config: fake_service)
    s = sidecar_module.SidecarSession("DEDUP-TEST")
    s.service = fake_service
    return s


@pytest.fixture
def failing_session(monkeypatch):
    fake_service = FakeWeComService(success=False)
    monkeypatch.setattr(sidecar_module, "WeComService", lambda config: fake_service)
    s = sidecar_module.SidecarSession("DEDUP-TEST-FAIL")
    s.service = fake_service
    return s


@pytest.mark.asyncio
async def test_duplicate_send_within_window_blocked(session):
    """Two send_message calls with identical text inside the dedup
    window must hit the device only once."""
    ok1 = await session.send_message("hello world")
    ok2 = await session.send_message("hello world")

    assert ok1 is True
    assert ok2 is True  # Idempotent: caller still sees success
    assert session.service.send_calls == ["hello world"]


@pytest.mark.asyncio
async def test_different_text_within_window_allowed(session):
    """Different text within the same window must be sent normally."""
    await session.send_message("first")
    await session.send_message("second")

    assert session.service.send_calls == ["first", "second"]


@pytest.mark.asyncio
async def test_duplicate_after_window_allowed(session):
    """After the dedup window expires the same text is allowed again."""
    # Force a tiny window so the test stays fast.
    session._dedup_window_seconds = 0.05

    await session.send_message("hello again")
    # Manually expire the window without sleeping for real.
    import time

    session._recent_sends = {h: ts - 1.0 for h, ts in session._recent_sends.items()}
    _ = time.time  # keep linter quiet

    await session.send_message("hello again")

    assert session.service.send_calls == ["hello again", "hello again"]


@pytest.mark.asyncio
async def test_failed_send_does_not_record_in_window(failing_session):
    """If the first send fails it must NOT enter the dedup window;
    a retry of the same text must still drive the device."""
    ok1 = await failing_session.send_message("retry-me")
    assert ok1 is False
    assert failing_session.service.send_calls == ["retry-me"]
    # The hash should NOT have been recorded.
    assert failing_session._recent_sends == {}

    ok2 = await failing_session.send_message("retry-me")
    assert ok2 is False
    assert failing_session.service.send_calls == ["retry-me", "retry-me"]
