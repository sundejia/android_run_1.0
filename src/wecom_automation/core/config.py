"""
Configuration management for WeCom Automation.

This module provides centralized configuration with:
- Default values
- Environment variable overrides
- Type-safe access
- Validation
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# ============================================
# 项目根目录和数据库路径
# ============================================


def get_project_root() -> Path:
    """
    获取项目根目录。

    优先级:
    1. WECOM_PROJECT_ROOT 环境变量
    2. 根据当前文件位置推算（假设在 src/wecom_automation/core/）
    """
    env_root = os.environ.get("WECOM_PROJECT_ROOT")
    if env_root:
        return Path(env_root).resolve()

    # 当前文件: src/wecom_automation/core/config.py
    # 项目根: 上3层
    return Path(__file__).resolve().parents[3]


def get_default_db_path() -> Path:
    """
    获取默认数据库路径。

    优先级:
    1. WECOM_DB_PATH 环境变量（绝对路径）
    2. 项目根目录下的 wecom_conversations.db
    """
    env_db = os.environ.get("WECOM_DB_PATH")
    if env_db:
        return Path(env_db).resolve()

    return get_project_root() / "wecom_conversations.db"


# 全局常量（便于导入）
PROJECT_ROOT = get_project_root()
DEFAULT_DB_PATH = get_default_db_path()


@dataclass(frozen=True)
class AppConfig:
    """WeCom app-specific configuration."""

    package_name: str = "com.tencent.wework"

    # Text patterns for UI elements (multi-language support)
    all_text_patterns: tuple[str, ...] = ("All", "全部", "全部消息")
    # Target filter: Private Chats (changed 2026-01-22)
    private_chats_patterns: tuple[str, ...] = ("Private Chats", "Private", "私聊", "单聊")

    # Channel identification patterns
    channel_text_patterns: tuple[str, ...] = ("@WeChat", "@微信", "@wechat", "＠WeChat", "＠微信", "＠wechat")

    # Fallback coordinates for key UI elements (1080x2340 reference device)
    back_button_coordinates: tuple[int, int] = (120, 180)
    send_button_coordinates: tuple[int, int] = (980, 2200)


@dataclass(frozen=True)
class TimingConfig:
    """Timing configuration for operations."""

    wait_after_launch: float = 3.0
    scroll_delay: float = 1.0
    tap_delay: float = 0.5
    retry_delay: float = 1.5
    ui_stabilization_delay: float = 0.3


@dataclass(frozen=True)
class ScrollConfig:
    """Scroll behavior configuration."""

    max_scrolls: int = 20
    stable_threshold: int = 4  # Stop after N consecutive scrolls with no new items
    scroll_distance: int = 600
    scroll_to_top_attempts: int = 6
    scroll_to_top_stable_threshold: int = 3  # Stop if UI unchanged for N attempts

    # Screen coordinates for scrolling (typical phone dimensions)
    start_x: int = 540
    scroll_up_start_y: int = 400
    scroll_up_end_y: int = 1000
    scroll_down_start_y: int = 1200
    scroll_down_end_y: int = 600
    swipe_duration_ms: int = 300


@dataclass(frozen=True)
class UIParserConfig:
    """Configuration for UI tree parsing."""

    # Container identification hints
    message_list_class_hints: tuple[str, ...] = ("recyclerview", "listview", "viewpager", "listlayout", "viewgroup")
    message_list_id_hints: tuple[str, ...] = (
        "conversation",
        "session",
        "message",
        "msg",
        "chat",
        "recent",
        "list",
        "inbox",
        "io2",
        "iop",
        "iru",  # Current WeCom chat ListView on observed devices
    )

    # Message Row hints (for distinguishing message rows from timestamps)
    message_row_id_hints: tuple[str, ...] = ("cmn", "cmj", "coy", "cp5")

    # Field identification hints
    name_resource_id_hints: tuple[str, ...] = ("title", "name", "nickname", "username", "contact")
    channel_resource_id_hints: tuple[str, ...] = ("channel", "source", "platform", "type", "tag")
    date_resource_id_hints: tuple[str, ...] = ("time", "timestamp", "date", "datetime", "last")
    snippet_resource_id_hints: tuple[str, ...] = (
        "content",
        "summary",
        "desc",
        "preview",
        "snippet",
        "message",
        "msg",
        "body",
        "idk",
        "icx",
        "ig6",  # WeCom newer version message text
        "igj",  # Current WeCom message text on observed devices
    )
    avatar_class_hints: tuple[str, ...] = ("imageview", "image", "avatar", "icon", "photo")
    avatar_resource_id_hints: tuple[str, ...] = (
        "avatar",
        "photo",
        "icon",
        "head",
        "portrait",
        "profile",
        "im4",
        "ilg",
        "iov",
        "ip9",  # Current WeCom avatar image on observed devices
    )

    # Patterns to exclude (dropdown/filter elements)
    dropdown_filter_patterns: tuple[str, ...] = (
        "private",
        "私聊",
        "单聊",
        "all",
        "全部",
        "group",
        "群聊",
        "unread",
        "未读",
        "mention",
        "@我",
        "cal",
        "日历",
        "calendar",
        "meeting",
        "会议",
    )


@dataclass(frozen=True)
class RetryConfig:
    """Retry behavior configuration."""

    max_retries: int = 4
    retry_delay: float = 1.5
    exponential_backoff: bool = False
    backoff_multiplier: float = 2.0


@dataclass(frozen=True)
class TimezoneConfig:
    """Timezone configuration for timestamp parsing."""

    # Default timezone (IANA format)
    timezone: str = "Asia/Shanghai"

    # Common timezone presets for quick selection
    PRESETS = {
        "china": "Asia/Shanghai",
        "beijing": "Asia/Shanghai",
        "hongkong": "Asia/Hong_Kong",
        "taiwan": "Asia/Taipei",
        "singapore": "Asia/Singapore",
        "tokyo": "Asia/Tokyo",
        "seoul": "Asia/Seoul",
        "us_pacific": "America/Los_Angeles",
        "us_eastern": "America/New_York",
        "uk": "Europe/London",
        "utc": "UTC",
    }

    @classmethod
    def from_preset(cls, preset: str) -> TimezoneConfig:
        """Create config from a preset name."""
        tz = cls.PRESETS.get(preset.lower(), preset)
        return cls(timezone=tz)


@dataclass
class Config:
    """
    Main configuration class that aggregates all sub-configurations.

    Usage:
        config = Config()  # Use defaults
        config = Config.from_env()  # Load from environment variables

        # Access sub-configs
        config.app.package_name
        config.timing.wait_after_launch
        config.timezone.timezone
        config.db_path  # Database path
    """

    app: AppConfig = field(default_factory=AppConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    scroll: ScrollConfig = field(default_factory=ScrollConfig)
    ui_parser: UIParserConfig = field(default_factory=UIParserConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    timezone_config: TimezoneConfig = field(default_factory=TimezoneConfig)

    # Device configuration
    device_serial: str | None = None
    use_tcp: bool = False
    droidrun_port: int = 8080  # DroidRun TCP port (must be unique per device for multi-device sync)

    # Database configuration
    db_path: str = field(default_factory=lambda: str(DEFAULT_DB_PATH))

    # Debug settings
    debug: bool = False
    log_file: str | None = None

    # Output settings
    output_dir: str = "."
    capture_avatars: bool = False

    @property
    def timezone(self) -> str:
        """Convenience property to get the timezone string."""
        return self.timezone_config.timezone

    @classmethod
    def from_env(cls) -> Config:
        """
        Create a Config instance with values from environment variables.

        Environment variables:
            WECOM_DEVICE_SERIAL: Device serial number
            WECOM_USE_TCP: Use TCP mode (true/false)
            WECOM_DEBUG: Enable debug mode (true/false)
            WECOM_OUTPUT_DIR: Output directory path
            WECOM_LOG_FILE: Log file path
            WECOM_WAIT_AFTER_LAUNCH: Wait time after launch (seconds)
            WECOM_MAX_SCROLLS: Maximum scroll attempts
        """

        def get_bool(key: str, default: bool = False) -> bool:
            value = os.environ.get(key, "").lower()
            return value in ("true", "1", "yes")

        def get_float(key: str, default: float) -> float:
            try:
                return float(os.environ.get(key, default))
            except ValueError:
                return default

        def get_int(key: str, default: int) -> int:
            try:
                return int(os.environ.get(key, default))
            except ValueError:
                return default

        timing = TimingConfig(
            wait_after_launch=get_float("WECOM_WAIT_AFTER_LAUNCH", 3.0),
            scroll_delay=get_float("WECOM_SCROLL_DELAY", 1.0),
        )

        scroll = ScrollConfig(
            max_scrolls=get_int("WECOM_MAX_SCROLLS", 20),
            stable_threshold=get_int("WECOM_STABLE_THRESHOLD", 4),
            scroll_to_top_attempts=get_int("WECOM_SCROLL_TO_TOP_ATTEMPTS", 6),
            scroll_to_top_stable_threshold=get_int("WECOM_SCROLL_TO_TOP_STABLE_THRESHOLD", 3),
        )

        # Timezone configuration
        timezone_str = os.environ.get("WECOM_TIMEZONE", "Asia/Shanghai")
        # Support preset names
        if timezone_str.lower() in TimezoneConfig.PRESETS:
            timezone_config = TimezoneConfig.from_preset(timezone_str)
        else:
            timezone_config = TimezoneConfig(timezone=timezone_str)

        return cls(
            timing=timing,
            scroll=scroll,
            timezone_config=timezone_config,
            device_serial=os.environ.get("WECOM_DEVICE_SERIAL"),
            use_tcp=get_bool("WECOM_USE_TCP"),
            droidrun_port=get_int("WECOM_DROIDRUN_PORT", 8080),
            db_path=str(get_default_db_path()),  # Uses WECOM_DB_PATH env var if set
            debug=get_bool("WECOM_DEBUG"),
            log_file=os.environ.get("WECOM_LOG_FILE"),
            output_dir=os.environ.get("WECOM_OUTPUT_DIR", "."),
            capture_avatars=get_bool("WECOM_CAPTURE_AVATARS"),
        )

    def with_overrides(self, **kwargs) -> Config:
        """
        Create a new Config with specific values overridden.

        Args:
            **kwargs: Config attributes to override

        Returns:
            New Config instance with overrides applied
        """
        import dataclasses

        return dataclasses.replace(self, **kwargs)
