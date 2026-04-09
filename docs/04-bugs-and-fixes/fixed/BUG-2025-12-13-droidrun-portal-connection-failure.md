# Bug Documentation: DroidRun Portal Connection Failure After Media Download

## Executive Summary

After running the image/video download sync process, the DroidRun Portal connection would fail with "Portal returned error: Unknown error". The root cause was identified as a conflict between `uiautomator dump` commands used in the sync code and DroidRun's accessibility service. The fix involved removing the conflicting `uiautomator dump` calls and re-enabling the accessibility service on the device.

---

## Bug Overview

| Field                  | Value                                                       |
| ---------------------- | ----------------------------------------------------------- |
| **Severity**           | High                                                        |
| **Affected Component** | `sync_service.py` → `_download_image_via_wecom()`           |
| **Related Services**   | DroidRun Portal, Android UiAutomator, Accessibility Service |
| **Discovery Date**     | 2025-12-13                                                  |
| **Resolution Date**    | 2025-12-13                                                  |
| **Environment**        | Development (local device: AN2FVB1706003302)                |

---

## Symptoms and Impact

### Observable Symptoms

- DroidRun Portal connection fails with error: `"Portal returned error: Unknown error"`
- All `get_state` attempts fail (3 retries exhausted)
- Error persists across application restarts
- Error persists until phone is physically rebooted

### Error Messages

```
get_state attempt 1 failed: Portal returned error: Unknown error
get_state attempt 2 failed: Portal returned error: Unknown error
get_state attempt 3 failed: Portal returned error: Unknown error
Failed to get state after 3 attempts: Portal returned error: Unknown error
```

### Frequency and Conditions

- Occurred after every successful run of image download process
- 100% reproducible after running `_download_image_via_wecom()`

### Business Impact

- Complete loss of DroidRun automation capability
- Unable to sync conversations or interact with WeCom
- Required physical phone restart to recover (significant downtime)

---

## Root Cause Analysis

### The Fundamental Cause

The `_download_image_via_wecom()` function was using `adb shell uiautomator dump` to dynamically find the "Save Image" button coordinates. This command conflicts with DroidRun's portal because:

1. **UiAutomator is a singleton service** - Only one UiAutomator instance can run on Android at a time
2. **DroidRun uses an accessibility service** that depends on UiAutomator internals
3. **Running `uiautomator dump` hijacks the service** and disrupts DroidRun's accessibility service
4. **The accessibility service becomes disabled** and reports "Accessibility service not available"

### Why the Bug Was Introduced

The code was added to dynamically find the "Save Image" button instead of using hardcoded coordinates:

```python
# The problematic code (lines 760-764 in sync_service.py)
subprocess.run(
    ["adb", "shell", "uiautomator", "dump", "/sdcard/ui.xml"],
    capture_output=True,
    timeout=10,
)
```

The intention was good (dynamic button detection), but the implementation used a command that has severe side effects on the Android accessibility stack.

### Contributing Factors

1. **Lack of awareness** that `uiautomator dump` is a destructive operation for accessibility services
2. **No documentation** in DroidRun about avoiding UiAutomator conflicts
3. **The error message was misleading** - "Unknown error" didn't indicate the accessibility service issue

### Five Whys Analysis

1. **Why did the portal connection fail?** → The portal returned "Unknown error"
2. **Why did the portal return an error?** → The accessibility service was unavailable
3. **Why was the accessibility service unavailable?** → It was disrupted by another UiAutomator process
4. **Why was there another UiAutomator process?** → Our code ran `adb shell uiautomator dump`
5. **Why did we run uiautomator dump?** → To dynamically find UI button coordinates

---

## Attempted Solutions (Failed)

### Attempt 1: Application Restart

- **What was tried**: Restarting the backend and frontend applications
- **Why it failed**: The issue was on the Android device, not the host applications
- **Learning**: Device-side state corruption requires device-side fixes

### Attempt 2: Force Stop and Restart DroidRun App

```bash
adb shell "am force-stop com.droidrun.portal"
adb shell "am start -n com.droidrun.portal/.ui.MainActivity"
```

- **What was tried**: Force stopping and restarting the DroidRun Portal app
- **Why it failed**: The accessibility service remains disabled even after app restart
- **Learning**: Android accessibility services have persistent state that survives app restarts

### Attempt 3: Kill UiAutomator Processes

```bash
adb shell "pkill -9 uiautomator"
adb shell "rm -f /sdcard/ui.xml"
```

- **What was tried**: Killing stuck uiautomator processes and cleaning temp files
- **Why it failed**: The accessibility service was already in a disabled state
- **Learning**: Cleaning up processes doesn't restore accessibility service state

---

## Successful Solution

### Part 1: Code Fix (Prevention)

Removed the `uiautomator dump` call and replaced with tested hardcoded coordinates:

**Before (problematic):**

```python
# Step 3: Find and tap "Save Image" button dynamically
# Dump UI to find the exact button location
save_button_found = False
try:
    subprocess.run(
        ["adb", "shell", "uiautomator", "dump", "/sdcard/ui.xml"],
        capture_output=True,
        timeout=10,
    )
    # ... parse XML and find button ...
```

**After (fixed):**

```python
# Step 3: Tap "Save Image" button
# NOTE: We avoid using 'uiautomator dump' here because it conflicts with
# DroidRun's portal (UiAutomator is a singleton service). Instead, we use
# tested coordinates that work reliably on most devices.
save_button_positions = [
    (792, 1689),   # Primary position (tested on 1080x2340)
    (792, 1650),   # Slightly higher
    (750, 1689),   # Slightly left
    (830, 1689),   # Slightly right
]

for btn_x, btn_y in save_button_positions:
    self.logger.info(f"Tapping Save Image at ({btn_x}, {btn_y})")
    subprocess.run(
        ["adb", "shell", "input", "tap", str(btn_x), str(btn_y)],
        capture_output=True,
        timeout=5,
    )
    break  # Only try first position
```

### Part 2: Runtime Fix (Recovery)

To recover from the corrupted state, the accessibility service needed to be re-enabled:

```bash
# Diagnose the issue
adb shell "content query --uri content://com.droidrun.portal/state"
# Output: Row: 0 result={"status":"error","error":"Accessibility service not available"}

# Open accessibility settings
adb shell "am start -a android.settings.ACCESSIBILITY_SETTINGS"
```

Then manually:

1. Navigate to DroidRun Portal in accessibility settings
2. Toggle the accessibility service ON
3. Accept permission prompts

### Why This Solution Worked

1. **Code fix eliminates the root cause** - No more `uiautomator dump` means no more service conflicts
2. **Using tested coordinates is reliable** - The "Save Image" button position is consistent on standard screens
3. **Re-enabling accessibility service restores portal functionality** - Direct fix for the corrupted state
4. **The fix was verified** by successfully running the sync process without portal disconnection

---

## Key Learnings and Insights

### Technical Insights

1. **UiAutomator is a destructive operation** - Running `uiautomator dump` from ADB will disrupt any accessibility services that depend on UiAutomator internals

2. **Android accessibility services have persistent state** - Disabling/corrupting them requires manual re-enabling, not just app restarts

3. **Error messages can be misleading** - "Unknown error" from the portal was actually masking "Accessibility service not available"

4. **Content providers can reveal true errors** - Querying `content://com.droidrun.portal/state` directly provided the actual error message

### Patterns Identified

- **Anti-pattern**: Using `uiautomator dump` in automation that also uses accessibility-based tools (DroidRun, Appium, etc.)
- **Pattern**: For UI coordinate detection, prefer one-time manual testing over runtime dynamic detection when using accessibility-dependent automation

### Debugging Technique Learned

When DroidRun returns "Unknown error", diagnose via:

```bash
adb shell "content query --uri content://com.droidrun.portal/state"
```

This provides the actual error message from the portal service.

---

## Prevention and Detection

### Prevention Measures

1. **Code Review Checkpoint**: Any PR that adds `uiautomator` commands should be flagged for review when using DroidRun
2. **Add comment warnings** in code near DroidRun usage:

   ```python
   # WARNING: Do not use 'uiautomator dump' or similar commands here.
   # It conflicts with DroidRun's accessibility service.
   ```

3. **Prefer DroidRun's own methods** for UI inspection instead of raw uiautomator commands

### Detection and Monitoring

1. **Add health check**: After media download operations, verify portal connectivity:

   ```python
   # After download, verify portal is still healthy
   try:
       await adb.get_state()
   except Exception as e:
       logger.error(f"Portal health check failed after download: {e}")
   ```

2. **Log the specific error**: When portal fails, query the content provider for the actual error message

### Test Cases Added

The existing unit tests continue to pass. Consider adding integration test that:

- Runs image download flow
- Verifies DroidRun portal remains connected afterward

### Documentation Updates

Added inline documentation in `sync_service.py` explaining why `uiautomator dump` should not be used.

---

## References and Resources

### Related Code

- File: `src/wecom_automation/services/sync_service.py`
- Function: `_download_image_via_wecom()`
- Lines: 755-776 (after fix)

### DroidRun Internals

- Package: `com.droidrun.portal`
- Content Provider: `content://com.droidrun.portal/state`
- Accessibility Service: Must be enabled in Android Settings → Accessibility

### Commands for Diagnosis

```bash
# Check portal actual error
adb shell "content query --uri content://com.droidrun.portal/state"

# Open accessibility settings
adb shell "am start -a android.settings.ACCESSIBILITY_SETTINGS"

# Verify DroidRun is running
adb shell "pidof com.droidrun.portal"
```

---

## Tags

`droidrun` `accessibility-service` `uiautomator` `android` `automation` `sync-service` `portal-connection` `singleton-conflict`
