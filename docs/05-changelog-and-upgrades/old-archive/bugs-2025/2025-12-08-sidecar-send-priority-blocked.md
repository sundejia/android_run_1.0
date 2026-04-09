# Bug Report: Sidecar message sending blocked by polling/state parsing

## Executive Summary

- Issue: Sidecar message send requests were blocked/delayed by concurrent state/queue polling and UI parsing, causing sends to wait behind background work.
- Impact: Outbound replies stalled; operators saw “Extracting conversation messages from UI tree…” spam and sends could be slow to launch.
- Status: Resolved (prioritized send path, cached state during sends, offloaded parsing).
- Fix: In `backend/routers/sidecar.py`, added a send-in-flight flag, cached state return for polls during sends, narrowed the lock to ADB I/O, and moved heavy parsing to a thread. Added regression test `test_sidecar_priority.py`.

## Timeline

- 2025-12-08: Observed logs showing../03-impl-and-arch/{serial}/state`and`/queue` polling while send stalled; UI parsing logs interleaved.
- 2025-12-08: Implemented priority handling and caching; added unit test to assert non-blocking snapshots during send.

## Symptoms and Impact

- During sidecar usage, send requests could be delayed while background polls held the session lock and parsed UI trees.
- Logs repeatedly showed:
  - `INFO: 127.0.0.1:53588 - "GE../03-impl-and-arch/AMFU6R1622014533/state HTTP/1.1" 200 OK`
  - `INFO: 127.0.0.1:53588 - "GE../03-impl-and-arch/AMFU6R1622014533/queue HTTP/1.1" 200 OK`
  - `Extracting conversation messages from UI tree...`
  - `Extracted 7 messages from conversation`
- User impact: Reply sends could feel unresponsive; background polling work was effectively higher priority than the interactive send.

## Environment

- App: WeCom Desktop (Electron/Vue renderer, FastAPI backend sidecar).
- OS: macOS (dev).
- Device: Android device `AMFU6R1622014533` via ADB/scrcpy.

## Reproduction Steps

1. Start backend and sidecar polling (default 1s interval for `/state`, `/queue`).
2. From sidecar, trigger a message send while polling continues.
3. Observe backend logs: UI parsing runs while send waits; send start is delayed.

## Expected vs Actual

- Expected: Message send should start immediately and not be blocked by background polling/state parsing.
- Actual: Send competed for the same lock as polling + parsing, so send could be delayed until parsing finished.

## Root Cause Analysis

- `SidecarSession.snapshot()` held the shared lock across both ADB fetch and CPU-heavy parsing (`extract_conversation_messages`), letting frequent polls monopolize the lock.
- `send_message()` shared the same lock, so sends waited behind snapshot work.
- No cached state existed to serve polls while a send was in progress; every poll repeated full parsing.

## Attempted / Related Work

- Prior work added a `/queue` stub to stop 404 spam, but it did not address priority contention; sends still waited behind snapshot parsing.

## Successful Fix

- Added `_send_idle` event and `_last_state` cache in `SidecarSession`:
  - When a send is in progress, snapshots return the cached state immediately (or wait for send to finish) instead of taking the lock.
  - Send path clears/sets `_send_idle` around its critical section.
- Reduced lock scope: lock only around ADB I/O (`get_ui_state`), then release before parsing.
- Offloaded CPU-heavy parsing (`extract_conversation_messages`, header info, kefu extraction) to `asyncio.to_thread` to avoid blocking the event loop.
- Cached the last successful state to serve quick responses during active sends.

## Verification

- Added regression test `wecom-desktop/backend/tests/test_sidecar_priority.py` to assert snapshots return cached state within <20ms while a send is running.
- Manual expectation: Sends should start immediately even under active polling; state responses during send may serve cached data but no longer block send.

## Prevention / Follow-ups

- Keep snapshot parsing off the event loop for other heavy paths.
- Consider rate-limiting state polls if future contention reappears.
- Add integration coverage for concurrent send + polling once device harness is available.
