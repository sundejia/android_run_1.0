# Bug Report: Sidecar shows “Unknown” for 客服 despite visible profile info

## Executive Summary

- Issue: The WeCom Desktop sidecar fails to display the 客服 (agent) name, showing “Unknown” even when the device’s main Messages/profile page clearly shows the agent (e.g., `wgz小号`, `302实验室`, “Not verified” badge).
- Impact: Sidecar context is incomplete across all conversations on the mirrored device; downstream features that rely on knowing the current agent (e.g., logging, auditing) cannot show correct metadata.
- Status: Open (not yet resolved).

## Timeline

- 2025-12-07: Sidecar feature introduced and initial kefu caching added (from non-conversation views).
- 2025-12-07: Detection broadened (wider X/Y bounds) and cache retains last found kefu; issue persists — sidecar still shows “Unknown”.

## Symptoms and Impact

- On the device’s Messages/profile view (left drawer open), the UI shows `wgz小号` and department `302实验室` with a “Not verified” badge.
- Sidecar simultaneously shows “Conversation detected” but lists 客服: “Unknown”.
- Occurs both on the Messages list and inside conversations; sidecar never picks up the visible kefu info.
- User-facing impact: Missing agent attribution in sidecar; reduces trust and usefulness of the sidecar pane during mirrored sessions.

## Environment

- App: WeCom Desktop (Electron + Vue) with sidecar window (scrcpy mirror).
- OS: macOS (dev environment), mirrored Android device via scrcpy.
- Branch/state: Local dev with sidecar feature; recent commits attempting kefu extraction.

## Reproduction Steps

1. Start mirroring a device and open the sidecar window.
2. From the mirrored device, open the main Messages/profile view (left drawer) where agent info appears at the top.
3. Observe sidecar → 客服 remains “Unknown” instead of the visible agent name.

## Expected vs Actual

- Expected: Sidecar should show the agent from the main/profile view and keep it cached across conversations.
- Actual: Sidecar displays “Unknown”.

## Evidence

- Screenshot: Side-by-side view shows profile header (`wgz小号`, `302实验室`, “Not verified”) while sidecar lists 客服: “Unknown”.

## Root Cause Analysis (current understanding)

- `extract_kefu_info_from_tree` relies on positional heuristics for left-panel text. The current bounds/filters still miss the agent text on the profile view. The accessibility nodes for the header may fall outside the assumed panel/coordinates or be structured differently than expected.
- Sidecar only captures kefu from UI parsing; no fallback to DB or prior sync metadata.

## Attempted Solutions (unsuccessful)

1. Cache kefu only when not in a conversation to avoid chat text contamination.
2. Widened search bounds (X/Y) and allowed caching even when in a conversation if cache empty.  
   Result: Still “Unknown” in sidecar.

## Next Steps / Proposed Fixes

- Capture and inspect the accessibility tree on the profile view; adjust `extract_kefu_info_from_tree` to target resourceIds/text patterns for the header (e.g., name, department, verification badge) instead of positional-only heuristics.
- Add debug logging/dump for kefu extraction when sidecar state is fetched to validate candidates.
- Consider a fallback: read kefu from synced DB or a dedicated `get_kefu_name()` call on sidecar startup, stored per-device.
- Add an automated test (unit or snapshot of parsed tree) for kefu extraction from the main Messages/profile layout to prevent regressions.

## Status

- Open / Investigating
