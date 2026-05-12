# Media auto-actions settings dedup — single source of truth (2026-05-12)

## Problem

Two independent places stored the **same** image-rating-server contract:

- **General** (`general.image_server_ip`, `general.image_review_timeout_seconds`, `general.image_upload_enabled`) — edited in **System Settings**, consumed by `image_review_client` on the realtime-reply path.
- **Media auto-actions** (`media_auto_actions.review_gate.rating_server_url`, `upload_timeout_seconds`, `upload_max_attempts`) — edited on **Media Auto-Actions**, consumed by `build_review_components` in `src/wecom_automation/services/review/runtime.py` for sync / review-gate submission.

If an operator filled only one side, the gate stayed off for the other path: logs such as `Skipping auto-contact-share: review data missing (reason=ai_review_status=None)` while uploads or other paths still looked healthy.

A second problem was **four** independent copies of default JSON for `media_auto_actions` (defaults registry, router, `settings_loader`, Vue fallback), which drifted whenever a field was added.

## Resolution (summary)

1. **SSOT for server URL and timeout** — Only `general.*` fields define the rating server and HTTP timeout. `review_gate` keeps **feature** toggles: `enabled`, `video_review_policy`.
2. **Python core owns the default schema** — `DEFAULT_MEDIA_AUTO_ACTION_SETTINGS` in `src/wecom_automation/services/media_actions/settings_loader.py` is imported by `wecom-desktop/backend/services/settings/defaults.py` and `wecom-desktop/backend/routers/media_actions.py` (deep copy where mutation is possible).
3. **Legacy reads stripped** — `load_media_auto_action_settings` drops `rating_server_url` / `upload_timeout_seconds` / `upload_max_attempts` from merged `review_gate` dicts so in-process consumers cannot diverge from `general`.
4. **Runtime wiring** — `build_review_components(..., settings_db_path=...)` loads `general` rows via `load_general_image_review_settings`. `create_sync_orchestrator` / `create_customer_syncer` pass `settings_db_path=str(get_default_db_path())`. Gate is disabled when `image_server_ip` is blank or `image_upload_enabled` is false (aligned with realtime behaviour).
5. **Idempotent migration** — `SettingsService.migrate_review_gate_url_to_general()` runs on service init: copies non-default legacy URL into empty `general.image_server_ip` (skips legacy default `http://127.0.0.1:8080`), copies tuned legacy timeout into default `image_review_timeout_seconds` when appropriate, always rewrites `review_gate` JSON without legacy keys. See `wecom-desktop/backend/tests/test_settings_review_url_migration.py`.
6. **UI** — Media Auto-Actions page removes URL/timeout/attempts inputs; copy points operators to **System Settings → 图片审核 / Image review**.

## Files touched (reference)

| Area | Path |
|------|------|
| Defaults + merge | `src/wecom_automation/services/media_actions/settings_loader.py` |
| Review client assembly | `src/wecom_automation/services/review/runtime.py` |
| Sync factory | `src/wecom_automation/services/sync/factory.py` |
| Settings definitions | `wecom-desktop/backend/services/settings/defaults.py` |
| Migration | `wecom-desktop/backend/services/settings/service.py` |
| API models | `wecom-desktop/backend/routers/media_actions.py` |
| Desktop UI + types | `wecom-desktop/src/views/MediaActionsView.vue`, `wecom-desktop/src/services/api.ts` |
| i18n | `wecom-desktop/backend/i18n/translations.py` |

## Tests

| Suite | Role |
|-------|------|
| `tests/unit/test_media_actions_settings_loader.py` | Legacy keys stripped; `load_general_image_review_settings` |
| `tests/unit/test_review_runtime.py` | URL from `general`; legacy `review_gate.rating_server_url` ignored |
| `wecom-desktop/backend/tests/test_settings_review_url_migration.py` | Migration idempotency and edge cases |
| `wecom-desktop/backend/tests/test_media_actions_api.py` | API response omits legacy fields; PUT ignores stale body keys |
| `wecom-desktop/src/views/MediaActionsView.spec.ts`, `mediaActions.spec.ts` | Frontend contract |

## Follow-up (not done here)

Optional consolidation of `/api/media-actions/settings` with the generic settings category API — kept as a thin typed shell for backward compatibility.

## Related docs

- [Media Auto-Actions feature](../features/media-auto-actions.md)
- [Auto contact share + review gate (2026-05-09)](./2026-05-09-contact-share-review-gate.md) — behaviour of `evaluate_gate_pass`; server URL wording updated 2026-05-12 to match SSOT.
- [Resolved: auto-blacklist review data missing](../04-bugs-and-fixes/resolved/2026-05-07-auto-blacklist-review-data-missing.md) — separate `require_review_pass` fix; dual-URL issue documented as related below in that file.
