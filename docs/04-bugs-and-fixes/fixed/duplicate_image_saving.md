# 图片重复保存问题分析

**日期**: 2026-01-18
**状态**: ✅ 已修复 (方案三)
**修复内容**: 取消阶段二的文件复制操作，直接使用阶段一抓取的路径存入数据库

## 1. 问题现象

用户发现图片被保存到了两个不同的位置：

1. `conversation_images\conversation_images\msg_XXX.png` (临时抓取目录，存在路径嵌套问题)
2. `conversation_images\customer_87\msg_2428_20260118_164914.png` (正式归档目录)

这导致了 **磁盘空间浪费** 和 **文件管理混乱**。

## 2. 根本原因

代码中确实存在 **两阶段保存机制**，且第一阶段的临时文件没有被清理。

### 阶段一：Inline Capture (临时抓取)

**位置**: `src/wecom_automation/services/wecom_service.py` (`_capture_image_inline`, Line 1640)

```python
# 在滚动提取消息时，立即截图并保存到临时目录
filename = f"msg_{msg_index}_{timestamp}.png"
image_path = image_dir / filename  # image_dir = output_dir / "conversation_images"
image_crop.save(image_path)
msg.image.local_path = str(image_path)  # 记录临时路径
```

- **目的**: 在滚动时立即抓取图片，避免坐标失效。
- **保存路径**: `{output_dir}/conversation_images/msg_{index}_{timestamp}.png`
- **文件命名**: 基于消息在**当前滚动批次中的索引** (`msg_index`)。

### 阶段二：Storage Archive (正式归档)

**位置**: `src/wecom_automation/services/sync_service.py` (`_save_message_image`, Line 2690)

```python
# 从临时路径复制到按客户分类的正式目录
storage = ImageStorageHelper(...)
dest_path = storage.save_image_from_source(
    source_path=source_path,  # 阶段一的临时文件
    customer_id=customer.id,
    message_id=message_id,    # 数据库中的消息ID
)
```

- **目的**: 将抓取的图片归档到按客户ID组织的目录中。
- **保存路径**: `{images_dir}/customer_{customer_id}/msg_{message_id}_{timestamp}.png`
- **文件命名**: 基于**数据库消息ID** (`message_id`)。

### 问题点

1. **临时文件未清理**: 阶段二只是**复制**文件，并没有删除阶段一产生的临时文件。
2. **路径嵌套**: `conversation_images\conversation_images` 表明 `output_dir` 本身可能已经是 `...conversation_images`，导致再次拼接 `conversation_images` 子目录时产生了嵌套。

## 3. 数据流示意

```
滚动提取消息
    │
    ▼
┌─────────────────────────────────────────┐
│ _capture_image_inline()                 │
│ 保存到: conversation_images/msg_5_*.png │  ← 临时文件 (未清理)
│ 更新: msg.image.local_path              │
└─────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────┐
│ _process_and_store_message()                     │
│   ↓                                              │
│ _save_message_image()                            │
│   ↓                                              │
│ ImageStorageHelper.save_image_from_source()      │
│ 复制到: customer_87/msg_2428_*.png               │  ← 正式归档
└──────────────────────────────────────────────────┘
```

## 4. 修复建议

### 方案一：阶段二完成后删除临时文件 (推荐)

在 `sync_service._save_message_image` 成功复制后，删除源文件：

```python
# sync_service.py, _save_message_image 方法
if dest_path:
    msg.image.local_path = str(dest_path)
    # 删除临时文件
    try:
        source_path.unlink()
    except Exception:
        pass  # 忽略删除失败
    return str(dest_path)
```

### 方案二：取消阶段一的持久化保存

让阶段一仅在内存中保留截图数据（如 `bytes`），不写入磁盘。阶段二直接从内存数据写入正式目录。此方案需要较大的重构。

### 方案三：统一保存路径

让阶段一直接保存到 `customer_{id}` 目录，跳过阶段二的复制操作。此方案需要在滚动时就知道 `customer_id`。

## 5. 关于路径嵌套问题

`conversation_images\conversation_images` 路径的产生，需要检查 `extract_conversation_messages` 的调用方式：

```python
# 检查 output_dir 的值
result = await self.wecom.extract_conversation_messages(
    output_dir=str(self.images_dir),  # <-- 如果 images_dir 已经是 .../conversation_images
                                      # 则 image_dir = images_dir / "conversation_images" 会产生嵌套
)
```

**建议**: 核查 `sync_service.py` 中 `self.images_dir` 的定义，确保它不是以 `conversation_images` 结尾的路径。
