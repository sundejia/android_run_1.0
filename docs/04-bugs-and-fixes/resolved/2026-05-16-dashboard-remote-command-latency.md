# Device-dashboard remote commands delayed ~10s on WeCom client

> Date: 2026-05-16  
> Status: Resolved  
> Area: `wecom-desktop` — `HeartbeatClient` ↔ device-dashboard `/ws/heartbeat`

## Summary

When an operator clicked **Start / Stop / Pause** for a per-device action in the **device-dashboard**, the WeCom desktop client took **~10–15 seconds** before `RealtimeReplyManager` actually started or stopped the device process. The dashboard REST API returned quickly, but the Android side felt unresponsive.

## Root cause

`HeartbeatClient._connect_and_heartbeat()` used a **half-duplex** loop: it only called `ws.recv()` **after** sending a heartbeat or draining the event queue. Between sends the client blocked on `asyncio.wait_for(self._event_queue.get(), timeout=self._interval)` with **`interval_s=10`**, so incoming `command` messages from the dashboard sat in the WebSocket buffer until the next heartbeat tick.

The dashboard server already pushes commands immediately over the open WebSocket; the bottleneck was entirely on the WeCom client read path.

## Fix

**File:** `wecom-desktop/backend/services/heartbeat_client.py`

- Split the connection into **`_reader_loop`** (continuous `ws.recv()`, dispatch `command` via `asyncio.create_task`) and **`_writer_loop`** (periodic heartbeats + event queue drain).
- Introduce **`safe_send`** with `asyncio.Lock` so concurrent `command_result` replies and heartbeat writes do not violate `websockets` send semantics.
- Run reader and writer under `asyncio.wait(..., return_when=FIRST_EXCEPTION)` so disconnects still trigger the existing reconnect/backoff in `_run()`.

Commands are now handled as soon as they arrive (latency ≈ network + `start_realtime_reply` work), not on the next 10s heartbeat boundary.

## Verification

1. Restart the WeCom desktop backend so the new client code loads.
2. From device-dashboard, click **Start** on a device.
3. WeCom logs should show `remote_command_received: action=device_start` **immediately**, not after the next heartbeat interval.

## Related

- Remote control feature (initial): commit `e6cef00` — `feat: remote device control via dashboard WebSocket commands`
- Implementation note: [../../implementation/2026-05-16-dashboard-command-latency-fix.md](../../implementation/2026-05-16-dashboard-command-latency-fix.md)
