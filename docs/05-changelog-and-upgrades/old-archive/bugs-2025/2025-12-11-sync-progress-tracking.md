# Sync Progress Bar Tracking Bug

> **Date**: 2025-12-11
> **Status**: ✅ Fixed
> **Component**: `device_manager.py`, `DeviceDetailView.vue`

## Symptoms

- Progress bar on device cards stays at 0% until suddenly jumping to 100%
- Progress bar goes up and down instead of monotonically increasing
- Progress would reach ~20% before conversation scanning, then jump back to ~13% when scanning starts
- Device detail view sync status panel not updating in real-time

Example behavior:

```
User observes:
1. Sync starts → 0%
2. Scrolling to top → jumps to 13%
3. Found customers → jumps to 20%
4. Scanning starts → DROPS back to 13% (wrong!)
5. ... stays at low % ...
6. Suddenly jumps to 100%
```

## Root Cause

### Issue 1: Non-Monotonic Progress

The `_parse_and_update_state` function in `device_manager.py` was setting progress based on log patterns without guarding against progress decreasing:

```python
# BEFORE: Progress could go backwards
if "Scrolling to top" in message:
    state.progress = 10  # Sets to 10%
elif "Found" in message and "customers" in message:
    state.progress = 20  # Sets to 20%
# Later, another "Scrolling to top" could reset it back to 10%!
```

### Issue 2: Pattern Matching During Wrong Phase

Log patterns like "Scrolling to top" could match both during initial navigation AND during conversation scanning (when scrolling within a conversation), causing progress to jump backwards.

### Issue 3: Wrong Progress Distribution

Progress was distributed as:

- 0-25%: Pre-scanning (too much for this phase)
- 25-95%: Conversation scanning

User expectation was:

- 0-10%: Pre-scanning
- 10-100%: Conversation scanning (proportional to customers + sub-steps)

### Issue 4: DeviceDetailView Not Connected to WebSocket

The device detail view wasn't connecting to the sync status WebSocket stream, so progress updates weren't being received in real-time.

## Solution

### 1. Monotonic Progress Enforcement

Added guard to ensure progress only increases:

```python
# device_manager.py
# === IMPORTANT: Only allow progress to increase (monotonic) ===
if new_progress > state.progress:
    state.progress = new_progress
```

### 2. Phase-Based Guards

Added `_in_scanning_phase` flag to prevent pre-scanning patterns from matching during conversation scanning:

```python
# device_manager.py
if not hasattr(state, '_in_scanning_phase'):
    state._in_scanning_phase = False

# Pre-scanning patterns only match when NOT in scanning phase
if not state._in_scanning_phase:
    if "Scrolling to top" in message:
        new_progress = 6
        # ...

# Entering scanning phase sets the flag
if "Syncing customer conversations" in message:
    state._in_scanning_phase = True
    new_progress = 10
```

### 3. Revised Progress Distribution

New progress distribution:

- **0-10%**: Pre-scanning phase
  - 1%: Opening WeCom
  - 2%: Getting kefu info
  - 3%: Kefu found
  - 4%: Setting up database
  - 5%: Navigating to private chats
  - 6%: Scrolling to top
  - 7%: Reached top
  - 8%: Extracting customer list
  - 10%: Found X customers

- **10-100%**: Conversation scanning (90% proportional)
  - Progress = 10 + 90 × (completed_customers + sub_step/5) / total_customers
  - 5 sub-steps per customer: start, extract, test, wait, back
  - Example: 5 customers, on customer 3, sub-step 2:
    - Progress = 10 + 90 × (2 + 2/5) / 5 = 10 + 90 × 0.48 = 53%

### 4. WebSocket Connection in DeviceDetailView

Connected to sync status stream for real-time updates:

```vue
// DeviceDetailView.vue onMounted(() => { load() // Connect to sync status stream for real-time
progress updates if (serial.value) { deviceStore.connectSyncStatusStream(serial.value) } }) //
Handle route changes watch( () => route.params.serial, (newSerial, oldSerial) => { // Disconnect old
stream if (oldSerial) { deviceStore.disconnectSyncStatusStream(oldSerial as string) } // Connect to
new stream if (newSerial) { deviceStore.connectSyncStatusStream(newSerial as string) } load() }, )
onUnmounted(() => { // Cleanup WebSocket connection if (serial.value) {
deviceStore.disconnectSyncStatusStream(serial.value) } })
```

## Files Changed

- `wecom-desktop/backend/services/device_manager.py`
  - Added tracking attributes: `_total_customers`, `_current_customer`, `_customer_sub_step`, `_in_scanning_phase`
  - Implemented phase-based progress tracking with guards
  - Added monotonic progress enforcement
  - Revised progress distribution (0-10% pre-scanning, 10-100% scanning)
  - Added sub-step progress within customer conversations

- `wecom-desktop/src/views/DeviceDetailView.vue`
  - Connected to sync status WebSocket on mount
  - Disconnected WebSocket on unmount and route changes
  - Proper cleanup to prevent memory leaks

## Tests

Manual verification:

```
# Before fix
Progress: 0% → 20% → 13% → 0% → 100% (jumping around)

# After fix
Progress: 0% → 1% → 2% → ... → 10% → 15% → 20% → ... → 100% (smooth, monotonic)
```

## Impact

- Progress bar now shows smooth, monotonically increasing progress
- First 10% is for initialization/navigation phase
- Remaining 90% is proportionally distributed across customers with sub-steps
- Device detail view shows real-time progress updates
- Better user experience with predictable progress indication
