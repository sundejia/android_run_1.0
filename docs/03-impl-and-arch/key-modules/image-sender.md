# 图片发送服务 (Image Sender)

## 概述

图片发送服务提供了通过企业微信的 **Favorites（收藏）** 功能发送图片的能力。这个模块具有以下特性：

- ✅ **动态 UI 元素查找** - 不依赖硬编码坐标
- ✅ **跨设备兼容** - 支持不同屏幕分辨率
- ✅ **版本兼容** - 支持不同 WeCom 版本
- ✅ **完整错误处理** - 提供详细的错误信息
- ✅ **灵活调用** - 支持 API 和代码直接调用

## 架构设计

### 模块位置

```
src/wecom_automation/services/message/
├── image_sender.py          # 核心实现
└── __init__.py             # 导出接口

wecom-desktop/backend/routers/
└── image_sender.py         # REST API 路由
```

### 核心类

```python
class ImageSender:
    """通用图片发送服务"""

    async def send_via_favorites(self, favorite_index: int = 0) -> bool:
        """发送指定索引的收藏图片"""

    async def list_favorites(self) -> list[dict[str, Any]]:
        """列出所有收藏项"""
```

### UI 元素查找策略

ImageSender 使用多种策略动态查找 UI 元素：

1. **附件按钮** (`_find_attach_button`)
   - 通过 resource_id 查找（id8）
   - 位置验证（屏幕底部，y > 2000）

2. **Favorites 按钮** (`_find_favorites_button`)
   - 通过文本查找 "Favorites"
   - 通过 resource_id 查找（agb）
   - 位置筛选（中间偏右，400 < x < 1000, 1200 < y < 2200）

3. **收藏项** (`_find_favorite_item`)
   - 通过 resource_id 查找（ls1）
   - 支持索引选择（0-based）

4. **发送按钮** (`_find_send_button`)
   - 通过文本查找 "Send"
   - 通过 resource_id 查找（dbf）

## 使用方法

### 1. 直接在代码中使用

```python
from wecom_automation.services.message.image_sender import ImageSender
from wecom_automation.services.wecom_service import WeComService

# 创建 WeComService 实例
wecom_service = WeComService(config, adb)

# 创建 ImageSender
sender = ImageSender(wecom_service)

# 发送第一个收藏项
success = await sender.send_via_favorites(favorite_index=0)

if success:
    print("✅ 图片发送成功")
else:
    print("❌ 图片发送失败")

# 列出所有收藏项
favorites = await sender.list_favorites()
for i, item in enumerate(favorites):
    print(f"[{i}] {item['text']} - {item['resource_id']}")
```

### 2. 通过 REST API 使用

#### 发送图片

```bash
POST /api/image-sender/send
Content-Type: application/json

{
  "device_serial": "ABC123",
  "favorite_index": 0
}
```

响应：

```json
{
  "success": true,
  "message": "Image sent successfully",
  "favorite_index": 0
}
```

#### 列出收藏项

```bash
POST /api/image-sender/list-favorites
Content-Type: application/json

{
  "device_serial": "ABC123"
}
```

响应：

```json
{
  "success": true,
  "message": "Found 5 favorites",
  "favorites": [
    {
      "index": 42,
      "resource_id": "com.tencent.wework:id/ls1",
      "text": "",
      "bounds": "123,456,789,1012"
    }
  ]
}
```

### 3. 在 Follow-up / Realtime Reply 中集成

你可以在回复流程中集成图片发送功能：

```python
# 在 realtime_reply_process.py 或 followup 相关代码中

from wecom_automation.services.message.image_sender import ImageSender

# 已有的 wecom_service 实例
sender = ImageSender(wecom_service)

# 根据条件决定是否发送图片
if should_send_image:
    success = await sender.send_via_favorites(favorite_index=0)
    if success:
        logger.info("✅ Image sent as part of reply")
```

### 4. 前端调用示例

```javascript
// 发送图片
async function sendImageFromFavorites(deviceSerial, favoriteIndex = 0) {
  try {
    const response = await fetch('/api/image-sender/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        device_serial: deviceSerial,
        favorite_index: favoriteIndex,
      }),
    })

    const result = await response.json()
    if (result.success) {
      console.log('✅ Image sent successfully')
    } else {
      console.error('❌ Failed to send image:', result.message)
    }
  } catch (error) {
    console.error('❌ Error:', error)
  }
}

// 列出收藏项
async function listFavorites(deviceSerial) {
  try {
    const response = await fetch('/api/image-sender/list-favorites', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_serial: deviceSerial }),
    })

    const result = await response.json()
    if (result.success) {
      console.log('收藏项列表:', result.favorites)
      return result.favorites
    }
  } catch (error) {
    console.error('❌ Error:', error)
  }
}
```

## 前置条件

在调用 `send_via_favorites()` 之前，确保：

1. ✅ **设备已连接** - ADB 连接正常
2. ✅ **WeCom 已打开** - 应用处于运行状态
3. ✅ **在对话界面** - 必须在某个联系人的聊天界面
4. ✅ **已有收藏** - Favorites 中至少有一个图片项
5. ✅ **索引有效** - favorite_index 不超过收藏项数量

## 错误处理

### 常见错误

| 错误                                               | 原因           | 解决方案                             |
| -------------------------------------------------- | -------------- | ------------------------------------ |
| `ElementNotFoundError: Attach button not found`    | 不在对话界面   | 导航到对话界面后再调用               |
| `ElementNotFoundError: Favorites button not found` | 附件菜单未打开 | 等待 UI 稳定后重试                   |
| `ElementNotFoundError: No favorite items found`    | Favorites 为空 | 先手动收藏一些图片                   |
| `Favorite index out of range`                      | 索引超出范围   | 使用 `list_favorites()` 查看可用索引 |

### 错误日志

启用 debug 模式查看详细日志：

```python
import logging
from wecom_automation.core.logging import get_logger

logger = get_logger("wecom_automation.image_sender")
logger.setLevel(logging.DEBUG)
```

## 工作流程

完整的发送流程如下：

```
1. 查找并点击附件按钮 (id8)
   └─> 等待 UI 稳定

2. 查找并点击 Favorites 按钮
   └─> 等待 2 秒（Favorites 列表加载）

3. 查找并点击指定索引的收藏项
   └─> 等待 2 秒（分享界面加载）

4. 查找并点击 Send 按钮
   └─> 等待 2 秒（发送完成）

5. 返回成功/失败状态
```

## 性能考虑

- **UI 查找时间**: 每次查找约 100-300ms
- **总耗时**: 约 7-10 秒（包含等待时间）
- **并发**: 不支持并发（需要顺序执行）
- **重试**: 当前不自动重试，需要外部实现

## 扩展建议

### 1. 自动重试机制

```python
async def send_with_retry(sender: ImageSender, favorite_index: int, max_retries: int = 3):
    for attempt in range(max_retries):
        success = await sender.send_via_favorites(favorite_index)
        if success:
            return True
        logger.warning(f"Retry {attempt + 1}/{max_retries}")
        await asyncio.sleep(2)
    return False
```

### 2. 批量发送

```python
async def send_multiple_images(sender: ImageSender, indices: list[int]):
    results = []
    for idx in indices:
        success = await sender.send_via_favorites(idx)
        results.append((idx, success))
        await asyncio.sleep(1)  # 避免过快发送
    return results
```

### 3. 条件发送

```python
async def conditional_send(sender: ImageSender, customer_name: str, keywords: list[str]):
    """根据客户消息关键词决定是否发送图片"""
    # 检查最新消息是否包含关键词
    if any(kw in customer_last_message for kw in keywords):
        return await sender.send_via_favorites(favorite_index=0)
    return False
```

## 测试

### 单元测试

```python
import pytest
from unittest.mock import MagicMock, AsyncMock

@pytest.mark.asyncio
async def test_send_via_favorites_success():
    # Mock WeComService
    wecom_service = MagicMock()
    wecom_service.adb.get_ui_state = AsyncMock(return_value=(None, mock_elements))
    wecom_service.adb.tap = AsyncMock()
    wecom_service.adb.wait = AsyncMock()

    # Create sender
    sender = ImageSender(wecom_service)

    # Test send
    success = await sender.send_via_favorites(favorite_index=0)
    assert success is True
```

### 集成测试

运行原始的 demo 脚本验证功能：

```bash
# 在项目根目录运行
python image_sender_demo.py
```

## 相关文档

- [消息处理模块](./message-handling.md)
- [Follow-up 系统](./followup-*.md)
- [ADB 服务](./adb-service.md)

## 迁移指南

如果你之前使用 `image_sender_demo.py`，迁移步骤：

1. **导入更新**:

   ```python
   # 旧
   from image_sender_demo import ImageSender

   # 新
   from wecom_automation.services.message.image_sender import ImageSender
   ```

2. **功能保持不变** - API 完全兼容，无需修改调用代码

3. **删除旧文件** - 迁移完成后可以删除 `image_sender_demo.py`

## 问题排查

### 问题：图片发送失败，但没有错误日志

**解决**：启用 debug 日志

```python
from wecom_automation.core.logging import get_logger
logger = get_logger("wecom_automation.image_sender")
# 查看日志文件 logs/{hostname}-global.log
```

### 问题：找不到 Favorites 按钮

**解决**：检查 WeCom 语言设置

- 确保 WeCom 语言为英文
- 或修改 `_find_favorites_button()` 添加中文支持

### 问题：点击后没有反应

**解决**：增加等待时间

```python
# 修改 config 中的 ui_stabilization_delay
config = config.with_overrides(ui_stabilization_delay=2.0)
```

## 版本历史

- **v1.0.0** (2026-02-06) - 初始版本，从 demo 迁移到主流程
  - 核心功能：通过 Favorites 发送图片
  - REST API 支持
  - 模块化设计
