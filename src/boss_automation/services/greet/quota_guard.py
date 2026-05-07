"""Quota guard for the greet executor.

Holds three caps (day, hour, optional per-job) and decides whether a
new greet send should proceed. Caller is expected to provide recent
send timestamps; the guard does not own its own DB connection — that
keeps it cheap to test and safe to share across processes.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class QuotaDecision(StrEnum):
    ALLOWED = "allowed"
    BLOCKED_HOUR = "blocked_hour"
    BLOCKED_DAY = "blocked_day"
    BLOCKED_JOB = "blocked_job"


@dataclass(frozen=True, slots=True)
class GreetQuota:
    per_day: int = 80
    per_hour: int = 15
    per_job: int | None = None


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class QuotaGuard:
    def __init__(
        self,
        quota: GreetQuota,
        *,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._quota = quota
        self._clock = clock

    def check(
        self,
        *,
        recent_send_times: Sequence[datetime],
        recent_per_job: int | None = None,
    ) -> QuotaDecision:
        now = self._clock()
        hour_threshold = now - timedelta(hours=1)
        day_threshold = now - timedelta(hours=24)

        in_last_hour = sum(1 for t in recent_send_times if t >= hour_threshold)
        in_last_day = sum(1 for t in recent_send_times if t >= day_threshold)

        if in_last_hour >= self._quota.per_hour:
            return QuotaDecision.BLOCKED_HOUR
        if in_last_day >= self._quota.per_day:
            return QuotaDecision.BLOCKED_DAY
        if self._quota.per_job is not None and recent_per_job is not None and recent_per_job >= self._quota.per_job:
            return QuotaDecision.BLOCKED_JOB
        return QuotaDecision.ALLOWED
