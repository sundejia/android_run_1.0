# Tasks - 0001 Pivot Foundation

## Phase 1: Scaffolding (commit a)

- [x] Create `openspec/AGENTS.md` and this change directory
- [x] Add `src/boss_automation/` package with `core`, `database`, `services`, `parsers` subpackages
- [x] Write `tests/unit/boss/test_boss_schema.py` — failing tests for `ensure_schema()` creating all required tables
- [x] Implement `src/boss_automation/database/schema.py` until tests pass
- [x] Write `tests/unit/boss/test_fixture_loader.py` — failing tests for the dump-fixture loader
- [x] Implement `tests/_fixtures/loader.py` until tests pass
- [x] Add `scripts/dump_boss_ui.py` (real-device tool, no unit test required; covered by integration spec only)
- [x] Update `pyproject.toml`: add `boss_automation` to wheel packages, coverage source, ruff src

## Phase 2: CI + theme (commit b)

- [x] Add `.github/workflows/ci.yml` with ruff + pytest (with coverage gate) + vitest jobs
- [x] Update `pyproject.toml`: add `--cov-fail-under=80` to default `addopts` (only when `--cov` is requested)
- [x] Add `boss-desktop/` Tailwind theme overrides (deep indigo palette, Inter font)
  - Note: applied as additive override in `wecom-desktop/tailwind.config.js` since rename is M6
- [x] Add `wecom-desktop/src/styles/boss-theme.css` for the recruitment color palette

## Phase 3: Docs + env vars (commit c)

- [x] Refresh `AGENTS.md` to mention OpenSpec at `openspec/AGENTS.md` (file now exists)
- [x] Add new doc directory `docs/00-boss-pivot/` with onboarding notes
- [x] Add `BOSS_*` environment variable definitions to `src/boss_automation/core/config.py`
- [x] Update `.cursorrules` to reference `src/boss_automation` test paths

## Phase 4: WeCom legacy archival start (commit d, optional within M0)

- [ ] Create `archive/wecom-legacy/README.md` documenting the archival plan
- [ ] Move `src/wecom_automation/services/contact_share/` → `archive/wecom-legacy/contact_share/`
- [ ] Move associated tests
- [ ] Verify all remaining tests still green
