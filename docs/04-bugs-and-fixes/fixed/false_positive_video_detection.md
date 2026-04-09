# 视频误判问题分析与修复

**日期**: 2026-01-18
**状态**: 已修复
**模块**: VideoMessageHandler (后端)

## 1. 问题描述

用户反馈在 Sidecar 界面中，系统消息（例如 "Greetings show above" 下方的区域）被错误地解析并显示为视频消息。
界面显示一个 "No video file" 的黑色视频框，并且日志中出现如下警告：

```
[WARNING] sync: Video NOT saved: customer=1y-, duration=None, reason=missing bounds or download failed
```

Meta 数据显示 `original_bounds` 为 `[0,691][1080,859]`（全屏宽度），这通常是系统消息或容器的特征，而非视频元素。

## 2. 原因分析

经过对 `src/wecom_automation/services/message/handlers/video.py` 的代码审查，发现 `VideoMessageHandler.can_handle` 方法中存在极其危险的判断逻辑：

```python
# src/wecom_automation/services/message/handlers/video.py

async def can_handle(self, message: Any) -> bool:
    # ... (前面的检查)

    # 使用 raw_bounds 作为视频容器边界
    if hasattr(message, 'raw_bounds') and message.raw_bounds:
        return True  # <--- 问题根源

    # ...
```

**逻辑漏洞**：
几乎所有的 `ConversationMessage` 对象（无论是文本、图片还是系统消息）都会由 `ui_parser` 填充 `raw_bounds` 属性。
当一个非标准的系统消息（或其他未被前面的 Handlers 捕获的消息）进入处理流程时，如果它带有 `raw_bounds`，`VideoMessageHandler` 就会错误地声称自己可以处理该消息，从而将其强制转换为视频类型并尝试下载。

在本例中，"Greetings show above" 或类似的系统提示信息虽然没有内容（`content` 为空），但拥有 `raw_bounds`，因此触发了此 Bug。

## 3. 修复方案

已修改 `VideoMessageHandler.can_handle` 方法，移除了仅基于 `raw_bounds` 存在的判断逻辑。
现在的视频判断逻辑更加严格，必须满足以下条件之一：

1. `message_type` 显式为 "video" 或 "VIDEO"。
2. 存在 `video_duration` 属性（表示解析到了视频时长）。
3. 存在 `video_bounds` 属性（如果有明确的视频边界）。

**代码变更**：

```python
<<<<
        # 使用 raw_bounds 作为视频容器边界
        if hasattr(message, 'raw_bounds') and message.raw_bounds:
            return True
====
        # 使用 raw_bounds 作为视频容器边界 - 只有在明确是视频类型或者有其他视频特征时才应该处理
        # 仅有 raw_bounds 不足以证明是视频，因为所有消息都有 raw_bounds
        # if hasattr(message, 'raw_bounds') and message.raw_bounds:
        #    return True
>>>>
```

此修复确保了只有真正的视频消息才会被 VideoHandler 拦截和处理。
