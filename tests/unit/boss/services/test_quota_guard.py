"""TDD tests for boss_automation/services/greet/quota_guard.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from boss_automation.services.greet.quota_guard import (
    GreetQuota,
    QuotaDecision,
    QuotaGuard,
)


class _FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def utcnow(self) -> datetime:
        return self.now


class TestGreetQuota:
    def test_immutable(self) -> None:
        from dataclasses import FrozenInstanceError

        q = GreetQuota(per_day=80, per_hour=15)
        with pytest.raises((AttributeError, FrozenInstanceError)):
            q.per_day = 100  # type: ignore[misc]


class TestQuotaGuard:
    @pytest.fixture()
    def now(self) -> datetime:
        return datetime(2026, 5, 7, 14, 30, tzinfo=UTC)

    def test_allows_when_no_history(self, now: datetime) -> None:
        guard = QuotaGuard(GreetQuota(per_day=80, per_hour=15), clock=_FakeClock(now).utcnow)
        decision = guard.check(recent_send_times=[])
        assert decision == QuotaDecision.ALLOWED

    def test_blocks_per_hour_cap(self, now: datetime) -> None:
        guard = QuotaGuard(GreetQuota(per_day=80, per_hour=3), clock=_FakeClock(now).utcnow)
        recent = [now - timedelta(minutes=i * 5) for i in range(3)]
        decision = guard.check(recent_send_times=recent)
        assert decision == QuotaDecision.BLOCKED_HOUR

    def test_blocks_per_day_cap(self, now: datetime) -> None:
        guard = QuotaGuard(GreetQuota(per_day=2, per_hour=15), clock=_FakeClock(now).utcnow)
        # Two sends earlier today (more than an hour ago)
        recent = [now - timedelta(hours=h) for h in (3, 5)]
        decision = guard.check(recent_send_times=recent)
        assert decision == QuotaDecision.BLOCKED_DAY

    def test_per_job_cap_blocks_when_exceeded(self, now: datetime) -> None:
        guard = QuotaGuard(
            GreetQuota(per_day=80, per_hour=15, per_job=1),
            clock=_FakeClock(now).utcnow,
        )
        decision = guard.check(
            recent_send_times=[now - timedelta(hours=2)],
            recent_per_job=1,
        )
        assert decision == QuotaDecision.BLOCKED_JOB

    def test_per_job_cap_none_means_unlimited(self, now: datetime) -> None:
        guard = QuotaGuard(
            GreetQuota(per_day=80, per_hour=15),
            clock=_FakeClock(now).utcnow,
        )
        decision = guard.check(
            recent_send_times=[],
            recent_per_job=999,
        )
        assert decision == QuotaDecision.ALLOWED

    def test_old_sends_outside_hour_window_do_not_count_against_hour(self, now: datetime) -> None:
        guard = QuotaGuard(GreetQuota(per_day=80, per_hour=2), clock=_FakeClock(now).utcnow)
        recent = [
            now - timedelta(minutes=10),
            now - timedelta(hours=2),
            now - timedelta(hours=3),
        ]
        decision = guard.check(recent_send_times=recent)
        assert decision == QuotaDecision.ALLOWED

    def test_old_sends_outside_day_window_do_not_count_against_day(self, now: datetime) -> None:
        guard = QuotaGuard(GreetQuota(per_day=2, per_hour=15), clock=_FakeClock(now).utcnow)
        recent = [
            now - timedelta(days=2),
            now - timedelta(days=3),
        ]
        decision = guard.check(recent_send_times=recent)
        assert decision == QuotaDecision.ALLOWED

    def test_decision_priority_hour_beats_day(self, now: datetime) -> None:
        # Both day and hour exceeded → hour reported first since the
        # operator can wait an hour but cannot easily wait until tomorrow.
        guard = QuotaGuard(GreetQuota(per_day=2, per_hour=2), clock=_FakeClock(now).utcnow)
        recent = [now - timedelta(minutes=10), now - timedelta(minutes=20)]
        decision = guard.check(recent_send_times=recent)
        assert decision == QuotaDecision.BLOCKED_HOUR
