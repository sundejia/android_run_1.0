# 实时监测无法获取媒体信息问题分析

## 问题描述

实时监测功能（`response_detector.py`）无法获取图片、视频、音频、表情包等媒体信息，而全量同步功能可以正确处理并存储这些媒体消息到数据库。

用户提供的数据库记录示例表明，全量同步可以正确存储媒体消息：

- ID: 296J
- customer_id: 123
- message_type: **image**
- content: (Null)
- 时间戳等其他字段正常

## 问题分析

### 1. 消息提取方式对比

#### 全量同步 (`customer_syncer.py` / `wecom_service.py`)

全量同步使用 `extract_conversation_messages()` 方法，该方法：

1. **带滚动提取**：滚动到顶部，再滚动下来获取全部消息
2. **内联媒体下载**：在提取过程中实时截图和下载媒体
3. **完整消息处理**：通过 `MessageProcessor` 处理每条消息

```python
# customer_syncer.py - 第 674-692 行
async def _extract_messages(self, with_scroll: bool = True) -> List[Any]:
    if with_scroll:
        # 完整提取：滚动到顶部，再滚动下来获取全部消息
        if hasattr(self._wecom, 'extract_conversation_messages'):
            result = await self._wecom.extract_conversation_messages()
            ...
```

关键：`wecom_service.py` 的 `extract_conversation_messages()` 方法（第 633-1007 行）会：

- 在滚动过程中**内联捕获图片** (`_capture_image_inline`)
- 在滚动过程中**内联下载视频** (`_download_video_inline`)
- 在滚动过程中**内联下载语音** (`_download_voice_inline`)

#### 实时监测 (`response_detector.py`)

实时监测使用 `_extract_visible_messages()` 方法：

```python
# response_detector.py - 第 907-916 行
async def _extract_visible_messages(self, wecom, serial: str) -> List[Any]:
    """提取当前可见消息（不滚动）"""
    try:
        tree = await wecom.adb.get_ui_tree()
        if not tree:
            return []
        return wecom.ui_parser.extract_conversation_messages(tree)  # 只解析 UI 树
    except Exception as e:
        self._logger.warning(f"[{serial}] Failed to extract messages: {e}")
        return []
```

**关键问题**：实时监测只调用了 `ui_parser.extract_conversation_messages(tree)`，这**仅解析 UI 树**，不会：

- ❌ 捕获/下载图片
- ❌ 捕获/下载视频
- ❌ 捕获/下载语音
- ❌ 捕获表情包

### 2. 消息存储流程对比

#### 全量同步使用 MessageProcessor

```python
# customer_syncer.py - 第 224 行
process_result = await self._message_processor.process(msg, context)
```

`MessageProcessor` 会：

1. 根据消息类型处理媒体文件
2. 下载/保存图片到本地
3. 正确设置 `message_type` (image/video/voice/sticker)
4. 将完整记录写入数据库

#### 实时监测直接写入数据库

```python
# response_detector.py - 第 918-994 行
async def _store_messages_to_db(...):
    for msg in messages:
        content = getattr(msg, 'content', '') or ''
        msg_type = getattr(msg, 'message_type', 'text')

        record = MessageRecord(
            customer_id=customer_id,
            content=content,  # 媒体消息的 content 为空或占位符
            message_type=MessageType.TEXT if msg_type == 'text' else MessageType.from_string(msg_type),
            ...
        )
```

**问题**：

1. 虽然能识别 `message_type`（如 image/video），但**没有下载实际媒体文件**
2. 媒体消息的 `content` 字段没有实际内容（图片没有路径，视频没有文件）

### 3. UI 解析器的行为

`ui_parser.py` 的 `extract_conversation_messages()` 方法（第 905-1400 行）确实可以**识别**媒体消息类型：

```python
# ui_parser.py - 第 1344-1367 行
if not content and not voice_duration:
    is_video = video_duration is not None or (has_video_thumbnail and has_play_button)

    if is_video:
        message_type = "video"
        content = f"[Video {video_duration}]" if video_duration else "[Video]"
        image_info = self._find_message_image(all_nodes, screen_width)
    elif has_sticker:
        message_type = "sticker"
        content = "[表情包]"
    else:
        image_info = self._find_message_image(all_nodes, screen_width)
        if image_info:
            message_type = "image"
```

**结论**：UI 解析器可以正确**识别和标记**媒体消息类型，但只返回元数据（如 bounds、类型），**不负责下载实际媒体文件**。

## 根本原因

| 功能     | 消息提取                                                 | 媒体下载                                                                                  | 结果                               |
| -------- | -------------------------------------------------------- | ----------------------------------------------------------------------------------------- | ---------------------------------- |
| 全量同步 | `wecom.extract_conversation_messages()` (带滚动)         | ✅ 内联下载 (`_capture_image_inline`, `_download_video_inline`, `_download_voice_inline`) | 媒体文件保存到本地，路径存入数据库 |
| 实时监测 | `ui_parser.extract_conversation_messages(tree)` (仅解析) | ❌ 无                                                                                     | 只识别类型，无实际媒体文件         |

## 解决方案

### 方案 1：在实时监测中添加内联媒体捕获（推荐）

在 `_extract_visible_messages()` 和 `_store_messages_to_db()` 之间添加媒体捕获逻辑：

```python
async def _capture_media_for_messages(
    self,
    wecom,
    messages: List[Any],
    serial: str,
    customer_id: int,
) -> List[Any]:
    """为消息列表中的媒体消息捕获实际内容"""
    from PIL import Image
    from io import BytesIO

    # 获取输出目录
    output_dir = Path(self._repository._db_path).parent / "conversation_images" / f"customer_{customer_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 截屏一次用于所有图片
    _, screenshot_bytes = await wecom.adb.take_screenshot()
    full_screenshot = Image.open(BytesIO(screenshot_bytes))
    img_width, img_height = full_screenshot.size

    for msg in messages:
        msg_type = getattr(msg, 'message_type', 'text')

        if msg_type == 'image' and hasattr(msg, 'image') and msg.image:
            # 捕获图片
            if msg.image.parse_bounds():
                x1, y1, x2, y2 = msg.image.x1, msg.image.y1, msg.image.x2, msg.image.y2
                if 0 <= x1 < x2 <= img_width and 0 <= y1 < y2 <= img_height:
                    cropped = full_screenshot.crop((x1, y1, x2, y2))
                    filename = f"img_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
                    save_path = output_dir / filename
                    cropped.save(save_path)
                    msg.content = str(save_path)  # 存储路径
                    self._logger.info(f"[{serial}] Captured image: {filename}")

        elif msg_type == 'sticker' and hasattr(msg, 'image') and msg.image:
            # 类似处理表情包
            pass

        elif msg_type == 'video':
            # 视频下载需要点击和交互，实时监测中可能不适合
            # 方案：记录 "[视频消息]" 占位符，或者跳过
            msg.content = "[视频消息]"

        elif msg_type == 'voice':
            # 语音下载需要播放触发缓存
            # 方案：记录语音时长作为占位符
            duration = getattr(msg, 'voice_duration', '')
            msg.content = f"[语音消息 {duration}]"

    return messages
```

修改 `_process_unread_user_with_wait()` 中的调用：

```python
# 在 Step 2 之后，Step 3 之前添加
messages = await self._extract_visible_messages(wecom, serial)
if messages:
    # 新增：捕获媒体内容
    messages = await self._capture_media_for_messages(
        wecom, messages, serial, customer_id
    )
```

### 方案 2：复用全量同步的 MessageProcessor

将 `MessageProcessor` 引入实时监测流程：

```python
from wecom_automation.services.message.processor import MessageProcessor

# 在初始化时创建
self._message_processor = MessageProcessor(repository, wecom_service, ...)

# 在存储消息时使用
for msg in messages:
    process_result = await self._message_processor.process(msg, context)
```

这需要更大的重构，但可以完全复用全量同步的媒体处理逻辑。

### 方案 3：最小化修改 - 仅保留类型标记

如果媒体下载在实时场景中不是关键需求，可以只确保 `message_type` 正确存储：

```python
# 确保 content 字段有意义的占位符
if msg_type == 'image':
    content = content or "[图片消息]"
elif msg_type == 'video':
    content = content or "[视频消息]"
elif msg_type == 'voice':
    duration = getattr(msg, 'voice_duration', '')
    content = content or f"[语音消息 {duration}]"
elif msg_type == 'sticker':
    content = content or "[表情包]"
```

## 推荐方案

**推荐方案 1**，原因：

1. 实时性好：在检测到消息时立即捕获图片
2. 代码改动适中：只需添加一个方法和几行调用
3. 对视频/语音使用占位符（这些需要交互操作，不适合实时场景）
4. 与全量同步的数据格式一致

## 实施步骤

1. 在 `response_detector.py` 中添加 `_capture_media_for_messages()` 方法
2. 修改 `_process_unread_user_with_wait()` 在提取消息后调用该方法
3. 确保 `_store_messages_to_db()` 正确处理带路径的 content 字段
4. 测试验证图片消息可以正确保存

## 相关文件

| 文件                                                                   | 作用                                |
| ---------------------------------------------------------------------- | ----------------------------------- |
| `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py` | 实时监测检测器                      |
| `src/wecom_automation/services/wecom_service.py`                       | 全量同步的消息提取（带内联下载）    |
| `src/wecom_automation/services/ui_parser.py`                           | UI 树解析（识别消息类型）           |
| `src/wecom_automation/services/sync/customer_syncer.py`                | 客户同步器（使用 MessageProcessor） |
| `src/wecom_automation/services/message/processor.py`                   | 消息处理器（处理媒体下载）          |

## 验证方法

1. 启动实时监测
2. 接收包含图片/表情包的消息
3. 检查数据库中的 `messages` 表：
   - `message_type` 是否正确（image/sticker/video/voice）
   - `content` 是否包含文件路径（图片）或占位符（视频/语音）
4. 检查 `conversation_images/customer_XXX/` 目录是否有保存的图片

---

## Bug 修复记录

### 2026-01-23: 修复两个运行时错误

**错误 1**: `name 'subprocess' is not defined`

**现象**：捕获媒体时报错 `Error capturing media for message 2: name 'subprocess' is not defined`

**根本原因**：在 `_capture_media_for_messages()` 方法中，`subprocess` 导入语句位于其他导入语句之后（第 959 行），当 try 块内的前置代码抛出异常时，错误处理代码无法使用 `subprocess` 模块。

**修复方案**：将 `import subprocess` 移动到方法开头，确保在任何后续代码之前导入：

```python
# 修复前
from PIL import Image
from io import BytesIO
from datetime import datetime
import subprocess  # 太晚了，可能未执行到这里

# 修复后
import subprocess  # 最先导入
from PIL import Image
from io import BytesIO
from datetime import datetime
```

---

**错误 2**: `unsupported operand type(s) for +: 'int' and 'tuple'`

**现象**：处理用户时报错，例如 `Error processing 孙德豪 (...): unsupported operand type(s) for +: 'int' and 'tuple'`

**根本原因**：`_interactive_wait_loop()` 方法中（第 822-823 行），代码直接将 `_store_messages_to_db()` 的返回值与整数相加：

```python
stored = await self._store_messages_to_db(...)
result['messages_stored'] += stored  # BUG: stored 是 tuple，不是 int
```

但 `_store_messages_to_db()` 返回的是 `tuple[int, List[int]]`（第 1593 行），而不是单个 `int`。

**修复方案**：正确解包返回的元组：

```python
# 修复前
stored = await self._store_messages_to_db(...)
result['messages_stored'] += stored

# 修复后
stored_count, _ = await self._store_messages_to_db(...)
result['messages_stored'] += stored_count
```

---

**修复文件**：`wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`

**修复行号**：

- 第 955-959 行（subprocess 导入位置）
- 第 822-823 行（元组解包）
