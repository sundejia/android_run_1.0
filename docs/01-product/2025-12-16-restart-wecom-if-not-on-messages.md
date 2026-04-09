# WeCom Restart Script (If Not On Messages Tab)

**Date**: 2025-12-16  
**Status**: ✅ Complete  
**Feature Type**: Automation Utility Script

## Overview

Created a Python script (`restart_wecom_if_not_on_messages.py`) that checks if WeCom is on the main Messages tab, and automatically force-stops and restarts the app if it's not. This script uses the verification logic from `verify_messages_screen.py` to determine the current screen state.

## Problem Solved

During automation workflows, WeCom may end up on a different screen (e.g., Emails, Doc, Workspace, or Contacts tabs) due to user interaction, app crashes, or other automation scripts. Rather than manually navigating back to the Messages tab, this script provides an automated way to reset WeCom to the Messages screen by restarting the app.

## Solution

The script:

1. Uses `verify_messages_screen()` to check if WeCom is currently on the Messages tab
2. If not on Messages tab, force-stops WeCom using `adb shell am force-stop com.tencent.wework`
3. Restarts WeCom using DroidRun's `AdbTools.start_app()`
4. Waits for the app to load, then verifies it's back on the Messages tab

## Key Features

### 1. Screen State Verification

- Leverages `verify_messages_screen.py` to reliably detect if WeCom is on Messages tab
- Supports all the same verification checks (top header label, navigation tabs, selection state)
- Uses the same command-line arguments for device selection and TCP preference

### 2. Force Stop and Restart

- Force stops WeCom using ADB shell command: `am force-stop com.tencent.wework`
- Restarts WeCom using DroidRun's `AdbTools.start_app()` method
- Includes a configurable wait time after restart (default 3.0 seconds) before verification

### 3. Verification After Restart

- After restarting, verifies that WeCom is now on the Messages tab
- Provides clear success/failure feedback
- Warns if restart didn't result in Messages tab (possible timing issue)

### 4. Smart Behavior

- If WeCom is already on Messages tab, takes no action (no unnecessary restart)
- Provides clear status messages at each step
- Handles errors gracefully with informative messages

## Technical Details

### Force Stop Implementation

Uses `subprocess.run()` to execute ADB shell command:

```python
adb shell "am force-stop com.tencent.wework"
```

The command is executed with:

- Device serial support (if specified)
- 10-second timeout to prevent hanging
- Proper error handling and status reporting

### Restart Implementation

Uses DroidRun's `AdbTools` API:

- `AdbTools(serial=serial, use_tcp=use_tcp)` - Connect to device
- `adb.start_app(WECOM_PACKAGE)` - Launch WeCom app
- Configurable wait time after launch

### Integration with verify_messages_screen.py

The script imports and uses the `verify_messages_screen()` function from `verify_messages_screen.py`, ensuring:

- Consistent verification logic
- Same command-line argument support (--serial, --prefer-tcp, --debug)
- Reusable verification code

## Usage

### Basic Usage

```bash
# Check and restart if not on Messages tab (uses first connected device)
python restart_wecom_if_not_on_messages.py
```

### With Device Serial

```bash
# Specify device serial
python restart_wecom_if_not_on_messages.py --serial AN2FVB1706003302
```

### Debug Mode

```bash
# Enable verbose output to see verification details
python restart_wecom_if_not_on_messages.py --debug

# Or use verbose flag
python restart_wecom_if_not_on_messages.py --verbose
python restart_wecom_if_not_on_messages.py -v
```

### Custom Wait Time

```bash
# Wait 5 seconds after restart before verifying
python restart_wecom_if_not_on_messages.py --wait-after-restart 5.0
```

### TCP Bridge (Faster Reads)

```bash
# Use Portal TCP bridge for faster UI state reads
python restart_wecom_if_not_on_messages.py --prefer-tcp --debug
```

## Output Examples

### Already on Messages Tab

```
============================================================
Checking if WeCom is on Messages tab...
============================================================
YES - Current screen is the Messages screen

✓ WeCom is already on the Messages tab. No action needed.
```

### Restart Required

```
============================================================
Checking if WeCom is on Messages tab...
============================================================
NO - Current screen is NOT the Messages screen

✗ WeCom is NOT on the Messages tab. Restarting WeCom...
============================================================

Step 1: Force stopping WeCom...
✓ Force stopped WeCom (package: com.tencent.wework)

Step 2: Restarting WeCom...
Launching WeCom...
Waiting 3.0s for app to load...
✓ WeCom restarted

Step 3: Verifying WeCom is on Messages tab...
============================================================
YES - Current screen is the Messages screen

✓ Success! WeCom is now on the Messages tab.
```

## Command-Line Arguments

| Argument                       | Description                                        | Default |
| ------------------------------ | -------------------------------------------------- | ------- |
| `--serial`                     | ADB serial of target device (omit for auto-detect) | None    |
| `--prefer-tcp`                 | Use Portal TCP bridge for faster reads             | False   |
| `--debug` / `--verbose` / `-v` | Enable debug/verbose mode                          | False   |
| `--wait-after-restart`         | Seconds to wait after restart before verifying     | 3.0     |

## Exit Codes

- `0` - Success: WeCom is (or was successfully restarted to) the Messages tab
- `1` - Failure: Restart did not result in Messages tab (or other error)

## Implementation Details

### File Location

- `restart_wecom_if_not_on_messages.py` (root directory)

### Key Functions

#### `force_stop_wecom(serial=None)`

Force stops WeCom app using ADB:

- Constructs ADB command with optional serial
- Executes `am force-stop` command via subprocess
- Returns True/False based on success
- Handles timeouts and errors gracefully

#### `restart_wecom(adb, wait_seconds=3.0)`

Restarts WeCom app:

- Uses DroidRun's `AdbTools.start_app()` method
- Waits specified time for app to load
- Provides status messages

#### `check_and_restart(serial=None, use_tcp=False, debug=False, wait_after_restart=3.0)`

Main workflow function:

1. Verifies current screen state using `verify_messages_screen()`
2. If not on Messages, force stops WeCom
3. Restarts WeCom
4. Verifies final state
5. Returns True/False based on success

## Integration with Existing Scripts

This script complements other automation utilities:

- `verify_messages_screen.py` - Screen verification (imported and used)
- `start_wecom.py` - WeCom launch utility
- `switch_to_private_chats.py` - Navigation to Private Chats filter
- `get_kefu_name.py` - Extract current user name

All follow similar patterns:

- DroidRun `AdbTools` for device connection
- Consistent command-line argument structure
- Clear status messages and error handling

## Use Cases

### 1. Pre-Workflow Reset

Reset WeCom to Messages tab before running automation:

```bash
# Ensure WeCom is on Messages tab before extraction
python restart_wecom_if_not_on_messages.py
python extract_message_list.py
```

### 2. Recovery from Automation Failures

Recover when automation leaves WeCom on wrong screen:

```bash
# Reset WeCom after failed automation
python restart_wecom_if_not_on_messages.py --debug
```

### 3. Scheduled Maintenance

Regularly ensure WeCom is in correct state:

```bash
# Check and reset every hour (via cron)
0 * * * * cd /path/to/project && python restart_wecom_if_not_on_messages.py
```

### 4. Script Integration

Use programmatically in Python:

```python
import subprocess

result = subprocess.run(
    ["python", "restart_wecom_if_not_on_messages.py", "--serial", device_serial],
    capture_output=True,
    text=True
)
if result.returncode == 0:
    print("WeCom is ready on Messages tab")
else:
    print("Failed to reset WeCom to Messages tab")
```

## Limitations

1. **App State Reset**: Force stopping the app will reset its state - any unsaved data may be lost
2. **Timing Dependent**: Verification after restart depends on app load time - may need to adjust `--wait-after-restart` for slower devices
3. **Accessibility Dependent**: Requires DroidRun Portal running and accessibility service enabled (same as `verify_messages_screen.py`)
4. **Language Dependent**: Assumes English UI labels (inherited from `verify_messages_screen.py`)

## Dependencies

- `droidrun<=0.4.13` - Android automation framework (already in project dependencies)
- `verify_messages_screen.py` - Screen verification logic (local file)

## Related Documentation

- [Messages Screen Verification Script](2025-12-16-verify-messages-screen.md) - Detailed documentation of verification logic used by this script
- [DroidRun Portal Connection Failure Bug](../04-bugs-and-fixes/fixed/BUG-2025-12-13-droidrun-portal-connection-failure.md) - Important notes about ADB and DroidRun usage

## Integration

### Device Initialization Endpoint

The `check_and_restart()` function is now integrated into the device initialization workflow:

- **Endpoint**: `POST /devices/{serial}/init`
- **Usage**: Automatically called during device initialization to ensure WeCom is on Messages view before extracting kefu information
- **See**: [Device Initialization with Messages View Verification](2025-12-16-device-init-messages-view-verification.md) for details

This integration ensures that when devices are first initialized via `http://localhost:5173/devices`, WeCom is automatically verified and, if necessary, restarted to the Messages view before proceeding with kefu extraction.

## Future Enhancements

Potential improvements:

1. **Conditional Restart**: Option to only verify without restarting
2. **Retry Logic**: Retry restart if first attempt fails
3. **State Preservation**: Attempt to preserve app state before restart (if possible)
4. **Multiple Screen Support**: Support for resetting to other screens (Emails, Doc, etc.)
5. **Additional Integrations**: Add as method to other automation service classes
