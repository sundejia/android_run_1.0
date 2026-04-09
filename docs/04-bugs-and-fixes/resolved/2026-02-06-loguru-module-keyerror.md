# Loguru KeyError: 'module' Fix

**Date**: 2026-02-06  
**Status**: ✅ Resolved  
**Severity**: Medium  
**Component**: Logging System

---

## Problem

When followup processes attempted to log messages, loguru threw a KeyError:

```
File "D:\111\android_run_test-backup\.venv\Lib\site-packages\loguru\_handler.py", line 180, in emit
formatted = precomputed_format.format_map(formatter_record)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
KeyError: 'module'
--- End of logging error ---
```

This error occurred specifically in [FOLLOWUP] logs, preventing proper logging output.

## Root Cause

The issue had two contributing factors:

1. **Format String Expects `module` Field**: The `LOG_FORMAT` in `src/wecom_automation/core/logging.py` uses `{extra[module]}` which expects all loggers to have a `module` field bound via `logger.bind(module=name)`.

```python
LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level:<8}</level> | "
    "<cyan>{extra[module]}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "  # ← KeyError here
    "<level>{message}</level>"
)
```

2. **Mixed Logger Usage**: The followup services use stdlib `logging.getLogger()` instead of loguru's `get_logger()`:

```python
# wecom-desktop/backend/services/followup/service.py
logger = logging.getLogger("followup.service")  # ← stdlib logger
```

When this stdlib logger is passed to `SidecarQueueClient`, it doesn't have the `module` field in its `extra` dict, causing the KeyError when loguru tries to format the message.

## Solution

### 1. Created Safe Log Format

Added `SAFE_LOG_FORMAT` that uses `{name}` instead of `{extra[module]}` to handle logs from any source:

```python
# Safe format compatible with both loguru and stdlib loggers
SAFE_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level:<8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "  # ← Uses {name} instead
    "<level>{message}</level>"
)
```

### 2. Updated File Handlers

Changed all file sink handlers to use `SAFE_LOG_FORMAT`:

```python
# Global log file
_loguru_logger.add(
    _log_dir / f"{hostname}-global.log",
    format=SAFE_LOG_FORMAT,  # ← Changed from LOG_FORMAT
    # ...
)

# Device-specific log file
_loguru_logger.add(
    log_dir / f"{hostname}-{serial}.log",
    format=SAFE_LOG_FORMAT,  # ← Changed from LOG_FORMAT
    # ...
)
```

### 3. Fixed SidecarQueueClient Logger Handling

Updated `SidecarQueueClient.__init__()` to properly convert stdlib loggers to loguru loggers:

```python
# Always use loguru logger to avoid format errors
if logger is None:
    from wecom_automation.core.logging import get_logger
    self._logger = get_logger(__name__)
else:
    # If a logger is provided, wrap it in a loguru logger
    from wecom_automation.core.logging import get_logger
    import logging

    if isinstance(logger, logging.Logger):
        # Use loguru logger instead, borrowing the name
        self._logger = get_logger(logger.name or "sidecar")
    else:
        # Assume it's already a loguru logger
        self._logger = logger
```

## Testing

### Before Fix

```
[INFO] [FOLLOWUP] Some message
KeyError: 'module'
--- End of logging error ---
```

### After Fix

```
[INFO] [FOLLOWUP] Some message
```

Logs now work correctly for all followup operations.

## Files Modified

1. `src/wecom_automation/core/logging.py`
   - Added `SAFE_LOG_FORMAT`
   - Updated global and device sinks to use safe format
2. `src/wecom_automation/services/integration/sidecar.py`
   - Fixed logger initialization to convert stdlib loggers to loguru

## Impact

- ✅ All FOLLOWUP logs now work correctly
- ✅ Compatible with both stdlib and loguru loggers
- ✅ No breaking changes to existing code
- ✅ File logs use safe format, console logs unchanged

## Related Issues

- Similar to the "Logger object has no attribute 'addHandler'" issue
- Part of the broader loguru migration effort

## Prevention

To avoid similar issues in the future:

1. **Use loguru everywhere**: Prefer `get_logger()` over `logging.getLogger()`
2. **Test logger compatibility**: When accepting loggers as parameters, ensure they work with the expected format
3. **Use safe formats**: For public APIs that accept loggers, use formats that don't require specific extra fields

## Lessons Learned

- Loguru format strings with `{extra[key]}` require the key to exist in the logger's context
- Mixed usage of stdlib and loguru requires careful handling
- Safe fallback formats are essential for robust logging systems
