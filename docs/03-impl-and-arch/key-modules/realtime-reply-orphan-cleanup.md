# Realtime reply: orphan subprocess cleanup

> **Last updated:** 2026-04-22  
> **Component:** `RealtimeReplyManager`, `main.py` lifespan  
> **Status:** Stable

## Purpose

Prevent **multiple concurrent** `realtime_reply_process.py` trees for the same device serial after **uvicorn `--reload`**, backend crashes, or any situation where the manager’s in-memory `_processes` map is reset while OS subprocesses survive.

Without cleanup, two trees compete for the same ADB/DroidRun session and produce unreliable UI automation (including `[Errno 22]` on swipe) and confusing multi-panel log behaviour.

## Implementation

**Module:** `wecom-desktop/backend/utils/orphan_process_cleaner.py`

- **`kill_realtime_reply_orphans(serial: str | None)`**
  - `serial` set: match processes whose command line includes `realtime_reply_process.py` and `--serial <serial>`.
  - `serial` is `None`: match **all** such processes (startup sweep).
- Uses **`psutil`** to enumerate processes, group matches into trees, and terminate from the **outermost root** so each logical tree is killed once.
- Best-effort: failures are logged; callers do not crash startup.

## Integration points

1. **`RealtimeReplyManager.start_realtime_reply`** — after the “already running in this worker” check, **before** building the `uv run …` command. Ensures a new start never stacks on top of a surviving orphan from a previous worker.
2. **`main.py` lifespan** — immediately after directory setup, **before** DB migrations. Ensures every new worker begins without leftover realtime-reply children from the replaced process.

## Testing

- Unit tests: `tests/unit/test_orphan_process_cleaner.py` (mocked `psutil`; included in pre-push `tests/unit` run).

## See also

- Incident write-up: `docs/04-bugs-and-fixes/resolved/2026-04-22-uvicorn-reload-realtime-reply-orphan-dupes.md`
