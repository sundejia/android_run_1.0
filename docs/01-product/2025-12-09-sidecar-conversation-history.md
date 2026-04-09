# Sidecar Conversation History Panel

**Date**: 2025-12-09  
**Status**: ✅ Complete  
**Components**: Frontend (SidecarView), Backend (sidecar.py), API (api.ts)

## Overview

Added a collapsible "History" panel to each sidecar device panel that displays the complete conversation history between the Agent and the current Streamer. The panel is collapsed by default and shows messages from the database in a compact chat-style view.

## Problem Statement

Previously, users could only see messages visible on the device screen. To view the full conversation history, they had to:

1. Navigate away from the sidecar view
2. Go to the Streamers section
3. Find and click on the specific streamer
4. View the conversation detail page

With the History panel, users can:

1. Expand the collapsible panel in the sidecar
2. View all synced messages without leaving the sidecar
3. Have context while preparing replies

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                 Sidecar Panel                                    │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ Agent: xxx | Conversation: Streamer Name (channel)          ││
│  └─────────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ [Message Textarea] + [Send Controls]                         ││
│  └─────────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ 💬 History [count] | 🔄 | Show ▲/Hide ▼  ← NEW              ││
│  │ ┌───────────────────────────────────────────────────────┐  ││
│  │ │  [Streamer]: message...                    10:30      │  ││
│  │ │                    message... [Agent]       10:31      │  ││
│  │ │  [Streamer]: message...                    10:32      │  ││
│  │ └───────────────────────────────────────────────────────┘  ││
│  └─────────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ Logs [count] | 📥 | Show ▲/Hide ▼                           ││
│  │ [Log entries...]                                             ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

## New Backend Endpoint

### `GE../03-impl-and-arch/{serial}/conversation-history`

Returns conversation history from the database for the current sidecar conversation.

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `contact_name` | string | No* | Streamer contact name |
| `channel` | string | No* | Streamer channel |
| `limit` | int | No | Max messages (default: 100, max: 500) |
| `db_path` | string | No | Database path override |

\* At least one of `contact_name` or `channel` is required.

**Response Model:**

```python
class ConversationHistoryMessage(BaseModel):
    id: int
    content: str | None
    message_type: str
    is_from_kefu: bool
    timestamp_raw: str | None
    timestamp_parsed: str | None
    extra_info: str | None
    created_at: str

class ConversationHistoryResponse(BaseModel):
    success: bool
    customer_id: int | None
    customer_name: str | None
    channel: str | None
    kefu_name: str | None
    messages: List[ConversationHistoryMessage]
    total_messages: int
    error: str | None
```

**Example Response:**

```json
{
  "success": true,
  "customer_id": 28,
  "customer_name": "主播小王",
  "channel": "抖音",
  "kefu_name": "客服张三",
  "messages": [
    {
      "id": 1,
      "content": "你好，想了解合作",
      "message_type": "text",
      "is_from_kefu": false,
      "timestamp_raw": "12:30",
      "timestamp_parsed": "2025-12-09T12:30:00",
      "extra_info": null,
      "created_at": "2025-12-09T12:30:00"
    },
    {
      "id": 2,
      "content": "您好！感谢您的关注...",
      "message_type": "text",
      "is_from_kefu": true,
      "timestamp_raw": "12:31",
      "timestamp_parsed": "2025-12-09T12:31:00",
      "extra_info": null,
      "created_at": "2025-12-09T12:31:00"
    }
  ],
  "total_messages": 2
}
```

**Lookup Logic:**

1. Find kefu associated with the device serial
2. Find customer matching contact_name/channel under that kefu
3. Return most recent messages in chronological order

## UI Features

### Collapsible Panel Header

| Element       | Description                       |
| ------------- | --------------------------------- |
| 💬 History    | Panel label                       |
| [count]       | Badge showing total message count |
| 🔄 button     | Refresh history                   |
| Show ▲/Hide ▼ | Collapse indicator                |

### Panel States

| State               | Height            | Behavior                     |
| ------------------- | ----------------- | ---------------------------- |
| Collapsed (default) | 32px              | Only header visible          |
| Expanded            | 200px (resizable) | Messages shown               |
| Loading             | -                 | Shows "loading..." indicator |
| Empty               | -                 | Shows "No history found"     |

### Message Display

| Message Type                       | Alignment | Style                            |
| ---------------------------------- | --------- | -------------------------------- |
| From Agent (is_from_kefu=true)     | Right     | Primary color background, border |
| From Streamer (is_from_kefu=false) | Left      | Surface background, border       |

Each message shows:

- Message content (with `[type]` prefix for non-text)
- Timestamp (smart formatting: time only for today, date+time for older)

### Resizable Height

- Minimum: 32px (collapsed)
- Maximum: 400px
- Default expanded: 200px
- Drag the top resize handle to adjust

## Panel State Variables

```typescript
// Added to PanelState
historyCollapsed: boolean          // Default: true (folded)
historyMessages: ConversationHistoryMessage[]
historyTotalCount: number
historyLoading: boolean
historyHeight: number              // Default: 200px
historyLastFetched: { contactName: string | null; channel: string | null } | null
```

## Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    User Action                                   │
│  Click "Show ▲" or drag resize handle                           │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│              toggleHistoryCollapsed(serial)                      │
│  1. Toggle historyCollapsed state                                │
│  2. If expanding & no messages → fetchConversationHistory()     │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│              fetchConversationHistory(serial)                    │
│  1. Get contact_name/channel from panel.state.conversation      │
│  2. Skip if already fetched for same conversation               │
│  3. Call API: GE../03-impl-and-arch/{serial}/conversation-history        │
│  4. Update historyMessages and historyTotalCount                │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│                Backend Database Lookup                           │
│  1. devices → Find device by serial                             │
│  2. kefus → Find kefu by device_id                              │
│  3. customers → Find customer by kefu_id + name + channel       │
│  4. messages → Get messages by customer_id (DESC, then reverse) │
└─────────────────────────────────────────────────────────────────┘
```

## Auto-Refresh Behavior

The history automatically refreshes when:

1. The conversation changes (different contact_name or channel)
2. User clicks the 🔄 refresh button
3. Panel is expanded after being collapsed

The history does NOT auto-refresh on poll interval to avoid unnecessary API calls.

## Files Changed

| File                         | Changes                                                                                                            |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `backend/routers/sidecar.py` | Added `ConversationHistoryMessage`, `ConversationHistoryResponse` models and `GET /conversation-history` endpoint  |
| `src/services/api.ts`        | Added `ConversationHistoryMessage`, `ConversationHistoryResponse` interfaces and `getConversationHistory()` method |
| `src/views/SidecarView.vue`  | Added history state, fetch/toggle/refresh functions, resize handlers, and collapsible UI section                   |

## Code Examples

### Frontend - Fetch Conversation History

```typescript
async function fetchConversationHistory(serial: string) {
  const panel = ensurePanel(serial)
  const contactName = panel.state?.conversation?.contact_name || null
  const channel = panel.state?.conversation?.channel || null

  if (!contactName && !channel) return

  // Skip if already fetched for same conversation
  if (
    panel.historyLastFetched?.contactName === contactName &&
    panel.historyLastFetched?.channel === channel
  )
    return

  panel.historyLoading = true
  const result = await api.getConversationHistory(serial, {
    contactName,
    channel,
    limit: 100,
  })

  if (result.success) {
    panel.historyMessages = result.messages
    panel.historyTotalCount = result.total_messages
    panel.historyLastFetched = { contactName, channel }
  }
  panel.historyLoading = false
}
```

### Backend - Conversation History Endpoint

```python
@router.get("/{serial}/conversation-history")
async def get_conversation_history(
    serial: str,
    contact_name: Optional[str] = None,
    channel: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
) -> ConversationHistoryResponse:
    # 1. Find kefu for device
    cursor.execute("""
        SELECT k.id, k.name FROM kefus k
        JOIN devices d ON k.device_id = d.id
        WHERE d.serial = ?
    """, (serial,))

    # 2. Find customer
    cursor.execute("""
        SELECT id, name, channel FROM customers
        WHERE kefu_id = ? AND name = ? AND channel = ?
    """, (kefu_id, contact_name, channel))

    # 3. Get messages
    cursor.execute("""
        SELECT * FROM messages
        WHERE customer_id = ?
        ORDER BY COALESCE(timestamp_parsed, created_at) DESC
        LIMIT ?
    """, (customer_id, limit))

    # 4. Return reversed (oldest first)
    return ConversationHistoryResponse(
        success=True,
        messages=list(reversed(messages)),
        total_messages=total_count,
        ...
    )
```

## Usage

1. Open sidecar for a device
2. Navigate to a conversation on the device
3. Click **💬 History** header or the "Show ▲" text to expand
4. View all synced messages in chronological order
5. Click 🔄 to refresh if new messages were synced
6. Drag the top border to resize the panel height
7. Click "Hide ▼" to collapse back

## Smart Timestamp Formatting

| Condition   | Format             | Example        |
| ----------- | ------------------ | -------------- |
| Today       | Time only          | `14:30`        |
| This year   | Month + day + time | `Dec 8, 14:30` |
| Other years | Full date          | `2024/12/8`    |

## Relationship to Other Features

- Uses the same database as [Customer Detail View](../../wecom-desktop/src/views/CustomerDetailView.vue)
- Complements the [Sidecar Generate Button](2025-12-08-sidecar-generate-button.md) by providing context
- Works alongside [AI Reply Integration](2025-12-08-ai-reply-integration.md) to show conversation context

## Known Limitations

1. **Database only**: Shows messages from the sync database, not live from the device
2. **No real-time updates**: Must manually refresh to see newly synced messages
3. **Requires prior sync**: Conversations must have been synced at least once to appear
4. **Customer matching**: Relies on exact name/channel match with database records
5. **Device must be connected**: Needs active device connection to get current conversation context
