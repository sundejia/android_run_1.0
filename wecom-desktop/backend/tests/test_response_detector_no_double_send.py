"""Regression tests for ``ResponseDetector._send_reply_wrapper``.

Locks in the Layer 2 fix from the
``sidecar-duplicate-send-perfect-fix`` plan: the direct-send fallback
must only fire when it is provably safe (queue never received the
message, or the queue had no in-flight send at hard timeout). Every
other Sidecar outcome MUST return ``(False, None)`` without driving the
device a second time.

Specifically:

* ``reason=sent`` -> success, no fallback.
* ``reason=cancelled`` / ``expired`` -> no fallback.
* ``reason=failed`` -> no fallback (avoid duplicate retry).
* ``reason=still_sending`` -> no fallback (Layer 1 says the queue may
  still complete on the device).
* ``reason=not_found`` -> no fallback (queue state lost, unsafe).
* ``reason=timeout`` -> direct send IS allowed (Layer 1 only returns
  this when the queue never moved past PENDING/READY).
* ``set_message_ready`` failure -> no fallback (queue state unknown).
* ``add_message`` failure -> direct send IS allowed (queue never had
  the message in the first place).

Usage:
    pytest wecom-desktop/backend/tests/test_response_detector_no_double_send.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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


def _build_detector():
    """Construct a ResponseDetector with the bare-minimum stubs we need."""
    from services.followup.response_detector import ResponseDetector

    repo = MagicMock()
    settings_manager = MagicMock()
    return ResponseDetector(repository=repo, settings_manager=settings_manager)


def _make_sidecar_client(*, add_id="msg-1", set_ready=True, wait_result=None):
    """Build an ``AsyncMock`` matching the SidecarClient surface used by
    ``_send_reply_wrapper``."""
    client = MagicMock()
    client.add_message = AsyncMock(return_value=add_id)
    client.set_message_ready = AsyncMock(return_value=set_ready)
    client.wait_for_send = AsyncMock(return_value=wait_result or {"success": True, "reason": "sent", "message": "hi"})
    client.mark_as_sent_directly = AsyncMock(return_value=True)
    return client


@pytest.fixture(autouse=True)
def _stub_environment():
    """Disable blacklist and cross-device dedup so they do not interfere.

    ``get_recent_replies_repository`` is imported lazily inside
    ``_send_reply_wrapper`` from
    ``services.followup.recent_replies_repository``. We patch it at the
    real source so the lazy import inside the wrapper picks up our
    fail-open stub. The wrapper already swallows any exception from
    that path, which is exactly what we want here.
    """
    with patch(
        "services.followup.response_detector.BlacklistChecker.is_blacklisted",
        return_value=False,
    ), patch(
        "services.followup.recent_replies_repository.get_recent_replies_repository",
        side_effect=Exception("disabled in tests"),
    ):
        yield


@pytest.fixture
def detector():
    det = _build_detector()
    # Stable timeout so wait_for_send mock is hit immediately
    det._get_sidecar_timeout = lambda: 0.1
    return det


@pytest.mark.asyncio
async def test_sent_reason_returns_success_no_direct_send(detector):
    """Happy path: queue confirms sent, wrapper returns True and never
    attempts a direct send."""
    client = _make_sidecar_client(wait_result={"success": True, "reason": "sent", "message": "hi"})

    with patch("aiohttp.ClientSession") as mock_session:
        success, sent = await detector._send_reply_wrapper(
            wecom_service=MagicMock(),
            serial="DEV1",
            user_name="Alice",
            user_channel="WeChat",
            message="hi",
            sidecar_client=client,
        )

    assert success is True
    assert sent == "hi"
    mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_timeout_reason_falls_back_to_direct_send(detector):
    """Layer 1 ``timeout`` only happens when queue never moved past
    READY. Direct send is the safe fallback in that case."""
    client = _make_sidecar_client(wait_result={"success": False, "reason": "timeout"})

    fake_response = AsyncMock()
    fake_response.status = 200
    fake_response.json = AsyncMock(return_value={"success": True})
    fake_session_cm = AsyncMock()
    fake_session_cm.__aenter__.return_value = fake_response
    fake_session_cm.__aexit__.return_value = None
    fake_session = MagicMock()
    fake_session.post = MagicMock(return_value=fake_session_cm)
    fake_outer_cm = AsyncMock()
    fake_outer_cm.__aenter__.return_value = fake_session
    fake_outer_cm.__aexit__.return_value = None

    with patch("aiohttp.ClientSession", return_value=fake_outer_cm) as mock_client_session:
        success, sent = await detector._send_reply_wrapper(
            wecom_service=MagicMock(),
            serial="DEV1",
            user_name="Alice",
            user_channel="WeChat",
            message="hi",
            sidecar_client=client,
        )

    assert success is True
    assert sent == "hi"
    mock_client_session.assert_called_once()


@pytest.mark.asyncio
async def test_still_sending_does_not_direct_send(detector):
    """If Layer 1 says ``still_sending`` we MUST NOT direct-send: the
    queue path may still complete on the device."""
    client = _make_sidecar_client(wait_result={"success": False, "reason": "still_sending"})

    with patch("aiohttp.ClientSession") as mock_session:
        success, sent = await detector._send_reply_wrapper(
            wecom_service=MagicMock(),
            serial="DEV1",
            user_name="Alice",
            user_channel="WeChat",
            message="hi",
            sidecar_client=client,
        )

    assert success is False
    assert sent is None
    mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_failed_does_not_direct_send(detector):
    """A queue-reported send failure must not be retried via direct
    send: the failure could have been mid-flight and a retry would
    duplicate the message."""
    client = _make_sidecar_client(wait_result={"success": False, "reason": "failed", "error": "boom"})

    with patch("aiohttp.ClientSession") as mock_session:
        success, sent = await detector._send_reply_wrapper(
            wecom_service=MagicMock(),
            serial="DEV1",
            user_name="Alice",
            user_channel="WeChat",
            message="hi",
            sidecar_client=client,
        )

    assert success is False
    assert sent is None
    mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_cancelled_does_not_direct_send(detector):
    client = _make_sidecar_client(wait_result={"success": False, "reason": "cancelled"})

    with patch("aiohttp.ClientSession") as mock_session:
        success, sent = await detector._send_reply_wrapper(
            wecom_service=MagicMock(),
            serial="DEV1",
            user_name="Alice",
            user_channel="WeChat",
            message="hi",
            sidecar_client=client,
        )

    assert success is False
    assert sent is None
    mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_expired_does_not_direct_send(detector):
    client = _make_sidecar_client(wait_result={"success": False, "reason": "expired"})

    with patch("aiohttp.ClientSession") as mock_session:
        success, sent = await detector._send_reply_wrapper(
            wecom_service=MagicMock(),
            serial="DEV1",
            user_name="Alice",
            user_channel="WeChat",
            message="hi",
            sidecar_client=client,
        )

    assert success is False
    assert sent is None
    mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_not_found_does_not_direct_send(detector):
    """If the queue lost track of the message, do not retry blindly."""
    client = _make_sidecar_client(wait_result={"success": False, "reason": "not_found"})

    with patch("aiohttp.ClientSession") as mock_session:
        success, sent = await detector._send_reply_wrapper(
            wecom_service=MagicMock(),
            serial="DEV1",
            user_name="Alice",
            user_channel="WeChat",
            message="hi",
            sidecar_client=client,
        )

    assert success is False
    assert sent is None
    mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_set_ready_failure_does_not_direct_send(detector):
    """If we cannot move the message to READY the queue state is
    ambiguous - do not direct-send."""
    client = _make_sidecar_client(set_ready=False)

    with patch("aiohttp.ClientSession") as mock_session:
        success, sent = await detector._send_reply_wrapper(
            wecom_service=MagicMock(),
            serial="DEV1",
            user_name="Alice",
            user_channel="WeChat",
            message="hi",
            sidecar_client=client,
        )

    assert success is False
    assert sent is None
    mock_session.assert_not_called()
    # wait_for_send must not even be called when set_ready failed
    client.wait_for_send.assert_not_called()


@pytest.mark.asyncio
async def test_add_message_failure_does_direct_send(detector):
    """If add_message returns no id the queue never owned the message,
    so direct send is safe and required."""
    client = _make_sidecar_client(add_id=None)

    fake_response = AsyncMock()
    fake_response.status = 200
    fake_response.json = AsyncMock(return_value={"success": True})
    fake_session_cm = AsyncMock()
    fake_session_cm.__aenter__.return_value = fake_response
    fake_session_cm.__aexit__.return_value = None
    fake_session = MagicMock()
    fake_session.post = MagicMock(return_value=fake_session_cm)
    fake_outer_cm = AsyncMock()
    fake_outer_cm.__aenter__.return_value = fake_session
    fake_outer_cm.__aexit__.return_value = None

    with patch("aiohttp.ClientSession", return_value=fake_outer_cm) as mock_client_session:
        success, sent = await detector._send_reply_wrapper(
            wecom_service=MagicMock(),
            serial="DEV1",
            user_name="Alice",
            user_channel="WeChat",
            message="hi",
            sidecar_client=client,
        )

    assert success is True
    assert sent == "hi"
    mock_client_session.assert_called_once()


@pytest.mark.asyncio
async def test_unknown_reason_does_not_direct_send(detector):
    """Defensive: any unknown reason must be conservative."""
    client = _make_sidecar_client(wait_result={"success": False, "reason": "weird-future-reason"})

    with patch("aiohttp.ClientSession") as mock_session:
        success, sent = await detector._send_reply_wrapper(
            wecom_service=MagicMock(),
            serial="DEV1",
            user_name="Alice",
            user_channel="WeChat",
            message="hi",
            sidecar_client=client,
        )

    assert success is False
    assert sent is None
    mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_exception_after_enqueue_does_not_direct_send(detector):
    """If we throw after enqueue (e.g. wait_for_send raises) the queue
    state is unknown, so direct-send would risk a duplicate."""
    client = _make_sidecar_client()
    client.wait_for_send = AsyncMock(side_effect=RuntimeError("network blip"))

    with patch("aiohttp.ClientSession") as mock_session:
        success, sent = await detector._send_reply_wrapper(
            wecom_service=MagicMock(),
            serial="DEV1",
            user_name="Alice",
            user_channel="WeChat",
            message="hi",
            sidecar_client=client,
        )

    assert success is False
    assert sent is None
    mock_session.assert_not_called()
