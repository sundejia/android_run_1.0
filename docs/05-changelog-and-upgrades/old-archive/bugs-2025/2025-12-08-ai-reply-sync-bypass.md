# AI Reply Sync Bypass Bug

**Date**: 2025-12-08  
**Status**: ✅ Fixed  
**Severity**: High  
**Component**: Backend sync.py, initial_sync.py

## Symptoms

When AI Reply was enabled in Settings and sync was started:

1. Mock messages like `测试信息: [...不知道，没想好......]` were still being sent
2. AI replies were not being generated
3. Both mock AND AI replies were sent (duplicate messages)
4. No AI-related logging appeared in sync output

## Root Cause Analysis

### Bug 1: Single-Device Sync Path Missing AI Settings

The `/sync/start` endpoint had two code paths:

1. **Single device**: Direct call to `manager.start_sync()`
2. **Multiple devices**: Staggered start via `_start_sync_staggered()`

The AI settings (`use_ai_reply`, `ai_server_url`, `ai_reply_timeout`) were only added to the staggered path, not the single-device path.

**Location**: `backend/routers/sync.py` lines 111-120

```python
# BEFORE (missing AI settings):
success = await manager.start_sync(
    serial=serial,
    db_path=request.options.db_path,
    # ... other options ...
    countdown_seconds=request.options.countdown_seconds,
)

# AFTER (fixed):
success = await manager.start_sync(
    serial=serial,
    db_path=request.options.db_path,
    # ... other options ...
    countdown_seconds=request.options.countdown_seconds,
    use_ai_reply=request.options.use_ai_reply,
    ai_server_url=request.options.ai_server_url,
    ai_reply_timeout=request.options.ai_reply_timeout,
)
```

### Bug 2: Frontend AI Processing Race Condition (Initial Implementation)

The initial implementation tried to process AI replies in the frontend (`SidecarView.vue`) when a "ready" message was detected in the queue. This caused:

1. Backend queued mock message immediately
2. Frontend polled and detected ready message
3. Frontend called AI server for reply
4. Original mock message was already being sent
5. AI reply was also displayed/queued = duplicate

**Solution**: Moved AI processing to the backend (`initial_sync.py`), so AI reply is fetched BEFORE the message is queued.

## Failed Attempts

1. **Frontend-only AI processing**: Caused race condition - message was queued before AI could respond
2. **Updating queued message content**: Added complexity and still had timing issues

## Final Fix

Process AI reply at the source - in `initial_sync.py` before adding to sidecar queue:

```python
async def sidecar_send_message(message: str) -> bool:
    # Get AI reply BEFORE queuing
    if ai_service:
        ai_reply = await ai_service.get_ai_reply(message, serial)
        final_message = ai_reply if ai_reply else message

    # Queue only the final message (already AI-processed or fallback)
    await sidecar_client.add_message(
        customer_name=...,
        message=final_message,  # AI reply or mock
    )
```

## Verification

1. Start sync with AI Reply enabled
2. Check logs for `[AI] Getting AI reply for:` messages
3. Verify only ONE message appears in sidecar
4. Confirm AI-generated content (not mock format)

### Test Commands

```bash
# Verify AI server is reachable
curl -s http://localhost:8000/health

# Test AI reply endpoint
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"chatInput": "不知道，没想好", "sessionId": "test"}'

# Check sync subprocess has AI flags
ps aux | grep initial_sync.py
# Should show: --use-ai-reply --ai-server-url http://localhost:8000
```

## Files Changed

| File                      | Change                                                |
| ------------------------- | ----------------------------------------------------- |
| `backend/routers/sync.py` | Added AI settings to single-device sync path          |
| `initial_sync.py`         | Moved AI processing before queue (no frontend needed) |
| `SidecarView.vue`         | Removed frontend AI processing (simplified)           |

## Lessons Learned

1. **Check all code paths**: When adding parameters to an endpoint, ensure ALL branches pass them
2. **Process at source**: Data transformations should happen at the source, not downstream
3. **Avoid race conditions**: Don't rely on polling to intercept and modify in-flight data
