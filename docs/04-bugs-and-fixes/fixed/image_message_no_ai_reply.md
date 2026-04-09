# Bug 分析：图片消息无法触发 AI 回复

> 时间: 2026-01-18  
> 状态: ✅ 已修复

---

## 问题描述

当客户发送的最后一条消息是**图片**时，系统无法调用 AI 回复。

### 日志表现

```
[DEBUG] sync: Image message skipped (duplicate)
[DEBUG] sync: Empty message, skipping reply
```

---

## 根因分析

### 问题代码位置

**文件**: `src/wecom_automation/services/sync/customer_syncer.py`  
**方法**: `_send_reply_to_customer` (第 440-497 行)

```python
async def _send_reply_to_customer(
    self,
    customer_msg: Any,
    customer: Any,
    context: MessageContext,
) -> bool:
    try:
        message_content = getattr(customer_msg, 'content', '') or ''
        if not message_content:
            self._logger.debug("Empty message, skipping reply")  # ← 问题在这里
            return False

        # ... 后续生成 AI 回复的代码
```

### 问题原因

1. **图片消息的 `content` 字段为空**
   - 图片消息的 `content` 通常是空字符串 `""`
   - 代码检测到 `content` 为空，直接返回 `False`，跳过 AI 回复

2. **逻辑缺陷**
   - 当前代码假设所有消息都有文本内容
   - 没有考虑图片、语音等非文本消息类型

---

## 解决方案

### 方案 A: 为图片消息生成描述性内容

修改 `_send_reply_to_customer` 方法，对图片消息进行特殊处理：

```python
async def _send_reply_to_customer(
    self,
    customer_msg: Any,
    customer: Any,
    context: MessageContext,
) -> bool:
    try:
        message_type = getattr(customer_msg, 'message_type', 'text')
        message_content = getattr(customer_msg, 'content', '') or ''

        # 处理非文本消息类型
        if not message_content:
            if message_type == 'image':
                message_content = "[客户发送了一张图片]"
            elif message_type == 'video':
                message_content = "[客户发送了一个视频]"
            else:
                self._logger.debug("Empty message with unknown type, skipping reply")
                return False

        # 后续 AI 回复逻辑...
```

## 影响范围

| 场景       | 影响                   |
| ---------- | ---------------------- |
| 全量同步   | 客户发图片后无 AI 回复 |
| 交互式等待 | 图片消息被检测但不回复 |
| 补刀系统   | 可能也受影响（需检查） |

---

## 建议修复

推荐使用 **方案 A**，原因：

1. 改动最小
2. 向 AI 传递有意义的上下文（告知 AI 客户发了图片）
3. AI 可以根据对话历史生成合适的回复（如"收到您的图片，请问有什么问题？"）

---

## 相关文件

- `src/wecom_automation/services/sync/customer_syncer.py` - 主要修改
- `src/wecom_automation/services/message/handlers/image.py` - 图片消息处理
- `docs/ai_trigger_and_prompt_analysis.md` - AI 触发条件文档
