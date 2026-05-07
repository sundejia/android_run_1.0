# 0004 - Greet Candidates: BOSS Recommended Talent Outreach

## Why

Recruiters spend most of their day on the "推荐牛人" feed: scroll →
tap a candidate card → tap 立即沟通 → BOSS auto-sends the recruiter's
configured greeting. Doing this by hand caps a recruiter at maybe 100
greetings/day. With M0–M2 now landed (recruiter identity + job sync),
M3 unlocks the first real automation use case.

The non-negotiables we MUST honor:

1. **Quota safety**. BOSS rate-limits greetings (commonly 100/day, but
   varies per account). Triggering the platform's anti-fraud system
   suspends the recruiter account, which is far more damaging than
   simply running slower. The executor MUST respect a configurable
   per-day cap and per-hour cap.
2. **Time-window safety**. Sending greetings at 03:00 looks like a
   bot. The schedule layer MUST gate execution by configurable
   day/hour windows, including cross-midnight windows (e.g. 21:00–01:00).
3. **Blacklist safety**. A candidate the operator blocked yesterday
   MUST never receive a greeting today, even if they reappear in the
   feed. Identity = `(recruiter_id, boss_candidate_id)` per the
   AGENTS.md blacklist guardrail.
4. **State-aware skipping**. If BOSS shows the candidate as "已沟通"
   (already messaged), the executor MUST detect that, skip
   gracefully, and NOT count the no-op as a quota event.
5. **Risk-control halting**. If BOSS surfaces a 风控弹窗
   (anti-fraud popup), the executor MUST halt the run, mark the
   schedule paused, and surface a structured error to the desktop
   app. Never auto-dismiss and continue.

## What

This change delivers all the building blocks needed to safely send
greetings at scale, plus the operator UI to configure the schedule.

- New UI fixtures for the recommended-candidates feed, candidate
  detail page (in two states: never-greeted and already-greeted), the
  立即沟通 success view, the daily-quota-exhausted page, and the
  风控弹窗.
- `parsers/candidate_card_parser.py` extracts a typed
  `CandidateCard` per item in the feed.
- `parsers/greet_state_detector.py` classifies the candidate-detail
  page into `READY_TO_GREET | ALREADY_GREETED | QUOTA_EXHAUSTED |
  RISK_CONTROL_BLOCKED | UNKNOWN`.
- `database/candidate_repository.py` for the existing `candidates`
  table (the schema landed in M0; M3 wires it).
- `services/greet/quota_guard.py` enforces per-day, per-hour, and
  per-job caps using the messages table as the source of truth.
- `services/greet/greet_executor.py` is the unit-of-work runner: tap
  card → detect state → tap 立即沟通 → confirm → record. Pluggable
  callbacks for blacklist checking, quota updates, and progress
  events.
- `services/greet/schedule.py` checks "is now inside the configured
  window" given a `GreetSchedule` config; supports cross-midnight.
- Backend route `POST /api/boss/greet/start`, `POST /api/boss/greet/stop`,
  `GET /api/boss/greet/status`. (Subprocess wiring lands in M6; M3 ships
  the in-process executor + REST surface used by tests and the desktop
  app's preview "test run".)
- Frontend `GreetScheduleView.vue` with time-window editor,
  per-hour cap input, per-day cap input, blacklist toggles, and a
  live "next eligible window" indicator.
- Pinia `useBossGreetStore` covering schedule load/save and dry-run.

## Out of Scope

- Subprocess process-per-device (lands in M6 alongside scrcpy).
- AI-generated personalized greetings (M4 owns templating).
- Re-engagement / 复聊 (M5 owns its own scheduler that REUSES
  M3's quota guard).

## Success Criteria

- All five new candidate-feed UI fixtures load via the existing
  fixture loader; parsers extract the expected fields.
- Greet executor passes a 8-path test matrix: ready / already-greeted
  / quota-exhausted / risk-control / blacklisted / outside-window /
  duplicate-tap / unknown-ui.
- Quota guard rejects an N+1th send within the same hour and the same
  day given configurable caps.
- Schedule.is_within_window returns correct results for normal,
  same-day, and cross-midnight windows.
- Backend POST /greet/start mounted only when BOSS_FEATURES_ENABLED.
- GreetScheduleView renders, validates form input, and persists via
  the store; vitest suite covers happy and validation-failure paths.
- Total BOSS unit-test count >= 165 (currently 119 + ~46 added).
- Coverage on src/boss_automation/ stays >= 90 %.
