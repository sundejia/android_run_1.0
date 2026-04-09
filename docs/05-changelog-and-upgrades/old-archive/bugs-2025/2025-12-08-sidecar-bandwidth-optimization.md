# Optimization: Sidecar bandwidth and polling reduction

## Executive Summary

- Issue: Sidecar polling was too frequent (1s) and extracted unnecessary data (recent messages), causing excessive ADB traffic and slowing down sync operations.
- Impact: Full sync with sidecar open was slower than without; sidecar state requests spammed logs and competed with sync automation for device access.
- Status: Resolved (removed recent messages extraction, made poll interval configurable, added sync-state-triggered refresh).

## Timeline

- 2025-12-08: Observed continuous `GE../03-impl-and-arch/<serial>/state` and `/queue` logs every second, with "Extracting conversation messages from UI tree..." spam.
- 2025-12-08: Implemented optimizations to reduce polling frequency and remove unnecessary message extraction.

## Symptoms and Impact

- Backend logs flooded with state/queue polling every second per open sidecar panel.
- `extract_conversation_messages()` called on every poll even though recent messages weren't needed for send functionality.
- Sync operations ran slower when sidecar was open due to ADB contention.
- Users reported "longer and longer wait in queue" for sidecar sends during full sync.

## Environment

- App: WeCom Desktop (Electron/Vue renderer, FastAPI backend).
- OS: macOS (dev).
- Devices: Multiple Android devices via ADB.

## Root Cause Analysis

1. **Excessive polling frequency**: Sidecar polled state every 1 second, but real-time message display wasn't actually needed.
2. **Unnecessary message extraction**: `snapshot()` called `extract_conversation_messages()` on every poll to populate `recent_messages`, which was expensive and unused for the core send functionality.
3. **No event-driven refresh**: Sidecar didn't refresh based on sync state changes, so frequent polling was the only way to stay updated.

## Successful Fix

### Frontend Changes (`wecom-desktop/src/views/SidecarView.vue`)

- Removed "Recent messages" UI section entirely (not needed for send workflow).
- Removed `message_count` display from conversation card.
- Made poll interval configurable via settings (default 10s, range 0-20s).
- Added watcher to restart polling when interval setting changes.
- Added watcher to trigger immediate refresh when sync status changes for open panels.

### TypeScript Types (`wecom-desktop/src/services/api.ts`)

- Removed `SidecarMessage` interface.
- Simplified `SidecarConversation` to only contain `contact_name` and `channel`.

### Backend Changes (`wecom-desktop/backend/routers/sidecar.py`)

- Removed `SidecarMessageModel` class.
- Simplified `ConversationModel` (removed `message_count`, `recent_messages`).
- Removed `_simplify_messages()` method.
- Updated `_extract_basic_state()` to skip `extract_conversation_messages()` call.
- Updated `snapshot()` to work with simplified state.

### Settings (`wecom-desktop/src/stores/settings.ts`, `SettingsView.vue`)

- Added `sidecarPollInterval` setting (0 = disabled, 1-20 seconds, default 10s).
- Added UI slider and input in Settings > Sidecar Settings.

## Verification

- TypeScript compiles without errors.
- Backend router loads successfully.
- Poll interval is now 10x slower by default (10s vs 1s).
- Message extraction is completely skipped, removing the most expensive operation from polling.
- Sidecar still refreshes immediately on sync state changes for responsive UX.

## Preserved Functionality

- Send textarea and all send functionality (manual, countdown, queue-based).
- Kefu info display.
- Conversation header (contact name, channel).
- Tree hash display.
- Queue status banner and controls.
- All queue polling for sync coordination.

## Performance Benefit

- ~10x reduction in state polling frequency (1s → 10s default).
- Eliminated expensive `extract_conversation_messages()` call from every poll.
- Reduced ADB contention with sync automation.
- Event-driven refresh on sync state changes maintains responsiveness without constant polling.
