# AI Reply Integration for Sidecar Sync

**Date**: 2025-12-08  
**Status**: ✅ Complete  
**Components**: Frontend (Settings, SidecarView), Backend (sync.py, device_manager.py), Sync Script (initial_sync.py)

## Overview

This feature integrates an external AI chatbot server (`http://localhost:8000`) into the WeCom sync workflow. When enabled, test messages during sync are replaced with AI-generated replies instead of mock messages like `测试信息: [...不知道，没想好......]`.

## Problem Statement

During sync, the system sends test messages to customers to verify message delivery. Previously, these were simple mock messages that echoed the last customer message. With AI integration:

1. **Follow-up messages** (when kefu sent last): Uses prompt `"主播没有回复上次的信息，请在生成一个\"补刀\"信息，再尝试与主播建立联系"`
2. **Reply messages** (when customer sent last): Extracts the customer's message and sends it to the AI for a personalized response

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Frontend (Vue.js)                             │
│  Settings: useAIReply, aiServerUrl, aiReplyTimeout              │
└────────────────────────┬────────────────────────────────────────┘
                         │ POST /sync/start (with AI settings)
┌────────────────────────▼────────────────────────────────────────┐
│                    Backend (FastAPI)                             │
│  SyncOptions includes: use_ai_reply, ai_server_url,             │
│                        ai_reply_timeout                          │
└────────────────────────┬────────────────────────────────────────┘
                         │ subprocess with --use-ai-reply flags
┌────────────────────────▼────────────────────────────────────────┐
│               initial_sync.py (Subprocess)                       │
│  AIReplyService calls AI server BEFORE queuing message          │
└────────────────────────┬────────────────────────────────────────┘
                         │ POST /chat (to AI server)
┌────────────────────────▼────────────────────────────────────────┐
│                AI Server (http://localhost:8000)                 │
│  WeCom Chatbot API - generates contextual replies                │
└─────────────────────────────────────────────────────────────────┘
```

## Settings

Added to `src/stores/settings.ts`:

| Setting          | Type    | Default                 | Description                        |
| ---------------- | ------- | ----------------------- | ---------------------------------- |
| `useAIReply`     | boolean | `false`                 | Toggle AI reply on/off             |
| `aiServerUrl`    | string  | `http://localhost:8000` | AI server endpoint                 |
| `aiReplyTimeout` | number  | `10`                    | Timeout in seconds for AI response |

## UI Changes

### Settings View (`SettingsView.vue`)

New "AI Reply Settings" section with:

- Toggle switch for enabling/disabling AI reply
- Text input for AI server URL
- Slider/number input for timeout (1-30 seconds)

### Sidecar View (`SidecarView.vue`)

Visual indicators showing message source:

- 🤖 **AI Reply** (green) - AI-generated response
- ⚠️ **AI Fallback** (yellow) - AI failed, using mock
- 📝 **Mock Reply** (gray) - AI disabled

## Backend Changes

### `backend/routers/sync.py`

```python
class SyncOptions(BaseModel):
    # ... existing options ...
    use_ai_reply: bool = False
    ai_server_url: str = "http://localhost:8000"
    ai_reply_timeout: int = 10
```

### `backend/services/device_manager.py`

New CLI arguments passed to subprocess:

```python
if use_ai_reply:
    cmd.append("--use-ai-reply")
    cmd.extend(["--ai-server-url", ai_server_url])
    cmd.extend(["--ai-reply-timeout", str(ai_reply_timeout)])
```

## Sync Script Changes (`initial_sync.py`)

### New `AIReplyService` Class

- `parse_test_message()` - Parses test messages and identifies type (followup/reply)
- `get_ai_reply()` - Calls AI server with appropriate prompt
- Handles timeout and fallback gracefully

### Modified `sidecar_send_message()` Function

```python
async def sidecar_send_message(message: str) -> bool:
    # If AI reply enabled, get AI reply FIRST
    if ai_service:
        ai_reply = await ai_service.get_ai_reply(message, serial)
        if ai_reply:
            final_message = ai_reply  # Use AI response
        else:
            final_message = message   # Fallback to mock

    # Queue the message (already processed)
    await sidecar_client.add_message(...)
```

## Message Parsing Logic

| Original Message                   | Type     | AI Prompt                                                                  |
| ---------------------------------- | -------- | -------------------------------------------------------------------------- |
| `测试信息: 想的怎么样了?`          | followup | `"主播没有回复上次的信息，请在生成一个\"补刀\"信息，再尝试与主播建立联系"` |
| `测试信息: [...不知道，没想好...]` | reply    | `"不知道，没想好"` (extracted content)                                     |

## Logging

All AI operations are logged for debugging:

```
[AI] Getting AI reply for: 测试信息: [...不知道，没想好...]...
[AI] Parsed type: reply, prompt: 不知道，没想好...
[AI] Sending request to http://localhost:8000/chat...
[AI] ✅ Got reply: 哎呀宝子~[可爱] 没想好很正常哒...
```

## Fallback Behavior

If AI fails (timeout, error, server unavailable):

1. Log the failure with reason
2. Use the original mock message
3. Continue sync normally

## Testing

### Manual Test (curl)

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "chatInput": "不知道，没想好",
    "sessionId": "test_sync_12345",
    "username": "sync_test"
  }'
```

### UI Test

1. Enable "Use AI Reply" in Settings
2. Ensure AI server is running (`http://localhost:8000`)
3. Start sync with Sidecar mode
4. Observe AI reply in sidecar message textarea

## Files Changed

| File                                 | Changes                                    |
| ------------------------------------ | ------------------------------------------ |
| `src/stores/settings.ts`             | Added AI settings types and defaults       |
| `src/views/SettingsView.vue`         | Added AI Reply Settings UI section         |
| `src/views/SidecarView.vue`          | Added AI indicators, pass settings to sync |
| `src/views/DeviceListView.vue`       | Pass AI settings to sync                   |
| `src/services/api.ts`                | Added AI fields to SyncOptions interface   |
| `backend/routers/sync.py`            | Added AI fields to SyncOptions model       |
| `backend/services/device_manager.py` | Pass AI CLI args to subprocess             |
| `initial_sync.py`                    | Added AIReplyService class and integration |

## Related Features

- **[Sidecar Generate Button](2025-12-08-sidecar-generate-button.md)**: On-demand AI/mock reply generation without running a sync. Uses the same `aiService.processTestMessage()` function and prompts, allowing manual generation from the sidecar header.

## Known Limitations

1. AI server must be running and accessible from sync subprocess
2. Network latency affects total sync time
3. AI responses may vary in quality based on prompt context
