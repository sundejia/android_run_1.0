"""Regression tests for ``ResponseDetector`` click-cooldown / day-level blocklist.

Background: on 2026-05-09 a single customer (`B2605080143-(保底正常)`) was falsely
flagged as a new friend by the over-broad keyword `"感谢您"`. The same customer
was added to ``priority_users`` every scan, each click failed, a 120-600s
cooldown was set, and 10 minutes later the cycle started again. This burned
5.5 hours of capacity.

P1 (separate test file) fixes the keyword. **P2 (this file)** guarantees that
even if some new false-positive scenario sneaks in, no single customer can
dominate the queue for more than ``_click_dayblock_threshold`` click failures
in a single day.

Usage:
    pytest wecom-desktop/backend/tests/test_response_detector_click_dayblock.py -v

See docs/04-bugs-and-fixes/resolved/2026-05-12-new-friend-false-positive-click-loop.md
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
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


SERIAL = "TESTDEVICE1234"
STUCK_USER = "B2605080143-(保底正常)"
OTHER_USER = "B2605080144-(保底正常)"


def _build_detector():
    from services.followup.response_detector import ResponseDetector

    return ResponseDetector(repository=MagicMock(), settings_manager=MagicMock())


def _make_priority_user(name: str, *, unread: int = 0, new_friend: bool = True):
    """Stand-in for ``UnreadUserInfo`` — only the attributes that
    ``_detect_first_page_unread`` reads."""

    def is_priority() -> bool:  # pragma: no cover - trivial
        return unread > 0 or new_friend

    return SimpleNamespace(
        name=name,
        message_preview="...",
        unread_count=unread,
        is_new_friend=new_friend,
        is_priority=is_priority,
        channel=None,
    )


def _stub_ui_tree(monkeypatch, users):
    """Patch the UI tree -> ``UnreadUserExtractor.extract_from_tree`` flow so
    ``_detect_first_page_unread`` returns the given list of priority users."""

    async def _get_ui_state():
        return ({"dummy_tree": True}, None)

    fake_adb = SimpleNamespace(get_ui_state=_get_ui_state)
    fake_wecom = SimpleNamespace(adb=fake_adb)

    import wecom_automation.services.sync_service as sync_service_module

    fake_extractor = MagicMock()
    fake_extractor.extract_from_tree = MagicMock(return_value=users)
    monkeypatch.setattr(sync_service_module, "UnreadUserExtractor", fake_extractor)

    return fake_wecom


# ---------------------------------------------------------------------------
# 1. Cooldown threshold escalates to dayblock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cooldown_escalates_to_dayblock_after_threshold_failures():
    import time as _time

    detector = _build_detector()
    key = f"{SERIAL}:{STUCK_USER}"

    # Simulate N-1 consecutive failures already recorded. We pre-load a cooldown
    # that has just expired (so the early-return cooldown check passes) and
    # patch ``_clean_expired_click_cooldowns`` so the cleanup pass does not
    # blow away our pre-loaded fail count before the failure path reads it.
    threshold = detector._click_dayblock_threshold
    detector._click_fail_cooldown[key] = (_time.time() - 1.0, threshold - 1)
    assert key not in detector._click_dayblock

    # Build a minimal wecom stub that always fails click.
    wecom = MagicMock()
    wecom.click_user_in_list = AsyncMock(return_value=False)

    user = _make_priority_user(STUCK_USER, unread=0, new_friend=True)

    with patch.object(detector, "_clean_expired_click_cooldowns", return_value=None), patch(
        "wecom_automation.services.blacklist_service.BlacklistChecker.is_blacklisted",
        return_value=False,
    ), patch(
        "wecom_automation.services.blacklist_service.BlacklistWriter"
    ) as MockWriter:
        MockWriter.return_value.ensure_user_in_blacklist_table = MagicMock()

        result = await detector._process_unread_user_with_wait(
            wecom=wecom,
            serial=SERIAL,
            unread_user=user,
            interactive_wait_timeout=1,
            sidecar_client=None,
        )

    assert result["reply_sent"] is False
    fail_count = detector._click_fail_cooldown[key][1]
    assert fail_count == threshold, f"expected fail_count={threshold}, got {fail_count}"
    assert key in detector._click_dayblock, (
        "After hitting the threshold, the customer MUST be added to _click_dayblock "
        "so the next priority scan drops them at detection time."
    )


@pytest.mark.asyncio
async def test_cooldown_below_threshold_does_not_dayblock():
    """A customer with fewer than ``threshold`` failures must NOT be dayblocked
    yet — premature dayblocking would block legitimate retries for transient
    UI glitches."""
    import time as _time

    detector = _build_detector()
    key = f"{SERIAL}:{STUCK_USER}"
    threshold = detector._click_dayblock_threshold
    detector._click_fail_cooldown[key] = (_time.time() - 1.0, threshold - 3)

    wecom = MagicMock()
    wecom.click_user_in_list = AsyncMock(return_value=False)
    user = _make_priority_user(STUCK_USER, unread=0, new_friend=True)

    with patch.object(detector, "_clean_expired_click_cooldowns", return_value=None), patch(
        "wecom_automation.services.blacklist_service.BlacklistChecker.is_blacklisted",
        return_value=False,
    ), patch(
        "wecom_automation.services.blacklist_service.BlacklistWriter"
    ) as MockWriter:
        MockWriter.return_value.ensure_user_in_blacklist_table = MagicMock()

        await detector._process_unread_user_with_wait(
            wecom=wecom,
            serial=SERIAL,
            unread_user=user,
            interactive_wait_timeout=1,
            sidecar_client=None,
        )

    fail_count = detector._click_fail_cooldown[key][1]
    assert fail_count == threshold - 2
    assert key not in detector._click_dayblock


# ---------------------------------------------------------------------------
# 2. Priority detection filters dayblocked customers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_first_page_unread_filters_dayblocked_customer(monkeypatch):
    detector = _build_detector()

    # Pre-populate dayblock for the stuck user.
    detector._click_dayblock.add(f"{SERIAL}:{STUCK_USER}")

    # Both users are priority candidates from the raw UI extraction.
    users = [
        _make_priority_user(STUCK_USER, unread=0, new_friend=True),
        _make_priority_user(OTHER_USER, unread=2, new_friend=False),
    ]
    wecom = _stub_ui_tree(monkeypatch, users)

    priority_users = await detector._detect_first_page_unread(wecom, SERIAL)

    names = [u.name for u in priority_users]
    assert STUCK_USER not in names, (
        "Dayblocked customer leaked through priority detection — the queue "
        "will get jammed again."
    )
    assert OTHER_USER in names, "Non-blocked customer must still flow through."


# ---------------------------------------------------------------------------
# 3. Dayblock is scoped per (serial, user) and does not leak across devices
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dayblock_is_scoped_per_serial(monkeypatch):
    detector = _build_detector()
    other_serial = "OTHER_DEVICE_9999"

    # User is dayblocked on SERIAL only.
    detector._click_dayblock.add(f"{SERIAL}:{STUCK_USER}")

    # Same name appears on a different device.
    users = [_make_priority_user(STUCK_USER, unread=2, new_friend=False)]
    wecom = _stub_ui_tree(monkeypatch, users)

    priority_on_other = await detector._detect_first_page_unread(wecom, other_serial)
    assert [u.name for u in priority_on_other] == [STUCK_USER], (
        "Dayblock must be keyed on (serial, name); a block on device A must not "
        "affect device B."
    )


# ---------------------------------------------------------------------------
# 4. Day rollover clears the dayblock
# ---------------------------------------------------------------------------


def test_day_rollover_clears_dayblock():
    detector = _build_detector()
    detector._click_dayblock.add(f"{SERIAL}:{STUCK_USER}")
    detector._click_dayblock_day = "1970-01-01"  # force "yesterday"

    detector._maybe_reset_click_dayblock()

    assert detector._click_dayblock == set(), (
        "Day rollover must clear yesterday's dayblock so legitimate retries "
        "are possible on the new day."
    )
    assert detector._click_dayblock_day != "1970-01-01"


# ---------------------------------------------------------------------------
# 5. Same-day call does NOT clear the dayblock
# ---------------------------------------------------------------------------


def test_same_day_call_keeps_dayblock_intact():
    detector = _build_detector()
    detector._click_dayblock.add(f"{SERIAL}:{STUCK_USER}")
    before = set(detector._click_dayblock)
    before_day = detector._click_dayblock_day

    detector._maybe_reset_click_dayblock()  # day unchanged

    assert detector._click_dayblock == before
    assert detector._click_dayblock_day == before_day


# ---------------------------------------------------------------------------
# 6. Successful click clears cooldown but keeps the dayblock entry
# ---------------------------------------------------------------------------


def test_dayblock_survives_cooldown_expiry():
    """If cooldown expires (10min) but the customer was already dayblocked,
    they MUST stay dayblocked for the rest of the day."""
    detector = _build_detector()
    key = f"{SERIAL}:{STUCK_USER}"
    detector._click_dayblock.add(key)
    detector._click_fail_cooldown[key] = (0.0, 5)  # already expired

    detector._clean_expired_click_cooldowns()

    assert key not in detector._click_fail_cooldown, "Expired cooldown should be cleared"
    assert key in detector._click_dayblock, (
        "Dayblock must outlive cooldown expiry — the latter is short-term, "
        "the former is the daily guardrail."
    )


# ---------------------------------------------------------------------------
# 7. Health snapshot exposes dayblock and active cooldown counts
# ---------------------------------------------------------------------------


def test_get_click_health_snapshot_returns_expected_shape():
    detector = _build_detector()
    detector._click_dayblock.add(f"{SERIAL}:{STUCK_USER}")
    # Set a far-future cooldown so the snapshot counts it as active.
    import time as _time

    detector._click_fail_cooldown[f"{SERIAL}:{OTHER_USER}"] = (_time.time() + 3600, 2)

    snap = detector.get_click_health_snapshot()
    assert snap["dayblock_size"] == 1
    assert f"{SERIAL}:{STUCK_USER}" in snap["dayblock_keys"]
    assert snap["active_cooldown_count"] == 1
    assert snap["active_cooldowns"][0]["fail_count"] == 2
    assert snap["active_cooldowns"][0]["retry_in_seconds"] > 0
    assert "unique_customers_clicked" in snap
    assert "priority_queue_repeats" in snap


# ---------------------------------------------------------------------------
# 8. Replay regression — 2026-05-09 priority-queue death loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_2026_05_09_repeated_priority_caps_at_five(monkeypatch):
    """Replay the failure mode that burned 5.5h on 2026-05-09.

    Before P1+P2, the same customer was re-detected as a priority user every
    scan, each click failed, and the cooldown only suppressed processing —
    not detection — so the bad row stayed in the queue.

    After the fix, the customer is added to ``_click_dayblock`` once they hit
    ``_click_dayblock_threshold`` consecutive failures, and from then on
    ``_detect_first_page_unread`` drops them. The acceptance criterion from
    the plan: **same customer is processed by ``_process_unread_user_with_wait``
    no more than ``threshold`` times in one day**.
    """
    import time as _time

    detector = _build_detector()
    threshold = detector._click_dayblock_threshold

    user = _make_priority_user(STUCK_USER, unread=0, new_friend=True)

    # Stub the wecom layer so click ALWAYS fails (the original UI-mismatch).
    wecom = MagicMock()
    wecom.click_user_in_list = AsyncMock(return_value=False)

    # Stub the priority-detection upstream so the customer keeps reappearing
    # on the first page (the original false-positive).
    wecom_for_detect = _stub_ui_tree(monkeypatch, [user])

    process_invocations = 0

    async def _no_op_blacklist_check(*_a, **_kw):
        return False

    with patch(
        "wecom_automation.services.blacklist_service.BlacklistChecker.is_blacklisted",
        return_value=False,
    ), patch(
        "wecom_automation.services.blacklist_service.BlacklistWriter"
    ) as MockWriter:
        MockWriter.return_value.ensure_user_in_blacklist_table = MagicMock()

        # Simulate many scan cycles. Force-expire any cooldown before each
        # process call so the failure path counter advances every cycle
        # (mirrors what happens after a 600s wait in real life).
        for cycle in range(threshold + 10):  # well past the threshold
            priority_users = await detector._detect_first_page_unread(
                wecom_for_detect, SERIAL
            )
            if not priority_users:
                # Dayblock has kicked in — the queue is empty for this user.
                continue

            for u in priority_users:
                cooldown_key = f"{SERIAL}:{u.name}"
                if cooldown_key in detector._click_fail_cooldown:
                    until, count = detector._click_fail_cooldown[cooldown_key]
                    detector._click_fail_cooldown[cooldown_key] = (_time.time() - 1, count)

                with patch.object(detector, "_clean_expired_click_cooldowns", return_value=None):
                    await detector._process_unread_user_with_wait(
                        wecom=wecom,
                        serial=SERIAL,
                        unread_user=u,
                        interactive_wait_timeout=1,
                        sidecar_client=None,
                    )
                process_invocations += 1

    assert process_invocations <= threshold, (
        f"Same customer was processed {process_invocations} times — must be "
        f"≤ {threshold}. Dayblock did not kick in fast enough; the death-loop "
        f"would still consume capacity."
    )
    assert f"{SERIAL}:{STUCK_USER}" in detector._click_dayblock
