# BOSS Zhipin Recruitment Automation - Pivot Documentation

This directory tracks the migration of this repository from a WeCom
(企业微信) automation framework to a BOSS 直聘 recruitment automation
framework. The migration is **incremental**: WeCom code remains in the
tree; BOSS modules ship alongside it.

## Status (2026-05)

**Milestones M0–M6 are complete.** The recruitment loop (recruiter → jobs →
greet → reply → re-engage) plus ops monitoring and smoke regression is
implemented and covered by tests.

Runtime E2E smoke on the May-2026 BOSS app is green for the two user-visible
send paths after the parser/runtime compatibility fixes:

- Candidate feed → card open → `立即沟通` returned `sent` on device
  `10AE9P1DTT002LE`.
- Message list → unread selection → reply generation returned `dry_run_ready`
  for an unread conversation; no message was sent in dry-run mode.

Post-M6 landing: `BossNavigator` brings tab-aware page navigation (BACK-retry
loop, pre/post action navigation) into production code so all executors and
dispatchers can drive the device end-to-end without the test script shim.
292 BOSS unit tests pass (including 11 navigator tests).

High-level completion summary: **`docs/implementation/2026-05-07-boss-pivot-m0-m6-complete.md`**.
Latest live-device runtime report: **`docs/implementation/2026-05-09-boss-e2e-live-test-report.md`**.

## Where things live

| Concern | Location |
|---------|----------|
| BOSS Python package | `src/boss_automation/` |
| BOSS schema | `src/boss_automation/database/schema.py` |
| BOSS configuration | `src/boss_automation/core/config.py` |
| BOSS unit tests | `tests/unit/boss/` |
| BOSS backend API tests | `wecom-desktop/backend/tests/test_boss_*.py` |
| Real-device UI dump tool | `scripts/dump_boss_ui.py` |
| Fixture loader | `tests/_fixtures/loader.py` |
| Captured fixtures | `tests/fixtures/boss/<page>/<scenario>.{json,png}` |
| Smoke regression script | `scripts/boss_smoke.py` |
| BOSS live E2E script | `scripts/boss_e2e_live.py` |
| BOSS page navigation | `src/boss_automation/services/boss_navigator.py` |
| Theme overrides | `wecom-desktop/src/styles/boss-theme.css` |
| BOSS Vue views | `wecom-desktop/src/views/boss/` |
| Tailwind palette | `boss.*` keys in `wecom-desktop/tailwind.config.js` |
| Change proposals | `openspec/changes/` |
| OpenSpec workflow | `openspec/AGENTS.md` |

## Roadmap (completed)

| Milestone | Theme | Status |
|-----------|-------|--------|
| M0 | Pivot foundation, OpenSpec, BOSS schema, dump tooling, CI | **Done** |
| M1 | BOSS app launch + recruiter detection + API/list UI | **Done** |
| M2 | Job sync (open/closed jobs per recruiter) | **Done** |
| M3 | Candidate ("牛人") greeting executor + quota guard + schedule | **Done** |
| M4 | Inbound message reply + resume-driven templates + dispatcher | **Done** |
| M5 | Re-engagement (复聊跟进) | **Done** |
| M6 | Ops hardening: monitoring summary API, smoke script, dashboard, docs | **Done** |

**Follow-ups (not part of M0–M6):** scrcpy multi-window automation,
background schedulers for greet/re-engage, optional packaging hardening.
See `openspec/changes/0007-ops-hardening/design.md`.

## Operator and developer docs

| Audience | Document |
|----------|----------|
| First-time setup / endpoints | `docs/guides/boss-zhipin-onboarding.md` |
| TDD workflow (short checklist) | `docs/development/boss-tdd-workflow.md` |
| Detailed TDD loop (fixtures, loader) | `docs/00-boss-pivot/tdd-workflow.md` |

## TDD Discipline

Every BOSS change should satisfy:

1. A failing test exists before production code (red → green).
2. `pytest tests/unit/boss/ --cov-fail-under=80` is green for BOSS modules
   (CI enforces coverage on `src/boss_automation`).
3. `ruff check` and `ruff format --check` are green for touched Python.
4. Real-device interaction is forbidden in unit tests. Capture fixtures with
   `dump_boss_ui.py` or commit **curated synthetic JSON** under
   `tests/fixtures/boss/` when the contract is stable; document the intent
   in the owning test file.
5. Integration tests (real device) live under `tests/integration/` with
   `@pytest.mark.integration`. CI skips them unless explicitly enabled.

## Capturing UI Fixtures

```bash
uv run scripts/dump_boss_ui.py \
    --serial <ADB-SERIAL> \
    --page me_profile \
    --label has_profile
```

Outputs under `tests/fixtures/boss/` (see `--fixture-root` in the script).

The script refuses to overwrite existing fixtures unless `--force` is set.
Use `--dry-run` to see planned paths without touching the device.

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `BOSS_FEATURES_ENABLED` | When truthy, mounts `boss_*` FastAPI routers | unset (routers off) |
| `BOSS_DEVICE_SERIAL` | ADB device serial for CLI / scripts | unset |
| `BOSS_USE_TCP` | Whether to use the DroidRun TCP bridge | `false` |
| `BOSS_DROIDRUN_PORT` | Per-device DroidRun port (multi-device must vary) | `8080` |
| `BOSS_DB_PATH` | Path to the BOSS SQLite file | `<project>/boss_recruitment.db` |
| `BOSS_OUTPUT_DIR` | Where sync media (resume screenshots, etc.) lands | `.` |
| `BOSS_DEBUG` | Enable verbose debug logs | `false` |
| `BOSS_LOG_FILE` | Optional file sink for logs | unset |
| `BOSS_TIMEZONE` | Timezone for parsed timestamps | `Asia/Shanghai` |

These never collide with the legacy `WECOM_*` variables.

## Coexistence With WeCom Code

The BOSS pivot is additive at the filesystem level. CI runs both suites:
BOSS unit tests are blocking where configured; some legacy WeCom tests may
run as informational depending on workflow (`continue-on-error`) so
environment-specific issues (e.g. optional deps) do not block BOSS merges.

The two stacks share:

- The host ADB server and connected devices.
- The Python virtualenv (recommended: `uv`).
- The Electron / Vite / Tailwind frontend infrastructure.

They do **not** share:

- SQLite files (`wecom_conversations.db` vs `boss_recruitment.db`).
- Environment variable namespace (`WECOM_*` vs `BOSS_*`).
- Feature directories (BOSS UI under `wecom-desktop/src/views/boss/`).
