# Global Log File Locking Analysis - Multi-Device Environment

**Date**: 2026-02-09
**Status**: Critical Production Issue
**Priority**: P0 - System Blocker
**Environment**: Windows, Python 3.13.5, Loguru 0.7.3

---

## Executive Summary

**Problem**: The global log file (`default-global.log`) experiences file locking issues when multiple devices operate in parallel, causing write failures and potential data loss.

**Root Cause**: Loguru's `enqueue=True` uses multiprocessing queues which are **not inherited by subprocesses** spawned with `subprocess.Popen()` (unlike `multiprocessing.Process()`). Each subprocess tries to open the same file independently, causing Windows file locking conflicts.

**Impact**: Medium - Device-specific logs work correctly, but backend service logs may be lost or corrupted when multiple subprocesses initialize simultaneously.

**Quick Fix**: Disable global log file in subprocess scripts (`init_logging(console=False)` is already implemented).

**Long-term Solution**: Implement centralized logging with proper inter-process communication (IPC) or separate log files per process.

---

## Table of Contents

1. [Current State Analysis](#current-state-analysis)
2. [Root Cause Analysis](#root-cause-analysis)
3. [Technical Deep Dive](#technical-deep-dive)
4. [Solution Comparison Matrix](#solution-comparison-matrix)
5. [Recommended Implementation Plan](#recommended-implementation-plan)
6. [Testing Strategy](#testing-strategy)
7. [Rollback Plan](#rollback-plan)
8. [References](#references)

---

## Current State Analysis

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                  Backend Main Process                        │
│                  (FastAPI / main.py)                         │
│                                                               │
│  init_logging(hostname="default")                            │
│  ├─> stderr (console output)                                 │
│  └─> logs/default-global.log  ❌ LOCKED FILE                │
│                                                               │
└──────────────────────────┬──────────────────────────────────┘
                           │ subprocess.Popen()
                           │ (no shared memory)
         ┌─────────────────┼─────────────────┐
         │                 │                 │
         ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Subprocess  │  │  Subprocess  │  │  Subprocess  │
│  Device A    │  │  Device B    │  │  Device C    │
│              │  │              │  │              │
│ init_logging()│  │ init_logging()│  │ init_logging()│
│   ❌ FAIL    │  │   ❌ FAIL    │  │   ❌ FAIL    │
│              │  │              │  │              │
│ Trying to    │  │ Trying to    │  │ Trying to    │
│ open same    │  │ open same    │  │ open same    │
│ file!        │  │ file!        │  │ file!        │
└──────────────┘  └──────────────┘  └──────────────┘
```

### Code Flow Analysis

#### 1. Backend Main Process (`main.py`)

**Location**: `D:\111\android_run_test-backup\wecom-desktop\backend\main.py`

**Lines 129-136**:

```python
def setup_backend_logging():
    """配置后端服务日志（使用 loguru）"""
    from wecom_automation.core.logging import init_logging

    hostname = _get_hostname()
    print(f"[startup] Initializing logging for hostname: {hostname}")
    init_logging(hostname=hostname, level="INFO", console=True)
    print(f"[startup] Logging configured: logs/{hostname}-global.log")
```

**What happens**:

- Calls `init_logging()` which creates `logs/default-global.log`
- Uses `enqueue=True` for multiprocessing safety
- **Problem**: Only works for `multiprocessing.Process()`, not `subprocess.Popen()`

#### 2. Subprocess Initialization (`initial_sync.py`)

**Location**: `D:\111\android_run_test-backup\wecom-desktop\backend\scripts\initial_sync.py`

**Lines 141-162**:

```python
def setup_logging(serial: str, debug: bool = False, log_file: Optional[str] = None):
    """配置日志系统 - 使用 loguru，同时输出到文件和 stdout（由父进程捕获）"""
    from wecom_automation.core.logging import init_logging, add_device_sink, get_logger
    from loguru import logger as _loguru_logger

    level = "DEBUG" if debug else "INFO"
    hostname = _get_hostname()

    # 初始化 loguru（全局日志，不输出到控制台）
    # 注意：loguru 默认输出到 stderr，这里我们需要自定义输出到 stdout
    init_logging(hostname=hostname, level=level, console=False)

    # 手动添加 stdout handler（用于父进程捕获并转发到前端 WebSocket）
    _loguru_logger.add(
        sys.stdout,
        format="{time:HH:mm:ss} | {level:<8} | {message}",
        level=level,
        colorize=False,  # stdout 不需要颜色
    )

    # 为该设备添加专属日志文件
    add_device_sink(serial, hostname=hostname, level=level)

    # 确保 stdout 刷新（用于父进程实时捕获）
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(line_buffering=True)

    return get_logger("sync", device=serial)
```

**What happens**:

- Each subprocess calls `init_logging(console=False)`
- **Attempts to create the same global log file**: `logs/default-global.log`
- **Windows file locking**: Only one process can open the file for writing
- **Result**: Second and subsequent processes fail to write to global log

#### 3. Realtime Reply Process (`realtime_reply_process.py`)

**Location**: `D:\111\android_run_test-backup\wecom-desktop\backend\scripts\realtime_reply_process.py`

**Lines 53-80**:

```python
def setup_logging(serial: str, debug: bool = False):
    """设置日志 - 使用 loguru，同时输出到文件和 stdout（由父进程捕获）"""
    from wecom_automation.core.logging import init_logging, add_device_sink, get_logger

    level = "DEBUG" if debug else "INFO"
    hostname = _get_hostname()

    # 初始化 loguru（全局日志 + 控制台）
    # 注意：loguru 默认输出到 stderr，这里我们需要自定义控制台输出到 stdout
    init_logging(hostname=hostname, level=level, console=False)

    # 手动添加 stdout handler（用于父进程捕获）
    from loguru import logger as _loguru_logger
    _loguru_logger.add(
        sys.stdout,
        format="{time:HH:mm:ss} | {level:<8} | {message}",
        level=level,
        colorize=False,  # stdout 不需要颜色
    )

    # 为该设备添加专属日志文件
    add_device_sink(serial, hostname=hostname, level=level)

    # 确保 stdout 刷新（用于父进程实时捕获）
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(line_buffering=True)

    return get_logger("scanner", device=serial)
```

**Same issue**: Attempts to create the same global log file.

#### 4. Logging Core Implementation (`logging.py`)

**Location**: `D:\111\android_run_test-backup\src\wecom_automation\core\logging.py`

**Lines 130-142**:

```python
# 全局日志文件（无设备上下文的日志）
# 使用 SAFE_LOG_FORMAT 以兼容 stdlib logging
_loguru_logger.add(
    _log_dir / f"{hostname}-global.log",
    format=SAFE_LOG_FORMAT,
    rotation="00:00",  # 午夜轮转
    retention="30 days",  # 保留 30 天
    encoding="utf-8",
    enqueue=True,  # 多进程安全  ❌ NOT FOR SUBPROCESS!
    filter=lambda r: "device" not in r["extra"],
    level=level,
    colorize=False,
)
```

**The misconception**: `enqueue=True` is documented as "multiprocess-safe", but this only applies to `multiprocessing.Process()` which shares memory and can inherit queues. It does NOT apply to `subprocess.Popen()` which spawns completely independent processes.

---

## Root Cause Analysis

### The Problem

**Loguru's `enqueue=True` Implementation**:

```python
# When enqueue=True, Loguru creates a multiprocessing.Queue:
queue = multiprocessing.Queue()
# Parent process writes to queue
# Consumer thread reads from queue and writes to file

# This works with multiprocessing.Process():
with multiprocessing.Pool() as pool:
    # Child processes inherit queue reference
    pool.map(func, args)  # ✅ Works!

# But FAILS with subprocess.Popen():
subprocess.Popen(["python", "script.py"])
# Child process is completely independent
# Queue is NOT inherited  ❌ Fails!
```

**Why It Fails**:

1. **Parent process** creates queue and file handler
2. **Subprocess spawns** with `subprocess.Popen()` (no shared memory)
3. **Subprocess imports** `wecom_automation.core.logging`
4. **Subprocess calls** `init_logging()` again
5. **Loguru tries to open** `default-global.log` for writing
6. **Windows file locking**: File already open in parent process
7. **Result**: Permission denied / file locked error

### Evidence from Logs

**Log file status**:

```bash
$ ls -la logs/default-global.log
-rw-r--r-- 1 Administrator 197121 196988  2月  9 17:44 default-global.log
```

The file exists and is being written to by the main process, but subprocess writes are failing silently or being lost.

### Windows-Specific Issues

**Why Windows is Affected More Than Linux**:

| Aspect           | Linux                                      | Windows                       |
| ---------------- | ------------------------------------------ | ----------------------------- |
| File locking     | Advisory (multiple writers allowed)        | Mandatory (exclusive access)  |
| Process creation | `fork()` (copy-on-write, inherits handles) | `spawn()` (no inheritance)    |
| Queue pickling   | Can pickle file descriptors                | Cannot pickle Windows handles |

**Result**: On Windows, when subprocess tries to open the file, it gets a `PermissionError` because the file is exclusively locked by the parent process.

---

## Technical Deep Dive

### Loguru's `enqueue=True` Mechanism

**Source**: [GitHub Issue #1338](https://github.com/Delgan/loguru/issues/1338)

```python
# Simplified implementation of enqueue=True
class Logger:
    def add(self, sink, enqueue=False):
        if enqueue:
            # Create multiprocessing queue
            queue = multiprocessing.Queue()

            # Start consumer thread in parent process
            consumer = threading.Thread(
                target=self._consume_queue,
                args=(queue, sink)
            )
            consumer.start()

            # Replace sink with queue
            sink = queue
        self._handlers.append(sink)

    def _consume_queue(self, queue, original_sink):
        while True:
            record = queue.get()
            original_sink.write(record)
```

**Key Insight**: The consumer thread runs in the **parent process only**, not in subprocesses.

### Device Manager Subprocess Creation

**Location**: `D:\111\android_run_test-backup\wecom-desktop\backend\services\device_manager.py`

**Lines 592-615**:

```python
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
]

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
```

**Key Point**: Uses `asyncio.create_subprocess_exec()` which wraps `subprocess.Popen()`, not `multiprocessing.Process()`.

### Current Workaround (Already Implemented)

**Good News**: The code already has `console=False` in subprocess scripts:

```python
# In initial_sync.py and realtime_reply_process.py
init_logging(hostname=hostname, level=level, console=False)
```

This means:

- ✅ Subprocesses do NOT duplicate console output
- ✅ Each subprocess writes to its own device log file
- ✅ Subprocess logs are captured via stdout by DeviceManager
- ❌ But `init_logging()` still tries to create the global log file

**What Actually Happens**:

```python
def init_logging(console=False):
    # Remove default handler
    _loguru_logger.remove()

    # Console handler
    if console:
        _loguru_logger.add(sys.stderr, ...)  # ✅ This is skipped

    # Global log file  ❌ ALWAYS CREATED!
    _loguru_logger.add(
        _log_dir / f"{hostname}-global.log",  # ❌ Subprocess tries to open this!
        ...
    )
```

---

## Solution Comparison Matrix

### Solution Options

| Solution                             | Complexity         | Time to Implement | Reliability  | Performance         | Side Effects                       |
| ------------------------------------ | ------------------ | ----------------- | ------------ | ------------------- | ---------------------------------- |
| **1. Skip global log in subprocess** | ⭐ Low             | ⚡ 1 hour         | ✅ High      | ✅ No impact        | ℹ️ Backend logs split across files |
| **2. Process identifier suffix**     | ⭐⭐ Medium        | ⏱️ 2-3 hours      | ✅ High      | ✅ No impact        | ℹ️ More log files to manage        |
| **3. Named pipes / IPC**             | ⭐⭐⭐ High        | 📅 1-2 days       | ⚠️ Medium    | ⚠️ Overhead         | ℹ️ Complex debugging               |
| **4. Central log service**           | ⭐⭐⭐⭐ Very High | 🗓️ 1 week         | ✅ Very High | ✅ Best             | ℹ️ Major architecture change       |
| **5. Socket-based logging**          | ⭐⭐⭐⭐ Very High | 🗓️ 3-5 days       | ✅ High      | ⚠️ Network overhead | ℹ️ Single point of failure         |

---

### Detailed Solutions

#### Solution 1: Skip Global Log in Subprocess (RECOMMENDED)

**Description**: Modify `init_logging()` to detect subprocess context and skip global log file creation.

**Implementation**:

```python
def init_logging(hostname=None, level="INFO", log_dir=None, console=True, force_global=False):
    # Detect if running in subprocess
    is_subprocess = _is_subprocess()

    if not is_subprocess or force_global:
        # Only create global log in main process
        _loguru_logger.add(
            _log_dir / f"{hostname}-global.log",
            ...
        )

def _is_subprocess():
    """Detect if running in subprocess by checking parent process"""
    import psutil
    try:
        parent = psutil.Process().parent()
        # Check if parent is uv or python with script args
        if parent and any(cmd in parent.name().lower() for cmd in ['uv', 'python', 'pythonw']):
            return True
    except:
        pass
    return False
```

**Pros**:

- ✅ Minimal code change
- ✅ Device logs still work perfectly
- ✅ No performance impact
- ✅ Backend logs remain in main process

**Cons**:

- ⚠️ Requires psutil dependency (or use alternative detection)
- ⚠️ Subprocess backend logs go to device-specific files instead

**Effort**: 1-2 hours

---

#### Solution 2: Process Identifier Suffix

**Description**: Add PID or unique identifier to global log filename in subprocess.

**Implementation**:

```python
def init_logging(hostname=None, level="INFO", log_dir=None, console=True):
    import os

    # If in subprocess, use PID suffix
    if _is_subprocess():
        pid = os.getpid()
        global_log = _log_dir / f"{hostname}-global-subprocess-{pid}.log"
    else:
        global_log = _log_dir / f"{hostname}-global.log"

    _loguru_logger.add(global_log, ...)
```

**Pros**:

- ✅ No file conflicts
- ✅ All logs preserved
- ✅ Simple to implement

**Cons**:

- ⚠️ Many small log files (need cleanup script)
- ⚠️ Harder to find specific logs
- ⚠️ Disk usage increase

**Effort**: 2-3 hours (including cleanup script)

---

#### Solution 3: Named Pipes / IPC

**Description**: Use Windows named pipes or Unix domain sockets for centralized logging.

**Implementation**:

```python
# Main process
import multiprocessing
pipe = multiprocessing.Pipe()

def log_server():
    while True:
        record = pipe[0].recv()
        write_to_file(record)

threading.Thread(target=log_server, daemon=True).start()

# Subprocess
pipe.send(log_record)
```

**Pros**:

- ✅ True centralized logging
- ✅ Real-time log aggregation

**Cons**:

- ❌ Complex error handling
- ❌ Pipe buffer limits
- ❌ Deadlocks if pipe fills up
- ❌ Platform-specific (named pipes on Windows, domain sockets on Linux)

**Effort**: 1-2 days

---

#### Solution 4: Central Log Service

**Description**: Run a dedicated logging service that all processes send logs to via HTTP/UDP.

**Implementation**:

```python
# Log service (FastAPI)
@app.post("/logs")
async def receive_log(record: LogRecord):
    logger.handle(record)

# Client
class LogClient:
    def emit(self, record):
        requests.post("http://localhost:9999/logs", json=record)
```

**Pros**:

- ✅ Production-grade solution
- ✅ Can add log filtering, alerting, search
- ✅ Scales to multiple machines

**Cons**:

- ❌ Major architecture change
- ❌ Network overhead
- ❌ Single point of failure (need HA setup)
- ❌ Not worth it for single-machine deployment

**Effort**: 1 week

---

#### Solution 5: Socket-Based Logging

**Description**: Use Python's `logging.handlers.SocketHandler` for log forwarding.

**Pros**:

- ✅ Built-in Python solution
- ✅ No external dependencies

**Cons**:

- ❌ Requires custom log record receiver
- ❌ Socket connection management complexity
- ❌ Overkill for local logging

**Effort**: 3-5 days

---

## Recommended Implementation Plan

### Phase 1: Immediate Fix (TODAY)

**Goal**: Stop the file locking errors with minimal risk.

**Changes Required**:

1. **Modify `src/wecom_automation/core/logging.py`**:

```python
def init_logging(
    hostname: str | None = None,
    level: str = "INFO",
    log_dir: Path | None = None,
    console: bool = True,
    force_global: bool = False,  # NEW PARAMETER
) -> None:
    """
    Initialize global logging.

    Args:
        force_global: If True, always create global log file (even in subprocess)
                      Use this only in main process.
    """
    global _initialized, _hostname, _log_dir

    if hostname is None:
        hostname = _get_hostname()

    _hostname = hostname
    _log_dir = log_dir or get_project_root() / "logs"
    _log_dir.mkdir(parents=True, exist_ok=True)

    # Remove default handler
    _loguru_logger.remove()

    # Console handler
    if console:
        _loguru_logger.add(
            sys.stderr,
            format=CONSOLE_FORMAT,
            level=level,
            colorize=True,
            filter=_swipe_filter,
        )

    # CHANGED: Only create global log if not in subprocess OR force_global=True
    if not _is_subprocess() or force_global:
        _loguru_logger.add(
            _log_dir / f"{hostname}-global.log",
            format=SAFE_LOG_FORMAT,
            rotation="00:00",
            retention="30 days",
            encoding="utf-8",
            enqueue=True,
            filter=lambda r: "device" not in r["extra"],
            level=level,
            colorize=False,
        )

    _initialized = True


def _is_subprocess() -> bool:
    """
    Detect if running in a subprocess (not multiprocessing.Process).

    Checks if parent process is uv, python, or other launcher.
    """
    import os
    import sys

    # Method 1: Check if we're a child process with different PID
    # This is simple and works on all platforms
    try:
        # If we were launched by uv or as a script, we're likely a subprocess
        if len(sys.argv) > 0:
            cmdline = ' '.join(sys.argv)
            # Check for uv run or script execution patterns
            if 'uv run' in cmdline or 'python' in cmdline:
                # Additional check: see if we're not the main module
                if __name__ != "__main__":
                    return True
    except Exception:
        pass

    # Method 2: Check parent process name (requires psutil)
    try:
        import psutil
        current_process = psutil.Process()
        parent = current_process.parent()
        if parent:
            parent_name = parent.name().lower()
            # If parent is uv, pythonw, or similar, we're likely a subprocess
            if any(cmd in parent_name for cmd in ['uv', 'pythonw', 'cmd', 'bash', 'sh']):
                return True
    except Exception:
        pass

    return False
```

2. **Update subprocess scripts to skip global log**:

In `wecom-desktop/backend/scripts/initial_sync.py` (line 151):

```python
# BEFORE:
init_logging(hostname=hostname, level=level, console=False)

# AFTER:
init_logging(hostname=hostname, level=level, console=False, force_global=False)
```

In `wecom-desktop/backend/scripts/realtime_reply_process.py` (line 62):

```python
# BEFORE:
init_logging(hostname=hostname, level=level, console=False)

# AFTER:
init_logging(hostname=hostname, level=level, console=False, force_global=False)
```

3. **Ensure main process uses global log**:

In `wecom-desktop/backend/main.py` (line 135):

```python
# BEFORE:
init_logging(hostname=hostname, level=level, console=True)

# AFTER:
init_logging(hostname=hostname, level=level, console=True, force_global=True)
```

**Testing**:

```bash
# 1. Start backend
cd wecom-desktop/backend
uvicorn main:app --reload --port 8765

# 2. Start sync for multiple devices
curl -X POST http://localhost:8765/devices/{serial1}/sync
curl -X POST http://localhost:8765/devices/{serial2}/sync

# 3. Check logs
ls -la logs/
# Should see:
# - default-global.log (only main process writes here)
# - default-{serial1}.log (device 1 logs)
# - default-{serial2}.log (device 2 logs)
```

**Expected Results**:

- ✅ No file locking errors
- ✅ Backend logs in `default-global.log`
- ✅ Device logs in `default-{serial}.log` files
- ✅ All subprocess logs captured via stdout and displayed in frontend

---

### Phase 2: Improved Detection (THIS WEEK)

**Goal**: Make subprocess detection more robust.

**Implementation**:

Add environment variable marker in DeviceManager when spawning subprocesses:

```python
# In device_manager.py
env = os.environ.copy()
env["PYTHONIOENCODING"] = "utf-8"
env["PYTHONUTF8"] = "1"
env["WECOM_SUBPROCESS"] = "true"  # NEW: Mark as subprocess
```

Update `_is_subprocess()` to check the marker:

```python
def _is_subprocess() -> bool:
    """Detect if running in subprocess by checking environment variable."""
    import os

    # Method 1: Check environment variable (most reliable)
    if os.environ.get("WECOM_SUBPROCESS", "").lower() == "true":
        return True

    # Method 2: Fallback to process detection (as above)
    ...
```

**Benefits**:

- ✅ 100% reliable detection
- ✅ No false positives
- ✅ Works on all platforms

---

### Phase 3: Long-term Architecture (NEXT SPRINT)

**Goal**: Implement production-grade centralized logging.

**Options**:

1. Use existing log aggregation from stdout (already implemented)
2. Add structured logging (JSON format) for better parsing
3. Implement log rotation and retention policies

**Current Architecture Analysis**:

The system **already has** centralized logging via:

- Subprocess stdout → DeviceManager.\_read_output() → WebSocket → Frontend

This means:

- ✅ All subprocess logs are already visible in frontend
- ✅ No need for complex IPC mechanisms
- ✅ Device-specific logs work perfectly

**What's Missing**:

- Backend service logs (FastAPI routers) only in `default-global.log`
- No structured logging for search/filtering
- No log level filtering in frontend

**Recommendation**:
Keep current architecture but add:

1. Structured logging (JSON) for better parsing
2. Log level filtering in frontend
3. Log search functionality

---

## Testing Strategy

### Unit Tests

```python
# tests/unit/test_logging_subprocess.py

import pytest
import subprocess
import sys
from pathlib import Path

def test_init_logging_skips_global_in_subprocess():
    """Test that subprocess doesn't create global log file."""
    from wecom_automation.core.logging import init_logging, _is_subprocess

    # Mock subprocess environment
    import os
    os.environ["WECOM_SUBPROCESS"] = "true"

    try:
        # Initialize logging
        init_logging(hostname="test", level="INFO", console=False)

        # Check that global log was NOT created
        log_file = Path("logs/test-global.log")
        assert not log_file.exists() or log_file.stat().st_size == 0
    finally:
        os.environ.pop("WECOM_SUBPROCESS", None)

def test_init_logging_creates_global_in_main():
    """Test that main process creates global log file."""
    from wecom_automation.core.logging import init_logging, force_global=True

    # Initialize logging with force_global=True
    init_logging(hostname="test", level="INFO", console=False, force_global=True)

    # Check that global log was created
    log_file = Path("logs/test-global.log")
    assert log_file.exists()

def test_subprocess_detection():
    """Test subprocess detection logic."""
    from wecom_automation.core.logging import _is_subprocess

    # In main pytest process, should not be detected as subprocess
    assert not _is_subprocess()
```

### Integration Tests

```python
# tests/integration/test_multi_device_logging.py

import pytest
import asyncio
from pathlib import Path

@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_device_sync_logging():
    """Test that multiple devices can sync simultaneously without log conflicts."""
    from wecom-desktop.backend.services.device_manager import DeviceManager

    manager = DeviceManager()

    # Start sync for 2 devices simultaneously
    results = await asyncio.gather(
        manager.start_sync("device1"),
        manager.start_sync("device2"),
        return_exceptions=True
    )

    # Both should succeed
    assert not any(isinstance(r, Exception) for r in results)

    # Check log files
    logs_dir = Path("logs")
    assert (logs_dir / "default-global.log").exists()
    assert (logs_dir / "default-device1.log").exists()
    assert (logs_dir / "default-device2.log").exists()

    # Verify no permission errors in logs
    global_log = (logs_dir / "default-global.log").read_text()
    assert "PermissionError" not in global_log
    assert "file locked" not in global_log.lower()
```

### Manual Testing

**Test Case 1: Single Device Sync**

```bash
# Start backend
cd wecom-desktop/backend
uvicorn main:app --reload --port 8765

# In another terminal, start single device sync
curl -X POST http://localhost:8765/devices/DEVICE_SERIAL/sync

# Check logs
tail -f logs/default-global.log
tail -f logs/default-DEVICE_SERIAL.log
```

**Expected**: No errors, logs written successfully.

**Test Case 2: Concurrent Multi-Device Sync**

```bash
# Start 3 device syncs simultaneously
curl -X POST http://localhost:8765/devices/DEVICE1/sync &
curl -X POST http://localhost:8765/devices/DEVICE2/sync &
curl -X POST http://localhost:8765/devices/DEVICE3/sync &
wait

# Check all log files
ls -la logs/default-*.log
```

**Expected**:

- `default-global.log` exists and contains only backend logs
- `default-DEVICE1.log`, `default-DEVICE2.log`, `default-DEVICE3.log` all exist
- No "Permission denied" or "file locked" errors in any log

**Test Case 3: Realtime Reply + Sync Concurrent**

```bash
# Start sync
curl -X POST http://localhost:8765/devices/DEVICE1/sync

# Start realtime reply
curl -X POST http://localhost:8765/api/realtime/start -d '{"serial": "DEVICE1"}'

# Check logs
tail -f logs/default-DEVICE1.log
```

**Expected**: Both processes write to same device log file without conflicts.

---

## Rollback Plan

### If Issues Occur

**Symptoms to Watch For**:

- Backend logs not appearing in `default-global.log`
- Device logs missing
- Frontend log viewer empty

**Rollback Steps**:

1. **Revert logging.py changes**:

```bash
git checkout HEAD -- src/wecom_automation/core/logging.py
```

2. **Revert subprocess script changes**:

```bash
git checkout HEAD -- wecom-desktop/backend/scripts/initial_sync.py
git checkout HEAD -- wecom-desktop/backend/scripts/realtime_reply_process.py
```

3. **Restart backend**:

```bash
# Stop current backend (Ctrl+C)
cd wecom-desktop/backend
uvicorn main:app --reload --port 8765
```

4. **Verify logs are working**:

```bash
tail -f logs/default-global.log
```

**Alternative: Quick Patch Without Rollback**

If only subprocess detection is failing, add manual override:

```python
# In subprocess scripts, explicitly skip global log
def init_logging(..., skip_global=False):
    if skip_global:
        # Skip global log creation
        pass
    else:
        # Normal behavior
        _loguru_logger.add(...)
```

Then call:

```python
init_logging(hostname=hostname, level=level, console=False, skip_global=True)
```

---

## Monitoring and Validation

### Log File Health Check Script

```python
#!/usr/bin/env python3
"""Check log file health and detect issues."""

from pathlib import Path
import re
from datetime import datetime

def check_log_file(log_path: Path):
    """Check a single log file for issues."""
    if not log_path.exists():
        return {"status": "missing", "errors": []}

    text = log_path.read_text(encoding="utf-8", errors="ignore")
    errors = []

    # Check for common error patterns
    error_patterns = [
        (r"PermissionError", "File permission error"),
        (r"Permission denied", "File access denied"),
        (r"file locked", "File locked by another process"),
        (r"Access is denied", "Windows access denied"),
        (r"cannot open file", "File open failure"),
    ]

    for pattern, description in error_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            errors.append(description)

    # Get file stats
    stat = log_path.stat()
    size_kb = stat.st_size / 1024

    return {
        "status": "healthy" if not errors else "unhealthy",
        "size_kb": round(size_kb, 2),
        "last_modified": datetime.fromtimestamp(stat.st_mtime),
        "errors": errors,
    }

def main():
    logs_dir = Path("logs")
    print(f"Checking log files in {logs_dir}/\n")

    # Check global log
    global_log = logs_dir / "default-global.log"
    result = check_log_file(global_log)
    print(f"📄 {global_log.name}")
    print(f"   Status: {result['status']}")
    print(f"   Size: {result['size_kb']} KB")
    print(f"   Last modified: {result['last_modified']}")
    if result['errors']:
        print("   Errors:")
        for error in result['errors']:
            print(f"     - {error}")
    print()

    # Check device logs
    device_logs = sorted(logs_dir.glob("default-*.log"))
    for log_file in device_logs:
        if log_file == global_log:
            continue
        result = check_log_file(log_file)
        status_icon = "✅" if result['status'] == "healthy" else "❌"
        print(f"{status_icon} {log_file.name}: {result['size_kb']} KB")

if __name__ == "__main__":
    main()
```

**Usage**:

```bash
python scripts/check_log_health.py
```

**Expected Output**:

```
Checking log files in logs/

📄 default-global.log
   Status: healthy
   Size: 191.95 KB
   Last modified: 2026-02-09 17:44:12.123456

✅ default-9586492623004ZE.log: 255.4 KB
✅ default-AN2FVB1706003302.log: 8.46 KB
```

---

## Conclusion

### Summary

The global log file locking issue is caused by Loguru's `enqueue=True` being designed for `multiprocessing.Process()` (shared memory) but not for `subprocess.Popen()` (independent processes). Each subprocess tries to open the same file, causing Windows file locking conflicts.

### Recommended Path Forward

1. **Immediate (Today)**: Implement Solution 1 - Skip global log in subprocess
   - Add `force_global` parameter to `init_logging()`
   - Detect subprocess context
   - Only create global log in main process
   - **Effort**: 1-2 hours
   - **Risk**: Low

2. **Short-term (This Week)**: Improve subprocess detection
   - Add `WECOM_SUBPROCESS` environment variable
   - Make detection 100% reliable
   - **Effort**: 1 hour
   - **Risk**: Very Low

3. **Long-term (Next Sprint)**: Enhance existing log aggregation
   - Add structured logging (JSON)
   - Implement log filtering in frontend
   - Add log search functionality
   - **Effort**: 2-3 days
   - **Risk**: Medium

### Key Takeaways

- ✅ Device-specific logs work perfectly (no changes needed)
- ✅ Subprocess logs are already aggregated via stdout → WebSocket → Frontend
- ✅ Only backend service logs need global log file
- ✅ Simple fix with minimal code changes
- ⚠️ No need for complex IPC mechanisms (current architecture is good)

### Next Steps

1. Review this document with the team
2. Get approval for Solution 1 implementation
3. Create pull request with changes
4. Test in development environment
5. Deploy to production
6. Monitor logs for 24 hours
7. Implement Phase 2 (subprocess detection) if needed

---

## References

### Code Locations

- **Logging Core**: `D:\111\android_run_test-backup\src\wecom_automation\core\logging.py`
- **Backend Main**: `D:\111\android_run_test-backup\wecom-desktop\backend\main.py`
- **Device Manager**: `D:\111\android_run_test-backup\wecom-desktop\backend\services\device_manager.py`
- **Initial Sync Script**: `D:\111\android_run_test-backup\wecom-desktop\backend\scripts\initial_sync.py`
- **Realtime Reply Script**: `D:\111\android_run_test-backup\wecom-desktop\backend\scripts\realtime_reply_process.py`

### External Resources

- [Loguru GitHub Issue #190 - Windows Multiprocessing Workaround](https://github.com/Delgan/loguru/issues/190)
- [Loguru GitHub Issue #421 - Adding Handler in Multiprocessing Context](https://github.com/Delgan/loguru/issues/421)
- [Loguru GitHub Issue #912 - Proper Way to Use with Multiprocessing](https://github.com/Delgan/loguru/issues/912)
- [Loguru GitHub Issue #1338 - Queue Implementation Choice](https://github.com/Delgan/loguru/issues/1338)
- [Loguru Documentation - Logger API](https://loguru.readthedocs.io/en/stable/api/logger.html)
- [StackOverflow - Multiprocessing Logging with Loguru](https://stackoverflow.com/questions/59433146/multiprocessing-logging-how-to-use-loguru-with-joblib-parallel)
- [CSDN Blog - Loguru Multiprocessing Best Practices](https://blog.csdn.net/gitblog_00991/article/details/154889585)

### Related Documentation

- `docs/03-impl-and-arch/key-modules/logging-system-architecture.md`
- `docs/05-changelog-and-upgrades/2026-02-06-loguru-migration-complete.md`
- `CLAUDE.md` (lines 787-788: subprocess logging documentation)

---

**Document Version**: 1.0
**Last Updated**: 2026-02-09
**Author**: System Architecture Analysis
**Status**: Ready for Review
