"""Tests for the governance ``ExecutionPolicyGuard`` (M9).

The guard sits in front of every side-effecting action (group invite, etc.).
It enforces:
    * ``governance.kill_switch`` — global stop-all flag.
    * ``governance.invite_rate_limit_seconds`` — minimum gap between two
      invites for the same device.
    * Every decision (allowed or blocked) is mirrored to ``analytics_events``
      so operators have an auditable trail.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wecom_automation.database.schema import init_database
from wecom_automation.services.governance.guard import (
    ExecutionPolicyGuard,
    GovernanceAction,
    GuardOutcome,
)
from wecom_automation.services.review.storage import ReviewStorage


@pytest.fixture()
def storage(tmp_path: Path) -> ReviewStorage:
    db = tmp_path / "android.db"
    init_database(str(db), force_recreate=True)
    return ReviewStorage(str(db))


def _settings(*, kill_switch: bool = False, rate_seconds: int = 60) -> dict:
    return {
        "governance": {
            "kill_switch": kill_switch,
            "invite_rate_limit_seconds": rate_seconds,
        }
    }


class TestKillSwitch:
    def test_kill_switch_blocks(self, storage: ReviewStorage) -> None:
        guard = ExecutionPolicyGuard(storage=storage)
        decision = guard.check(
            action=GovernanceAction.GROUP_INVITE,
            device_serial="dev-1",
            settings=_settings(kill_switch=True),
            trace_id="100",
        )
        assert decision.outcome == GuardOutcome.BLOCKED
        assert decision.reason == "kill_switch"

        events = storage.list_events(trace_id="100")
        assert any(e.event_type == "governance.blocked" for e in events)

    def test_kill_switch_off_allows(self, storage: ReviewStorage) -> None:
        guard = ExecutionPolicyGuard(storage=storage)
        decision = guard.check(
            action=GovernanceAction.GROUP_INVITE,
            device_serial="dev-1",
            settings=_settings(kill_switch=False),
            trace_id="101",
        )
        assert decision.outcome == GuardOutcome.ALLOWED


class TestRateLimit:
    def test_first_call_allowed(self, storage: ReviewStorage) -> None:
        guard = ExecutionPolicyGuard(storage=storage)
        d = guard.check(
            action=GovernanceAction.GROUP_INVITE,
            device_serial="dev-1",
            settings=_settings(rate_seconds=60),
            trace_id="200",
        )
        assert d.outcome == GuardOutcome.ALLOWED

    def test_second_within_window_blocked(self, storage: ReviewStorage) -> None:
        guard = ExecutionPolicyGuard(storage=storage)
        guard.check(
            action=GovernanceAction.GROUP_INVITE,
            device_serial="dev-1",
            settings=_settings(rate_seconds=60),
            trace_id="201",
        )
        d2 = guard.check(
            action=GovernanceAction.GROUP_INVITE,
            device_serial="dev-1",
            settings=_settings(rate_seconds=60),
            trace_id="202",
        )
        assert d2.outcome == GuardOutcome.BLOCKED
        assert d2.reason == "rate_limit"
        events = storage.list_events(event_type="governance.blocked")
        assert any(e.trace_id == "202" for e in events)

    def test_different_devices_independent(self, storage: ReviewStorage) -> None:
        guard = ExecutionPolicyGuard(storage=storage)
        a = guard.check(
            action=GovernanceAction.GROUP_INVITE,
            device_serial="dev-A",
            settings=_settings(rate_seconds=60),
            trace_id="300",
        )
        b = guard.check(
            action=GovernanceAction.GROUP_INVITE,
            device_serial="dev-B",
            settings=_settings(rate_seconds=60),
            trace_id="301",
        )
        assert a.outcome == GuardOutcome.ALLOWED
        assert b.outcome == GuardOutcome.ALLOWED

    def test_after_window_allowed_again(self, storage: ReviewStorage) -> None:
        clock = [0.0]

        def fake_now() -> float:
            return clock[0]

        guard = ExecutionPolicyGuard(storage=storage, clock=fake_now)
        d1 = guard.check(
            action=GovernanceAction.GROUP_INVITE,
            device_serial="dev-1",
            settings=_settings(rate_seconds=10),
            trace_id="400",
        )
        assert d1.outcome == GuardOutcome.ALLOWED
        clock[0] = 5.0
        d2 = guard.check(
            action=GovernanceAction.GROUP_INVITE,
            device_serial="dev-1",
            settings=_settings(rate_seconds=10),
            trace_id="401",
        )
        assert d2.outcome == GuardOutcome.BLOCKED
        clock[0] = 11.0
        d3 = guard.check(
            action=GovernanceAction.GROUP_INVITE,
            device_serial="dev-1",
            settings=_settings(rate_seconds=10),
            trace_id="402",
        )
        assert d3.outcome == GuardOutcome.ALLOWED


class TestAudit:
    def test_allowed_decision_audited(self, storage: ReviewStorage) -> None:
        guard = ExecutionPolicyGuard(storage=storage)
        guard.check(
            action=GovernanceAction.GROUP_INVITE,
            device_serial="dev-1",
            settings=_settings(),
            trace_id="500",
        )
        events = storage.list_events(trace_id="500")
        assert any(e.event_type == "governance.allowed" for e in events)
