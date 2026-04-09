# AI Config Router - Usage Analysis & Status

**Date**: 2026-02-06
**File**: `wecom-desktop/backend/routers/ai_config.py`
**Status**: ✅ **Active - In Use**

## Executive Summary

`ai_config.py` provides API endpoints for AI configuration management and admin action recording. **These endpoints are actively used** by the frontend and **should NOT be removed**.

## API Endpoints

### 1. AI Configuration Endpoints

#### `GET /api/ai/config`

**Purpose**: Get current AI configuration (system_prompt, prompt_style_key)

**Frontend Usage**:

```typescript
// wecom-desktop/src/services/api.ts
async getAIConfig(): Promise<AIConfigResponse> {
  return this.request('/api/ai/config')
}
```

**Current Status**: ❌ **NOT USED** by frontend

**Why**: Frontend uses `/settings/update` endpoint instead (see below)

---

#### `POST /api/ai/config`

**Purpose**: Update AI configuration (system_prompt, prompt_style_key)

**Frontend Usage**:

```typescript
// wecom-desktop/src/services/api.ts
async updateAIConfig(config: Partial<AIConfig>): Promise<AIConfigResponse> {
  return this.request('/api/ai/config', {
    method: 'POST',
    body: JSON.stringify(config),
  })
}
```

**Current Status**: ❌ **NOT USED** by frontend

**Why**: Frontend uses `/settings/update` endpoint instead

---

### 2. Admin Action Endpoint

#### `POST /api/ai/admin-action`

**Purpose**: Record operator actions on AI replies (EDIT, CANCEL, APPROVE)

**Frontend Usage**: ✅ **ACTIVELY USED**

**Used By**: `SidecarView.vue` (3 locations)

```typescript
// wecom-desktop/src/views/SidecarView.vue:659
await recordAdminAction(
  serial,
  actionType, // 'EDIT' or 'APPROVE'
  panel.originalAiMessage,
  wasEdited ? editedMessage : undefined,
  reason
)
```

**Locations Called**:

1. **Line 659**: After clicking "Send" in Sidecar panel
2. **Line 855**: After clicking "Send" in alternative UI
3. **Line 876**: Similar scenario in different code path

**Purpose**: Save operator edits to Excel for training data collection

**Response Types**:

- `EDIT` → Saved to Excel (with modified content)
- `CANCEL` → Not saved
- `APPROVE` → Not saved

---

## Actual AI Configuration Flow

### How Frontend Actually Manages AI Config

**Endpoint Used**: `POST /settings/update`

**Router**: `wecom-desktop/backend/routers/settings.py`

**Frontend Code**:

```typescript
// wecom-desktop/src/stores/settings.ts:298-299
const updateResponse = await fetch(`${settings.value.backendUrl}/settings/update`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    system_prompt: settings.value.systemPrompt, // ← Saved here
    prompt_style_key: settings.value.promptStyleKey, // ← And here
    // ... other settings
  }),
})
```

**Backend Handler**:

```python
# wecom-desktop/backend/routers/settings.py:317
@router.post("/update")
async def update_settings(request: UpdateSettingsRequest):
    """Update application settings."""
    service = get_settings_service()
    # ... saves to database
```

### Why Two Routes Exist?

**Historical Reason**:

- `/api/ai/config` was created earlier for AI-specific configuration
- `/settings/update` was created later as part of unified settings system

**Current State**:

- Frontend uses unified `/settings/update` for all settings
- `/api/ai/config` endpoints are **redundant but not harmful**

## Data Flow Diagram

```
Frontend (SettingsView.vue)
    │
    │ User edits systemPrompt
    ↓
Settings Store (settings.ts)
    │
    │ save() function called
    ↓
POST /settings/update  ← ACTIVE ROUTE
    │
    ↓
Settings Router (settings.py)
    │
    │ update_settings()
    ↓
Settings Service (services/settings/service.py)
    │
    │ set_system_prompt()
    ↓
Unified settings (`settings` table in main DB, default `wecom_conversations.db`)
    │
    ↓
┌─────────────────────────────────────┐
│ Table: settings                     │
│ - category: 'ai_reply'             │
│ - key: 'system_prompt'             │
│ - value: "prompt text..."          │
└─────────────────────────────────────┘
```

## Admin Action Recording Flow

```
Sidecar Panel (SidecarView.vue)
    │
    │ User clicks "Send" on AI message
    ↓
recordAdminAction(actionType, ...)
    │
    ↓
POST /api/ai/admin-action  ← ACTIVE ENDPOINT
    │
    ↓
AI Config Router (ai_config.py)
    │
    │ record_admin_action()
    ↓
save_admin_action_to_excel()
    │
    ├─ Load context from database (last 5 messages)
    ├─ Build row data
    ↓
Excel File (settings/admin_actions.xlsx)
    │
    └─ Columns: 序号, 分类, 上文1-4, 问题, 回复
```

## Code Analysis

### Active Code

#### Frontend (`src/`)

**API Client** (`src/services/api.ts`):

```typescript
// Line 1473-1485
async getAIConfig(): Promise<AIConfigResponse> {
  return this.request('/api/ai/config')  // ← Defined but NOT used
}

async updateAIConfig(config: Partial<AIConfig>): Promise<AIConfigResponse> {
  return this.request('/api/ai/config', {  // ← Defined but NOT used
    method: 'POST',
    body: JSON.stringify(config),
  })
}

async recordAdminAction(action: RecordAdminActionRequest): Promise<...> {
  return this.request('/api/ai/admin-action', {  // ← ACTIVELY USED
    method: 'POST',
    body: JSON.stringify(action),
  })
}
```

**Settings Store** (`src/stores/settings.ts`):

```typescript
// Line 298-299
system_prompt: settings.value.systemPrompt,  // Uses /settings/update
prompt_style_key: settings.value.promptStyleKey,  // Uses /settings/update
```

**Sidecar View** (`src/views/SidecarView.vue`):

- Line 659: `recordAdminAction(...)` ✅ Active
- Line 855: `recordAdminAction(...)` ✅ Active
- Line 876: `recordAdminAction(...)` ✅ Active

#### Backend (`wecom-desktop/backend/`)

**Router Registration** (`main.py:213`):

```python
app.include_router(ai_config.router, prefix="/api/ai", tags=["ai"])
```

**Active Endpoint** (`routers/ai_config.py:333`):

```python
@router.post("/admin-action")
async def record_admin_action(request: RecordAdminActionRequest):
    """Record an operator action on an AI reply."""
    # ... saves to Excel
```

## Database Storage

### AI Settings Location

**Database**: same SQLite file as conversations (`wecom_conversations.db` by default, or `WECOM_DB_PATH`)

**Table**: `settings`

**Records**:

```sql
-- System Prompt
category: 'ai_reply', key: 'system_prompt', value: '...'

-- Prompt Style
category: 'ai_reply', key: 'prompt_style_key', value: 'professional'

-- Other AI Settings
category: 'ai_reply', key: 'server_url', value: 'http://localhost:8000'
category: 'ai_reply', key: 'reply_timeout', value: '10'
```

### Excel Storage

**File**: `settings/admin_actions.xlsx`

**Purpose**: Training data collection for operator-edited AI replies

**Columns**:

- 序号 (Row Number)
- 分类 (Category - for manual labeling)
- 上文1-4 (Context Messages 1-4)
- 文本消息内容 (Customer Question)
- 确定回复 (Operator Modified Reply)

**Saved**: Only `EDIT` type actions

## Recommendations

### 1. Keep the File ✅

**Reason**: `/api/ai/admin-action` endpoint is actively used

**Don't Remove**: `record_admin_action()` function

---

### 2. Clean Up Redundant Endpoints ⚠️

**Optional**: Remove unused `/api/ai/config` endpoints

**Rationale**:

- Frontend uses `/settings/update` instead
- Reduces code confusion
- Single source of truth for settings

**Steps**:

1. Remove `get_ai_config()` function (lines 86-92)
2. Remove `POST /config` endpoint (lines 303-325)
3. Remove `GET /config` endpoint (lines 286-300)
4. Remove `load_ai_config()` and `save_ai_config()` functions
5. Keep `record_admin_action()` and Excel saving code
6. Update frontend API client to remove unused methods

**Impact**:

- No breaking changes (endpoints not used)
- Cleaner code
- Less confusion about which endpoint to use

---

### 3. Add Documentation

**Suggested**: Add inline comments explaining the two routes

```python
# Note: AI configuration is managed through /settings/update endpoint
# This router only provides admin-action recording for learning data
```

---

### 4. Consider Frontend Cleanup

**Optional**: Remove unused API client methods

**Files to Update**:

- `src/services/api.ts`: Remove `getAIConfig()` and `updateAIConfig()`
- Check for any other references to these methods

## Migration Path

If removing redundant endpoints:

```python
# BEFORE (Current)
@router.get("/config")  # ← Unused
async def get_ai_config():
    ...

@router.post("/config")  # ← Unused
async def update_ai_config():
    ...

@router.post("/admin-action")  # ← Active
async def record_admin_action():
    ...

# AFTER (Cleaned)
# Removed: /config endpoints (use /settings/update instead)

@router.post("/admin-action")  # ← Active
async def record_admin_action():
    ...
```

## Testing Verification

### How to Verify Active Usage

**1. Check Admin Action Recording**:

```bash
# Open Sidecar panel
# Edit an AI-generated message
# Click "Send"
# Check settings/admin_actions.xlsx was updated
```

**2. Verify Settings Save**:

```bash
# Open Settings view
# Edit system prompt
# Check database:
python -c "
from services.settings import get_settings_service
s = get_settings_service()
prompt = s.get_system_prompt()
print(f'System prompt length: {len(prompt)}')
"
```

**3. Network Traffic**:

```javascript
// Open Browser DevTools → Network
// Use Sidecar panel and edit AI message
// Look for: POST /api/ai/admin-action  ← Should appear
// Look for: POST /settings/update     ← Should appear when saving settings
```

## Conclusion

### Status Summary

| Endpoint                    | Status    | Used By         | Action     |
| --------------------------- | --------- | --------------- | ---------- |
| `GET /api/ai/config`        | ❌ Unused | None            | Can remove |
| `POST /api/ai/config`       | ❌ Unused | None            | Can remove |
| `POST /api/ai/admin-action` | ✅ Active | SidecarView.vue | **Keep**   |

### Recommendation

**Keep** `ai_config.py` but consider cleanup:

1. ✅ **Keep**: `/api/ai/admin-action` endpoint and Excel saving logic
2. ⚠️ **Consider removing**: `/api/ai/config` endpoints (redundant)
3. ✅ **Keep**: File itself (active admin-action functionality)
4. 📝 **Add**: Documentation explaining the settings flow

The file is **not obsolete** - the admin-action recording is actively used for training data collection.

## Related Files

### Backend

- `wecom-desktop/backend/routers/ai_config.py` - This file
- `wecom-desktop/backend/routers/settings.py` - Actual settings endpoint used
- `wecom-desktop/backend/main.py:213` - Router registration

### Frontend

- `wecom-desktop/src/services/api.ts:1473-1497` - API client methods
- `wecom-desktop/src/stores/settings.ts:298-299` - Settings save logic
- `wecom-desktop/src/views/SidecarView.vue:659,855,876` - Admin action calls

### Storage

- `wecom_conversations.db` (or `WECOM_DB_PATH`) — contains `settings` table for unified app settings
- `settings/admin_actions.xlsx` - Training data Excel file
