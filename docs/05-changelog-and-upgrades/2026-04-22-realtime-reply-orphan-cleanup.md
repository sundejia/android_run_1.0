# 2026-04-22 — Realtime reply orphan process cleanup

## Summary

Added **two-layer** cleanup so duplicate `realtime_reply_process.py` subprocess trees cannot survive uvicorn `--reload` and compete for the same device:

1. **Per-device** — before starting follow-up for a serial, terminate any matching orphan tree (`RealtimeReplyManager.start_realtime_reply`).
2. **Startup** — on backend worker startup, terminate all orphaned realtime-reply trees (`main.py` lifespan).

## Code

- `wecom-desktop/backend/utils/orphan_process_cleaner.py`
- `wecom-desktop/backend/services/realtime_reply_manager.py` — calls cleaner before spawn
- `wecom-desktop/backend/main.py` — lifespan startup sweep

## Docs

- Resolved incident: `docs/04-bugs-and-fixes/resolved/2026-04-22-uvicorn-reload-realtime-reply-orphan-dupes.md`
- Architecture: `docs/03-impl-and-arch/key-modules/realtime-reply-orphan-cleanup.md`
- Corrected corrupted URLs / script paths in `docs/03-impl-and-arch/key-modules/scan-interval-parameter-flow.md`

## Tests

- `tests/unit/test_orphan_process_cleaner.py`
