# 实时回复只保存客服消息，客户消息未保存问题分析

## 问题描述

在实时回复功能（FollowUp）运行时，数据库 `messages` 表中只保存了客服（kefu）发送的消息，客户的消息没有被保存。

### 症状表现

从数据库截图可以看到：

- 所有记录的 `is_from_kefu` 字段都是 `1`（表示客服消息）
- 没有 `is_from_kefu = 0` 的记录（客户消息）
- 消息内容都是客服发送的内容

**用户反馈**：问题是在昨晚修改代码（添加实时回复支持图片/表情包/视频）后才出现的。

---

## 🔴 核心问题发现

### ⚠️ 真正的根因（从日志发现）

从日志截图中发现了**真正的错误**：

```
[WARNING] [AN2FVB17060003302] [1/1] ❌ Error: MessageContext.__init__() missing 1 required positional argument: 'channel'
```

**问题**：在 `_store_messages_to_db()` 方法中创建 `MessageContext` 时，缺少了 `channel` 参数！

**原始代码**（第 1011-1017 行）：

```python
context = MessageContext(
    customer_id=customer_id,
    customer_name=user_name,
    device_serial=serial,
    kefu_name=None,  # Will be auto-detected  ← 这里也有问题！kefu_name 不允许 None
)
# 缺少 channel=user_channel 参数！
```

**`MessageContext` 的定义**（`interfaces.py` 第 177-192 行）：

```python
@dataclass
class MessageContext:
    customer_id: int
    customer_name: str
    channel: Optional[str]  # ← 必需参数，没有默认值！
    kefu_name: str          # ← 必需参数，不能是 None！
    device_serial: str
```

### 次要问题：处理器注册顺序（已修复）

**问题流程**：

```
消息 (type="text", is_self=False, content="你好")
    ↓
ImageMessageHandler.can_handle() → 检查 message.image.bounds
    ↓
如果 message.image 存在（即使 bounds 为空），返回 True
    ↓
ImageMessageHandler.process() 执行
    ↓
调用 save_image_from_bounds(wecom_service, ...)
    ↓
如果 wecom_service.screenshot_element() 抛出异常
    ↓
异常在 MessageProcessor.process() 中被捕获 (第 125-130 行)
    ↓
"继续尝试其他处理器" 但消息已被标记为处理完成
    ↓
客户消息丢失！
```

### 具体问题点

1. **`ImageMessageHandler.can_handle()` 条件过于宽松**（image.py 第 73 行）：

   ```python
   if hasattr(message, 'image') and message.image and message.image.bounds:
       return True
   ```

   只要 `message.image` 存在且有 `bounds`，就会处理，即使它是文本消息。

2. **异常后消息处理不当**：当处理器抛出异常时，`MessageProcessor.process()` 会 `continue` 到下一个处理器，但如果所有处理器都失败，消息就会丢失。

3. **缺少 `StickerMessageHandler`**：昨晚的修改添加了表情包支持，但 `_register_message_handlers()` 中**没有注册 `StickerMessageHandler`**。

---

## 🟢 修复方案

### 修复 1: 修正处理器注册顺序

将 `TextMessageHandler` 注册为**默认回退处理器**，确保它在其他处理器之后注册：

```python
async def _register_message_handlers(self, processor, wecom, serial: str):
    """注册消息处理器（与全量同步保持一致）"""
    from wecom_automation.services.message.handlers.image import ImageMessageHandler
    from wecom_automation.services.message.handlers.video import VideoMessageHandler
    from wecom_automation.services.message.handlers.voice import VoiceMessageHandler
    from wecom_automation.services.message.handlers.text import TextMessageHandler
    from wecom_automation.services.message.handlers.sticker import StickerMessageHandler  # 新增
    from wecom_automation.core.config import get_project_root

    project_root = get_project_root()

    # Register Text Handler FIRST (most common, fast check)
    text_handler = TextMessageHandler(
        repository=processor._repository,
        logger=self._logger,
    )
    processor.register_handler(text_handler)

    # Register Sticker Handler (NEW - before image to avoid confusion)
    sticker_handler = StickerMessageHandler(
        repository=processor._repository,
        wecom_service=wecom,
        images_dir=project_root / "conversation_images",
        logger=self._logger,
    )
    processor.register_handler(sticker_handler)

    # ... 其余处理器
```

### 修复 2: 增强异常处理

在 `_store_messages_to_db()` 中增强异常处理，确保即使处理器失败也能保存消息：

```python
for idx, msg in enumerate(messages):
    try:
        result = await processor.process(msg, context)
        # ...
    except Exception as msg_error:
        self._logger.warning(f"[{serial}]    [{idx+1}/{len(messages)}] ❌ Error: {msg_error}")
        # 新增：异常时作为纯文本消息保存
        try:
            fallback_result = await self._save_as_text_fallback(msg, context)
            if fallback_result.added:
                stored_count += 1
        except Exception as fallback_error:
            self._logger.error(f"[{serial}] Fallback save also failed: {fallback_error}")
```

### 修复 3: 增加调试日志

在处理每条消息前输出详细信息：

```python
self._logger.info(
    f"[{serial}]    Processing msg {idx+1}: is_self={is_self}, type={msg_type}, "
    f"has_image={hasattr(msg, 'image') and msg.image is not None}"
)
```

---

### 2. `is_self` 判断逻辑

消息的发送者是通过 `ui_parser.py` 的 `_extract_message_from_row()` 方法判断的：

```python
# ui_parser.py - 第 1304-1315 行
if avatar_on_left:
    is_self = False  # 客户消息（左侧头像）
elif avatar_on_right:
    is_self = True   # 客服消息（右侧头像）
elif content_x is not None:
    is_self = content_x > screen_width // 2  # 根据内容位置判断
```

**关键点**：在企业微信中，客服发送的消息在右侧（`is_self=True`），客户发送的消息在左侧（`is_self=False`）。

### 3. 消息处理器的 `is_from_kefu` 判断

消息处理器使用 `_is_from_kefu()` 方法判断消息来源：

```python
# base.py - 第 133-148 行
def _is_from_kefu(self, message: Any) -> bool:
    if hasattr(message, 'is_self'):
        return message.is_self
    if hasattr(message, 'is_from_kefu'):
        return message.is_from_kefu
    return False
```

**逻辑**：`is_self=True` → `is_from_kefu=True`（客服消息）

## 根本原因分析

经过代码审查，我发现了以下**可能的根本原因**：

### 可能原因 1: 客户消息被过滤或跳过

在 `TextMessageHandler` 中（第 82-92 行），有一段针对**客服消息**的去重逻辑：

```python
# 对于客服消息，先检查是否已存在相同内容
if is_from_kefu and content:
    if self._repository.check_kefu_message_exists(...):
        return MessageProcessResult(added=False, ...)
```

这段逻辑只针对客服消息进行去重，**客户消息不受影响**。但是需要验证 `is_self` 属性是否正确传递。

### 可能原因 2: UI 解析器位置判断错误

在 `ui_parser.py` 中，`is_self` 的判断基于：

1. 头像位置（avatar_x）
2. 内容位置（content_x）
3. 屏幕宽度（screen_width）

如果 **screen_width 检测错误** 或 **坐标解析错误**，可能导致所有消息都被判断为客服消息。

### 可能原因 3: 消息去重导致客户消息被跳过

在 `_store_messages_to_db()` 调用 `MessageProcessor.process()` 时，消息会经过去重检查：

```python
# repository.add_message_if_not_exists(record)
```

如果客户消息的去重逻辑有 bug（例如 hash 计算错误），可能导致客户消息被误判为已存在而跳过。

### 可能原因 4: 日志中可以看到问题

从 `response_detector.py` 的日志输出来看（第 1025-1028 行）：

```python
self._logger.info(
    f"[{serial}]    [{idx+1}/{len(messages)}] ✅ {msg_label} stored: {content}... "
    f"(type={msg_type}, db_id={result.message_id})"
)
```

日志应该显示 `👨 CUSTOMER` 或 `👤 KEFU`，可以通过检查日志来确认问题。

## 详细诊断步骤

### 步骤 1: 检查日志输出

在 `scanner.log` 或 `followup.log` 中搜索以下关键词：

- `👨 CUSTOMER stored` - 客户消息存储成功
- `👤 KEFU stored` - 客服消息存储成功
- `Storage summary` - 存储摘要

### 步骤 2: 验证消息提取

在 `_extract_visible_messages()` 调用后，添加调试日志：

```python
for msg in messages:
    self._logger.info(
        f"Extracted: is_self={msg.is_self}, type={msg.message_type}, "
        f"content={msg.content[:30] if msg.content else 'None'}"
    )
```

### 步骤 3: 验证 screen_width

检查日志中的 `screen_width` 值是否正确（通常为 1080 或 1440）。

## 可能的解决方案

### 方案 1: 检查并修复 `is_self` 判断逻辑

1. 在 `_extract_visible_messages()` 之后添加日志，输出每条消息的 `is_self` 值
2. 验证头像位置和内容位置是否正确检测
3. 如果发现问题，修复 `ui_parser.py` 中的位置判断逻辑

### 方案 2: 检查消息去重逻辑

1. 检查 `add_message_if_not_exists()` 方法的去重条件
2. 验证客户消息是否被误判为重复
3. 如果发现问题，调整去重条件

### 方案 3: 强制记录所有消息

作为临时解决方案，可以在 `_store_messages_to_db()` 中添加强制记录逻辑：

```python
# 如果检测到客户消息未被保存，强制记录
if not is_self and not result.added:
    self._logger.warning(f"Customer message not saved: {content[:30]}...")
```

## 相关代码文件

| 文件                                                                   | 作用                                   |
| ---------------------------------------------------------------------- | -------------------------------------- |
| `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py` | 实时回复检测器主逻辑                   |
| `src/wecom_automation/services/ui_parser.py`                           | UI 树解析，`is_self` 判断              |
| `src/wecom_automation/services/message/processor.py`                   | 消息处理器入口                         |
| `src/wecom_automation/services/message/handlers/text.py`               | 文本消息处理器                         |
| `src/wecom_automation/services/message/handlers/base.py`               | 消息处理器基类，`_is_from_kefu()` 方法 |
| `src/wecom_automation/database/repository.py`                          | 数据库操作，消息去重                   |

## 调试建议

### 1. 增强日志输出

在 `response_detector.py` 的 `_store_messages_to_db()` 方法开头添加：

```python
# 详细输出每条消息的属性
for idx, msg in enumerate(messages):
    is_self = getattr(msg, 'is_self', 'UNKNOWN')
    content = (getattr(msg, 'content', '') or '')[:50]
    self._logger.info(f"[DEBUG] Message {idx}: is_self={is_self}, content={content}")
```

### 2. 检查数据库存储结果

在存储后检查返回值：

```python
result = await processor.process(msg, context)
if not result.added:
    self._logger.warning(f"Message not added: is_self={is_self}, reason=duplicate?")
```

### 3. 验证 UI 解析

直接打印 UI 树中的头像位置和内容位置，确认位置检测是否正确。

## 下一步行动

1. **启用详细日志**：添加上述调试日志
2. **重现问题**：在实时回复模式下进行测试
3. **分析日志**：检查是否有 `👨 CUSTOMER` 消息被跳过
4. **修复问题**：根据日志分析结果定位并修复问题

---

## 深入分析：核心问题定位

### 从截图分析

从截图中可以看到数据库 `messages` 表的记录：

- 所有记录的 `is_from_kefu` 字段都是 `1`
- 消息内容基本都是客服发送的内容
- 没有看到客户发送的消息（`is_from_kefu = 0`）

### 消息保存的两个路径

在 `response_detector.py` 中，消息有两个保存入口：

1. **`_store_messages_to_db()` - 第 591 行**：存储提取到的所有消息（包括客户和客服）
2. **`_store_sent_message()` - 第 650 行**：存储 AI 发送的回复消息（仅客服消息）

```python
# 第 591 行：保存提取的所有消息
stored_count, message_db_ids = await self._store_messages_to_db(...)

# 第 650 行：保存 AI 回复
reply_db_id = await self._store_sent_message(...)
```

### 可能的问题 1：`_store_messages_to_db()` 未正常工作

如果 `_store_messages_to_db()` 方法中的 `MessageProcessor` 处理失败或跳过客户消息，而 `_store_sent_message()` 正常工作，就会导致只有客服消息被保存。

### 可能的问题 2：消息去重逻辑过于激进

`MessageRecord.compute_hash()` 方法使用以下字段计算 hash：

- `customer_id`
- `content`（或 `image_bounds`）
- `message_type`
- `is_from_kefu`
- `timestamp_bucket`（30 分钟桶）
- `sequence`
- `ui_position`

如果客户消息的这些字段组合产生了相同的 hash，就会被认为是重复消息而跳过。

### 可能的问题 3：UI 解析器的 `is_self` 判断错误

在 `ui_parser.py` 的 `_extract_message_from_row()` 方法中（第 1304-1315 行），`is_self` 的判断逻辑：

```python
if avatar_on_left:
    is_self = False  # 客户消息
elif avatar_on_right:
    is_self = True   # 客服消息
elif content_x is not None:
    is_self = content_x > screen_width // 2  # 基于内容位置
```

**潜在问题**：

- 如果 `screen_width` 检测错误
- 如果所有消息的 `content_x` 都大于 `screen_width // 2`
- 如果头像检测失败

可能导致所有消息都被判断为 `is_self=True`。

### 验证方法

1. **检查日志输出**：
   搜索日志中的 `👨 CUSTOMER stored` 和 `👤 KEFU stored` 关键词

2. **直接查询数据库**：

   ```sql
   -- 查看最近的消息，检查 is_from_kefu 分布
   SELECT is_from_kefu, COUNT(*) as count
   FROM messages
   GROUP BY is_from_kefu;

   -- 查看客户消息
   SELECT * FROM messages WHERE is_from_kefu = 0 ORDER BY id DESC LIMIT 20;
   ```

3. **检查消息提取**：
   在 `_store_messages_to_db()` 开头添加日志，输出每条消息的 `is_self` 值

4. **检查 hash 冲突**：
   ```sql
   -- 查看是否有相同 hash 的消息
   SELECT message_hash, COUNT(*) as count
   FROM messages
   GROUP BY message_hash
   HAVING count > 1;
   ```

### 推荐的调试步骤

1. **添加日志输出**：在 `_store_messages_to_db()` 方法开头添加：

   ```python
   for idx, msg in enumerate(messages):
       is_self = getattr(msg, 'is_self', 'UNKNOWN')
       content = (getattr(msg, 'content', '') or '')[:30]
       self._logger.info(f"[DEBUG] Message {idx}: is_self={is_self}, content={content}...")
   ```

2. **验证 MessageProcessor 结果**：在处理每条消息后检查 `result.added` 的值

3. **检查 UI 解析**：临时打印 `screen_width`、`avatar_x`、`content_x` 等值

---

## ✅ 已实施的修复

### 🔧 修复 1（核心修复）: 补全 MessageContext 参数

**问题**：`MessageContext` 初始化时缺少 `channel` 参数，导致所有消息都无法保存！

**文件**: `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`

**修改**（第 1011-1018 行）：

```python
# 之前（错误）:
context = MessageContext(
    customer_id=customer_id,
    customer_name=user_name,
    device_serial=serial,
    kefu_name=None,  # ← 也是错误的，不能是 None
)

# 之后（修复）:
context = MessageContext(
    customer_id=customer_id,
    customer_name=user_name,
    channel=user_channel,  # ← 添加缺失的 channel 参数
    device_serial=serial,
    kefu_name="",  # ← 使用空字符串而非 None
)
```

### 修复 2: 重新排列消息处理器注册顺序

修改 `_register_message_handlers()` 方法，将处理器注册顺序调整为：

1. **TextMessageHandler** (第一个) - 处理大多数文本消息
2. **StickerMessageHandler** (新增) - 处理表情包消息
3. **VoiceMessageHandler** - 处理语音消息
4. **VideoMessageHandler** - 处理视频消息
5. **ImageMessageHandler** (最后) - 处理图片消息

### 修复 3: 添加 StickerMessageHandler

之前缺少的表情包处理器已添加。

### 修复 4: 添加调试日志

在消息处理循环中添加了详细的调试日志，输出每条消息的 `is_self`、`message_type` 和是否有 `image` 属性。

---

**创建时间**: 2026-01-24  
**状态**: ✅ 已修复 (待测试验证)  
**优先级**: 高  
**修复人**: Gemini 2.5 Pro
