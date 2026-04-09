# Entity Deletion Feature

> **Date**: 2025-12-12
> **Status**: ✅ Complete
> **Scope**: Agents, Conversations, Streamers tables

## Overview

Added delete functionality to all three main entity tables in the WeCom Desktop application:

- **Agents** (`/kefus`) - Customer service representatives
- **Conversations** (`/conversations`) - Individual chat threads (customers)
- **Streamers** (`/streamers`) - Grouped streamer profiles

Each deletion is **safe**, **complete**, and **redoable**.

## Safety Design

### Database Cascade Chain

The SQLite schema uses `ON DELETE CASCADE` foreign key constraints to ensure referential integrity:

```
Agents (kefus) deletion:
├── kefu_devices (CASCADE) - device-agent links
├── customers (CASCADE) - all conversations
│     └── messages (CASCADE)
│           └── images (CASCADE)

Conversations (customers) deletion:
├── messages (CASCADE)
│     └── images (CASCADE)

Streamers deletion:
├── All customers with that name (CASCADE to messages/images)
├── streamer_profiles entry
└── streamer_personas entries
```

### Deletion Properties

| Property     | Implementation                                                      |
| ------------ | ------------------------------------------------------------------- |
| **Safe**     | Foreign key CASCADE constraints ensure no orphaned records          |
| **Complete** | All related data (messages, images, profiles, personas) are removed |
| **Redoable** | Data can be re-synced from the Android device at any time           |

## Backend Implementation

### Agents (`kefus.py`)

```python
@router.delete("/{kefu_id}")
async def delete_kefu(kefu_id: int, db_path: Optional[str] = None):
    """
    Delete a 客服 and all associated data.

    Cascades to:
    - kefu_devices entries (device-kefu links)
    - customers entries (all customers of this kefu)
    - messages entries (all messages via customers)
    - images entries (all images via messages)
    """
```

**Response:**

```json
{
  "success": true,
  "message": "Deleted kefu 'AgentName' and all associated data",
  "deleted": {
    "kefu_id": 1,
    "kefu_name": "AgentName",
    "department": "SomeDept",
    "device_links_removed": 2,
    "customers_removed": 15,
    "messages_removed": 1234
  }
}
```

### Conversations (`customers.py`)

```python
@router.delete("/{customer_id}")
async def delete_customer(customer_id: int, db_path: Optional[str] = None):
    """
    Delete a customer (conversation) and all associated data.

    Cascades to:
    - messages entries (all messages in this conversation)
    - images entries (all images via messages)
    """
```

**Response:**

```json
{
  "success": true,
  "message": "Deleted conversation with 'StreamerName' and all associated data",
  "deleted": {
    "customer_id": 1,
    "customer_name": "StreamerName",
    "channel": "@WeChat",
    "kefu_name": "AgentName",
    "messages_removed": 50,
    "images_removed": 5
  }
}
```

### Streamers (`streamers.py`)

```python
@router.delete("/{streamer_id}")
async def delete_streamer(streamer_id: str, db_path: Optional[str] = None):
    """
    Delete a streamer and all associated data.

    Deletes:
    - All customers (conversations) with this streamer's name
    - All messages in those conversations (CASCADE)
    - All images in those messages (CASCADE)
    - The streamer_profile entry
    - All streamer_personas entries
    """
```

**Response:**

```json
{
  "success": true,
  "message": "Deleted streamer 'StreamerName' and all associated data",
  "deleted": {
    "streamer_id": "abc123def456",
    "streamer_name": "StreamerName",
    "conversations_removed": 3,
    "messages_removed": 150,
    "profile_removed": true,
    "personas_removed": 1
  }
}
```

## Frontend Implementation

### API Service (`api.ts`)

Added three new methods and response types:

```typescript
// Types
interface KefuDeleteResponse { success: boolean; message: string; deleted: KefuDeletedInfo; }
interface CustomerDeleteResponse { success: boolean; message: string; deleted: CustomerDeletedInfo; }
interface StreamerDeleteResponse { success: boolean; message: string; deleted: StreamerDeletedInfo; }

// Methods
api.deleteKefu(kefuId: number, dbPath?: string): Promise<KefuDeleteResponse>
api.deleteCustomer(customerId: number, dbPath?: string): Promise<CustomerDeleteResponse>
api.deleteStreamer(streamerId: string, dbPath?: string): Promise<StreamerDeleteResponse>
```

### Stores

Each store (`kefus.ts`, `customers.ts`, `streamers.ts`) gained:

- `deleteLoading: boolean` - Loading state
- `deleteError: string | null` - Error message
- `lastDeleted*: *DeletedInfo | null` - Last deletion info
- `delete*(id): Promise<*DeletedInfo>` - Delete action

### Views

Each list view gained:

- **Actions column** with 🗑️ delete button
- **Confirmation modal** with:
  - Entity name and details
  - Warning about what will be deleted (counts)
  - Tip that data can be re-synced
  - Cancel / Delete buttons
  - Loading and error states
- **Success toast** notification (auto-hides after 5 seconds)
- **Vue transitions** for smooth modal and toast animations

## UI Screenshots

### Table with Delete Button

Each table now has an "Actions" column with a delete button:

| Streamer | Agent  | Device | Last message | Preview  | Totals  | Actions |
| -------- | ------ | ------ | ------------ | -------- | ------- | ------- |
| Name     | Agent1 | ABC123 | 12/12/2025   | Hello... | 50 msgs | 🗑️      |

### Confirmation Modal

```
┌─────────────────────────────────────────┐
│ Delete Conversation?                     │
│                                         │
│ Are you sure you want to delete the     │
│ conversation with **StreamerName**      │
│ (@WeChat)?                              │
│                                         │
│ ⚠️ This will permanently delete:        │
│   • 50 messages                         │
│   • All images in this conversation     │
│                                         │
│ 💡 Tip: Data can be re-synced from the │
│ device if needed.                       │
│                                         │
│               [Cancel] [Delete]         │
└─────────────────────────────────────────┘
```

## Files Changed

### Backend

- `wecom-desktop/backend/routers/kefus.py` - Added DELETE endpoint
- `wecom-desktop/backend/routers/customers.py` - Added DELETE endpoint
- `wecom-desktop/backend/routers/streamers.py` - Added DELETE endpoint

### Frontend

- `wecom-desktop/src/services/api.ts` - Added delete types and methods
- `wecom-desktop/src/stores/kefus.ts` - Added delete state and action
- `wecom-desktop/src/stores/customers.ts` - Added delete state and action
- `wecom-desktop/src/stores/streamers.ts` - Added delete state and action
- `wecom-desktop/src/views/KefuListView.vue` - Added delete UI
- `wecom-desktop/src/views/CustomersListView.vue` - Added delete UI
- `wecom-desktop/src/views/StreamersListView.vue` - Added delete UI (both card and table views)

## Testing

Manual testing checklist:

- [ ] Delete agent and verify cascade removes customers, messages, images
- [ ] Delete conversation and verify cascade removes messages, images
- [ ] Delete streamer and verify cascade removes all conversations, profile, personas
- [ ] Verify confirmation modal shows correct counts
- [ ] Verify success toast appears and auto-hides
- [ ] Verify error handling displays properly
- [ ] Verify deleted entity is removed from list immediately
- [ ] Verify data can be re-synced after deletion

## Related Documentation

- [Agent-Device Consolidation](2025-12-09-agent-device-consolidation.md) - Agent data model
- [Streamers Database & Persona Analysis](2025-12-11-streamers-database-persona-analysis.md) - Streamer data model
- Database schema: `src/wecom_automation/database/schema.py`
