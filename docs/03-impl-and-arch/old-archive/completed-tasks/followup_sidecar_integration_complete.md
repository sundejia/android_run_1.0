# FollowUp Sidecar Integration - Complete ✅

> Implementation Date: 2026-01-20
> Status: ✅ **Complete**

## Summary

Successfully integrated FollowUp with the Sidecar queue system, enabling manual review and editing of AI-generated replies before sending. FollowUp messages now flow through the same queue as Sync messages, with source tracking for better visibility.

## What Was Implemented

### Backend Changes

#### 1. Sidecar Queue - Source Field (`sidecar.py`)

**Status**: ✅ Already implemented

The `QueuedMessageModel` already has a `source` field to track message origin:

```python
class QueuedMessageModel(BaseModel):
    id: str
    serial: str
    customerName: str
    channel: Optional[str] = None
    message: str
    timestamp: float
    status: MessageStatus = MessageStatus.PENDING
    error: Optional[str] = None
    source: str = "manual"  # "manual" | "sync" | "followup"
```

#### 2. FollowUp Settings - Sidecar Toggle (`followup.py`)

**Modified**: Added `sendViaSidecar` field

**Updated API Model**:

```python
class FollowUpSettings(BaseModel):
    enabled: bool = True
    scanInterval: int = 60
    maxFollowUps: int = 3
    initialDelay: int = 120
    subsequentDelay: int = 120
    useExponentialBackoff: bool = False
    backoffMultiplier: float = 2.0
    enableOperatingHours: bool = True
    startHour: int = 10
    endHour: int = 22
    useAIReply: bool = False
    enableInstantResponse: bool = False
    sendViaSidecar: bool = True  # NEW: Send via Sidecar for manual review
```

**Updated GET/ `/settings` endpoint**:

- Returns `sendViaSidecar` field

**Updated POST `/settings` endpoint**:

- Accepts and saves `sendViaSidecar` field
- Stores in unified settings service

#### 3. FollowUp Settings (`settings.py`)

**Status**: ✅ Already implemented

The `FollowUpSettings` dataclass already includes:

```python
send_via_sidecar: bool = True
```

With proper serialization in `to_dict()` and `from_dict()` methods.

#### 4. Sidecar Queue Logic (`response_detector.py`)

**Added**: `_send_reply_wrapper()` method

**New Method**:

```python
async def _send_reply_wrapper(
    self,
    wecom_service: Any,
    serial: str,
    user_name: str,
    user_channel: Optional[str],
    message: str,
    sidecar_client: Optional[Any] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Send reply via Sidecar queue (with source='followup') or direct send

    - If sidecar_client provided: Add to queue for manual review
    - If sidecar_client None or fails: Direct send (fallback)
    """
    if sidecar_client:
        # Add to Sidecar queue with source='followup'
        url = f"http://localhost:8765/a../03-impl-and-arch/{serial}/queue/add"
        payload = {
            "customerName": user_name,
            "channel": user_channel,
            "message": message,
            "source": "followup"
        }
        # POST to queue API...
    else:
        # Direct send (no human review)
        # Use wecom_service.send_message()...
```

**Key Features**:

- Sends with `source: "followup"` to Sidecar queue
- Automatic fallback to direct send if queue fails
- Returns `(success, sent_text)` tuple
- Proper error handling and logging

### Frontend Changes

#### 5. API Type Definitions (`api.ts`)

**Modified**: `QueuedMessage` and `AddMessageRequest` interfaces

**Updated Types**:

```typescript
export interface QueuedMessage {
  id: string
  serial: string
  customerName: string
  channel: string | null
  message: string
  timestamp: number
  status: MessageStatus
  error?: string
  source: 'manual' | 'sync' | 'followup' // NEW: Message source
}

export interface AddMessageRequest {
  customerName: string
  channel?: string | null
  message: string
  source?: 'manual' | 'sync' | 'followup' // NEW: Message source
}
```

#### 6. SidecarView - Source Badges (`SidecarView.vue`)

**Modified**: Added source badges in countdown display

**Updated statusMessage generation**:

```typescript
// Add source to status message
const sourceLabel =
  readyMessage.source === 'followup'
    ? 'FollowUp'
    : readyMessage.source === 'sync'
      ? 'Sync'
      : 'Manual'
panel.statusMessage = `${sourceLabel} message for ${readyMessage.customerName}...`
```

**Added visual badges in template**:

```vue
<div class="flex items-center gap-2">
  <!-- Source badge -->
  <span
    v-if="sidecars[serial]?.currentQueuedMessage?.source === 'followup'"
    class="px-2 py-0.5 text-xs font-medium rounded bg-blue-500/20 text-blue-400 border border-blue-500/30"
  >
    🔄 FOLLOWUP
  </span>
  <span
    v-else-if="sidecars[serial]?.currentQueuedMessage?.source === 'sync'"
    class="px-2 py-0.5 text-xs font-medium rounded bg-green-500/20 text-green-400 border border-green-500/30"
  >
    🔃 SYNC
  </span>
  <span>{{ sidecars[serial]?.statusMessage }}</span>
</div>
```

#### 7. FollowUpView - Settings UI (`FollowUpView.vue`)

**Status**: ✅ Already implemented

The settings UI already has the `sendViaSidecar` checkbox with proper styling and warning message when disabled.

## Architecture

### Flow Comparison

**Before (Direct Send)**:

```
FollowUp detects unread
    ↓
AI generates reply
    ↓
Direct send to device ❌ (No human review)
```

**After (Sidecar Queue)**:

```
FollowUp detects unread
    ↓
AI generates reply
    ↓
Check send_via_sidecar setting
    ├─ TRUE → Add to Sidecar queue ✅ (source='followup')
    │          ↓
    │          User reviews & edits
    │          ↓
    │          Manual send confirmation
    │          ↓
    │          Send to device
    │
    └─ FALSE → Direct send to device (no review)
```

### Message Sources

| Source     | Origin          | Badge Color | Icon |
| ---------- | --------------- | ----------- | ---- |
| `followup` | FollowUp system | Blue        | 🔄   |
| `sync`     | Sync process    | Green       | 🔃   |
| `manual`   | Manual entry    | Gray        | ✍️   |

## UI Examples

### FollowUp Settings

```
┌─────────────────────────────────────────┐
│ Follow-Up Settings                      │
├─────────────────────────────────────────┤
│                                         │
│ ☑ Use AI Reply                          │
│                                         │
│ ☑ Send via Sidecar (Recommended)       │
│   ┗ AI replies will be queued for       │
│     manual review before sending        │
│                                         │
│ ⚠️ Warning: Messages will be sent       │
│    automatically without human review    │
│    (when Sidecar is disabled)            │
│                                         │
└─────────────────────────────────────────┘
```

### Sidecar Queue Display

```
┌─────────────────────────────────────────┐
│ Sidecar - EMULATOR29X                   │
├─────────────────────────────────────────┤
│                                         │
│ 🔄 FOLLOWUP Message for 张三             │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━ 80%        │
│                                         │
│ [客户你好，在吗？]                       │
│                                         │
│ [✏️ Edit] [✖️ Cancel] [📤 Send]          │
│                                         │
└─────────────────────────────────────────┘
```

## Benefits

### For Users

1. **Human Review**: AI-generated replies can be reviewed before sending
2. **Edit Capability**: Users can edit AI replies to better fit the context
3. **Cancel Option**: Inappropriate replies can be cancelled
4. **Source Visibility**: Clear indication of message origin (Sync/FollowUp/Manual)
5. **Flexible Control**: Option to disable Sidecar for automatic sending

### For Operations

1. **Reduced Risk**: Fewer inappropriate messages sent to customers
2. **Quality Control**: Human oversight ensures quality
3. **Audit Trail**: All queued messages are tracked
4. **Consistent UX**: Same queue system for Sync and FollowUp

## Configuration

### Enable Sidecar Mode (Recommended)

```python
# In FollowUp settings
send_via_sidecar = True  # Default
```

**Behavior**:

- AI replies added to Sidecar queue
- User must manually confirm send
- Can edit or cancel before sending

### Disable Sidecar Mode (Automatic)

```python
send_via_sidecar = False
```

**Behavior**:

- AI replies sent immediately
- No human review
- Warning shown in UI

## Files Modified

| File                                                     | Changes                                | Lines |
| -------------------------------------------------------- | -------------------------------------- | ----- |
| `backend/routers/followup.py`                            | Added sendViaSidecar to settings model | ~5    |
| `backend/servic../03-impl-and-arch/response_detector.py` | Added `_send_reply_wrapper()` method   | ~70   |
| `src/services/api.ts`                                    | Added source field to QueuedMessage    | ~3    |
| `src/views/SidecarView.vue`                              | Added source badges to UI              | ~20   |

**Total**: ~100 lines added/modified across 4 files

## Testing Checklist

- [x] Backend syntax validated
- [x] Settings API updated
- [x] Queue wrapper method implemented
- [x] Frontend types updated
- [x] Source badges added to UI
- [ ] **Integration Testing Required**:
  - [ ] Test Sidecar mode (send_via_sidecar=true)
  - [ ] Test direct send mode (send_via_sidecar=false)
  - [ ] Verify source badges appear correctly
  - [ ] Test edit/cancel functionality
  - [ ] Verify warning message appears when Sidecar disabled

## Next Steps

### Recommended Testing

1. **Start Backend**:

   ```bash
   cd wecom-desktop/backend
   uvicorn main:app --reload --port 8765
   ```

2. **Start Frontend**:

   ```bash
   cd wecom-desktop
   npm run dev:electron
   ```

3. **Test Scenarios**:
   - Open FollowUp settings, verify "Send via Sidecar" checkbox exists
   - Enable Sidecar mode, start FollowUp for a device
   - Wait for FollowUp to detect unread messages
   - Check Sidecar panel for queued message with 🔄 FOLLOWUP badge
   - Test editing the message
   - Test cancelling the message
   - Test sending the message
   - Disable Sidecar mode, verify warning appears
   - Test direct send mode

### Optional Enhancements

1. **Queue List View**: Show all queued messages in a list (not just current ready message)
2. **Bulk Operations**: Approve/reject all FollowUp messages at once
3. **Priority Queuing**: Mark certain messages as high priority
4. **Queue Analytics**: Statistics on approval/cancellation rates
5. **Auto-Approve Rules**: Auto-approve messages based on confidence score

## Troubleshooting

### Issue: Messages not appearing in Sidecar queue

**Check**:

- Is `send_via_sidecar` enabled in settings?
- Is FollowUp process running?
- Check logs for Sidecar API errors
- Verify backend is running on port 8765

### Issue: Source badge not showing

**Check**:

- Is `currentQueuedMessage` populated?
- Does the message have `source` field set?
- Check browser console for errors

### Issue: Direct send not working

**Check**:

- Is `send_via_sidecar` disabled?
- Check if Sidecar queue API is failing (fallback should trigger)
- Verify WeComService is working

## Summary

✅ **Backend**: Sidecar integration implemented with source tracking
✅ **Settings API**: sendViaSidecar field added
✅ **Queue Logic**: \_send_reply_wrapper() method implemented
✅ **Frontend Types**: QueuedMessage interface updated
✅ **UI Badges**: Source badges added to SidecarView
✅ **Syntax**: All Python files validated

**The FollowUp Sidecar integration is complete and ready for testing!** 🚀

---

**Related Documentation**:

- [Original Implementation Plan](./followup_sidecar_integration.md)
- [FollowUp Multi-Device System](./followup_multidevice_implementation_complete.md)
- [FollowUp Log Integration](./followup_log_integration_complete.md)
