# Low-Spec Performance Profile

## Purpose

Defines how runtime performance tiering works after the 2026-04-01 rollout.

The system now supports a settings-driven low-spec mode that prioritizes stability and throughput consistency on constrained hardware.

## Runtime Model

Resolved profile is exposed by:

- `GET /settings/performance/profile`

Response includes:
- `lowSpecMode`
- `effective` runtime values (after safety overrides)
- `metrics` snapshot (startup/memory/ADB/polling/sync/SQLite)

## Effective Value Rules

The following values are resolved in backend service logic (`SettingsService`):

- `maxConcurrentSyncDevices`
  - default from settings
  - forced to `1` when low-spec mode is on
- `sidecarPollInterval`
  - from settings
  - low-spec enforces a minimum polling interval (except explicit `0` disable)
- `scanInterval`
  - from settings
  - low-spec enforces a larger minimum interval
- `sidecarMaxPanels`
  - from settings
  - low-spec forces `1`
- mirror quality budget
  - lower effective FPS / bitrate under low-spec
- image review inline wait
  - disabled under low-spec (background async path)

## Frontend Integration

Settings UI now manages:
- `lowSpecMode`
- `maxConcurrentSyncDevices`
- `sidecarMaxPanels`

And displays resolved profile + metrics to avoid mismatch between configured values and effective runtime values.

Files:
- `wecom-desktop/src/views/SettingsView.vue`
- `wecom-desktop/src/stores/settings.ts`

## Polling and Backpressure Changes

Key improvements:
- sidecar send wait switched from busy polling to event-driven wakeups
- frontend timers reduced under low-spec and gated by page visibility
- device monitor polling uses adaptive backoff and low-spec-safe lower bound

## Why This Is Architecturally Correct

This design follows modern performance principles:
- do not default to full feature activation
- apply load-budgeted capability tiers
- enforce backpressure on expensive paths
- preserve fault isolation (per-device subprocess model)
