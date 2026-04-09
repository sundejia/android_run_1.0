# AI 回复包含 XML 标签问题

## 问题描述

**发现日期**: 2026-02-04

**现象**: 企微发送的消息中多了一个 `<response>` 标签

**日志对比**:

- 服务器返回：`"output": "\n宝子，我们主要是露脸视频直播..."`（正常）
- 企微日志：`{'output': '<response>\n宝子，我们是线上直播...'`（多了 `<response>` 标签）

## 根本原因

AI 服务器（大语言模型）有时会在输出中包含 XML 格式的标签，如 `<response>`、`</response>` 等。这是 LLM 的常见行为，特别是当 prompt 中使用了 XML 格式的指令时，模型可能会"模仿"这种格式来包裹自己的回复。

在 `response_detector.py` 的 `_generate_reply` 方法中，代码直接返回了 `ai_reply.strip()`，没有清理这些可能存在的 XML 标签。

## 修复方案

在 `response_detector.py` 第 1946-1948 行，添加 XML 标签清理逻辑：

```python
if ai_reply and len(ai_reply.strip()) > 0:
    # Clean up potential XML tags that AI might include
    import re
    cleaned_reply = ai_reply.strip()
    # Remove common XML wrapper tags that LLMs sometimes include
    xml_tags_to_remove = [
        r'</?response>',
        r'</?output>',
        r'</?reply>',
        r'</?answer>',
        r'</?message>',
    ]
    for pattern in xml_tags_to_remove:
        cleaned_reply = re.sub(pattern, '', cleaned_reply, flags=re.IGNORECASE)
    cleaned_reply = cleaned_reply.strip()

    if cleaned_reply != ai_reply.strip():
        self._logger.info(f"[{device_serial}] 🧹 Cleaned XML tags from AI reply")

    return cleaned_reply
```

## 影响范围

- 所有通过 `ResponseDetector._generate_reply()` 生成的 AI 回复
- 包括实时回复和补刀场景

## 测试建议

1. 发送测试消息，观察日志中是否显示 "🧹 Cleaned XML tags from AI reply"
2. 确认最终发送的消息不再包含 `<response>` 或其他 XML 标签

## 状态

- [x] 问题定位
- [x] 修复方案实施
- [x] 验证测试（通过）
