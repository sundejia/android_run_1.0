# Tasks - 0003 Job Sync

## Phase 1: Fixtures + Parser (RED → GREEN)

- [x] tests/fixtures/boss/jobs_list/open_tab.json
- [x] tests/fixtures/boss/jobs_list/closed_tab.json
- [x] tests/fixtures/boss/jobs_list/empty_state.json
- [x] tests/fixtures/boss/jobs_list/long_list_page1.json
- [x] tests/unit/boss/parsers/test_job_list_parser.py — RED
- [x] src/boss_automation/parsers/job_list_parser.py — GREEN

## Phase 2: Repository

- [x] tests/unit/boss/test_job_repository.py — RED
- [x] src/boss_automation/database/job_repository.py — GREEN

## Phase 3: Orchestrator

- [x] tests/unit/boss/services/test_job_sync_orchestrator.py — RED
- [x] src/boss_automation/services/job_sync_orchestrator.py — GREEN
  - Reuses AdbPort Protocol from M1
  - Iterates configured tabs (open / closed / hidden)
  - Scrolls until two consecutive UI hashes match (stable threshold)
  - Persists via JobRepository
  - Emits typed JobSyncProgress events to a callback

## Phase 4: Backend route + subprocess script

- [x] wecom-desktop/backend/routers/boss_jobs.py
- [x] wecom-desktop/backend/tests/test_boss_jobs_api.py
- [x] wecom-desktop/backend/scripts/boss_sync_jobs.py (CLI wrapper)

## Phase 5: Frontend

- [x] wecom-desktop/src/services/bossApi.ts (extend with jobs methods)
- [x] wecom-desktop/src/stores/bossJobs.ts + spec
- [x] wecom-desktop/src/views/boss/JobsView.vue + spec

## Phase 6: Wire-up

- [x] Register boss_jobs router in main.py behind boss_features_enabled
