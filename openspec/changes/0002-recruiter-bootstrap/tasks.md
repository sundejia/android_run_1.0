# Tasks - 0002 Recruiter Bootstrap

## Phase 1: Parser (RED → GREEN)

- [x] Create `tests/fixtures/boss/home/logged_in.json` (synthetic until
      real device dump replaces it)
- [x] Create `tests/fixtures/boss/home_logged_out/login_wall.json`
- [x] Create `tests/fixtures/boss/me_profile/has_profile.json`
- [x] Create `tests/fixtures/boss/me_profile/empty_profile.json`
- [x] Write failing tests `tests/unit/boss/parsers/test_recruiter_profile_parser.py`
- [x] Implement `src/boss_automation/parsers/recruiter_profile_parser.py`

## Phase 2: Repository

- [x] Write failing tests `tests/unit/boss/test_recruiter_repository.py`
- [x] Implement `src/boss_automation/database/recruiter_repository.py`

## Phase 3: Service

- [x] Write failing tests `tests/unit/boss/services/test_boss_app_service.py`
      using a fake ADB layer
- [x] Implement `src/boss_automation/services/adb_port.py` (thin
      protocol over the parts of ADBService we actually consume — keeps
      the service testable without DroidRun)
- [x] Implement `src/boss_automation/services/boss_app_service.py`

## Phase 4: Backend route + frontend view

- [x] Backend tests `wecom-desktop/backend/tests/test_boss_recruiters_api.py`
- [x] Implement `wecom-desktop/backend/routers/boss_recruiters.py`
      (NOT registered into the legacy `main.py` yet — registration
      happens in a separate commit so the legacy app stays clean)
- [x] Frontend store `wecom-desktop/src/stores/bossRecruiters.ts` +
      Vitest spec
- [x] Frontend view `wecom-desktop/src/views/boss/RecruitersListView.vue`
      + Vitest spec for the empty-state and the populated-state
      rendering

## Phase 5: Wire-up + integration

- [x] Register the new router into `main.py` behind a feature flag
      (`BOSS_FEATURES_ENABLED` env var, default false)
- [x] Add an integration test stub `tests/integration/test_recruiter_bootstrap_e2e.py`
      with `pytestmark = pytest.mark.integration` (skipped on CI)
