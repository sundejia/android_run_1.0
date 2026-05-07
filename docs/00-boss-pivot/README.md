# BOSS Zhipin Recruitment Automation - Pivot Documentation

This directory tracks the migration of this repository from a WeCom
(企业微信) automation framework to a BOSS 直聘 recruitment automation
framework. The migration is intentionally incremental: WeCom code keeps
shipping while the BOSS modules are built alongside it.

## Where things live (M0)

| Concern | Location |
|---------|----------|
| BOSS Python package | `src/boss_automation/` |
| BOSS schema | `src/boss_automation/database/schema.py` |
| BOSS configuration | `src/boss_automation/core/config.py` |
| BOSS unit tests | `tests/unit/boss/` |
| Real-device UI dump tool | `scripts/dump_boss_ui.py` |
| Fixture loader | `tests/_fixtures/loader.py` |
| Captured fixtures | `tests/fixtures/boss/<page>/<scenario>.{json,png}` |
| Theme overrides | `wecom-desktop/src/styles/boss-theme.css` |
| Tailwind palette | `boss.*` keys in `wecom-desktop/tailwind.config.js` |
| Change proposals | `openspec/changes/` |
| OpenSpec workflow | `openspec/AGENTS.md` |

## Roadmap

| Milestone | Theme | Status |
|-----------|-------|--------|
| M0 | Pivot foundation, OpenSpec, BOSS schema, dump tooling, CI | in progress |
| M1 | BOSS app launch + recruiter detection | pending |
| M2 | Job sync (open/closed jobs per recruiter) | pending |
| M3 | Candidate ("牛人") greeting executor + quota guard + schedule | pending |
| M4 | Inbound message reply + resume-driven template selection | pending |
| M5 | Re-engagement (复聊跟进) | pending |
| M6 | Ops hardening, scrcpy multi-window, monitoring panel | pending |

## TDD Discipline

Every commit in this pivot must satisfy:

1. A failing test exists before any production code is written.
2. `pytest tests/unit/boss/ --cov-fail-under=80` is green.
3. `ruff check` and `ruff format --check` are green for new code.
4. Real-device interaction is forbidden in unit tests. Use the dump
   tool to create JSON fixtures, then write tests that load them.
5. Integration tests (real device required) live under
   `tests/integration/` and carry `@pytest.mark.integration`. CI skips
   them; you run them locally.

## Capturing UI Fixtures

```bash
uv run scripts/dump_boss_ui.py \
    --serial <ADB-SERIAL> \
    --page candidate_card \
    --label first_time_greet
```

Outputs:
- `tests/fixtures/boss/candidate_card/first_time_greet.json`
- `tests/fixtures/boss/candidate_card/first_time_greet.png`

The script refuses to overwrite existing fixtures; pass `--force` to
intentionally replace one. Use `--dry-run` to see the planned output
paths without contacting the device.

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `BOSS_DEVICE_SERIAL` | ADB device serial for the active BOSS session | unset |
| `BOSS_USE_TCP` | Whether to use the DroidRun TCP bridge | `false` |
| `BOSS_DROIDRUN_PORT` | Per-device DroidRun port (multi-device must vary) | `8080` |
| `BOSS_DB_PATH` | Path to the BOSS SQLite file | `<project>/boss_recruitment.db` |
| `BOSS_OUTPUT_DIR` | Where sync media (resume screenshots, etc.) lands | `.` |
| `BOSS_DEBUG` | Enable verbose debug logs | `false` |
| `BOSS_LOG_FILE` | Optional file sink for logs | unset |
| `BOSS_TIMEZONE` | Timezone for parsed timestamps | `Asia/Shanghai` |

These never collide with the legacy `WECOM_*` variables, so both stacks
can run side by side on the same host.

## Coexistence With WeCom Code

Until M6, the WeCom package, desktop app, and tests stay in place. The
BOSS pivot is purely additive at the file system level. CI runs both
test suites: BOSS tests are blocking, legacy WeCom tests are
informational (`continue-on-error: true`) so a logfire/opentelemetry
mismatch in the legacy environment cannot block merges of new BOSS
work.

The two stacks share:
- The host ADB server and connected devices.
- The Python virtualenv.
- The Electron / Vite / Tailwind frontend infrastructure.

They do NOT share:
- SQLite files (`wecom_conversations.db` vs `boss_recruitment.db`).
- Environment variable namespace (`WECOM_*` vs `BOSS_*`).
- View directories (BOSS views will land under
  `wecom-desktop/src/views/boss/` in M1+).
