"""Tests for the timestamp parser module."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from wecom_automation.services.timestamp_parser import (
    TimestampContext,
    TimestampParser,
    parse_wecom_timestamp,
)


@pytest.fixture
def parser():
    """Create a parser with Asia/Shanghai timezone."""
    return TimestampParser(timezone="Asia/Shanghai")


@pytest.fixture
def fixed_reference_time():
    """A fixed reference time for consistent testing: Wednesday Dec 10, 2025 8:30 PM."""
    return datetime(2025, 12, 10, 20, 30, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


class TestTimestampParser:
    """Tests for TimestampParser class."""

    def test_parse_time_only_pm(self, parser, fixed_reference_time):
        """Test parsing PM time (today's message)."""
        parser.set_reference_time(fixed_reference_time)

        result = parser.parse("PM 8:29")

        assert result is not None
        assert result.hour == 20
        assert result.minute == 29
        assert result.day == 10
        assert result.month == 12

    def test_parse_time_only_am(self, parser, fixed_reference_time):
        """Test parsing AM time."""
        parser.set_reference_time(fixed_reference_time)

        result = parser.parse("AM 10:30")

        assert result is not None
        assert result.hour == 10
        assert result.minute == 30

    def test_parse_chinese_time_pm(self, parser, fixed_reference_time):
        """Test parsing Chinese afternoon time."""
        parser.set_reference_time(fixed_reference_time)

        result = parser.parse("下午 8:29")

        assert result is not None
        assert result.hour == 20
        assert result.minute == 29

    def test_parse_chinese_time_am(self, parser, fixed_reference_time):
        """Test parsing Chinese morning time."""
        parser.set_reference_time(fixed_reference_time)

        result = parser.parse("上午 10:30")

        assert result is not None
        assert result.hour == 10
        assert result.minute == 30

    def test_parse_yesterday_english(self, parser, fixed_reference_time):
        """Test parsing yesterday with English label."""
        parser.set_reference_time(fixed_reference_time)

        result = parser.parse("Yesterday PM 8:41")

        assert result is not None
        assert result.day == 9
        assert result.hour == 20
        assert result.minute == 41

    def test_parse_yesterday_chinese(self, parser, fixed_reference_time):
        """Test parsing yesterday with Chinese label."""
        parser.set_reference_time(fixed_reference_time)

        result = parser.parse("昨天 下午 8:41")

        assert result is not None
        assert result.day == 9
        assert result.hour == 20
        assert result.minute == 41

    def test_parse_day_of_week_english(self, parser, fixed_reference_time):
        """Test parsing day of week (Thursday) from Wednesday reference."""
        # Reference is Wednesday Dec 10, 2025
        parser.set_reference_time(fixed_reference_time)

        result = parser.parse("Thursday PM 7:37")

        assert result is not None
        # Thursday before Wednesday is 6 days ago (Dec 4)
        assert result.day == 4
        assert result.hour == 19
        assert result.minute == 37

    def test_parse_day_of_week_monday(self, parser, fixed_reference_time):
        """Test parsing Monday from Wednesday reference."""
        parser.set_reference_time(fixed_reference_time)

        result = parser.parse("Monday PM 4:55")

        assert result is not None
        # Monday before Wednesday is 2 days ago (Dec 8)
        assert result.day == 8
        assert result.hour == 16
        assert result.minute == 55

    def test_parse_chinese_day_of_week(self, parser, fixed_reference_time):
        """Test parsing Chinese day of week."""
        parser.set_reference_time(fixed_reference_time)

        result = parser.parse("星期四 下午 7:37")

        assert result is not None
        assert result.day == 4  # Thursday = Dec 4
        assert result.hour == 19
        assert result.minute == 37

    def test_parse_chinese_short_day_of_week(self, parser, fixed_reference_time):
        """Test parsing Chinese short form day of week."""
        parser.set_reference_time(fixed_reference_time)

        result = parser.parse("周四 下午 7:37")

        assert result is not None
        assert result.day == 4  # Thursday = Dec 4

    def test_parse_date_slash_format(self, parser, fixed_reference_time):
        """Test parsing slash date format."""
        parser.set_reference_time(fixed_reference_time)

        result = parser.parse("12/5")

        assert result is not None
        assert result.month == 12
        assert result.day == 5

    def test_parse_date_with_year(self, parser, fixed_reference_time):
        """Test parsing date with year."""
        parser.set_reference_time(fixed_reference_time)

        result = parser.parse("2024/11/20")

        assert result is not None
        assert result.year == 2024
        assert result.month == 11
        assert result.day == 20

    def test_parse_just_now(self, parser, fixed_reference_time):
        """Test parsing 'just now'."""
        parser.set_reference_time(fixed_reference_time)

        result = parser.parse("just now")

        assert result is not None
        # Should be approximately the reference time
        assert abs((result - fixed_reference_time).total_seconds()) < 1

    def test_parse_gang_gang(self, parser, fixed_reference_time):
        """Test parsing Chinese '刚刚' (just now)."""
        parser.set_reference_time(fixed_reference_time)

        result = parser.parse("刚刚")

        assert result is not None
        assert abs((result - fixed_reference_time).total_seconds()) < 1

    def test_parse_relative_minutes_ago(self, parser, fixed_reference_time):
        """Test parsing X minutes ago."""
        parser.set_reference_time(fixed_reference_time)

        result = parser.parse("5 mins ago")

        assert result is not None
        expected = fixed_reference_time - timedelta(minutes=5)
        assert abs((result - expected).total_seconds()) < 1

    def test_parse_relative_hours_ago_chinese(self, parser, fixed_reference_time):
        """Test parsing X小时前."""
        parser.set_reference_time(fixed_reference_time)

        result = parser.parse("2小时前")

        assert result is not None
        expected = fixed_reference_time - timedelta(hours=2)
        assert abs((result - expected).total_seconds()) < 1

    def test_invalid_timestamp(self, parser, fixed_reference_time):
        """Test parsing invalid timestamp returns None."""
        parser.set_reference_time(fixed_reference_time)

        result = parser.parse("Invalid timestamp")

        assert result is None

    def test_empty_timestamp(self, parser):
        """Test parsing empty string returns None."""
        result = parser.parse("")
        assert result is None

    def test_timezone_change(self):
        """Test changing timezone."""
        parser = TimestampParser(timezone="Asia/Shanghai")
        assert parser.timezone == "Asia/Shanghai"

        parser.set_timezone("America/New_York")
        assert parser.timezone == "America/New_York"


class TestTimestampContext:
    """Tests for TimestampContext class."""

    def test_context_propagation(self, parser, fixed_reference_time):
        """Test timestamp context propagates to messages without timestamps."""
        parser.set_reference_time(fixed_reference_time)
        context = TimestampContext(parser)

        # Set context from a timestamp separator
        context.update_from_separator("Thursday PM 7:37")

        # Get timestamp for a message without its own timestamp
        raw, parsed = context.get_timestamp_for_message(None)

        assert raw == "Thursday PM 7:37"
        assert parsed is not None
        assert parsed.day == 4
        assert parsed.hour == 19

    def test_context_update_from_message(self, parser, fixed_reference_time):
        """Test that message timestamps update the context."""
        parser.set_reference_time(fixed_reference_time)
        context = TimestampContext(parser)

        # Get timestamp for a message with its own timestamp
        raw, parsed = context.get_timestamp_for_message("PM 8:29")

        assert raw == "PM 8:29"
        assert parsed.hour == 20

        # Next message without timestamp should use the updated context
        raw2, parsed2 = context.get_timestamp_for_message(None)
        assert raw2 == "PM 8:29"
        assert parsed2.hour == 20

    def test_context_reset(self, parser, fixed_reference_time):
        """Test context reset."""
        parser.set_reference_time(fixed_reference_time)
        context = TimestampContext(parser)

        context.update_from_separator("Thursday PM 7:37")
        context.reset()

        raw, parsed = context.get_timestamp_for_message(None)
        assert raw is None
        assert parsed is None


class TestParseWecomTimestampFunction:
    """Tests for the convenience function."""

    def test_convenience_function(self, fixed_reference_time):
        """Test the parse_wecom_timestamp convenience function."""
        result = parse_wecom_timestamp("PM 8:29", timezone="Asia/Shanghai", reference_time=fixed_reference_time)

        assert result is not None
        assert result.hour == 20
        assert result.minute == 29

    def test_default_timezone(self):
        """Test default timezone is Asia/Shanghai."""
        # Create a reference time for today
        now = datetime.now(ZoneInfo("Asia/Shanghai"))

        result = parse_wecom_timestamp("PM 8:29", reference_time=now)

        assert result is not None
        assert result.tzinfo is not None


class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_same_weekday_is_7_days_ago(self, parser, fixed_reference_time):
        """Test that same weekday (Wednesday on Wednesday) is 7 days ago."""
        # Reference is Wednesday Dec 10
        parser.set_reference_time(fixed_reference_time)

        result = parser.parse("Wednesday PM 3:00")

        assert result is not None
        # Should be Dec 3 (7 days ago), not today
        assert result.day == 3

    def test_12_hour_edge_cases(self, parser, fixed_reference_time):
        """Test 12:00 AM and 12:00 PM."""
        parser.set_reference_time(fixed_reference_time)

        # 12:00 AM should be midnight (00:00)
        result_am = parser.parse("AM 12:00")
        assert result_am is not None
        assert result_am.hour == 0

        # 12:00 PM should be noon (12:00)
        result_pm = parser.parse("PM 12:00")
        assert result_pm is not None
        assert result_pm.hour == 12

    def test_time_with_preceding_text(self, parser, fixed_reference_time):
        """Test parsing time that has preceding text."""
        parser.set_reference_time(fixed_reference_time)

        result = parser.parse("Today PM 5:30")

        assert result is not None
        assert result.hour == 17
        assert result.minute == 30
