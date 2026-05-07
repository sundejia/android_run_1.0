# 0002 - Recruiter Bootstrap

## Why

Before any recruiting workflow can run, the automation must know
*which recruiter account is logged in on a given Android device*. The
recruiter is the root of the data model: jobs, candidates,
conversations, and follow-up attempts all hang off `recruiters.id`.

Today the BOSS Python package can create the schema but cannot read
anything from a real BOSS Zhipin app. M1 closes that gap.

## What

- A fixture catalog for the three BOSS app pages we need at bootstrap
  time:
  * `home` (logged-in main page with the bottom navigation bar)
  * `home_logged_out` (login wall)
  * `me_profile` (the "我" tab showing recruiter name + company)
- `boss_automation/parsers/recruiter_profile_parser.py`:
  pure functions that turn a UI tree into typed
  `RecruiterProfile` and `LoginState` objects.
- `boss_automation/services/boss_app_service.py:BossAppService`:
  - `launch()` opens the app via `ADBService.start_app`.
  - `is_logged_in()` returns a bool from the current UI tree.
  - `get_recruiter_profile()` navigates to the "我" tab if needed and
    returns a `RecruiterProfile`.
- `boss_automation/database/recruiter_repository.py`: simple
  upsert-by-device_serial repository.
- Backend route `GET /api/boss/recruiters` and
  `POST /api/boss/recruiters/{serial}/refresh` (in a NEW router file
  under `wecom-desktop/backend/routers/boss_recruiters.py` so it does
  not collide with the legacy `/devices` and `/kefus` routes).
- Frontend `RecruitersListView.vue` under
  `wecom-desktop/src/views/boss/` listing each device with its bound
  recruiter, plus a refresh button per device.
- Pinia store `bossRecruiters.ts`.
- Integration test file (skipped on CI) that exercises the full real-device
  bootstrap path.

## Out Of Scope

- Job sync (M2).
- Greeting any candidate (M3).
- Resume parsing (M4).
- Multi-account switching on a single device (deferred until product
  confirms the use case).
- BOSS account login / scan-code automation. Recruiters log in
  manually; the framework only **detects** the logged-in state.

## Success Criteria

- `pytest tests/unit/boss/ --cov=src/boss_automation
  --cov-fail-under=80` is green and includes ≥ 12 new tests for parser
  + service + repository.
- `BossAppService.get_recruiter_profile()` correctly returns
  `RecruiterProfile(name="王经理", company="ACME 互联网", position="HRBP")`
  against the fixture `tests/fixtures/boss/me_profile/has_profile.json`.
- The frontend renders one card per connected BOSS device, showing the
  recruiter's name + company, even when the recruiter info is not yet
  cached (placeholder card with a "刷新" button).
- Coverage of `src/boss_automation/parsers/` and
  `src/boss_automation/services/` ≥ 90%.
