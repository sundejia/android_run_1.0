# System Robustness Fixes — 2026-04-09

> Based on the [daily operations monitoring report](../../daily-operations-monitoring-plan.md)
> analysing 2026-04-02 ~ 2026-04-06 logs across three devices.

---

## Problem Summary

Five days of production logs revealed critical gaps:

| #   | Problem                                                          | Severity | Impact                                                               |
| --- | ---------------------------------------------------------------- | -------- | -------------------------------------------------------------------- |
| 1   | AI server down → system retries same customer 54× in 30 min      | P0       | Customer sees read-status flickering, no reply                       |
| 2   | `reply=None` silently skipped — no metrics recorded              | P0       | All AI failures invisible to dashboards                              |
| 3   | `last_customer_msg_db_id` never assigned (code bug)              | P1       | AI replies cannot be linked back to the originating customer message |
| 4   | Click-into-chat failures retry every scan cycle without cooldown | P1       | ~20 wasted click attempts per day per device                         |
| 5   | `_interactive_wait_loop` replies have zero metrics               | P2       | Follow-up round replies are invisible                                |
| 6   | Process exit → 19.5 h downtime, no auto-restart                  | P0       | 4/5–4/6 full outage                                                  |
| 7   | AI health only tested on-demand (when replying)                  | P1       | Failures go unnoticed until a customer message arrives               |
| 8   | Sidecar timeout hardcoded at 300 s                               | P2       | Every nighttime reply delayed 5 min                                  |

---

## Changes Made

### Phase 1 — Urgent Code Fixes

#### 1. AI Circuit Breaker (`circuit_breaker.py` — new file)

**File:** `wecom-desktop/backend/services/followup/circuit_breaker.py`

State machine: `CLOSED → OPEN (3 consecutive failures) → HALF_OPEN (120 s cooldown) → CLOSED / OPEN`

Integrated at two call-sites inside `ResponseDetector`:

- `_process_unread_user_with_wait()` — before `_generate_reply()`
- `_interactive_wait_loop()` — before `_generate_reply()`

When OPEN, AI call is skipped; messages are still stored to DB; a structured `ai_circuit_open` error metric is logged.

#### 2. AI Failure Metrics

**File:** `wecom-desktop/backend/services/followup/response_detector.py`

- Added `else` branch after `if reply:` in `_process_unread_user_with_wait()` — calls `metrics.log_reply_sent(success=False)` and `metrics.log_error("ai_no_reply")`.
- Enhanced `_generate_reply()` with per-failure-type metrics at every `return None` path:
  - `ai_human_transfer` — customer requested human agent
  - `ai_empty_reply` — model returned empty string
  - `ai_http_error` — non-200 HTTP status
  - `ai_timeout` — request timed out
  - `ai_connection_error` — network/exception errors

#### 3. `last_customer_msg_db_id` Bug Fix

**File:** `wecom-desktop/backend/services/followup/response_detector.py`

The `for` loop that found the last customer message only did `break` without assigning the DB ID. Fixed to walk `messages` and `message_db_ids` in parallel from the end.

#### 4. Click Failure Cooldown

**File:** `wecom-desktop/backend/services/followup/response_detector.py`

- New `_click_fail_cooldown` dict and `_clean_expired_click_cooldowns()` method.
- Progressive backoff: 1st fail → 120 s, 2nd → 300 s, 3rd+ → 600 s.
- Cooldown cleared on successful click; expired entries pruned each scan.

#### 5. Interactive Wait Loop Metrics

**File:** `wecom-desktop/backend/services/followup/response_detector.py`

Added `loop_metrics.log_reply_sent()` / `record_ai_reply_generated()` / `log_error()` to the success, send-failure, and reply-None branches of `_interactive_wait_loop`.

---

### Phase 2 — Monitoring Infrastructure

#### 6. Process Auto-Restart

**File:** `wecom-desktop/backend/services/realtime_reply_manager.py`

- New `_attempt_restart()` with exponential backoff (5 s → 15 s → 45 s → … → 300 s max, 10 attempts max).
- Restart counter resets after 5 min of stable running.
- Disabled on explicit `stop_realtime_reply()`.
- Also fixed `stop_all()` which was calling the non-existent `stop_followup()`.

#### 7. Heartbeat Service

**New files:**

- `wecom-desktop/backend/services/heartbeat_service.py` — SQLite tables (`heartbeats`, `ai_health_checks`, `process_events`), read/write helpers.
- `wecom-desktop/backend/routers/monitoring.py` — API endpoints:
  - `GET /api/monitoring/heartbeats` — recent heartbeats by device
  - `GET /api/monitoring/heartbeats/latest` — most recent per device (status cards)
  - `GET /api/monitoring/ai-health` — recent AI health check results
  - `GET /api/monitoring/process-events` — process start/stop/crash events

**Integration:**

- `realtime_reply_process.py` writes a heartbeat every scan and lifecycle events on start/stop.
- `main.py` registers the monitoring router and creates tables at startup.

#### 8. AI Health Check

**New file:** `wecom-desktop/backend/services/ai_health_checker.py`

Three-layer probe every 5 minutes:

1. **TCP** — is the host reachable?
2. **HTTP** — does `/health` respond?
3. **Inference** — does `POST /chat` with a minimal prompt return 200?

Results stored in `ai_health_checks` table. If unhealthy, the circuit breaker is force-opened.

#### 9. Sidecar Night-Mode Timeout

**Files:**

- `wecom-desktop/backend/services/settings/defaults.py` — four new settings: `sidecar_timeout` (300), `night_mode_sidecar_timeout` (30), `night_mode_start_hour` (22), `night_mode_end_hour` (8).
- `wecom-desktop/backend/services/followup/response_detector.py` — new `_get_sidecar_timeout()` method selects 30 s during 22:00–08:00, 300 s otherwise. Replaces hardcoded `timeout=300.0` in `_send_reply_wrapper`.

---

## Files Changed

| File                                                           | Type     |
| -------------------------------------------------------------- | -------- |
| `wecom-desktop/backend/services/followup/circuit_breaker.py`   | **New**  |
| `wecom-desktop/backend/services/heartbeat_service.py`          | **New**  |
| `wecom-desktop/backend/services/ai_health_checker.py`          | **New**  |
| `wecom-desktop/backend/routers/monitoring.py`                  | **New**  |
| `wecom-desktop/backend/services/followup/response_detector.py` | Modified |
| `wecom-desktop/backend/services/realtime_reply_manager.py`     | Modified |
| `wecom-desktop/backend/scripts/realtime_reply_process.py`      | Modified |
| `wecom-desktop/backend/main.py`                                | Modified |
| `wecom-desktop/backend/services/settings/defaults.py`          | Modified |

## Test Validation

All 511 existing unit tests pass (`tests/unit/`). No test changes required — the new code is additive and behind existing interfaces.
