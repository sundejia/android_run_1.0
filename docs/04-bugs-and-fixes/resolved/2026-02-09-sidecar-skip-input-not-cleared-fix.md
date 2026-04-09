# Sidecar Skip Input Box Not Cleared Fix

> Date: 2026-02-09
> Status: ✅ Resolved
> Severity: P1 (High)
> Related: Sidecar View, FollowUp Skip

## Summary

Fixed a bug where the input box in Sidecar view would not be cleared after clicking the Skip button, leading to stale messages being retained in the input queue and potentially causing duplicate sends.

## Problem

### Symptoms

1. When user clicked "Skip" button in Sidecar view:
   - The message in the input box remained visible
   - `pendingMessage` state was not cleared
   - `currentQueuedMessage` was not reset
   - `queueMode` flag stayed true

2. This could cause:
   - Old message being displayed for the next customer
   - Double-send if the next customer's message triggered the queue
   - Confusion about which message was queued

### Root Cause

The `skipDeviceSync()` function in `SidecarView.vue` only called the backend API to request skip but did not clean up the local Vue state. The frontend state variables that control the input box display were left in their "message queued" state.

## Solution

### Changes Made

**File Modified:**
- `wecom-desktop/src/views/SidecarView.vue`

**State Cleanup Added:**

```javascript
async function skipDeviceSync(serial: string) {
  // ... existing API call code ...

  if (result.success) {
    // Clear local state to prevent stale message in input box
    // Without this, the old message stays in the input and can cause
    // a double-send when the next user's message is queued
    panel.currentQueuedMessage = null
    panel.pendingMessage = ''
    panel.queueMode = false
    panel.originalAiMessage = null
    clearCountdown(serial)
    console.log('[Skip] Follow-up local state cleared')

    panel.statusMessage = '✅ Skip requested - follow-up will skip this scan'
    console.log('[Skip] Follow-up skip requested successfully')

    // Wait a bit for the backend to handle the skip
    await new Promise((resolve) => setTimeout(resolve, 500))

    // Refresh state to reflect the skip
    await fetchState(serial, false)
    await fetchQueueState(serial)
  }
}
```

### State Variables Cleared

| Variable | Purpose |
|----------|---------|
| `currentQueuedMessage` | The message currently queued for sending |
| `pendingMessage` | Message displayed in input box |
| `queueMode` | Flag indicating we're in queue mode |
| `originalAiMessage` | Original AI-generated message before edits |
| Countdown state | Cleared via `clearCountdown()` |

### Additional Improvements

- Added 500ms delay after skip to allow backend processing
- Added explicit state refresh (`fetchState` and `fetchQueueState`) after skip
- This ensures the UI reflects the true backend state

## Testing

- Manual testing with Skip button confirmed input is now cleared
- Verified that next customer's message displays correctly after skip
- Confirmed no stale messages remain in the queue state

## Related Issues

- Related to duplicate send issues (ensures state is clean between customers)
- Connects to Sidecar timeout/duplicate send investigation (separate issue)

## References

- Code: `wecom-desktop/src/views/SidecarView.vue:1139-1157`
- Related: `docs/04-bugs-and-fixes/active/2026-02-09-sidecar-timeout-duplicate-send.md`
