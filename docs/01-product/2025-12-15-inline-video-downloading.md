# Inline Video Downloading

**Date**: 2025-12-15  
**Status**: ✅ Complete  
**Feature Type**: Core Functionality Enhancement

## Overview

Implemented inline video downloading during conversation extraction, similar to how images are captured. Videos are now downloaded immediately when detected during scroll, ensuring accurate coordinates and reliable file saving.

## Problem Solved

Previously, videos were processed after extraction completed, when screen coordinates were stale. This caused:

- Videos not being downloaded
- Database paths pointing to non-existent files
- Video playback failures in the web UI

## Solution

Videos are now downloaded **inline during scroll extraction**, stopping the scroll process at each video to:

1. Click the video to open fullscreen
2. Long-press to show save menu
3. Click "Save to phone"
4. Wait for download and verify
5. Pull video from device
6. Resume scrolling

## Implementation

### Core Components

#### 1. Inline Download Method (`_download_video_inline`)

Located in `src/wecom_automation/services/wecom_service.py`:

```python
async def _download_video_inline(
    self,
    msg: ConversationMessage,
    video_dir: Path,
    msg_index: int,
    captured_keys: Set[str],
) -> Optional[str]
```

**Process**:

1. Validates video has valid bounds
2. Clicks video center to open fullscreen
3. Long-presses to show save menu
4. Finds "Save to phone" button (by text patterns or fallback position)
5. Monitors `/sdcard/DCIM/WeixinWork/` for new video files
6. Verifies file is new and size is stable
7. Pulls video from device using ADB
8. Cleans up and returns to conversation view

**Key Features**:

- **Verification**: Checks file existence before/after to ensure correct video
- **File Size Check**: Verifies file size is stable (download complete)
- **Smart Cleanup**: Intelligently presses back to return to conversation

#### 2. Smart Cleanup (`_cleanup_video_download_state`)

Prevents over-pressing back button which could exit conversation or app:

```python
async def _cleanup_video_download_state(self) -> None:
    # Presses back intelligently - stops when conversation view detected
    # Checks for: messages visible, input field, or send button
```

**Improvements**:

- Maximum 2 back presses (reduced from 3)
- UI state checking after each press
- Stops immediately when conversation view detected

#### 3. Path Preservation

Updated `_save_message_video()` to preserve original filenames:

- If video already in customer directory → use directly
- If in different directory → preserve filename when copying
- Only generate new timestamp as fallback

This ensures database paths always match actual files.

### Integration Points

#### Extract Conversation Messages

Modified `extract_conversation_messages()` to:

- Accept `download_videos=True` parameter
- Track captured videos with `captured_video_keys` set
- Call `_download_video_inline()` for each video **during scroll** (not after)
- Return `videos_downloaded` count

#### Sync Service

Updated `_sync_customer_conversation()` to:

- Pass `download_videos=True` to extraction
- Use `video_local_path` from inline download
- Track `videos_saved` in statistics

### Data Model Updates

#### ConversationMessage

- Added `video_local_path: Optional[str]` field

#### ConversationExtractionResult

- Added `videos_downloaded: int = 0` field
- Added `video_count` property

## User Experience

### Before

- Videos not downloaded during sync
- Database had metadata but no files
- Video playback failed

### After

- Videos download automatically during sync
- Files saved to `device_storage/<serial>/conversation_videos/customer_X/` by default when sync is launched via the backend device manager
- Database paths match actual files
- Videos play correctly in web UI

## Technical Details

### Video Detection

Videos are detected by:

- `video_duration` (e5v resource ID with time format)
- OR both `video_thumbnail` (k2j) AND `play_button` (jqb)

### Save Menu Interaction

The "Save to phone" button is found by:

1. Text patterns: "save to phone", "保存到手机", "保存"
2. Fallback: Fixed position based on UI layout (x=396, y=858)

### File Verification

Before pulling video:

1. Lists existing videos on device
2. Waits for new file to appear
3. Checks file size stability (two checks 0.5s apart)
4. Only pulls if file is new and size is stable

### Error Handling

- Video download failures → graceful cleanup, continue with next message
- Menu not appearing → fallback position attempt
- File not found → warning logged, metadata still recorded
- Pull timeout → error logged, cleanup performed

## Configuration

No new configuration required. Videos are downloaded automatically when:

- `download_videos=True` is passed to `extract_conversation_messages()`
- Default behavior in sync service

When sync is started from the multi-device desktop/backend flow, the default output root is device-specific, so video files land under `device_storage/<serial>/conversation_videos/`. If a caller explicitly passes a custom output path, that explicit path overrides the default.

## Files Modified

1. `src/wecom_automation/services/wecom_service.py` - Inline download logic
2. `src/wecom_automation/services/adb_service.py` - Long press support
3. `src/wecom_automation/services/sync_service.py` - Path preservation
4. `src/wecom_automation/core/models.py` - Data model updates
5. `wecom-desktop/index.html` - CSP update for video playback

## Related Features

- [Resources Media Browser](01-product/2025-12-12-resources-media-browser.md) - Video playback in web UI
- Inline image capture (similar pattern)

## Future Enhancements

Potential improvements:

- Video thumbnail generation
- Video duration verification
- Batch video download optimization
- Progress tracking for video downloads
