# 图片存储路径问题分析与解决方案

## 问题描述

1. **`conversation_images/customer_id/`** - 提取的图片是**错误的**
2. **`conversation_images/conversation_images/`** - 图片是**正确的**，但嵌套目录且重复保存
3. **没有按 customer_id 正确分类存储**

## 根本原因

存在两个独立的图片保存流程，它们在不同时机运行，导致图片存储混乱：

### 流程 1: 滚动时实时捕获（正确）

**位置**: `wecom_service.py` 第 877-905 行

```python
# INLINE IMAGE CAPTURE - capture images NOW while visible
if download_images and image_dir and HAS_PIL:
    _, screenshot_bytes = await self.adb.take_screenshot()
    full_screenshot = Image.open(BytesIO(screenshot_bytes))

    for msg in new_messages:
        if msg.message_type == "image" and msg.image:
            captured = await self._capture_image_inline(
                msg, full_screenshot, img_width, img_height,
                image_dir,  # ← 保存到 output_dir/conversation_images
                ...
            )
```

**特点**:

- ✅ 在滚动提取时立即截图
- ✅ 图片还在屏幕上，坐标准确
- ❌ 保存到 `conversation_images/conversation_images/`（路径嵌套）
- ❌ 没有按 `customer_id` 分类

### 流程 2: 消息处理时截图（错误）

**位置**: `image_handler.py` 第 141-147 行

```python
image_path = await self._storage.save_image_from_bounds(
    wecom_service=self._wecom,
    customer_id=context.customer_id,  # ← 按客户分类
    message_id=msg_record.id,
    bounds=image_bounds,  # ← 使用旧坐标
)
```

**特点**:

- ❌ 消息处理时图片可能已滚出屏幕
- ❌ 使用的 bounds 坐标已过时，截图结果错误
- ✅ 正确按 `customer_id` 分类存储
- ✅ 创建数据库记录

## 解决方案

### 方案: 合并两个流程的优点

**目标**:

1. 在滚动时实时捕获（保证准确性）
2. 按 `customer_id` 分类存储
3. 创建正确的数据库记录
4. 消息处理时复制已捕获的图片，而不是重新截图

### 实现步骤

#### Step 1: 修改 `_capture_image_inline`

修改 `wecom_service.py` 中的内联捕获，增加返回图片路径：

```python
async def _capture_image_inline(
    self,
    msg: ConversationMessage,
    screenshot: Image.Image,
    width: int,
    height: int,
    output_dir: Path,
    msg_index: int,
    captured_keys: Set[str],
) -> Optional[str]:
    """
    Capture image inline during scroll.

    Returns:
        Local path if captured, None if skipped
    """
    # ... existing logic ...

    # 保存到临时目录（稍后由 ImageMessageHandler 复制到正确位置）
    filename = f"temp_image_{msg_index}_{timestamp}.png"
    filepath = output_dir / filename

    # 裁剪并保存
    cropped = screenshot.crop((x1, y1, x2, y2))
    cropped.save(filepath, "PNG")

    # 存储到消息对象中供后续使用
    msg.image.local_path = str(filepath)

    return str(filepath)
```

#### Step 2: 修改 `ImageMessageHandler`

修改 `image_handler.py`，优先使用已捕获的图片：

```python
async def process(self, message: Any, context: MessageContext) -> MessageProcessResult:
    # ... 创建消息记录 ...

    # 检查图片是否已在滚动时捕获
    existing_path = None
    if hasattr(message.image, 'local_path') and message.image.local_path:
        existing_path = Path(message.image.local_path)
        if existing_path.exists():
            self._logger.info(f"Using pre-captured image: {existing_path}")

    if existing_path and existing_path.exists():
        # 复制到正确的 customer_id 目录
        image_path = self._storage.save_image_from_source(
            source_path=existing_path,
            customer_id=context.customer_id,
            message_id=msg_record.id,
            bounds=image_bounds,
        )
    elif image_bounds:
        # 回退：使用 bounds 截图（可能不准确）
        self._logger.warning("Falling back to bounds-based capture (may be inaccurate)")
        image_path = await self._storage.save_image_from_bounds(
            wecom_service=self._wecom,
            customer_id=context.customer_id,
            message_id=msg_record.id,
            bounds=image_bounds,
        )
    else:
        image_path = None
```

#### Step 3: 修复路径嵌套问题

修改 `wecom_service.py` 第 678-680 行：

```python
# 旧代码（有问题）
image_dir = Path(output_dir) / "conversation_images"

# 新代码（修复嵌套）
if "conversation_images" in str(output_dir):
    image_dir = Path(output_dir)
else:
    image_dir = Path(output_dir) / "conversation_images"
```

### 修改后的数据流

```
[滚动提取阶段]
    ↓
图片在屏幕上可见
    ↓
_capture_image_inline() 立即截图
    ↓
保存到临时路径 + 存储到 msg.image.local_path
    ↓
[消息处理阶段]
    ↓
ImageMessageHandler.process()
    ↓
检查 msg.image.local_path 是否存在
    ↓
存在 → 复制到 customer_id/ 目录
不存在 → 使用 bounds 截图（回退，可能不准确）
    ↓
创建数据库记录
```

### 预期目录结构

```
conversation_images/
├── customer_1/
│   ├── msg_101_20260119_160000.png
│   └── msg_102_20260119_160100.png
├── customer_2/
│   ├── msg_201_20260119_160200.png
│   └── msg_202_20260119_160300.png
└── temp/
    └── (临时文件，定期清理)
```

## 需要修改的文件

| 文件               | 修改内容                                                             |
| ------------------ | -------------------------------------------------------------------- |
| `wecom_service.py` | 1. 修复路径嵌套<br>2. 在 `_capture_image_inline` 中存储 `local_path` |
| `image_handler.py` | 优先使用已捕获的图片                                                 |
| `image_storage.py` | 添加 `save_image_from_source` 方法（如果不存在）                     |

## 实施优先级

1. **高**: 修复路径嵌套（消除 `conversation_images/conversation_images/`）
2. **高**: 修改 `ImageMessageHandler` 优先使用已捕获图片
3. **中**: 在滚动捕获时存储 `local_path`
4. **低**: 添加临时文件清理机制

## 验证方法

1. 运行同步测试
2. 检查 `conversation_images/` 目录结构是否正确
3. 验证图片内容是否与消息匹配
4. 确认没有嵌套目录
