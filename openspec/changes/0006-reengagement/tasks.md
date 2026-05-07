# Tasks — 0006 Reengagement

## Phase 1: Detector

- [x] tests/unit/boss/services/test_silent_candidate_detector.py
- [x] src/boss_automation/services/reengagement/detector.py

## Phase 2: Repository

- [x] tests/unit/boss/test_followup_attempts_repository.py
- [x] src/boss_automation/database/followup_attempts_repository.py

## Phase 3: Orchestrator

- [x] tests/unit/boss/services/test_reengagement_orchestrator.py
- [x] src/boss_automation/services/reengagement/orchestrator.py
  covering: blacklist mid-flight check, candidate-replied
  cancellation, daily cap, dispatch failure, dry-run.

## Phase 4: Backend API

- [x] wecom-desktop/backend/routers/boss_reengagement.py
- [x] wecom-desktop/backend/tests/test_boss_reengagement_api.py
- [x] Mounted in main.py behind BOSS_FEATURES_ENABLED.

## Phase 5: Frontend

- [x] bossApi.ts extended (settings + scan + run)
- [x] stores/bossReengagement.ts + spec
- [x] views/boss/ReengagementView.vue + spec

## Verification

- 248 BOSS Python unit tests green (`uv run pytest tests/unit/boss`).
- 49 BOSS backend API tests green (incl. 7 new reengagement tests).
- 99 desktop Vitest tests green (incl. 9 new reengagement tests).
- ruff clean on the new modules.
