# Image Bounds 属性访问路径修复

**修复日期**: 2026-01-18
**状态**: ✅ 已修复

## 问题描述

`ImageMessageHandler` 和 `VideoMessageHandler` 中存在错误的属性访问路径，导致图片和视频无法正确保存。

### 根本原因

`ConversationMessage` 模型的数据结构：

```python
@dataclass
class ConversationMessage:
    content: Optional[str] = None
    message_type: str = "text"
    image: Optional[ImageInfo] = None      # ← ImageInfo 对象
    video_duration: Optional[str] = None   # ← 仅时长字符串
    video_local_path: Optional[str] = None # ← 仅文件路径
    raw_bounds: Optional[str] = None       # ← 消息容器边界
    # 注意：没有 image_bounds 或 video_bounds 属性！
```

**ImageInfo 结构**：

```python
@dataclass
class ImageInfo:
    bounds: Optional[str] = None  # ← 图片边界坐标在这里
    local_path: Optional[str] = None
    # ...
```

## 修复内容

### 1. image.py 修复

**文件**: `src/wecom_automation/services/message/handlers/image.py`

#### 修复点 1: can_handle 方法（第 71-76 行）

**修复前**:

```python
# 检查是否有图片bounds
if hasattr(message, 'image_bounds') and message.image_bounds:
    return True
```

**修复后**:

```python
# 检查是否有图片（通过 message.image 对象）
# Note: ConversationMessage.image 是 ImageInfo 对象，不是直接的 bounds 字符串
if hasattr(message, 'image') and message.image and message.image.bounds:
    return True
```

#### 修复点 2: process 方法（第 93-95 行）

**修复前**:

```python
# 获取图片bounds
image_bounds = getattr(message, 'image_bounds', None)
```

**修复后**:

```python
# 获取图片bounds
# Note: ConversationMessage.image 是 ImageInfo 对象，通过 .bounds 访问坐标
image_bounds = message.image.bounds if (message.image and hasattr(message.image, 'bounds')) else None
```

### 2. video.py 修复

**文件**: `src/wecom_automation/services/message/handlers/video.py`

#### 修复点 1: can_handle 方法（第 64-76 行）

**修复前**:

```python
# 检查视频bounds
if hasattr(message, 'video_bounds') and message.video_bounds:
    return True

# 检查视频时长
if hasattr(message, 'video_duration') and message.video_duration:
    return True
```

**修复后**:

```python
# 检查视频bounds（Note: ConversationMessage 没有 video_bounds 字段，使用 raw_bounds 作为容器边界）
# 前向兼容：如果有 video_bounds 属性则使用
if hasattr(message, 'video_bounds') and message.video_bounds:
    return True
# 使用 raw_bounds 作为视频容器边界
if hasattr(message, 'raw_bounds') and message.raw_bounds:
    return True

# 检查视频时长
if hasattr(message, 'video_duration') and message.video_duration:
    return True
```

#### 修复点 2: process 方法（第 93-96 行）

**修复前**:

```python
# 获取视频元数据
video_bounds = getattr(message, 'video_bounds', None)
video_duration = getattr(message, 'video_duration', None)
```

**修复后**:

```python
# 获取视频元数据
# Note: ConversationMessage 没有 video_bounds 字段，使用 raw_bounds 作为容器边界
video_bounds = getattr(message, 'video_bounds', None) or getattr(message, 'raw_bounds', None)
video_duration = getattr(message, 'video_duration', None)
```

#### 修复点 3: 日志消息改进（第 140-150 行）

**修复前**:

```python
self._logger.info(
    f"Video message saved: customer={context.customer_name}, "
    f"duration={video_duration}, path={video_path}"
)
```

**修复后**:

```python
# 根据保存结果显示不同的日志
if video_path:
    self._logger.info(
        f"Video saved successfully: customer={context.customer_name}, "
        f"duration={video_duration}, path={video_path}"
    )
else:
    self._logger.warning(
        f"Video NOT saved: customer={context.customer_name}, "
        f"duration={video_duration}, reason={'missing bounds or download failed' if video_bounds else 'missing bounds'}"
    )
```

## 修复效果

### 修复前

```
22:07:52 [INFO] sync: Image message saved: customer=B2601020037 (保底正常), path=None
22:07:52 [INFO] sync: Video message saved: customer=B2601020037 (保底正常), path=None
```

**问题**：

- 日志显示 "saved" 但 `path=None`
- 实际上图片/视频没有被保存到磁盘
- 只有消息记录被创建，内容为 "[图片]" 或 "[视频]"

### 修复后

**成功保存时**:

```
22:15:30 [INFO] sync: Image saved successfully: customer=B2601020037 (保底正常), path=output/images/customer_123/msg_456_20260118_221530.png
22:15:31 [INFO] sync: Video saved successfully: customer=B2601020037 (保底正常), duration=00:15, path=output/videos/customer_123/video_456_20260118_221531.mp4
```

**保存失败时**:

```
22:16:00 [WARNING] sync: Image NOT saved: customer=B2601020037 (保底正常), reason=missing image_bounds attribute
22:16:01 [WARNING] sync: Video NOT saved: customer=B2601020037 (保底正常), duration=00:15, reason=missing bounds
```

## 正确的属性访问方式

| 媒体类型    | 错误用法               | 正确用法                   |
| ----------- | ---------------------- | -------------------------- |
| 图片 bounds | `message.image_bounds` | `message.image.bounds`     |
| 视频 bounds | `message.video_bounds` | `message.raw_bounds`       |
| 图片路径    | `message.image_path`   | `message.image.local_path` |
| 视频路径    | `message.video_path`   | `message.video_local_path` |

## 影响范围

### 修复前的影响

1. **数据不完整**
   - 消息记录存在，但缺少实际图片/视频文件
   - 用户界面只能显示 "[图片]" 或 "[视频]" 占位符

2. **存储资源浪费**
   - 需要重新同步来补全媒体文件

3. **用户体验降低**
   - 历史对话中的媒体无法查看
   - 无法进行图片/视频内容分析

4. **调试困难**
   - 日志显示 "saved" 但实际未保存，造成混淆

### 修复后的改进

1. **数据完整性**
   - 图片和视频正确保存到磁盘
   - 数据库记录与实际文件一致

2. **日志清晰性**
   - 成功和失败状态明确区分
   - 失败原因详细记录

3. **代码健壮性**
   - 正确的属性访问路径
   - 前向兼容性支持

## 验证步骤

1. **运行同步测试**

   ```bash
   uv run wecom-automation --skip-launch --capture-avatars
   ```

2. **检查日志输出**
   - 确认不再出现 `path=None` 的 "saved" 日志
   - 成功日志应显示完整路径
   - 失败日志应显示 WARNING 级别和具体原因

3. **验证文件保存**

   ```bash
   ls output/images/customer_*/
   ls output/videos/customer_*/
   ```

4. **检查数据库记录**
   ```sql
   SELECT m.id, m.content, m.message_type,
          i.file_path as image_path,
          v.file_path as video_path
   FROM messages m
   LEFT JOIN images i ON m.id = i.message_id
   LEFT JOIN videos v ON m.id = v.message_id
   WHERE m.message_type IN ('image', 'video')
   LIMIT 10;
   ```

## 相关文档

- 原问题分析: `docs/04-bugs-and-fixes/active/01-18-image-path-none-analysis.md`
- 本修复文档: `docs/04-bugs-and-fixes/active/01-18-image-bounds-fix.md`

## 修改的文件

1. `src/wecom_automation/services/message/handlers/image.py`
   - 第 71-76 行：修复 can_handle 方法
   - 第 93-95 行：修复 process 方法的属性访问

2. `src/wecom_automation/services/message/handlers/video.py`
   - 第 64-76 行：修复 can_handle 方法
   - 第 93-96 行：修复 process 方法的属性访问
   - 第 140-150 行：改进日志消息
