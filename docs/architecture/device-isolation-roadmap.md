# Device Isolation Roadmap

## Target

Move from the current partially isolated architecture to a stronger isolation model where one device has minimal effect on another.

## Current State

- Device sync workers: isolated per subprocess
- Sync media outputs: isolated by default per device
- Conversation database: isolated per device for sync ingestion
- Read APIs: federated across discovered device DBs by default
- Settings / orchestration metadata: shared control DB
- ADB / host runtime: shared
- AI inference service: usually shared

## Phase 1

Keep the current unified product behavior while reducing obvious runtime collisions.

- Keep per-device subprocess isolation
- Keep per-device media output roots
- Surface warnings when devices share a DB
- Add repeatable three-device stress testing to release validation

## Phase 2

Introduce device-local persistence with a controlled aggregation layer.

- One DB per device for sync ingestion
- A read-side aggregation service for dashboards and history
- Federated query layer is now the default V1 implementation
- Per-device upload / retry telemetry

### Phase 2 Notes

- Device-local conversation DBs live under `device_storage/<serial>/wecom_conversations.db`
- The shared control DB remains responsible for settings and orchestration metadata
- Aggregated reads currently cover dashboard, customers, resources, and streamers
- The federated read contract is intentionally explicit so a future materialized/cache layer can sit behind the same service boundary

## Phase 3

Separate heavy shared dependencies.

- Per-device work queues
- AI request throttling or per-device concurrency budgets
- Dedicated worker pools for CPU-heavy media steps
- Optional ADB broker / command scheduler to smooth host-side bursts

## Phase 4

Pursue stronger fault-domain isolation.

- Independent worker process supervision
- Health-based circuit breaking per device
- Queue draining and restart semantics per device
- Optional external service boundaries for storage and inference

## Non-Negotiable Design Rules

- Do not silently share critical mutable state when claiming device isolation.
- Keep orchestration metadata separate from per-device execution state.
- If a resource remains shared, expose that fact through logs, metrics, and operator-facing docs.
- Prefer explicit aggregation over hidden coupling through one shared SQLite file.
