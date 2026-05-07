# Proposal — 0006 Reengagement (复聊跟进)

## Why

After M4, the system can reply to candidates that send the recruiter
unread messages. But many candidates simply *don't* reply after the
first round. Today the recruiter has no automated way to "ping" them
again, so a sizeable portion of the funnel goes silent.

M5 closes that gap: for any conversation where **we sent the last
message** and the candidate has been silent past a configured
threshold, schedule a re-engagement message ("还在看机会吗？
方便聊几句吗？"), respecting the same blacklist + quota guardrails as
M3 / M4.

## What

### In scope

- Pure-function detector that scans the persisted conversation /
  message tables and yields candidates eligible for re-engagement
  (`SilentCandidateDetector`).
- New repository for `followup_attempts_v2` (the M0 schema already
  has the table) — append-only attempt history with `pending /
  sent / cancelled / failed` lifecycle.
- `ReengagementOrchestrator` that, per recruiter:
  - asks the detector for eligible candidates,
  - applies cooldown (e.g. don't re-engage the same person twice
    within N days),
  - re-validates blacklist state at *send time* (AGENTS.md guardrail
    — never fail-open),
  - cancels any pending attempt when the candidate replies in the
    interim,
  - dispatches via the existing `ReplyDispatcher` so the actual UI
    work (open chat → type → send) is shared with M4.
- Backend router `boss_reengagement`:
  - `GET / PUT /api/boss/reengagement/settings/{device_serial}` —
    silent-threshold, cooldown, daily cap, scenario template.
  - `POST /api/boss/reengagement/scan` — return eligible candidates
    without sending.
  - `POST /api/boss/reengagement/run` — execute one attempt, returning
    the recorded `followup_attempts_v2` row + dispatch outcome.
- Frontend Pinia store `bossReengagement` and view
  `ReengagementView.vue` (settings form + scan results table + "run
  one" + last-attempt log).

### Out of scope (defer)

- The background scheduler / APScheduler job that runs scans on a
  cron — kept for M6 (运维硬化) so we don't ship a long-running task
  without monitoring.
- AI-generated re-engagement copy. We use a template-only path here;
  the existing `AiReplyClient` from M4 can be wired in later behind
  a feature flag.
- Per-job cool-down logic (the basic per-candidate cool-down is
  enough for the first ship).

## Success criteria

- All M5 logic is fixture/mock driven; no real device required for
  unit + API tests.
- Send-time blacklist check is *the* authoritative gate (AGENTS.md
  Blacklist Send-Safety guardrail) and is covered by a regression
  test where the candidate is blacklisted between scan and run.
- A pending attempt is automatically cancelled (and logged) if the
  candidate replies before we send.
- 90+% line coverage on the new modules.
