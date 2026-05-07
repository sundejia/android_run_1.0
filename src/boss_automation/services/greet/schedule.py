"""Time-window scheduling for greet executor.

A ``GreetSchedule`` defines an allowed weekly window using a 7-bit
weekday mask and start/end minutes. ``end_minute < start_minute``
indicates a cross-midnight window (e.g. ``21:00`` → ``01:00``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def weekday_mask_for(weekdays: Iterable[int]) -> int:
    """Return a 7-bit mask where bit 0 = Monday … bit 6 = Sunday."""
    mask = 0
    for w in weekdays:
        if not 0 <= w <= 6:
            raise ValueError(f"weekday must be 0..6, got {w}")
        mask |= 1 << w
    return mask


@dataclass(frozen=True, slots=True)
class GreetSchedule:
    weekday_mask: int
    start_minute: int
    end_minute: int
    timezone: str = "Asia/Shanghai"

    def __post_init__(self) -> None:
        if not 0 <= self.start_minute < 1440:
            raise ValueError("start_minute must be in [0, 1440)")
        if not 0 <= self.end_minute < 1440:
            raise ValueError("end_minute must be in [0, 1440)")


def _weekday_active(mask: int, weekday: int) -> bool:
    return bool(mask & (1 << weekday))


def is_within_window(schedule: GreetSchedule, when: datetime) -> bool:
    tz = ZoneInfo(schedule.timezone)
    local = when.astimezone(tz)
    weekday = local.weekday()
    minute_of_day = local.hour * 60 + local.minute

    if schedule.start_minute <= schedule.end_minute:
        # Same-day window.
        if not _weekday_active(schedule.weekday_mask, weekday):
            return False
        return schedule.start_minute <= minute_of_day < schedule.end_minute

    # Cross-midnight window: split into two sub-windows.
    # Late part: [start_minute, 1440) belongs to ``weekday``.
    if minute_of_day >= schedule.start_minute and _weekday_active(schedule.weekday_mask, weekday):
        return True
    # Early part: [0, end_minute) belongs to ``weekday - 1``
    # (whose start_minute fired the day before).
    if minute_of_day < schedule.end_minute:
        prior_weekday = (local - timedelta(days=1)).weekday()
        if _weekday_active(schedule.weekday_mask, prior_weekday):
            return True
    return False
