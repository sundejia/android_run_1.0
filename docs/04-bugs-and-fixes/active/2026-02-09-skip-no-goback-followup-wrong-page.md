# Skip Button No Go-Back - Follow-Up Starts on Wrong Page

> Date: 2026-02-09
> Status: 🔴 Active (Root Cause Identified)
> Severity: P0 (Critical)
> Related: Response Detector, Queue Manager, Skip Button

## Summary

After clicking the "Skip" button in Sidecar, the system fails to return to the main page (消息列表). The follow-up (补刀) process then starts on the wrong page, causing search/click operations to fail or target wrong elements. Follow-up MUST only start on the main page.

## Symptoms

1. User clicks "Skip" button in Sidecar view
2. System does NOT navigate back to the main page
3. Follow-up process starts immediately on the current (wrong) page
4. Follow-up operations (search customer, click, send message) fail or behave incorrectly
5. User remains stuck in the chat conversation screen

## Log Evidence (日志4.txt)

**Timeline:**
```
14:28:34 | INFO | ⏭️ Skip detected during wait - stopping user processing
14:28:34 | INFO | ⏭️ Skip requested during user processing - stopping scan
14:28:35 | INFO | ✅ Queue empty, all red dot users processed
14:28:35 | INFO | ║           补刀检测 (FOLLOWUP CHECK)                      ║
14:28:35 | INFO | Building conversation list from database...
14:28:35 | INFO | Updating follow-up queue...
```

**Missing:** No `go_back()` call between skip and follow-up start.

## Root Cause Analysis

### Primary Bug: Conditional Go-Back Logic

**Location:** `wecom-desktop/backend/services/followup/response_detector.py:1299-1328`

The `_handle_skip_once()` method has flawed conditional logic:

```python
async def _handle_skip_once(self, wecom, serial: str, sidecar_client: Any | None) -> None:
    # Clear skip flag...

    # Only go back if we are in a chat screen
    try:
        screen = await wecom.get_current_screen()
    except Exception as e:
        self._logger.debug(f"[{serial}] Screen detection failed during skip handling: {e}")
        screen = None

    if screen == "chat":  # ❌ BUG: Only goes back if screen == "chat"
        try:
            await wecom.go_back()
            await asyncio.sleep(0.5)
        except Exception as e:
            self._logger.warning(f"[{serial}] Error during go_back (skip handling): {e}")
```

**Problem:** The condition `if screen == "chat"` only triggers `go_back()` when screen is exactly "chat". It FAILS to go back when:
- `screen == "other"` - User is on settings/profile/other WeCom screens
- `screen == "unknown"` - Screen detection failed
- `screen == None` - Exception occurred during detection

**Result:** After skip, the device remains on whatever screen it was on, and follow-up starts from there.

### Secondary Bug: Follow-Up Skips Page Validation

**Location:** `wecom-desktop/backend/services/followup/queue_manager.py:436-438`

```python
# NOTE: 不再调用 ensure_home_page()，避免多次返回键导致退回主屏幕。
# 这里假设调用方已保证处于可执行补刀的起始页面（如消息列表/私聊列表）。
self._log("  ⚠️ 跳过 ensure_home_page（避免退回主屏幕）", "WARN")
```

**Problem:** This comment admits the assumption that "caller has ensured correct starting page", but after skip, this assumption is **violated**. The follow-up execution doesn't validate the current screen state.

### Design Flaw: Screen Detection Returns Multiple Values

**Location:** `src/wecom_automation/services/wecom_service.py:2545-2603`

`get_current_screen()` can return:
- `"chat"` - In a chat conversation screen
- `"private_chats"` - In the private chats list (main page) ✅ Correct starting page
- `"other"` - In other WeCom screens ❌ Wrong page
- `"unknown"` - Cannot determine ❌ Potentially wrong page

**Problem:** The skip handler only handles ONE case ("chat"), ignoring three other cases.

## Screen State Transition Diagram

```
Correct Flow (Expected):
┌─────────────┐
│  Skip Click │
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│ Check Screen    │
└──────┬──────────┘
       │
       ├─► "private_chats" ──► ✅ Already on main page, skip go_back
       │
       ├─► "chat" ──────────► ✅ Go back to main page
       │
       ├─► "other" ─────────► ❌ CURRENT: Stays on wrong page (BUG!)
       │
       └─► "unknown"/None ───► ❌ CURRENT: Stays on wrong page (BUG!)
                 │
                 ▼
         ┌───────────────┐
         │ Follow-up     │ ← Starts on WRONG page!
         │ Starts Here   │
         └───────────────┘
```

## Fix Strategy

### Priority 1: Invert Conditional Logic (Critical)

**File:** `wecom-desktop/backend/services/followup/response_detector.py`

**Change:**
```python
# BEFORE (Wrong)
if screen == "chat":
    await wecom.go_back()

# AFTER (Correct)
if screen not in ["private_chats"]:
    await wecom.go_back()
    self._logger.info(f"[{serial}] ✅ Navigated back from screen: {screen}")
else:
    self._logger.info(f"[{serial}] ✅ Already on main page, no go_back needed")
```

**Rationale:** Invert the logic from whitelist to blacklist. Go back for ALL screens EXCEPT when we're confirmed to be on the main page ("private_chats").

### Priority 2: Add Defensive Screen Validation (Follow-up)

**File:** `wecom-desktop/backend/services/followup/queue_manager.py`

**Change:**
```python
# BEFORE (No validation)
# NOTE: 不再调用 ensure_home_page()，避免多次返回键导致退回主屏幕。
# 这里假设调用方已保证处于可执行补刀的起始页面（如消息列表/私聊列表）。

# AFTER (With validation)
screen = await self._wecom.get_current_screen()
if screen not in ["private_chats"]:
    self._log(f"  ⚠️ Wrong screen before follow-up: {screen}, navigating back...", "WARN")
    await self._wecom.go_back()
    await asyncio.sleep(0.5)
```

### Priority 3: Improve Logging (Debug)

Add explicit logs for:
```python
# In _handle_skip_once()
try:
    screen = await wecom.get_current_screen()
    self._logger.info(f"[{serial}] 🔍 Skip handler detected screen: {screen}")
except Exception as e:
    self._logger.warning(f"[{serial}] Screen detection failed during skip: {e}")
    screen = None
```

## Impact

**Who is affected:**
- All users using Skip button during real-time reply or follow-up
- Especially problematic when skip occurs during:
  - Screen detection failures
  - Navigation to non-chat screens
  - Error states

**Risk level:** HIGH - Follow-up operations on wrong screen can:
- Send messages to wrong customers
- Click wrong UI elements
- Cause application crashes
- Corrupt sync state

## Testing Checklist

- [ ] Skip from chat screen → Should go back to main page
- [ ] Skip from main page → Should NOT go back (already there)
- [ ] Skip from settings/profile → Should go back to main page
- [ ] Skip during screen detection failure → Should still go back (defensive)
- [ ] Verify follow-up starts correctly after skip
- [ ] Verify log shows screen detection result

## Related Issues

- Sidecar skip input box not cleared (fixed in 2026-02-09)
- Sidecar timeout/duplicate send (active: 2026-02-09)

## References

- Log file: `C:\Users\Administrator\Documents\xwechat_files\shenguo999_c8d5\msg\file\2026-02\日志4.txt`
- Code: `wecom-desktop/backend/services/followup/response_detector.py:1299-1328`
- Code: `wecom-desktop/backend/services/followup/queue_manager.py:436-438`
- Code: `src/wecom_automation/services/wecom_service.py:2545-2603` (get_current_screen)
