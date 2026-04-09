# Pre-push: restore Python unit tests (2026-04-03)

## Summary

The `pre-push` hook had been **hard-disabled** for Python tests with a comment blaming pytest 9.x and `pytest-cov` on Windows. That diagnosis was **incomplete**. The real blockers were:

1. **`tests/unit/test_attempt_intervals.py` rebinding `sys.stdout` at import time**  
   Replacing `sys.stdout` with a new `TextIOWrapper` breaks pytest’s capture teardown on Windows and surfaces as `ValueError: I/O operation on closed file` during collection or session shutdown—not primarily a `pytest-cov` bug.

2. **Fragile test invocation in the old hook**  
   Using `tests/unit/test_*.py` relies on shell glob expansion; in environments where the glob is not expanded, pytest receives a literal path that does not exist.

3. **Wrong `sys.path` in `test_attempt_intervals.py`**  
   The file used `Path(__file__).parent` as “project root”, so `wecom-desktop/backend` was never on the path and imports like `services.*` failed.

## What we changed

| Area                                   | Change                                                                                                                                                                                                                                                                                                                                                   |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.husky/pre-push`                      | Run `tests/unit` via `uv run --extra dev python -c "… pytest.main(…) …"` with `src` and `wecom-desktop/backend` prepended to `sys.path`. Uses `--no-cov` so push stays fast and coverage plugins do not affect the hook. Fallback: same via `python` if `uv` is missing. **If neither `uv` nor `python` is available, the hook fails** (no silent skip). |
| `tests/unit/test_attempt_intervals.py` | Remove import-time `sys.stdout` replacement; resolve `PROJECT_ROOT` with `Path(__file__).resolve().parents[2]` and add `wecom-desktop/backend` and `src` to `sys.path`.                                                                                                                                                                                  |

## How to run the same checks locally

From the repository root:

```bash
cd wecom-desktop && npx vue-tsc --noEmit && cd ..
uv run --extra dev python -c "import pathlib, sys, pytest; root = pathlib.Path.cwd(); sys.path[:0] = [str(root / 'src'), str(root / 'wecom-desktop' / 'backend')]; raise SystemExit(pytest.main(['tests/unit', '-v', '--tb=short', '-q', '--no-cov']))"
```

## Scope note

Pre-push runs **`tests/unit` only** (fast, no device). Backend route tests under `wecom-desktop/backend/tests/` remain for CI or manual runs; see `README.md` / `docs/07-appendix/test-organization.md`.

## Verification

- `npx vue-tsc --noEmit` in `wecom-desktop`
- Full `tests/unit` suite with the same `pytest.main` invocation as the hook
