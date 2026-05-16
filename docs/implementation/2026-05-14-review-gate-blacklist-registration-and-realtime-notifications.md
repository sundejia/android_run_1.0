# Review Gate AutoBlacklistAction Registration & Realtime Notifications

> **Date**: 2026-05-14
> **Status**: Implemented

## Problem

Three issues in the media auto-actions (审核图片→拉群/发名片) pipeline:

### 1. AutoBlacklistAction missing from webhook path

`review_gate_runtime.py`'s `_register_default_actions()` only registered `AutoGroupInviteAction` and `AutoContactShareAction`, but **not** `AutoBlacklistAction`. This meant that when a review verdict arrived via webhook (`POST /api/webhooks/image-review` → `ReviewGate.on_verdict()` → `bus.emit()`), the auto-blacklist step was silently skipped. Only the sync/realtime-reply path (which uses `build_media_event_bus()` in `factory.py`) correctly ran all three actions.

### 2. Inconsistent action ordering between two entry paths

`build_media_event_bus()` (sync & realtime-reply) registered actions in order: **blacklist → group invite → contact share**.

`_register_default_actions()` (webhook path) registered: **group invite → contact share** — missing blacklist entirely.

The same customer, same config, could get different behavior depending on which code path triggered the action.

### 3. No realtime feedback in frontend

`MediaActionsView.vue` defined no WebSocket listeners for `media_action_triggered` or `media_action_settings_updated` events. Operators had to wait for a 10-second polling refresh to see any results from test triggers or live actions.

## Resolution

### Fix 1 & 2: Register all three actions in webhook path

**File**: `wecom-desktop/backend/services/review_gate_runtime.py`

- `_register_default_actions()` now accepts `db_path` parameter
- Registers all three actions in the same order as `build_media_event_bus()`:
  1. `AutoBlacklistAction(BlacklistWriter(db_path), db_path=db_path)` — pure DB, no WeComService needed
  2. `AutoGroupInviteAction(group_chat_service=None)` — placeholder until `bind_wecom_service()`
  3. `AutoContactShareAction(ContactShareService(wecom_service=None), db_path=None)` — placeholder
- `bind_wecom_service()` now handles `auto_blacklist` by updating `action._db_path` and `action._writer._db_path`
- Also added `action._db_path = db_path` for `auto_group_invite` (was previously missing)

### Fix 3: Frontend WebSocket integration

**File**: `wecom-desktop/src/views/MediaActionsView.vue`

- Imports `useGlobalWebSocketStore` and `GlobalWebSocketEvent`
- Registers two WebSocket listeners on mount:
  - `media_action_triggered`: pushes results into `realtimeNotifications` array (max 20)
  - `media_action_settings_updated`: auto-reloads settings when changed from another session
- Adds **Realtime Notifications panel** UI (cyan-bordered card) showing: action name, status badge, customer name, message, timestamp
- 30-second auto-cleanup timer removes stale notifications
- All listeners and timers cleaned up on unmount

## Files changed

| File | Change |
|------|--------|
| `wecom-desktop/backend/services/review_gate_runtime.py` | Register AutoBlacklistAction, handle in bind_wecom_service |
| `wecom-desktop/src/views/MediaActionsView.vue` | WebSocket listeners + realtime notifications UI |

## Tests

Existing tests unaffected — `test_webhook_drives_gate.py` monkeypatches `get_review_gate` with a custom bus, so the default action registration is bypassed. The frontend spec (`MediaActionsView.spec.ts`) tests component rendering and save flows.

## Related docs

- [Media Actions Settings Dedup SSOT (2026-05-12)](./2026-05-12-media-actions-settings-dedup-ssot.md)
- [Contact Share + Review Gate (2026-05-09)](./2026-05-09-contact-share-review-gate.md)
- [Per-Device Action Profiles (2026-05-13)](./2026-05-13-per-kefu-action-profiles.md)
