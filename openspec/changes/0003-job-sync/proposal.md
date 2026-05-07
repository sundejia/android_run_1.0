# 0003 - Job Sync

## Why

Almost every recruiter workflow on BOSS Zhipin operates *inside the
context of a specific open job*: greeting, replying, re-engaging — all
require selecting a job first. To run automation safely, the framework
must know exactly which jobs each recruiter has, their status (open /
closed / hidden), and basic metadata (title, salary range, location).

M1 gave us recruiters; M2 gives us their jobs.

## What

- Fixtures for the "我的职位" page in three tab states (open, closed,
  hidden), one empty-state variant, and one paginated long-list variant.
- Parser `boss_automation/parsers/job_list_parser.py`:
  pure functions that return typed `Job` objects from a UI tree.
- Repository `boss_automation/database/job_repository.py`:
  upsert by `(recruiter_id, boss_job_id)`, status update, list by
  recruiter / by status.
- Orchestrator `boss_automation/services/job_sync_orchestrator.py`:
  drives an `AdbPort` to navigate each tab, scroll until the list is
  stable, parse, and persist; supports per-tab progress callbacks and a
  checkpoint that can resume mid-scroll if the process is killed.
- Subprocess script `wecom-desktop/backend/scripts/boss_sync_jobs.py`:
  CLI wrapper used by the desktop app; mirrors the existing pattern of
  `wecom-desktop/backend/scripts/initial_sync.py`.
- Backend routes (additions to `routers/boss_recruiters.py` or a new
  `routers/boss_jobs.py`): list jobs by recruiter, trigger a sync, get
  sync status.
- Frontend `views/boss/JobsView.vue`: per-recruiter table of jobs with
  status pills, sync button, and live progress.
- Settings entries: `boss.job_sync.interval_seconds`,
  `boss.job_sync.max_parallel_devices`.

## Out Of Scope

- Editing or closing jobs from the desktop app (read-only sync only).
- Job-detail page parsing beyond what is visible in the list (M3 fetches
  more when greeting candidates).
- Real subprocess orchestration via the legacy `DeviceManager`. M2 ships
  the script and the orchestrator; wiring it into a long-running
  managed process is M6.