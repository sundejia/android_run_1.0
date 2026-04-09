# AI 提示词和上下文拼接逻辑文档

> 文档创建于：2026-01-19  
> 版本：v1.0

本文档详细说明 **Generate 按钮** 和 **AI Reply** 功能中使用的提示词构建和上下文拼接逻辑。

---

## 目录

1. [概述](#概述)
2. [触发入口](#触发入口)
3. [提示词构建流程](#提示词构建流程)
4. [上下文拼接逻辑](#上下文拼接逻辑)
5. [最终提示词结构](#最终提示词结构)
6. [AI 服务器请求格式](#ai-服务器请求格式)
7. [代码位置索引](#代码位置索引)

---

## 概述

系统中有两个主要场景使用 AI 回复功能：

| 场景                | 来源                            | 描述                         |
| ------------------- | ------------------------------- | ---------------------------- |
| **Generate 按钮**   | 前端 Sidecar 页面               | 用户手动点击按钮生成 AI 回复 |
| **AI Reply (自动)** | 后端 Followup/Response Detector | 同步过程中自动生成 AI 回复   |

两者都遵循相同的提示词拼接逻辑，只是触发方式不同。

---

## 触发入口

### 1. Generate 按钮 (前端)

**文件**: `wecom-desktop/src/views/SidecarView.vue`  
**函数**: `generateReply(serial: string)`

```typescript
async function generateReply(serial: string) {
  // 1. 获取当前对话的最后一条消息
  const lastMsgResponse = await api.getLastMessage(serial)

  // 2. 判断是"补刀"模式还是"回复"模式
  const isFollowUp = lastMsg.is_from_kefu // 客服发的 → 补刀模式

  // 3. 获取对话历史（最近 10 条）
  const conversationHistory = panel.historyMessages.slice(-10)

  // 4. 调用 AI 服务
  const aiResult = await aiService.processTestMessage(
    testMessage,
    settings.value.aiServerUrl,
    settings.value.aiReplyTimeout,
    serial,
    settingsStore.combinedSystemPrompt, // ★ 组合后的系统提示词
    conversationHistory // ★ 对话历史上下文
  )
}
```

### 2. AI Reply (后端 - 响应检测)

**文件**: `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`  
**函数**: `_generate_reply()`

### 3. AI Reply (后端 - 补刀扫描)

**文件**: `wecom-desktop/backend/servic../03-impl-and-arch/scanner.py`  
**函数**: `_generate_ai_followup_message()`

---

## 提示词构建流程

### 系统提示词组成

系统提示词 (`combinedSystemPrompt`) 由以下三部分拼接而成：

```
┌─────────────────────────────────────────────────────────────┐
│                    组合后的系统提示词                          │
├─────────────────────────────────────────────────────────────┤
│  1. 自定义提示词 (systemPrompt)                               │
│     └── 用户在设置页面自定义的提示词                          │
│                                                             │
│  2. 预设风格提示词 (promptStyleKey)                          │
│     └── 五种预设风格之一（无预设/默认/活泼/专业/极简）          │
│                                                             │
│  3. 长度限制指令                                             │
│     └── 将回复控制在 XX 字以内                               │
└─────────────────────────────────────────────────────────────┘
```

### 前端组合逻辑

**文件**: `wecom-desktop/src/stores/settings.ts`

```typescript
const combinedSystemPrompt = computed(() => {
  const stylePreset = PROMPT_STYLE_PRESETS.find((p) => p.key === settings.value.promptStyleKey)
  const stylePrompt = stylePreset?.prompt || ''
  const customPrompt = settings.value.systemPrompt || ''
  const maxLength = settings.value.aiReplyMaxLength || 50

  // 组合顺序：自定义提示词优先，然后是预设风格
  let basePrompt = ''
  if (customPrompt && stylePrompt) {
    basePrompt = `${customPrompt}\n\n${stylePrompt}`
  } else {
    basePrompt = customPrompt || stylePrompt
  }

  // 检查是否已有长度限制指令
  const hasLengthLimit = /将?回复控制在\s*\d+\s*字/.test(basePrompt)

  // 只有在没有长度限制时才添加
  if (!hasLengthLimit) {
    const lengthInstruction = `\n\n将回复控制在 ${maxLength} 字以内。`
    return basePrompt + lengthInstruction
  }

  return basePrompt
})
```

### 后端组合逻辑

**文件**: `wecom-desktop/backend/servic../03-impl-and-arch/key-modules/service.py`

```python
def get_combined_system_prompt(self) -> str:
    custom_prompt = self.get_system_prompt()
    preset_key = self.get(SettingCategory.AI_REPLY.value, "prompt_style_key", "none")
    max_length = self.get(SettingCategory.AI_REPLY.value, "reply_max_length", 50)

    # 查找预设
    preset = next((p for p in PROMPT_STYLE_PRESETS if p["key"] == preset_key), None)
    style_prompt = preset["prompt"] if preset else ""

    # 组合提示词
    base_prompt = ""
    if custom_prompt and style_prompt:
        base_prompt = f"{custom_prompt}\n\n{style_prompt}"
    else:
        base_prompt = custom_prompt or style_prompt

    # 检查是否已有长度限制指令
    has_length_limit = bool(re.search(r'将?回复控制在\s*\d+\s*字', base_prompt))

    if not has_length_limit:
        length_instruction = f"\n\n将回复控制在 {max_length} 字以内。"
        return base_prompt + length_instruction if base_prompt else f"将回复控制在 {max_length} 字以内。"

    return base_prompt
```

### 预设风格列表

| Key            | 名称          | 描述                 |
| -------------- | ------------- | -------------------- |
| `none`         | 无预设        | 不使用预设风格       |
| `default`      | 默认风格      | 礼貌大方，有条理     |
| `lively`       | 活泼风格      | 热情活泼，像朋友一样 |
| `professional` | 专业风格      | 正式商务用语         |
| `minimal`      | 极简/高效风格 | 直接高效，不寒暄     |

---

## 上下文数据来源对比

> ⚠️ **重要差异**：前端和后端获取对话上下文的方式完全不同！

### 前端 (Generate 按钮) - 从数据库读取

前端通过 API 从数据库获取历史消息，这些消息是之前同步过程中存储的。

**数据流**：

```
数据库 (messages 表) → API → 前端 historyMessages → AI 上下文
```

**代码位置**: `SidecarView.vue`

```typescript
// 1. 先获取对话历史（从数据库）
await fetchConversationHistory(serial)

// 2. 从缓存的历史消息中取最近 10 条
const conversationHistory = panel.historyMessages
  .slice(-10)
  .map((msg) => ({
    content: msg.content || '',
    is_from_kefu: msg.is_from_kefu,
  }))
  .filter((msg) => msg.content)

// 3. 调用 AI 服务
const aiResult = await aiService.processTestMessage(
  testMessage,
  serverUrl,
  timeout,
  serial,
  settingsStore.combinedSystemPrompt,
  conversationHistory // ← 来自数据库
)
```

**API 调用**:

```
GET /a../03-impl-and-arch/{serial}/conversation-history
    ?contact_name={name}&channel={channel}&limit=100
```

### 后端 (AI Reply 自动回复) - 从 UI 树实时提取

后端直接从手机屏幕的 UI 树中实时提取当前可见的消息，**不从数据库读取上下文**。

**数据流**：

```
手机屏幕 → ADB UI Dump → UI 解析器 → 消息列表 → AI 上下文
```

**代码位置**: `response_detector.py` 和 `scanner.py`

```python
# response_detector.py - 响应检测时
async def _process_unread_user_with_wait(self, ...):
    # Step 2: 从 UI 树提取可见消息（不滚动）
    messages = await self._extract_visible_messages(wecom, serial)

    # Step 3: 将消息存储到数据库（先写入，再生成回复）
    stored_count = await self._store_messages_to_db(...)

    # Step 4: 生成 AI 回复，使用最近 5 条消息作为上下文
    reply = await self._generate_reply(user_name, messages[-5:], serial)
```

```python
# scanner.py - 补刀扫描时
async def _handle_kefu_last_message(self, ...):
    if settings.use_ai_reply:
        # 获取对话消息用于 AI 上下文（从 UI 树实时提取）
        tree = await wecom.adb.get_ui_tree()
        messages = wecom.ui_parser.extract_conversation_messages(tree) if tree else []

        # 使用这些消息生成 AI 补刀
        msg_text = await self._generate_ai_followup_message(
            user_name, messages, serial, attempt_number
        )
```

### 对比总结

| 特性             | 前端 (Generate)              | 后端 (AI Reply)                                   |
| ---------------- | ---------------------------- | ------------------------------------------------- |
| **数据来源**     | 📊 数据库 `messages` 表      | 📱 手机 UI 树实时提取                             |
| **消息数量**     | 最近 10 条                   | 最近 5-10 条（可见消息）                          |
| **是否包含历史** | ✅ 包含所有历史同步的消息    | ❌ 只有当前屏幕可见的消息                         |
| **实时性**       | 可能有延迟（需等待同步）     | 实时最新                                          |
| **可靠性**       | 稳定（已存储的数据）         | 取决于 UI 解析成功率                              |
| **获取方式**     | API: `/conversation-history` | `wecom.ui_parser.extract_conversation_messages()` |

### 后端 UI 提取方法详解

```python
async def _extract_visible_messages(self, wecom, serial: str) -> List[Any]:
    """提取当前可见消息（不滚动）"""
    try:
        tree = await wecom.adb.get_ui_tree()  # 获取 UI 树
        if not tree:
            return []
        return wecom.ui_parser.extract_conversation_messages(tree)  # 解析消息
    except Exception as e:
        self._logger.warning(f"[{serial}] Failed to extract messages: {e}")
        return []
```

### 为什么后端不从数据库读取？

1. **实时性需求**：后端在同步过程中需要获取最新消息，数据库中的消息可能还未写入
2. **同步流程顺序**：后端是"先提取消息 → 再存入数据库 → 再生成回复"
3. **避免循环依赖**：如果先写入再读取，会增加额外的 I/O 开销
4. **处理新消息**：在交互等待循环中，需要实时检测新的客户消息

---

## 上下文拼接逻辑

### 对话历史格式化

**文件**: `wecom-desktop/src/services/aiService.ts`

```typescript
formatConversationContext(
  conversationHistory: Array<{ content: string; is_from_kefu: boolean }>,
  currentMessage: string,
  maxLength: number = 800
): string {
  // 构建上下文行
  const contextLines: string[] = []
  for (const msg of conversationHistory) {
    if (!msg.content || !msg.content.trim()) continue
    // AGENT = kefu (我们), STREAMER = customer (客户)
    const role = msg.is_from_kefu ? 'AGENT' : 'STREAMER'
    contextLines.push(`${role}: ${msg.content}`)
  }

  // 构建最新消息部分（总是包含）
  const latestPart = `[LATEST MESSAGE]\n${currentMessage}`

  // 如果没有上下文，只返回最新消息
  if (contextLines.length === 0) {
    return latestPart
  }

  // 迭代减少上下文直到满足长度限制
  while (contextLines.length > 0) {
    const parts = ['[CONTEXT]', ...contextLines, '', latestPart]
    const formatted = parts.join('\n')

    if (formatted.length <= maxLength) {
      return formatted
    }

    // 移除最早的消息
    contextLines.shift()
  }

  return latestPart
}
```

### 上下文格式示例

```
[CONTEXT]
STREAMER: 你好，我想咨询一下合作的事情
AGENT: 您好！非常感谢您的关注，请问您想了解哪方面的合作呢？
STREAMER: 主要是直播带货这块
AGENT: 好的，我们有专业的直播带货团队...

[LATEST MESSAGE]
主播没有回复上次的信息，请生成一个"补刀"信息
```

### 消息类型判断

| 场景         | 判断条件                       | 发送的提示词                                                         |
| ------------ | ------------------------------ | -------------------------------------------------------------------- |
| **补刀模式** | `lastMsg.is_from_kefu = true`  | `主播没有回复上次的信息，请生成一个"补刀"信息，再尝试与主播建立联系` |
| **回复模式** | `lastMsg.is_from_kefu = false` | 直接使用客户消息内容                                                 |

---

## 最终提示词结构

前端和后端最终发送给 AI 服务器的输入格式是统一的：

```
system_prompt: [组合后的系统提示词]
user_prompt: [格式化后的对话上下文]
```

### 完整示例

```
system_prompt: 你是一个专业的客服助手。
语气礼貌大方，使用"您"称呼用户。
回答要直接且有条理，避免冗长。

将回复控制在 50 字以内。

If the user wants to switch to human operation, human agent, or manual service, directly return ONLY the text 'command back to user operation' without any other text.

user_prompt: [CONTEXT]
STREAMER: 你好，我想咨询一下合作的事情
AGENT: 您好！非常感谢您的关注
STREAMER: 主要是直播带货这块

[LATEST MESSAGE]
主要是直播带货这块
```

### 长度限制机制

1. **上下文长度限制**: 最多 800 字符（超出则移除最早的消息）
2. **最终输入限制**: 最多 1000 字符（超出则智能截断）
3. **回复长度限制**: 通过系统提示词指定（默认 50 字）

```typescript
// aiService.ts
truncateFinalInput(input: string, maxLength: number = 1000): string {
  if (input.length <= maxLength) {
    return input
  }

  // 智能截断：保留 system_prompt 和最新消息
  const systemPromptMatch = input.match(/^system_prompt: ([\s\S]*?)\nuser_prompt: /)
  if (systemPromptMatch) {
    const systemPromptPart = systemPromptMatch[0]
    const userPromptPart = input.slice(systemPromptMatch[0].length)

    const availableForUser = maxLength - systemPromptPart.length
    if (availableForUser > 100) {
      const truncatedUser = userPromptPart.slice(-availableForUser)
      return systemPromptPart + truncatedUser
    }
  }

  // 备用方案：保留开头 30%，结尾 70%
  const keepStart = Math.floor(maxLength * 0.3)
  const keepEnd = maxLength - keepStart - 20
  return input.slice(0, keepStart) + '\n...[truncated]...\n' + input.slice(-keepEnd)
}
```

---

## AI 服务器请求格式

### 请求端点

```
POST {aiServerUrl}/chat
```

### 请求体结构

```json
{
  "chatInput": "system_prompt: ...\nuser_prompt: ...",
  "sessionId": "sidecar_DEVICE_SERIAL_TIMESTAMP",
  "username": "sidecar_DEVICE_SERIAL",
  "message_type": "text",
  "metadata": {
    "source": "sidecar",
    "serial": "DEVICE_SERIAL",
    "timestamp": "2026-01-19T19:27:36+08:00"
  }
}
```

### 响应体结构

```json
{
  "output": "AI生成的回复文本",
  "session_id": "...",
  "user_key": "...",
  "username": "...",
  "conversation_id": "...",
  "stage": 0,
  "timestamp": "...",
  "user_input": "...",
  "success": true
}
```

### 特殊指令处理

当 AI 返回以下文本时，表示用户要求人工服务：

```
command back to user operation
```

系统会：

1. 不发送任何回复
2. 将用户加入黑名单
3. 发送邮件通知（如果启用）

---

## 代码位置索引

### 前端代码

| 文件                        | 函数/变量                     | 描述                  |
| --------------------------- | ----------------------------- | --------------------- |
| `src/views/SidecarView.vue` | `generateReply()`             | Generate 按钮触发函数 |
| `src/services/aiService.ts` | `processTestMessage()`        | 处理测试消息并调用 AI |
| `src/services/aiService.ts` | `getAIReply()`                | 发送请求到 AI 服务器  |
| `src/services/aiService.ts` | `formatConversationContext()` | 格式化对话上下文      |
| `src/services/aiService.ts` | `truncateFinalInput()`        | 截断过长的输入        |
| `src/stores/settings.ts`    | `combinedSystemPrompt`        | 组合后的系统提示词    |
| `src/stores/settings.ts`    | `PROMPT_STYLE_PRESETS`        | 预设风格列表          |

### 后端代码

| 文件                                                       | 函数                               | 描述                          |
| ---------------------------------------------------------- | ---------------------------------- | ----------------------------- |
| `backend/servic../03-impl-and-arch/key-modules/service.py` | `get_combined_system_prompt()`     | 获取组合后的系统提示词        |
| `backend/servic../03-impl-and-arch/scanner.py`             | `_generate_ai_followup_message()`  | 生成 AI 补刀消息              |
| `backend/servic../03-impl-and-arch/scanner.py`             | `_handle_kefu_last_message()`      | 处理客服最后消息的情况        |
| `backend/servic../03-impl-and-arch/response_detector.py`   | `_generate_reply()`                | 生成 AI 回复消息              |
| `backend/servic../03-impl-and-arch/response_detector.py`   | `_extract_visible_messages()`      | 从 UI 树提取可见消息          |
| `backend/servic../03-impl-and-arch/response_detector.py`   | `_process_unread_user_with_wait()` | 处理未读用户（带交互等待）    |
| `backend/routers/sidecar.py`                               | `get_conversation_history()`       | API: 从数据库获取对话历史     |
| `backend/routers/sidecar.py`                               | `get_last_message()`               | API: 获取当前对话最后一条消息 |

---

## 数据流图

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                            用户点击 Generate 按钮                             │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Step 1: 获取最后一条消息                                                      │
│         API: /a../03-impl-and-arch/{serial}/last-message                              │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Step 2: 判断消息类型                                                          │
│         ├── is_from_kefu = true  → 补刀模式 (Follow-up)                       │
│         └── is_from_kefu = false → 回复模式 (Reply)                           │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Step 3: 获取对话历史                                                          │
│         ├── 从 historyMessages 获取最近 10 条消息                             │
│         └── 过滤空消息，保留有效内容                                          │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Step 4: 构建系统提示词                                                        │
│         ├── 自定义提示词 (systemPrompt)                                       │
│         ├── 预设风格提示词 (promptStyleKey)                                   │
│         └── 长度限制指令 (aiReplyMaxLength)                                   │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Step 5: 格式化对话上下文                                                      │
│         ├── [CONTEXT] 对话历史（AGENT/STREAMER 角色标记）                     │
│         └── [LATEST MESSAGE] 当前消息                                         │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Step 6: 拼接最终输入                                                          │
│         system_prompt: [组合后的系统提示词]                                   │
│         user_prompt: [格式化后的对话上下文]                                   │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Step 7: 截断处理                                                              │
│         └── 确保最终输入不超过 1000 字符                                      │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Step 8: 发送到 AI 服务器                                                      │
│         POST {aiServerUrl}/chat                                               │
│         Body: { chatInput, sessionId, username, metadata }                    │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Step 9: 处理响应                                                              │
│         ├── success = true → 显示回复到输入框                                 │
│         ├── humanRequested = true → 跳过用户，加入黑名单                      │
│         └── success = false → 回退到模拟消息                                  │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 注意事项

1. **上下文消息数量**: 前端最多使用 **10 条** 历史消息，后端最多使用 **5-10 条**
2. **角色标记**: 前端使用 `AGENT/STREAMER`，后端使用 `AGENT/CUSTOMER`
3. **超时时间**: 默认 10 秒，可在设置中调整
4. **长度限制**:
   - 上下文部分最多 800 字符
   - 最终输入最多 1000 字符
   - AI 回复长度通过系统提示词控制
5. **人工转接检测**: AI 返回 `command back to user operation` 时触发人工转接流程
