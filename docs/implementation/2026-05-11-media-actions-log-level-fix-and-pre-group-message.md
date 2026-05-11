# Media Actions: Log-Level Fix, Pre-Group Message & Action Reorder

**Date**: 2026-05-11
**Scope**: `auto_contact_share`, `auto_group_invite`, `factory.py`, frontend, i18n

## Problem Statement

### 1. Invisible skip reasons (auto_contact_share + auto_group_invite)

Both `AutoContactShareAction.should_execute()` and `AutoGroupInviteAction.should_execute()` logged all skip reasons at `logger.debug()`. Production logs run at INFO level, so when a media event triggered auto_blacklist but NOT auto_contact_share or auto_group_invite, the skip reason was invisible — making production debugging impossible.

### 2. Missing pre-group message feature

The auto_group_invite flow only supported sending a message **after** creating the group (`send_test_message_after_create`). Users needed the ability to send a configurable template message in the customer's **private chat** before navigating to the group creation UI — mirroring the existing `send_message_before_share` pattern in auto_contact_share.

### 3. Action ordering mismatch

The previous registration order (`contact_share → group_invite → blacklist`) meant blacklist ran last. The desired product flow is: blacklist first (block AI) → send pre-group message → create group → optionally send post-group message.

## Changes

### Log-level promotion

**Files**: `auto_contact_share.py`, `auto_group_invite.py`

All `logger.debug()` calls in `should_execute()` promoted to `logger.info()`. This affects:
- "media actions disabled" skip
- "action disabled" skip
- "no WeComService" skip (contact share only)
- "not media" skip
- "review gate rejected" skip
- "no contact name configured" skip (contact share only)
- "no group members configured" skip (group invite only)
- "already shared/blacklisted/group exists" skip
- "eligible" confirmation log

### Pre-group message

**Model**: `GroupInviteRequest` — added `send_message_before_create: bool = False` and `pre_create_message_text: str = ""`

**Workflow**: `GroupInviteWorkflowService.execute()` — between `navigate_to_chat()` and `open_chat_info()`, sends the pre-create message via `navigator.send_message()`. Errors are caught and logged but do not block group creation. 1.5s delay after sending to ensure delivery before UI navigation.

**Action**: `AutoGroupInviteAction.execute()` — reads `send_message_before_create` and `pre_create_message_text` from settings, renders template via `render_media_template()` (supports `{customer_name}`, `{kefu_name}`, `{device_serial}`), passes rendered text to `GroupChatService`.

**Service chain**: `AutoGroupInviteAction` → `GroupChatService.create_group_chat()` → `_perform_ui_group_creation()` → `GroupInviteRequest` → `GroupInviteWorkflowService`

**Settings** (3 places synced):
- `src/wecom_automation/services/media_actions/settings_loader.py`
- `wecom-desktop/backend/services/settings/defaults.py`
- `wecom-desktop/backend/routers/media_actions.py` (Pydantic model + DEFAULT_SETTINGS)

**Frontend**:
- `api.ts` — TypeScript interface updated
- `MediaActionsView.vue` — toggle + textarea + preview (mirrors auto_contact_share's pre-share message UI)
- `translations.py` — English + Chinese i18n keys added

### Action reorder

**File**: `factory.py`

Registration order changed from:
```
contact_share → group_invite → blacklist
```
to:
```
blacklist → group_invite → contact_share
```

The MediaEventBus iterates ALL actions independently — no short-circuit. Each action's `should_execute()` runs regardless of previous results. The new order ensures:
1. Blacklist fires first → customer blocked from AI reply/follow-up
2. Group invite fires second → sends pre-group message + creates group
3. Contact share fires last (if enabled — mutually exclusive with group invite via user settings)

## Files Changed

| File | Change |
|---|---|
| `src/wecom_automation/services/media_actions/actions/auto_contact_share.py` | debug → info (7 calls) |
| `src/wecom_automation/services/media_actions/actions/auto_group_invite.py` | debug → info (7 calls) + pre-group message |
| `src/wecom_automation/services/group_invite/models.py` | 2 new fields |
| `src/wecom_automation/services/group_invite/service.py` | pre-group message step |
| `src/wecom_automation/services/media_actions/group_chat_service.py` | pass-through (abstract + concrete) |
| `src/wecom_automation/services/media_actions/factory.py` | reorder |
| `src/wecom_automation/services/media_actions/settings_loader.py` | defaults |
| `wecom-desktop/backend/services/settings/defaults.py` | defaults |
| `wecom-desktop/backend/routers/media_actions.py` | Pydantic + defaults |
| `wecom-desktop/src/services/api.ts` | TypeScript interface |
| `wecom-desktop/src/views/MediaActionsView.vue` | UI toggle + textarea + preview |
| `wecom-desktop/backend/i18n/translations.py` | en + zh-CN keys |
| `tests/unit/test_auto_group_invite_action.py` | updated assertion |
| `tests/unit/test_media_actions_factory.py` | updated test name + assertion |

## Test Results

50 related tests pass. 829 total unit tests pass (2 updated for new signatures).

## Docs Updated

- `docs/features/media-auto-actions.md` — action order corrected
- `docs/04-bugs-and-fixes/resolved/2026-05-07-auto-blacklist-review-data-missing.md` — action order note updated
