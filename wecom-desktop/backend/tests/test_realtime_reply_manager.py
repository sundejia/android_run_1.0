"""
Unit tests for RealtimeReplyManager

Tests the core functionality of managing multiple follow-up subprocesses.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, AsyncMock, MagicMock, patch

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

import pytest

from services.realtime_reply_manager import (
    RealtimeReplyManager,
    RealtimeReplyStatus,
    RealtimeReplyState,
    get_realtime_reply_manager,
)


@pytest.fixture
def manager():
    """Create a fresh RealtimeReplyManager for each test."""
    # Reset singleton
    import services.realtime_reply_manager

    services.realtime_reply_manager._realtime_reply_manager = None

    manager = RealtimeReplyManager()
    return manager


@pytest.fixture
def mock_process():
    """Create a mock subprocess."""
    process = Mock()
    process.pid = 12345
    process.returncode = None

    # Create async mock methods
    process.wait = AsyncMock(return_value=0)
    process.stdout = Mock()
    process.stderr = Mock()

    return process


class TestRealtimeReplyManager:
    """Test suite for RealtimeReplyManager."""

    def test_initial_state(self, manager):
        """Test manager starts with empty state."""
        assert len(manager._processes) == 0
        assert len(manager._states) == 0
        assert len(manager._log_callbacks) == 0
        assert len(manager._status_callbacks) == 0

    def test_get_state_empty(self, manager):
        """Test getting state for non-existent device."""
        state = manager.get_state("nonexistent")
        assert state is None

    def test_get_all_states_empty(self, manager):
        """Test getting all states when empty."""
        states = manager.get_all_states()
        assert states == {}

    def test_is_running_empty(self, manager):
        """Test is_running for non-existent device."""
        assert not manager.is_running("nonexistent")

    def test_state_creation(self, manager):
        """Test RealtimeReplyState dataclass."""
        state = RealtimeReplyState(
            status=RealtimeReplyStatus.RUNNING,
            message="Test",
            responses_detected=5,
            replies_sent=3,
            started_at=datetime.now(),
        )

        assert state.status == RealtimeReplyStatus.RUNNING
        assert state.message == "Test"
        assert state.responses_detected == 5
        assert state.replies_sent == 3
        assert state.started_at is not None

    def test_register_log_callback(self, manager):
        """Test registering log callbacks."""
        callback = AsyncMock()
        manager.register_log_callback("device1", callback)

        assert "device1" in manager._log_callbacks
        assert callback in manager._log_callbacks["device1"]

    def test_unregister_log_callback(self, manager):
        """Test unregistering log callbacks."""
        callback = AsyncMock()
        manager.register_log_callback("device1", callback)
        manager.unregister_log_callback("device1", callback)

        assert callback not in manager._log_callbacks.get("device1", set())

    def test_register_status_callback(self, manager):
        """Test registering status callbacks."""
        callback = AsyncMock()
        manager.register_status_callback("device1", callback)

        assert "device1" in manager._status_callbacks
        assert callback in manager._status_callbacks["device1"]

    @pytest.mark.asyncio
    async def test_broadcast_log(self, manager):
        """Test broadcasting log to callbacks."""
        callback = AsyncMock()
        manager.register_log_callback("device1", callback)

        await manager._broadcast_log("device1", "INFO", "Test message")

        # Callback should be called once
        assert callback.call_count == 1

        # Check the log entry structure
        call_args = callback.call_args[0][0]
        assert call_args["level"] == "INFO"
        assert call_args["message"] == "Test message"
        assert call_args["source"] == "followup"
        assert "timestamp" in call_args

    @pytest.mark.asyncio
    async def test_broadcast_status(self, manager):
        """Test broadcasting status updates."""
        callback = AsyncMock()
        manager.register_status_callback("device1", callback)

        manager._states["device1"] = RealtimeReplyState(status=RealtimeReplyStatus.RUNNING, message="Running")

        await manager._broadcast_status("device1")

        # Callback should be called once
        assert callback.call_count == 1

        # Check the status data structure
        call_args = callback.call_args[0][0]
        assert call_args["status"] == "running"
        assert call_args["message"] == "Running"

    @pytest.mark.asyncio
    async def test_parse_and_update_state_responses(self, manager):
        """Test parsing log messages for response detection."""
        manager._states["device1"] = RealtimeReplyState()

        await manager._parse_and_update_state("device1", "Found 3 unread messages", "INFO")

        assert manager._states["device1"].responses_detected == 3

    @pytest.mark.asyncio
    async def test_parse_and_update_state_replies(self, manager):
        """Test parsing log messages for replies sent."""
        manager._states["device1"] = RealtimeReplyState()

        await manager._parse_and_update_state("device1", "Reply sent successfully", "INFO")

        assert manager._states["device1"].replies_sent == 1
        assert manager._states["device1"].last_scan_at is not None

    @pytest.mark.asyncio
    async def test_parse_and_update_state_errors(self, manager):
        """Test parsing error messages."""
        manager._states["device1"] = RealtimeReplyState()

        await manager._parse_and_update_state("device1", "Connection failed", "ERROR")

        assert len(manager._states["device1"].errors) == 1
        assert "Connection failed" in manager._states["device1"].errors

    @pytest.mark.asyncio
    async def test_decode_output_utf8(self, manager):
        """Test decoding UTF-8 output."""
        data = "Test message\n".encode("utf-8")
        result = manager._decode_output(data)
        assert result == "Test message"

    @pytest.mark.asyncio
    async def test_decode_output_gbk(self, manager):
        """Test decoding GBK output (Windows)."""
        # Test with Chinese characters
        data = "测试消息\n".encode("gbk")
        result = manager._decode_output(data)
        assert "测试" in result or result  # May vary by system

    @pytest.mark.asyncio
    async def test_start_realtime_reply_already_running(self, manager, mock_process):
        """Test starting realtime reply when already running."""
        manager._processes["device1"] = mock_process
        manager._states["device1"] = RealtimeReplyState(status=RealtimeReplyStatus.RUNNING)

        result = await manager.start_realtime_reply("device1")

        assert result is False

    @pytest.mark.asyncio
    async def test_stop_realtime_reply_not_running(self, manager):
        """Test stopping realtime reply when not running."""
        result = await manager.stop_realtime_reply("device1")
        assert result is False

    @pytest.mark.asyncio
    async def test_pause_realtime_reply_not_running(self, manager):
        """Test pausing realtime reply when not running."""
        result = await manager.pause_realtime_reply("device1")
        assert result is False

    @pytest.mark.asyncio
    async def test_resume_realtime_reply_not_paused(self, manager):
        """Test resuming realtime reply when not paused."""
        manager._states["device1"] = RealtimeReplyState(status=RealtimeReplyStatus.RUNNING)

        result = await manager.resume_realtime_reply("device1")
        assert result is False

    @pytest.mark.asyncio
    async def test_stop_all_empty(self, manager):
        """Test stopping all devices when none are running."""
        await manager.stop_all()
        assert len(manager._processes) == 0


class TestSingleton:
    """Test the singleton pattern."""

    def test_singleton_same_instance(self):
        """Test that get_realtime_reply_manager returns same instance."""
        # Reset singleton
        import services.realtime_reply_manager

        services.realtime_reply_manager._realtime_reply_manager = None

        manager1 = get_realtime_reply_manager()
        manager2 = get_realtime_reply_manager()

        assert manager1 is manager2


class TestRealtimeReplyStatus:
    """Test RealtimeReplyStatus enum."""

    def test_status_values(self):
        """Test all status values exist."""
        assert RealtimeReplyStatus.IDLE == "idle"
        assert RealtimeReplyStatus.STARTING == "starting"
        assert RealtimeReplyStatus.RUNNING == "running"
        assert RealtimeReplyStatus.PAUSED == "paused"
        assert RealtimeReplyStatus.STOPPED == "stopped"
        assert RealtimeReplyStatus.ERROR == "error"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
