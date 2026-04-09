# Messages Screen Verification Script

**Date**: 2025-12-16  
**Status**: ✅ Complete  
**Feature Type**: Automation Utility Script

## Overview

Created a Python script (`verify_messages_screen.py`) that verifies whether the current WeCom screen is the main Messages screen. This is useful for automation workflows that need to ensure the device is on the correct screen before performing operations.

## Problem Solved

When automating WeCom interactions, it's often necessary to verify that the device is on a specific screen before proceeding. The Messages screen has distinctive characteristics (top header label, bottom navigation tabs, selected tab state) that can be reliably detected using DroidRun's accessibility tree.

## Solution

The script uses DroidRun's `AdbTools` to:

1. Retrieve the current UI accessibility tree
2. Check for the top "Messages" header label (using bounds to verify position)
3. Verify all bottom navigation tabs are present (Messages, Emails, Doc, Workspace, Contacts)
4. Detect if the Messages tab is selected/highlighted

The script returns `YES` (exit code 0) if on Messages screen, `NO` (exit code 1) otherwise.

## Key Features

### 1. Top Header Label Verification

- Finds the main header label at the top of the screen (Y position < 300px)
- Verifies the header text contains "Messages" (case-insensitive)
- When on other tabs (Emails, Doc, Workspace, Contacts), the top header will say those names instead, allowing the script to distinguish between screens

### 2. Navigation Tabs Detection

- Checks for all 5 required bottom navigation tabs
- Ensures Messages, Emails, Doc, Workspace, and Contacts are all present
- This confirms we're in the main WeCom interface, not a sub-screen

### 3. Tab Selection State

- Attempts to detect if Messages tab is selected (via `selected`, `checked` properties or class names)
- Checks if other tabs are selected (which would indicate we're NOT on Messages screen)
- Falls back to header label as primary indicator if selection state isn't exposed via accessibility APIs

### 4. Debug/Verbose Mode

- `--debug` / `--verbose` / `-v` flag for detailed evaluation output
- Shows each check with visual indicators (✓, ❌, ⚠)
- Displays:
  - Top header text and position
  - Found vs required navigation tabs
  - Tab selection state detection results
  - Final decision logic

## Technical Details

### DroidRun Integration

Uses DroidRun's `AdbTools` API:

- `adb.get_state()` - Retrieves current UI state
- `adb.raw_tree_cache` - Access to accessibility tree
- Bounds extraction from tree nodes to determine element positions

### Bounds Detection

The script extracts bounds from accessibility tree nodes using multiple property names:

- `bounds` - String format: `"[x1,y1][x2,y2]"`
- `visibleBounds`, `boundsInScreen`, `boundsInParent`, `rect` - Alternative property names
- Dict format with `left`, `top`, `right`, `bottom` keys
- List/tuple format: `[x1, y1, x2, y2]`

### Tree Navigation

Recursively searches the accessibility tree for:

- Text matching (exact or case-insensitive partial match)
- Element collection (all elements with matching text)
- Position-based filtering (top header detection using Y coordinate threshold)

## Usage

### Basic Usage

```bash
# Check if current screen is Messages screen (uses first connected device)
python verify_messages_screen.py

# Output:
# YES - Current screen is the Messages screen
# (exit code 0)
```

### With Device Serial

```bash
# Specify device serial
python verify_messages_screen.py --serial AN2FVB1706003302
```

### Debug Mode

```bash
# Enable verbose output to see evaluation criteria
python verify_messages_screen.py --debug

# Or use verbose flag
python verify_messages_screen.py --verbose
python verify_messages_screen.py -v
```

### Debug Output Example

```
============================================================
VERIFYING MESSAGES SCREEN
============================================================
Connecting to device: auto-detect
Retrieving UI state from device...
UI tree retrieved successfully

[Check 1] Looking for top header label...
  ✓ Top header found: 'Messages'
    Position: y=156px (bounds: (0, 156, 1080, 234))
  ✓ Top header contains 'Messages'

[Check 2] Looking for bottom navigation tabs...
  Required tabs: ['Messages', 'Emails', 'Doc', 'Workspace', 'Contacts']
  Found tabs: ['Contacts', 'Doc', 'Emails', 'Messages', 'Workspace']
  ✓ All required tabs found

[Check 3] Checking tab selection state...
  Found 2 'Messages' element(s) in tree
  ⚠ Messages tab selection state not detected (may not be exposed via accessibility API)
  ✓ No other tabs are selected

[DECISION LOGIC]
  ✓ Top header is 'Messages'
  ✓ All navigation tabs present
  Result: YES (on Messages screen)
============================================================
```

### TCP Bridge (Faster Reads)

```bash
# Use Portal TCP bridge for faster UI state reads
python verify_messages_screen.py --prefer-tcp --debug
```

## Implementation Details

### File Location

- `verify_messages_screen.py` (root directory)

### Key Functions

#### `find_top_header_label(node, top_threshold=300)`

Finds the main header label at the top of the screen by:

- Recursively searching all nodes
- Filtering by Y position (< 300px)
- Returning the element closest to the top

#### `is_messages_screen(tree, debug=False)`

Main verification logic:

1. Normalizes tree to list of root nodes
2. Finds and verifies top header is "Messages"
3. Checks all navigation tabs are present
4. Attempts to detect selection state
5. Returns True/False based on criteria

#### `verify_messages_screen(serial=None, use_tcp=False, debug=False)`

High-level function that:

- Connects to device via DroidRun
- Retrieves UI state
- Calls `is_messages_screen()` with tree
- Handles errors gracefully

### Decision Logic

The script uses a three-tier decision approach:

1. **Primary Indicator**: Top header label MUST be "Messages"
   - If header is "Emails", "Doc", "Workspace", or "Contacts" → Return `NO`
2. **Secondary Indicator**: All navigation tabs must be present
   - Confirms we're in main WeCom interface
3. **Tertiary Indicator**: Tab selection state (if detectable)
   - If Messages tab explicitly selected → Return `YES`
   - If another tab explicitly selected → Return `NO`
   - If selection state undetectable → Trust header label (return `YES` if header is "Messages")

## Integration with Existing Scripts

This script follows the same patterns as other automation scripts:

- `start_wecom.py` - Launches WeCom and lists Messages tab
- `switch_to_private_chats.py` - Switches message filter to Private Chats
- `get_kefu_name.py` - Extracts current user name from UI

All use:

- `droidrun.tools.adb.AdbTools` for device connection
- `get_state()` for UI tree retrieval
- `raw_tree_cache` for accessibility tree access
- Similar argument parsing (--serial, --prefer-tcp)

## Use Cases

### 1. Pre-flight Checks

Before running automation workflows, verify device is on correct screen:

```bash
if python verify_messages_screen.py; then
    python extract_message_list.py
else
    echo "Device not on Messages screen. Please navigate manually."
fi
```

### 2. Debugging Automation Failures

When automation scripts fail, verify screen state:

```bash
python verify_messages_screen.py --debug
# Shows exactly why verification fails
```

### 3. Screen State Validation

In automated test suites:

```python
import subprocess

result = subprocess.run(
    ["python", "verify_messages_screen.py", "--serial", device_serial],
    capture_output=True,
    text=True
)
assert result.returncode == 0, "Device must be on Messages screen"
```

## Limitations

1. **Accessibility API Dependent**: Requires DroidRun Portal to be running and accessibility service enabled
2. **Language Dependent**: Assumes English UI labels ("Messages", "Emails", etc.)
3. **Position Heuristics**: Top header detection uses Y < 300px threshold, which may vary by device resolution
4. **Selection State**: Tab selection state may not always be detectable via accessibility APIs, so script relies primarily on header label

## Dependencies

- `droidrun<=0.4.13` - Android automation framework (already in project dependencies)

## Related Documentation

- [DroidRun Portal Connection Failure Bug](../04-bugs-and-fixes/fixed/BUG-2025-12-13-droidrun-portal-connection-failure.md) - Important notes about avoiding `uiautomator dump` conflicts
- [Overlay Optimization](../03-impl-and-arch/key-modules/overlay_optimization.md) - Performance optimization for DroidRun overlay feature

## Future Enhancements

Potential improvements:

1. Support for Chinese UI labels ("消息", "邮件", etc.)
2. Configurable position thresholds for different device resolutions
3. Additional screen verification functions (Emails screen, Doc screen, etc.)
4. Integration into automation service as a method rather than standalone script
