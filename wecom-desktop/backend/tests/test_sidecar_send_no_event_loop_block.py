"""Regression test for the multi-device sidecar send halt.

Covers Bug B1 from the "three devices serialize" handoff: the synchronous
``BlacklistChecker.is_blacklisted(use_cache=False)`` call inside
``routers/sidecar.py:_ensure_contact_not_blacklisted`` used to run on the
FastAPI event-loop thread, stalling every other device's HTTP/WebSocket
traffic for the duration of the SQLite query.

The fix wraps the blocking call with ``asyncio.to_thread`` so it runs on a
worker thread. This test pins that behavior in place: if a future change
removes the ``to_thread`` wrap, three concurrent gate calls will once again
serialize and this test will fail.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
sys.path.insert(0, str(backend_dir.parent.parent / "src"))

# Mock droidrun before importing the routers (matches existing test patterns).
mock_droidrun = MagicMock()
mock_droidrun.AdbTools = MagicMock()
mock_droidrun.tools = MagicMock()
mock_droidrun.tools.adb = MagicMock()
mock_droidrun.tools.adb.AdbTools = MagicMock()
sys.modules.setdefault("droidrun", mock_droidrun)
sys.modules.setdefault("droidrun.tools", mock_droidrun.tools)
sys.modules.setdefault("droidrun.tools.adb", mock_droidrun.tools.adb)

from routers import sidecar  # noqa: E402


SLOW_QUERY_SECONDS = 0.5
DEVICE_COUNT = 3
# Threshold is generous: serialized would be N * SLOW (1.5 s);
# concurrent with to_thread should land well under that. We give plenty of
# headroom for slow CI machines while still catching regressions.
SERIAL_BUDGET = SLOW_QUERY_SECONDS * DEVICE_COUNT
CONCURRENT_BUDGET = SLOW_QUERY_SECONDS + 0.5  # 1 slow query + scheduler overhead


def _slow_blocking_check(*_args, **_kwargs) -> bool:
    """Simulate a slow blocking SQLite query (e.g. lock contention)."""
    time.sleep(SLOW_QUERY_SECONDS)
    return False  # not blacklisted -> gate returns without raising 409


@pytest.mark.asyncio
async def test_blacklist_gate_does_not_block_event_loop() -> None:
    """Three concurrent gate checks must NOT serialize.

    ``_ensure_contact_not_blacklisted`` resolves the blacklist via
    ``asyncio.to_thread(BlacklistChecker.is_blacklisted, ...)``. With the
    fix in place, three concurrent calls overlap on worker threads. Without
    the fix, they would run sequentially on the event loop and take
    ~``DEVICE_COUNT * SLOW_QUERY_SECONDS`` seconds.
    """
    sessions = [MagicMock() for _ in range(DEVICE_COUNT)]
    for sess in sessions:
        sess.snapshot = AsyncMock(return_value=MagicMock(conversation=None))

    with patch(
        "routers.sidecar.BlacklistChecker.is_blacklisted",
        side_effect=_slow_blocking_check,
    ):
        start = time.monotonic()
        await asyncio.gather(
            *(
                sidecar._ensure_contact_not_blacklisted(
                    f"serial-{i}",
                    contact_name=f"customer-{i}",
                    channel="@WeChat",
                    session=sessions[i],
                )
                for i in range(DEVICE_COUNT)
            )
        )
        elapsed = time.monotonic() - start

    assert elapsed < CONCURRENT_BUDGET, (
        f"Blacklist gate appears to be serializing on the event loop: "
        f"elapsed={elapsed:.2f}s, expected < {CONCURRENT_BUDGET:.2f}s. "
        f"Did someone remove the asyncio.to_thread wrap in "
        f"_ensure_contact_not_blacklisted?"
    )
    assert elapsed < SERIAL_BUDGET, (
        f"Concurrent gate calls took {elapsed:.2f}s — serialization detected."
    )


@pytest.mark.asyncio
async def test_blacklist_gate_still_raises_409_when_blocked() -> None:
    """The to_thread wrap must preserve the 409 fail-closed behavior."""
    from fastapi import HTTPException

    session = MagicMock()
    session.snapshot = AsyncMock(return_value=MagicMock(conversation=None))

    with patch(
        "routers.sidecar.BlacklistChecker.is_blacklisted",
        return_value=True,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await sidecar._ensure_contact_not_blacklisted(
                "serial-X",
                contact_name="BlockedUser",
                channel="@WeChat",
                session=session,
            )

    assert exc_info.value.status_code == 409
    assert "BlockedUser" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_blacklist_gate_skips_when_no_resolved_name() -> None:
    """If no contact name can be resolved, the gate must short-circuit
    without ever calling ``is_blacklisted``."""
    session = MagicMock()
    session.snapshot = AsyncMock(return_value=MagicMock(conversation=None))

    with patch(
        "routers.sidecar.BlacklistChecker.is_blacklisted",
    ) as mock_check:
        await sidecar._ensure_contact_not_blacklisted(
            "serial-X",
            contact_name=None,
            channel=None,
            session=session,
        )

    mock_check.assert_not_called()
