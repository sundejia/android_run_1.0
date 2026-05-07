"""TDD tests for boss_automation/services/greet/schedule.py."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from boss_automation.services.greet.schedule import (
    GreetSchedule,
    is_within_window,
    weekday_mask_for,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _at(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=SHANGHAI)


class TestWeekdayMaskHelper:
    def test_monday_only(self) -> None:
        # Mon=0
        assert weekday_mask_for([0]) == 0b0000001

    def test_full_week(self) -> None:
        assert weekday_mask_for(range(7)) == 0b1111111

    def test_weekends_only(self) -> None:
        assert weekday_mask_for([5, 6]) == 0b1100000


class TestIsWithinWindowSameDay:
    def test_inside_simple_business_hours(self) -> None:
        sched = GreetSchedule(
            weekday_mask=weekday_mask_for(range(7)),
            start_minute=9 * 60,
            end_minute=18 * 60,
            timezone="Asia/Shanghai",
        )
        # Thursday 2026-05-07 14:30 → inside 09:00-18:00
        assert is_within_window(sched, _at(2026, 5, 7, 14, 30)) is True

    def test_outside_simple_business_hours(self) -> None:
        sched = GreetSchedule(
            weekday_mask=weekday_mask_for(range(7)),
            start_minute=9 * 60,
            end_minute=18 * 60,
            timezone="Asia/Shanghai",
        )
        assert is_within_window(sched, _at(2026, 5, 7, 19, 0)) is False

    def test_blocked_weekday(self) -> None:
        # Mon-Fri only
        sched = GreetSchedule(
            weekday_mask=weekday_mask_for([0, 1, 2, 3, 4]),
            start_minute=9 * 60,
            end_minute=18 * 60,
            timezone="Asia/Shanghai",
        )
        # 2026-05-09 is a Saturday → weekday=5; should be blocked.
        assert is_within_window(sched, _at(2026, 5, 9, 14, 0)) is False


class TestIsWithinWindowCrossMidnight:
    def test_inside_late_night_part(self) -> None:
        # 21:00 → 01:00 next day
        sched = GreetSchedule(
            weekday_mask=weekday_mask_for(range(7)),
            start_minute=21 * 60,
            end_minute=1 * 60,
            timezone="Asia/Shanghai",
        )
        # 22:00 same day, weekday Thursday=3
        assert is_within_window(sched, _at(2026, 5, 7, 22, 0)) is True

    def test_inside_early_morning_part(self) -> None:
        sched = GreetSchedule(
            weekday_mask=weekday_mask_for(range(7)),
            start_minute=21 * 60,
            end_minute=1 * 60,
            timezone="Asia/Shanghai",
        )
        # 00:30 the next morning, weekday Friday=4
        assert is_within_window(sched, _at(2026, 5, 8, 0, 30)) is True

    def test_outside_cross_midnight_window(self) -> None:
        sched = GreetSchedule(
            weekday_mask=weekday_mask_for(range(7)),
            start_minute=21 * 60,
            end_minute=1 * 60,
            timezone="Asia/Shanghai",
        )
        # 14:00 → outside the 21–01 window
        assert is_within_window(sched, _at(2026, 5, 7, 14, 0)) is False

    def test_cross_midnight_respects_weekday_mask_on_late_part(self) -> None:
        # Active only on Mondays
        sched = GreetSchedule(
            weekday_mask=weekday_mask_for([0]),
            start_minute=21 * 60,
            end_minute=1 * 60,
            timezone="Asia/Shanghai",
        )
        # Monday 22:00 → in
        assert is_within_window(sched, _at(2026, 5, 4, 22, 0)) is True
        # Tuesday 22:00 → out
        assert is_within_window(sched, _at(2026, 5, 5, 22, 0)) is False

    def test_cross_midnight_carries_weekday_into_next_day(self) -> None:
        # Active only on Mondays — early-morning Tuesday should still
        # count because the window started on Monday.
        sched = GreetSchedule(
            weekday_mask=weekday_mask_for([0]),
            start_minute=21 * 60,
            end_minute=1 * 60,
            timezone="Asia/Shanghai",
        )
        # 2026-05-05 is a Tuesday, 00:30 belongs to the Monday-night
        # window that started at 21:00.
        assert is_within_window(sched, _at(2026, 5, 5, 0, 30)) is True
