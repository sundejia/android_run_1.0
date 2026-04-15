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
| 8   | Sidecar daytime timeout default was 300 s                        | P2       | Long idle waits when no operator at Sidecar UI                       |

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

- `wecom-desktop/backend/services/settings/defaults.py` — four new settings: `sidecar_timeout` (**60** as of 2026-04-15; was 300 at first ship), `night_mode_sidecar_timeout` (30), `night_mode_start_hour` (22), `night_mode_end_hour` (8).
- `wecom-desktop/backend/services/followup/response_detector.py` — new `_get_sidecar_timeout()` method selects 30 s during 22:00–08:00, **daytime `sidecar_timeout` otherwise** (fallback **60** s). Replaces hardcoded `timeout=300.0` in `_send_reply_wrapper`.

---

### Follow-up fix (2026-04-10) — `SidecarSettings` dataclass vs database keys

**Symptom (production logs):**

- `SidecarSettings.__init__() got an unexpected keyword argument 'sidecar_timeout'`
- `cannot access local variable 'ai_server_url' where it is not associated with a value`

**Cause:**

- Phase 2 added four SIDECAR keys in `defaults.py` (`sidecar_timeout`, `night_mode_sidecar_timeout`, `night_mode_start_hour`, `night_mode_end_hour`).
- `SettingsService.get_sidecar_settings()` builds `SidecarSettings(**data)` from the full category dict. The `SidecarSettings` dataclass originally only listed five fields, so the extra keys broke construction whenever `get_all_settings()` / `get_flat_settings()` ran (for example from `load_settings()` during AI reply generation in `response_detector.py`).
- The generic `except` around the AI request block logged `ai_server_url` even when the failure happened before that variable was assigned, which raised a secondary `UnboundLocalError`.

**Fix:**

- `wecom-desktop/backend/services/settings/models.py` — add the four missing fields to `SidecarSettings` with defaults matching `defaults.py`.
- `wecom-desktop/backend/services/followup/response_detector.py` — set a default `ai_server_url` immediately before the `try` that loads settings and calls the AI, so error logging and metrics always have a defined value.

**Regression test:** `tests/unit/test_sidecar_settings_models.py` — ensures `SidecarSettings(**data)` accepts the full SIDECAR category shape.

### Repo tooling (2026-04-10) — pre-commit, lint-staged, pre-push

- **`lint-staged.config.mjs`** (package root) — single lint-staged configuration: Prettier for `docs/**/*.md`, Ruff (via `uv run --extra dev`) for `wecom-desktop/backend/**/*.py` and `tests/**/*.py`, ESLint/Prettier for `wecom-desktop/src/**/*.{ts,tsx,vue,js}`. Resolves paths whether Git reports them from the monorepo root or as absolute Windows paths. Avoid `*/` inside block comments in `.mjs` files (it terminates the comment).
- **`wecom-desktop/package.json`** — removed duplicate `lint-staged` key so nested config does not steal staged files from the root config.
- **`.husky/pre-commit`** — runs `npx lint-staged` from `android_run_test-main/` when the repo root is one level up; skips `android_run_test-main/docs/*` in the secret scan; documents path layout.
- **`.husky/pre-push`** — dropped invalid `--no-cov` pytest flag when `pytest-cov` is not installed.

---

## Files Changed

| File                                                           | Type                                  |
| -------------------------------------------------------------- | ------------------------------------- |
| `wecom-desktop/backend/services/followup/circuit_breaker.py`   | **New**                               |
| `wecom-desktop/backend/services/heartbeat_service.py`          | **New**                               |
| `wecom-desktop/backend/services/ai_health_checker.py`          | **New**                               |
| `wecom-desktop/backend/routers/monitoring.py`                  | **New**                               |
| `wecom-desktop/backend/services/followup/response_detector.py` | Modified                              |
| `wecom-desktop/backend/services/realtime_reply_manager.py`     | Modified                              |
| `wecom-desktop/backend/scripts/realtime_reply_process.py`      | Modified                              |
| `wecom-desktop/backend/main.py`                                | Modified                              |
| `wecom-desktop/backend/services/settings/defaults.py`          | Modified                              |
| `wecom-desktop/backend/services/settings/models.py`            | Modified (2026-04-10 follow-up)       |
| `tests/unit/test_sidecar_settings_models.py`                   | **New** (2026-04-10 follow-up)        |
| `lint-staged.config.mjs`                                       | **New** (2026-04-10 tooling)          |
| `wecom-desktop/package.json`                                   | Modified (nested lint-staged removed) |
| `.husky/pre-commit` / `.husky/pre-push`                        | Modified (2026-04-10 tooling)         |

## Test Validation

Run `pytest tests/unit/ -v --tb=short` from the `android_run_test-main` package directory (see `.husky/pre-push`). After the 2026-04-10 follow-up, a dedicated test covers `SidecarSettings` construction with all SIDECAR keys; the full unit suite must pass before push.

---

## Update (2026-04-15) — Daytime Sidecar default 300 s → 60 s

The seeded default and code fallbacks for **`sidecar_timeout`** were lowered from **300** to **60** seconds so unattended queues fail faster. Night mode defaults are unchanged. Full file list and rationale: [Sidecar review timeout defaults](../sidecar/sidecar-review-timeout-defaults.md).
