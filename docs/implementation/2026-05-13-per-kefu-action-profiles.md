# Per-Device Action Profiles (按设备覆盖配置)

> **Date**: 2026-05-13
> **Status**: Implemented
> **Supersedes**: Per-kefu action profiles (schema v15) → per-device action profiles (schema v16)

## Problem

When the system manages multiple phones simultaneously, all devices share the same global `auto_group_invite` and `auto_contact_share` configuration. The original per-kefu approach (schema v15, keyed by `kefu_id`) was replaced by a device-centric model because:

1. Each phone is the natural configuration boundary — the same kefu may use different phones with different group members or contacts.
2. `device_serial` is always available at runtime (no kefu_name → kefu_id → device_serial resolution chain needed).
3. Reduces complexity: factory and resolver take `device_serial` directly instead of resolving via junction tables.

## Solution

### Resolution Chain (Target)

```
Code defaults (DEFAULT_MEDIA_AUTO_ACTION_SETTINGS)
  → Global settings (settings table, category=media_auto_actions)
    → Device overrides (device_action_profiles table)
```

### Database: `device_action_profiles` table (schema v16)

```sql
CREATE TABLE device_action_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_serial TEXT NOT NULL,
    action_type TEXT NOT NULL,          -- 'auto_group_invite' | 'auto_contact_share'
    enabled BOOLEAN NOT NULL DEFAULT 1,
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(device_serial, action_type)
);
```

Each row is a per-device override for one action type. `config_json` stores only fields that differ from global defaults; absent fields inherit from the global `media_auto_actions` settings.

### Migration: v15 → v16

Data is migrated from `kefu_action_profiles` to `device_action_profiles` by joining through `kefu_devices` → `devices` tables to resolve `kefu_id → device_serial`. The migration:

1. Creates `device_action_profiles` table + indexes + trigger.
2. Reads all rows from `kefu_action_profiles`.
3. For each row, resolves `kefu_id → device_serial` via `kefu_devices` junction table.
4. Inserts into `device_action_profiles` (ON CONFLICT IGNORE to handle multiple kefus per device).

### Settings Resolution: `device_resolver.py`

`resolve_media_settings_by_device(global_settings, device_serial, db_path)` merges:

1. Global defaults (`DEFAULT_MEDIA_AUTO_ACTION_SETTINGS`)
2. Global overrides from `settings` table (`load_media_auto_action_settings`)
3. Per-device overrides from `device_action_profiles` table

Output is a dict with identical shape to `load_media_auto_action_settings()`, so downstream actions require zero code changes.

Resolution flow:

1. If `device_serial` or `db_path` is empty, return global settings unchanged (safe fallback).
2. Load all `device_action_profiles` rows for that `device_serial`.
3. If no rows exist, return global settings unchanged.
4. Deep-copy global settings, then iterate over profile rows:
   - If `enabled = false` for the action type, set the section-level `enabled` to `False`.
   - Otherwise, parse `config_json` and merge its fields into the corresponding section dict.
5. Log which overrides were applied (INFO level).

Convenience wrapper `resolve_media_settings_by_device_from_db(device_serial, settings_db_path, profiles_db_path=None)` loads global settings and resolves per-device overrides in one call.

### Factory Integration

`build_media_event_bus()` accepts new optional `device_serial` parameter. When provided, it calls `resolve_media_settings_by_device()` before returning. The old `kefu_name` parameter is kept as a deprecated backward-compat argument (ignored when `device_serial` is provided).

Callers updated:
- `create_sync_orchestrator()` / `create_customer_syncer()` in `services/sync/factory.py` — pass `device_serial=config.device_serial`.
- `ResponseDetector._init_media_event_bus()` — passes `device_serial=serial` directly (no longer resolves kefu_name first).

### Backend API

New router at `/api/device-profiles` (`routers/device_profiles.py`):

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | List all devices with override status (`DeviceActionProfileSummary[]`) |
| `/{device_serial}/actions` | GET | Get per-device action overrides |
| `/{device_serial}/actions/{action_type}` | PUT | Create/update override (upsert via `ON CONFLICT`). Broadcasts `device_action_profile_updated` WebSocket event. |
| `/{device_serial}/actions/{action_type}` | DELETE | Remove override (revert to global). Broadcasts `device_action_profile_deleted` WebSocket event. |
| `/{device_serial}/effective` | GET | Get fully resolved settings (calls `resolve_media_settings_by_device_from_db`). Uses `device_resolver` to merge global + per-device. |

Valid `action_type` values: `auto_group_invite`, `auto_contact_share`.

### Frontend

`MediaActionsView.vue` has a "按设备覆盖配置" section showing connected devices. Each device is a button with a green badge if configured; clicking opens an edit panel with group invite and contact share config fields.

- **Pinia store**: `wecom-desktop/src/stores/deviceProfiles.ts` (`useDeviceProfilesStore`) manages profile list, selected device actions, and effective settings.
- **API client types**: `DeviceActionProfileSummary`, `DeviceActionProfile`, `DeviceEffectiveSettings` (defined in `services/api.ts`).
- **WebSocket events**: `device_action_profile_updated`, `device_action_profile_deleted` broadcast via global WebSocket manager.

### Cleanup of Deprecated Per-Kefu Code

The following were removed or deprecated:

- `kefuProfiles.ts` store — **deleted**.
- `KefuActionProfileSummary`, `KefuActionProfile`, `EffectiveSettings` types — **removed** from `api.ts`.
- `kefu_overrides` field — **removed** from `settings_loader.py` defaults, `api.ts` `AutoContactShareSettings` interface, `media_actions.py` Pydantic model.
- `AutoContactShareAction._resolve_contact_name()` — **simplified**: removed legacy `kefu_overrides` fallback, now relies entirely on merged settings from `device_resolver`.
- Per-Kefu Overrides template section in `MediaActionsView.vue` — **replaced** with Per-Device Override section.

Kept for backward compatibility:
- `kefu_resolver.py` — still used by `kefu_profiles.py` router (legacy API remains registered).
- `kefu_profiles.py` router — still registered at `/api/kefu-profiles` for any external consumers.
- `kefu_action_profiles` table — not dropped; migration only copies data to `device_action_profiles`.

## Files Changed

| File | Change |
|------|--------|
| `src/wecom_automation/database/schema.py` | New `device_action_profiles` table + migration v16 |
| `src/wecom_automation/services/media_actions/device_resolver.py` | **New** — device settings merger |
| `src/wecom_automation/services/media_actions/factory.py` | `device_serial` parameter, deprecate `kefu_name` |
| `src/wecom_automation/services/media_actions/settings_loader.py` | Remove `kefu_overrides` from defaults |
| `src/wecom_automation/services/media_actions/actions/auto_contact_share.py` | Simplify `_resolve_contact_name()`, remove legacy fallback |
| `src/wecom_automation/services/sync/factory.py` | Pass `device_serial` to factory |
| `wecom-desktop/backend/services/followup/response_detector.py` | Pass `device_serial=serial` directly |
| `wecom-desktop/backend/routers/device_profiles.py` | **New** — REST API |
| `wecom-desktop/backend/routers/media_actions.py` | Remove `kefu_overrides` from Pydantic model |
| `wecom-desktop/backend/main.py` | Register device_profiles router |
| `wecom-desktop/backend/i18n/translations.py` | Add per-device override i18n keys |
| `wecom-desktop/src/stores/deviceProfiles.ts` | **New** — Pinia store |
| `wecom-desktop/src/stores/kefuProfiles.ts` | **Deleted** |
| `wecom-desktop/src/services/api.ts` | New device profile types + methods; remove kefu types |
| `wecom-desktop/src/views/MediaActionsView.vue` | Per-device config UI replaces per-kefu |
