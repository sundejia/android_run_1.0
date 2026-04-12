# Fix: Multi-Resolution Group Invite & DroidRun Port Collision

> **Status**: Fixed  
> **Date**: 2026-04-12  
> **Devices**: vivo V2357A (720×1612), vivo V2055A (1080×2400)

## Problem

The auto group invite feature failed on the 1080p device (V2055A) while working on the 720p device (V2357A). A secondary bug was also discovered: the realtime reply path defaulted all devices to DroidRun port 8080.

### Symptom 1 — Add-Member Button Not Found (1080p)

E2E test step "Find add-member button" failed on the 1080p device. The button element has no `text`, `contentDescription`, or `resourceId`, so detection relies on a pixel-bounds fallback in `_find_add_member_entry`. The hardcoded bounds were calibrated for 720px width:

```python
# Only matched on 720p — failed on 1080p
150 <= x1 and 180 <= y1 and x2 <= 360 and y2 <= 420
```

On the 1080p device, the same button appeared at `(256, 312, 436, 557)`, exceeding `x2 <= 360`.

### Symptom 2 — DroidRun Port Collision in Realtime Reply

`response_detector.py` constructed `Config()` without passing a `droidrun_port`, causing all devices to default to port 8080. When multiple devices ran realtime reply simultaneously, only one could bind the port.

## Root Cause

1. **Hardcoded pixel bounds** in `wecom_service.py` group invite helpers assumed a 720p reference device.
2. **Missing port propagation** in the realtime reply chain: `realtime_reply_manager.py` → `realtime_reply_process.py` → `response_detector.py`.

## Fix

### 1. Resolution-Aware Bounds (`wecom_service.py`)

Added `_screen_width` / `_screen_height` instance variables with `_update_screen_dimensions()` that detects screen size from the UI tree root element's bounds. Called at the start of `open_chat_info`, `tap_add_member_button`, `search_and_select_member`, and `confirm_group_creation`.

Converted all hardcoded pixel bounds to ratio-based calculations:

| Method | Before (px) | After (ratio) |
|--------|-------------|---------------|
| `_find_add_member_entry` fallback | `x2 <= 360` | `x2 <= sw * 0.52` |
| `_is_image_like_click_target` | `x1 >= 480, y1 <= 260` | `x1 >= sw * 0.44, y1 <= sh * 0.12` |
| `_find_search_button` fallback | `bounds[1] <= 160, bounds[0] >= 560` | `bounds[1] <= sh * 0.08, bounds[0] >= sw * 0.52` |
| `_find_member_result_candidates` | `bounds[0] < 150` | `bounds[0] < sw * 0.14` |

### 2. Per-Device DroidRun Port (3 files)

- **`realtime_reply_manager.py`**: Allocates unique port via `PortAllocator().allocate(serial)`, passes `--tcp-port` to subprocess, releases on stop.
- **`realtime_reply_process.py`**: Added `--tcp-port` CLI argument, passed to `detect_and_reply()`.
- **`response_detector.py`**: Added `droidrun_port` parameter to `detect_and_reply()`, with fallback to `PortAllocator` lookup.

### 3. Debug Logging (`wecom_service.py`)

Added f-string debug/warning logs to `_find_group_invite_menu_button`, `_find_add_member_entry`, `_find_group_confirm_button`, and `_update_screen_dimensions`. Also fixed pre-existing `%d`/`%s` format strings (incompatible with Loguru) to f-strings.

### 4. Bug Fixes

- Fixed `NavigationError(..., details=...)` → `context=...` (parent class `WeComAutomationError` does not accept `details` kwarg).
- Fixed Loguru-incompatible `%d`/`%s` format strings across 8 log calls.

### 5. E2E Test Enhancement (`tests/integration/test_group_invite_e2e.py`)

Extended from 8 steps (stopped at "find add-member") to 10 steps covering the full flow:

1. DroidRun Portal connection
2. WeCom launch
3. Navigate to private chats
4. Extract customer list (first screen only, no scrolling)
5. Open customer chat
6. Open chat info
7. **Tap add-member button**
8. **Search and select member**
9. **Confirm group creation**
10. Return to private chats

## Validation

Both devices pass 10/10 steps with the complete group invite flow:

| Device | Resolution | Result |
|--------|-----------|--------|
| V2357A (10AEB80XHX006D4) | 720×1612 | **10/10 PASS** |
| V2055A (9586492623004ZE) | 1080×2400 | **10/10 PASS** |

## Files Changed

| File | Change |
|------|--------|
| `src/wecom_automation/services/wecom_service.py` | Resolution-aware bounds, screen dimension caching, debug logging, Loguru format fix, `details` → `context` bug fix |
| `wecom-desktop/backend/services/followup/response_detector.py` | Accept and propagate `droidrun_port` |
| `wecom-desktop/backend/scripts/realtime_reply_process.py` | `--tcp-port` CLI argument |
| `wecom-desktop/backend/services/realtime_reply_manager.py` | Port allocation/release via `PortAllocator` |
| `tests/integration/test_group_invite_e2e.py` | Full 10-step flow with `--member` argument |
