# Fix: AI Circuit Breaker Locked Open by Health Checker (BUG-2026-04-27)

> **Status**: Fixed
> **Date**: 2026-04-27 (report) / 2026-04-28 (fix)
> **Severity**: Major
> **Area**: `services/ai_health_checker.py`, regression coverage for `services/followup/circuit_breaker.py`
> **Tracking ID**: BUG-2026-04-27-circuit-breaker-skip-reply

## Problem

Three customers (B2604270395, B2604270410, B2604260278) did not receive AI auto-replies on 2026-04-27. The proximate cause was `AICircuitBreaker.allow_request()` returning `False`, so `response_detector.py` short-circuited the AI call and logged:

```
[10AF42051X00B1D]    AI circuit breaker OPEN — skipping AI call for B2604270395-(保底正常)
```

The breaker stayed effectively-open for hours, even though real `POST /chat` requests against `118.31.238.44:8000` continued to succeed in the same windows (HTTP 200 logged at 16:20, 16:37, 16:40, 17:08).

## Root Cause

`PeriodicAIHealthChecker._loop` called `circuit_breaker.force_open()` on **every** non-`healthy` probe result, including `inference_timeout` (probe's 10s budget exceeded but service still works for real customers). Because the health-check interval (300s) is wider than the breaker's recovery window (120s), the cycle was:

1. Probe → `inference_timeout` → `force_open()` → breaker `OPEN` for 120s.
2. Cooldown elapses → `HALF_OPEN` → real customer request succeeds → `CLOSED`.
3. Customer messages flow normally for ~180s.
4. Next probe (300s after step 1) → still degraded → `force_open()` again → back to step 1.

Result: a sustained "health-check lockup". Customers who happened to send messages inside the recurring 120s `OPEN` windows were silently skipped.

`AICircuitBreaker.force_open()` itself is correct — it already guards against re-resetting `_last_failure_time` while already `OPEN`. The bug lived entirely in the health checker's escalation policy.

## Fix

`PeriodicAIHealthChecker` now classifies probe statuses by severity and gates `force_open()` accordingly:

| Probe status        | Severity | Behaviour                                                      |
| ------------------- | -------- | -------------------------------------------------------------- |
| `healthy`           | ok       | Reset the consecutive-unhealthy counter                        |
| `unreachable`       | fatal    | `force_open()` immediately (network is dead)                   |
| `service_down`      | severe   | `force_open()` after **N** consecutive results (default `N=2`) |
| `inference_error`   | severe   | Same as `service_down`                                         |
| `inference_timeout` | warn     | Log only — never `force_open()`                                |
| _unknown_           | severe   | Treated as severe (fail-safe)                                  |

Additional safeguards:

- Once the health checker forces the breaker open for an outage, it does **not** keep re-firing `force_open()` on subsequent unhealthy probes during the same outage. The breaker's own 120s cooldown / `HALF_OPEN` probe handles recovery; the gate is reset only when a `healthy` probe is observed.
- New constructor kwarg `force_open_threshold: int = 2` (back-compat: existing callers in `realtime_reply_process.py` pick up the safer default automatically).
- The existing `AICircuitBreaker.force_open()` guard against resetting the cooldown timer when already `OPEN` is now covered by regression tests.

## Files Changed

- `wecom-desktop/backend/services/ai_health_checker.py`
  - Added `_STATUS_SEVERITY` map and `_handle_probe_result()` method.
  - `_loop()` now delegates breaker escalation to `_handle_probe_result()`.
  - New constructor kwarg `force_open_threshold` (default `2`).
- `tests/unit/test_circuit_breaker.py` (new) — 7 tests covering the natural state machine and the `force_open` regression case.
- `tests/unit/test_ai_health_checker.py` (new) — 11 tests covering severity classification, the consecutive-failure gate, recovery behaviour, and end-to-end loop wiring.

## TDD Trace

1. **RED**: Wrote 11 failing tests against the existing API expressing the desired severity policy. Failures: `TypeError: ... got an unexpected keyword argument 'force_open_threshold'` and `AttributeError: ... has no attribute '_handle_probe_result'`.
2. **GREEN**: Added `_handle_probe_result()` + severity map + threshold gate. All 18 tests pass; existing `tests/unit/test_response_detector.py` still passes.

## Verification

```bash
python -m pytest tests/unit/test_circuit_breaker.py tests/unit/test_ai_health_checker.py -v
# 18 passed
```

Field validation (after deploy):

- Re-create the original failure mode (slow `/chat` returning >10s but still 200): expected log line is `[AIHealthChecker] AI degraded (inference_timeout); not tripping circuit breaker (warn-only severity)`. Real customer replies must continue.
- Simulate a true outage (`/health` 5xx for ≥10 minutes): on the **second** consecutive `service_down` probe, expected log is `[AIHealthChecker] AI unhealthy (service_down) for 2 consecutive probes, circuit breaker forced open`. After `recovery_timeout`, breaker should naturally `HALF_OPEN` and recover on the first successful customer call.

## Out of Scope (deferred follow-ups from the bug report)

- Section 8.2.4 — Retry queue for messages skipped while breaker was `OPEN`.
- Section 8.2.5 — Restoring Redis on the AI server (operations).
- Operator-facing manual replay for B2604270395 / B2604270410 / B2604260278 (action item #4 in the bug report).
