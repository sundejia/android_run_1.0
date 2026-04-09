"""
Unit tests for configuration.
"""

import os

import pytest

from wecom_automation.core.config import (
    AppConfig,
    Config,
    RetryConfig,
    ScrollConfig,
    TimingConfig,
    UIParserConfig,
)


class TestAppConfig:
    """Tests for AppConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = AppConfig()
        assert config.package_name == "com.tencent.wework"
        assert "All" in config.all_text_patterns
        assert "全部" in config.all_text_patterns
        assert "Private Chats" in config.private_chats_patterns
        assert "私聊" in config.private_chats_patterns

    def test_immutability(self):
        """Test that AppConfig is immutable (frozen dataclass)."""
        from dataclasses import FrozenInstanceError

        config = AppConfig()
        with pytest.raises(FrozenInstanceError):
            config.package_name = "other.package"


class TestTimingConfig:
    """Tests for TimingConfig."""

    def test_default_values(self):
        """Test default timing values."""
        config = TimingConfig()
        assert config.wait_after_launch == 3.0
        assert config.scroll_delay == 1.0
        assert config.tap_delay == 0.5
        assert config.retry_delay == 1.5
        assert config.ui_stabilization_delay == 0.3

    def test_custom_values(self):
        """Test custom timing values."""
        config = TimingConfig(
            wait_after_launch=5.0,
            scroll_delay=2.0,
        )
        assert config.wait_after_launch == 5.0
        assert config.scroll_delay == 2.0


class TestScrollConfig:
    """Tests for ScrollConfig."""

    def test_default_values(self):
        """Test default scroll values."""
        config = ScrollConfig()
        assert config.max_scrolls == 20
        assert config.stable_threshold == 4
        assert config.scroll_distance == 600
        assert config.start_x == 540

    def test_custom_values(self):
        """Test custom scroll values."""
        config = ScrollConfig(
            max_scrolls=50,
            stable_threshold=5,
        )
        assert config.max_scrolls == 50
        assert config.stable_threshold == 5


class TestUIParserConfig:
    """Tests for UIParserConfig."""

    def test_default_values(self):
        """Test default UI parser values."""
        config = UIParserConfig()

        # Check class hints
        assert "recyclerview" in config.message_list_class_hints
        assert "listview" in config.message_list_class_hints

        # Check ID hints
        assert "conversation" in config.message_list_id_hints
        assert "message" in config.message_list_id_hints

        # Check field hints
        assert "title" in config.name_resource_id_hints
        assert "time" in config.date_resource_id_hints
        assert "content" in config.snippet_resource_id_hints

        # Check avatar hints
        assert "avatar" in config.avatar_resource_id_hints
        assert "imageview" in config.avatar_class_hints

    def test_dropdown_filter_patterns(self):
        """Test dropdown filter patterns include common values."""
        config = UIParserConfig()
        patterns = config.dropdown_filter_patterns
        assert "private" in patterns
        assert "all" in patterns
        assert "group" in patterns


class TestRetryConfig:
    """Tests for RetryConfig."""

    def test_default_values(self):
        """Test default retry values."""
        config = RetryConfig()
        assert config.max_retries == 4
        assert config.retry_delay == 1.5
        assert config.exponential_backoff is False
        assert config.backoff_multiplier == 2.0


class TestConfig:
    """Tests for main Config class."""

    def test_default_initialization(self):
        """Test default configuration initialization."""
        config = Config()

        # Check sub-configs are initialized
        assert isinstance(config.app, AppConfig)
        assert isinstance(config.timing, TimingConfig)
        assert isinstance(config.scroll, ScrollConfig)
        assert isinstance(config.ui_parser, UIParserConfig)
        assert isinstance(config.retry, RetryConfig)

        # Check defaults
        assert config.device_serial is None
        assert config.use_tcp is False
        assert config.debug is False
        assert config.output_dir == "."
        assert config.capture_avatars is False

    def test_custom_initialization(self):
        """Test configuration with custom values."""
        custom_timing = TimingConfig(wait_after_launch=10.0)
        config = Config(
            timing=custom_timing,
            device_serial="ABC123",
            use_tcp=True,
            debug=True,
        )

        assert config.timing.wait_after_launch == 10.0
        assert config.device_serial == "ABC123"
        assert config.use_tcp is True
        assert config.debug is True

    def test_from_env_basic(self):
        """Test loading config from environment variables."""
        # Set environment variables
        os.environ["WECOM_DEVICE_SERIAL"] = "test-device"
        os.environ["WECOM_USE_TCP"] = "true"
        os.environ["WECOM_DEBUG"] = "1"

        try:
            config = Config.from_env()
            assert config.device_serial == "test-device"
            assert config.use_tcp is True
            assert config.debug is True
        finally:
            # Clean up
            del os.environ["WECOM_DEVICE_SERIAL"]
            del os.environ["WECOM_USE_TCP"]
            del os.environ["WECOM_DEBUG"]

    def test_from_env_with_numbers(self):
        """Test loading numeric values from environment."""
        os.environ["WECOM_WAIT_AFTER_LAUNCH"] = "5.5"
        os.environ["WECOM_MAX_SCROLLS"] = "30"

        try:
            config = Config.from_env()
            assert config.timing.wait_after_launch == 5.5
            assert config.scroll.max_scrolls == 30
        finally:
            del os.environ["WECOM_WAIT_AFTER_LAUNCH"]
            del os.environ["WECOM_MAX_SCROLLS"]

    def test_from_env_invalid_values(self):
        """Test handling invalid environment values."""
        os.environ["WECOM_WAIT_AFTER_LAUNCH"] = "not-a-number"
        os.environ["WECOM_MAX_SCROLLS"] = "invalid"

        try:
            config = Config.from_env()
            # Should fall back to defaults
            assert config.timing.wait_after_launch == 3.0
            assert config.scroll.max_scrolls == 20
        finally:
            del os.environ["WECOM_WAIT_AFTER_LAUNCH"]
            del os.environ["WECOM_MAX_SCROLLS"]

    def test_with_overrides(self):
        """Test creating config with overrides."""
        original = Config(debug=False, output_dir="./original")
        modified = original.with_overrides(
            debug=True,
            output_dir="./modified",
        )

        # Original should be unchanged
        assert original.debug is False
        assert original.output_dir == "./original"

        # Modified should have new values
        assert modified.debug is True
        assert modified.output_dir == "./modified"

        # Other values should be preserved
        assert modified.use_tcp == original.use_tcp
