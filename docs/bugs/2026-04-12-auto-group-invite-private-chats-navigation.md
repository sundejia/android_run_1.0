# Fix: Auto Group Invite Leaves Realtime Scan on "All" Instead of Private Chats

> **Status**: Fixed  
> **Date**: 2026-04-12  
> **Area**: Realtime reply (`response_detector`), media auto-actions (`AutoGroupInviteAction`), `WeComService`

## Problem

During **Phase 1 realtime reply** (red-dot scan), when a customer sent an **image or video**, the pipeline stored messages, emitted a `MediaEvent`, and `AutoGroupInviteAction` ran the full **group invite workflow**. After success, the Android UI stayed on the **new group chat** screen.

When control returned to `_process_unread_user_with_wait`, **Step 7** performed a single `go_back()`. From a freshly created group chat, WeCom often lands on the **"All"** message list, not the **"Private Chats"** filter. The scan loop then called `_detect_first_page_unread` on the wrong list, so behavior diverged from the intended "private chats only" scan.

## Root Cause

1. `GroupInviteWorkflowService.create_group_chat` ends on the **group chat** screen (by design: `confirm_group_creation` waits until `get_current_screen() == "chat"`).
2. No step reset the message list filter back to private chats before returning to the detector loop.
3. `WeComService.ensure_on_private_chats()` previously treated `screen == "chat"` as: `go_back()` once → **return True** without re-checking whether the list filter was actually "Private Chats".

## Fix (three layers)

1. **`WeComService.ensure_on_private_chats()`** (`src/wecom_automation/services/wecom_service.py`): After `go_back()` from `chat`, re-read `get_current_screen()`. If not `private_chats`, call `switch_to_private_chats()`.
2. **`GroupChatService.restore_navigation()`** + **`AutoGroupInviteAction.execute()` `finally`**: Always call `restore_navigation()` after `create_group_chat` (success, failure, or exception), delegating to `ensure_on_private_chats()`.
3. **`ResponseDetector` Step 7** (`wecom-desktop/backend/services/followup/response_detector.py`): After `go_back()` from the customer session, call `ensure_on_private_chats()` again as a safety net (including the generic error path).

## Tests

| File                                          | Coverage                                                                                                                |
| --------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `tests/unit/test_auto_group_invite_action.py` | `restore_navigation` invoked on success, failure, exception; failures in `restore_navigation` do not mask action result |
| `tests/unit/test_group_chat_service.py`       | `restore_navigation` delegates to `WeComService`, no-op without wecom, graceful on exception                            |

## Related docs

- [Media Auto-Actions](../features/media-auto-actions.md)
- [Android group invite workflow](../implementation/2026-04-04-android-group-invite-workflow.md)
- [Multi-resolution group invite & DroidRun port](2026-04-12-multi-resolution-group-invite-and-droidrun-port-fix.md) (same date, different issue)
