"""
Device Manager - Orchestrates sync operations across multiple devices.

This service provides:
- Per-device subprocess isolation for sync operations
- Real-time log streaming via callbacks
- Sync state management and progress tracking
- Graceful process termination
"""

import asyncio
import os
import platform
import re
import subprocess
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

# Windows doesn't have SIGSTOP/SIGCONT, so we need conditional imports
if platform.system() != "Windows":
    import signal
else:
    signal = None  # type: ignore

# Windows Job Objects for pause/resume functionality
if platform.system() == "Windows":
    try:
        from utils.windows_job import get_job_manager
    except ImportError:
        # Fallback for when running from project root
        from backend.utils.windows_job import get_job_manager

# Get project root for script paths
from services.conversation_storage import (
    get_device_conversation_db_path,
    get_device_storage_root,
)
from utils.path_utils import get_project_root
from wecom_automation.core.config import get_default_db_path
from wecom_automation.core.performance import runtime_metrics

PROJECT_ROOT = get_project_root()


class _WindowsProcessWrapper:
    """Wrapper to make subprocess.Popen compatible with asyncio.subprocess.Process interface."""

    def __init__(self, popen: subprocess.Popen):
        self._popen = popen
        self.stdout = _AsyncStreamReader(popen.stdout)
        self.stderr = _AsyncStreamReader(popen.stderr)
        self.pid = popen.pid

    @property
    def returncode(self):
        return self._popen.returncode

    async def wait(self):
        """Wait for process to complete."""
        return await asyncio.to_thread(self._popen.wait)

    def terminate(self):
        """Terminate the process."""
        self._popen.terminate()

    def kill(self):
        """Kill the process."""
        self._popen.kill()


class _AsyncStreamReader:
    """Wrapper to make synchronous stream readable in async context."""

    def __init__(self, stream):
        self._stream = stream

    async def readline(self) -> bytes:
        """Read a line from the stream."""
        if self._stream is None:
            return b""
        return await asyncio.to_thread(self._stream.readline)


class SyncStatus(str, Enum):
    """Sync operation status."""

    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class SyncState:
    """State of a sync operation for a device."""

    status: SyncStatus = SyncStatus.IDLE
    progress: int = 0
    message: str = ""
    customers_synced: int = 0
    messages_added: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None


LogCallback = Callable[[dict], Coroutine[Any, Any, None]]
StatusCallback = Callable[[dict], Coroutine[Any, Any, None]]


class PortAllocator:
    """
    Allocates unique DroidRun TCP ports for multi-device support.

    Each device needs a unique port (8080, 8090, 8100, ...) to avoid conflicts
    when running multiple sync operations in parallel.

    Port assignment is based on device serial hash to ensure consistent
    port allocation across restarts.
    """

    BASE_PORT = 8080
    MAX_PORT = 8180
    PORT_STEP = 10  # Step between ports

    _instance = None
    _allocations: dict[str, int] = {}  # serial -> port
    _used_ports: set[int] = set()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def allocate(self, serial: str) -> int:
        """
        Allocate a unique port for a device.

        Args:
            serial: Device serial number

        Returns:
            Allocated port number
        """
        # Return existing allocation if any
        if serial in self._allocations:
            return self._allocations[serial]

        # Calculate port based on serial hash for consistency
        hash_offset = abs(hash(serial)) % 10
        port = self.BASE_PORT + (hash_offset * self.PORT_STEP)

        # Find next available port if collision
        while port in self._used_ports and port < self.MAX_PORT:
            port += self.PORT_STEP

        if port >= self.MAX_PORT:
            # Fallback: find any available port
            port = self.BASE_PORT
            while port in self._used_ports:
                port += 1
                if port >= self.MAX_PORT:
                    raise RuntimeError("No available ports in range 8080-8180")

        self._allocations[serial] = port
        self._used_ports.add(port)
        return port

    def release(self, serial: str) -> None:
        """
        Release a device's port allocation.

        Args:
            serial: Device serial number
        """
        if serial in self._allocations:
            port = self._allocations.pop(serial)
            self._used_ports.discard(port)

    def get_allocation(self, serial: str) -> int | None:
        """Get the port allocated to a device, if any."""
        return self._allocations.get(serial)

    def clear_all(self) -> None:
        """Clear all port allocations."""
        self._allocations.clear()
        self._used_ports.clear()


# Global port allocator instance
_port_allocator = PortAllocator()


class DeviceManager:
    """
    Manages sync operations for multiple devices.

    Each device runs in an isolated subprocess to prevent interference.
    Logs and status updates are streamed in real-time via callbacks.
    """

    def __init__(self):
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._sync_states: dict[str, SyncState] = {}
        self._log_callbacks: dict[str, set[LogCallback]] = {}
        self._status_callbacks: dict[str, set[StatusCallback]] = {}
        self._read_tasks: dict[str, asyncio.Task] = {}
        self._db_paths: dict[str, str] = {}

    @staticmethod
    def _sanitize_serial_for_path(serial: str) -> str:
        """Create a filesystem-safe path segment for a device serial."""
        sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", serial).strip("._-")
        return sanitized or "unknown-device"

    def _get_device_output_root(self, serial: str) -> Path:
        """Return the per-device runtime storage root under the project."""
        return get_device_storage_root(serial)

    def _resolve_storage_paths(self, serial: str, images_dir: str | None) -> tuple[Path, Path, Path, Path]:
        """
        Resolve storage paths for a device.

        When the caller does not specify an image directory, default to a
        per-device storage root to avoid media files from concurrent devices
        landing in the same runtime directory.
        """
        if images_dir:
            image_path = Path(images_dir)
            output_root = image_path.parent
            resolved_images_path = image_path
        else:
            output_root = self._get_device_output_root(serial)
            resolved_images_path = output_root / "conversation_images"

        return (
            output_root,
            resolved_images_path,
            output_root / "conversation_videos",
            output_root / "conversation_voices",
        )

    @staticmethod
    def _resolve_db_path(db_path: str | None, serial: str | None = None) -> Path:
        """Return the normalized DB path the sync process will use."""
        if db_path:
            return Path(db_path).expanduser().resolve()
        if serial:
            return get_device_conversation_db_path(serial)
        return get_default_db_path().resolve()

    async def _warn_if_db_is_shared(self, serial: str, db_path: Path) -> None:
        """
        Warn when multiple active devices are writing to the same SQLite file.

        SQLite WAL improves concurrency, but heavy multi-device writes can still
        queue behind one another and look like intermittent slowdowns.
        """
        shared_with = [
            other_serial
            for other_serial, other_db_path in self._db_paths.items()
            if other_serial != serial and other_db_path == str(db_path)
        ]
        if not shared_with:
            return

        peers = ", ".join(sorted(shared_with))
        await self._broadcast_log(
            serial,
            "WARNING",
            (
                "Using shared SQLite DB "
                f"{db_path}. Active peer devices: {peers}. "
                "Concurrent writes may wait on WAL/busy_timeout and appear slower under load."
            ),
        )

    def get_active_sync_count(self) -> int:
        active = {SyncStatus.STARTING, SyncStatus.RUNNING, SyncStatus.PAUSED}
        return sum(1 for state in self._sync_states.values() if state.status in active)

    def _record_sync_completion(self, serial: str, state: SyncState | None) -> None:
        if state is None or state.started_at is None:
            return
        completed_at = state.completed_at or datetime.now()
        runtime_metrics.record_sync_run(
            serial,
            status=state.status.value,
            duration_ms=(completed_at - state.started_at).total_seconds() * 1000,
            customers_synced=state.customers_synced,
            messages_added=state.messages_added,
        )

    def get_sync_state(self, serial: str) -> SyncState | None:
        """Get sync state for a device."""
        return self._sync_states.get(serial)

    def get_all_sync_states(self) -> dict[str, SyncState]:
        """Get sync states for all devices."""
        return self._sync_states.copy()

    def register_log_callback(self, serial: str, callback: LogCallback):
        """Register a callback for log messages from a device."""
        if serial not in self._log_callbacks:
            self._log_callbacks[serial] = set()
        self._log_callbacks[serial].add(callback)

    def unregister_log_callback(self, serial: str, callback: LogCallback):
        """Unregister a log callback."""
        if serial in self._log_callbacks:
            self._log_callbacks[serial].discard(callback)

    def register_status_callback(self, serial: str, callback: StatusCallback):
        """Register a callback for status updates from a device."""
        if serial not in self._status_callbacks:
            self._status_callbacks[serial] = set()
        self._status_callbacks[serial].add(callback)

    def unregister_status_callback(self, serial: str, callback: StatusCallback):
        """Unregister a status callback."""
        if serial in self._status_callbacks:
            self._status_callbacks[serial].discard(callback)

    async def _broadcast_log(self, serial: str, level: str, message: str, source: str = "sync"):
        """Broadcast a log message to all registered callbacks."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
            "source": source,
        }

        if serial in self._log_callbacks:
            broken: list = []
            for callback in list(self._log_callbacks[serial]):
                try:
                    await callback(log_entry)
                except Exception:
                    broken.append(callback)
            if broken:
                bucket = self._log_callbacks.get(serial)
                if bucket is not None:
                    for cb in broken:
                        bucket.discard(cb)

    async def _broadcast_status(self, serial: str):
        """Broadcast current sync status to all registered callbacks."""
        state = self._sync_states.get(serial)
        if not state:
            return

        status_data = {
            "status": state.status.value,
            "progress": state.progress,
            "message": state.message,
            "customers_synced": state.customers_synced,
            "messages_added": state.messages_added,
        }

        if serial in self._status_callbacks:
            for callback in list(self._status_callbacks[serial]):
                try:
                    await callback(status_data)
                except Exception:
                    pass

    def _decode_output(self, data: bytes) -> str:
        """Decode subprocess output with proper encoding handling for Windows."""
        if not data:
            return ""

        # Try UTF-8 first (most common for Python scripts)
        try:
            return data.decode("utf-8").rstrip()
        except UnicodeDecodeError:
            pass

        # On Windows, try GBK (Chinese) or system default encoding
        if platform.system() == "Windows":
            try:
                return data.decode("gbk").rstrip()
            except UnicodeDecodeError:
                pass
            try:
                return data.decode("cp936").rstrip()
            except UnicodeDecodeError:
                pass

        # Last resort: replace errors
        return data.decode("utf-8", errors="replace").rstrip()

    async def _read_output(self, serial: str, stream: asyncio.StreamReader, is_stderr: bool = False):
        """Read output from a subprocess and broadcast as logs."""
        try:
            while True:
                line = await stream.readline()
                if not line:
                    break

                text = self._decode_output(line)
                if not text:
                    continue

                # Forward [DASHEVENT] markers to dashboard emitter
                if text.startswith("[DASHEVENT] "):
                    self._forward_dash_event(text[12:])
                    continue

                # Parse log level from output
                # Default to INFO instead of ERROR for stderr - Python logging uses stderr by default
                level = "INFO"

                # Try to extract level from log format
                # Format: "HH:MM:SS | LEVEL    | message"
                match = re.match(r"[\d:]+\s*\|\s*(\w+)\s*\|\s*(.+)", text)
                if match:
                    parsed_level = match.group(1).upper()
                    if parsed_level in ("DEBUG", "INFO", "WARNING", "ERROR"):
                        level = parsed_level
                    text = match.group(2)

                # Update state based on log content
                await self._parse_and_update_state(serial, text, level)

                # Broadcast log
                await self._broadcast_log(serial, level, text)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            await self._broadcast_log(serial, "ERROR", f"Output read error: {e}")

    @staticmethod
    def _forward_dash_event(json_str: str) -> None:
        """Parse a [DASHEVENT] JSON line and forward to DashboardEventEmitter."""
        try:
            import json
            data = json.loads(json_str)
            kind = data.pop("kind", None)
            serial = data.pop("serial", None)
            if kind and serial:
                from services.dashboard_events import get_dashboard_emitter
                get_dashboard_emitter().emit(kind, serial, data)
        except Exception:
            pass

    async def _parse_and_update_state(self, serial: str, message: str, level: str):
        """Parse log messages to update sync state with monotonic progress.

        Broadcasts status only when a _user-visible_ field actually changes
        (status/progress/message/customers_synced/messages_added, or a new
        error appended). The previous implementation broadcast on every
        single stdout line, doubling the WS frame rate per log and
        contributing to the sidecar log-pipeline backpressure observed
        under multi-device bursts.
        """
        state = self._sync_states.get(serial)
        if not state:
            return

        # Snapshot the fields that appear in status_data (plus errors length)
        # so we can decide at the end whether anything actually changed.
        prev_status = state.status.value
        prev_progress = state.progress
        prev_message = state.message
        prev_customers = state.customers_synced
        prev_messages = state.messages_added
        prev_errors_len = len(state.errors)

        # Initialize tracking attributes if not present
        if not hasattr(state, "_total_customers"):
            state._total_customers = 0
        if not hasattr(state, "_current_customer"):
            state._current_customer = 0
        if not hasattr(state, "_customer_sub_step"):
            state._customer_sub_step = 0  # 0-4 sub-steps per customer
        if not hasattr(state, "_in_scanning_phase"):
            state._in_scanning_phase = False

        # Track if we should update displayed message
        should_update_message = False
        new_message = message
        new_progress = state.progress  # Start with current progress

        # === Progress tracking ===
        # 0-10%: Pre-scanning phase (initialization, navigation, customer extraction)
        # 10-100%: Conversation scanning (90% proportional to customers + sub-steps)

        # ============================================
        # PRE-SCANNING PHASE (0-10%)
        # ============================================

        # Phase 1: Initialization (0-3%)
        if not state._in_scanning_phase:
            if "Ensuring WeCom is open" in message or "Step 1:" in message:
                new_progress = 1
                new_message = "Opening WeCom..."
                should_update_message = True
            elif "Getting kefu information" in message or "Step 2:" in message:
                new_progress = 2
                new_message = "Getting kefu information..."
                should_update_message = True
            elif "Current kefu:" in message:
                new_progress = 3
                match = re.search(r"Current kefu:\s*(.+)", message)
                new_message = f"Kefu: {match.group(1)}" if match else message
                should_update_message = True

            # Phase 2: Database & Navigation (3-7%)
            elif "Setting up database" in message or "Step 3:" in message:
                new_progress = 4
                new_message = "Setting up database..."
                should_update_message = True
            elif "Navigating to private chats" in message or "Step 4:" in message:
                new_progress = 5
                new_message = "Navigating to private chats..."
                should_update_message = True
            elif "Scrolling to top" in message:
                new_progress = 6
                scroll_match = re.search(r"max_attempts=(\d+)", message)
                if scroll_match:
                    new_message = f"Scrolling to top (max_attempts={scroll_match.group(1)})..."
                else:
                    new_message = "Scrolling to top..."
                should_update_message = True
            elif "UI stable" in message or "assuming top reached" in message or "Scrolled to top" in message:
                new_progress = 7
                new_message = "Reached top of list"
                should_update_message = True

            # Phase 3: Customer extraction (7-10%)
            elif "Extracting customer list" in message or "Step 5:" in message:
                new_progress = 8
                new_message = "Extracting customer list..."
                should_update_message = True
            elif "Found" in message and "customers" in message:
                match = re.search(r"Found\s+(\d+)\s+customers?", message)
                if match:
                    state._total_customers = int(match.group(1))
                    new_progress = 10
                    new_message = f"Found {state._total_customers} customers"
                    should_update_message = True

        # ============================================
        # CONVERSATION SCANNING PHASE (10-100%)
        # ============================================
        # Progress = 10 + (90 * overall_progress)
        # overall_progress = (completed_customers + current_sub_progress) / total_customers
        # current_sub_progress = sub_step / 5 (5 sub-steps: start, extract, process, test, back)

        if "Syncing customer conversations" in message or "Step 6:" in message:
            state._in_scanning_phase = True
            new_progress = 10
            new_message = "Starting customer sync..."
            should_update_message = True

        elif ("Processing customer" in message or "Syncing customer" in message) and "Processing customer" in message:
            state._in_scanning_phase = True
            match = re.search(r"(\d+)/(\d+)(?::\s*(.+))?", message)
            if match:
                current, total = int(match.group(1)), int(match.group(2))
                customer_name = match.group(3) if match.group(3) else ""
                state._total_customers = total
                state._current_customer = current
                state._customer_sub_step = 0  # Starting this customer
                state.customers_synced = current - 1

                # Calculate: 10% + 90% * (completed + 0/5) / total
                completed = current - 1
                overall = completed / total
                new_progress = 10 + int(90 * overall)

                if customer_name:
                    new_message = f"Syncing {current}/{total}: {customer_name}"
                else:
                    new_message = f"Syncing customer {current}/{total}"
                should_update_message = True

        elif state._in_scanning_phase and state._total_customers > 0:
            # Sub-step tracking within customer conversation
            if "Could not find user" in message:
                # User not found, skip to end of this customer
                state._customer_sub_step = 4
                completed = state._current_customer - 1
                sub_progress = state._customer_sub_step / 5.0
                overall = (completed + sub_progress) / state._total_customers
                new_progress = 10 + int(90 * overall)

            elif "Extracted" in message and "messages" in message:
                # Extracting messages - sub-step 1
                state._customer_sub_step = 1
                match = re.search(r"Extracted\s+(\d+)\s+messages(?:\s+for\s+(.+))?", message)
                if match:
                    msg_count = int(match.group(1))
                    customer_name = match.group(2) if match.group(2) else ""

                    completed = state._current_customer - 1
                    sub_progress = state._customer_sub_step / 5.0
                    overall = (completed + sub_progress) / state._total_customers
                    new_progress = 10 + int(90 * overall)

                    if customer_name:
                        new_message = f"Extracted {msg_count} messages for {customer_name}"
                    else:
                        new_message = f"Extracted {msg_count} messages"
                    should_update_message = True

            elif "Sending test message" in message:
                # Sending test - sub-step 2
                state._customer_sub_step = 2
                completed = state._current_customer - 1
                sub_progress = state._customer_sub_step / 5.0
                overall = (completed + sub_progress) / state._total_customers
                new_progress = 10 + int(90 * overall)
                new_message = f"Sending test message ({state._current_customer}/{state._total_customers})"
                should_update_message = True

            elif "wait" in message.lower() and "response" in message.lower():
                # Waiting for response - sub-step 3
                state._customer_sub_step = 3
                completed = state._current_customer - 1
                sub_progress = state._customer_sub_step / 5.0
                overall = (completed + sub_progress) / state._total_customers
                new_progress = 10 + int(90 * overall)

            elif "go back" in message.lower() or "Going back" in message:
                # Going back - sub-step 4
                state._customer_sub_step = 4
                completed = state._current_customer - 1
                sub_progress = state._customer_sub_step / 5.0
                overall = (completed + sub_progress) / state._total_customers
                new_progress = 10 + int(90 * overall)

        # Track messages and customers from summary
        if "Messages added:" in message:
            match = re.search(r"Messages added:\s*(\d+)", message)
            if match:
                state.messages_added = int(match.group(1))
        elif "Customers synced:" in message:
            match = re.search(r"Customers synced:\s*(\d+)", message)
            if match:
                state.customers_synced = int(match.group(1))
        elif "Stored response:" in message:
            state.messages_added = (state.messages_added or 0) + 1

        # ============================================
        # COMPLETION (100%)
        # ============================================
        if "SYNC COMPLETE" in message or "Sync completed" in message:
            state.status = SyncStatus.COMPLETED
            new_progress = 100
            state.completed_at = datetime.now()
            new_message = "Sync completed successfully"
            should_update_message = True
        elif "SYNC RESULTS" in message:
            new_progress = 98
            new_message = "Finishing up..."
            should_update_message = True

        # Error handling - only update display for critical errors, not transient ones
        if level == "ERROR":
            state.errors.append(message)

            # List of transient/retry errors that should NOT update the progress message
            transient_error_patterns = [
                "get_state attempt",
                "Portal returned error",
                "retry",
                "Retrying",
                "attempt 1 failed",
                "attempt 2 failed",
                "Connection reset",
                "timeout",
            ]

            # Check if this is a transient error
            is_transient = any(pattern.lower() in message.lower() for pattern in transient_error_patterns)

            if not is_transient:
                # Only update display for non-transient (critical) errors
                new_message = f"Error: {message[:100]}"
                should_update_message = True

        # === IMPORTANT: Only allow progress to increase (monotonic) ===
        if new_progress > state.progress:
            state.progress = new_progress

        # Update message only for important status changes
        if should_update_message:
            state.message = new_message

        # Broadcast only when a field visible to clients actually changed.
        # For the ~80-90% of log lines that don't map to any status field,
        # this short-circuits an otherwise-wasted WS frame per line.
        changed = (
            prev_status != state.status.value
            or prev_progress != state.progress
            or prev_message != state.message
            or prev_customers != state.customers_synced
            or prev_messages != state.messages_added
            or len(state.errors) > prev_errors_len
        )
        if changed:
            await self._broadcast_status(serial)

    async def start_sync(
        self,
        serial: str,
        db_path: str | None = None,
        images_dir: str | None = None,
        timing_multiplier: float = 1.0,
        auto_placeholder: bool = True,
        no_test_messages: bool = False,
        send_via_sidecar: bool = False,
        countdown_seconds: int = 10,
        use_ai_reply: bool = False,
        ai_server_url: str = "http://localhost:8000",
        ai_reply_timeout: int = 10,
        system_prompt: str = "",
        resume: bool = False,
    ) -> bool:
        """
        Start a sync operation for a device.

        Args:
            serial: Device serial number
            db_path: Path to SQLite database
            images_dir: Directory for image storage
            timing_multiplier: Delay multiplier for anti-detection
            auto_placeholder: Use placeholder for voice messages
            no_test_messages: Skip sending test messages
            send_via_sidecar: Route messages through sidecar for review
            countdown_seconds: Countdown duration when using sidecar
            use_ai_reply: Use AI server for generating replies
            ai_server_url: URL of AI server
            ai_reply_timeout: Timeout for AI replies in seconds
            system_prompt: System prompt to guide AI behavior
            resume: Resume from last checkpoint if available

        Returns:
            True if sync started successfully
        """
        # Check if already running
        if serial in self._processes:
            process = self._processes[serial]
            if process.returncode is None:
                await self._broadcast_log(serial, "WARNING", "Sync already running")
                return False

        # Initialize state
        self._sync_states[serial] = SyncState(
            status=SyncStatus.STARTING,
            message="Initializing sync...",
            started_at=datetime.now(),
        )
        await self._broadcast_status(serial)

        # Allocate unique port for this device
        droidrun_port = _port_allocator.allocate(serial)
        await self._broadcast_log(serial, "DEBUG", f"Allocated DroidRun port: {droidrun_port}")

        db_path_obj = self._resolve_db_path(db_path, serial)
        output_root, images_path, videos_path, voices_path = self._resolve_storage_paths(serial, images_dir)
        output_root.mkdir(parents=True, exist_ok=True)
        self._db_paths[serial] = str(db_path_obj)
        await self._warn_if_db_is_shared(serial, db_path_obj)

        # Build command using uv run (v2 modular version)
        script_path = PROJECT_ROOT / "wecom-desktop" / "backend" / "scripts" / "initial_sync.py"

        cmd = [
            "uv",
            "run",
            str(script_path),
            "--serial",
            serial,
            "--timing-multiplier",
            str(timing_multiplier),
            "--tcp-port",
            str(droidrun_port),  # Pass allocated port
            "--output-root",
            str(output_root),
            "--images-dir",
            str(images_path),
            "--videos-dir",
            str(videos_path),
            "--voices-dir",
            str(voices_path),
        ]

        cmd.extend(["--db", str(db_path_obj)])

        if auto_placeholder:
            cmd.append("--auto-placeholder")

        if no_test_messages:
            cmd.append("--no-test-messages")

        if send_via_sidecar:
            cmd.append("--send-via-sidecar")
            cmd.extend(["--countdown-seconds", str(countdown_seconds)])

        # AI Reply settings
        if use_ai_reply:
            cmd.append("--use-ai-reply")
            cmd.extend(["--ai-server-url", ai_server_url])
            cmd.extend(["--ai-reply-timeout", str(ai_reply_timeout)])
            if system_prompt:
                await self._broadcast_log(
                    serial, "INFO", f"[AI] 系统提示词已配置 ({len(system_prompt)}字符): {system_prompt[:80]}..."
                )
                # Use base64 encoding to safely pass multi-line prompts via command line
                import base64

                encoded_prompt = base64.b64encode(system_prompt.encode("utf-8")).decode("ascii")
                cmd.extend(["--system-prompt-b64", encoded_prompt])
            else:
                await self._broadcast_log(serial, "WARNING", "[AI] 未配置系统提示词")

        # Resume from checkpoint
        if resume:
            cmd.append("--resume")

        # Add debug flag for more verbose output
        cmd.append("--debug")

        try:
            await self._broadcast_log(serial, "INFO", f"Starting sync: {' '.join(cmd)}")
            await self._broadcast_log(serial, "DEBUG", f"Working dir: {PROJECT_ROOT}")

            # Set up environment for UTF-8 output
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"

            # Platform-specific subprocess creation
            if platform.system() == "Windows":
                # On Windows, use shell=True to properly find 'uv' in PATH
                # and avoid DLL initialization issues (0xC0000142)
                process = await self._create_subprocess_windows(cmd)
            else:
                # On Unix, use process groups for proper signal handling
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(PROJECT_ROOT),
                    env=env,
                    start_new_session=True,  # Create new process group (Unix only)
                )

            self._processes[serial] = process
            self._sync_states[serial].status = SyncStatus.RUNNING
            self._sync_states[serial].message = "Sync started"
            await self._broadcast_status(serial)

            # Notify dashboard
            try:
                from services.dashboard_events import get_dashboard_emitter
                get_dashboard_emitter().emit("device_launched", serial, {"source": "sync"})
            except Exception:
                pass

            # Windows: Create job object for pause/resume support
            if platform.system() == "Windows":
                try:
                    job_manager = get_job_manager()
                    job_manager.create_job(serial)
                    job_manager.add_process(serial, process.pid)
                    await self._broadcast_log(serial, "DEBUG", f"Created job object for process {process.pid}")
                except Exception as e:
                    await self._broadcast_log(serial, "WARNING", f"Failed to create job object: {e}")

            # Start output readers
            stdout_task = asyncio.create_task(self._read_output(serial, process.stdout, is_stderr=False))
            stderr_task = asyncio.create_task(self._read_output(serial, process.stderr, is_stderr=True))

            # Store tasks for cleanup
            self._read_tasks[serial] = asyncio.create_task(
                self._wait_for_completion(serial, process, stdout_task, stderr_task)
            )

            return True

        except Exception as e:
            self._sync_states[serial].status = SyncStatus.ERROR
            self._sync_states[serial].message = str(e)
            self._sync_states[serial].errors.append(str(e))
            await self._broadcast_status(serial)
            await self._broadcast_log(serial, "ERROR", f"Failed to start sync: {e}")
            return False

    async def _create_subprocess_windows(self, cmd: list[str]) -> asyncio.subprocess.Process:
        """Create subprocess on Windows using thread pool for compatibility."""
        # Set up environment to force UTF-8 output from Python subprocess
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        # Convert command list to string for shell execution
        # This helps Windows find 'uv' in PATH
        cmd_str = " ".join(f'"{arg}"' if " " in arg else arg for arg in cmd)

        # Use Popen in a thread to avoid asyncio subprocess issues on Windows
        def _create_process():
            # Use shell=True to properly find 'uv' in PATH on Windows
            # This avoids DLL initialization issues (0xC0000142)
            return subprocess.Popen(
                cmd_str,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(PROJECT_ROOT),
                env=env,
                shell=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )

        popen = await asyncio.to_thread(_create_process)

        # Wrap Popen in an async-compatible wrapper
        return _WindowsProcessWrapper(popen)

    async def _wait_for_completion(
        self,
        serial: str,
        process: asyncio.subprocess.Process,
        stdout_task: asyncio.Task,
        stderr_task: asyncio.Task,
    ):
        """Wait for subprocess to complete and update state."""
        try:
            # Wait for output readers to complete
            await asyncio.gather(stdout_task, stderr_task)

            # Wait for process to exit
            return_code = await process.wait()

            state = self._sync_states.get(serial)
            if state:
                if return_code == 0:
                    state.status = SyncStatus.COMPLETED
                    state.message = "Sync completed successfully"
                    state.progress = 100
                elif state.status != SyncStatus.STOPPED:
                    state.status = SyncStatus.ERROR

                    # Provide helpful error messages for known Windows error codes
                    if return_code == 3221225794:  # 0xC0000142 - STATUS_DLL_INIT_FAILED
                        state.message = "DLL initialization failed - try restarting the app"
                        state.errors.append(
                            "Exit code 0xC0000142: DLL init failed. This may be caused by PATH issues or conflicting Python installations."
                        )
                    elif return_code == 3221225477:  # 0xC0000005 - Access violation
                        state.message = "Access violation error"
                        state.errors.append("Exit code 0xC0000005: Access violation")
                    elif return_code == 1:
                        state.message = "Sync failed with errors"
                        state.errors.append(f"Exit code: {return_code}")
                    else:
                        state.message = f"Sync failed with exit code {return_code}"
                        state.errors.append(f"Exit code: {return_code}")

                state.completed_at = datetime.now()
                await self._broadcast_status(serial)
                await self._broadcast_log(
                    serial, "INFO" if return_code == 0 else "ERROR", f"Sync process exited with code {return_code}"
                )
                self._record_sync_completion(serial, state)

        except asyncio.CancelledError:
            pass
        finally:
            # Cleanup
            if serial in self._processes:
                del self._processes[serial]
            if serial in self._read_tasks:
                del self._read_tasks[serial]
            self._db_paths.pop(serial, None)

    async def stop_sync(self, serial: str) -> bool:
        """
        Stop a running sync operation.

        Args:
            serial: Device serial number

        Returns:
            True if sync was stopped or already completed
        """
        state = self._sync_states.get(serial)

        # If no process exists, check if we have a running state to update
        if serial not in self._processes:
            if state and state.status in (SyncStatus.RUNNING, SyncStatus.STARTING):
                state.status = SyncStatus.STOPPED
                state.message = "Sync stopped (process not found)"
                state.completed_at = datetime.now()
                await self._broadcast_status(serial)
                self._record_sync_completion(serial, state)
                return True
            return False

        process = self._processes[serial]

        # If process already exited, clean up and return success
        if process.returncode is not None:
            del self._processes[serial]
            if serial in self._read_tasks:
                del self._read_tasks[serial]

            # Update state if still marked as running
            if state and state.status in (SyncStatus.RUNNING, SyncStatus.STARTING):
                state.status = SyncStatus.STOPPED
                state.message = "Sync stopped (process already exited)"
                state.completed_at = datetime.now()
                await self._broadcast_status(serial)
                self._record_sync_completion(serial, state)
            return True

        # Update state to stopping
        if state:
            state.status = SyncStatus.STOPPED
            state.message = "Stopping sync..."
            await self._broadcast_status(serial)

        await self._broadcast_log(serial, "WARNING", "Stopping sync...")

        try:
            if platform.system() == "Windows":
                # On Windows, shell=True spawns cmd.exe which spawns Python
                # terminate() only kills cmd.exe, not the Python subprocess
                # Use taskkill /F /T to force kill the entire process tree
                try:
                    await self._broadcast_log(serial, "INFO", f"Killing process tree (PID: {process.pid})...")
                    result = await asyncio.to_thread(
                        subprocess.run,
                        ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                        capture_output=True,
                        timeout=5.0,
                    )
                    if result.returncode != 0:
                        # taskkill may fail if process already exited, try terminate as fallback
                        await self._broadcast_log(
                            serial, "WARNING", f"taskkill returned {result.returncode}, trying terminate..."
                        )
                        process.terminate()
                except subprocess.TimeoutExpired:
                    await self._broadcast_log(serial, "WARNING", "taskkill timed out, trying terminate...")
                    process.terminate()
                except FileNotFoundError:
                    # taskkill not found (shouldn't happen on Windows)
                    await self._broadcast_log(serial, "WARNING", "taskkill not found, trying terminate...")
                    process.terminate()
                except Exception as e:
                    await self._broadcast_log(serial, "WARNING", f"taskkill failed: {e}, trying terminate...")
                    process.terminate()

                # Wait for process to exit
                try:
                    await asyncio.wait_for(process.wait(), timeout=3.0)
                except TimeoutError:
                    await self._broadcast_log(serial, "WARNING", "Process still running, force killing...")
                    process.kill()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=3.0)
                    except TimeoutError:
                        await self._broadcast_log(serial, "ERROR", "Failed to kill process")
            else:
                # On Unix, terminate process group for proper cleanup
                pgid = os.getpgid(process.pid)

                # First try SIGTERM to the process group
                os.killpg(pgid, signal.SIGTERM)

                # Wait for graceful shutdown (short timeout)
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except TimeoutError:
                    # Force kill the process group if not responding
                    await self._broadcast_log(serial, "WARNING", "Process not responding, force killing...")
                    os.killpg(pgid, signal.SIGKILL)
                    try:
                        await asyncio.wait_for(process.wait(), timeout=3.0)
                    except TimeoutError:
                        await self._broadcast_log(serial, "ERROR", "Failed to kill process")

            # Update final state
            if state:
                state.status = SyncStatus.STOPPED
                state.message = "Sync stopped by user"
                state.completed_at = datetime.now()
                await self._broadcast_status(serial)

            await self._broadcast_log(serial, "INFO", "Sync stopped")

            # Notify dashboard
            try:
                from services.dashboard_events import get_dashboard_emitter
                get_dashboard_emitter().emit("device_stopped", serial, {"source": "sync"})
            except Exception:
                pass

            # Clean up
            if serial in self._processes:
                del self._processes[serial]
            if serial in self._read_tasks:
                task = self._read_tasks[serial]
                task.cancel()
                del self._read_tasks[serial]
            self._db_paths.pop(serial, None)

            # Release port allocation
            _port_allocator.release(serial)

            # Windows: Clean up job object
            if platform.system() == "Windows":
                try:
                    job_manager = get_job_manager()
                    job_manager.terminate_job(serial)
                except Exception as e:
                    await self._broadcast_log(serial, "WARNING", f"Failed to cleanup job object: {e}")

            return True

        except Exception as e:
            await self._broadcast_log(serial, "ERROR", f"Failed to stop sync: {e}")
            # Still try to clean up
            if serial in self._processes:
                del self._processes[serial]
            if serial in self._read_tasks:
                del self._read_tasks[serial]
            self._db_paths.pop(serial, None)

            # Windows: Clean up job object
            if platform.system() == "Windows":
                try:
                    job_manager = get_job_manager()
                    job_manager.terminate_job(serial)
                except Exception:
                    pass

            return False

    async def pause_sync(self, serial: str) -> bool:
        """
        Pause a running sync operation.

        Args:
            serial: Device serial number

        Returns:
            True if sync was paused successfully
        """
        state = self._sync_states.get(serial)

        if not state:
            await self._broadcast_log(serial, "WARNING", "Cannot pause: no sync state found")
            return False

        if state.status != SyncStatus.RUNNING:
            await self._broadcast_log(serial, "WARNING", f"Cannot pause: sync is {state.status.value}")
            return False

        # Check if process exists
        if serial not in self._processes:
            await self._broadcast_log(serial, "WARNING", "Cannot pause: no process found")
            return False

        process = self._processes[serial]

        # If process already exited, can't pause
        if process.returncode is not None:
            await self._broadcast_log(serial, "WARNING", "Cannot pause: process already exited")
            return False

        try:
            # Windows: Use Job Objects
            if platform.system() == "Windows":
                job_manager = get_job_manager()
                success = job_manager.suspend_job(serial)

                if success:
                    state.status = SyncStatus.PAUSED
                    state.message = "Sync paused"
                    await self._broadcast_status(serial)
                    await self._broadcast_log(serial, "INFO", "Sync paused")
                    return True
                else:
                    await self._broadcast_log(serial, "ERROR", "Failed to pause sync")
                    return False

            # Unix: Use SIGSTOP
            else:
                # Send SIGSTOP to the entire process group to pause all child processes
                pgid = os.getpgid(process.pid)
                os.killpg(pgid, signal.SIGSTOP)

                state.status = SyncStatus.PAUSED
                state.message = "Sync paused"
                await self._broadcast_status(serial)
                await self._broadcast_log(serial, "INFO", "Sync paused")

                return True

        except Exception as e:
            await self._broadcast_log(serial, "ERROR", f"Failed to pause sync: {e}")
            return False

    async def resume_sync(self, serial: str) -> bool:
        """
        Resume a paused sync operation.

        Args:
            serial: Device serial number

        Returns:
            True if sync was resumed successfully
        """
        state = self._sync_states.get(serial)

        if not state:
            await self._broadcast_log(serial, "WARNING", "Cannot resume: no sync state found")
            return False

        if state.status != SyncStatus.PAUSED:
            await self._broadcast_log(serial, "WARNING", f"Cannot resume: sync is {state.status.value}")
            return False

        # Check if process exists
        if serial not in self._processes:
            await self._broadcast_log(serial, "WARNING", "Cannot resume: no process found")
            return False

        process = self._processes[serial]

        # If process already exited, can't resume
        if process.returncode is not None:
            await self._broadcast_log(serial, "WARNING", "Cannot resume: process already exited")
            return False

        try:
            # Windows: Use Job Objects
            if platform.system() == "Windows":
                job_manager = get_job_manager()
                success = job_manager.resume_job(serial)

                if success:
                    state.status = SyncStatus.RUNNING
                    state.message = "Sync resumed"
                    await self._broadcast_status(serial)
                    await self._broadcast_log(serial, "INFO", "Sync resumed")
                    return True
                else:
                    await self._broadcast_log(serial, "ERROR", "Failed to resume sync")
                    return False

            # Unix: Use SIGCONT
            else:
                # Send SIGCONT to the entire process group to resume all child processes
                pgid = os.getpgid(process.pid)
                os.killpg(pgid, signal.SIGCONT)

                state.status = SyncStatus.RUNNING
                state.message = "Sync resumed"
                await self._broadcast_status(serial)
                await self._broadcast_log(serial, "INFO", "Sync resumed")

                return True

        except Exception as e:
            await self._broadcast_log(serial, "ERROR", f"Failed to resume sync: {e}")
            return False

    async def stop_all(self):
        """Stop all running sync operations."""
        serials = list(self._processes.keys())
        for serial in serials:
            await self.stop_sync(serial)
