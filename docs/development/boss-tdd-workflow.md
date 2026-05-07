# BOSS Pivot — TDD Workflow Playbook

This is the dev-side companion to `docs/guides/boss-zhipin-onboarding.md`.
It captures the loop the M0–M6 milestones used so future BOSS work
stays consistent.

## Loop

```
fixture  ──▶  red test  ──▶  green impl  ──▶  ruff + format  ──▶  commit
   ▲                                                                  │
   └──────────────────── repeat per slice ───────────────────────────┘
```

Each slice ships one capability end-to-end (parser, repository, service,
router, store, view). No "skeleton + later" PRs.

## 1. Fixture-first

For any code that ingests a UI tree:

1. Dump from a real device with `scripts/dump_boss_ui.py` *or* hand
   -build a synthetic JSON in `tests/fixtures/boss/<feature>/<case>.json`.
2. Synthetic fixtures are encouraged when the production UI is volatile:
   they document the contract our parser depends on.
3. Each fixture should have a short header comment in the JSON owner
   (the test file) describing what it is testing — fixtures are the
   spec.

## 2. Red test

Always write the failing test before the implementation.

- Pure-Python services: `tests/unit/boss/...`
- DB repositories: same directory, `test_<thing>_repository.py`
- API routers: `wecom-desktop/backend/tests/test_boss_<thing>_api.py`
- Frontend components / stores: co-located `*.spec.ts` next to the
  source file.

Run *just the new test* and confirm it fails for the right reason
(import error, missing function, wrong return value). A test that
fails for the wrong reason is not a red test.

## 3. Green impl

Smallest change that makes the new test pass without breaking any
existing test. Don't add fields you don't have a test for; that's
where dead code is born.

## 4. Ruff + format

```bash
uv run ruff check src/boss_automation tests/unit/boss \
                  wecom-desktop/backend/routers \
                  wecom-desktop/backend/tests
uv run ruff format src/boss_automation tests/unit/boss \
                   wecom-desktop/backend/routers \
                   wecom-desktop/backend/tests
```

Frontend:

```bash
cd wecom-desktop && npm run -s test
```

## 5. Commit

Use Conventional Commits with the milestone prefix:

```
feat(boss-m6): add /api/boss/monitoring/summary endpoint
```

One milestone = one commit at the green light, not many tiny WIPs.

## Test organisation conventions

Per `.cursorrules`:

- ❌ never put `test_*.py` in project root, `src/`, or `scripts/`.
- ✅ Python BOSS unit tests → `tests/unit/boss/`
- ✅ Backend BOSS API tests → `wecom-desktop/backend/tests/`
- ✅ Frontend specs → next to the source file as `*.spec.ts`

## Repository / service guardrails

The patterns we keep:

- Repositories own one table and call `ensure_schema()` on init.
- Services accept dependencies in the constructor (`AdbPort`,
  repositories, callbacks). Do not import driver modules directly
  inside service code paths.
- Async callbacks must be `Awaitable`-typed and `await`-ed.
- Any send-safety check (blacklist, replied-mid-flight, daily cap)
  runs at *both* enqueue time and immediately before the actual
  send. Never fail-open.

## Frontend conventions

- New BOSS views go under `wecom-desktop/src/views/boss/` and are
  scoped with the `boss-scope` CSS class (see
  `wecom-desktop/src/styles/boss-theme.css`).
- Pinia stores expose `fetchAll`, `loading`, `error` consistently.
- API methods centralise in `wecom-desktop/src/services/bossApi.ts`.

## Smoke regression gate

After any backend change, run:

```bash
uv run python scripts/boss_smoke.py
```

It should print `BOSS smoke OK` and exit 0. CI runs the same script
via `tests/unit/boss/test_boss_smoke.py`.

## Where to find the milestones

- `openspec/changes/0001-pivot-foundation/` — schema, packages, CI.
- `openspec/changes/0002-recruiter-bootstrap/` — bind device → recruiter.
- `openspec/changes/0003-job-sync/` — job list scrape.
- `openspec/changes/0004-greet-candidates/` — feed + greet executor.
- `openspec/changes/0005-message-reply/` — parsers + dispatcher.
- `openspec/changes/0006-reengagement/` — silent detector + orchestrator.
- `openspec/changes/0007-ops-hardening/` — monitoring + smoke + docs.
