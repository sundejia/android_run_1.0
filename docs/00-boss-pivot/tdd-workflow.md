# TDD Workflow For The BOSS Pivot

This is the playbook every contributor follows when adding a new BOSS
feature. It is the ground truth referenced from `openspec/AGENTS.md`
and `docs/00-boss-pivot/README.md`.

## The Loop

```
1. Capture or update a UI fixture from a real device.
2. Write the failing unit test that uses that fixture.
3. Implement the smallest production code that turns the test green.
4. Refactor, then re-run the full BOSS suite + ruff.
5. Commit with the change ID prefix, e.g. feat(0002): ...
```

## 1. Capture A Fixture

```bash
uv run scripts/dump_boss_ui.py \
    --serial <ADB-SERIAL> \
    --page jobs_list \
    --label open_tab_with_pagination
```

After capture, inspect the JSON to confirm:
- The expected user-visible labels appear in `ui_tree`.
- `app.package_name` matches a known BOSS package.
- `device.serial` and `captured_at` are recorded.

Commit the fixture in the same PR as the test that consumes it. Never
edit a fixture by hand; re-dump instead.

## 2. Write The Failing Test

Use the loader rather than reading the JSON directly:

```python
from pathlib import Path

from tests._fixtures.loader import load_fixture


FIXTURE_PATH = Path(__file__).resolve().parents[3] \
    / "tests" / "fixtures" / "boss" / "jobs_list" / "open_tab_with_pagination.json"


def test_open_jobs_parser_returns_paginated_results() -> None:
    fixture = load_fixture(FIXTURE_PATH)

    jobs = parse_open_jobs(fixture.ui_tree)  # not yet implemented

    assert len(jobs) == 12
    assert all(job.status == "open" for job in jobs)
```

Run the test and confirm it fails with the expected import or
attribute error. This pins the contract before any implementation.

## 3. Implement The Minimum

Production code for that test goes under `src/boss_automation/`. Pure
parsing functions live in `src/boss_automation/parsers/`. Functions
that talk to the device live in `src/boss_automation/services/`.

Keep parsers free of I/O. Pass the UI tree dict in, return typed
domain objects out. This is what makes them testable from fixtures.

## 4. Refactor And Verify

```bash
uv run ruff check src/boss_automation/ tests/unit/boss/
uv run ruff format src/boss_automation/ tests/unit/boss/
uv run python -m pytest tests/unit/boss/ -p no:logfire \
    --cov=src/boss_automation --cov-fail-under=80
```

Both gates must be green before commit.

## 5. Commit

Use Conventional Commits with the OpenSpec change ID as the scope:

```
feat(0002): parse recruiter profile from main page tree
test(0002): cover empty profile fallback path
fix(0003): handle blank job-status badge after reload
```

## When Real-Device Behavior Changes

If a fixture goes stale (BOSS app updated, screen flow changed):

1. Re-dump with `--force`.
2. Re-run the affected tests; they may go red.
3. Update parsers/services until green.
4. Commit fixture + code together so a single revert fully restores
   the prior contract.

## When To Add An Integration Test

Add a `tests/integration/test_*.py` (with `pytestmark =
pytest.mark.integration`) when you need to validate behavior that
spans the device and the orchestrator: e.g. "after greeting 5
candidates the quota guard halts further attempts". CI does not run
these; the human running the regression must do `pytest -m
integration` against a connected device.

## Anti-Patterns To Avoid

- Hardcoding screen coordinates in parsers. Always extract by resource
  id, content description, or text from the dumped tree.
- Mocking the entire `ADBService` for a parser test; the parser should
  not need any device abstraction.
- Editing a fixture by hand to make a test pass. The fixture is
  evidence; if you change it, you change reality.
- Adding code without a corresponding new or updated test.
