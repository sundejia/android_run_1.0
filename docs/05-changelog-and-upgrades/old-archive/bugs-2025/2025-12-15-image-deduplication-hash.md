# Image Message Deduplication Hash Bug

> **Date**: 2025-12-15
> **Status**: ✅ Fixed
> **Component**: `sync_service.py`, `models.py`

## Symptoms

- Multiple different image messages captured during scroll (logs show "Inline image capture complete: 2 images")
- Only one image saved to customer directory (logs show "Images saved: 1")
- Two distinct images with different dimensions (405x299 and 405x260) being treated as duplicates
- Images are correctly captured inline during scroll, but only one is persisted to database

Example from logs:

```
[2025-12-15T16:18:51.223614] [INFO] Captured image: msg_6_20251215_161851.png (405x299)
[2025-12-15T16:18:54.285470] [INFO] Captured image: msg_15_20251215_161854.png (405x260)
[2025-12-15T16:19:08.072486] [INFO] Inline image capture complete: 2 images
...
[2025-12-15T16:19:30.551574] [INFO] Images saved: 1  ← Only 1 saved!
```

## Root Cause

The message hash computation in `MessageRecord.compute_hash()` did not include any image-specific identifiers. For image messages:

1. **No text content**: Image messages have `content = None`, so the hash input was empty for content
2. **No image identifier**: The hash only included:
   - `customer_id`
   - `content` (empty for images)
   - `message_type` (both are "image")
   - `is_from_kefu` (both are False)
   - `timestamp` (both in same 2-hour bucket)
   - `sequence` (only stored if > 0, so first images had no sequence)

This caused two different images from the same sender at similar times to generate **identical hashes**, making them appear as duplicates in the database.

### Hash Input Before Fix

```python
# Image 1 (405x299)
hash_input = "1||image|0|2025-12-15T16:00:00|"

# Image 2 (405x260)
hash_input = "1||image|0|2025-12-15T16:00:00|"  # SAME HASH!
```

Both images had identical hash inputs because:

- No content (empty string)
- Same message type ("image")
- Same sender (customer, not kefu)
- Same timestamp bucket (2-hour bucket)
- No sequence number (only stored when > 0)

## Solution

### 1. Include Image Dimensions in Extra Info

Modified `_process_and_store_message` in `sync_service.py` to include image bounds and dimensions in `extra_info`:

```python
# Handle image messages - include bounds/dimensions for unique identification
# This is CRITICAL because image messages have no text content, so two different
# images from the same sender at the same time would otherwise have the same hash
if msg_type == MessageType.IMAGE and msg.image:
    if msg.image.bounds:
        extra_info["image_bounds"] = msg.image.bounds
    # Also include dimensions as a secondary identifier
    if msg.image.parse_bounds():
        width = msg.image.x2 - msg.image.x1
        height = msg.image.y2 - msg.image.y1
        extra_info["image_dimensions"] = f"{width}x{height}"
```

### 2. Use Image Dimensions in Hash Computation

Updated `MessageRecord.compute_hash()` in `models.py` to use image dimensions when computing hash for image messages:

```python
# For image messages, use dimensions as content identifier
# This is CRITICAL because images have no text content
content_str = self.content or ""
msg_type = self.message_type.value if isinstance(self.message_type, MessageType) else str(self.message_type)

if msg_type == "image":
    # Use image dimensions to distinguish different images
    # Dimensions are constant regardless of scroll position
    img_dims = extra.get("image_dimensions", "")
    if img_dims:
        content_str = f"[IMG:{img_dims}]"
elif msg_type == "video":
    # Use video duration to distinguish different videos
    vid_dur = extra.get("video_duration", "")
    if vid_dur:
        content_str = f"[VID:{vid_dur}]"
```

### 3. Always Include Sequence

Changed sequence handling to always include it (even if 0) to ensure uniqueness:

```python
# Always include sequence (even if 0) to ensure uniqueness
extra_info["sequence"] = msg._sequence
```

### Hash Input After Fix

```python
# Image 1 (405x299)
hash_input = "1|[IMG:405x299]|image|0|2025-12-15T16:00:00|0"

# Image 2 (405x260)
hash_input = "1|[IMG:405x260]|image|0|2025-12-15T16:00:00|1"  # DIFFERENT HASH!
```

Now each image has a unique hash based on its dimensions.

## Files Changed

- `src/wecom_automation/services/sync_service.py`
  - Added image bounds and dimensions to `extra_info` for image messages
  - Added video duration to `extra_info` for video messages
  - Changed sequence handling to always include it (even if 0)

- `src/wecom_automation/database/models.py`
  - Updated `MessageRecord.compute_hash()` to use image dimensions in hash for image messages
  - Updated `MessageRecord.compute_hash()` to use video duration in hash for video messages
  - Added logic to extract dimensions from `extra_info` and use as content identifier

## Tests

The fix ensures that:

- Different images with different dimensions generate different hashes
- Images are stored as separate messages in the database
- Both images are saved to the customer directory
- The deduplication logic correctly distinguishes between different images

## Impact

- **Image messages are now properly deduplicated**: Different images are correctly identified as unique messages
- **All captured images are saved**: No more lost images due to incorrect deduplication
- **Video messages also benefit**: Similar fix applied for video messages using duration as identifier
- **More robust deduplication**: Sequence numbers are always included, providing additional uniqueness

## Related Issues

This bug is related to the previous fix in `2025-12-11-extraction-fingerprint-dedup.md`, which addressed timestamp inclusion in fingerprints. However, that fix was for the extraction phase deduplication, while this fix addresses the database-level message hash deduplication.

## Technical Notes

- Image dimensions are extracted from UI bounds during extraction, making them available for hash computation
- Dimensions are constant regardless of scroll position, making them a reliable identifier
- The hash uses a 2-hour timestamp bucket for fuzzy matching (same as before), but now includes image-specific identifiers to distinguish different images within the same time window
