"""
Timestamp Parser Service - Parse WeChat/WeCom relative timestamps to absolute datetime.

WeChat displays timestamps in various relative formats:
1. Today: "PM 8:29" or "上午 10:30" (just time)
2. Yesterday: "Yesterday PM 8:41" or "昨天 下午 8:41"
3. This week: "Thursday PM 7:37" or "星期四 下午 7:37" or "周四 下午 7:37"
4. Older: "12/5" or "2024/12/5" (date format)

This module converts these relative timestamps to absolute datetime objects.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from wecom_automation.core.logging import get_logger

# Day name mappings (English, Chinese full, Chinese short)
DAY_MAPPINGS = {
    # English
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
    # Chinese full form (星期X)
    "星期一": 0,
    "星期二": 1,
    "星期三": 2,
    "星期四": 3,
    "星期五": 4,
    "星期六": 5,
    "星期日": 6,
    "星期天": 6,
    # Chinese short form (周X)
    "周一": 0,
    "周二": 1,
    "周三": 2,
    "周四": 3,
    "周五": 4,
    "周六": 5,
    "周日": 6,
    "周天": 6,
}

# AM/PM mappings
AM_PM_MAPPINGS = {
    # English
    "am": "AM",
    "pm": "PM",
    # Chinese
    "上午": "AM",
    "下午": "PM",
    "凌晨": "AM",
    "早上": "AM",
    "中午": "PM",
    "晚上": "PM",
}

# Relative day mappings
RELATIVE_DAY_MAPPINGS = {
    "today": 0,
    "今天": 0,
    "今日": 0,
    "yesterday": 1,
    "昨天": 1,
    "昨日": 1,
    "just now": 0,
    "刚刚": 0,
}

# Regex patterns
TIME_12H_PATTERN = re.compile(
    r"(?P<ampm>AM|PM|am|pm|上午|下午|凌晨|早上|中午|晚上)?\s*"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})"
    r"(?:\s*(?P<ampm2>AM|PM|am|pm|上午|下午|凌晨|早上|中午|晚上))?",
    re.IGNORECASE,
)

DATE_SLASH_PATTERN = re.compile(r"(?:(?P<year>\d{4})[/\-])?(?P<month>\d{1,2})[/\-](?P<day>\d{1,2})")

# Chinese date pattern: X月X日
DATE_CN_PATTERN = re.compile(r"(?:(?P<year>\d{4})年)?(?P<month>\d{1,2})月(?P<day>\d{1,2})日?")


class TimestampParser:
    """
    Parser for WeChat/WeCom relative timestamps.

    Usage:
        parser = TimestampParser(timezone="Asia/Shanghai")
        dt = parser.parse("Thursday PM 7:37")
        dt = parser.parse("Yesterday PM 8:41")
        dt = parser.parse("PM 8:29")
    """

    def __init__(self, timezone: str = "Asia/Shanghai"):
        """
        Initialize the timestamp parser.

        Args:
            timezone: IANA timezone name (e.g., "Asia/Shanghai", "America/New_York")
        """
        self.timezone = timezone
        self._tz = ZoneInfo(timezone)
        self.logger = get_logger("wecom_automation.timestamp_parser")

        # Cache current context (date reference point)
        self._reference_time: datetime | None = None

    @property
    def tz(self) -> ZoneInfo:
        """Get the timezone object."""
        return self._tz

    def set_timezone(self, timezone: str) -> None:
        """
        Update the timezone.

        Args:
            timezone: IANA timezone name
        """
        self.timezone = timezone
        self._tz = ZoneInfo(timezone)
        self.logger.debug(f"Timezone set to: {timezone}")

    def get_now(self) -> datetime:
        """Get current time in the configured timezone."""
        return datetime.now(self._tz)

    def set_reference_time(self, ref_time: datetime | None = None) -> None:
        """
        Set the reference time for parsing relative timestamps.

        This should be called before parsing a batch of messages to ensure
        consistent date calculations.

        Args:
            ref_time: Reference datetime (uses current time if None)
        """
        if ref_time is None:
            self._reference_time = self.get_now()
        else:
            # Ensure timezone awareness
            if ref_time.tzinfo is None:
                ref_time = ref_time.replace(tzinfo=self._tz)
            self._reference_time = ref_time

    def get_reference_time(self) -> datetime:
        """Get the reference time, initializing if needed."""
        if self._reference_time is None:
            self.set_reference_time()
        return self._reference_time

    def parse(self, timestamp_raw: str, reference_time: datetime | None = None) -> datetime | None:
        """
        Parse a WeChat timestamp string to an absolute datetime.

        Args:
            timestamp_raw: Raw timestamp string from WeChat UI
            reference_time: Optional reference time (defaults to instance reference)

        Returns:
            Parsed datetime with timezone, or None if parsing failed
        """
        if not timestamp_raw:
            return None

        timestamp_raw = timestamp_raw.strip()
        ref_time = reference_time or self.get_reference_time()

        try:
            # Try different parsing strategies in order
            result = (
                self._parse_relative_day_time(timestamp_raw, ref_time)
                or self._parse_day_of_week_time(timestamp_raw, ref_time)
                or self._parse_date_time(timestamp_raw, ref_time)
                or self._parse_time_only(timestamp_raw, ref_time)
                or self._parse_relative_time(timestamp_raw, ref_time)
            )

            if result:
                self.logger.debug(f"Parsed '{timestamp_raw}' -> {result}")
            else:
                self.logger.warning(f"Failed to parse timestamp: '{timestamp_raw}'")

            return result

        except Exception as e:
            self.logger.error(f"Error parsing timestamp '{timestamp_raw}': {e}")
            return None

    def _parse_time_only(self, text: str, ref_time: datetime) -> datetime | None:
        """
        Parse time-only format (today's messages).

        Formats: "PM 8:29", "上午 10:30", "8:29 PM"
        """
        # Check if text contains only time (no day references)
        text_lower = text.lower()

        # Skip if contains day name or relative day
        for day_name in DAY_MAPPINGS:
            if day_name.lower() in text_lower:
                return None
        for rel_day in RELATIVE_DAY_MAPPINGS:
            if rel_day.lower() in text_lower and rel_day.lower() not in ("today", "今天", "今日"):
                return None

        # Try to extract time
        match = TIME_12H_PATTERN.search(text)
        if match:
            hour, minute = int(match.group("hour")), int(match.group("minute"))
            ampm = match.group("ampm") or match.group("ampm2")

            if ampm:
                ampm_normalized = AM_PM_MAPPINGS.get(ampm.lower(), ampm.upper())
                if ampm_normalized == "PM" and hour < 12:
                    hour += 12
                elif ampm_normalized == "AM" and hour == 12:
                    hour = 0

            # Create datetime for today
            result = ref_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return result

        return None

    def _parse_relative_day_time(self, text: str, ref_time: datetime) -> datetime | None:
        """
        Parse relative day + time format.

        Formats: "Yesterday PM 8:41", "昨天 下午 8:41", "Today 10:30"
        """
        text_lower = text.lower()
        days_ago = None

        # Find relative day
        for rel_day, offset in RELATIVE_DAY_MAPPINGS.items():
            if rel_day.lower() in text_lower:
                days_ago = offset
                break

        if days_ago is None:
            return None

        # Extract time
        match = TIME_12H_PATTERN.search(text)
        if not match:
            # "just now" / "刚刚" - no time component
            if days_ago == 0:
                return ref_time
            return None

        hour, minute = int(match.group("hour")), int(match.group("minute"))
        ampm = match.group("ampm") or match.group("ampm2")

        if ampm:
            ampm_normalized = AM_PM_MAPPINGS.get(ampm.lower(), ampm.upper())
            if ampm_normalized == "PM" and hour < 12:
                hour += 12
            elif ampm_normalized == "AM" and hour == 12:
                hour = 0

        # Calculate the date
        target_date = ref_time.date() - timedelta(days=days_ago)
        result = datetime(target_date.year, target_date.month, target_date.day, hour, minute, 0, 0, tzinfo=self._tz)
        return result

    def _parse_day_of_week_time(self, text: str, ref_time: datetime) -> datetime | None:
        """
        Parse day-of-week + time format.

        Formats: "Thursday PM 7:37", "星期四 下午 7:37", "周四 下午 7:37"
        """
        text_lower = text.lower()
        target_weekday = None

        # Find day of week
        for day_name, weekday in DAY_MAPPINGS.items():
            if day_name.lower() in text_lower:
                target_weekday = weekday
                break

        if target_weekday is None:
            return None

        # Extract time
        match = TIME_12H_PATTERN.search(text)
        if not match:
            return None

        hour, minute = int(match.group("hour")), int(match.group("minute"))
        ampm = match.group("ampm") or match.group("ampm2")

        if ampm:
            ampm_normalized = AM_PM_MAPPINGS.get(ampm.lower(), ampm.upper())
            if ampm_normalized == "PM" and hour < 12:
                hour += 12
            elif ampm_normalized == "AM" and hour == 12:
                hour = 0

        # Calculate the date - find the most recent occurrence of this weekday
        # WeChat shows day names for messages within the past week (not today/yesterday)
        current_weekday = ref_time.weekday()
        days_back = (current_weekday - target_weekday) % 7

        # If it's the same weekday, it means 7 days ago (not today, which would show time only)
        if days_back == 0:
            days_back = 7
        # If the calculated day would be today or yesterday, adjust
        # (since those have special labels)
        if days_back <= 1:
            days_back += 7

        target_date = ref_time.date() - timedelta(days=days_back)
        result = datetime(target_date.year, target_date.month, target_date.day, hour, minute, 0, 0, tzinfo=self._tz)
        return result

    def _parse_date_time(self, text: str, ref_time: datetime) -> datetime | None:
        """
        Parse explicit date + optional time format.

        Formats: "12/5", "2024/12/5", "12月5日", "2024年12月5日"
        """
        # Try slash format first
        match = DATE_SLASH_PATTERN.search(text)
        if match:
            year = int(match.group("year")) if match.group("year") else ref_time.year
            month = int(match.group("month"))
            day = int(match.group("day"))
        else:
            # Try Chinese format
            match = DATE_CN_PATTERN.search(text)
            if match:
                year = int(match.group("year")) if match.group("year") else ref_time.year
                month = int(match.group("month"))
                day = int(match.group("day"))
            else:
                return None

        # Extract optional time
        hour, minute = 12, 0  # Default to noon if no time
        time_match = TIME_12H_PATTERN.search(text)
        if time_match:
            hour, minute = int(time_match.group("hour")), int(time_match.group("minute"))
            ampm = time_match.group("ampm") or time_match.group("ampm2")

            if ampm:
                ampm_normalized = AM_PM_MAPPINGS.get(ampm.lower(), ampm.upper())
                if ampm_normalized == "PM" and hour < 12:
                    hour += 12
                elif ampm_normalized == "AM" and hour == 12:
                    hour = 0

        try:
            result = datetime(year, month, day, hour, minute, 0, 0, tzinfo=self._tz)
            return result
        except ValueError:
            return None

    def _parse_relative_time(self, text: str, ref_time: datetime) -> datetime | None:
        """
        Parse relative time format (X minutes/hours ago).

        Formats: "5 mins ago", "2 hours ago", "3分钟前", "2小时前"
        """
        text_lower = text.lower()

        # English patterns
        patterns = [
            (r"(\d+)\s*(?:sec|secs|second|seconds)\s*ago", "seconds"),
            (r"(\d+)\s*(?:min|mins|minute|minutes)\s*ago", "minutes"),
            (r"(\d+)\s*(?:hr|hrs|hour|hours)\s*ago", "hours"),
            (r"(\d+)\s*(?:day|days)\s*ago", "days"),
        ]

        for pattern, unit in patterns:
            match = re.search(pattern, text_lower)
            if match:
                value = int(match.group(1))
                delta = timedelta(**{unit: value})
                return ref_time - delta

        # Chinese patterns
        cn_patterns = [
            (r"(\d+)\s*秒前", "seconds"),
            (r"(\d+)\s*分钟前", "minutes"),
            (r"(\d+)\s*小时前", "hours"),
            (r"(\d+)\s*天前", "days"),
        ]

        for pattern, unit in cn_patterns:
            match = re.search(pattern, text)
            if match:
                value = int(match.group(1))
                delta = timedelta(**{unit: value})
                return ref_time - delta

        return None


class TimestampContext:
    """
    Maintains timestamp context for a conversation extraction session.

    WeChat shows timestamps as separators, and multiple messages following
    a timestamp share that timestamp. This class tracks the current timestamp
    context and assigns it to messages.
    """

    def __init__(self, parser: TimestampParser):
        """
        Initialize timestamp context.

        Args:
            parser: TimestampParser instance to use
        """
        self.parser = parser
        self._current_timestamp: datetime | None = None
        self._current_timestamp_raw: str | None = None

    def update_from_separator(self, timestamp_raw: str) -> datetime | None:
        """
        Update the current timestamp context from a timestamp separator.

        Args:
            timestamp_raw: Raw timestamp string from a separator row

        Returns:
            Parsed datetime, or None if parsing failed
        """
        if not timestamp_raw:
            return self._current_timestamp

        parsed = self.parser.parse(timestamp_raw)
        if parsed:
            self._current_timestamp = parsed
            self._current_timestamp_raw = timestamp_raw

        return self._current_timestamp

    def get_timestamp_for_message(self, message_timestamp_raw: str | None = None) -> tuple[str | None, datetime | None]:
        """
        Get the timestamp for a message.

        If the message has its own timestamp, parse and return it.
        Otherwise, return the current context timestamp.

        Args:
            message_timestamp_raw: Optional timestamp from the message itself

        Returns:
            Tuple of (raw_timestamp, parsed_datetime)
        """
        if message_timestamp_raw:
            # Message has its own timestamp, parse it
            parsed = self.parser.parse(message_timestamp_raw)
            if parsed:
                # Also update context
                self._current_timestamp = parsed
                self._current_timestamp_raw = message_timestamp_raw
                return message_timestamp_raw, parsed

        # Return current context
        return self._current_timestamp_raw, self._current_timestamp

    def reset(self) -> None:
        """Reset the timestamp context."""
        self._current_timestamp = None
        self._current_timestamp_raw = None


# Convenience function for simple parsing
def parse_wecom_timestamp(
    timestamp_raw: str, timezone: str = "Asia/Shanghai", reference_time: datetime | None = None
) -> datetime | None:
    """
    Parse a WeChat/WeCom timestamp string.

    Args:
        timestamp_raw: Raw timestamp from UI
        timezone: IANA timezone name
        reference_time: Optional reference time (defaults to now)

    Returns:
        Parsed datetime with timezone, or None if parsing failed
    """
    parser = TimestampParser(timezone=timezone)
    if reference_time:
        parser.set_reference_time(reference_time)
    return parser.parse(timestamp_raw)
