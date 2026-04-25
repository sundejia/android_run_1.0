"""Regression tests for ``wait_for_send`` SENDING grace handling.

This file locks in the Layer 1 fix from the
``sidecar-duplicate-send-perfect-fix`` plan. The original implementation
returned ``{"success": False, "reason": "timeout"}`` whenever the hard
timeout elapsed, even if the queued message was actively in
``MessageStatus.SENDING`` at that moment. That false-negative timeout was
the trigger for the duplicate-send race, because the upstream
``_send_reply_wrapper`` then fell back to a direct send while the original
send was still in flight.

The new behaviour:

* PENDING/READY at hard timeout -> mark EXPIRED, return ``timeout`` (unchanged).
* SENDING at hard timeout -> enter a grace window (``sidecar_grace_seconds``)
  and keep polling. If the message reaches a terminal state during grace
  return that state. If grace runs out while still SENDING, return the
  new ``still_sending`` reason so the caller knows NOT to direct-send.
* SENT/FAILED reached during normal polling work as before.

Usage:
    pytest wecom-desktop/backend/tests/test_sidecar_wait_for_send_grace.py -v
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
sys.path.insert(0, str(backend_dir.parent.parent / "src"))

# Mock droidrun before importing anything that pulls in WeComService.
mock_droidrun = MagicMock()
mock_droidrun.tools = MagicMock()
mock_droidrun.tools.adb = MagicMock()
mock_droidrun.tools.adb.AdbTools = MagicMock()
sys.modules.setdefault("droidrun", mock_droidrun)
sys.modules.setdefault("droidrun.tools", mock_droidrun.tools)
sys.modules.setdefault("droidrun.tools.adb", mock_droidrun.tools.adb)

from routers import sidecar as sidecar_module  # noqa: E402
from routers.sidecar import (  # noqa: E402
    MessageStatus,
    QueuedMessageModel,
    wait_for_send,
)


SERIAL = "TEST-WAIT-GRACE"


@pytest.fixture(autouse=True)
def reset_sidecar_state():
    """Reset module-level dicts between tests so they are independent."""
    sidecar_module._queues.pop(SERIAL, None)
    sidecar_module._waiting_events.pop(SERIAL, None)
    sidecar_module._skip_flags.pop(SERIAL, None)
    yield
    sidecar_module._queues.pop(SERIAL, None)
    sidecar_module._waiting_events.pop(SERIAL, None)
    sidecar_module._skip_flags.pop(SERIAL, None)


def _enqueue(message_id: str, status: MessageStatus = MessageStatus.READY) -> QueuedMessageModel:
    msg = QueuedMessageModel(
        id=message_id,
        serial=SERIAL,
        customerName="Alice",
        channel="WeChat",
        message="hello",
        timestamp=0.0,
        status=status,
    )
    sidecar_module._queues.setdefault(SERIAL, []).append(msg)
    return msg


@pytest.mark.asyncio
async def test_pending_timeout_returns_timeout_and_marks_expired(monkeypatch):
    """A queued message that never moves out of READY must timeout cleanly
    and be marked EXPIRED so it cannot be sent later by accident."""
    msg = _enqueue("msg-pending", status=MessageStatus.READY)

    # Disable grace so we do not stall the test unnecessarily.
    monkeypatch.setattr(sidecar_module, "_get_grace_seconds", lambda: 0.0)

    result = await wait_for_send(SERIAL, "msg-pending", timeout=0.05)

    assert result == {"success": False, "reason": "timeout"}
    assert msg.status == MessageStatus.EXPIRED


@pytest.mark.asyncio
async def test_sending_during_timeout_enters_grace_and_returns_sent(monkeypatch):
    """If the message is SENDING when the hard timeout fires, wait_for_send
    must keep polling for the grace window and pick up the SENT transition
    instead of returning a false timeout."""
    msg = _enqueue("msg-sending-then-sent", status=MessageStatus.SENDING)

    # 5 second grace is enough for our 0.2s simulated send to finish.
    monkeypatch.setattr(sidecar_module, "_get_grace_seconds", lambda: 5.0)

    async def flip_to_sent_after_delay():
        await asyncio.sleep(0.2)
        msg.status = MessageStatus.SENT
        msg.message = "hello (final)"
        # Wake up the polling loop sooner.
        sidecar_module._get_waiting_event(SERIAL).set()

    flip_task = asyncio.create_task(flip_to_sent_after_delay())
    result = await wait_for_send(SERIAL, "msg-sending-then-sent", timeout=0.05)
    await flip_task

    assert result["success"] is True
    assert result["reason"] == "sent"
    assert result["message"] == "hello (final)"


@pytest.mark.asyncio
async def test_sending_grace_exhausted_returns_still_sending(monkeypatch):
    """If grace runs out while the message is still SENDING, wait_for_send
    must return the new ``still_sending`` reason so the upstream caller
    knows it is unsafe to direct-send."""
    msg = _enqueue("msg-grace-exhausted", status=MessageStatus.SENDING)

    monkeypatch.setattr(sidecar_module, "_get_grace_seconds", lambda: 0.2)

    result = await wait_for_send(SERIAL, "msg-grace-exhausted", timeout=0.05)

    assert result == {"success": False, "reason": "still_sending"}
    # Status must NOT have been forcibly changed; the in-flight send still owns it.
    assert msg.status == MessageStatus.SENDING


@pytest.mark.asyncio
async def test_sent_during_normal_polling_returns_sent(monkeypatch):
    """Sanity-check the happy path: a transition to SENT before timeout
    returns ``sent`` immediately."""
    msg = _enqueue("msg-normal-sent", status=MessageStatus.READY)
    monkeypatch.setattr(sidecar_module, "_get_grace_seconds", lambda: 1.0)

    async def flip_to_sent():
        await asyncio.sleep(0.05)
        msg.status = MessageStatus.SENT
        msg.message = "hi"
        sidecar_module._get_waiting_event(SERIAL).set()

    flip_task = asyncio.create_task(flip_to_sent())
    result = await wait_for_send(SERIAL, "msg-normal-sent", timeout=2.0)
    await flip_task

    assert result == {"success": True, "reason": "sent", "message": "hi"}


@pytest.mark.asyncio
async def test_sending_then_failed_during_grace_returns_failed(monkeypatch):
    """If the in-flight send transitions to FAILED during the grace window,
    wait_for_send must return ``failed`` so the caller knows not to retry."""
    msg = _enqueue("msg-grace-fail", status=MessageStatus.SENDING)
    msg.error = None
    monkeypatch.setattr(sidecar_module, "_get_grace_seconds", lambda: 1.0)

    async def flip_to_failed():
        await asyncio.sleep(0.1)
        msg.status = MessageStatus.FAILED
        msg.error = "device disconnected"
        sidecar_module._get_waiting_event(SERIAL).set()

    flip_task = asyncio.create_task(flip_to_failed())
    result = await wait_for_send(SERIAL, "msg-grace-fail", timeout=0.05)
    await flip_task

    assert result["success"] is False
    assert result["reason"] == "failed"
    assert result["error"] == "device disconnected"
