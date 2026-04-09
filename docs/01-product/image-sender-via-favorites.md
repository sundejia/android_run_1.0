# Image Sender via Favorites

**Implemented**: 2025-02-05
**Integrated**: 2026-02-06
**Status**: ✅ Complete

## Overview

The Image Sender feature provides the ability to send images through WeChat's **Favorites** functionality. This is a versatile module that can be integrated into automatic replies, follow-up messages, or called directly via REST API.

### Key Features

- **Dynamic UI Element Detection** - No hardcoded coordinates
- **Cross-Device Compatibility** - Supports different screen resolutions
- **Version Compatibility** - Works with different WeChat versions
- **Complete Error Handling** - Detailed error messages
- **Flexible Invocation** - API and direct code calls
- **REST API Endpoints** - Easy integration from frontend

## Architecture

### Module Location

```
src/wecom_automation/services/message/
├── image_sender.py          # Core implementation
└── __init__.py             # Export interface

wecom-desktop/backend/routers/
└── image_sender.py         # REST API routes
```

### Core Classes

```python
class ImageSender:
    """Universal image sending service"""

    async def send_via_favorites(self, favorite_index: int = 0) -> bool:
        """Send image at specified favorites index"""

    async def list_favorites(self) -> list[dict[str, Any]]:
        """List all favorite items"""
```

## Usage

### 1. REST API (Recommended)

**Start backend:**

```bash
cd wecom-desktop/backend
uvicorn main:app --reload --port 8765
```

**Send image:**

```bash
curl -X POST http://localhost:8765/api/image-sender/send \
  -H "Content-Type: application/json" \
  -d '{
    "device_serial": "YOUR_DEVICE_SERIAL",
    "favorite_index": 0
  }'
```

**List favorites:**

```bash
curl -X POST http://localhost:8765/api/image-sender/list-favorites \
  -H "Content-Type: application/json" \
  -d '{
    "device_serial": "YOUR_DEVICE_SERIAL"
  }'
```

### 2. Python Code

```python
from wecom_automation.services.message.image_sender import ImageSender

sender = ImageSender(wecom_service)
success = await sender.send_via_favorites(favorite_index=0)

# List all favorites
favorites = await sender.list_favorites()
for i, item in enumerate(favorites):
    print(f"[{i}] {item['text']} - {item['resource_id']}")
```

### 3. Integration in Realtime Reply

```python
# In realtime_reply_process.py
from wecom_automation.services.message.image_sender import ImageSender

sender = ImageSender(wecom_service)

if should_send_image:  # Your business logic
    success = await sender.send_via_favorites(favorite_index=0)
    if success:
        logger.info("✅ Image sent as part of reply")
```

## UI Element Detection Strategy

The ImageSender uses multiple strategies for dynamic UI element detection:

1. **Attach Button** (`_find_attach_button`)
   - Find by resource_id (id8)
   - Position validation (bottom of screen, y > 2000)

2. **Favorites Button** (`_find_favorites_button`)
   - Find by text "Favorites"
   - Find by resource_id (agb)
   - Position filter (middle-right, 400 < x < 1000, 1200 < y < 2200)

3. **Favorite Item** (`_find_favorite_item`)
   - Find by resource_id (ls1)
   - Supports index selection (0-based)

4. **Send Button** (`_find_send_button`)
   - Find by text "Send"
   - Find by resource_id (dbf)

## Prerequisites

Before sending images, ensure:

1. ✅ Device connected via ADB
2. ✅ WeChat application is open
3. ✅ In conversation view (chat with a contact)
4. ✅ Favorites has at least one image
5. ✅ favorite_index is valid

## Use Cases

### Scenario 1: Auto-Send Product Images

```python
if "产品" in customer_message or "图片" in customer_message:
    sender = ImageSender(wecom_service)
    await sender.send_via_favorites(favorite_index=0)
```

### Scenario 2: Keyword-Based Image Selection

```python
keyword_to_image = {
    "价格表": 0,
    "使用说明": 1,
    "联系方式": 2,
}

for keyword, index in keyword_to_image.items():
    if keyword in customer_message:
        sender = ImageSender(wecom_service)
        await sender.send_via_favorites(favorite_index=index)
        break
```

### Scenario 3: Batch Image Sending

```python
async def send_product_series(wecom_service, start_index=0, count=3):
    """Send a series of product images"""
    sender = ImageSender(wecom_service)

    for i in range(count):
        success = await sender.send_via_favorites(favorite_index=start_index + i)
        if success:
            print(f"✅ Sent image {start_index + i}")
            await asyncio.sleep(2)  # Wait 2 seconds between sends
        else:
            print(f"❌ Failed to send image {start_index + i}")
            break
```

## Technical Implementation

### REST API Endpoints

| Endpoint                           | Method | Description               |
| ---------------------------------- | ------ | ------------------------- |
| `/api/image-sender/send`           | POST   | Send image from favorites |
| `/api/image-sender/list-favorites` | POST   | List all favorite items   |
| `/api/image-sender/health`         | GET    | Health check              |

### Request/Response Models

**SendImageRequest:**

```python
{
    "device_serial": str,     # Device serial number
    "favorite_index": int      # Index of favorite item (0-based)
}
```

**SendImageResponse:**

```python
{
    "success": bool,           # True if sent successfully
    "message": str,            # Status message
    "favorite_index": int      # Index that was sent
}
```

## Performance Notes

1. **Execution Time**: Each send takes 7-10 seconds
2. **Batch Sending**: Add 2-3 second delays between consecutive sends
3. **Async Usage**: Always use async/await to avoid blocking

## Error Handling

```python
from wecom_automation.services.message.image_sender import (
    ImageSender,
    ElementNotFoundError
)

try:
    sender = ImageSender(wecom_service)
    success = await sender.send_via_favorites(favorite_index=0)
except ElementNotFoundError as e:
    logger.error(f"UI element not found: {e}")
    # Can retry or take other action
except Exception as e:
    logger.error(f"Send failed: {e}")
```

## Debugging

### Check Available Favorites

```python
sender = ImageSender(wecom_service)
favorites = await sender.list_favorites()

for i, item in enumerate(favorites):
    print(f"[{i}] Index: {item['index']}, ID: {item['resource_id']}")
```

### Enable Detailed Logging

```python
from wecom_automation.core.logging import get_logger

logger = get_logger("wecom_automation.image_sender")
# Logs will be output to logs/{hostname}-global.log
```

## Integration Points

You can integrate this feature in:

1. **Realtime Reply** (`wecom-desktop/backend/scripts/realtime_reply_process.py`)
   - Send images based on customer message keywords
   - Attach product images automatically

2. **Follow-up Service** (`wecom-desktop/backend/services/followup/`)
   - Include images in follow-up messages
   - Send product catalogs after initial contact

3. **Frontend** (Vue.js)
   - Manual image sending button
   - Batch send operations

## Documentation

| Document                                            | Purpose                          |
| --------------------------------------------------- | -------------------------------- |
| `docs/03-impl-and-arch/key-modules/image-sender.md` | Complete technical documentation |
| `IMAGE_SENDER_INTEGRATION.md`                       | Integration completion report    |
| `USAGE_IMAGE_SENDER.md`                             | Quick start guide                |
| `http://localhost:8765/docs`                        | Interactive API documentation    |

## Related Files

- **Core module**: `src/wecom_automation/services/message/image_sender.py`
- **API routes**: `wecom-desktop/backend/routers/image_sender.py`
- **Integration**: `wecom-desktop/backend/main.py`
- **Test script**: `quick_test_image_sender.py`

## Troubleshooting

**Q: How do I know which favorites are available?**

```bash
# Use test script
python quick_test_image_sender.py --serial YOUR_DEVICE --list

# Or via API
curl -X POST http://localhost:8765/api/image-sender/list-favorites \
  -H "Content-Type: application/json" \
  -d '{"device_serial": "YOUR_DEVICE"}'
```

**Q: What if sending fails?**

- Check logs: `logs/{hostname}-global.log`
- Ensure you're in conversation view
- Ensure Favorites is not empty
- Verify the index is valid

**Q: Can I send multiple images at once?**

- Yes, but add 2-3 second delays between sends to avoid rate limiting

## Summary

The Image Sender feature provides a flexible, modular way to send images through WeChat's Favorites functionality. It's:

- ✅ **Modular** - Clean interface and separation of concerns
- ✅ **Testable** - Test scripts and documentation
- ✅ **Integratable** - Can be called from anywhere
- ✅ **Flexible Control** - You decide when and how to use it
- ✅ **Well Documented** - Complete usage guides
