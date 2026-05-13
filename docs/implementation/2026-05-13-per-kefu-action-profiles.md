# Per-Kefu Action Profiles (按客服覆盖配置)

> **Date**: 2026-05-13
> **Status**: Implemented

## Problem

When the system manages multiple phones/kefus simultaneously, all kefus share the same global `auto_group_invite` (group members, group name template) and `auto_contact_share` (contact name) configuration. There is no way to configure "Kefu A should invite Manager A to groups and share Manager X's card" while "Kefu B should invite Manager B to groups and share Manager Y's card."

Additionally, `kefu_name` in the realtime reply `MessageContext` was hardcoded to empty string, making the existing `kefu_overrides` mechanism non-functional.

## Solution

### Database: `kefu_action_profiles` table (schema v15)

```sql
CREATE TABLE kefu_action_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kefu_id INTEGER NOT NULL REFERENCES kefus(id) ON DELETE CASCADE,
    action_type TEXT NOT NULL,          -- 'auto_group_invite' | 'auto_contact_share'
    enabled BOOLEAN NOT NULL DEFAULT 1,
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(kefu_id, action_type)
);
```

Each row is a per-kefu override for one action type. `config_json` stores only fields that differ from global defaults; absent fields inherit from the global `media_auto_actions` settings.

### Settings Resolution: `kefu_resolver.py`

`resolve_media_settings(global_settings, kefu_name, db_path)` merges:

1. Global defaults (`DEFAULT_MEDIA_AUTO_ACTION_SETTINGS`)
2. Global overrides from `settings` table (`load_media_auto_action_settings`)
3. Per-kefu overrides from `kefu_action_profiles` table

Output is a dict with identical shape to `load_media_auto_action_settings()`, so downstream actions (`AutoGroupInviteAction`, `AutoContactShareAction`) require zero code changes.

Resolution flow:

1. If `kefu_name` or `db_path` is empty, return global settings unchanged (safe fallback).
2. Query `kefus` table to resolve `kefu_name` to `kefu_id`. If not found, return global settings.
3. Load all `kefu_action_profiles` rows for that `kefu_id`.
4. If no rows exist, return global settings unchanged.
5. Deep-copy global settings, then iterate over profile rows:
   - If `enabled = false` for the action type, set the section-level `enabled` to `False`.
   - Otherwise, parse `config_json` and merge its fields into the corresponding section dict.
6. Log which overrides were applied (INFO level).

Convenience wrapper `resolve_media_settings_from_db(kefu_name, settings_db_path, profiles_db_path=None)` loads global settings and resolves per-kefu overrides in one call.

### Factory Integration

`build_media_event_bus()` accepts new optional `kefu_name` parameter. When provided, it calls `resolve_media_settings()` before returning. When `None`, behavior is identical to before (fully backward compatible).

### Bug Fix: `kefu_name` Empty String

`ResponseDetector._store_messages_to_db()` now resolves kefu_name from the conversation database via `_get_kefu_name(serial)`, which queries `kefus` + `kefu_devices` tables. The result is cached per-serial for the process lifetime.

### Backend API

New router at `/api/kefu-profiles` (`routers/kefu_profiles.py`):

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | List all kefus with override status (`KefuActionProfileSummary[]`) |
| `/{kefu_id}/actions` | GET | Get per-kefu action overrides |
| `/{kefu_id}/actions/{action_type}` | PUT | Create/update override (upsert via `ON CONFLICT`). Broadcasts `kefu_action_profile_updated` WebSocket event. |
| `/{kefu_id}/actions/{action_type}` | DELETE | Remove override (revert to global). Broadcasts `kefu_action_profile_deleted` WebSocket event. |
| `/{kefu_id}/effective` | GET | Get fully resolved settings (calls `resolve_media_settings_from_db`). Uses `kefu_resolver` to merge global + per-kefu. |

Valid `action_type` values: `auto_group_invite`, `auto_contact_share`.

### Frontend

`MediaActionsView.vue` gains a "按客服覆盖配置" section below the global settings. Each kefu is a button; clicking opens an edit panel with group invite and contact share config fields.

- **Pinia store**: `wecom-desktop/src/stores/kefuProfiles.ts` (`useKefuProfilesStore`) manages profile list, selected kefu actions, and effective settings.
- **API client types**: `KefuActionProfileSummary`, `KefuActionProfile`, `EffectiveSettings` (defined in `services/api.ts`).
- **WebSocket events**: `kefu_action_profile_updated`, `kefu_action_profile_deleted` broadcast via global WebSocket manager.

### Migration from `kefu_overrides`

The v14->v15 migration automatically moves existing `kefu_overrides` entries from the settings table to `kefu_action_profiles`. The migration reads `auto_contact_share.kefu_overrides` from the `settings` table, looks up each kefu by name in the `kefus` table, and inserts a row with `action_type = 'auto_contact_share'` and `config_json = {"contact_name": "<value>"}`. The `kefu_overrides` field is deprecated and kept as a legacy fallback in `_resolve_contact_name()` for one release cycle.

### Resolution in `_resolve_contact_name`

`AutoContactShareAction._resolve_contact_name()` resolves the contact name with this priority:

1. `contact_name` from the section dict (already merged by `kefu_resolver` if a per-kefu profile exists).
2. `kefu_overrides[event.kefu_name]` (legacy fallback, deprecated).
3. Global `contact_name` (inherited when no override exists).

Since `kefu_resolver` merges per-kefu `config_json` fields into the section dict before actions run, step 1 covers both the global default and per-kefu overrides.

## Files Changed

| File | Change |
|------|--------|
| `src/wecom_automation/database/schema.py` | New table + migration v15 |
| `src/wecom_automation/services/media_actions/kefu_resolver.py` | **New** - settings merger |
| `src/wecom_automation/services/media_actions/factory.py` | `kefu_name` parameter |
| `src/wecom_automation/services/media_actions/actions/auto_contact_share.py` | Deprecate `kefu_overrides`, profile-first resolution |
| `wecom-desktop/backend/services/followup/response_detector.py` | Fix kefu_name bug + pass to factory |
| `wecom-desktop/backend/routers/kefu_profiles.py` | **New** - REST API |
| `wecom-desktop/backend/main.py` | Register new router |
| `wecom-desktop/src/stores/kefuProfiles.ts` | **New** - Pinia store |
| `wecom-desktop/src/services/api.ts` | API types + methods |
| `wecom-desktop/src/views/MediaActionsView.vue` | Per-kefu config UI section |
