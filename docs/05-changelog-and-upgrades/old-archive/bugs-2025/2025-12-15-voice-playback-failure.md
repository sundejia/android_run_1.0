# Voice Message Playback Failure

**Date**: 2025-12-15  
**Status**: ✅ Fixed  
**Severity**: High  
**Impact**: Voice messages could not be played in UI even though audio files were successfully downloaded

## Problem

Voice messages were being downloaded successfully from WeCom cache and converted to WAV format, but the UI showed "No audio file" and playback was not possible.

### Symptoms

1. Voice files were downloaded to `conversation_voices/` directory
2. Database had voice message records but `voice_file_exists` was always `false`
3. UI displayed "No audio file" for all voice messages
4. Play buttons were disabled (opacity-50) in both Resources view and Conversation detail view
5. Backend API endpoint `/resources/voice` returned 500 Internal Server Error

### Root Cause

Multiple issues prevented voice playback:

1. **Missing Repository Method**: The `_save_message_voice()` method in `sync_service.py` called `repository.update_message_extra_info()`, but this method didn't exist in `ConversationRepository`, causing voice file paths to never be saved to the database.

2. **Database Records Had Placeholder Data**: Existing voice message records in the database had `extra_info` containing only:

   ```json
   { "voice_duration": "2\"", "source": "placeholder", "sequence": 0 }
   ```

   Missing the critical `voice_file_path` field.

3. **Backend API Missing Import**: The `/resources/voice` endpoint in `resources.py` used `json.loads()` but didn't import the `json` module, causing 500 errors when trying to parse `extra_info`.

4. **File Path Not Persisted**: Even when voice files were downloaded during extraction, the file paths were not being saved to the database's `extra_info` field, so the API couldn't determine if files existed.

## Failed Attempts

1. **Manual Database Update**: Initially tried manually updating database records with SQL - this worked temporarily but didn't fix the root cause for future syncs.

2. **Checking File Existence**: Verified files existed on disk, but the database didn't have the paths, so the API couldn't find them.

## Solution

### 1. Added Repository Method

Created `update_message_extra_info()` method in `ConversationRepository`:

```python
def update_message_extra_info(self, message_id: int, updates: dict) -> bool:
    """
    Update the extra_info field of a message by merging with existing data.

    This is used to add voice/image/video file paths after they're downloaded.
    """
    # Get current extra_info
    # Parse existing JSON
    # Merge updates
    # Update in database
```

This method safely merges new voice metadata into existing `extra_info` without overwriting other fields.

### 2. Fixed Backend API Import

Added missing `import json` to `wecom-desktop/backend/routers/resources.py`:

```python
import hashlib
import json  # Added this
import subprocess
```

This fixed the 500 errors when the API tried to parse `extra_info` JSON.

### 3. Database Migration

Updated existing voice message records to include file paths:

```sql
UPDATE messages
SET extra_info = json_set(extra_info, '$.voice_file_path', 'conversation_images/conversation_voices/voice_1_20251215_202557.wav')
WHERE id = 1 AND message_type = 'voice';
```

### 4. Verified Sync Service Integration

Confirmed that `_save_message_voice()` in `sync_service.py` now correctly calls `update_message_extra_info()` to persist file paths during future syncs.

## Implementation Details

### Files Modified

1. **`src/wecom_automation/database/repository.py`**:
   - Added `update_message_extra_info()` method to safely merge metadata into `extra_info` JSON field

2. **`wecom-desktop/backend/routers/resources.py`**:
   - Added `import json` to fix JSON parsing errors
   - Fixed `/resources/voice` endpoint to properly parse `extra_info`

3. **Database Records**:
   - Updated existing voice message records with correct `voice_file_path` values

### Key Code Changes

```python
# In repository.py - new method
def update_message_extra_info(self, message_id: int, updates: dict) -> bool:
    # Get current extra_info
    current_extra = {}
    if row["extra_info"]:
        current_extra = json.loads(row["extra_info"])

    # Merge updates
    current_extra.update(updates)

    # Update in database
    cursor.execute(
        "UPDATE messages SET extra_info = ? WHERE id = ?",
        (json.dumps(current_extra), message_id)
    )
```

```python
# In resources.py - fixed import
import json  # Was missing, causing 500 errors
```

## Testing

1. **API Testing**:
   - Verified `/resources/voice/by-message/1` returns `file_exists: true`
   - Confirmed `/resources/voice/1/file` serves WAV file correctly (HTTP 200, audio/wav)
   - Tested `/resources/voice` list endpoint returns correct `voice_file_exists` status

2. **UI Testing**:
   - Verified play buttons appear in Resources view when `voice_file_exists: true`
   - Confirmed inline playback works in Conversation detail view
   - Tested audio player modal in Resources view

3. **Database Verification**:
   - Confirmed `extra_info` contains `voice_file_path` after sync
   - Verified file paths match actual downloaded files

## Related Issues

- Voice message download feature (feature doc: `docs/01-product/2025-12-15-voice-message-download.md`)
- Similar issue with video playback CSP (fixed in video download bug report)

## Prevention

- Repository method now exists for all future voice/image/video metadata updates
- Backend API properly handles JSON parsing
- Sync service automatically saves file paths during extraction
- Database records will always include `voice_file_path` for downloaded voices

## Impact

After fix:

- ✅ Voice files are playable in Resources view (table and gallery)
- ✅ Voice messages show play buttons in Conversation detail view
- ✅ Audio player modal works correctly
- ✅ API endpoints return correct file existence status
- ✅ Future syncs automatically save voice file paths
