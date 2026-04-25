"""End-to-end style regression for the duplicate-send race.

This test simulates the production failure described in
``docs/04-bugs-and-fixes/active/2026-02-09-sidecar-timeout-duplicate-send.md``
and the ``sidecar-duplicate-send-perfect-fix`` plan:

1. ``realtime_reply`` enqueues a Sidecar message.
2. The frontend (or auto-send) flips it to ``SENDING`` and starts
   driving the device. The ADB link is slow: each phase
   (tap input, type text, tap send) eats real wall-clock time so the
   total send takes longer than the configured Sidecar hard timeout.
3. ``_send_reply_wrapper`` calls ``wait_for_send``. Without the fix it
   would return ``timeout`` even though the send is still in flight,
   the wrapper would direct-send a second copy, and the device would
   see two messages.

With the fix in place:

* Layer 1's grace window keeps polling until SENDING reaches SENT.
* ``wait_for_send`` therefore returns ``sent``.
* The wrapper returns ``(True, message)`` and never calls the direct-send
  HTTP endpoint, so the device receives the message exactly once.

We assert exactly one ADB drive sequence even though the entire chain
exceeds the original 60s timeout.

Usage:
    pytest tests/integration/test_sidecar_slow_device_no_duplicate.py -v
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "wecom-desktop" / "backend"))
sys.path.insert(0, str(REPO_ROOT / "src"))

mock_droidrun = MagicMock()
mock_droidrun.tools = MagicMock()
mock_droidrun.tools.adb = MagicMock()
mock_droidrun.tools.adb.AdbTools = MagicMock()
sys.modules.setdefault("droidrun", mock_droidrun)
sys.modules.setdefault("droidrun.tools", mock_droidrun.tools)
sys.modules.setdefault("droidrun.tools.adb", mock_droidrun.tools.adb)

from routers import sidecar as sidecar_module  # noqa: E402
from routers.sidecar import MessageStatus, QueuedMessageModel, wait_for_send  # noqa: E402


SERIAL = "INTEGRATION-SLOW"


def _build_detector():
    from services.followup.response_detector import ResponseDetector

    repo = MagicMock()
    settings_manager = MagicMock()
    return ResponseDetector(repository=repo, settings_manager=settings_manager)


class FakeSidecarClient:
    """Mimics the SidecarClient surface used by ``_send_reply_wrapper``,
    backed by the real in-memory queue in ``routers.sidecar``."""

    def __init__(self, serial: str):
        self.serial = serial

    async def add_message(self, customer_name, channel, message):
        msg_id = f"{self.serial}-msg"
        msg = QueuedMessageModel(
            id=msg_id,
            serial=self.serial,
            customerName=customer_name,
            channel=channel,
            message=message,
            timestamp=0.0,
            status=MessageStatus.PENDING,
        )
        sidecar_module._queues.setdefault(self.serial, []).append(msg)
        return msg_id

    async def set_message_ready(self, msg_id):
        for m in sidecar_module._get_queue(self.serial):
            if m.id == msg_id:
                m.status = MessageStatus.READY
                return True
        return False

    async def wait_for_send(self, msg_id, timeout):
        return await wait_for_send(self.serial, msg_id, timeout=timeout)

    async def mark_as_sent_directly(self, msg_id):
        return True


@pytest.fixture(autouse=True)
def _reset_sidecar_state():
    sidecar_module._queues.pop(SERIAL, None)
    sidecar_module._waiting_events.pop(SERIAL, None)
    yield
    sidecar_module._queues.pop(SERIAL, None)
    sidecar_module._waiting_events.pop(SERIAL, None)


@pytest.mark.asyncio
async def test_slow_device_send_does_not_double_send(monkeypatch):
    """Simulate a device whose total send time crosses the hard timeout.

    Real numbers: hard timeout = 0.3s, "ADB send" takes 0.6s. Grace = 1.0s.
    With the fix, the upstream wrapper sees ``reason=sent`` once the
    fake ADB completes during grace, and never falls back to direct send.
    """
    detector = _build_detector()
    detector._get_sidecar_timeout = lambda: 0.3

    # Layer 1's grace seconds; large enough for our fake send to finish.
    monkeypatch.setattr(sidecar_module, "_get_grace_seconds", lambda: 1.0)

    client = FakeSidecarClient(SERIAL)
    adb_send_calls: list[str] = []

    async def fake_frontend_send(msg_id: str, text: str):
        """Stand-in for the frontend / countdown that, after enqueue,
        flips the message to SENDING and drives the (slow) ADB link."""
        await asyncio.sleep(0.05)  # let _send_reply_wrapper enter wait_for_send
        for m in sidecar_module._get_queue(SERIAL):
            if m.id == msg_id:
                m.status = MessageStatus.SENDING
                break
        sidecar_module._get_waiting_event(SERIAL).set()

        # Slow ADB chain: type + tap takes longer than the hard timeout
        await asyncio.sleep(0.6)
        adb_send_calls.append(text)

        for m in sidecar_module._get_queue(SERIAL):
            if m.id == msg_id:
                m.status = MessageStatus.SENT
                m.message = text
                break
        sidecar_module._get_waiting_event(SERIAL).set()

    original_add = client.add_message

    async def add_and_drive(customer_name=None, channel=None, message=None):
        msg_id = await original_add(customer_name=customer_name, channel=channel, message=message)
        asyncio.create_task(fake_frontend_send(msg_id, message))
        return msg_id

    client.add_message = add_and_drive  # type: ignore[assignment]

    with patch(
        "services.followup.response_detector.BlacklistChecker.is_blacklisted",
        return_value=False,
    ), patch(
        "services.followup.recent_replies_repository.get_recent_replies_repository",
        side_effect=Exception("disabled in test"),
    ), patch("aiohttp.ClientSession") as mock_http:
        success, sent = await detector._send_reply_wrapper(
            wecom_service=MagicMock(),
            serial=SERIAL,
            user_name="Alice",
            user_channel="WeChat",
            message="hello world",
            sidecar_client=client,
        )

    assert success is True, "wrapper must report success once SENT lands during grace"
    assert sent == "hello world"
    assert adb_send_calls == ["hello world"], (
        "device must see the message exactly once (no direct-send fallback)"
    )
    mock_http.assert_not_called(), "no aiohttp direct-send may be issued"


@pytest.mark.asyncio
async def test_slow_device_grace_exhausted_no_direct_send(monkeypatch):
    """If the slow device exceeds *both* the hard timeout AND the grace
    window, ``wait_for_send`` returns ``still_sending`` and the wrapper
    must NOT fall back to direct send. The original send may still
    complete on the device long after we return; what matters is that
    the wrapper does not fire a second send."""
    detector = _build_detector()
    detector._get_sidecar_timeout = lambda: 0.1
    monkeypatch.setattr(sidecar_module, "_get_grace_seconds", lambda: 0.2)

    client = FakeSidecarClient(SERIAL)
    adb_send_calls: list[str] = []

    async def fake_frontend_send(msg_id: str, text: str):
        await asyncio.sleep(0.02)
        for m in sidecar_module._get_queue(SERIAL):
            if m.id == msg_id:
                m.status = MessageStatus.SENDING
                break
        sidecar_module._get_waiting_event(SERIAL).set()
        # Send takes much longer than timeout + grace.
        await asyncio.sleep(1.5)
        adb_send_calls.append(text)
        for m in sidecar_module._get_queue(SERIAL):
            if m.id == msg_id:
                m.status = MessageStatus.SENT
                m.message = text
                break

    original_add = client.add_message

    async def add_and_drive(customer_name=None, channel=None, message=None):
        msg_id = await original_add(customer_name=customer_name, channel=channel, message=message)
        asyncio.create_task(fake_frontend_send(msg_id, message))
        return msg_id

    client.add_message = add_and_drive  # type: ignore[assignment]

    with patch(
        "services.followup.response_detector.BlacklistChecker.is_blacklisted",
        return_value=False,
    ), patch(
        "services.followup.recent_replies_repository.get_recent_replies_repository",
        side_effect=Exception("disabled in test"),
    ), patch("aiohttp.ClientSession") as mock_http:
        success, sent = await detector._send_reply_wrapper(
            wecom_service=MagicMock(),
            serial=SERIAL,
            user_name="Alice",
            user_channel="WeChat",
            message="hi again",
            sidecar_client=client,
        )

    assert success is False
    assert sent is None
    mock_http.assert_not_called(), "direct-send fallback must NOT fire"

    # Wait for the slow ADB chain to finish so we don't leave a dangling task.
    await asyncio.sleep(1.7)
    assert adb_send_calls == ["hi again"], "the original send still completes on the device once"
