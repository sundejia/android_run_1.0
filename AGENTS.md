<!-- OPENSPEC:START -->

# OpenSpec Instructions

These instructions are for AI assistants working in this project.

Always open `@/openspec/AGENTS.md` when the request:

- Mentions planning or proposals (words like proposal, spec, change, plan)
- Introduces new capabilities, breaking changes, architecture shifts, or big performance/security work
- Sounds ambiguous and you need the authoritative spec before coding

Use `@/openspec/AGENTS.md` to learn:

- How to create and apply change proposals
- Spec format and conventions
- Project structure and guidelines

Keep this managed block so 'openspec update' can refresh the instructions.

<!-- OPENSPEC:END -->

## Project Context (2026-05 onward): BOSS Zhipin Pivot

This repository is mid-pivot from a WeCom (企业微信) automation framework
to a BOSS 直聘 recruitment automation framework. Until M6 (see
`openspec/changes/0001-pivot-foundation/design.md`) the WeCom and BOSS
stacks coexist:

- New BOSS work goes under `src/boss_automation/` and
  `tests/unit/boss/`. WeCom code under `src/wecom_automation/` keeps
  shipping until each capability is replaced.
- BOSS-specific recruitment views go under
  `wecom-desktop/src/views/boss/` (created in M1).
- Two SQLite files coexist: `wecom_conversations.db` and
  `boss_recruitment.db`. Use `BOSS_DB_PATH` to override the BOSS path.
- Two env-var namespaces: `WECOM_*` (legacy) and `BOSS_*` (new). Never
  cross-read.
- TDD is mandatory for BOSS code. See `docs/00-boss-pivot/tdd-workflow.md`
  for the loop and `openspec/AGENTS.md` for the change-proposal format.
- Real-device interaction is forbidden in unit tests. Capture fixtures
  with `scripts/dump_boss_ui.py` and load them via
  `tests/_fixtures/loader.py`.

## Sidecar Guardrails

### Single Source Of Truth For Active Target

- Any Sidecar action that operates on the "current user" MUST resolve that user through one shared helper.
- If a feature supports both normal conversation state and queue/follow-up state, the resolver MUST prefer queued data when `currentQueuedMessage` exists.
- Do not duplicate target-resolution logic across template bindings, click handlers, status refreshes, and API payload builders.

### Keep UI State And Action Payloads Aligned

- `disabled`, `title`, visible label/icon, optimistic status text, and request payloads MUST all use the same active-target resolver.
- Do not gate Sidecar actions only on `state.conversation.*` when the action can also run from queued messages.
- If a button toggles backend state, the tooltip and fallback copy MUST describe the actual next action, not the current state.

### Regression Tests Required

- When fixing a Sidecar state bug, add a regression test for the exact stale-state shape that caused it.
- For block/allow flows, cover both paths: block triggers skip for the active queued user, allow does not.
- Protect backend toggle endpoints with route tests for both state transitions so frontend and backend cannot silently drift apart.

## Blacklist Identity Guardrails

### Use One Customer Identity Semantics Everywhere

- Blacklist state, whitelist filtering, block/allow toggles, status APIs, and management views MUST share the same customer identity rule.
- In this project, blacklist business identity is `device_serial + customer_name`. Do not let one code path switch back to `customer_name + customer_channel`.
- If runtime checks use name-only matching, sync filtering and reason lookup MUST use the same rule.

### Treat Channel As Metadata, Not State Key

- `customer_channel` is display and normalization metadata. It may be refreshed, normalized, or missing without changing who the customer is.
- Do not use channel differences to create new blacklist rows, new state transitions, or separate allow/block decisions for the same customer.
- When scanned data arrives with a different channel representation, update metadata in place instead of inserting a second logical customer state row.

### Prevent State Drift Across Duplicate Rows

- Any status update API that starts from a row `id` MUST still converge all rows for the same logical customer identity, not just the clicked row.
- If historical duplicate rows exist, service-layer updates must leave them with one consistent block/allow state.
- Do not rely on UI dedupe alone to fix blacklist consistency. The backend service layer must enforce identity semantics.

### Blacklist Regression Coverage Is Mandatory

- Any change to blacklist logic must add or update tests for channel representation differences such as `@WeChat` vs `＠WeChat` and `NULL` vs non-`NULL`.
- Any change to scanned-user upsert logic must test repeated scans for the same customer with different channel values.
- Any blacklist status endpoint that returns metadata like `reason` must have a regression test proving metadata still resolves when channel formatting differs.
- Any change that redefines blacklist identity semantics must also include a repair path for historical blacklist rows. Do not fix only new writes while leaving old databases in a drifted state.

## Database Migration Guardrails

### Version Numbers Are Not Schema Validation

- Never assume `schema_version` alone proves a live database is structurally complete.
- For any runtime-critical table, startup/migration code MUST verify required columns and repair missing ones idempotently.
- Fresh database creation SQL and migration repair logic MUST be kept in sync so new installs and upgraded installs converge to the same schema.

### Test Drift, Not Just Happy Paths

- Add a migration regression case where `schema_version` is already current but a required column is missing.
- Backfill assertions are required for newly added non-null business columns such as blacklist state flags.
- If runtime code reads a column directly, add at least one API or service test that exercises that code path against a drifted legacy database.

## Android Upload Integration Guardrails

### Backend URL And Token Must Be Treated As One Contract

- The Android log uploader targets the Data-Platform backend base URL, never the frontend page URL. Do not point upload config at port `5180`; uploads belong to the backend API base such as `http://host:8085`.
- `/api/android-logs/upload` is a token-protected endpoint. Any change to uploader settings, scripts, or docs must verify both sides of the contract together: Data-Platform `ANDROID_LOG_UPLOAD_TOKEN` and wecom-desktop `log_upload_token`.
- If an upload-related change touches the URL, request headers, or defaults, review `scripts/configure_log_upload.py`, the settings model, and the backend router in one pass so client and server cannot drift.

### Fail Early On Critical Config

- For any feature that depends on `.env` secrets or tokens, do not rely on a relative `env_file` that changes with the process working directory. Resolve config files from the project root or another stable absolute path.
- Do not leave critical upload config failures to be discovered only after a user clicks a button. Add startup validation or an explicit startup warning for missing required integration settings.
- When a backend route rejects requests because configuration is missing, add or update a regression test that locks the exact status code and error message.

### Regression Scope For Upload Changes

- Any change to Android upload behavior must test all three states: server token configured and correct, configured but wrong token, and server token missing.
- Do not ship upload fixes that only modify UI text or only modify the backend route. Upload regressions often come from configuration loading, not request handling alone.

## Person Identity Upload Rules

### Keep Identity Fields Strictly Separated

- `device_id` is the stable machine identity for dedupe, storage, and cross-machine traceability. Never replace it with a person label.
- `person_name` is the business identity shown to downstream monitoring and must be user-editable in settings.
- `hostname` remains machine/log-prefix metadata. Do not silently repurpose `hostname` as person identity.

### Update Producer Contract End To End

- Any new upload identity field must be added in one pass across:
  - settings defaults/model/service
  - settings API request/response mapping
  - desktop store and settings UI
  - log upload status payload
  - log upload HTTP client
- Do not add a settings field only in Vue or only in FastAPI. The desktop app loads from backend flat settings, so partial wiring creates silent drift.

### Effective Person Name Must Be Stable

- Blank `person_name` must resolve through one backend helper and fall back deterministically to the effective hostname.
- Do not duplicate person-name fallback logic in Vue components, upload services, and tests.
- If normalization rules change, update the shared settings service helper and the API tests together.

### Required Regression Coverage

- Any producer-side identity change must verify:
  - settings update persists the new field
  - blank input fallback behavior
  - upload request body contains `device_id`, `hostname`, and `person_name` together
- If upload status UI displays identity metadata, the backend status response must expose the same fields that the upload client sends.

## AI Circuit Breaker and Health Monitoring Guardrails

### Circuit Breaker State Must Be Checked Before Every AI Call

- Any code path that calls the AI reply service MUST first check `_ai_circuit_breaker.allow_request()`.
- If the breaker is OPEN, skip the AI call, log a structured `ai_circuit_open` error metric, and continue processing the next customer.
- After every AI call, record the outcome via `record_success()` or `record_failure()`. Never leave an AI call untracked.

### All AI Failure Paths Must Emit Structured Metrics

- Every `return None` inside `_generate_reply()` MUST be preceded by a `metrics.log_error()` call with a distinct error type.
- The error type taxonomy is: `ai_timeout`, `ai_connection_error`, `ai_http_error`, `ai_empty_reply`, `ai_human_transfer`. Do not add generic catch-all error types.
- When `_process_unread_user_with_wait` or `_interactive_wait_loop` receives `reply=None`, it MUST call `metrics.log_reply_sent(success=False)`.

### Heartbeat and Health Check Data Integrity

- The `heartbeat_service.ensure_tables()` call MUST happen before any heartbeat or health-check write. Both `main.py` startup and `realtime_reply_process.py` entry point call it.
- Health check results MUST include all three diagnostic layers (network, http_service, inference) even when an earlier layer fails (mark subsequent layers as "skipped").
- `PeriodicAIHealthChecker` MUST be stopped cleanly on process exit to avoid orphan asyncio tasks.

### Process Auto-Restart Safety

- Auto-restart is disabled when `stop_realtime_reply()` is called explicitly; do not restart a process the user intentionally stopped.
- Restart counter MUST reset after stable running (default 5 min). Do not accumulate restart counts across unrelated failure episodes.
- Maximum restart attempts (default 10) MUST be enforced. After exhaustion, the process stays stopped and the state is set to ERROR.
