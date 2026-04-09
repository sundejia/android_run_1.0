# Device Initialization with Messages View Verification

**Date**: 2025-12-16  
**Status**: ✅ Complete  
**Components**: Backend (devices.py), Integration with restart_wecom_if_not_on_messages.py

## Overview

Enhanced the device initialization endpoint (`POST /devices/{serial}/init`) to ensure WeCom is on the Messages view before extracting kefu information. This integration uses the `check_and_restart` function from `restart_wecom_if_not_on_messages.py` to verify and, if necessary, restart WeCom to the Messages tab before proceeding with kefu extraction.

## Problem Statement

Previously, the device initialization process had a limitation:

- **Known Limitation**: "WeCom must be in a state where kefu info is visible (Messages tab)"
- If WeCom was on a different tab (Emails, Doc, Workspace, Contacts) when initialization was called, kefu extraction would fail or extract incorrect information
- Manual intervention was required to navigate to the Messages tab before initialization

## Solution

Integrated the `check_and_restart` function from `restart_wecom_if_not_on_messages.py` into the device initialization workflow:

1. **After launching WeCom** (if `launch_wecom=True`), the system now calls `check_and_restart()`
2. **Verification**: Checks if WeCom is currently on the Messages view using `verify_messages_screen()`
3. **Automatic recovery**: If not on Messages, force-stops and restarts WeCom to ensure it opens on the Messages tab
4. **Proceed only when verified**: Kefu extraction only proceeds after confirming WeCom is on the Messages view
5. **Error handling**: Returns an error if unable to get WeCom to the Messages view

## Technical Implementation

### Backend Changes (`wecom-desktop/backend/routers/devices.py`)

#### Updated `init_device` Endpoint

**Before:**

```python
if launch_wecom:
    # Launch WeCom
    await adb.start_app(WECOM_PACKAGE)
    wecom_launched = True
    # Wait for app to load
    await asyncio.sleep(2.0)

# Get UI state and extract kefu info
await adb.get_state()
# ... extract kefu ...
```

**After:**

```python
if launch_wecom:
    # Launch WeCom
    await adb.start_app(WECOM_PACKAGE)
    wecom_launched = True
    # Wait for app to load
    await asyncio.sleep(2.0)

# Ensure WeCom is on the Messages view before proceeding
# This will check if we're on Messages, and restart if not
is_on_messages = await check_and_restart(
    serial=serial,
    use_tcp=False,
    debug=False,
    wait_after_restart=3.0,
)

if not is_on_messages:
    return InitDeviceResponse(
        success=False,
        wecom_launched=wecom_launched,
        error="Failed to ensure WeCom is on Messages view. Please try again."
    )

# Get UI state and extract kefu info
await adb.get_state()
# ... extract kefu ...
```

## Workflow

```
┌─────────────────────────────────────────────────────────────┐
│  POST /devices/{serial}/init                                 │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │ Launch WeCom (if needed)│
         └───────────┬─────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │ check_and_restart()   │
         │  - verify_messages_   │
         │    screen()           │
         │  - If not Messages:   │
         │    force-stop &       │
         │    restart            │
         │  - Verify again       │
         └───────────┬─────────────┘
                     │
         ┌───────────┴─────────────┐
         │                         │
    ┌────▼────┐              ┌────▼────┐
    │ Success │              │ Failure  │
    └────┬────┘              └────┬────┘
         │                         │
         ▼                         ▼
    Extract kefu              Return error
    from UI tree
```

## API Behavior

### Success Case

When WeCom is successfully verified/restarted to Messages view:

```json
{
  "success": true,
  "kefu": {
    "name": "wyd",
    "department": "302实验室",
    "verification_status": "未认证"
  },
  "wecom_launched": true,
  "error": null
}
```

### Failure Case

When unable to get WeCom to Messages view:

```json
{
  "success": false,
  "kefu": null,
  "wecom_launched": true,
  "error": "Failed to ensure WeCom is on Messages view. Please try again."
}
```

## Integration Points

### With `restart_wecom_if_not_on_messages.py`

- **Function used**: `check_and_restart()`
- **Parameters**:
  - `serial`: Device serial number
  - `use_tcp`: False (standard ADB connection)
  - `debug`: False (no verbose output)
  - `wait_after_restart`: 3.0 seconds (allows app to fully load)

### With `verify_messages_screen.py`

- **Indirectly used**: `check_and_restart()` internally calls `verify_messages_screen()`
- **Verification checks**:
  - Top header label must be "Messages"
  - Bottom navigation tabs must be present (Messages, Emails, Doc, Workspace, Contacts)
  - Messages tab selection state

## User Experience Impact

### Before

- Initialization could fail if WeCom was on wrong tab
- Manual navigation to Messages tab required
- Error: "Could not extract kefu info from UI" (unclear cause)

### After

- Automatic verification and recovery to Messages view
- Clear error message if recovery fails
- Higher success rate for initialization
- No manual intervention needed

## Benefits

1. **Reliability**: Ensures WeCom is in the correct state before extraction
2. **Automation**: No manual navigation required
3. **Error clarity**: Clear error messages when verification fails
4. **Recovery**: Automatic restart if WeCom is on wrong screen
5. **Consistency**: Uses same verification logic as standalone script

## Files Changed

| File                                       | Changes                                                                     |
| ------------------------------------------ | --------------------------------------------------------------------------- |
| `wecom-desktop/backend/routers/devices.py` | Added import of `check_and_restart`, integrated into `init_device` endpoint |

## Related Documentation

- **[Device Auto-Initialization](2025-12-08-device-kefu-auto-init.md)**: Original device initialization feature (now enhanced)
- **[WeCom Restart Script](2025-12-16-restart-wecom-if-not-on-messages.md)**: Standalone script that provides the `check_and_restart` function
- **[Messages Screen Verification](2025-12-16-verify-messages-screen.md)**: Core verification logic used by the restart script

## Known Limitations

1. **Timing dependent**: Verification after restart depends on app load time (3.0 second wait may need adjustment for slower devices)
2. **State reset**: Force stopping WeCom resets app state (any unsaved data may be lost)
3. **Accessibility required**: Requires DroidRun Portal running and accessibility service enabled

## Future Enhancements

Potential improvements:

1. **Configurable wait time**: Allow customization of `wait_after_restart` via API parameter
2. **Retry logic**: Retry restart if first attempt fails
3. **Debug mode**: Option to enable debug output during initialization
4. **TCP support**: Option to use TCP bridge for faster verification
