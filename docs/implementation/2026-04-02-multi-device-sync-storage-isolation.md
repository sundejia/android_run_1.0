# Multi-Device Sync Storage Isolation

## Summary

Phase 1 isolated sync media outputs per device. Phase 2 now completes the data-path split by moving sync conversation writes to per-device SQLite DBs while preserving a shared control DB for settings and orchestration metadata.

## What Changed

### Backend Sync Launch

- `DeviceManager` now resolves a per-device default output root:
  - `device_storage/<serial>/conversation_images`
  - `device_storage/<serial>/conversation_videos`
  - `device_storage/<serial>/conversation_voices`
- Those paths are passed explicitly into the sync subprocess instead of relying on a shared default media root.

### Sync Subprocess

- `initial_sync.py` now accepts and resolves:
  - `--output-root`
  - `--images-dir`
  - `--videos-dir`
  - `--voices-dir`
- Media directories stay internally consistent even when only an output root is supplied.

### Shared-DB Warning

- The backend still warns when multiple active devices are configured to use the same SQLite DB path.
- This is now a compatibility / operator-safety signal rather than the default architecture.

## What Did Not Change

- The shared control DB still defaults to `WECOM_DB_PATH` / project-root `wecom_conversations.db`.
- ADB, host CPU/memory/disk, backend orchestration, and shared AI endpoints can still create cross-device slowdowns.
- The system is therefore more strongly isolated than Phase 1, but not a fully separate fault domain for every dependency.

## Why This Matters

Before Phase 1, multiple sync processes could write media into the same default runtime directories. Before Phase 2, those devices still wrote conversation data into one shared SQLite DB.

After this change:

- device execution remains isolated by subprocess
- media output is isolated by default
- sync conversation writes are isolated by default per device
- remaining contention is easier to attribute to shared control-plane / ADB / AI / host resources

## Verification

- Added backend regression test: `wecom-desktop/backend/tests/test_device_storage_isolation.py`
- Verified new isolation tests pass
- Verified existing `sync` API concurrency-limit tests still pass

## Phase 2 Update

Phase 2 is now implemented on top of the Phase 1 runtime isolation work:

- Sync ingestion defaults to `device_storage/<serial>/wecom_conversations.db`
- Settings and orchestration metadata continue using the shared control DB path
- Backend startup now migrates the control DB explicitly and also migrates any discovered device DBs
- Dashboard, customers, resources, and streamers now support federated reads across discovered device DBs when `db_path` is not explicitly supplied
- Federated responses use source-aware numeric IDs so existing detail/delete/file endpoints can still resolve back to the correct device DB
- Realtime reply entrypoints now bind their conversation repository to the device-local DB instead of the legacy shared default

## Phase 2 Verification

- Updated `wecom-desktop/backend/tests/test_device_storage_isolation.py` for device-local DB defaults
- Added `wecom-desktop/backend/tests/test_federated_reads.py`
- Verified with `uv run pytest wecom-desktop/backend/tests/test_device_storage_isolation.py wecom-desktop/backend/tests/test_federated_reads.py`
