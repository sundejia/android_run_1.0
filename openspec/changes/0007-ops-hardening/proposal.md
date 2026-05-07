# Proposal — 0007 Ops Hardening (运维硬化)

## Why

M0 → M5 delivered the full BOSS recruitment loop (jobs → greet →
reply → re-engage). What's missing for production-readiness is
*observability* and *runbooks*: today the operator has no single
view of how many candidates were greeted today, how many silent
ones still need follow-up, or how many templates exist.

M6 closes that gap with a tightly-scoped slice: a BOSS-aware
monitoring summary endpoint, a smoke-test CLI that exercises the
full happy path against an in-memory DB, a desktop dashboard view
fed by the new endpoint, and the operator-facing docs.

## What

### In scope

- `GET /api/boss/monitoring/summary` returning per-recruiter:
  - jobs grouped by status (open / closed / hidden / draft),
  - candidate status counts,
  - greet attempts in the last 24h (sent / cancelled / failed),
  - re-engagement attempts in the last 24h,
  - last greet/run/reengagement timestamps if available.
- `scripts/boss_smoke.py` — runs an end-to-end happy path through the
  pure-Python services (recruiter upsert → job upsert →
  candidate upsert → message insert → reengagement scan/run dry)
  against a tmp DB and prints a one-line summary. Used as a CI gate
  and a manual sanity check.
- A small unit test for `boss_smoke.py` exercising the happy path.
- Two short ops docs:
  - `docs/guides/boss-zhipin-onboarding.md` — how to bind a device,
    run the first sync, configure greet/reengagement.
  - `docs/development/boss-tdd-workflow.md` — fixture → red → green
    → ruff → commit playbook for future BOSS work.
- Frontend `BossDashboardView.vue` (+ Pinia store + spec) that
  consumes the summary endpoint and renders cards per recruiter.

### Out of scope (explicit deferrals)

- The scrcpy multi-window integration (which actually launches scrcpy
  bound to BOSS-tracked devices) — kept as a follow-up. The plan
  scoped it for M6, but it requires real-device wiring that lives
  outside the BOSS_AUTOMATION package and would expand surface area
  too much for one milestone. The dashboard exposes the
  hooks needed for that wiring later.
- Background scheduler for greet/reengagement.
- Production deployment/packaging tweaks.

## Success criteria

- `/api/boss/monitoring/summary` returns deterministic JSON for a
  seeded DB; covered by an API regression test.
- `boss_smoke.py` finishes successfully against a tmp DB; covered
  by an automated test.
- Operator docs explicitly mention every M0–M5 endpoint they need
  to call and what env vars to set.
- All BOSS test suites still pass (Python unit, backend API, Vitest).
