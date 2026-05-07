# 0001 - Pivot Foundation: BOSS Zhipin Automation

## Why

The repository currently delivers a WeCom (企业微信) Android automation
framework with a mature multi-device backend and Electron desktop app. The
product direction is now to control the BOSS 直聘 recruiter app for
job-posting sync, candidate ("牛人") greetings, AI-assisted replies, and
re-engagement outreach.

We need a clean foundation that:
- Keeps the proven generic infrastructure (DroidRun ADB layer, multi-device
  subprocess orchestration, WebSocket logs, settings center, scrcpy mirror,
  CI scaffolding) reusable.
- Quarantines all WeCom-specific business code so it cannot be accidentally
  imported by the new BOSS modules.
- Establishes an independent BOSS data model and package namespace.
- Hard-wires strict TDD with fixture-driven UI parsing as the discipline
  for every milestone after this one.

## What

This change ships the M0 "scaffolding" deliverables that unblock M1+:

- A new Python package `src/boss_automation/` with empty but runnable
  subpackages (`core`, `database`, `services`, `parsers`).
- A new SQLite schema for BOSS recruitment data (recruiters, jobs,
  candidates, conversations, messages, greeting_templates,
  followup_attempts_v2, job_sync_checkpoints) with idempotent migrations.
- A real-device UI dump tool at `scripts/dump_boss_ui.py` that produces
  reusable fixtures under `tests/fixtures/boss/<page>/<scenario>.json`.
- A fixture loader at `tests/_fixtures/loader.py` for unit tests.
- The first TDD-driven test suite covering the BOSS schema initialization
  and dump-fixture loading contracts.
- An OpenSpec workspace (`openspec/AGENTS.md`, `specs/`, `changes/`).
- CI workflow at `.github/workflows/ci.yml` running ruff, pytest (with
  coverage gate), and vitest.
- Tailwind theme overrides on the desktop app for a recruitment-grade
  visual identity.
- Documentation refresh in `AGENTS.md`, `CLAUDE.md`, `.cursorrules`.

## Out Of Scope

- Renaming `src/wecom_automation/` or `wecom-desktop/` directories. These
  remain in place until the BOSS surface is functionally complete; further
  rename is deferred to the M6 ops-hardening change.
- Implementing any BOSS-specific UI parsing (M1).
- Implementing job sync, greet, reply, or re-engagement workflows
  (M2-M5).
- Deleting WeCom code. This change archives where helpful but never
  destroys; full archival happens incrementally as BOSS replaces each
  capability.

## Success Criteria

- `pytest tests/` is green, including ≥ 5 new tests for BOSS scaffolding.
- `ruff check` and `ruff format --check` pass for new code.
- `pytest --cov=src/boss_automation --cov-fail-under=80` passes.
- `npm run test:unit` (in `wecom-desktop/`) is green.
- `python -c "from boss_automation.database.schema import ensure_schema; ensure_schema(':memory:')"` succeeds and creates all eight BOSS tables.
- `.github/workflows/ci.yml` exists and runs the above three steps.
- Every commit in this change references `0001` in the message.
