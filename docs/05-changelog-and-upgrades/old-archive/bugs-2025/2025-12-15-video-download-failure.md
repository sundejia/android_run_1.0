# Video Download Failure - Stale Coordinates

**Date**: 2025-12-15  
**Status**: ✅ Fixed  
**Severity**: High  
**Impact**: Videos could not be downloaded during conversation sync

## Problem

Videos were not being downloaded successfully during conversation extraction. The downloaded video files were either missing or corrupted.

### Symptoms

1. Video files were not found in the expected location after sync
2. Database recorded video metadata but file_path pointed to non-existent files
3. Video playback failed in the web UI with "file not found" errors

### Root Cause

The video downloading logic had a critical flaw:

1. **Stale Coordinates**: The code would:
   - Locate video position during scroll
   - Record the video coordinates
   - Continue scrolling through the entire conversation
   - Only attempt to download the video AFTER scrolling completed
   - By this time, the screen had scrolled past the video, making coordinates invalid

2. **No Inline Download**: Unlike images which were captured inline during scroll, videos were processed after extraction, when their screen coordinates were no longer valid.

3. **Path Mismatch**: The sync service would generate a new timestamp when saving video records, but the actual file had a different timestamp from the inline download, causing database path mismatches.

## Failed Attempts

1. **Initial approach**: Tried to download videos after extraction by scrolling back to their positions - this failed because:
   - Scroll position tracking was unreliable
   - Multiple videos at different positions made it complex
   - Timing issues with UI stabilization

2. **Post-extraction download**: Attempted to pull videos from device `/sdcard/DCIM/WeixinWork/` after extraction - this failed because:
   - Could not verify which video corresponded to which message
   - Risk of pulling wrong video files
   - No way to ensure video was actually saved

## Solution

Implemented **inline video downloading** that stops scrolling at each video to download it immediately:

### 1. Inline Video Download Method

Created `_download_video_inline()` in `WeComService` that:

- **Stops scrolling** when a video is detected
- **Clicks** on the video to open fullscreen view
- **Long-presses** to show the save menu
- **Finds and clicks** "Save to phone" button
- **Waits** for download to complete by monitoring `/sdcard/DCIM/WeixinWork/` for new files
- **Verifies** the video is correct (checks file size stability, file is new)
- **Pulls** the video from device
- **Cleans up** (intelligently presses back to return to conversation)

### 2. Smart Cleanup

Fixed `_cleanup_video_download_state()` to:

- Press back **only up to 2 times** (reduced from 3)
- **Check UI state after each back press** to detect if we're in conversation view
- **Stop immediately** when conversation view is detected (by checking for messages, input field, or send button)
- Prevents over-pressing which could exit the conversation or even the WeCom app

### 3. Path Consistency Fix

Updated `_save_message_video()` in `sync_service.py` to:

- **Preserve original filename** when copying from inline download location
- **Use video directly** if already in correct customer directory
- **Only generate new timestamp** as fallback
- Ensures database path always matches actual file

### 4. CSP Fix for Video Playback

Added `media-src 'self' http://localhost:* blob:` to Content Security Policy in `index.html` to allow video playback from the backend API.

## Implementation Details

### Files Modified

1. **`src/wecom_automation/services/wecom_service.py`**:
   - Added `_download_video_inline()` method
   - Modified `extract_conversation_messages()` to call inline video download during scroll
   - Added `_cleanup_video_download_state()` with smart back-press detection

2. **`src/wecom_automation/services/adb_service.py`**:
   - Added `long_press(x, y, duration_ms)` method for performing long presses

3. **`src/wecom_automation/services/sync_service.py`**:
   - Updated `_save_message_video()` to preserve original filenames and handle inline-downloaded videos correctly
   - Updated `_sync_customer_conversation()` to pass `download_videos=True`

4. **`src/wecom_automation/core/models.py`**:
   - Added `video_local_path` field to `ConversationMessage`
   - Added `videos_downloaded` field to `ConversationExtractionResult`
   - Added `video_count` property

5. **`wecom-desktop/index.html`**:
   - Updated CSP to include `media-src 'self' http://localhost:* blob:`

### Key Code Changes

```python
# In extract_conversation_messages() - inline video download
if download_videos and video_dir:
    for msg in new_messages:
        if msg.message_type == "video":
            # CRITICAL: Stop here and download the video inline
            # This ensures coordinates are still valid
            video_path = await self._download_video_inline(
                msg, video_dir, msg_idx, captured_video_keys
            )
```

## Testing

1. **Manual Testing**:
   - Verified videos are downloaded during sync
   - Confirmed video files exist in `conversation_videos/customer_X/`
   - Verified database paths match actual files
   - Tested video playback in web UI

2. **Edge Cases Handled**:
   - Multiple videos in same conversation
   - Videos at different scroll positions
   - Video download failures (graceful cleanup)
   - Menu not appearing (fallback position)
   - File verification (ensures correct video is pulled)

## Related Issues

- Video playback CSP violation (fixed in same session)
- Database path mismatch (fixed in same session)

## Prevention

- Videos are now downloaded inline, similar to images
- File paths are preserved to prevent timestamp mismatches
- Smart cleanup prevents navigation issues
