# BOSS Zhipin Onboarding Guide

This guide takes a fresh operator from "I have an Android device" to
"my recruiter dashboard is live" in under 30 minutes.

> Audience: a recruiter or ops person setting up automation for a
> *single* BOSS Zhipin account on a *single* Android device. Multi
> -device fan-out is identical, just repeated per device.

## 0. Prerequisites

- Python 3.11+ with `uv` available on `PATH`.
- Node 18+ for the desktop app.
- An Android device with BOSS Zhipin (Boss直聘) installed and
  *already* logged in to the recruiter account you want to automate.
- ADB available on `PATH` and `adb devices` shows the device as
  `device` (not `unauthorized`).

## 1. One-time install

```bash
# Backend
uv venv --python 3.11
source .venv/bin/activate                      # Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"

# Desktop app
cd wecom-desktop
npm install
cd ..
```

Verify the install with the smoke script:

```bash
uv run python scripts/boss_smoke.py
# expect: BOSS smoke OK (recruiters=1, jobs=1, candidates=1, ...)
```

If that line prints, every BOSS service / repository / orchestrator
is wired correctly. If it does not, fix it before continuing — none
of the per-device flows below will work otherwise.

## 2. Enable the BOSS feature flag

The pivot routers stay dark unless you opt in. Add the env var to the
shell that runs the backend (or to your `.env` if you use one):

```bash
export BOSS_FEATURES_ENABLED=true
```

## 3. Start the backend

```bash
cd wecom-desktop/backend
uvicorn main:app --reload --port 8765
```

Hit each BOSS endpoint to confirm the routers mounted:

```bash
curl http://localhost:8765/api/boss/monitoring/summary
# {"generated_at_iso": "...", "window_hours": 24, "recruiters": []}
```

## 4. Bind a recruiter to a device

In a separate shell:

```bash
# Optional: dump the Me-tab UI to a fixture (confirms DroidRun + BOSS app access):
uv run python scripts/dump_boss_ui.py \
    --serial <ADB_SERIAL> \
    --page me_profile \
    --label has_profile

# Persist a recruiter row for this device (M1: operator-supplied snapshot).
# The body must include at least one of name, company, position, avatar_path.
curl -X POST "http://localhost:8765/api/boss/recruiters/<ADB_SERIAL>/refresh" \
     -H 'content-type: application/json' \
     -d '{"name": "王经理", "company": "示例科技", "position": "HRBP"}'
```

A future milestone may add an empty-body refresh that scrapes the live
device; until then, fill fields from the BOSS app UI or from a fixture
dump you inspect locally.

The `recruiters` table now has a row keyed by `device_serial`.

## 5. Sync open and closed jobs

```bash
uv run python wecom-desktop/backend/scripts/boss_sync_jobs.py \
    --serial <ADB_SERIAL>
# or via API:
curl -X POST http://localhost:8765/api/boss/jobs/sync \
     -H 'content-type: application/json' \
     -d '{"device_serial": "<ADB_SERIAL>"}'
```

Confirm in the dashboard or via:

```bash
curl http://localhost:8765/api/boss/monitoring/summary
```

## 6. Configure greet schedule + reply templates

Both are managed from the desktop app:

- *Greet 调度* page → daily window, daily quota, scenario template.
- *Templates* page → CRUD for first-greet / reply / reengage scenarios.

You can also drive them from the API; see the OpenSpec `0004-greet`
and `0005-message-reply` change folders for the request/response
shapes.

## 7. Configure re-engagement

- *复聊跟进 / Reengagement* page → silent days, cooldown, daily cap.
- Hit *Scan* to preview eligible candidates.
- Hit *Run* (with the dispatcher hook disabled) for a dry-run that
  records an attempt without sending.

## 8. Day-2 ops checklist

- Watch the dashboard's `silent_candidates_eligible` counter — if it
  trends up, the followup queue is falling behind.
- Watch `reengagement_attempts_last_24h.failed`; non-zero means the
  dispatcher is erroring (typically: BOSS app not on Messages tab).
- Re-run `scripts/boss_smoke.py` after any backend deploy as a fast
  regression gate before re-enabling per-device traffic.

## Reference: env vars

| Variable | Purpose |
|----------|---------|
| `BOSS_FEATURES_ENABLED` | Mount the `boss_*` routers. Required. |
| `BOSS_DB_PATH` | Override the SQLite file. Defaults to `boss_recruitment.db`. |

## Reference: useful endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/boss/monitoring/summary` | Per-recruiter dashboard counters. |
| `GET /api/boss/recruiters` | List bound recruiters. |
| `GET /api/boss/recruiters/{device_serial}` | Get one recruiter by serial. |
| `POST /api/boss/recruiters/{device_serial}/refresh` | Upsert recruiter snapshot (body needs ≥1 profile field today). |
| `POST /api/boss/jobs/sync` | Sync open/closed jobs. |
| `GET /api/boss/jobs?recruiter_id=<id>` | List jobs for a recruiter (optional `status_filter`). |
| `GET / PUT /api/boss/greet/settings/{device_serial}` | Greet config. |
| `GET / PUT /api/boss/reengagement/settings/{device_serial}` | Reengage config. |
| `POST /api/boss/reengagement/scan` | Preview eligible candidates. |
| `POST /api/boss/reengagement/run` | Execute one re-engagement attempt. |

## Reference: where things live

- BOSS Python package: `src/boss_automation/`
- BOSS routers: `wecom-desktop/backend/routers/boss_*.py`
- Frontend BOSS views: `wecom-desktop/src/views/boss/`
- BOSS UI fixtures (used by tests + smoke): `tests/fixtures/boss/`
- OpenSpec change folders: `openspec/changes/000{1..7}-*/`

See `docs/development/boss-tdd-workflow.md` for the dev playbook.
