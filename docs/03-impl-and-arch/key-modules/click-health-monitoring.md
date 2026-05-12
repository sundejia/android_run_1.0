# Click Health Monitoring

## What it tracks

`ResponseDetector` exposes a per-scan snapshot of the click subsystem so the
2026-05-09 priority-queue death-loop (a single customer stuck in
priority → click-fail → cooldown → priority again for 5.5 h) is observable in
near real-time rather than only via post-mortem log forensics.

**Snapshot fields** (returned by `ResponseDetector.get_click_health_snapshot()`):

| Field | Meaning |
|---|---|
| `dayblock_day` | Local calendar day the dayblock state belongs to. Rolls over at midnight. |
| `dayblock_size` | How many `(serial, customer_name)` pairs have hit the per-day click-failure threshold (default 5) and are now suppressed from priority detection for the rest of the day. |
| `dayblock_keys` | Sorted list of those keys. The actual customer names are included on purpose — they are the same names the operator already sees in the device log/UI. |
| `active_cooldown_count` | How many `(serial, customer_name)` pairs currently have an unexpired click cooldown (< dayblock threshold). |
| `active_cooldowns` | Details: `[{key, fail_count, retry_in_seconds}]`. |
| `unique_customers_clicked` | Distinct customers that successfully clicked at least once today (resets at day rollover). |
| `priority_queue_repeats` | Times today that a customer with an existing cooldown was sighted again at priority-detection time — the canonical "queue running in circles" signal. |

## How samples flow into the dashboard

```
ResponseDetector
   │  per scan
   ▼
realtime_reply_process.py — record_click_health(...)
   │
   ▼
monitoring.db / click_health table
   ▲
   │
GET /api/monitoring/click-health{/latest, ?device_serial=…}
   │
   ▼
frontend monitoring dashboard
```

## Endpoints

- `GET /api/monitoring/click-health/latest` — newest sample per device; cards.
- `GET /api/monitoring/click-health?device_serial=XYZ&limit=200` — time series
  for one device; charts.

JSON columns (`dayblock_keys`, `active_cooldowns`) are decoded server-side, so
the frontend can render them directly.

## Suggested alert thresholds

These are starting points, not contractual SLAs — tune per fleet.

| Signal | Threshold | Rationale |
|---|---|---|
| `dayblock_size > 0` for ≥ 3 consecutive scans | warn | Any non-empty dayblock means a customer hit the click-failure ceiling today. Names are in `dayblock_keys`. |
| `dayblock_size ≥ 5` | page | Five distinct customers blocked in one day is unusual unless the device has a UI-layer issue (resolution change, locale change, WeCom update). |
| `active_cooldown_count > 3` for ≥ 5 minutes | warn | Several customers are stuck in the 120-600 s backoff ramp. |
| `priority_queue_repeats` rising while `unique_customers_clicked` flat | page | Queue is running in circles — exactly the 2026-05-09 failure mode. |
| `priority_queue_repeats / max(1, unique_customers_clicked) > 3` | warn | Steady-state ratio. Devices doing useful work should be < 1. |

## Where to look next

- Root-cause document for the 2026-05-09 outage (resolved):
  [`docs/04-bugs-and-fixes/resolved/2026-05-12-new-friend-false-positive-click-loop.md`](../../04-bugs-and-fixes/resolved/2026-05-12-new-friend-false-positive-click-loop.md)
- Implementation:
  - `wecom-desktop/backend/services/followup/response_detector.py` (snapshot + counters)
  - `wecom-desktop/backend/services/heartbeat_service.py` (persistence)
  - `wecom-desktop/backend/routers/monitoring.py` (REST surface)
  - `wecom-desktop/backend/scripts/realtime_reply_process.py` (per-scan write)
- Tests:
  - `wecom-desktop/backend/tests/test_response_detector_click_dayblock.py`
  - `wecom-desktop/backend/tests/test_monitoring_click_health.py`
