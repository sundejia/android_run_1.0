# Agent-Device Consolidation

**Date**: 2025-12-09  
**Status**: ✅ Complete

## Summary

Agents (kefus) are now identified by `name + department` instead of `name + device_id`. This allows the same agent to use multiple devices while maintaining a unified view of their customers and messages.

## Problem

Previously, agents were identified by `name + device_id`, which caused several issues:

1. **Duplicate Agent Records**: The same agent using different devices appeared as separate entries
   - Example: `wyd` on device A = Agent 1, `wyd` on device B = Agent 2
2. **Fragmented Customer Data**: Customers were split across device-specific agent records
   - The same customer talking to the same agent would appear under different kefu IDs
3. **Inaccurate Statistics**: Message counts and customer counts were fragmented
   - Total messages for an agent were split across multiple records

4. **Poor User Experience**: The Agents page showed 4 entries when there were only 2 actual agents

## Solution

### Database Schema Changes (v1 → v2)

1. **Modified `kefus` table**
   - Removed: `device_id INTEGER NOT NULL REFERENCES devices(id)`
   - Changed unique constraint: `UNIQUE(name, device_id)` → `UNIQUE(name, department)`

2. **Added `kefu_devices` junction table**

   ```sql
   CREATE TABLE kefu_devices (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       kefu_id INTEGER NOT NULL REFERENCES kefus(id) ON DELETE CASCADE,
       device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
       updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
       UNIQUE(kefu_id, device_id)
   );
   ```

3. **New indexes**
   - `idx_kefu_devices_kefu_id` on `kefu_devices(kefu_id)`
   - `idx_kefu_devices_device_id` on `kefu_devices(device_id)`

### Migration Process

The `migrate_v1_to_v2()` function handles:

1. **Create junction table** for kefu-device relationships
2. **Group existing kefus** by `name + department`
3. **For each group with duplicates**:
   - Select first kefu ID as canonical
   - Link all devices to canonical kefu via junction table
   - Merge conflicting customers (same name+channel under different kefu IDs)
   - Move messages from old customers to canonical customers
   - Delete duplicate kefu records
4. **Recreate kefus table** without `device_id` column
5. **Update schema version** to 2

### API Changes

#### `/kefus` Endpoint

**Before**:

```json
{
  "id": 1,
  "name": "wyd",
  "department": "302实验室",
  "device_id": 1,
  "device_serial": "ABC123"
}
```

**After**:

```json
{
  "id": 1,
  "name": "wyd",
  "department": "302实验室",
  "device_count": 2,
  "devices": [
    { "id": 1, "serial": "unknown", "model": null },
    { "id": 3, "serial": "AN2FVB1706003302", "model": null }
  ]
}
```

#### `/dashboard/overview` Endpoint

The `kefus` array now includes `device_count` and `devices` array for each agent.

### UI Changes

**Agents Table** (`KefuListView.vue`):

- Column header: "Device" → "Devices"
- Cell content: Shows device count and truncated serial list
  - Example: "2 devices" with "unknown, AN2FVB1706..." on hover

### Repository Changes

**New methods**:

- `get_kefu_by_name_and_department(name, department)` - Find kefu by identity
- `link_kefu_to_device(kefu_id, device_id)` - Create kefu-device relationship
- `get_devices_for_kefu(kefu_id)` - List all devices for a kefu

**Modified methods**:

- `get_or_create_kefu()` - Now identifies by name+department, auto-links to device
- `list_kefus_for_device()` - Uses junction table

## Before & After

| Metric                  | Before       | After              |
| ----------------------- | ------------ | ------------------ |
| Total Agents            | 4            | 2                  |
| Agent `wyd` entries     | 2 (separate) | 1 (with 2 devices) |
| Agent `wgz小号` entries | 2 (separate) | 1 (with 2 devices) |

## Files Changed

### Database Layer

- `src/wecom_automation/database/schema.py` - Schema v2, migration logic
- `src/wecom_automation/database/models.py` - Removed `device_id` from `KefuRecord`
- `src/wecom_automation/database/repository.py` - New/updated kefu methods

### Backend API

- `wecom-desktop/backend/routers/kefus.py` - Updated queries, added devices array
- `wecom-desktop/backend/routers/dashboard.py` - Updated queries for junction table
- `wecom-desktop/backend/routers/customers.py` - Removed device join
- `wecom-desktop/backend/routers/sidecar.py` - Updated kefu lookup

### Frontend

- `wecom-desktop/src/views/KefuListView.vue` - Devices column

### Tests

- `tests/unit/test_database.py` - Updated for new schema, added multi-device tests

## Testing

Run the database tests to verify the schema and repository:

```bash
cd /path/to/whc
PYTHONPATH=src python -m pytest tests/unit/test_database.py -v
```

To run the migration manually:

```bash
PYTHONPATH=src python -c "
from wecom_automation.database.schema import run_migrations, get_schema_version
print('Current version:', get_schema_version())
run_migrations()
print('New version:', get_schema_version())
"
```

## Rollback

If needed, restore from backup:

```bash
cp wecom_conversations.db.backup wecom_conversations.db
```

Note: A backup is automatically created before migration as `wecom_conversations.db.backup`.
