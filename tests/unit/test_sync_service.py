"""
Unit tests for the sync service.

These tests cover:
- HumanTiming delay generation
- VoiceHandlerAction enum
- Message processing logic
"""

import os
import tempfile

import pytest

from wecom_automation.core.models import ConversationMessage
from wecom_automation.database.models import MessageType
from wecom_automation.services.sync_service import (
    HumanTiming,
    InitialSyncService,
    VoiceHandlerAction,
)

# =============================================================================
# HumanTiming Tests
# =============================================================================


class TestHumanTiming:
    """Tests for HumanTiming delay generator."""

    def test_default_multiplier(self):
        """Test default timing multiplier is 1.0."""
        timing = HumanTiming()
        assert timing.multiplier == 1.0

    def test_tap_delay_in_range(self):
        """Test tap delay is within expected range."""
        timing = HumanTiming()
        for _ in range(100):
            delay = timing.get_tap_delay()
            assert 0.5 <= delay <= 2.0

    def test_scroll_delay_in_range(self):
        """Test scroll delay is within expected range."""
        timing = HumanTiming()
        for _ in range(100):
            delay = timing.get_scroll_delay()
            assert 1.0 <= delay <= 3.0

    def test_type_delay_in_range(self):
        """Test type delay is within expected range."""
        timing = HumanTiming()
        for _ in range(100):
            delay = timing.get_type_delay()
            assert 0.3 <= delay <= 1.0

    def test_user_switch_delay_in_range(self):
        """Test user switch delay is within expected range."""
        timing = HumanTiming()
        for _ in range(100):
            delay = timing.get_user_switch_delay()
            assert 3.0 <= delay <= 5.0

    def test_read_delay_in_range(self):
        """Test read delay is within expected range."""
        timing = HumanTiming()
        for _ in range(100):
            delay = timing.get_read_delay()
            assert 1.0 <= delay <= 2.0

    def test_scroll_distance_in_range(self):
        """Test scroll distance is within expected range."""
        timing = HumanTiming()
        for _ in range(100):
            distance = timing.get_scroll_distance()
            assert 500 <= distance <= 700

    def test_multiplier_affects_delays(self):
        """Test that multiplier scales delays."""
        timing_slow = HumanTiming(multiplier=2.0)
        timing_fast = HumanTiming(multiplier=0.5)

        # Get average delays
        slow_delays = [timing_slow.get_tap_delay() for _ in range(50)]
        fast_delays = [timing_fast.get_tap_delay() for _ in range(50)]

        avg_slow = sum(slow_delays) / len(slow_delays)
        avg_fast = sum(fast_delays) / len(fast_delays)

        # Slow should be roughly 4x the fast (2.0 / 0.5 = 4)
        # Allow some variance due to randomness
        assert avg_slow > avg_fast * 2

    def test_delays_are_random(self):
        """Test that delays vary between calls."""
        timing = HumanTiming()
        delays = [timing.get_tap_delay() for _ in range(10)]

        # Not all delays should be the same
        unique_delays = set(delays)
        assert len(unique_delays) > 1


# =============================================================================
# VoiceHandlerAction Tests
# =============================================================================


class TestVoiceHandlerAction:
    """Tests for VoiceHandlerAction enum."""

    def test_enum_values(self):
        """Test all enum values exist."""
        assert VoiceHandlerAction.CAPTION == "caption"
        assert VoiceHandlerAction.INPUT == "input"
        assert VoiceHandlerAction.PLACEHOLDER == "placeholder"
        assert VoiceHandlerAction.SKIP == "skip"

    def test_string_comparison(self):
        """Test enum can be compared with strings."""
        assert VoiceHandlerAction.CAPTION == "caption"
        assert VoiceHandlerAction.INPUT == "input"


# =============================================================================
# InitialSyncService Tests
# =============================================================================


@pytest.fixture
def temp_db_path():
    """Create a temporary database file path."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(db_path)
    yield db_path
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def temp_images_dir():
    """Create a temporary images directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


class TestInitialSyncServiceInit:
    """Tests for InitialSyncService initialization."""

    def test_creates_repository(self, temp_db_path, temp_images_dir):
        """Test that repository is created automatically."""
        sync = InitialSyncService(
            db_path=temp_db_path,
            images_dir=temp_images_dir,
        )
        assert sync.repository is not None

    def test_creates_images_directory(self, temp_db_path, temp_images_dir):
        """Test that images directory is created."""
        import shutil

        shutil.rmtree(temp_images_dir, ignore_errors=True)

        InitialSyncService(
            db_path=temp_db_path,
            images_dir=temp_images_dir,
        )

        assert os.path.exists(temp_images_dir)

    def test_timing_multiplier(self, temp_db_path, temp_images_dir):
        """Test timing multiplier is set."""
        sync = InitialSyncService(
            db_path=temp_db_path,
            images_dir=temp_images_dir,
            timing_multiplier=2.0,
        )
        assert sync.timing.multiplier == 2.0


class TestVoiceHandlerCallback:
    """Tests for voice handler callback."""

    def test_set_callback(self, temp_db_path, temp_images_dir):
        """Test setting voice handler callback."""
        sync = InitialSyncService(
            db_path=temp_db_path,
            images_dir=temp_images_dir,
        )

        def my_callback(msg):
            return VoiceHandlerAction.PLACEHOLDER, None

        sync.set_voice_handler_callback(my_callback)
        assert sync._voice_handler_callback is not None

    @pytest.mark.asyncio
    async def test_voice_message_with_content_uses_content(self, temp_db_path, temp_images_dir):
        """Test voice message with existing content doesn't need callback."""
        sync = InitialSyncService(
            db_path=temp_db_path,
            images_dir=temp_images_dir,
        )

        msg = ConversationMessage(
            content="这是语音转文字",
            message_type="voice",
            is_self=False,
            voice_duration='3"',
        )

        content, extra_info = await sync._handle_voice_message(msg)

        assert content == "这是语音转文字"
        assert extra_info.get("source") == "transcription"

    @pytest.mark.asyncio
    async def test_voice_message_no_content_uses_placeholder(self, temp_db_path, temp_images_dir):
        """Test voice message without content uses placeholder when no callback."""
        sync = InitialSyncService(
            db_path=temp_db_path,
            images_dir=temp_images_dir,
        )

        msg = ConversationMessage(
            content=None,
            message_type="voice",
            is_self=False,
            voice_duration='5"',
        )

        content, extra_info = await sync._handle_voice_message(msg)

        assert content == "[Voice Message]"
        assert extra_info.get("source") == "placeholder_no_callback"

    @pytest.mark.asyncio
    async def test_voice_message_callback_input(self, temp_db_path, temp_images_dir):
        """Test voice message with INPUT callback."""
        sync = InitialSyncService(
            db_path=temp_db_path,
            images_dir=temp_images_dir,
        )

        def callback(msg):
            return VoiceHandlerAction.INPUT, "用户手动输入的文字"

        sync.set_voice_handler_callback(callback)

        msg = ConversationMessage(
            content=None,
            message_type="voice",
            is_self=False,
            voice_duration='3"',
        )

        content, extra_info = await sync._handle_voice_message(msg)

        assert content == "用户手动输入的文字"
        assert extra_info.get("source") == "user_input"

    @pytest.mark.asyncio
    async def test_voice_message_callback_skip(self, temp_db_path, temp_images_dir):
        """Test voice message with SKIP callback."""
        sync = InitialSyncService(
            db_path=temp_db_path,
            images_dir=temp_images_dir,
        )

        def callback(msg):
            return VoiceHandlerAction.SKIP, None

        sync.set_voice_handler_callback(callback)

        msg = ConversationMessage(
            content=None,
            message_type="voice",
            is_self=False,
        )

        content, extra_info = await sync._handle_voice_message(msg)

        assert content is None
        assert extra_info == {}

    @pytest.mark.asyncio
    async def test_voice_message_callback_placeholder(self, temp_db_path, temp_images_dir):
        """Test voice message with PLACEHOLDER callback."""
        sync = InitialSyncService(
            db_path=temp_db_path,
            images_dir=temp_images_dir,
        )

        def callback(msg):
            return VoiceHandlerAction.PLACEHOLDER, None

        sync.set_voice_handler_callback(callback)

        msg = ConversationMessage(
            content=None,
            message_type="voice",
            is_self=False,
        )

        content, extra_info = await sync._handle_voice_message(msg)

        assert content == "[Voice Message]"
        assert extra_info.get("source") == "placeholder"


class TestMessageProcessing:
    """Tests for message processing logic."""

    @pytest.mark.asyncio
    async def test_process_text_message(self, temp_db_path, temp_images_dir):
        """Test processing a text message."""
        sync = InitialSyncService(
            db_path=temp_db_path,
            images_dir=temp_images_dir,
        )

        # Setup device and kefu
        device = sync.repository.get_or_create_device("test_device")
        kefu = sync.repository.get_or_create_kefu("测试客服", device.id)
        customer = sync.repository.get_or_create_customer("测试客户", kefu.id)

        sync._current_device = device
        sync._current_kefu = kefu

        msg = ConversationMessage(
            content="Hello, this is a test message",
            message_type="text",
            is_self=True,
            timestamp="10:30",
        )

        result = await sync._process_and_store_message(msg, customer)

        assert result["added"] is True
        assert result["is_voice"] is False

        # Verify message was stored
        messages = sync.repository.get_messages_for_customer(customer.id)
        assert len(messages) == 1
        assert messages[0].content == "Hello, this is a test message"

    @pytest.mark.asyncio
    async def test_process_duplicate_message(self, temp_db_path, temp_images_dir):
        """Test that duplicate messages are skipped."""
        sync = InitialSyncService(
            db_path=temp_db_path,
            images_dir=temp_images_dir,
        )

        device = sync.repository.get_or_create_device("test_device")
        kefu = sync.repository.get_or_create_kefu("测试客服", device.id)
        customer = sync.repository.get_or_create_customer("测试客户", kefu.id)

        msg = ConversationMessage(
            content="Duplicate message",
            message_type="text",
            is_self=False,
            timestamp="10:30",
        )

        # Process twice
        result1 = await sync._process_and_store_message(msg, customer)
        result2 = await sync._process_and_store_message(msg, customer)

        assert result1["added"] is True
        assert result2["added"] is False

        # Only one message should be stored
        messages = sync.repository.get_messages_for_customer(customer.id)
        assert len(messages) == 1

    @pytest.mark.asyncio
    async def test_process_voice_message_with_content(self, temp_db_path, temp_images_dir):
        """Test processing a voice message with transcription."""
        sync = InitialSyncService(
            db_path=temp_db_path,
            images_dir=temp_images_dir,
        )

        device = sync.repository.get_or_create_device("test_device")
        kefu = sync.repository.get_or_create_kefu("测试客服", device.id)
        customer = sync.repository.get_or_create_customer("测试客户", kefu.id)

        msg = ConversationMessage(
            content="语音转文字内容",
            message_type="voice",
            is_self=False,
            voice_duration='5"',
        )

        result = await sync._process_and_store_message(msg, customer)

        assert result["added"] is True
        assert result["is_voice"] is True

        # Verify message was stored with correct type
        messages = sync.repository.get_messages_for_customer(customer.id)
        assert len(messages) == 1
        assert messages[0].message_type == MessageType.VOICE
        assert messages[0].content == "语音转文字内容"
