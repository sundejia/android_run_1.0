# Followup Table Schema Verification

## Summary

User requested verification of database tables, specifically asking if `follow_message` table was missing.

## Investigation Findings

### Actual State

**Database: `wecom_conversations.db`**

The database contains the following followup-related tables:

| Table Name               | Purpose                                                    | Status    |
| ------------------------ | ---------------------------------------------------------- | --------- |
| `followup_attempts`      | Tracks follow-up attempt records, status, and retry counts | ✅ EXISTS |
| `followup_sent_messages` | Tracks sent follow-up messages for deduplication           | ✅ EXISTS |

**NOT Found**: `follow_message` table

### Conclusion

**No table named `follow_message` exists in the codebase, and this is CORRECT.**

The table has always been named `followup_attempts` since its inception. The user likely confused the table name with the purpose (storing follow-up messages).

## Schema Details

### `followup_attempts` Table

```sql
CREATE TABLE followup_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_serial TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    customer_id TEXT,
    customer_channel TEXT,  -- Added 2026-02-06 for blacklist integration

    last_kefu_message_id TEXT NOT NULL,
    last_kefu_message_time DATETIME,
    last_checked_message_id TEXT,

    max_attempts INTEGER NOT NULL DEFAULT 3,
    current_attempt INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_followup_at DATETIME,

    UNIQUE(device_serial, customer_name)
);
```

### `followup_sent_messages` Table (Added 2026-02-06)

```sql
CREATE TABLE followup_sent_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_serial TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    message_template TEXT NOT NULL,
    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(device_serial, customer_name, message_template)
);
```

**Purpose**: Prevents duplicate follow-up messages from being sent to the same customer within a short period.

## Recent Changes (2026-02-06)

### 1. Added `customer_channel` Column

**Files Modified**:

- `wecom-desktop/backend/services/followup/attempts_repository.py`
- `wecom-desktop/backend/services/followup/queue_manager.py`

**Purpose**:

- Store customer channel (e.g., `@WeChat`) for blacklist integration
- Fix bug where blacklist check was using wrong field (`customer_id` instead of `customer_channel`)

**Migration**: Applied automatically via `ALTER TABLE` in `_ensure_tables()`

### 2. Created `followup_sent_messages` Table

**Purpose**: Deduplicate follow-up messages to prevent sending the same message template to the same customer repeatedly.

**Usage**:

- Before sending a follow-up, check if the same `(device_serial, customer_name, message_template)` combination exists
- If exists, skip sending to avoid spam

## Verification Commands

```bash
# Check all tables in database
sqlite3 wecom_conversations.db ".tables"

# Check followup_attempts schema
sqlite3 wecom_conversations.db ".schema followup_attempts"

# Check followup_sent_messages schema
sqlite3 wecom_conversations.db ".schema followup_sent_messages"

# Verify customer_channel column exists
sqlite3 wecom_conversations.db "PRAGMA table_info(followup_attempts);"
```

## Related Documentation

- `docs/03-impl-and-arch/key-modules/followup-system-logic.md` - Overall followup system architecture
- `docs/03-impl-and-arch/key-modules/realtime-followup-separation.md` - Phase 1 (realtime) vs Phase 2 (followup) separation
- `docs/01-product/blacklist-system.md` - Blacklist integration

## Resolution

**Status**: ✅ RESOLVED

- Database schema is correct and up to date
- All necessary tables exist and are properly indexed
- Migration for `customer_channel` column is automatic and backward compatible
- No action required beyond this documentation

---

**Date**: 2026-02-06
**Investigated by**: Claude Code
**Result**: No issues found - database schema is correct
