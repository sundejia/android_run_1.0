# Global Log File Locking Fix - Quick Reference Card

**Problem**: Multiple subprocesses trying to write to `default-global.log` causes Windows file locking

**Solution**: Skip global log creation in subprocesses

---

## Files to Modify

### 1. `src/wecom_automation/core/logging.py`

**Change**: Add `force_global` parameter and subprocess detection

**Location**: Lines 93-144 (init_logging function)

**Add**:

```python
def init_logging(
    hostname: str | None = None,
    level: str = "INFO",
    log_dir: Path | None = None,
    console: bool = True,
    force_global: bool = False,  # <-- NEW
) -> None:
    """..."""
    global _initialized, _hostname, _log_dir

    if hostname is None:
        hostname = _get_hostname()

    _hostname = hostname
    _log_dir = log_dir or get_project_root() / "logs"
    _log_dir.mkdir(parents=True, exist_ok=True)

    _loguru_logger.remove()

    if console:
        _loguru_logger.add(
            sys.stderr,
            format=CONSOLE_FORMAT,
            level=level,
            colorize=True,
            filter=_swipe_filter,
        )

    # <-- CHANGED: Add condition
    if not _is_subprocess() or force_global:  # <-- NEW LINE
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
        )  # <-- INDENT THIS BLOCK

    _initialized = True


def _is_subprocess() -> bool:  # <-- NEW FUNCTION
    """Detect if running in subprocess by checking environment variable."""
    import os
    return os.environ.get("WECOM_SUBPROCESS", "").lower() == "true"
```

---

### 2. `wecom-desktop/backend/services/device_manager.py`

**Change**: Set `WECOM_SUBPROCESS` environment variable when spawning subprocess

**Location**: Lines 596-599 (in start_sync method)

**Change**:

```python
# Set up environment for UTF-8 output
env = os.environ.copy()
env["PYTHONIOENCODING"] = "utf-8"
env["PYTHONUTF8"] = "1"
env["WECOM_SUBPROCESS"] = "true"  # <-- ADD THIS LINE
```

---

### 3. `wecom-desktop/backend/scripts/initial_sync.py`

**Change**: Add `force_global=False` parameter

**Location**: Line 151

**Change**:

```python
# BEFORE:
init_logging(hostname=hostname, level=level, console=False)

# AFTER:
init_logging(hostname=hostname, level=level, console=False, force_global=False)
```

---

### 4. `wecom-desktop/backend/scripts/realtime_reply_process.py`

**Change**: Add `force_global=False` parameter

**Location**: Line 62

**Change**:

```python
# BEFORE:
init_logging(hostname=hostname, level=level, console=False)

# AFTER:
init_logging(hostname=hostname, level=level, console=False, force_global=False)
```

---

### 5. `wecom-desktop/backend/main.py`

**Change**: Add `force_global=True` parameter

**Location**: Line 135

**Change**:

```python
# BEFORE:
init_logging(hostname=hostname, level=level, console=True)

# AFTER:
init_logging(hostname=hostname, level=level, console=True, force_global=True)
```

---

## Testing Checklist

- [ ] Start backend: `cd wecom-desktop/backend && uvicorn main:app --reload`
- [ ] Start device 1 sync: `curl -X POST http://localhost:8765/devices/DEVICE1/sync`
- [ ] Start device 2 sync: `curl -X POST http://localhost:8765/devices/DEVICE2/sync`
- [ ] Check log files exist:
  ```bash
  ls -la logs/default-*.log
  ```
- [ ] Run health check:
  ```bash
  python scripts/check_log_health.py
  ```
- [ ] Verify no errors in logs:
  ```bash
  grep -i "permission\|locked\|denied" logs/default-*.log
  ```
- [ ] Check frontend log viewer shows device logs
- [ ] Monitor for 24 hours in production

---

## Expected Results

**Before Fix**:

```
❌ default-global.log: Permission denied (device 1)
❌ default-global.log: File locked (device 2)
✅ default-DEVICE1.log: OK
✅ default-DEVICE2.log: OK
```

**After Fix**:

```
✅ default-global.log: OK (main process only)
✅ default-DEVICE1.log: OK
✅ default-DEVICE2.log: OK
```

---

## Rollback Commands

```bash
git checkout HEAD -- src/wecom_automation/core/logging.py
git checkout HEAD -- wecom-desktop/backend/services/device_manager.py
git checkout HEAD -- wecom-desktop/backend/scripts/initial_sync.py
git checkout HEAD -- wecom-desktop/backend/scripts/realtime_reply_process.py
git checkout HEAD -- wecom-desktop/backend/main.py
```

---

## Verification Script

```bash
# Run after fix
python scripts/check_log_health.py

# Expected output:
# [OK] All log files are healthy (N/N)
```

---

## Common Issues

**Issue**: `TypeError: init_logging() got an unexpected keyword argument 'force_global'`
**Fix**: Make sure you updated `src/wecom_automation/core/logging.py` first

**Issue**: Subprocess still creates global log
**Fix**: Verify `WECOM_SUBPROCESS=true` is set in device_manager.py

**Issue**: Main process doesn't create global log
**Fix**: Verify `force_global=True` is passed in main.py

---

## References

- Full Analysis: `docs/04-bugs-and-fixes/active/2026-02-09-global-log-file-locking-analysis.md`
- Executive Summary: `docs/04-bugs-and-fixes/active/2026-02-09-global-log-file-locking-summary.md`
- Health Check Script: `scripts/check_log_health.py`

---

**Estimated Time**: 1-2 hours
**Risk Level**: Low
**Rollback**: Simple (git checkout)
