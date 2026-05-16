# Session changelog — 2026-05-16

## Fixed

- **Device-dashboard remote commands delayed ~10s** — `HeartbeatClient` now runs a dedicated WebSocket reader so `device_start` / `device_stop` / etc. execute as soon as the dashboard pushes them, instead of waiting for the next heartbeat tick (`interval_s=10`).

## Docs

- [04-bugs-and-fixes/resolved/2026-05-16-dashboard-remote-command-latency.md](../04-bugs-and-fixes/resolved/2026-05-16-dashboard-remote-command-latency.md)
- [implementation/2026-05-16-dashboard-command-latency-fix.md](../implementation/2026-05-16-dashboard-command-latency-fix.md)

## Tests

- `tests/unit/test_heartbeat_client_commands.py` — reader dispatches `command` without blocking on writer interval.
