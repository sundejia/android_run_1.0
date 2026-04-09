# Bug Report: Sidecar queue endpoint returned constant 404s

## Executive Summary

- Issue: The renderer repeatedly polled `GE../03-impl-and-arch/<serial>/queue` and the backend returned 404, spamming logs and cluttering debugging output.
- Impact: Noise in backend logs during every sidecar session; harder to monitor real errors while mirroring/automating devices.
- Status: Resolved (placeholder queue endpoint added).

## Timeline

- 2025-12-08: Observed continuous 404s for `GE../03-impl-and-arch/AMFU6R1622014533/queue` while sidecar state/send endpoints were working.
- 2025-12-08: Added queue response models and a stub `GE../03-impl-and-arch/{serial}/queue` that returns an empty queue with 200 to quiet the noise.

## Symptoms and Impact

- Backend log spam: `INFO: 127.0.0.1:62111 - "GE../03-impl-and-arch/AMFU6R1622014533/queue HTTP/1.1" 404 Not Found` repeating every poll.
- Functional impact minimal (state/send worked), but the noise obscured other issues and degraded observability during live automation.

## Environment

- App: WeCom Desktop (Electron/Vue renderer + FastAPI backend).
- Backend: Uvicorn dev server on macOS (local).
- Device: Android device `AMFU6R1622014533` connected via ADB/scrcpy.

## Reproduction Steps

1. Start backend (`uvicorn main:app --reload --port 8765`) and renderer/electron (`npm start`).
2. Open sidecar for a connected device.
3. Watch backend logs: repeated `GE../03-impl-and-arch/<serial>/queue` 404 responses.

## Expected vs Actual

- Expected: Sidecar queue polling should return 200 with a (possibly empty) payload.
- Actual: Endpoint did not exist → FastAPI returned 404 for every poll.

## Evidence

- Logs (excerpt): `127.0.0.1:62111 - "GE../03-impl-and-arch/AMFU6R1622014533/queue HTTP/1.1" 404 Not Found` repeated alongside normal `/state` and `/send` traffic.

## Root Cause Analysis

- The renderer polls a../03-impl-and-arch/{serial}/queue` endpoint for queued actions/messages.
- Backend router `sidecar.py` only exposed `/state` and `/send`; no `/queue` route existed, so every poll hit 404.

## Attempted / Alternative Fixes

- None prior; issue traced directly to missing route.

## Successful Fix

- Added queue DTOs and a stub endpoint:
  - New models: `SidecarQueueItem`, `SidecarQueueResponse` (empty payload defaults).
  - New route: `GE../03-impl-and-arch/{serial}/queue` returns `SidecarQueueResponse()` after ensuring session creation.
- File: `wecom-desktop/backend/routers/sidecar.py`.
- Behavior: Returns HTTP 200 with `{items: [], has_items: false, detail: "Queue is empty"}` so polling stops emitting 404s. Future queue behavior can build on this shape.

## Verification

- Lint: `backend/routers/sidecar.py` reports no lint issues.
- Manual runtime verification still needed: restart backend/electron and confirm../03-impl-and-arch/<serial>/queue` returns 200 with empty payload and logs stay clean.

## Preventive Measures

- Keep frontend/renderer polling contracts documented; add placeholder endpoints when interfaces are defined but not yet implemented.
- Consider lightweight contract tests to assert required sidecar routes exist (`/state`, `/queue`, `/send`).
- Add backend tests for sidecar router to ensure all renderer endpoints respond 200/appropriate bodies.

## Status

- Resolved (awaiting manual runtime verification in next dev run).
