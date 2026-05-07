# Tasks - 0004 Greet Candidates

## Phase 1: Fixtures

- [x] candidates_feed/feed_with_cards.json
- [x] candidate_detail/ready_to_greet.json
- [x] candidate_detail/already_greeted.json
- [x] candidate_detail/quota_exhausted.json
- [x] candidate_detail/risk_control_popup.json

## Phase 2: Parsers + State Detector

- [x] tests/unit/boss/parsers/test_candidate_card_parser.py
- [x] src/boss_automation/parsers/candidate_card_parser.py
- [x] tests/unit/boss/parsers/test_greet_state_detector.py
- [x] src/boss_automation/parsers/greet_state_detector.py

## Phase 3: Repository

- [x] tests/unit/boss/test_candidate_repository.py
- [x] src/boss_automation/database/candidate_repository.py

## Phase 4: Quota Guard + Schedule

- [x] tests/unit/boss/services/test_quota_guard.py
- [x] src/boss_automation/services/greet/quota_guard.py
- [x] tests/unit/boss/services/test_greet_schedule.py
- [x] src/boss_automation/services/greet/schedule.py

## Phase 5: Greet Executor

- [x] tests/unit/boss/services/test_greet_executor.py
- [x] src/boss_automation/services/greet/greet_executor.py
  - 8-path matrix: ready / already-greeted / quota / risk-control
    / blacklisted / outside-window / duplicate-tap / unknown.

## Phase 6: Backend route

- [x] wecom-desktop/backend/routers/boss_greet.py
- [x] wecom-desktop/backend/tests/test_boss_greet_api.py
- [x] Mount in main.py behind BOSS_FEATURES_ENABLED

## Phase 7: Frontend

- [x] wecom-desktop/src/services/bossApi.ts (greet methods)
- [x] wecom-desktop/src/stores/bossGreet.ts + spec
- [x] wecom-desktop/src/views/boss/GreetScheduleView.vue + spec
