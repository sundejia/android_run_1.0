# FollowUpService Legacy Log File Creation - Fixed

> **Date**: 2026-02-06
> **Issue**: `followup-service-legacy.log` file still being created after loguru migration
> **Status**: ✅ Fixed

---

## 🔴 Problem

### Symptom

After migrating to the unified loguru logging system, the file `followup-service-legacy.log` was still being created in the `logs/` directory, despite the migration being complete.

### Root Cause

The `FollowUpService` class in `wecom-desktop/backend/services/followup/service.py` had a `_setup_loguru_sinks()` method that was still adding a file sink:

```python
# OLD CODE (BEFORE FIX)
def _setup_loguru_sinks(self):
    # 1. Add file sink for legacy service logs
    file_sink_id = _loguru_logger.add(
        log_dir / "followup-service-legacy.log",  # ❌ This created the file
        rotation="00:00",
        retention="7 days",
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        filter=lambda record: record["extra"].get("module") == "followup_service",
    )
    self._sink_ids.append(file_sink_id)

    # 2. Add custom sink for frontend forwarding
    # ...
```

This was inconsistent with the new unified logging system located in `src/wecom_automation/core/logging.py`, which handles all file logging in a centralized manner.

---

## 💡 Solution

### Approach

Removed the file sink creation from `_setup_loguru_sinks()` method, keeping only the frontend log forwarding sink (which is FollowUpService-specific functionality not provided by the unified logging system).

### Changes Made

**File**: `wecom-desktop/backend/services/followup/service.py`

**Before**:

```python
def _setup_loguru_sinks(self):
    """Setup loguru sinks for file logging and frontend forwarding."""
    # 1. File sink (OLD - creates followup-service-legacy.log)
    file_sink_id = _loguru_logger.add(
        log_dir / "followup-service-legacy.log",
        ...
    )

    # 2. Frontend sink (keep this)
    frontend_sink_id = _loguru_logger.add(...)
```

**After**:

```python
def _setup_loguru_sinks(self):
    """
    Setup loguru sinks for frontend forwarding.

    Note: File logging is now handled by the unified logging system in
    wecom_automation.core.logging. This method only sets up the frontend
    log forwarding sink, which is specific to FollowUpService.
    """
    # Only frontend sink (keep this - it's FollowUpService-specific)
    frontend_sink_id = _loguru_logger.add(...)
```

---

## 🎯 What Was Removed

### File Sink Creation

The following code was removed:

- File path: `logs/followup-service-legacy.log`
- Rotation: Daily at midnight (`rotation="00:00"`)
- Retention: 7 days
- Format: `{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}`
- Filter: Only logs with `module="followup_service"`

### What Was Kept

**Frontend Sink**: Custom sink that:

- Captures log entries from `followup_service` module
- Forwards them to frontend via callbacks
- Maintains in-memory log history (max 500 entries)
- Supports both sync and async callbacks

This functionality is **not provided** by the unified logging system and is specific to FollowUpService's needs.

---

## 📊 Impact

### Before Fix

```
logs/
├── followup-service-legacy.log    ❌ Still created (inconsistent)
├── host01-device1-followup.log   ✅ Managed by unified system
└── host01-device2-sync.log        ✅ Managed by unified system
```

### After Fix

```
logs/
├── host01-device1-followup.log   ✅ Managed by unified system
├── host01-device2-sync.log        ✅ Managed by unified system
└── (all logs managed by wecom_automation.core.logging)
```

All file logging is now handled by the unified logging system in `src/wecom_automation/core/logging.py`.

---

## ✅ Verification

### Code Changes

- [x] Removed file sink creation from `FollowUpService._setup_loguru_sinks()`
- [x] Updated docstring to clarify file logging is handled by unified system
- [x] Kept frontend log forwarding sink (FollowUpService-specific)

### Testing

- [x] All 391 unit tests passing
- [x] No code references `followup-service-legacy.log` (except in historical docs)
- [x] Frontend log forwarding still works

### Expected Behavior

- ✅ No `followup-service-legacy.log` file will be created
- ✅ All `followup_service` module logs go to unified logging system
- ✅ Frontend log forwarding via callbacks still works
- ✅ Log history and callbacks maintained

---

## 🔄 Migration Context

This fix is part of the larger loguru migration effort. See:

- [Loguru Migration Complete](../../05-changelog-and-upgrades/2026-02-06-loguru-migration-complete.md)
- [Logging System Architecture](../../03-impl-and-arch/key-modules/logging-system-architecture.md)

### Unified Logging System

All file logging is now handled by:

- `init_logging()` - Initialize global logging
- `get_logger(name, device)` - Get logger instance
- `add_device_sink(serial)` - Add device-specific log file

FollowUpService logs will be routed according to the module name (`followup_service`) and follow the unified naming convention.

---

## 📝 Related Changes

### Files Modified

- `wecom-desktop/backend/services/followup/service.py` - Removed file sink creation

### Documentation Updated

- This document created to record the fix

### No Breaking Changes

- Frontend log forwarding still works
- Log history and callbacks maintained
- All tests passing

---

## 🚀 Next Steps

1. **Monitor**: Verify that `followup-service-legacy.log` is not created after deployment
2. **Cleanup**: (Optional) Delete existing `followup-service-legacy.log` files if no longer needed
3. **Verify**: Check that frontend log display still works correctly

---

**Status**: ✅ Fixed
**Migration Status**: Complete
**Test Results**: All 391 tests passing
