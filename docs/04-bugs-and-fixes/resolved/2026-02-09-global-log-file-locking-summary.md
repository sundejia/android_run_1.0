# Global Log File Locking - Executive Summary

**Issue**: `default-global.log` file locked in multi-device environment
**Status**: Root Cause Identified
**Priority**: P0 - Production Blocker
**Date**: 2026-02-09

---

## The Problem (TL;DR)

When multiple devices sync in parallel, subprocesses try to write to `default-global.log`, causing Windows file locking errors.

**Why**: Loguru's `enqueue=True` works with `multiprocessing.Process()` (shared memory) but NOT with `subprocess.Popen()` (independent processes).

---

## Root Cause

```python
# Main process (main.py)
init_logging()  # Creates logs/default-global.log with enqueue=True

# Subprocess 1 (initial_sync.py)
init_logging()  # Tries to open logs/default-global.log ❌ LOCKED!

# Subprocess 2 (realtime_reply_process.py)
init_logging()  # Tries to open logs/default-global.log ❌ LOCKED!
```

**Windows File Locking**: Only one process can open a file for writing at a time.

---

## Quick Fix (1-2 Hours)

Add `force_global` parameter to skip global log in subprocesses:

```python
# src/wecom_automation/core/logging.py
def init_logging(..., force_global=False):
    if not _is_subprocess() or force_global:
        # Only create global log in main process
        _loguru_logger.add(_log_dir / f"{hostname}-global.log", ...)

def _is_subprocess():
    # Check environment variable set by DeviceManager
    return os.environ.get("WECOM_SUBPROCESS") == "true"
```

```python
# wecom-desktop/backend/services/device_manager.py
env = os.environ.copy()
env["WECOM_SUBPROCESS"] = "true"  # Mark as subprocess
```

```python
# Main process
init_logging(force_global=True)  # ✅ Creates global log

# Subprocess scripts
init_logging(force_global=False)  # ✅ Skips global log
```

---

## Solution Comparison

| Solution                          | Complexity         | Time     | Reliability  | Recommendation |
| --------------------------------- | ------------------ | -------- | ------------ | -------------- |
| **Skip global log in subprocess** | ⭐ Low             | 1-2 hrs  | ✅ High      | **DO THIS**    |
| PID suffix on log files           | ⭐⭐ Medium        | 2-3 hrs  | ✅ High      | Alternative    |
| Named pipes / IPC                 | ⭐⭐⭐ High        | 1-2 days | ⚠️ Medium    | Overkill       |
| Central log service               | ⭐⭐⭐⭐ Very High | 1 week   | ✅ Very High | Future         |

---

## Implementation Steps

### 1. Modify `src/wecom_automation/core/logging.py`

```python
def init_logging(
    hostname: str | None = None,
    level: str = "INFO",
    log_dir: Path | None = None,
    console: bool = True,
    force_global: bool = False,  # ← NEW PARAMETER
) -> None:
    """Initialize global logging.

    Args:
        force_global: If True, always create global log (even in subprocess)
                      Use this only in main process.
    """
    # ... existing code ...

    # CHANGED: Only create global log if not in subprocess OR force_global=True
    if not _is_subprocess() or force_global:
        _loguru_logger.add(
            _log_dir / f"{hostname}-global.log",
            ...
        )


def _is_subprocess() -> bool:
    """Detect if running in subprocess by checking environment variable."""
    import os
    return os.environ.get("WECOM_SUBPROCESS", "").lower() == "true"
```

### 2. Update `wecom-desktop/backend/services/device_manager.py`

```python
async def start_sync(self, serial: str, ...):
    # ... existing code ...

    # Set up environment
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["WECOM_SUBPROCESS"] = "true"  # ← MARK AS SUBPROCESS

    # Create subprocess with this environment
    process = await asyncio.create_subprocess_exec(
        *cmd,
        env=env,  # ← PASS ENV
        ...
    )
```

### 3. Update subprocess scripts

**`wecom-desktop/backend/scripts/initial_sync.py`** (line 151):

```python
# BEFORE:
init_logging(hostname=hostname, level=level, console=False)

# AFTER:
init_logging(hostname=hostname, level=level, console=False, force_global=False)
```

**`wecom-desktop/backend/scripts/realtime_reply_process.py`** (line 62):

```python
# BEFORE:
init_logging(hostname=hostname, level=level, console=False)

# AFTER:
init_logging(hostname=hostname, level=level, console=False, force_global=False)
```

### 4. Update main process

**`wecom-desktop/backend/main.py`** (line 135):

```python
# BEFORE:
init_logging(hostname=hostname, level=level, console=True)

# AFTER:
init_logging(hostname=hostname, level=level, console=True, force_global=True)
```

---

## Testing

```bash
# 1. Start backend
cd wecom-desktop/backend
uvicorn main:app --reload --port 8765

# 2. Start multiple device syncs
curl -X POST http://localhost:8765/devices/DEVICE1/sync
curl -X POST http://localhost:8765/devices/DEVICE2/sync

# 3. Check logs
ls -la logs/
# Expected:
# - default-global.log (main process only)
# - default-DEVICE1.log (device 1)
# - default-DEVICE2.log (device 2)

# 4. Verify no errors
grep -i "permission\|locked\|denied" logs/default-*.log
# Should return: (empty)
```

---

## Expected Results

✅ **Before Fix**:

- Multiple processes try to open `default-global.log`
- Windows file locking errors
- Lost or corrupted logs

✅ **After Fix**:

- Main process: writes to `default-global.log`
- Subprocess 1: writes to `default-DEVICE1.log`
- Subprocess 2: writes to `default-DEVICE2.log`
- All subprocess logs captured via stdout → WebSocket → Frontend
- No file locking errors

---

## Rollback Plan

If issues occur:

```bash
# 1. Revert changes
git checkout HEAD -- src/wecom_automation/core/logging.py
git checkout HEAD -- wecom-desktop/backend/scripts/initial_sync.py
git checkout HEAD -- wecom-desktop/backend/scripts/realtime_reply_process.py
git checkout HEAD -- wecom-desktop/backend/main.py
git checkout HEAD -- wecom-desktop/backend/services/device_manager.py

# 2. Restart backend
cd wecom-desktop/backend
uvicorn main:app --reload --port 8765
```

---

## Monitoring

Run health check script:

```bash
python scripts/check_log_health.py
```

Expected output:

```
Checking log files in logs/

📄 default-global.log
   Status: healthy
   Size: 191.95 KB
   Last modified: 2026-02-09 17:44:12

✅ default-9586492623004ZE.log: 255.4 KB
✅ default-AN2FVB1706003302.log: 8.46 KB
```

---

## Key Insights

1. **Current Architecture Already Works**: Subprocess logs are captured via stdout and displayed in frontend
2. **Only Backend Logs Need Global File**: Device logs work perfectly with per-device files
3. **Simple Fix**: Just need to skip global log creation in subprocess
4. **No IPC Needed**: Existing stdout → WebSocket → Frontend flow is sufficient
5. **Low Risk**: Minimal code changes, easy to rollback

---

## References

- **Full Analysis**: `docs/04-bugs-and-fixes/active/2026-02-09-global-log-file-locking-analysis.md`
- **Loguru Issue #190**: [Windows Multiprocessing Workaround](https://github.com/Delgan/loguru/issues/190)
- **Loguru Issue #421**: [Handler in Multiprocessing Context](https://github.com/Delgan/loguru/issues/421)
- **Loguru Issue #912**: [Proper Way with Multiprocessing](https://github.com/Delgan/loguru/issues/912)

---

**Next Steps**:

1. ✅ Review this summary with team
2. ⏳ Approve implementation plan
3. ⏳ Create pull request
4. ⏳ Test in development
5. ⏳ Deploy to production
6. ⏳ Monitor for 24 hours

---

**Document Version**: 1.0
**Author**: System Architecture Analysis
**Status**: Ready for Implementation
