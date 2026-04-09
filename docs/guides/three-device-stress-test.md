# Three-Device Stress Test Guide

## Goal

Validate whether three devices can run at the same time without causing unacceptable slowdown, queueing, or pauses for one another.

## Test Matrix

Run all tests with three real devices connected at the same time.

1. Baseline single-device sync
2. Three-device sync without AI reply
3. Three-device sync with AI reply enabled
4. Three-device sync plus realtime reply enabled on at least one device
5. Three-device sync in low-spec mode

## Metrics To Capture

- Per-device sync start time
- Per-device completion time
- Device-local DB path used by each sync worker
- SQLite lock warnings and retry count when explicitly testing a shared-DB compatibility scenario
- ADB command latency by device
- AI request latency: P50, P95, P99
- Host CPU usage
- Host memory usage
- Disk queue / disk active time
- Any unexpected backend warnings about shared DB usage

## Validation Steps

1. Start backend and confirm three devices are online.
2. Clear or archive old logs for a clean run.
3. Run the baseline single-device sync and record total duration.
4. Run three-device sync with the same workload size.
5. Confirm each device is writing to its own `device_storage/<serial>/wecom_conversations.db`.
6. Compare each device against the baseline:
   - total sync duration
   - time-to-first-customer
   - time spent waiting on DB / retries
7. Repeat with AI reply enabled.
8. Repeat with low-spec mode enabled to verify that concurrency limiting behaves as expected.
9. Optionally run a separate shared-DB compatibility scenario by explicitly forcing the same `db_path` across devices and validating warnings/retry behavior.

## Pass / Fail Heuristics

- Pass:
  - no device enters an unexplained paused state
  - no device starves indefinitely
  - duration increase is bounded and explainable by host load
- Investigate:
  - repeated SQLite lock warnings during the default per-device DB scenario
  - one device consistently lagging while CPU is low
  - AI latency spikes that correlate across all three devices
- Fail:
  - device-level deadlock
  - persistent ADB stalls
  - one device blocks others from making forward progress

## Recommended Evidence Collection

- Backend logs
- Per-device sync logs
- Windows Task Manager performance screenshots
- AI service logs if AI reply is enabled
- A short table comparing single-device and three-device timing
