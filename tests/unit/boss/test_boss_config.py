"""TDD tests for src/boss_automation/core/config.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from boss_automation.core.config import (
    PROJECT_ROOT,
    AppConfig,
    Config,
    GreetQuotaConfig,
    ScrollConfig,
    TimezoneConfig,
    TimingConfig,
    get_default_db_path,
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "BOSS_DB_PATH",
        "BOSS_DEVICE_SERIAL",
        "BOSS_USE_TCP",
        "BOSS_DROIDRUN_PORT",
        "BOSS_DEBUG",
        "BOSS_LOG_FILE",
        "BOSS_TIMEZONE",
        "BOSS_OUTPUT_DIR",
    ):
        monkeypatch.delenv(key, raising=False)


class TestAppDefaults:
    def test_default_app_package_is_boss_zhipin(self) -> None:
        assert AppConfig().package_name == "com.hpbr.bosszhipin"

    def test_app_accepts_both_known_boss_packages(self) -> None:
        accepted = AppConfig().accepted_package_names
        assert "com.hpbr.bosszhipin" in accepted
        assert "com.hpbr.directhires" in accepted

    def test_default_quota_values_are_sane(self) -> None:
        quota = GreetQuotaConfig()
        assert quota.per_hour > 0
        assert quota.per_day >= quota.per_hour
        assert quota.cooldown_seconds >= 1


class TestDefaultDbPath:
    def test_default_path_is_under_project_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BOSS_DB_PATH", raising=False)
        path = get_default_db_path()
        assert path == PROJECT_ROOT / "boss_recruitment.db"

    def test_env_override_takes_precedence(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        custom = tmp_path / "custom.db"
        monkeypatch.setenv("BOSS_DB_PATH", str(custom))
        assert get_default_db_path() == custom.resolve()


class TestConfigFromEnv:
    def test_returns_defaults_when_no_env(self) -> None:
        cfg = Config.from_env()
        assert cfg.device_serial is None
        assert cfg.use_tcp is False
        assert cfg.droidrun_port == 8080
        assert cfg.timezone == "Asia/Shanghai"
        assert cfg.debug is False

    def test_picks_up_device_and_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BOSS_DEVICE_SERIAL", "EMU-7")
        monkeypatch.setenv("BOSS_USE_TCP", "true")
        monkeypatch.setenv("BOSS_DROIDRUN_PORT", "8085")
        cfg = Config.from_env()
        assert cfg.device_serial == "EMU-7"
        assert cfg.use_tcp is True
        assert cfg.droidrun_port == 8085

    def test_invalid_port_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BOSS_DROIDRUN_PORT", "not-a-port")
        cfg = Config.from_env()
        assert cfg.droidrun_port == 8080

    def test_debug_and_log_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BOSS_DEBUG", "1")
        monkeypatch.setenv("BOSS_LOG_FILE", "/tmp/boss.log")
        cfg = Config.from_env()
        assert cfg.debug is True
        assert cfg.log_file == "/tmp/boss.log"

    def test_timezone_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BOSS_TIMEZONE", "America/Los_Angeles")
        cfg = Config.from_env()
        assert cfg.timezone == "America/Los_Angeles"


class TestConfigWithOverrides:
    def test_override_known_attribute(self) -> None:
        cfg = Config().with_overrides(device_serial="EMU-9", droidrun_port=9999)
        assert cfg.device_serial == "EMU-9"
        assert cfg.droidrun_port == 9999

    def test_override_unknown_attribute_raises(self) -> None:
        with pytest.raises(AttributeError):
            Config().with_overrides(no_such_field=True)

    def test_overrides_do_not_mutate_original(self) -> None:
        original = Config()
        derived = original.with_overrides(droidrun_port=9001)
        assert original.droidrun_port == 8080
        assert derived.droidrun_port == 9001


class TestSubconfigDefaults:
    def test_timing_defaults_are_human_paced(self) -> None:
        timing = TimingConfig()
        assert timing.wait_after_launch >= 1.0
        assert timing.inter_message_min < timing.inter_message_max

    def test_scroll_defaults_have_threshold(self) -> None:
        scroll = ScrollConfig()
        assert scroll.stable_threshold >= 1
        assert scroll.max_scrolls > 0

    def test_timezone_default(self) -> None:
        assert TimezoneConfig().timezone == "Asia/Shanghai"
