# Sidecar Generate Reply Button

**Date**: 2025-12-08  
**Status**: ✅ Complete  
**Components**: Frontend (SidecarView), Backend (sidecar.py), API (api.ts)

## Overview

Added a "Generate" button to the sidecar panel header that generates AI or mock replies based on the last message in the conversation. This allows manual generation of replies using the same logic as the sync process, without requiring an active sync operation.

## Problem Statement

Previously, AI-generated or mock replies were only available during an active sync operation. Users needed to:

1. Start a sync to get AI-generated responses
2. Wait for the sync to reach a specific customer
3. Review and send the message from the sidecar

With the Generate button, users can:

1. Navigate to any conversation on the device
2. Click "Generate" to instantly get an AI/mock reply
3. Review, edit, and send the message manually

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                 Sidecar Panel Header                             │
│  [🤖 Generate] [🖥️ Mirror] [🔄] [✖️]                             │
└────────────────────────┬────────────────────────────────────────┘
                         │ Click Generate
┌────────────────────────▼────────────────────────────────────────┐
│               Frontend (SidecarView.vue)                         │
│  generateReply() → GE../03-impl-and-arch/{serial}/last-message           │
└────────────────────────┬────────────────────────────────────────┘
                         │ Get last message info
┌────────────────────────▼────────────────────────────────────────┐
│               Backend (sidecar.py)                               │
│  Extract messages from UI tree → Return last message            │
│  { is_from_kefu, content, message_type }                        │
└────────────────────────┬────────────────────────────────────────┘
                         │ If AI enabled
┌────────────────────────▼────────────────────────────────────────┐
│               AI Service (aiService.ts)                          │
│  processTestMessage() → POST /chat to AI server                 │
└─────────────────────────────────────────────────────────────────┘
```

## Button Behavior

The Generate button:

1. **Fetches last message** from the device's current conversation via new API endpoint
2. **Determines reply type**:
   - If kefu sent last → **补刀 (follow-up)** mode
   - If customer sent last → **reply** mode
3. **Generates response**:
   - If AI enabled → Calls AI service with appropriate prompt
   - If AI disabled or fails → Uses mock message format
4. **Populates textarea** with the generated message for review before sending

## Message Generation Logic

| Last Message From        | Mode  | Test Message Format           | AI Prompt                                                                  |
| ------------------------ | ----- | ----------------------------- | -------------------------------------------------------------------------- |
| Kefu (is_self=true)      | 补刀  | `测试信息: 想的怎么样了?`     | `"主播没有回复上次的信息，请在生成一个\"补刀\"信息，再尝试与主播建立联系"` |
| Customer (is_self=false) | Reply | `测试信息: [...{content}...]` | The extracted message content                                              |

## New Backend Endpoint

### `GE../03-impl-and-arch/{serial}/last-message`

Returns information about the last message in the current conversation.

**Response Model:**

```python
class LastMessageModel(BaseModel):
    is_from_kefu: bool       # True if kefu sent the last message
    content: str | None      # Message content (None for media)
    message_type: str        # "text", "image", "voice", etc.

class LastMessageResponse(BaseModel):
    success: bool
    last_message: LastMessageModel | None
    error: str | None
```

**Example Response:**

```json
{
  "success": true,
  "last_message": {
    "is_from_kefu": false,
    "content": "我想了解一下合作方案",
    "message_type": "text"
  }
}
```

## UI Changes

### Sidecar Panel Header

Before:

```
SERIAL | 🖥️ Mirror | 🔄 | ✖️
```

After:

```
SERIAL | 🤖 Generate | 🖥️ Mirror | 🔄 | ✖️
```

### Button States

| State         | Icon | Disabled | Tooltip                                            |
| ------------- | ---- | -------- | -------------------------------------------------- |
| Idle          | 🤖   | No       | "Generate AI reply..." or "Generate mock reply..." |
| Generating    | ⏳   | Yes      | -                                                  |
| AI Processing | ⏳   | Yes      | -                                                  |
| Sending       | -    | Yes      | -                                                  |

### Visual Feedback

After generation, the textarea shows:

- **Green border** (`border-green-500/50`) for AI-generated replies
- **Yellow border** (`border-yellow-500/50`) for AI fallback (mock)
- **Standard border** for mock-only mode

Status message shows:

- `"AI reply generated (Xms)"` for successful AI generation
- `"AI failed, using mock: {error}"` for AI fallback
- `"Mock message generated"` for mock-only mode

## Files Changed

| File                         | Changes                                                                                 |
| ---------------------------- | --------------------------------------------------------------------------------------- |
| `backend/routers/sidecar.py` | Added `LastMessageModel`, `LastMessageResponse`, and `GET /last-message` endpoint       |
| `src/services/api.ts`        | Added `LastMessageInfo`, `LastMessageResponse` interfaces and `getLastMessage()` method |
| `src/views/SidecarView.vue`  | Added `generating` state, `generateReply()` function, and Generate button               |

## Code Examples

### Frontend - generateReply Function

```typescript
async function generateReply(serial: string) {
  const panel = ensurePanel(serial)
  panel.generating = true

  // 1. Get last message
  const lastMsgResponse = await api.getLastMessage(serial)
  const lastMsg = lastMsgResponse.last_message
  const isFollowUp = lastMsg.is_from_kefu

  // 2. Build test message
  let testMessage: string
  if (isFollowUp) {
    testMessage = '测试信息: 想的怎么样了?'
  } else {
    testMessage = `测试信息: [...${lastMsg.content?.slice(0, 30)}...]`
  }

  // 3. Generate reply (AI or mock)
  if (settings.value.useAIReply) {
    const aiResult = await aiService.processTestMessage(...)
    panel.pendingMessage = aiResult.success ? aiResult.reply : testMessage
  } else {
    panel.pendingMessage = testMessage
  }

  panel.generating = false
}
```

### Backend - Last Message Endpoint

```python
@router.get("/{serial}/last-message", response_model=LastMessageResponse)
async def get_last_message(serial: str) -> LastMessageResponse:
    session = get_session(serial)

    # Get UI tree and extract messages
    tree, _ = await session.service.adb.get_ui_state(force=True)
    messages = session.service.ui_parser.extract_conversation_messages(tree)

    if not messages:
        return LastMessageResponse(success=False, error="No messages found")

    last_msg = messages[-1]
    return LastMessageResponse(
        success=True,
        last_message=LastMessageModel(
            is_from_kefu=last_msg.is_self,
            content=last_msg.content,
            message_type=last_msg.message_type,
        )
    )
```

## Usage

1. Open sidecar for a device
2. Navigate to a customer conversation on the device
3. Click **🤖 Generate** in the panel header
4. Wait for generation (shows ⏳ spinner)
5. Review the generated message in the textarea
6. Edit if needed, then click "Send now" or start countdown

## Relationship to AI Reply Integration

This feature extends the [AI Reply Integration](2025-12-08-ai-reply-integration.md) by:

- Reusing the same `aiService.processTestMessage()` function
- Using the same AI prompts for 补刀 and reply modes
- Respecting the same settings (`useAIReply`, `aiServerUrl`, `aiReplyTimeout`)

The key difference is that AI Reply Integration works during active sync, while this feature allows on-demand generation without running a sync.

## Known Limitations

1. Only gets the last **visible** message from the conversation view
2. Requires the device to be displaying a conversation (not the chat list)
3. AI server must be running if AI reply is enabled
4. Media-only messages return `content: null`, resulting in `[media]` placeholder
