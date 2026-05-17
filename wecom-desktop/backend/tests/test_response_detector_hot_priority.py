"""Regression tests for hot-chat priority in the red-dot queue.

After refactoring ``_scan_device_for_responses`` to use a two-tier queue
(``hot_queue`` for already-chatted users, ``cold_queue`` for first-time
users), these tests verify:

1. A user who already chatted and then replied (reprocess) is processed
   before any new stranger detected in the same re-scan.
2. A hot user arriving in a later re-scan still beats a cold user that
   was already queued from a previous re-scan.
3. When no users reply (no reprocess), the original FIFO order is kept.

Usage:
    pytest wecom-desktop/backend/tests/test_response_detector_hot_priority.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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


SERIAL = "TESTDEVICE_HOT"


def _build_detector():
    from services.followup.response_detector import ResponseDetector

    return ResponseDetector(repository=MagicMock(), settings_manager=MagicMock())


def _make_user(name: str, *, unread: int = 1):
    def is_priority() -> bool:
        return unread > 0

    return SimpleNamespace(
        name=name,
        message_preview="...",
        unread_count=unread,
        is_new_friend=False,
        is_priority=is_priority,
        channel=None,
    )


async def _run_scan_with_scripted_redetections(
    detector,
    initial_users: list,
    redetections: list[list],
) -> list[str]:
    """Drive ``_scan_device_for_responses`` with scripted re-detection results.

    ``redetections`` is a list where each element is the list of users returned
    by ``_detect_first_page_unread`` after the Nth user is processed.  When the
    list is exhausted, subsequent calls return [].

    Returns the names of users in the order they were processed (i.e. passed to
    ``_process_unread_user_with_wait``).
    """
    processed_order: list[str] = []
    redetect_iter = iter(redetections)

    async def fake_process(wecom, serial, user, timeout, *, sidecar_client=None):
        processed_order.append(user.name)
        return {"skipped": False, "reply_sent": False, "messages_stored": 0}

    async def fake_detect(wecom, serial):
        return next(redetect_iter, [])

    fake_wecom = MagicMock()
    fake_wecom.launch_wecom = AsyncMock()
    fake_wecom.switch_to_private_chats = AsyncMock()
    fake_wecom.adb = MagicMock()
    fake_wecom.adb.scroll_to_top = AsyncMock()
    fake_wecom.get_current_screen = AsyncMock(return_value="private_chats")
    fake_wecom.ensure_on_private_chats = AsyncMock(return_value=True)
    fake_wecom.go_back = AsyncMock()

    detector._detect_first_page_unread = AsyncMock(side_effect=[initial_users] + redetections + [[]])
    detector._process_unread_user_with_wait = AsyncMock(side_effect=fake_process)
    detector._init_media_event_bus = AsyncMock()
    detector._try_followup_if_idle = AsyncMock()
    detector._emit_dash_event = MagicMock()

    import wecom_automation.services.wecom_service as ws_mod

    original_wecom = ws_mod.WeComService
    ws_mod.WeComService = MagicMock(return_value=fake_wecom)
    try:
        await detector._scan_device_for_responses(SERIAL, interactive_wait_timeout=10)
    finally:
        ws_mod.WeComService = original_wecom

    return processed_order


# ---------------------------------------------------------------------------
# 1. Reprocess (hot) wins over new stranger (cold) in the same re-scan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reprocess_wins_over_new_stranger_same_cycle():
    """After processing P1 and P2, if P1 replies (reprocess) and P4 is a new
    stranger in the same re-detection, P1 must be processed before P4."""
    detector = _build_detector()

    p1 = _make_user("P1")
    p2 = _make_user("P2")
    p3 = _make_user("P3")
    p4 = _make_user("P4")

    initial = [p1, p2, p3]
    redetections = [
        [],  # after P1: nothing new
        [p1, p4],  # after P2: P1 replied again + P4 is new
        [],  # after P1 (reprocess): nothing new
        [],  # after P4: nothing new
        [],  # after P3: nothing new
    ]

    order = await _run_scan_with_scripted_redetections(detector, initial, redetections)
    assert order == ["P1", "P2", "P1", "P4", "P3"]


# ---------------------------------------------------------------------------
# 2. Existing cold user doesn't jump over a later-arriving hot user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_existing_cold_does_not_jump_over_returning_hot():
    """cold_queue already has P3 waiting. A re-scan after processing P2 reveals
    that P1 (already chatted) replied. P1 must be processed before P3, even
    though P3 was queued earlier."""
    detector = _build_detector()

    p1 = _make_user("P1")
    p2 = _make_user("P2")
    p3 = _make_user("P3")

    initial = [p1, p2, p3]
    redetections = [
        [],  # after P1: nothing
        [p1],  # after P2: P1 replied (hot), P3 still in cold_queue
        [],  # after P1 (reprocess): nothing
        [],  # after P3: nothing
    ]

    order = await _run_scan_with_scripted_redetections(detector, initial, redetections)
    assert order == ["P1", "P2", "P1", "P3"]


# ---------------------------------------------------------------------------
# 3. Pure FIFO when no replies (no regression)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_regression_pure_fifo_when_no_replies():
    """When no processed user replies, the order should be the original
    initial_unread order (FIFO from the cold_queue)."""
    detector = _build_detector()

    p1 = _make_user("P1")
    p2 = _make_user("P2")
    p3 = _make_user("P3")

    initial = [p1, p2, p3]
    redetections = [
        [],  # after P1
        [],  # after P2
        [],  # after P3
    ]

    order = await _run_scan_with_scripted_redetections(detector, initial, redetections)
    assert order == ["P1", "P2", "P3"]


# ---------------------------------------------------------------------------
# 4. Multiple hot users preserve detection order among themselves
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_hot_users_keep_detection_order():
    """When two previously-chatted users both reply at the same time, they
    should be processed in their detection order (the order returned by
    _detect_first_page_unread), before any cold users."""
    detector = _build_detector()

    p1 = _make_user("P1")
    p2 = _make_user("P2")
    p3 = _make_user("P3")
    p4 = _make_user("P4")

    initial = [p1, p2, p3, p4]
    redetections = [
        [],  # after P1
        [],  # after P2
        [p1, p2],  # after P3: both P1 and P2 replied
        [],  # after P1 (hot)
        [],  # after P2 (hot)
        [],  # after P4
    ]

    order = await _run_scan_with_scripted_redetections(detector, initial, redetections)
    assert order == ["P1", "P2", "P3", "P1", "P2", "P4"]
