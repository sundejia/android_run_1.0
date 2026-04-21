# Sidecar / Logs Panel: Log stream disconnect after long runtime

> Date: 2026-04-21  
> Status: Resolved  
> Area: `wecom-desktop` (Sidecar, Logs view, backend log router)

## Summary

After the desktop app ran for a long time, the Sidecar (and other) log panels showed **"Log stream disconnected"** and logs stopped updating until the user refreshed the UI or toggled the log stream. The root cause was missing **client-side auto-reconnect**, a **one-way** server "keepalive" that did not exercise the full path, and **idle TCP / proxy** timeouts. Follow-up work added **application-level ping/pong**, **uvicorn WebSocket control-frame pings**, **dead callback pruning** on broadcast failure, and **regression tests**.

## Root causes (condensed)

1. **No reconnect on `onclose`**: `useLogStore` removed the socket and appended a warning line but never opened a new WebSocket.
2. **Server-only text `ping`**: The backend sent `ping` without the client sending anything; NATs and half-open connections could still drop the socket silently for long periods.
3. **`ping`/`pong` leaked into the UI**: Plain-text frames were parsed as logs, so users could see spurious `ping` lines every 30 seconds (before the refactor).
4. **Broadcast callbacks never pruned**: Failed `send_json` in per-socket callbacks was swallowed; dead callbacks stayed in `DeviceManager` / `RealtimeReplyManager` sets.

## Implementation

### Frontend — `wecom-desktop/src/stores/logs.ts`

- Exponential backoff reconnect (cap 30 s, max 20 attempts) on **passive** close only.
- `intentionallyClosed` flag so `disconnectLogStream()` / user toggles do not trigger reconnect storms.
- Client sends `ping` every 25 s; treats received `ping`/`pong` as heartbeat (updates `lastPongAt`, **not** shown in the log list).
- Watchdog closes the socket if no pong-like activity for 35 s, which triggers the reconnect path.

### Backend — `wecom-desktop/backend/routers/logs.py`

- Client-driven contract: inbound `ping` → outbound `pong`; other inbound text ignored.
- 90 s `receive_text` timeout as a **backstop** only (aligned with client heartbeat); on timeout, one `send_text("ping")` probe, then break if write fails.
- `broadcast_log` / `broadcast_sync_status`: on send failure, remove socket from the set and `await ws.close()`.
- `websocket_sync_status` uses the same receive/ping/pong pattern as log stream.
- INFO log on disconnect: `websocket_logs closed client=… reason=…`.

### Uvicorn — `wecom-desktop/backend/main.py` and `package.json`

- `ws_ping_interval=20`, `ws_ping_timeout=30` in `uvicorn.run` for `python main.py`.
- `npm run backend` passes `--ws-ping-interval 20 --ws-ping-timeout 30`.

### Services — callback hygiene

- `device_manager.py` and `realtime_reply_manager.py`: `_broadcast_log` removes callbacks that raise on `await callback(...)`.

## Tests

| Location | Role |
| -------- | ---- |
| `wecom-desktop/src/stores/logs.spec.ts` | Pinia store: no ping/pong in UI, reconnect, no reconnect on intentional close, heartbeat sends `ping` |
| `wecom-desktop/backend/tests/test_logs_ws.py` | FastAPI: ping/pong, short idle, unknown text ignored, callback unregistered on disconnect |

Run from repo root (examples):

```bash
cd wecom-desktop && npx vitest run src/stores/logs.spec.ts
uv run --extra dev python -m pytest wecom-desktop/backend/tests/test_logs_ws.py -v
```

## Related documentation

- `docs/03-impl-and-arch/key-modules/logging-system-architecture.md` — WebSocket reliability section
- `docs/03-impl-and-arch/key-modules/current-log-structure-analysis.md` — protocol and client behavior
- `docs/03-impl-and-arch/key-modules/sidecar_websocket_implementation.md` — endpoint table corrected (unified `/ws/logs/{serial}`)

## Optional follow-up (not in this fix)

- Subprocess restart paths: ensure log callbacks are re-registered if the realtime worker process is replaced (separate reliability topic).
