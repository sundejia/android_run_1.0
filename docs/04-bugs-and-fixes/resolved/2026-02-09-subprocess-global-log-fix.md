# Subprocess Global Log File Locking - FIXED

**Date**: 2026-02-09
**Status**: ✅ RESOLVED
**Priority**: P0 - Production Blocker
**Environment**: Windows, Python 3.13.5, Loguru 0.7.3

---

## Problem

Multiple subprocesses trying to write to `default-global.log` caused Windows file locking errors.

### Root Cause

- `initial_sync.py` and `realtime_reply_process.py` called `init_logging()` which always created `default-global.log`
- Windows file locking: only one process can open a file for writing at a time
- Loguru's `enqueue=True` works with `multiprocessing.Process()` (shared memory) but NOT with `subprocess.Popen()` (independent processes)

---

## Solution

Added `serial` parameter to `init_logging()` to separate subprocess logging from main process logging.

### Implementation

**`src/wecom_automation/core/logging.py`** (lines 93-160):

```python
def init_logging(
    hostname: str | None = None,
    level: str = "INFO",
    log_dir: Path | None = None,
    console: bool = True,
    serial: str | None = None,  # NEW: device serial for subprocess isolation
) -> None:
    """
    Initialize logging configuration (supports both main and subprocess)

    Args:
        serial: Device serial number (optional)
            - If serial provided (subprocess): only write to device-specific log, NOT global.log
            - If serial NOT provided (main process): only write to global.log

    Multi-process logging isolation strategy:
        - Main process: write to {hostname}-global.log
        - Subprocess: write to {hostname}-{serial}.log, avoiding file locking conflicts
    """
    # ... setup code ...

    # Log file write strategy: based on whether serial is provided
    if serial:
        # ✅ Subprocess mode: only write device-specific log, skip global.log
        device_log_file = _log_dir / f"{hostname}-{serial}.log"
        _loguru_logger.add(
            device_log_file,
            format=SAFE_LOG_FORMAT,
            rotation="00:00",
            retention="30 days",
            encoding="utf-8",
            enqueue=True,
            filter=lambda r, s=serial: r["extra"].get("device") == s,
            level=level,
            colorize=False,
        )
    else:
        # ✅ Main process mode: only write global.log
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
```

### Updated Calls

**Main process** (`wecom-desktop/backend/main.py:135`):

```python
init_logging(hostname=hostname, level="INFO", console=True)
# Writes to: default-global.log
```

**Subprocess 1** (`wecom-desktop/backend/scripts/initial_sync.py:153`):

```python
init_logging(hostname=hostname, level=level, console=False, serial=serial)
# Writes to: default-{serial}.log
```

**Subprocess 2** (`wecom-desktop/backend/scripts/realtime_reply_process.py:62`):

```python
init_logging(hostname=hostname, level=level, console=False, serial=serial)
# Writes to: default-{serial}.log
```

---

## Results

### Before Fix

```
❌ default-global.log: Permission denied (device 1 subprocess)
❌ default-global.log: File locked (device 2 subprocess)
✅ default-DEVICE1.log: OK (via add_device_sink)
✅ default-DEVICE2.log: OK (via add_device_sink)
```

### After Fix

```
✅ default-global.log: OK (main process only)
✅ default-DEVICE1.log: OK (subprocess device 1)
✅ default-DEVICE2.log: OK (subprocess device 2)
```

---

## Testing

### Manual Test Results

1. **Single Device Sync**: ✅ Pass
2. **Concurrent Multi-Device Sync**: ✅ Pass
3. **Realtime Reply + Sync Concurrent**: ✅ Pass
4. **No File Locking Errors**: ✅ Confirmed
5. **Frontend Log Viewer**: ✅ Working (via stdout capture)
6. **Log Health Check**: ✅ All files healthy

### Verification Command

```bash
python scripts/check_log_health.py
```

---

## Key Changes

| File                        | Change                   | Impact                                   |
| --------------------------- | ------------------------ | ---------------------------------------- |
| `logging.py`                | Added `serial` parameter | Subprocess writes to device-specific log |
| `initial_sync.py`           | Pass `serial=serial`     | No global log creation                   |
| `realtime_reply_process.py` | Pass `serial=serial`     | No global log creation                   |
| `main.py`                   | No change needed         | Continues writing to global.log          |

---

## Advantages

1. ✅ **Semantic Clarity**: `serial` parameter clearly indicates device subprocess mode
2. ✅ **No File Locking**: Each process writes to separate file
3. ✅ **Code Simplicity**: No need for `add_device_sink()` call (handled internally)
4. ✅ **Backward Compatible**: Main process doesn't pass `serial`, behavior unchanged
5. ✅ **No Environment Variables**: Doesn't require subprocess detection via env vars

---

## Migration from Old Design

Old proposal (NOT implemented):

- `skip_global` parameter
- `force_global` parameter
- `_is_subprocess()` detection
- `WECOM_SUBPROCESS` environment variable

New implementation (actual):

- Single `serial` parameter
- No subprocess detection needed
- Simpler, more semantic

---

## Related Documents

- **Analysis**: `docs/04-bugs-and-fixes/active/2026-02-09-global-log-file-locking-analysis.md` (archived)
- **Summary**: `docs/04-bugs-and-fixes/active/2026-02-09-global-log-file-locking-summary.md` (archived)
- **Quick Reference**: `docs/04-bugs-and-fixes/active/2026-02-09-global-log-fix-quick-reference.md` (archived)
- **Architecture**: `docs/03-impl-and-arch/key-modules/logging-system-architecture.md` (updated)

---

**Fixed By**: Code implementation
**Reviewed**: 2026-02-09
**Status**: Production ready
