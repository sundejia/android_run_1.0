# Bug Report: Mirror button does nothing

## Executive Summary
- Issue: Clicking **🖥️ Mirror** produced no window when the app was launched without a shell PATH or without the Electron bridge.
- Impact: Users could not start mirroring; no feedback was shown.
- Status: Fixed.

## Symptoms
- Mirror button click results in no action or window.
- Occurs when Electron is started from Finder/GUI (PATH missing) or when running the renderer in a plain browser where `window.electronAPI` is unavailable.

## Root Cause
- The scrcpy binary lookup only relied on PATH/bundled locations; GUI launches lacked PATH, so `scrcpy` could not be spawned.
- The renderer left the Mirror button enabled even when the Electron mirror bridge was unavailable, so clicks were ignored silently.

## Fix
- Mirror manager now:
  - Honors `SCRCPY_PATH` if set and logs if invalid.
  - Falls back to common scrcpy locations (`/opt/homebrew/bin/scrcpy`, `/usr/local/bin/scrcpy`, `/usr/bin/scrcpy`, Windows Program Files) when PATH is missing.
- Renderer now:
  - Detects `window.electronAPI.mirror` availability and disables the Mirror button with a tooltip when unavailable.
  - Logs mirror start/stop failures and keeps mirror status in sync.

## Verification
- Manual: Launch app from a GUI session without shell PATH, ensure scrcpy is found via common path or `SCRCPY_PATH`, click Mirror → window opens. In browser-only renderer, Mirror button is disabled with tooltip.









