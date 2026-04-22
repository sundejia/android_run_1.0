# Resolved: Uvicorn reload left duplicate realtime-reply processes (2026-04-22)

> **Status:** Fixed in code (2026-04-22)  
> **Severity:** High (multi-device ADB contention, alternating “frozen” log panels, `[Errno 22] Invalid argument` on swipe)

## Symptoms

- With two phones connected, only one device’s Message Assistant log panel appeared to refresh; the other stayed static or “stuck”.
- Behaviour could **flip**: left refreshes while right freezes, then later the opposite — consistent with **two independent Python trees driving the same serial**, not a single hung process.
- Backend file `logs/<hostname>-<serial>.log` showed **two unrelated `Scan #` counters interleaved** for the **same device** (impossible from one process).
- Errors such as `Swipe failed: [Errno 22] Invalid argument` during `switch_to_private_chats` / scroll-to-top.

## Root cause

`RealtimeReplyManager` spawns per-device trees via:

- `subprocess.Popen(..., shell=True, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)` on Windows
- Typical shape: `cmd.exe → uv.exe → python.exe → python.exe` running  
  `wecom-desktop/backend/scripts/realtime_reply_process.py --serial …`

When the backend runs as `uvicorn main:app --reload …`, **file changes restart the uvicorn worker process**. Those child trees **do not die with the worker** (separate job group / shell wrapper). After reload:

1. The new worker loads a **fresh** `RealtimeReplyManager` singleton with an **empty** `_processes` dict.
2. The guard `if serial in self._processes` therefore **does not see** the old trees.
3. Starting follow-up again (or auto-restart) launches a **second** tree for the same `--serial`.
4. Both trees issue ADB/DroidRun gestures to the same phone → conflicts, flaky swipes, and alternating log throughput per panel depending on WebSocket coupling and timing.

## Fix (two layers)

| Layer             | Where                                       | Behaviour                                                                                                                                                                  |
| ----------------- | ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1 — Pre-start** | `RealtimeReplyManager.start_realtime_reply` | Before spawning, call `kill_realtime_reply_orphans(serial)` to terminate any leftover tree for that serial (runs in `asyncio.to_thread` so the event loop is not blocked). |
| **2 — Startup**   | `main.py` lifespan                          | On worker startup, call `kill_realtime_reply_orphans()` with **no** serial to remove **all** orphaned `realtime_reply_process.py` trees left by the previous worker.       |

Implementation: `wecom-desktop/backend/utils/orphan_process_cleaner.py` (uses `psutil`; matches command lines containing `realtime_reply_process.py`, deduplicates process trees by roots, terminates recursively).

## Operational notes

- After deploying this fix, **restart the backend once** so Layer 2 runs and clears any existing duplicates.
- For day-to-day dev, **prefer running uvicorn without `--reload` on machines that drive real devices**, or accept that `--reload` will intentionally restart the worker — Layer 2 now cleans orphans on each reload.
- Manual verification: task list should show **at most one** `cmd.exe /c uv run … realtime_reply_process.py --serial <serial>` per device.

## Related files

- `wecom-desktop/backend/utils/orphan_process_cleaner.py`
- `wecom-desktop/backend/services/realtime_reply_manager.py`
- `wecom-desktop/backend/main.py`
- Design note: `docs/03-impl-and-arch/key-modules/realtime-reply-orphan-cleanup.md`
