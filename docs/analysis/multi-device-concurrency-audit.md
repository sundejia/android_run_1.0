# Multi-Device Concurrency Audit

## Summary

The system now isolates the main sync execution path and the default conversation write target per device, but it still has shared-resource pressure points that can make one device slow down another under load.

## Confirmed Current-State Risks

- Sync processes are isolated per device, so Python GIL is not the main cross-device bottleneck.
- Default sync writes now go to `device_storage/<serial>/wecom_conversations.db`, so cross-device SQLite write contention only remains when operators explicitly point multiple devices at the same `db_path` or when the system is reading legacy shared data.
- The sync router limits concurrent devices and starts them with staggered delays, which is direct evidence that the system expects shared ADB/runtime contention.
- Before this hardening pass, media outputs also defaulted to shared runtime roots. Sync startup now isolates default media output roots under `device_storage/<serial>/`.

## What Was Hardened

- Default sync media outputs now resolve to per-device storage roots:
  - `device_storage/<serial>/conversation_images`
  - `device_storage/<serial>/conversation_videos`
  - `device_storage/<serial>/conversation_voices`
- Sync startup now passes explicit storage arguments to the sync subprocess so image/video/voice outputs stay aligned.
- When multiple active devices point at the same SQLite DB, the backend now emits an explicit warning to surface the remaining contention risk.

## Remaining Non-Isolated Components

- Shared control/settings DB
- Shared ADB server and USB/host resources
- Shared AI service endpoint when multiple devices point to the same inference backend
- Shared backend process for orchestration, status, and websockets

## Architectural Conclusion

The current system is now closer to:

- `device execution`: isolated
- `runtime media outputs`: isolated by default for sync
- `data plane`: isolated for sync ingestion, federated for default read APIs
- `host resource plane`: shared

That means three devices can now ingest independently by default, but strict no-impact latency guarantees are still not possible until host-side bottlenecks and other shared services are also partitioned or brokered.
