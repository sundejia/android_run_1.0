# 表情包消息支持实现指南

## 概述

本文档描述如何在 WeCom 自动化系统中添加对表情包（Sticker）消息的支持。

### 需求说明

1. **存储方式**: 表情包按照图片方式存储（截图保存）
2. **数据库标识**: 写入数据库时 `message_type` 为 `"sticker"`，`content` 为 `"[表情包]"`
3. **前端支持**: 在 History 和 Conversation 界面中正确显示表情包

### UI Tree 特征分析

根据测试分析，图片和表情包在 WeCom UI Tree 中的关键区别：

| 特征           | 图片 (Image)                | 表情包 (Sticker)                |
| -------------- | --------------------------- | ------------------------------- |
| **className**  | `android.widget.ImageView`  | `android.widget.RelativeLayout` |
| **resourceId** | `com.tencent.wework:id/k1r` | `com.tencent.wework:id/igf`     |
| **典型尺寸**   | 405x306                     | 423x450                         |

---

## 一、数据库层改动

### 1.1 添加 MessageType 枚举

修改 `src/wecom_automation/database/models.py`：

```python
class MessageType(str, Enum):
    """Enumeration of supported message types."""
    TEXT = "text"
    VOICE = "voice"
    IMAGE = "image"
    VIDEO = "video"
    STICKER = "sticker"  # 新增：表情包
    FILE = "file"
    LINK = "link"
    LOCATION = "location"
    SYSTEM = "system"
    UNKNOWN = "unknown"
```

### 1.2 数据库存储说明

表情包消息复用 `images` 表存储文件，通过 `message_type = 'sticker'` 区分。

**messages 表记录**：

```sql
INSERT INTO messages (customer_id, content, message_type, is_from_kefu, ...)
VALUES (123, '[表情包]', 'sticker', 0, ...);
```

**images 表记录**：

```sql
INSERT INTO images (message_id, file_path, file_name, original_bounds, ...)
VALUES (456, 'conversation_images/customer_123/sticker_456_20260122_163000.png', ...);
```

---

## 二、UI 解析层改动

### 2.1 修改 UIParser 识别逻辑

修改 `src/wecom_automation/services/ui_parser.py`：

```python
# 在 _extract_message_from_row 方法中添加表情包检测

def _extract_message_from_row(self, row: dict, screen_width: int = 1080) -> Optional[ConversationMessage]:
    """从消息行节点提取消息"""

    # ... 现有代码 ...

    # 新增：表情包检测变量
    has_sticker = False
    sticker_bounds = None

    for node in all_nodes:
        rid = (node.get("resourceId") or "").lower()
        class_name = (node.get("className") or "").lower()
        node_bounds = self._get_node_bounds(node)

        # ... 现有的图片/视频检测代码 ...

        # 新增：表情包检测 (igf resource id + RelativeLayout)
        if "igf" in rid and "relativelayout" in class_name:
            has_sticker = True
            sticker_bounds = node_bounds
            continue

    # ... 现有代码 ...

    # 新增：在确定消息类型时检查表情包
    if not content and not voice_duration:
        # 先检查视频
        is_video = video_duration is not None or (has_video_thumbnail and has_play_button)

        if is_video:
            message_type = "video"
            # ... 现有视频处理 ...
        elif has_sticker:
            # 表情包消息
            message_type = "sticker"
            content = "[表情包]"
            # 使用表情包bounds创建ImageInfo用于截图
            if sticker_bounds:
                image_info = ImageInfo(bounds=sticker_bounds)
        else:
            # 普通图片
            image_info = self._find_message_image(all_nodes, screen_width)
            if image_info:
                message_type = "image"
```

### 2.2 完整的表情包检测函数

在 `ui_parser.py` 中添加辅助方法：

```python
def _is_sticker_element(self, node: dict) -> bool:
    """
    判断节点是否为表情包元素

    表情包特征:
    - resourceId 包含 "igf"
    - className 为 RelativeLayout
    - 没有子元素 (childCount = 0)
    - 可点击和长按
    """
    rid = (node.get("resourceId") or "").lower()
    class_name = (node.get("className") or "").lower()
    child_count = node.get("childCount", -1)
    is_clickable = node.get("isClickable", False)
    is_long_clickable = node.get("isLongClickable", False)

    return (
        "igf" in rid and
        "relativelayout" in class_name and
        child_count == 0 and
        is_clickable and
        is_long_clickable
    )

def _find_sticker_in_row(self, all_nodes: list) -> Optional[str]:
    """
    在消息行中查找表情包元素

    Returns:
        表情包的 bounds 字符串，如果没有找到则返回 None
    """
    for node in all_nodes:
        if self._is_sticker_element(node):
            return self._get_node_bounds(node)
    return None
```

---

## 三、消息处理器层改动

### 3.1 创建表情包消息处理器

新建文件 `src/wecom_automation/services/message/handlers/sticker.py`：

```python
"""
表情包消息处理器

处理表情包消息的识别、保存和存储。
表情包按照图片方式存储，但 message_type 标记为 'sticker'。
"""

import json
from pathlib import Path
from typing import Any, Optional

from wecom_automation.core.interfaces import MessageContext, MessageProcessResult
from wecom_automation.database.models import MessageRecord, MessageType
from wecom_automation.database.repository import ConversationRepository
from wecom_automation.services.message.handlers.base import BaseMessageHandler
from wecom_automation.services.message.image_storage import ImageStorageHelper


class StickerMessageHandler(BaseMessageHandler):
    """
    表情包消息处理器

    职责:
    - 识别表情包消息
    - 截图保存表情包到本地（复用图片存储逻辑）
    - 创建消息和图片记录，message_type 为 'sticker'
    """

    def __init__(
        self,
        repository: ConversationRepository,
        wecom_service,
        images_dir: Path,
        logger=None
    ):
        """
        初始化表情包消息处理器

        Args:
            repository: 数据库仓库
            wecom_service: WeComService 实例
            images_dir: 图片/表情包保存目录
            logger: 日志记录器
        """
        super().__init__(repository, logger)
        self._wecom = wecom_service
        self._images_dir = Path(images_dir)
        self._images_dir.mkdir(parents=True, exist_ok=True)

        # 复用图片存储辅助类
        self._storage = ImageStorageHelper(
            repository=repository,
            images_dir=self._images_dir,
            logger=logger
        )

    async def can_handle(self, message: Any) -> bool:
        """
        判断是否为表情包消息

        Args:
            message: 消息对象

        Returns:
            True 如果是表情包消息
        """
        msg_type = self._get_message_type(message)
        return msg_type in ("sticker", "STICKER", "表情包")

    async def process(
        self,
        message: Any,
        context: MessageContext
    ) -> MessageProcessResult:
        """
        处理表情包消息

        Args:
            message: 消息对象
            context: 消息上下文

        Returns:
            处理结果
        """
        # 获取表情包 bounds（复用 image 属性）
        sticker_bounds = None
        if hasattr(message, 'image') and message.image:
            sticker_bounds = message.image.bounds if hasattr(message.image, 'bounds') else None

        # 解析时间戳
        timestamp_raw, timestamp_parsed = self._get_parsed_timestamp(message)

        # 创建消息记录
        extra_info = {}
        if sticker_bounds:
            extra_info['original_bounds'] = sticker_bounds
        extra_info['is_sticker'] = True  # 标记为表情包

        record = MessageRecord(
            customer_id=context.customer_id,
            content="[表情包]",  # 表情包内容标识
            message_type=MessageType.STICKER.value,  # 使用 sticker 类型
            is_from_kefu=self._is_from_kefu(message),
            timestamp_raw=timestamp_raw,
            timestamp_parsed=timestamp_parsed,
            extra_info=json.dumps(extra_info) if extra_info else None,
        )

        # 保存到数据库
        added, msg_record = self._repository.add_message_if_not_exists(record)

        if not added:
            self._logger.debug("Sticker message skipped (duplicate)")
            return MessageProcessResult(
                added=False,
                message_type="sticker",
                message_id=msg_record.id if msg_record else None,
            )

        # 保存表情包文件（截图方式，复用图片存储逻辑）
        sticker_path = None

        if not sticker_bounds:
            self._logger.warning(
                f"No sticker_bounds for message, cannot save sticker. "
                f"customer={context.customer_name}, message_id={msg_record.id if msg_record else 'N/A'}"
            )
        elif not msg_record:
            self._logger.warning(
                f"No message record created, cannot save sticker. "
                f"customer={context.customer_name}"
            )
        else:
            # 检查是否有预捕获的图片
            existing_path = None
            if hasattr(message, 'image') and message.image and hasattr(message.image, 'local_path'):
                if message.image.local_path:
                    existing_path = Path(message.image.local_path)
                    if existing_path.exists():
                        self._logger.info(f"Using pre-captured sticker: {existing_path}")

            if existing_path and existing_path.exists():
                # 复制预捕获的表情包到正确目录
                sticker_path = self._storage.save_image_from_source(
                    source_path=existing_path,
                    customer_id=context.customer_id,
                    message_id=msg_record.id,
                    bounds=sticker_bounds,
                )
            elif sticker_bounds:
                # 使用 bounds 截图
                self._logger.warning("Falling back to bounds-based capture for sticker")
                sticker_path = await self._storage.save_image_from_bounds(
                    wecom_service=self._wecom,
                    customer_id=context.customer_id,
                    message_id=msg_record.id,
                    bounds=sticker_bounds,
                )

        # 日志
        if sticker_path:
            self._logger.info(
                f"Sticker saved successfully: customer={context.customer_name}, "
                f"path={sticker_path}"
            )
        else:
            self._logger.warning(
                f"Sticker NOT saved: customer={context.customer_name}, "
                f"reason={'missing bounds or capture failed' if sticker_bounds else 'missing sticker_bounds'}"
            )

        return MessageProcessResult(
            added=True,
            message_type="sticker",
            message_id=msg_record.id if msg_record else None,
            extra={"path": str(sticker_path) if sticker_path else None},
        )
```

### 3.2 注册处理器

修改 `src/wecom_automation/services/message/processor.py`，添加表情包处理器：

```python
from wecom_automation.services.message.handlers.sticker import StickerMessageHandler

class MessageProcessor:
    def __init__(self, ...):
        # ... 现有代码 ...

        # 注册处理器（顺序很重要，sticker 应该在 image 之前）
        self._handlers = [
            VoiceMessageHandler(...),
            VideoMessageHandler(...),
            StickerMessageHandler(  # 新增：表情包处理器
                repository=repository,
                wecom_service=wecom_service,
                images_dir=images_dir,
                logger=logger
            ),
            ImageMessageHandler(...),  # 图片处理器放在表情包之后
            TextMessageHandler(...),
        ]
```

---

## 四、前端改动

### 4.1 API 类型定义

修改 `wecom-desktop/src/services/api.ts`，添加表情包类型支持：

```typescript
// 表情包和图片共用 ImageInfo 类型
export interface ImageInfo {
  image_id: number
  message_id: number
  file_name: string | null
  file_path: string
  width: number | null
  height: number | null
  original_bounds: string | null
}

// 消息类型枚举
export type MessageType =
  | 'text'
  | 'voice'
  | 'image'
  | 'video'
  | 'sticker'
  | 'file'
  | 'link'
  | 'system'
  | 'unknown'
```

### 4.2 CustomerDetailView.vue 改动

修改 `wecom-desktop/src/views/CustomerDetailView.vue`：

```vue
<script setup lang="ts">
// ... 现有代码 ...

// 判断是否为媒体消息（包含表情包）
function isMediaMessage(messageType: string): boolean {
  return ['image', 'video', 'voice', 'sticker'].includes(messageType)
}

// 获取表情包信息（复用图片接口）
function getStickerInfo(messageId: number): ImageInfo | null | undefined {
  return getImageInfo(messageId) // 表情包复用图片的获取逻辑
}
</script>

<template>
  <!-- ... 现有模板代码 ... -->

  <!-- 在消息列表中添加表情包渲染 -->

  <!-- 表情包消息（复用图片显示组件，但显示不同图标） -->
  <div v-else-if="msg.message_type === 'sticker'" class="mt-2">
    <div
      class="relative inline-block rounded-lg overflow-hidden bg-wecom-darker border border-wecom-border"
      :class="
        getImageInfo(msg.id)?.image_id
          ? 'cursor-pointer hover:border-wecom-primary group'
          : 'opacity-60'
      "
      @click.stop="getImageInfo(msg.id)?.image_id ? openImageViewer(getImageInfo(msg.id)!) : null"
    >
      <!-- 表情包缩略图 -->
      <div
        v-if="getImageInfo(msg.id)?.image_id"
        class="max-w-[150px] max-h-[150px] overflow-hidden"
      >
        <img
          :src="getImageUrl(getImageInfo(msg.id)!.image_id)"
          :alt="getImageInfo(msg.id)?.file_name || 'Sticker'"
          class="w-auto h-auto max-w-[150px] max-h-[150px] object-contain hover:scale-105 transition-transform duration-200"
        />
      </div>

      <!-- 占位符 -->
      <div
        v-else
        class="w-32 h-32 flex items-center justify-center bg-gradient-to-br from-wecom-dark to-wecom-darker"
      >
        <span class="text-4xl">😀</span>
      </div>

      <!-- 加载指示器 -->
      <div
        v-if="isImageLoading(msg.id)"
        class="absolute inset-0 flex items-center justify-center bg-black/30"
      >
        <span class="text-white text-sm animate-pulse">Loading...</span>
      </div>

      <!-- 无文件指示器 -->
      <div
        v-else-if="getImageInfo(msg.id) === null"
        class="absolute inset-0 flex items-center justify-center bg-black/30"
      >
        <span class="text-white/70 text-xs px-2 py-1 bg-black/50 rounded">No sticker file</span>
      </div>

      <!-- 表情包标识 -->
      <div class="absolute top-2 left-2 px-2 py-0.5 bg-yellow-500/80 text-white text-xs rounded">
        表情包
      </div>
    </div>

    <!-- 内容文本 -->
    <p v-if="msg.content && msg.content !== '[表情包]'" class="text-wecom-text mt-2 text-sm">
      {{ msg.content }}
    </p>
  </div>

  <!-- ... 其他消息类型 ... -->
</template>
```

### 4.3 ResourcesView.vue 改动

修改 `wecom-desktop/src/views/ResourcesView.vue`（如果存在），添加表情包过滤选项：

```vue
<script setup lang="ts">
// 资源类型过滤
const resourceTypes = ref([
  { value: 'all', label: 'All' },
  { value: 'image', label: 'Images' },
  { value: 'sticker', label: 'Stickers' }, // 新增
  { value: 'video', label: 'Videos' },
  { value: 'voice', label: 'Voice' },
])
</script>

<template>
  <!-- 资源列表中为表情包添加特殊标识 -->
  <div v-for="resource in filteredResources" :key="resource.id" class="resource-item">
    <!-- 表情包显示 -->
    <div v-if="resource.message_type === 'sticker'" class="relative">
      <img :src="resource.thumbnail_url" class="w-20 h-20 object-cover rounded" />
      <span class="absolute top-1 left-1 px-1 py-0.5 bg-yellow-500 text-white text-xs rounded">
        表情包
      </span>
    </div>
    <!-- 图片显示 -->
    <div v-else-if="resource.message_type === 'image'">
      <img :src="resource.thumbnail_url" class="w-20 h-20 object-cover rounded" />
    </div>
  </div>
</template>
```

---

## 五、后端 API 改动

### 5.1 消息类型统计

修改 `wecom-desktop/backend/routers/customers.py`，确保消息统计包含表情包：

```python
@router.get("/{customer_id}/messages/breakdown")
async def get_message_breakdown(customer_id: int):
    """获取消息类型分布"""
    # 现有代码已经通过 GROUP BY message_type 自动包含 sticker
    # 无需额外改动
    pass
```

### 5.2 资源 API

修改 `wecom-desktop/backend/routers/resources.py`，支持按类型过滤：

```python
@router.get("/images")
async def list_images(
    customer_id: Optional[int] = None,
    message_type: Optional[str] = None,  # 新增：支持 'image' 或 'sticker'
    page: int = 1,
    page_size: int = 20
):
    """
    获取图片/表情包列表

    Args:
        message_type: 可选，'image' 只返回图片，'sticker' 只返回表情包，
                     不指定则返回全部
    """
    query = """
        SELECT i.*, m.message_type
        FROM images i
        JOIN messages m ON i.message_id = m.id
        WHERE 1=1
    """
    params = []

    if customer_id:
        query += " AND m.customer_id = ?"
        params.append(customer_id)

    if message_type:
        query += " AND m.message_type = ?"
        params.append(message_type)

    # ... 分页和执行 ...
```

---

## 六、测试计划

### 6.1 单元测试

创建 `tests/unit/test_sticker_handler.py`：

```python
import pytest
from unittest.mock import Mock, AsyncMock
from wecom_automation.services.message.handlers.sticker import StickerMessageHandler
from wecom_automation.database.models import MessageType


class TestStickerHandler:
    """表情包处理器测试"""

    @pytest.fixture
    def handler(self):
        repo = Mock()
        wecom = Mock()
        return StickerMessageHandler(repo, wecom, "/tmp/images")

    @pytest.mark.asyncio
    async def test_can_handle_sticker(self, handler):
        """测试识别表情包消息"""
        msg = Mock()
        msg.message_type = "sticker"
        assert await handler.can_handle(msg) is True

    @pytest.mark.asyncio
    async def test_can_handle_image(self, handler):
        """测试不处理普通图片"""
        msg = Mock()
        msg.message_type = "image"
        assert await handler.can_handle(msg) is False

    @pytest.mark.asyncio
    async def test_process_creates_correct_record(self, handler):
        """测试创建正确的消息记录"""
        # ... 测试实现 ...
```

### 6.2 集成测试

创建测试脚本 `test_sticker_detection.py`：

```python
"""测试表情包检测功能"""

import asyncio
from wecom_automation.core.config import Config
from wecom_automation.services.wecom_service import WeComService


async def test_sticker_detection():
    """测试在聊天界面检测表情包"""
    config = Config(device_serial=None, debug=True)
    service = WeComService(config)
    await service.connect()

    # 获取当前屏幕的消息
    messages = await service.get_conversation_messages()

    # 统计消息类型
    sticker_count = sum(1 for m in messages if m.message_type == "sticker")
    image_count = sum(1 for m in messages if m.message_type == "image")

    print(f"检测到 {sticker_count} 条表情包消息")
    print(f"检测到 {image_count} 条图片消息")

    # 打印表情包详情
    for msg in messages:
        if msg.message_type == "sticker":
            print(f"  - 表情包: bounds={msg.image.bounds if msg.image else 'N/A'}")


if __name__ == "__main__":
    asyncio.run(test_sticker_detection())
```

---

## 七、实现步骤总结

### Phase 1: 后端基础支持 (预计 2 小时)

1. [ ] 添加 `MessageType.STICKER` 枚举
2. [ ] 修改 `ui_parser.py` 添加表情包检测逻辑
3. [ ] 创建 `StickerMessageHandler` 处理器
4. [ ] 注册处理器到 `MessageProcessor`
5. [ ] 测试表情包检测和存储

### Phase 2: 前端显示支持 (预计 1.5 小时)

1. [ ] 更新 API 类型定义
2. [ ] 修改 `CustomerDetailView.vue` 添加表情包渲染
3. [ ] 修改 `ResourcesView.vue` 支持表情包过滤
4. [ ] 测试前端显示

### Phase 3: 测试和文档 (预计 1 小时)

1. [ ] 编写单元测试
2. [ ] 编写集成测试
3. [ ] 更新 API 文档
4. [ ] 完成本实现文档

---

## 八、注意事项

1. **兼容性**: 表情包复用图片的存储和显示逻辑，确保向后兼容
2. **性能**: 表情包文件通常较小，但仍需注意批量截图的性能
3. **去重**: 表情包的 hash 计算需要包含 bounds，避免相同表情包被视为重复
4. **UI 一致性**: 表情包在前端应有明显的视觉区分（如黄色标签）

---

## 九、相关文件

| 文件                                                        | 改动类型 | 说明              |
| ----------------------------------------------------------- | -------- | ----------------- |
| `src/wecom_automation/database/models.py`                   | 修改     | 添加 STICKER 枚举 |
| `src/wecom_automation/services/ui_parser.py`                | 修改     | 添加表情包检测    |
| `src/wecom_automation/services/message/handlers/sticker.py` | 新建     | 表情包处理器      |
| `src/wecom_automation/services/message/processor.py`        | 修改     | 注册处理器        |
| `wecom-desktop/src/services/api.ts`                         | 修改     | 类型定义          |
| `wecom-desktop/src/views/CustomerDetailView.vue`            | 修改     | 表情包渲染        |
| `wecom-desktop/src/views/ResourcesView.vue`                 | 修改     | 表情包过滤        |
| `tests/unit/test_sticker_handler.py`                        | 新建     | 单元测试          |
