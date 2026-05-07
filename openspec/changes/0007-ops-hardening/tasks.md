# Tasks — 0007 Ops Hardening

## Phase 1: Monitoring summary

- [x] wecom-desktop/backend/routers/boss_monitoring.py
- [x] wecom-desktop/backend/tests/test_boss_monitoring_api.py
- [x] Mount in main.py behind BOSS_FEATURES_ENABLED.

## Phase 2: Smoke test

- [x] scripts/boss_smoke.py
- [x] tests/unit/boss/test_boss_smoke.py

## Phase 3: Docs

- [x] docs/guides/boss-zhipin-onboarding.md
- [x] docs/development/boss-tdd-workflow.md

## Phase 4: Frontend dashboard

- [x] bossApi.ts extended (monitoring summary)
- [x] stores/bossMonitoring.ts + spec
- [x] views/boss/BossDashboardView.vue + spec

## Verification

- [x] ruff + pytest + vitest all green
  (252 BOSS unit tests, 53 BOSS API tests, 109 vitest tests).
- [x] `uv run python scripts/boss_smoke.py` prints `BOSS smoke OK` and
  exits 0.
- [x] Single commit `feat(boss-m6): ops hardening ...`.
