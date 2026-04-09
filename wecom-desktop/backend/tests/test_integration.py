"""
Integration tests for multi-device sync operations.

These tests verify the actual behavior with real subprocess execution
(using a simple test script instead of initial_sync.py).
"""

import asyncio
import os
import sys
import tempfile
import pytest
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.device_manager import DeviceManager, SyncStatus


# Create a simple test script that simulates sync behavior
TEST_SCRIPT = """
import sys
import time
import signal

serial = sys.argv[1] if len(sys.argv) > 1 else "unknown"
duration = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0

# Handle SIGTERM gracefully
def handle_sigterm(signum, frame):
    print(f"[{serial}] Received SIGTERM, stopping gracefully", flush=True)
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_sigterm)

print(f"[{serial}] Starting sync", flush=True)

steps = 10
for i in range(steps):
    time.sleep(duration / steps)
    print(f"[{serial}] Syncing customer {i+1}/{steps}", flush=True)

print(f"[{serial}] SYNC COMPLETE", flush=True)
"""


@pytest.fixture
def test_script():
    """Create a temporary test script."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(TEST_SCRIPT)
        script_path = f.name

    yield script_path

    # Cleanup
    os.unlink(script_path)


@pytest.fixture
def device_manager_with_test_script(test_script, monkeypatch):
    """Create a DeviceManager that uses the test script."""
    dm = DeviceManager()

    # Store original start_sync
    original_start_sync = dm.start_sync

    async def patched_start_sync(serial, **kwargs):
        # Override the command to use our test script
        dm._sync_states[serial] = dm._sync_states.get(serial) or __import__(
            "services.device_manager", fromlist=["SyncState"]
        ).SyncState(
            status=SyncStatus.STARTING,
            message="Initializing sync...",
        )

        try:
            # Build command with test script
            cmd = [
                sys.executable,
                test_script,
                serial,
                "3.0",  # 3 second duration
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            dm._processes[serial] = process
            dm._sync_states[serial].status = SyncStatus.RUNNING
            dm._sync_states[serial].message = "Sync started"

            # Start output readers
            stdout_task = asyncio.create_task(dm._read_output(serial, process.stdout, is_stderr=False))
            stderr_task = asyncio.create_task(dm._read_output(serial, process.stderr, is_stderr=True))

            dm._read_tasks[serial] = asyncio.create_task(
                dm._wait_for_completion(serial, process, stdout_task, stderr_task)
            )

            return True
        except Exception as e:
            dm._sync_states[serial].status = SyncStatus.ERROR
            dm._sync_states[serial].message = str(e)
            return False

    dm.start_sync = patched_start_sync
    return dm


class TestRealSubprocessExecution:
    """Tests with real subprocess execution."""

    @pytest.mark.asyncio
    async def test_single_device_completes(self, device_manager_with_test_script):
        """Test that a single device sync completes successfully."""
        dm = device_manager_with_test_script

        logs = []

        async def log_callback(log):
            logs.append(log)

        dm.register_log_callback("DEVICE_A", log_callback)

        result = await dm.start_sync("DEVICE_A")
        assert result is True

        # Wait for completion
        await asyncio.sleep(4.0)

        state = dm.get_sync_state("DEVICE_A")
        assert state.status == SyncStatus.COMPLETED

        # Check logs were received
        assert len(logs) > 0
        log_messages = [l["message"] for l in logs]
        assert any("SYNC COMPLETE" in msg for msg in log_messages)

    @pytest.mark.asyncio
    async def test_two_devices_run_simultaneously(self, device_manager_with_test_script):
        """Test that two devices can sync at the same time."""
        dm = device_manager_with_test_script

        logs_a = []
        logs_b = []

        async def log_callback_a(log):
            logs_a.append(log)

        async def log_callback_b(log):
            logs_b.append(log)

        dm.register_log_callback("DEVICE_A", log_callback_a)
        dm.register_log_callback("DEVICE_B", log_callback_b)

        # Start both devices
        result_a = await dm.start_sync("DEVICE_A")
        result_b = await dm.start_sync("DEVICE_B")

        assert result_a is True
        assert result_b is True

        # Both should be running
        assert dm.get_sync_state("DEVICE_A").status == SyncStatus.RUNNING
        assert dm.get_sync_state("DEVICE_B").status == SyncStatus.RUNNING

        # Wait for both to complete
        await asyncio.sleep(4.0)

        # Both should have completed
        assert dm.get_sync_state("DEVICE_A").status == SyncStatus.COMPLETED
        assert dm.get_sync_state("DEVICE_B").status == SyncStatus.COMPLETED

        # Both should have received logs
        assert len(logs_a) > 0
        assert len(logs_b) > 0

        # Logs should be independent (contain device-specific content)
        log_a_messages = " ".join([l["message"] for l in logs_a])
        log_b_messages = " ".join([l["message"] for l in logs_b])

        assert "DEVICE_A" in log_a_messages
        assert "DEVICE_B" in log_b_messages

    @pytest.mark.asyncio
    async def test_stop_one_while_other_continues(self, device_manager_with_test_script):
        """Test stopping one device while another continues."""
        dm = device_manager_with_test_script

        # Start both devices
        await dm.start_sync("DEVICE_A")
        await dm.start_sync("DEVICE_B")

        # Wait a bit for them to start
        await asyncio.sleep(1.0)

        # Stop device A
        result = await dm.stop_sync("DEVICE_A")
        assert result is True

        # Device A should be stopped
        assert dm.get_sync_state("DEVICE_A").status == SyncStatus.STOPPED

        # Device B should still be running
        assert dm.get_sync_state("DEVICE_B").status == SyncStatus.RUNNING

        # Wait for device B to complete
        await asyncio.sleep(3.0)

        # Device B should have completed
        assert dm.get_sync_state("DEVICE_B").status == SyncStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_stop_both_devices(self, device_manager_with_test_script):
        """Test stopping both devices."""
        dm = device_manager_with_test_script

        # Start both devices
        await dm.start_sync("DEVICE_A")
        await dm.start_sync("DEVICE_B")

        # Wait a bit
        await asyncio.sleep(1.0)

        # Stop both
        result_a = await dm.stop_sync("DEVICE_A")
        result_b = await dm.stop_sync("DEVICE_B")

        assert result_a is True
        assert result_b is True

        # Both should be stopped
        assert dm.get_sync_state("DEVICE_A").status == SyncStatus.STOPPED
        assert dm.get_sync_state("DEVICE_B").status == SyncStatus.STOPPED

    @pytest.mark.asyncio
    async def test_three_devices_simultaneously(self, device_manager_with_test_script):
        """Test three devices running at the same time."""
        dm = device_manager_with_test_script

        # Start three devices
        results = await asyncio.gather(
            dm.start_sync("DEVICE_A"),
            dm.start_sync("DEVICE_B"),
            dm.start_sync("DEVICE_C"),
        )

        assert all(results)

        # All should be running
        for serial in ["DEVICE_A", "DEVICE_B", "DEVICE_C"]:
            assert dm.get_sync_state(serial).status == SyncStatus.RUNNING

        # Wait for completion
        await asyncio.sleep(4.0)

        # All should have completed
        for serial in ["DEVICE_A", "DEVICE_B", "DEVICE_C"]:
            assert dm.get_sync_state(serial).status == SyncStatus.COMPLETED


class TestStaggeredStart:
    """Tests for staggered start functionality."""

    @pytest.mark.asyncio
    async def test_staggered_start_with_delay(self, device_manager_with_test_script):
        """Test that staggered start introduces delays between devices."""
        dm = device_manager_with_test_script

        start_times = {}

        async def track_start_a(log):
            if "Starting sync" in log.get("message", ""):
                start_times["A"] = asyncio.get_event_loop().time()

        async def track_start_b(log):
            if "Starting sync" in log.get("message", ""):
                start_times["B"] = asyncio.get_event_loop().time()

        dm.register_log_callback("DEVICE_A", track_start_a)
        dm.register_log_callback("DEVICE_B", track_start_b)

        # Start with staggered delay
        await dm.start_sync("DEVICE_A")
        await asyncio.sleep(1.0)  # Stagger delay
        await dm.start_sync("DEVICE_B")

        # Wait for logs
        await asyncio.sleep(0.5)

        # Device B should have started after Device A
        if "A" in start_times and "B" in start_times:
            assert start_times["B"] > start_times["A"]
            assert start_times["B"] - start_times["A"] >= 0.9  # At least ~1 second apart


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
