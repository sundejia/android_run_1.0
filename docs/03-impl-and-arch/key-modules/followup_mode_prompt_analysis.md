# 补刀模式检测与提示词变化分析

## 概述

当系统检测到"补刀模式"（follow-up mode）时，**提示词确实会发生变化**。

## 检测逻辑

### 补刀模式触发条件

当**客服发送了最后一条消息**（客户没有回复），系统会进入补刀模式。

**位置**: `wecom-desktop/src/services/aiService.ts` 第 90-113 行

```typescript
parseTestMessage(message: string): { type: 'followup' | 'reply' | 'unknown'; content: string } {
  // Check if it's a test message
  if (!trimmed.startsWith('测试信息:') && !trimmed.startsWith('测试信息：')) {
    return { type: 'unknown', content: trimmed }
  }

  // Extract content after "测试信息:"
  const content = prefixMatch[1].trim()

  // Check for the specific follow-up pattern
  if (content === '想的怎么样了?' || content === '想的怎么样了？') {
    return { type: 'followup', content }  // ← 补刀模式
  }

  // Otherwise it's a regular reply
  return { type: 'reply', content }  // ← 普通回复模式
}
```

### 检测方式

| 检测条件                   | 消息格式                  | 类型              |
| -------------------------- | ------------------------- | ----------------- |
| 消息内容是 `想的怎么样了?` | `测试信息: 想的怎么样了?` | `followup` (补刀) |
| 其他内容                   | `测试信息: [客户消息]`    | `reply` (回复)    |

## 提示词变化

### 补刀模式 vs 回复模式

**位置**: `wecom-desktop/src/services/aiService.ts` 第 118-127 行

```typescript
getAIPrompt(parsed: { type: 'followup' | 'reply' | 'unknown'; content: string }): string {
  if (parsed.type === 'followup') {
    // 补刀模式 - 使用特殊提示词
    return '主播没有回复上次的信息，请在生成一个"补刀"信息，再尝试与主播建立联系'
  }
  if (parsed.type === 'reply') {
    // 回复模式 - 使用客户消息内容
    return parsed.content
  }
  return parsed.content
}
```

### 对比表

| 模式         | 场景                             | AI 提示词                                                              | 目的             |
| ------------ | -------------------------------- | ---------------------------------------------------------------------- | ---------------- |
| **补刀模式** | 客服发了最后一条消息，客户没回复 | `主播没有回复上次的信息，请在生成一个"补刀"信息，再尝试与主播建立联系` | 重新吸引客户注意 |
| **回复模式** | 客户发了消息，需要回复           | 客户消息的实际内容                                                     | 直接回复客户问题 |

## 完整流程

```
[同步或 Sidecar 检测]
        ↓
检测最后一条消息发送者
        ↓
        ├── 客户发的 (is_self=false)
        │       ↓
        │   生成回复消息
        │       ↓
        │   测试信息: [客户消息内容]
        │       ↓
        │   parseTestMessage() → type='reply'
        │       ↓
        │   提示词 = 客户消息内容
        │
        └── 客服发的 (is_self=true)
                ↓
            生成补刀消息
                ↓
            测试信息: 想的怎么样了?
                ↓
            parseTestMessage() → type='followup'
                ↓
            提示词 = "主播没有回复上次的信息..."
```

## 代码位置

| 文件                                                                          | 描述                              |
| ----------------------------------------------------------------------------- | --------------------------------- |
| `wecom-desktop/src/services/aiService.ts`                                     | AI 服务，包含消息解析和提示词生成 |
| `src/wecom_automation/servic../03-impl-and-arch/key-modules/reply_service.py` | 后端 AI 回复服务                  |
| `initial_sync.py`                                                             | 同步脚本中的补刀逻辑              |

## 后端对应逻辑

**位置**: `src/wecom_automation/servic../03-impl-and-arch/key-modules/reply_service.py` 第 223-227 行

```python
def _get_prompt_by_message_type(self, message_type: str) -> str:
    """根据消息类型获取提示词"""
    if message_type == 'followup':
        return '主播没有回复上次的信息，请在生成一个"补刀"信息，再尝试与主播建立联系'
    return ''  # reply 类型使用原始内容
```

## 总结

**是的，检测到补刀模式时提示词会发生变化：**

- **回复模式**: 直接使用客户发送的消息内容作为提示词
- **补刀模式**: 使用固定提示词 `"主播没有回复上次的信息，请在生成一个"补刀"信息，再尝试与主播建立联系"`

这种设计让 AI 能够：

1. 在回复模式下针对客户问题生成相关回复
2. 在补刀模式下生成重新吸引客户关注的消息
