# 2026-04-01 Low-Spec Performance Rollout

## Summary

Implemented the low-spec performance plan end-to-end across backend, frontend, automation core, and tests.

This rollout focuses on:
- performance observability first
- runtime capability tiering (`lowSpecMode`)
- polling reduction and event-driven waits
- ADB hot-path consolidation
- async degradation for non-critical AI image review

## What Was Implemented

## 1) Baseline Metrics and Observability

- Added `src/wecom_automation/core/performance.py` with runtime metrics collector.
- Captures startup duration/memory, ADB call counts and timing, polling counters, sync run durations, SQLite slow query stats.
- Added instrumented SQLite connection/cursor in:
  - `src/wecom_automation/database/schema.py`
  - `wecom-desktop/backend/services/settings/repository.py`
- Backend startup now initializes metrics directory and records startup completion:
  - `wecom-desktop/backend/main.py`
- Exposed runtime snapshot via:
  - `GET /settings/performance/profile`

## 2) Low-Spec Mode and Capability Tiering

- Added new settings fields:
  - `general.low_spec_mode`
  - `sync.max_concurrent_devices`
  - `sidecar.max_panels`
- Wired settings through models/defaults/mappings and service helpers:
  - `wecom-desktop/backend/services/settings/models.py`
  - `wecom-desktop/backend/services/settings/defaults.py`
  - `wecom-desktop/backend/services/settings/service.py`
- Added resolved profile logic (effective values under low-spec mode) in `SettingsService`.
- Frontend settings store now supports:
  - `lowSpecMode`
  - `maxConcurrentSyncDevices`
  - `sidecarMaxPanels`
  - profile fetch API
  - file: `wecom-desktop/src/stores/settings.ts`

## 3) Polling Convergence

- Replaced high-frequency busy wait in sidecar `wait_for_send()` with event-driven wait + bounded timeout wakeups:
  - `wecom-desktop/backend/routers/sidecar.py`
- Added adaptive backoff in device monitor polling with low-spec safeguards:
  - `wecom-desktop/backend/services/device_monitor.py`
- Frontend polling now respects low-spec and page visibility:
  - `wecom-desktop/src/views/DeviceDetailView.vue`
  - `wecom-desktop/src/views/DeviceListView.vue`
  - `wecom-desktop/src/views/DashboardView.vue`
  - `wecom-desktop/src/views/RealtimeView.vue`
  - `wecom-desktop/src/stores/sidecarQueue.ts`
  - `wecom-desktop/src/views/SidecarView.vue`

## 4) ADB Hot-Path Optimizations

- Added ADB call instrumentation in `ADBService`:
  - `src/wecom_automation/services/adb_service.py`
- Replaced some `get_ui_tree()` hot points with `get_ui_state()` in:
  - `src/wecom_automation/services/wecom_service.py`
  - `wecom-desktop/backend/services/followup/response_detector.py`

## 5) AI/Image Review Cost Control

- In low-spec mode, image review upload now runs asynchronously and returns early (non-blocking for sync hot path):
  - `wecom-desktop/backend/services/image_review_client.py`

## 6) Concurrency Guardrails

- `/sync/start` now enforces runtime max concurrent sync slots based on resolved settings:
  - `wecom-desktop/backend/routers/sync.py`
- `DeviceManager` now exposes active sync count and records sync completion metrics:
  - `wecom-desktop/backend/services/device_manager.py`

## 7) UI and Docs Alignment

- Settings page now includes low-spec controls and runtime profile display:
  - `wecom-desktop/src/views/SettingsView.vue`
- Updated README claims from hardcoded “up to 3 panels” to settings-driven limits.

## Documentation Corrections

Corrected outdated/incomplete statements that implied fixed panel caps. The current behavior is:
- panel limits are settings-driven
- low-spec mode can force stricter effective caps (for example, sidecar panels -> 1)

## Validation and Tests

- Added/updated backend tests:
  - `wecom-desktop/backend/tests/test_sync_api.py` (new)
  - `wecom-desktop/backend/tests/test_settings_api.py`
  - `wecom-desktop/backend/tests/test_image_review_client.py`
- Verified targeted test suite passes.

## Notes and Boundaries Preserved

- Did not remove per-device process isolation.
- Did not treat protocol changes alone (for example, WebSocket) as performance fixes.
- Implemented resource budgeting and degradation instead of “all features on by default”.
