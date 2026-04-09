# Bug Report: Logs Clear created “[object PointerEvent]” tabs

## Executive Summary
- Issue: Clicking the main “Clear” button in Device Logs when multiple devices were connected spawned phantom tabs labeled `[object PointerEvent]`.
- Impact: UI clutter and confusion; repeated clicks kept adding bogus tabs.
- Resolution: Sanitize Clear/Export handlers to ignore DOM events as serials, filter device lists to strings only, and add a “clear all logs + reset layout” action.
- Status: Fixed (UI retest recommended with two devices).

## Timeline
- 2025-12-07: Phantom tabs observed after pressing Clear with two devices connected.
- 2025-12-07: Root cause identified and fixed in `LogsView.vue`.

## Symptoms and Impact
- Steps: Open Device Logs with two devices streaming; click the header “🗑️ Clear”.
- Result: A new tab named `[object PointerEvent]` appeared; additional clicks added more phantom tabs.
- User-facing impact: Log viewer polluted with non-existent devices; difficult to navigate real logs.

## Environment
- App: WeCom Desktop (Electron + Vue).
- View: `Device Logs` at `http://localhost:5173/logs`.
- Devices: Two connected (any serials).

## Root Cause Analysis
- The Clear/Export handlers treated the first argument as a serial; when invoked from the header button, Vue passed the click `PointerEvent`. That event object became a Map key in the log store, surfacing as `[object PointerEvent]` tabs.
- `availableDevices` combined device serials with `devicesWithLogs` without filtering non-string keys, letting the event-derived entry render.

## Fix Implemented
- Gate handler inputs to accept only string serials; ignore events.
- Filter `devicesWithLogs` to strings before building available devices.
- Add `clearAllLogs` to wipe all device logs, close panels, and reset the empty-state message; bind header Clear to this new action.

## Verification
- Manual: With two devices, press header “Clear”; no phantom tabs appear, panels reset to empty state.
- Note: Re-run after future log-store changes.

## References
- Changes in `wecom-desktop/src/views/LogsView.vue`.

