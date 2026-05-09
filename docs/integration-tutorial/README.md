# Review-Gated Auto-Group-Invite — Integration Tutorial (Pointer)

The full step-by-step tutorial (with **7 full-page UI screenshots**, command
output logs, and an embedded LaTeX-rendered PDF copy) lives in the sibling
repository:

> **Canonical**:
> [`image-rating-server/docs/integration-tutorial/TUTORIAL.md`](https://github.com/sundejia/image-rating-server/blob/main/docs/integration-tutorial/TUTORIAL.md)
>
> PDF download:
> [`image-rating-server/docs/integration-tutorial/TUTORIAL.pdf`](https://github.com/sundejia/image-rating-server/blob/main/docs/integration-tutorial/TUTORIAL.pdf)

## What the tutorial covers

The tutorial walks through 13 steps and demonstrates the **review-gated
auto-group-invite pipeline** end-to-end:

1. Boot three independent processes (rating-server backend `:8080`, Next.js
   dashboard `:8081`, this android desktop backend `:8000`).
2. Register a webhook subscription via the dashboard so the rating-server
   knows where to push verdicts.
3. Trigger 3 synthetic verdicts (2 approved, 1 rejected) via
   `dispatcher.on_analysis_completed`.
4. Observe that the inbound webhook landed, `ReviewGate.on_verdict()`
   evaluated each, and `AutoGroupInviteAction` fired only for the two that
   passed the four-field gate (`decision=合格 ∧ is_portrait ∧
is_real_person ∧ face_visible`).
5. Inspect the resulting analytics events + JSONL traces export.

## Why this matters for `boss-automation`

This repository owns the **inbound** half of the contract:

| Module                                                  | Role                                                                 |
| ------------------------------------------------------- | -------------------------------------------------------------------- |
| `wecom-desktop/backend/routers/webhooks.py`             | HTTP entry point for `/api/webhooks/image-review`                    |
| `wecom-desktop/backend/services/webhook_receiver.py`    | HMAC verification, idempotency, verdict persistence                  |
| `wecom-desktop/backend/services/review_gate_runtime.py` | Process-singleton wiring of `ReviewGate` + `MediaEventBus` + actions |
| `src/wecom_automation/services/review/gate.py`          | Bridges verdict → policy → governance → bus                          |
| `src/wecom_automation/services/review/policy.py`        | `PolicyEvaluator` that dispatches to versioned skills                |
| `src/wecom_automation/skills/approval_policy/v1.py`     | The four-field gate decision                                         |
| `src/wecom_automation/services/governance/guard.py`     | `ExecutionPolicyGuard` (kill-switch + rate limit + audit)            |
| `src/wecom_automation/services/lifecycle/startup.py`    | `LifecycleService` (startup self-healing)                            |
| `src/wecom_automation/services/analytics/service.py`    | `AnalyticsService` facade for centralised telemetry                  |

## Reproducing the demo locally

The tutorial includes a small launcher you can run in this repo:

```powershell
$env:PYTHONPATH = "src"
python demo_run\start_android_demo.py
```

That binds the inbound webhook router on `127.0.0.1:8000` and pre-seeds a few
`pending_reviews` rows so the rating-server's outbound dispatch has somewhere
to land. Step-by-step instructions and screenshots are in the canonical
tutorial linked above.

## Tests covering this surface

| Suite                                           | What it asserts                                                                                                                 |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `tests/integration/test_cross_process_e2e.py`   | End-to-end **across a real uvicorn subprocess** with HMAC-signed HTTP — covers approve / reject / replay / bad-signature paths. |
| `tests/integration/test_review_pipeline_e2e.py` | In-process composition test for the gate / policy / governance chain.                                                           |
| `tests/unit/test_review_gate.py`                | `ReviewGate.on_verdict()` policy + governance interaction.                                                                      |
| `tests/unit/test_processor_review_gate.py`      | `MessageProcessor` rewiring (image → review submitter, video → policy).                                                         |
| `tests/unit/test_governance_guard.py`           | Kill-switch + rate-limit + audit eventing.                                                                                      |
| `tests/unit/test_lifecycle.py`                  | Startup recovery, idempotency GC, orphan-image quarantine.                                                                      |
| `tests/unit/test_analytics_service.py`          | Centralised analytics facade.                                                                                                   |
| `wecom-desktop/backend/tests/test_webhook_*.py` | Inbound HTTP layer + drives-gate background task.                                                                               |
