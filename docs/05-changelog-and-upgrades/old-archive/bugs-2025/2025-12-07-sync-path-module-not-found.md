# Bug Report: Sync Selected fails with `ModuleNotFoundError` for `wecom_automation`

## Executive Summary

- Issue: Multi-device “Sync Selected” in WeCom Desktop failed immediately with `ModuleNotFoundError: No module named 'wecom_automation'`.
- Impact: Sync subprocess exited with code 1 for all selected devices; no data synchronized.
- Resolution: Added an explicit `src` path bootstrap to `initial_sync.py` so it can import the local `wecom_automation` package when executed directly by the backend subprocess.
- Status: Fixed and verified via direct import; UI retest recommended.

## Timeline

- 2025-12-07: Failure observed in desktop logs for two devices during sync start.
- 2025-12-07: Root cause identified and fixed by adjusting `initial_sync.py` imports.

## Symptoms and Impact

- Action: Clicked “Sync Selected (2)” in WeCom Desktop.
- Result: Both device syncs logged `ModuleNotFoundError: No module named 'wecom_automation'` originating from `initial_sync.py`, then exited with code 1.
- Scope: Affected all sync attempts launched via the desktop backend (subprocess execution).
- User-facing impact: Sync did not run; no conversations were synchronized.

## Environment

- OS: macOS (per host environment).
- Components: WeCom Desktop backend (`wecom-desktop/backend`), `initial_sync.py` script in repo root.
- Invocation: Backend `DeviceManager` launches `python initial_sync.py ...` with `cwd` at project root; relies on local source instead of an installed package.

## Root Cause Analysis

- `initial_sync.py` imported `wecom_automation.*` assuming the package was installed or on `PYTHONPATH`.
- The backend subprocess executed the script directly from the repo without installing the package; `src/` was not on `sys.path`, so imports resolved to nothing and raised `ModuleNotFoundError`.
- Regression context: The sync button had worked in earlier revisions where the environment likely had an editable install or path injection; current workflow depended on implicit path availability that was no longer present.

## Attempted Solutions (Failed)

- Observed logs pointed straight to missing module; no alternate fixes attempted before adjusting import path.

## Successful Solution

- Added a small bootstrap at the top of `initial_sync.py` to prepend the repository `src` directory to `sys.path` before importing `wecom_automation`.
- Verification: `python - <<'PY'\nimport initial_sync\nprint('import ok')\nPY` now succeeds.

```47:51:initial_sync.py
# Ensure local package imports work when the script is executed directly
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
```

## Lessons Learned / Prevention

- When launching scripts directly via subprocess, always ensure `src` is on `sys.path` or install the package in editable mode for that environment.
- Consider adding a lightweight startup check in the backend to fail fast on import errors before starting device processes.
- Add a smoke test that exercises the backend `start_sync` path in CI to catch missing-module regressions.

## Follow-ups

- Retest the desktop “Sync Selected” flow with multiple devices to confirm end-to-end sync now runs.
- Evaluate installing `wecom-automation` in the backend environment (`uv pip install -e .`) to avoid future path-related import issues.

## References

- Fix implemented in `initial_sync.py` (path bootstrap).
- Triggering logs observed in WeCom Desktop Device Logs panel for two devices.\*\*\*
