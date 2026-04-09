# Video 和 Image 消息类型判断逻辑

本文档详细说明项目中判断消息类型为 video 或 image 的依据和逻辑。

## 1. 消息类型枚举定义

在 `src/wecom_automation/database/models.py` 中定义了消息类型枚举：

```python
class MessageType(str, Enum):
    """Enumeration of supported message types."""
    TEXT = "text"
    VOICE = "voice"
    IMAGE = "image"
    VIDEO = "video"
    FILE = "file"
    LINK = "link"
    LOCATION = "location"
    SYSTEM = "system"
    UNKNOWN = "unknown"
```

## 2. UI 解析层判断逻辑

消息类型的首次判断发生在 UI 解析阶段，位于 `src/wecom_automation/services/ui_parser.py` 的 `_extract_message_from_row()` 方法中。

### 2.1 Video 消息判断条件

**Video 类型的判断需要强有力的证据**，具体条件如下：

```python
# 位置: ui_parser.py 第 1296-1318 行

# Video 检测需要 STRONG evidence:
# - video_duration (e5v 带时间格式如 "00:45") 是最可靠的指标
# - 或者同时存在 video thumbnail (k2j) 和 play button (jqb)
# 单独的指标如仅 k2j 或仅 jqb 是不够的（可能出现在图片视图中）

if not content and not voice_duration:
    is_video = video_duration is not None or (has_video_thumbnail and has_play_button)

    if is_video:
        message_type = "video"
```

**Video 判断的关键 UI 元素：**

| 元素         | Resource ID (旧版) | Resource ID (新版) | 说明                                   |
| ------------ | ------------------ | ------------------ | -------------------------------------- |
| Video 时长   | `e5v`              | `e5l`              | 格式如 "00:45" 或 "1:23"，最可靠的指标 |
| Video 缩略图 | `k2j`              | `k1r`/`k1s`        | 视频缩略图 ImageView                   |
| 播放按钮     | `jqb`              | `jpn`              | 播放按钮覆盖层                         |

**判断优先级：**

1. ✅ 有 `video_duration` (e5v) → 判定为 Video
2. ✅ 同时有 `video_thumbnail` (k2j) AND `play_button` (jqb) → 判定为 Video
3. ❌ 仅有 k2j 或仅有 jqb → 不足以判定为 Video

### 2.2 Image 消息判断条件

**Image 类型通过排除法和尺寸检测判断**：

```python
# 位置: ui_parser.py 第 1314-1317 行

else:
    # 检查仅图片消息（无文字内容但有图片）
    image_info = self._find_message_image(all_nodes, screen_width)
    if image_info:
        message_type = "image"
```

**`_find_message_image()` 方法的判断逻辑**（第 1363-1406 行）：

```python
def _find_message_image(self, all_nodes, screen_width) -> Optional[ImageInfo]:
    """
    查找消息图片（非头像）

    头像 ID 为 'im4' 且较小（约 114px）
    消息图片更大且没有头像 ID
    """
    for node in all_nodes:
        rid = (node.get("resourceId") or "").lower()
        class_name = (node.get("className") or "").lower()
        bounds = self._get_node_bounds(node)

        # 跳过头像
        if "im4" in rid:
            continue

        # 检查是否为 ImageView
        if "imageview" not in class_name and "image" not in class_name:
            continue

        # 解析边界坐标
        x1, y1, x2, y2 = map(int, match.groups())
        width = x2 - x1
        height = y2 - y1

        # 消息图片大于头像（>150px）
        if width > 150 and height > 150:
            return ImageInfo(bounds=bounds, ...)
```

**Image 判断的关键条件：**

| 条件         | 说明                             |
| ------------ | -------------------------------- |
| class 类型   | `imageview` 或包含 `image`       |
| 资源 ID 排除 | 不包含 `im4`（头像的 ID）        |
| 尺寸要求     | 宽度 > 150px **且** 高度 > 150px |

## 3. Handler 层判断逻辑

### 3.1 ImageMessageHandler

位于 `src/wecom_automation/services/message/handlers/image.py`：

```python
async def can_handle(self, message: Any) -> bool:
    """判断是否为图片消息"""

    # 1. 类型标记检查
    msg_type = self._get_message_type(message)
    if msg_type in ("image", "IMAGE", "photo"):
        return True

    # 2. 检查是否有图片对象及 bounds
    # ConversationMessage.image 是 ImageInfo 对象
    if hasattr(message, 'image') and message.image and message.image.bounds:
        return True

    return False
```

### 3.2 VideoMessageHandler

位于 `src/wecom_automation/services/message/handlers/video.py`：

```python
async def can_handle(self, message: Any) -> bool:
    """判断是否为视频消息"""

    # 1. 类型标记检查
    msg_type = self._get_message_type(message)
    if msg_type in ("video", "VIDEO"):
        return True

    # 2. 检查视频 bounds
    # 前向兼容：如果有 video_bounds 属性则使用
    if hasattr(message, 'video_bounds') and message.video_bounds:
        return True
    # 使用 raw_bounds 作为视频容器边界
    if hasattr(message, 'raw_bounds') and message.raw_bounds:
        return True

    # 3. 检查视频时长
    if hasattr(message, 'video_duration') and message.video_duration:
        return True

    return False
```

## 4. 消息对象数据结构

### 4.1 ConversationMessage

在 `src/wecom_automation/core/models.py` 中定义：

```python
@dataclass
class ConversationMessage:
    content: Optional[str] = None
    timestamp: Optional[str] = None
    is_self: bool = False
    message_type: str = "text"                    # 消息类型
    image: Optional[ImageInfo] = None             # 图片信息
    voice_duration: Optional[str] = None          # 语音时长
    voice_local_path: Optional[str] = None        # 语音本地路径
    video_duration: Optional[str] = None          # 视频时长（如 "00:45"）
    video_local_path: Optional[str] = None        # 视频本地路径
    sender_name: Optional[str] = None
    sender_avatar: Optional[AvatarInfo] = None
    raw_bounds: Optional[str] = None              # 容器边界
```

### 4.2 ImageInfo

```python
@dataclass
class ImageInfo:
    bounds: Optional[str] = None          # 格式 "[x1,y1][x2,y2]"
    resource_id: Optional[str] = None
    content_description: Optional[str] = None
    local_path: Optional[str] = None      # 下载后的本地路径

    # 解析后的坐标
    x1: int = 0
    y1: int = 0
    x2: int = 0
    y2: int = 0
```

## 5. 判断流程总结

```
┌──────────────────────────────────────────────────────────┐
│                 UI 解析层 (ui_parser.py)                  │
├──────────────────────────────────────────────────────────┤
│  1. 检查 video_duration (e5v 元素)                        │
│     └── 有 → message_type = "video"                      │
│                                                          │
│  2. 检查 video_thumbnail (k2j) + play_button (jqb)       │
│     └── 同时有 → message_type = "video"                  │
│                                                          │
│  3. 检查 ImageView 元素                                   │
│     └── 排除头像 (im4)                                    │
│     └── 尺寸 > 150x150 → message_type = "image"          │
│                                                          │
│  4. 其他情况 → message_type = "text" 或其他类型           │
└──────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│               Handler 层 (handlers/*.py)                  │
├──────────────────────────────────────────────────────────┤
│  ImageMessageHandler.can_handle():                       │
│    - msg_type in ("image", "IMAGE", "photo")             │
│    - message.image.bounds 存在                           │
│                                                          │
│  VideoMessageHandler.can_handle():                       │
│    - msg_type in ("video", "VIDEO")                      │
│    - message.video_bounds 或 raw_bounds 存在             │
│    - message.video_duration 存在                         │
└──────────────────────────────────────────────────────────┘
```

## 6. 关键文件位置

| 文件                                                      | 功能                                    |
| --------------------------------------------------------- | --------------------------------------- |
| `src/wecom_automation/database/models.py`                 | MessageType 枚举定义                    |
| `src/wecom_automation/core/models.py`                     | ConversationMessage、ImageInfo 数据模型 |
| `src/wecom_automation/services/ui_parser.py`              | UI 解析和类型判断逻辑                   |
| `src/wecom_automation/services/message/handlers/image.py` | Image Handler                           |
| `src/wecom_automation/services/message/handlers/video.py` | Video Handler                           |
| `src/wecom_automation/services/message/handlers/base.py`  | Handler 基类                            |

---

_文档创建日期: 2026-01-18_
