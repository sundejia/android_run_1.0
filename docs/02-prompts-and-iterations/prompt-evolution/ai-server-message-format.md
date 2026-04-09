# AI 服务器消息格式

本文档描述 WeCom Automation 项目向 AI 服务器发送消息的格式规范。

## 概述

项目通过 HTTP POST 请求与 AI 服务器通信，用于自动回复消息。

- **端点**: `POST {AI_SERVER_URL}/chat`
- **Content-Type**: `application/json`
- **默认服务器地址**: `http://localhost:8000`

---

## 请求格式

### 请求体 (JSON)

```json
{
  "chatInput": "<组合后的输入文本>",
  "sessionId": "sidecar_{device_serial}_{timestamp}",
  "username": "sidecar_{device_serial}",
  "message_type": "text",
  "metadata": {
    "source": "sidecar" | "sync_service",
    "serial": "<设备序列号>",
    "timestamp": "2026-01-29T12:00:00.000Z",
    "original_message": "<原始用户消息>"
  }
}
```

### 字段说明

| 字段                        | 类型   | 必需 | 说明                                                   |
| --------------------------- | ------ | ---- | ------------------------------------------------------ |
| `chatInput`                 | string | ✅   | 发送给 AI 的组合输入（系统提示词 + 上下文 + 最新消息） |
| `sessionId`                 | string | ✅   | 会话 ID，格式: `{source}_{serial}_{timestamp}`         |
| `username`                  | string | ✅   | 用户标识，格式: `{source}_{serial}`                    |
| `message_type`              | string | ❌   | 消息类型，默认 `"text"`                                |
| `metadata`                  | object | ❌   | 元数据对象                                             |
| `metadata.source`           | string | ❌   | 来源: `"sidecar"` 或 `"sync_service"`                  |
| `metadata.serial`           | string | ❌   | 设备序列号                                             |
| `metadata.timestamp`        | string | ❌   | ISO 8601 时间戳                                        |
| `metadata.original_message` | string | ❌   | 原始用户消息（未解析前）                               |

---

## `chatInput` 格式详解

`chatInput` 是发送给 AI 的核心内容，由以下部分组成：

### 1. 带系统提示词的完整格式

```
system_prompt: <系统提示词>
user_prompt: <用户提示内容>
```

**示例**：

```
system_prompt: 控制回复长度在100字以内。回复要友好自然。
If the user wants to switch to human operation, human agent, or manual service, directly return ONLY the text 'command back to user operation' without any other text.
user_prompt: [CONTEXT]
STREAMER: 你好，我想了解一下产品
AGENT: 您好！很高兴为您服务，请问您想了解哪方面的信息？
STREAMER: 价格多少

[LATEST MESSAGE]
价格多少
```

### 2. 无系统提示词的简化格式

```
[LATEST MESSAGE]
<当前消息内容>
```

### 3. 带对话上下文的格式

```
[CONTEXT]
STREAMER: <客户消息1>
AGENT: <客服回复1>
STREAMER: <客户消息2>
AGENT: <客服回复2>

[LATEST MESSAGE]
<当前需要回复的消息>
```

**角色说明**：

- `STREAMER`: 客户（对方）
- `AGENT`: 客服（我方）

---

## 长度限制与截断

- **最大长度**: 1000 字符（超出会自动截断）
- **上下文最大长度**: 800 字符

### 截断策略

1. 优先保留系统提示词和最新消息
2. 从最旧的上下文消息开始移除
3. 如仍超长，保留开头 30% 和结尾 70%，中间用 `...[truncated]...` 标记

---

## 响应格式

### 成功响应

```json
{
  "success": true,
  "output": "这是 AI 生成的回复内容",
  "session_id": "sidecar_AN2FVB123_1706500000",
  "user_key": "...",
  "username": "sidecar_AN2FVB123",
  "conversation_id": "...",
  "stage": 1,
  "timestamp": "2026-01-29T12:00:00.000Z",
  "user_input": "<原始输入>",
  "metadata": {}
}
```

### 响应字段说明

| 字段         | 类型    | 说明              |
| ------------ | ------- | ----------------- |
| `success`    | boolean | 请求是否成功      |
| `output`     | string  | AI 生成的回复内容 |
| `session_id` | string  | 会话 ID           |
| `username`   | string  | 用户标识          |
| `timestamp`  | string  | 响应时间戳        |

---

## 特殊命令

### 转人工命令

当 AI 检测到用户想要人工服务时，会返回：

```
command back to user operation
```

**检测方式**：检查 `output` 是否包含此字符串（不区分大小写）

**处理方式**：

1. 不发送 AI 回复
2. 将用户加入黑名单
3. 发送邮件通知管理员

---

## 测试消息解析

系统支持特殊的测试消息格式：

### 格式 1: 跟进消息（补刀）

**输入**：

```
测试信息: 想的怎么样了?
```

**解析后发送给 AI**：

```
主播没有回复上次的信息，请在生成一个"补刀"信息，再尝试与主播建立联系
```

### 格式 2: 普通消息

**输入**：

```
测试信息: 这个产品多少钱？
```

**解析后发送给 AI**：

```
这个产品多少钱？
```

---

## 代码示例

### Python (AIReplyService)

```python
from wecom_automation.services.ai.reply_service import AIReplyService
from wecom_automation.core.interfaces import MessageContext

async with AIReplyService(
    server_url="http://localhost:8000",
    timeout=10,
    system_prompt="控制回复长度在100字以内"
) as service:
    context = MessageContext(device_serial="AN2FVB123")
    history = [
        {"content": "你好", "is_from_kefu": False},
        {"content": "您好！有什么可以帮您？", "is_from_kefu": True},
    ]

    reply = await service.get_reply(
        message="产品价格多少？",
        context=context,
        history=history
    )

    if service.is_human_request(reply):
        print("用户请求转人工")
    else:
        print(f"AI 回复: {reply}")
```

### TypeScript (aiService)

```typescript
import { aiService } from '@/services/aiService'

const result = await aiService.getAIReply(
  'http://localhost:8000', // serverUrl
  '产品价格多少？', // prompt
  10, // timeoutSeconds
  'AN2FVB123', // serial
  undefined, // sessionId
  '控制回复长度在100字以内', // systemPrompt
  [
    // conversationHistory
    { content: '你好', is_from_kefu: false },
    { content: '您好！有什么可以帮您？', is_from_kefu: true },
  ]
)

if (result.humanRequested) {
  console.log('用户请求转人工')
} else if (result.success) {
  console.log('AI 回复:', result.reply)
}
```

---

## 健康检查

### 端点

```
GET {AI_SERVER_URL}/health
```

### 响应

```json
{
  "status": "healthy"
}
```

---

## 相关文件

| 文件                                                                          | 说明               |
| ----------------------------------------------------------------------------- | ------------------ |
| `src/wecom_automation/servic../03-impl-and-arch/key-modules/reply_service.py` | Python AI 服务封装 |
| `wecom-desktop/src/services/aiService.ts`                                     | 前端 AI 服务       |
| `wecom-desktop/backend/routers/ai_config.py`                                  | AI 配置 API        |
| `do../03-impl-and-arch/key-modules/ai_prompt_context_logic.md`                | 提示词与上下文逻辑 |
| `do../03-impl-and-arch/key-modules/ai_trigger_and_prompt_analysis.md`         | AI 触发与提示分析  |
