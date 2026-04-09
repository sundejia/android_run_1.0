"""
Tests for DeviceManager - focusing on multi-device concurrent sync operations.

These tests verify:
1. Multiple devices can sync simultaneously without conflicts
2. Stop operation works reliably for any device
3. Staggered start prevents ADB conflicts
4. Process cleanup happens correctly
"""

import asyncio
import platform
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.device_manager import DeviceManager, SyncStatus


class MockProcess:
    """Mock asyncio subprocess for testing."""

    def __init__(self, serial: str, should_fail: bool = False, hang_on_terminate: bool = False):
        self.serial = serial
        self.should_fail = should_fail
        self.hang_on_terminate = hang_on_terminate
        self.returncode = None
        self._terminated = False
        self._killed = False
        self.stdout = self._create_mock_stream()
        self.stderr = self._create_mock_stream()

    def _create_mock_stream(self):
        """Create a mock stream that yields some log lines then ends."""
        stream = AsyncMock()
        stream._call_count = 0

        async def readline():
            stream._call_count += 1

            # Add delay to simulate real process behavior
            await asyncio.sleep(0.3)

            if stream._call_count == 1:
                return f"Starting sync for {self.serial}\n".encode()
            elif stream._call_count == 2:
                return b"Syncing customer 1/10\n"
            elif stream._call_count == 3:
                if self.should_fail:
                    return b"ERROR: Portal returned error\n"
                return b"Syncing customer 5/10\n"
            elif stream._call_count == 4:
                return b"SYNC COMPLETE\n"
            else:
                return b""  # EOF

        stream.readline = readline
        return stream

    def terminate(self):
        self._terminated = True
        if not self.hang_on_terminate:
            self.returncode = -15

    def kill(self):
        self._killed = True
        self.returncode = -9

    async def wait(self):
        if self.hang_on_terminate and not self._killed:
            # Simulate hanging - will timeout
            await asyncio.sleep(10)

        if self.returncode is None:
            self.returncode = 1 if self.should_fail else 0
        return self.returncode


@pytest.fixture
def device_manager():
    """Create a fresh DeviceManager for each test."""
    return DeviceManager()


@pytest.fixture
def mock_subprocess():
    """Mock subprocess creation."""
    processes = {}

    async def create_subprocess_exec(*args, **kwargs):
        # Extract serial from command args
        serial = None
        for i, arg in enumerate(args):
            if arg == "--serial" and i + 1 < len(args):
                serial = args[i + 1]
                break

        process = MockProcess(serial or "unknown")
        processes[serial] = process
        return process

    with patch("asyncio.create_subprocess_exec", side_effect=create_subprocess_exec):
        yield processes


class TestSingleDeviceSync:
    """Tests for single device sync operations."""

    @pytest.mark.asyncio
    async def test_start_sync_single_device(self, device_manager, mock_subprocess):
        """Test starting sync on a single device."""
        result = await device_manager.start_sync("DEVICE_A")

        assert result is True
        assert "DEVICE_A" in device_manager._processes

        state = device_manager.get_sync_state("DEVICE_A")
        assert state is not None
        assert state.status in (SyncStatus.STARTING, SyncStatus.RUNNING)

    @pytest.mark.asyncio
    async def test_stop_sync_single_device(self, device_manager, mock_subprocess):
        """Test stopping sync on a single device."""
        await device_manager.start_sync("DEVICE_A")

        # Give it a moment to start
        await asyncio.sleep(0.1)

        result = await device_manager.stop_sync("DEVICE_A")

        assert result is True
        state = device_manager.get_sync_state("DEVICE_A")
        assert state.status == SyncStatus.STOPPED

    @pytest.mark.asyncio
    async def test_stop_nonexistent_device(self, device_manager):
        """Test stopping sync on a device that isn't syncing."""
        result = await device_manager.stop_sync("NONEXISTENT")
        assert result is False


class TestMultiDeviceSync:
    """Tests for multi-device concurrent sync operations."""

    @pytest.mark.asyncio
    async def test_start_two_devices_simultaneously(self, device_manager, mock_subprocess):
        """Test starting sync on two devices at the same time."""
        # Start both devices
        result_a = await device_manager.start_sync("DEVICE_A")
        result_b = await device_manager.start_sync("DEVICE_B")

        assert result_a is True
        assert result_b is True

        # Both should have processes
        assert "DEVICE_A" in device_manager._processes
        assert "DEVICE_B" in device_manager._processes

        # Both should have states
        state_a = device_manager.get_sync_state("DEVICE_A")
        state_b = device_manager.get_sync_state("DEVICE_B")

        assert state_a is not None
        assert state_b is not None

    @pytest.mark.asyncio
    async def test_stop_one_device_while_other_runs(self, device_manager, mock_subprocess):
        """Test stopping one device while another continues running."""
        # Start both devices
        await device_manager.start_sync("DEVICE_A")
        await device_manager.start_sync("DEVICE_B")

        await asyncio.sleep(0.1)

        # Stop only device A
        result = await device_manager.stop_sync("DEVICE_A")

        assert result is True

        # Device A should be stopped
        state_a = device_manager.get_sync_state("DEVICE_A")
        assert state_a.status == SyncStatus.STOPPED

        # Device B should still be running
        state_b = device_manager.get_sync_state("DEVICE_B")
        assert state_b.status in (SyncStatus.STARTING, SyncStatus.RUNNING)
        assert "DEVICE_B" in device_manager._processes

    @pytest.mark.asyncio
    async def test_stop_all_devices(self, device_manager, mock_subprocess):
        """Test stopping all devices at once."""
        # Start multiple devices
        await device_manager.start_sync("DEVICE_A")
        await device_manager.start_sync("DEVICE_B")
        await device_manager.start_sync("DEVICE_C")

        await asyncio.sleep(0.1)

        # Stop all
        await device_manager.stop_all()

        # All should be stopped
        for serial in ["DEVICE_A", "DEVICE_B", "DEVICE_C"]:
            state = device_manager.get_sync_state(serial)
            assert state.status == SyncStatus.STOPPED

    @pytest.mark.asyncio
    async def test_devices_have_independent_states(self, device_manager, mock_subprocess):
        """Test that each device maintains independent state."""
        # Start devices with different timings
        await device_manager.start_sync("DEVICE_A")
        await asyncio.sleep(0.05)
        await device_manager.start_sync("DEVICE_B")

        # Update state for device A only
        state_a = device_manager.get_sync_state("DEVICE_A")
        state_a.progress = 50
        state_a.customers_synced = 5

        # Device B should not be affected
        state_b = device_manager.get_sync_state("DEVICE_B")
        assert state_b.progress != 50
        assert state_b.customers_synced != 5


class TestProcessCleanup:
    """Tests for process cleanup and error handling."""

    @pytest.mark.asyncio
    async def test_cleanup_after_stop(self, device_manager, mock_subprocess):
        """Test that processes are cleaned up after stop."""
        await device_manager.start_sync("DEVICE_A")
        await asyncio.sleep(0.1)

        await device_manager.stop_sync("DEVICE_A")

        # Process should be removed
        assert "DEVICE_A" not in device_manager._processes

    @pytest.mark.asyncio
    async def test_cannot_start_duplicate_sync(self, device_manager, mock_subprocess):
        """Test that starting sync twice on same device fails."""
        result1 = await device_manager.start_sync("DEVICE_A")
        assert result1 is True

        # Second start should fail
        result2 = await device_manager.start_sync("DEVICE_A")
        assert result2 is False

    @pytest.mark.asyncio
    async def test_can_restart_after_stop(self, device_manager, mock_subprocess):
        """Test that a device can be restarted after being stopped."""
        await device_manager.start_sync("DEVICE_A")
        await asyncio.sleep(0.1)
        await device_manager.stop_sync("DEVICE_A")

        # Should be able to start again
        result = await device_manager.start_sync("DEVICE_A")
        assert result is True


class TestLogCallbacks:
    """Tests for log callback functionality."""

    @pytest.mark.asyncio
    async def test_log_callbacks_per_device(self, device_manager, mock_subprocess):
        """Test that log callbacks are called for the correct device."""
        logs_a = []
        logs_b = []

        async def callback_a(log):
            logs_a.append(log)

        async def callback_b(log):
            logs_b.append(log)

        device_manager.register_log_callback("DEVICE_A", callback_a)
        device_manager.register_log_callback("DEVICE_B", callback_b)

        await device_manager.start_sync("DEVICE_A")
        await device_manager.start_sync("DEVICE_B")

        # Wait for some logs
        await asyncio.sleep(0.2)

        # Each device should have received its own logs
        assert len(logs_a) > 0
        assert len(logs_b) > 0

        # Logs should be independent
        assert logs_a != logs_b

    @pytest.mark.asyncio
    async def test_unregister_callback(self, device_manager, mock_subprocess):
        """Test that unregistered callbacks stop receiving logs."""
        logs = []

        async def callback(log):
            logs.append(log)

        device_manager.register_log_callback("DEVICE_A", callback)
        await device_manager.start_sync("DEVICE_A")

        await asyncio.sleep(0.1)
        initial_count = len(logs)

        device_manager.unregister_log_callback("DEVICE_A", callback)

        await asyncio.sleep(0.1)
        # Should not receive more logs after unregistering
        # (may receive a few more due to timing)
        assert len(logs) <= initial_count + 2


class TestStatusCallbacks:
    """Tests for status callback functionality."""

    @pytest.mark.asyncio
    async def test_status_callbacks_per_device(self, device_manager, mock_subprocess):
        """Test that status callbacks are called for the correct device."""
        statuses_a = []
        statuses_b = []

        async def callback_a(status):
            statuses_a.append(status)

        async def callback_b(status):
            statuses_b.append(status)

        device_manager.register_status_callback("DEVICE_A", callback_a)
        device_manager.register_status_callback("DEVICE_B", callback_b)

        await device_manager.start_sync("DEVICE_A")
        await device_manager.start_sync("DEVICE_B")

        await asyncio.sleep(0.1)

        # Each device should have received status updates
        assert len(statuses_a) > 0
        assert len(statuses_b) > 0


class TestConcurrentStopOperations:
    """Tests for concurrent stop operations - the main issue reported."""

    @pytest.mark.asyncio
    async def test_stop_both_devices_sequentially(self, device_manager, mock_subprocess):
        """Test stopping both devices one after another."""
        await device_manager.start_sync("DEVICE_A")
        await device_manager.start_sync("DEVICE_B")

        await asyncio.sleep(0.1)

        # Stop both sequentially
        result_a = await device_manager.stop_sync("DEVICE_A")
        result_b = await device_manager.stop_sync("DEVICE_B")

        assert result_a is True
        assert result_b is True

        # Both should be stopped
        assert device_manager.get_sync_state("DEVICE_A").status == SyncStatus.STOPPED
        assert device_manager.get_sync_state("DEVICE_B").status == SyncStatus.STOPPED

    @pytest.mark.asyncio
    async def test_stop_both_devices_concurrently(self, device_manager, mock_subprocess):
        """Test stopping both devices at the same time."""
        await device_manager.start_sync("DEVICE_A")
        await device_manager.start_sync("DEVICE_B")

        await asyncio.sleep(0.1)

        # Stop both concurrently
        results = await asyncio.gather(
            device_manager.stop_sync("DEVICE_A"),
            device_manager.stop_sync("DEVICE_B"),
        )

        assert results[0] is True
        assert results[1] is True

        # Both should be stopped
        assert device_manager.get_sync_state("DEVICE_A").status == SyncStatus.STOPPED
        assert device_manager.get_sync_state("DEVICE_B").status == SyncStatus.STOPPED

    @pytest.mark.asyncio
    async def test_stop_cleans_up_even_on_hang(self, device_manager):
        """Test that stop cleans up even if process hangs."""
        # Create a hanging process
        hanging_process = MockProcess("DEVICE_A", hang_on_terminate=True)

        async def create_hanging(*args, **kwargs):
            return hanging_process

        patch_target = (
            "services.device_manager.DeviceManager._create_subprocess_windows"
            if platform.system() == "Windows"
            else "asyncio.create_subprocess_exec"
        )

        with patch(patch_target, side_effect=create_hanging):
            await device_manager.start_sync("DEVICE_A")
            await asyncio.sleep(0.1)

            # Stop should eventually succeed by force killing
            result = await asyncio.wait_for(device_manager.stop_sync("DEVICE_A"), timeout=10.0)

            assert result is True
            if platform.system() == "Windows":
                assert hanging_process._terminated or hanging_process._killed
            else:
                assert hanging_process._killed is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
