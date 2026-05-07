"""Configuration for the BOSS Zhipin recruitment automation.

Mirrors the layered ``Config`` shape used by the WeCom legacy package so
later milestones can share infrastructure helpers without translation.

All values are sourced from environment variables prefixed with
``BOSS_`` so they cannot collide with the legacy ``WECOM_`` settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEFAULT_DB_FILENAME: Final[str] = "boss_recruitment.db"


def get_default_db_path() -> Path:
    """Resolve the default BOSS SQLite path.

    Order of precedence:
    1. ``BOSS_DB_PATH`` environment variable.
    2. ``<PROJECT_ROOT>/boss_recruitment.db``.
    """
    env = os.environ.get("BOSS_DB_PATH")
    if env:
        return Path(env).expanduser().resolve()
    return PROJECT_ROOT / DEFAULT_DB_FILENAME


@dataclass(frozen=True, slots=True)
class AppConfig:
    """BOSS Zhipin Android app coordinates."""

    package_name: str = "com.hpbr.bosszhipin"
    main_activity: str = "com.hpbr.bosszhipin.module.main.activity.MainActivity"
    accepted_package_names: tuple[str, ...] = (
        "com.hpbr.bosszhipin",
        "com.hpbr.directhires",
    )


@dataclass(frozen=True, slots=True)
class TimingConfig:
    """Timing knobs for human-paced interactions."""

    wait_after_launch: float = 5.0
    wait_after_tap: float = 0.6
    wait_after_swipe: float = 0.4
    wait_after_input: float = 0.5
    inter_message_min: float = 1.5
    inter_message_max: float = 4.0


@dataclass(frozen=True, slots=True)
class ScrollConfig:
    """Scrolling knobs for paginated lists (jobs, candidates, messages)."""

    max_scrolls: int = 30
    scroll_delay: float = 1.5
    stable_threshold: int = 2


@dataclass(frozen=True, slots=True)
class GreetQuotaConfig:
    """Limits enforced by the greet executor (M3)."""

    per_hour: int = 30
    per_job_per_hour: int = 10
    per_day: int = 200
    cooldown_seconds: int = 4


@dataclass(frozen=True, slots=True)
class TimezoneConfig:
    timezone: str = "Asia/Shanghai"


@dataclass(slots=True)
class Config:
    """Aggregate runtime configuration for BOSS automation."""

    app: AppConfig = field(default_factory=AppConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    scroll: ScrollConfig = field(default_factory=ScrollConfig)
    quota: GreetQuotaConfig = field(default_factory=GreetQuotaConfig)
    timezone_config: TimezoneConfig = field(default_factory=TimezoneConfig)

    device_serial: str | None = None
    use_tcp: bool = False
    droidrun_port: int = 8080

    db_path: str = field(default_factory=lambda: str(get_default_db_path()))
    output_dir: str = "."
    debug: bool = False
    log_file: str | None = None

    @property
    def timezone(self) -> str:
        return self.timezone_config.timezone

    @classmethod
    def from_env(cls) -> Config:
        """Build a config from ``BOSS_*`` environment variables."""

        def _bool(value: str | None) -> bool:
            return (value or "").strip().lower() in ("1", "true", "yes", "on")

        def _int(value: str | None, default: int) -> int:
            try:
                return int(value) if value else default
            except (TypeError, ValueError):
                return default

        cfg = cls()
        cfg.device_serial = os.environ.get("BOSS_DEVICE_SERIAL") or cfg.device_serial
        cfg.use_tcp = _bool(os.environ.get("BOSS_USE_TCP")) or cfg.use_tcp
        cfg.droidrun_port = _int(os.environ.get("BOSS_DROIDRUN_PORT"), cfg.droidrun_port)
        cfg.db_path = os.environ.get("BOSS_DB_PATH") or cfg.db_path
        cfg.output_dir = os.environ.get("BOSS_OUTPUT_DIR") or cfg.output_dir
        cfg.debug = _bool(os.environ.get("BOSS_DEBUG")) or cfg.debug
        cfg.log_file = os.environ.get("BOSS_LOG_FILE") or cfg.log_file

        tz = os.environ.get("BOSS_TIMEZONE")
        if tz:
            cfg.timezone_config = replace(cfg.timezone_config, timezone=tz)

        return cfg

    def with_overrides(self, **overrides: object) -> Config:
        """Return a shallow copy with the given top-level overrides applied."""
        for key in overrides:
            if not hasattr(self, key):
                raise AttributeError(f"unknown Config attribute: {key}")
        new = Config(
            app=self.app,
            timing=self.timing,
            scroll=self.scroll,
            quota=self.quota,
            timezone_config=self.timezone_config,
            device_serial=self.device_serial,
            use_tcp=self.use_tcp,
            droidrun_port=self.droidrun_port,
            db_path=self.db_path,
            output_dir=self.output_dir,
            debug=self.debug,
            log_file=self.log_file,
        )
        for key, value in overrides.items():
            setattr(new, key, value)
        return new
