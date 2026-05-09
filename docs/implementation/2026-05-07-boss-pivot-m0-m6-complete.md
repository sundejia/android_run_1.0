# BOSS Zhipin Pivot — M0 Through M6 Delivered (2026-05)

This document records what shipped when the repository pivoted from WeCom
(企业微信) automation to BOSS 直聘 recruitment automation alongside the
legacy stack. It is the canonical “what we built” summary for operators
and future contributors.

## Scope

- **In scope:** additive modules under `src/boss_automation/`, BOSS FastAPI
  routers (`wecom-desktop/backend/routers/boss_*.py`), BOSS desktop UI
  (`wecom-desktop/src/views/boss/`), BOSS SQLite schema (default
  `boss_recruitment.db`), fixture-driven unit tests, CI gates for BOSS.
- **Explicitly not removed:** `src/wecom_automation/`, existing desktop
  routes, `wecom_conversations.db`. Both stacks coexist until a future
  cleanup milestone.

## Milestones Delivered

| ID | Theme | Primary artifacts |
|----|-------|-------------------|
| **M0** | Pivot foundation | `src/boss_automation/` package, `ensure_schema`, `tests/_fixtures/loader.py`, `scripts/dump_boss_ui.py`, Tailwind `boss` theme, `.github/workflows/ci.yml`, OpenSpec `0001-pivot-foundation` |
| **M1** | Recruiter bootstrap | `RecruiterProfile` parsers, `RecruiterRepository`, `BossAppService`, `boss_recruiters` router, `RecruitersListView` |
| **M2** | Job sync | `job_list_parser`, `JobSyncOrchestrator`, `job_repository`, `boss_jobs` router + CLI, `JobsView` |
| **M3** | Candidate greeting | Candidate parsers, `GreetExecutor`, quota + schedule, `boss_greet` router, `GreetScheduleView` |
| **M4** | Message reply | Message/conversation/resume parsers, `TemplateEngine`, `AiReplyClient`, `ReplyDispatcher`, `boss_templates` + `boss_messages`, templates + conversations UI |
| **M5** | Re-engagement | `SilentCandidateDetector`, `FollowupAttemptsRepository`, `ReengagementOrchestrator`, `boss_reengagement` router, `ReengagementView` |
| **M6** | Ops hardening | `GET /api/boss/monitoring/summary`, `scripts/boss_smoke.py`, `BossDashboardView` + `useBossMonitoringStore`, onboarding + TDD docs |
| **Post-M6** | Navigation landing | `BossNavigator` tab-aware navigation, `AdbPort.press_back`, DroidRunAdapter coordinate-based `tap_by_text`, wired into `ReplyDispatcher` / `GreetExecutor` / API routers |

## Operations Surface

| Concern | Location / mechanism |
|---------|----------------------|
| Feature gate | `BOSS_FEATURES_ENABLED=true` mounts all `boss_*` routers |
| BOSS database | `BOSS_DB_PATH` or default `boss_recruitment.db` at repo root |
| Smoke regression | `uv run python scripts/boss_smoke.py` → prints `BOSS smoke OK` |
| Monitoring API | `GET /api/boss/monitoring/summary` (rolling 24h windows) |
| Page navigation | `BossNavigator` — tab-aware BACK-retry navigation (mirrors WeCom `ensure_on_private_chats`) |
| Operator runbook | `docs/guides/boss-zhipin-onboarding.md` |
| Developer playbook | `docs/development/boss-tdd-workflow.md`, `docs/00-boss-pivot/tdd-workflow.md` |

## Deferred After M6

Documented in OpenSpec `openspec/changes/0007-ops-hardening/`:

- **scrcpy multi-window** integration bound to tracked devices (needs
  real-device wiring outside `boss_automation`).
- **Background schedulers** for greet / re-engage (today: on-demand +
  dashboard polling).
- **Production packaging** tweaks beyond the existing Electron stack.

## Verification Snapshot (local)

These numbers drift as tests are added; they reflect the regime at M6
completion:

- Python: `tests/unit/` (includes WeCom + BOSS) — full suite used by
  `.husky/pre-push`.
- BOSS-only: `tests/unit/boss/` and `wecom-desktop/backend/tests/` with
  `-k boss` filter when isolating.
- Frontend: `npm run test` / `vitest` in `wecom-desktop/`.

## Related Documents

- `docs/00-boss-pivot/README.md` — pivot index and roadmap (completed).
- `openspec/changes/0001-pivot-foundation/` … `0007-ops-hardening/` —
  proposals, tasks, designs per milestone.
