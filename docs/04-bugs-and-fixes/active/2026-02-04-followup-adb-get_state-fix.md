# Bug Fix: FollowupExecutor - ADBService has no attribute 'get_state'

**Date:** 2026-02-04
**Status:** Fixed
**Affected Component:** Followup System (realtime reply)

## Problem

The followup system was failing with the error:

```
[FOLLOWUP]
[15787989750086X] ❌ 连接失败: 'ADBService' object has no attribute 'get_state'
```

## Root Cause

In `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py:2016`, the code was passing `wecom.adb` (an `ADBService` instance) to `get_followup_queue_manager()`, but the `FollowupExecutor` expected an `AdbTools` instance from the `droidrun` library.

**Class hierarchy:**

- `WeComService.adb` → returns `ADBService` (from `wecom_automation.services.adb_service`)
- `ADBService.adb` → returns `AdbTools` (from `droidrun`)

The `FollowupExecutor` calls `get_state()` on the adb object, which is a method of `AdbTools`, not `ADBService`.

## Solution

Changed `response_detector.py:2016` from:

```python
adb=wecom.adb,  # ADBService instance
```

To:

```python
adb=wecom.adb.adb,  # AdbTools instance (underlying droidrun object)
```

## Files Changed

- `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py:2016`

## Related Components

- `FollowupExecutor` (`wecom-desktop/backend/servic../03-impl-and-arch/executor.py`)
- `FollowupQueueManager` (`wecom-desktop/backend/servic../03-impl-and-arch/queue_manager.py`)
- `ADBService` (`src/wecom_automation/services/adb_service.py`)

## Testing

Manual testing required:

1. Start realtime reply for a device
2. Trigger followup message
3. Verify connection succeeds and messages are sent

## Prevention

When integrating `AdbTools` with `ADBService`, always remember:

- `ADBService` wraps `AdbTools` and provides additional functionality
- If code requires the raw `AdbTools` instance (e.g., third-party integrations), access it via `service.adb.adb`
- Type hints should clearly indicate whether `AdbTools` or `ADBService` is expected
