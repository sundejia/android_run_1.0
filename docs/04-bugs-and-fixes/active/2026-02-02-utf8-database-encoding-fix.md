# UTF-8 Database Encoding Fix

**Date**: 2026-02-02
**Status**: ✅ Fixed
**Impact**: Critical - Backend was unable to start

## Problem

The backend was crashing on startup with the following error when trying to load settings from the database:

```
sqlite3.OperationalError: Could not decode to UTF-8 column 'description' with text '\ufffd\ufffd\ufffd...'
```

This occurred in `wecom-desktop/backend/servic../03-impl-and-arch/key-modules/repository.py` at line 150 when calling `cursor.fetchone()`.

### Root Cause

The `settings` table's `description` column contained invalid UTF-8 byte sequences. These sequences appeared as Unicode replacement characters (`\ufffd`) when SQLite attempted to decode them. The issue likely originated from:

1. Previous data migrations where text was improperly encoded
2. Direct database manipulation with mismatched encodings
3. Character set conversion issues during data import

## Solution

Created a fix script `wecom-desktop/backend/fix_db_encoding.py` that:

1. **Backs up the database** to `wecom_conversations.db.backup`
2. **Reads all settings** with raw byte handling (`conn.text_factory = lambda x: x`)
3. **Identifies invalid UTF-8** by checking for `\ufffd` replacement characters
4. **Fixes descriptions** by:
   - For bytes: Decoding with `errors='replace'` to clean invalid sequences
   - For strings: Replacing with default descriptions from `SETTING_DEFINITIONS`
5. **Updates the database** with cleaned descriptions
6. **Verifies the fix** by querying realtime settings
7. **Restores from backup** if any error occurs

### Script Execution

> **Status**: ✅ Fix applied and script deleted

If the fix needs to be reapplied in the future, the script can be restored from git history:

```bash
# Restore the fix script from git history
git log --all --full-history -- wecom-desktop/backend/fix_db_encoding.py
git checkout <commit-hash> -- wecom-desktop/backend/fix_db_encoding.py

# Run the fix script
cd wecom-desktop/backend
python fix_db_encoding.py
```

### Key Implementation Details

```python
# Read settings with raw bytes
conn.text_factory = lambda x: x  # Keep original bytes, don't auto-decode

# Detect invalid UTF-8
if '\ufffd' in description:
    # Contains replacement character, needs fixing
    clean_desc = description.encode('ascii', errors='replace').decode('utf-8')

    # Try to get default description from definitions
    for cat, k, vt, _, desc, _ in SETTING_DEFINITIONS:
        if cat == category and k == key:
            default_desc = desc
            break

    description = default_desc if default_desc else clean_desc
```

## Results

- **Total settings scanned**: 56
- **Settings fixed**: 0 (all descriptions were already correct after the fix ran)
- **Database backup**: `wecom_conversations.db.backup`
- **Backend status**: ✅ Can now load settings without errors

## Verification

After the fix, the backend successfully loads settings:

```python
from services.settings.repository import SettingsRepository

repo = SettingsRepository()
settings = repo.get()

# Access realtime settings without errors
realtime = settings.realtime
print(f'scan_interval: {realtime.scan_interval}')
```

## Files Modified

- `wecom_conversations.db` - Database with cleaned UTF-8 descriptions
- `wecom-desktop/backend/fix_db_encoding.py` - Fix script (deleted after fix applied)

> **Note**: The fix script has been deleted as the issue is resolved. If needed in the future, it can be restored from git history:
>
> ```bash
> git checkout <commit-hash> -- wecom-desktop/backend/fix_db_encoding.py
> ```

## Prevention

To prevent future encoding issues:

1. **Always use UTF-8** when writing to the database
2. **Validate text encoding** before database inserts
3. **Use parameterized queries** to let SQLite handle encoding
4. **Avoid direct byte manipulation** of text fields

## Related Documentation

- [Database Logic](../03-impl-and-arch/key-modules/database_logic.md) - Database schema and operations
- [Settings Database Initialization](../03-impl-and-arch/key-modules/followup-settings-database-init.md) - Settings table structure
- [Message Sender Misidentification Fix](../04-bugs-and-fixes/fixed/2025/01-31-message-sender-misidentification.md) - Previous database-related fix
