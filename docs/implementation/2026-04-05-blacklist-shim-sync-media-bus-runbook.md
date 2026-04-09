# Blacklist shim, sync media bus wiring, and Windows runbook (2026-04-05)

## Summary

This note records follow-up work that landed together: consolidating blacklist logic behind the shared automation package, documenting sync/blacklist behavior, tightening media auto-actions integration tests, and hardening Android UI detection for post–group-create confirmation.

## Backend blacklist module

`wecom-desktop/backend/services/blacklist_service.py` is now a **compatibility shim** only. All behavior lives in `src/wecom_automation/services/blacklist_service.py` (`BlacklistChecker`, `BlacklistWriter`). The desktop class `BlacklistService` subclasses `BlacklistWriter` and exposes the same class methods routers and legacy code expect (`load_cache`, `is_blacklisted`, `invalidate_cache`).

Routers that already import from `wecom_automation.services.blacklist_service` are unchanged; the shim avoids a second divergent implementation in the backend tree.

## Sync factory and media event bus

`create_sync_orchestrator` / `create_customer_syncer` pass the **device conversation DB** as `db_path` into `build_media_event_bus`, while **settings and side-effect DB paths** resolve to the control DB from `get_default_db_path()`. Unit coverage: `tests/unit/test_sync_factory.py`.

## Android: group-create confirmation and `get_current_screen`

`confirm_group_creation` polls until `get_current_screen()` returns `chat`. External / Chinese group titles (for example `群聊(3)`) and `ListView`/`RecyclerView` message areas without `chat` in `resourceId` previously caused false `other`, so `WeComService._is_chat_screen` was extended to:

- Treat `ListView` / `RecyclerView` nodes in the flat element list as a message list.
- Recognize Chinese group title patterns on clickable nodes.
- Use a lower Y threshold (top ≥ 800) for “bottom” `EditText` so shorter viewports still match.
- Accept `has_group_chat_hint` + `has_input_field` + `has_message_list` as chat when back-button heuristics miss.

**Bugfix:** `_is_chat_screen` previously did `has_message_list = has_message_list or check_tree_for_chat(tree)`. The walker sets `has_message_list` via `nonlocal` but usually returns `False`, so the assignment reset the flag to `False`. The tree is now walked only for side effects (no `or` on the return value).

Regression tests: `tests/unit/test_wecom_service_screen_detection.py`.

### Real-device follow-up (2026-04-05 PM)

On the live device, the remaining failure was **not** the final chat-screen heuristic itself. A real `MediaEventBus(..., wecom_service=WeComService)` run showed the Android flow could:

- enter the customer chat
- open chat info
- add the configured member
- tap the confirm/create-group button
- actually land in the external group chat

But `confirm_group_creation()` still returned `False` because its polling window was only:

- initial wait: `max(post_confirm_wait_seconds, tap_delay)`
- plus about **3 seconds** of extra polling

Observed behavior on the external-group screen:

- the first 1-2 polls returned `other` / `unknown`
- a few seconds later the exact same screen was detected as `chat`

The fix was to keep the same screen-detection semantics and only extend the confirmation polling budget in `WeComService.confirm_group_creation()` so slower external-group transitions still complete and write back success.

## Documentation corrections

- **`docs/03-impl-and-arch/key-modules/sync-blacklist-selection-*.md`** — Aligned with the current blacklist model (scan index + `is_blacklisted`, default allow for new scans, Phase 1.5 whitelist).
- **`wecom-desktop/README.md`** — Removed references to a non-existent `backend/requirements.txt`; documented installing the Python project from the repo root with `uv` and running the API with `uv run`.

## Windows / DroidRun operational notes

- Prefer **`uv sync --extra dev`** at the repo root, then run the backend from `wecom-desktop/backend` with `uv run uvicorn main:app --reload --port 8765`.
- Vite may listen on **`localhost` (IPv6)**; if the browser shows connection issues, try `127.0.0.1:5173` or the exact host printed in the terminal.
- If Portal reports **accessibility unavailable** after other tools used `uiautomator` dumps, re-enable DroidRun Portal’s accessibility service (see `docs/04-bugs-and-fixes/fixed/BUG-2025-12-13-droidrun-portal-connection-failure.md`).
- Blacklist HTTP API is under **`/api/blacklist/...`** (FastAPI `wecom-desktop/backend/routers/blacklist.py`). Customers blocked by blacklist are skipped in realtime follow-up until removed or toggled off.

## Related docs

- [Media Auto-Actions](../features/media-auto-actions.md)
- [Android group invite workflow](2026-04-04-android-group-invite-workflow.md)
- [Device user / blacklist system](../03-impl-and-arch/key-modules/sync-blacklist-selection-feature.md)
