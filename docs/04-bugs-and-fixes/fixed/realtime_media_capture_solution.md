# 实时监测媒体捕获解决方案

> 文档版本: 1.0  
> 创建时间: 2026-01-23  
> 作者: 架构设计师

---

## 一、背景与问题回顾

### 1.1 问题现象

实时监测功能（FollowUp Response Detector）无法获取和保存媒体消息（图片、视频、音频、表情包），而全量同步功能可以正确处理。

### 1.2 根因分析

| 模块         | 消息提取                                        | 媒体处理    | 数据完整性 |
| ------------ | ----------------------------------------------- | ----------- | ---------- |
| **全量同步** | `wecom.extract_conversation_messages()`         | ✅ 内联捕获 | 完整       |
| **实时监测** | `ui_parser.extract_conversation_messages(tree)` | ❌ 仅解析   | 仅类型标记 |

---

## 二、方案评估

### 2.1 方案对比矩阵

| 评估维度       | 方案1: 添加内联媒体捕获      | 方案2: 复用 MessageProcessor | 方案3: 仅保留类型标记 |
| -------------- | ---------------------------- | ---------------------------- | --------------------- |
| **开发复杂度** | 中等 (新增1个方法)           | 高 (重构存储流程)            | 低 (修改几行)         |
| **代码耦合度** | 低 (独立方法)                | 高 (引入新依赖)              | 极低                  |
| **媒体完整性** | 高 (图片完整, 视频/语音占位) | 最高 (全部完整)              | 无 (仅元数据)         |
| **运行时性能** | 中等 (截图+裁剪)             | 较低 (复杂处理链)            | 最高                  |
| **实时性保障** | ✅ 适合实时场景              | ⚠️ 可能阻塞                  | ✅ 最佳               |
| **维护成本**   | 低                           | 中等                         | 极低                  |
| **风险等级**   | 低                           | 中等                         | 无                    |

### 2.2 方案深度分析

#### 方案1: 添加内联媒体捕获 ⭐ 推荐

**核心思路**: 在实时监测提取消息后、存储前，添加独立的媒体捕获方法。

**优势**:

- ✅ **职责单一**: 新增方法专职处理媒体，不影响现有逻辑
- ✅ **渐进式增强**: 对图片/表情包完整捕获，视频/语音优雅降级
- ✅ **实时性保障**: 单次截图处理所有图片，延迟可控 (~200ms)
- ✅ **易于回滚**: 出问题可快速禁用

**劣势**:

- ⚠️ 视频/语音仍使用占位符（需交互操作，不适合实时场景）

#### 方案2: 复用 MessageProcessor

**核心思路**: 将全量同步的 MessageProcessor 引入实时监测。

**优势**:

- ✅ 最大程度复用现有代码
- ✅ 媒体处理逻辑完全一致

**劣势**:

- ❌ **重构成本高**: 需要调整依赖注入和初始化流程
- ❌ **耦合度增加**: 实时监测将依赖更多组件
- ❌ **实时性风险**: MessageProcessor 的同步处理可能阻塞检测循环

#### 方案3: 仅保留类型标记

**核心思路**: 确保 `message_type` 正确，content 使用占位符。

**优势**:

- ✅ 改动最小
- ✅ 无性能影响

**劣势**:

- ❌ **无实际媒体内容**: 只有 `[图片]` 文字，无法查看
- ❌ **用户体验差**: 前端无法展示媒体预览

---

## 三、最优方案: 混合增强策略

### 3.1 方案概述

综合考量后，推荐 **方案1 + 方案3 的混合策略**：

```
┌─────────────────────────────────────────────────────────────────┐
│                     混合增强策略                                  │
├─────────────────────────────────────────────────────────────────┤
│  图片 / 表情包  →  方案1: 内联截图裁剪，保存完整文件              │
│  视频 / 语音    →  方案3: 使用占位符，记录元数据                  │
└─────────────────────────────────────────────────────────────────┘
```

**设计原则**:

1. **图片优先**: 图片是最常见的媒体类型，且截图捕获成本低
2. **优雅降级**: 视频/语音需要交互操作，采用占位符方案
3. **数据一致**: 保持与全量同步相同的存储格式

### 3.2 架构设计

```
┌──────────────────────────────────────────────────────────────────┐
│                    ResponseDetector                              │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  _process_unread_user_with_wait()                                │
│       │                                                           │
│       ▼                                                           │
│  ┌─────────────────────────────────────────────┐                 │
│  │ _extract_visible_messages()                  │                 │
│  │   └─→ ui_parser.extract_conversation_messages() │              │
│  └─────────────────────────────────────────────┘                 │
│       │                                                           │
│       ▼  [新增]                                                   │
│  ┌─────────────────────────────────────────────┐                 │
│  │ _capture_media_inline()                      │  ◄── 核心新增   │
│  │   ├─→ 图片: 截图裁剪保存                      │                 │
│  │   ├─→ 表情包: 截图裁剪保存                    │                 │
│  │   ├─→ 视频: 生成占位符 + 保留 bounds 元数据   │                 │
│  │   └─→ 语音: 生成占位符 + 保留 duration 元数据 │                 │
│  └─────────────────────────────────────────────┘                 │
│       │                                                           │
│       ▼                                                           │
│  ┌─────────────────────────────────────────────┐                 │
│  │ _store_messages_to_db()                      │                 │
│  │   └─→ 存储消息记录（含媒体路径/占位符）       │                 │
│  └─────────────────────────────────────────────┘                 │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 四、详细实施方案

### 4.1 新增方法: `_capture_media_inline()`

**文件**: `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`

**位置**: 在 `_extract_visible_messages()` 方法之后添加

```python
async def _capture_media_inline(
    self,
    wecom,
    serial: str,
    messages: List[Any],
    customer_id: int,
) -> List[Any]:
    """
    内联捕获媒体消息内容

    处理策略:
    - 图片/表情包: 截图裁剪保存到本地
    - 视频: 生成占位符 "[视频消息 00:45]"
    - 语音: 生成占位符 "[语音消息 3"]"

    Args:
        wecom: WeComService 实例
        serial: 设备序列号
        messages: 从 UI 树提取的消息列表
        customer_id: 客户数据库ID

    Returns:
        处理后的消息列表（已填充 content 字段）
    """
    try:
        from PIL import Image
        from io import BytesIO
    except ImportError:
        self._logger.warning(f"[{serial}] PIL not installed, skipping media capture")
        return self._fill_media_placeholders(messages)

    # 获取输出目录
    db_path = Path(self._repository._db_path)
    project_root = db_path.parent
    image_dir = project_root / "conversation_images" / f"customer_{customer_id}"
    image_dir.mkdir(parents=True, exist_ok=True)

    # 检查是否有需要截图的媒体消息
    has_screenshot_media = any(
        getattr(msg, 'message_type', 'text') in ('image', 'sticker')
        and hasattr(msg, 'image') and msg.image
        for msg in messages
    )

    if not has_screenshot_media:
        # 无需截图，只处理占位符
        return self._fill_media_placeholders(messages)

    # 截屏一次用于所有图片（避免多次截屏）
    try:
        _, screenshot_bytes = await wecom.adb.take_screenshot()
        full_screenshot = Image.open(BytesIO(screenshot_bytes))
        img_width, img_height = full_screenshot.size
    except Exception as e:
        self._logger.warning(f"[{serial}] Screenshot failed: {e}")
        return self._fill_media_placeholders(messages)

    captured_count = 0

    for msg in messages:
        msg_type = getattr(msg, 'message_type', 'text')

        if msg_type in ('image', 'sticker'):
            # 捕获图片/表情包
            if hasattr(msg, 'image') and msg.image and hasattr(msg.image, 'parse_bounds'):
                if msg.image.parse_bounds():
                    x1, y1 = msg.image.x1, msg.image.y1
                    x2, y2 = msg.image.x2, msg.image.y2

                    # 验证边界
                    if (0 <= x1 < x2 <= img_width and
                        0 <= y1 < y2 <= img_height and
                        (x2 - x1) >= 50 and (y2 - y1) >= 50):

                        try:
                            cropped = full_screenshot.crop((x1, y1, x2, y2))
                            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                            prefix = "sticker" if msg_type == 'sticker' else "img"
                            filename = f"{prefix}_{timestamp}.png"
                            save_path = image_dir / filename
                            cropped.save(save_path)

                            # 更新消息内容为文件路径
                            msg.content = str(save_path)
                            captured_count += 1
                            self._logger.info(f"[{serial}] 📷 Captured {msg_type}: {filename}")
                        except Exception as e:
                            self._logger.warning(f"[{serial}] Failed to crop {msg_type}: {e}")
                            msg.content = f"[{msg_type}]"
                    else:
                        msg.content = f"[{msg_type}]"
                else:
                    msg.content = f"[{msg_type}]"
            else:
                msg.content = f"[{msg_type}]"

        elif msg_type == 'video':
            # 视频占位符（含时长）
            video_duration = getattr(msg, 'video_duration', None)
            content = getattr(msg, 'content', '')
            if not content or content.startswith('[Video'):
                msg.content = f"[视频消息 {video_duration}]" if video_duration else "[视频消息]"

        elif msg_type == 'voice':
            # 语音占位符（含时长）
            voice_duration = getattr(msg, 'voice_duration', '')
            msg.content = f"[语音消息 {voice_duration}]" if voice_duration else "[语音消息]"

    if captured_count > 0:
        self._logger.info(f"[{serial}] Media capture complete: {captured_count} items saved")

    return messages


def _fill_media_placeholders(self, messages: List[Any]) -> List[Any]:
    """为媒体消息填充占位符（无需截图时使用）"""
    for msg in messages:
        msg_type = getattr(msg, 'message_type', 'text')
        content = getattr(msg, 'content', '') or ''

        if not content:
            if msg_type == 'image':
                msg.content = "[图片消息]"
            elif msg_type == 'sticker':
                msg.content = "[表情包]"
            elif msg_type == 'video':
                duration = getattr(msg, 'video_duration', '')
                msg.content = f"[视频消息 {duration}]" if duration else "[视频消息]"
            elif msg_type == 'voice':
                duration = getattr(msg, 'voice_duration', '')
                msg.content = f"[语音消息 {duration}]" if duration else "[语音消息]"

    return messages
```

### 4.2 修改调用点

**文件**: `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`

**修改位置**: `_process_unread_user_with_wait()` 方法，在消息提取后调用

```python
# 原代码（约第 536 行）
messages = await self._extract_visible_messages(wecom, serial)

# 修改为（在提取后添加媒体捕获）
messages = await self._extract_visible_messages(wecom, serial)

if messages:
    # 获取或创建 customer_id
    customer_id = self._repository.find_or_create_customer(user_name, user_channel, serial)
    if customer_id:
        # 捕获媒体内容（图片截图，视频/语音占位符）
        messages = await self._capture_media_inline(wecom, serial, messages, customer_id)
```

### 4.3 导入依赖

在文件顶部添加导入：

```python
from datetime import datetime
from pathlib import Path
```

---

## 五、测试验证

### 5.1 测试用例

| 测试场景     | 预期结果                                         | 验证方法     |
| ------------ | ------------------------------------------------ | ------------ |
| 接收图片消息 | 图片保存到 `conversation_images/customer_XXX/`   | 检查文件存在 |
| 接收表情包   | 表情包保存到 `conversation_images/customer_XXX/` | 检查文件存在 |
| 接收视频消息 | 数据库存储 `[视频消息 00:45]`                    | 查询数据库   |
| 接收语音消息 | 数据库存储 `[语音消息 3"]`                       | 查询数据库   |
| 混合消息     | 各类型正确处理                                   | 综合验证     |

### 5.2 验证 SQL

```sql
-- 检查媒体消息存储情况
SELECT id, customer_id, message_type, content, created_at
FROM messages
WHERE message_type IN ('image', 'sticker', 'video', 'voice')
ORDER BY created_at DESC
LIMIT 20;
```

---

## 六、风险与回退

### 6.1 风险评估

| 风险         | 概率 | 影响 | 缓解措施         |
| ------------ | ---- | ---- | ---------------- |
| 截图失败     | 低   | 中   | 回退到占位符方案 |
| 边界计算错误 | 低   | 低   | 添加边界校验     |
| 磁盘空间不足 | 中   | 高   | 添加存储空间检查 |
| PIL 库缺失   | 低   | 中   | 优雅降级为占位符 |

### 6.2 回退方案

如需紧急回退，只需注释掉调用点的媒体捕获行：

```python
# 回退：注释此行
# messages = await self._capture_media_inline(wecom, serial, messages, customer_id)
```

---

## 七、后续优化建议

1. **视频缩略图**: 未来可考虑捕获视频的第一帧作为缩略图
2. **语音转文字**: 结合 ASR 服务将语音转为文字存储
3. **异步上传**: 媒体文件可异步上传到云存储
4. **压缩优化**: 对大尺寸图片进行压缩后存储

---

## 八、总结

本方案采用 **混合增强策略**，针对不同媒体类型采取差异化处理：

- **图片/表情包**: 完整捕获，用户体验最佳
- **视频/语音**: 优雅降级，保持实时性

该方案在 **功能完整性** 与 **系统实时性** 之间取得了最佳平衡，同时保持了代码的简洁和可维护性。
