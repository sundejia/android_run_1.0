# 消息发送控制代码流程分析

本文档详细分析了 wecom-desktop 项目中消息发送的完整流程，包括前端、后端和自动化服务三层架构。

## 目录

- [架构概览](#架构概览)
- [消息发送模式](#消息发送模式)
- [前端代码流程](#前端代码流程)
- [后端API流程](#后端api流程)
- [自动化服务流程](#自动化服务流程)
- [AI服务集成](#ai服务集成)
- [消息内容生成规则](#消息内容生成规则)

---

## 架构概览

```
┌─────────────────────────────────────────────────────────────────────┐
│                         前端 (Vue.js)                                │
│  SidecarView.vue → sendNow() / generateReply()                      │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      后端 API (FastAPI)                              │
│../03-impl-and-arch/{serial}/send          → 直接发送                          │
│../03-impl-and-arch/{serial}/send-and-save → 发送并保存到数据库                 │
│../03-impl-and-arch/{serial}/queue/send    → 队列模式发送                       │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   自动化服务 (wecom_automation)                       │
│  WeComService.send_message() → ADB 操作发送消息                       │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Android 设备                                  │
│  企业微信 App → 输入框 → 发送按钮                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 消息发送模式

### 1. 手动发送模式 (Sidecar)

用户在 Sidecar 界面手动输入或生成消息，点击 "Send now" 发送。

### 2. 队列模式 (Queue Mode)

同步过程中，消息先进入队列，等待用户确认后发送。

### 3. 自动同步模式 (Sync)

批量同步时自动发送测试消息，无需人工干预。

---

## 前端代码流程

### 文件位置

`wecom-desktop/src/views/SidecarView.vue`

### 核心函数: `sendNow()`

```typescript
async function sendNow(serial: string) {
  const panel = ensurePanel(serial)
  const message = panel.pendingMessage.trim()

  // 1. 检查消息是否为空
  if (!message) {
    panel.statusMessage = '没有内容可以发送'
    return
  }

  // 2. 队列模式：使用队列API发送
  if (panel.queueMode && panel.currentQueuedMessage) {
    await sendQueuedMessage(serial)
    return
  }

  // 3. 检查同步状态
  const syncStatus = deviceStore.getSyncStatus(serial)
  const isSyncRunning = syncStatus && ['running', 'starting'].includes(syncStatus.status)

  if (isSyncRunning) {
    // 同步中：使用 send-and-save API（发送并保存到数据库）
    const result = await api.sendAndSaveMessage(serial, message, contactName, channel)
  } else {
    // 非同步：使用普通 send API
    const result = await api.sendSidecarMessage(serial, message)
  }
}
```

### 核心函数: `generateReply()` - 生成AI回复

```typescript
async function generateReply(serial: string) {
  // 1. 获取最后一条消息
  const lastMsgResponse = await api.getLastMessage(serial)
  const lastMsg = lastMsgResponse.last_message

  // 2. 判断消息类型
  const isFollowUp = lastMsg.is_from_kefu // 客服发的 = 补刀模式

  // 3. 构建测试消息格式
  let testMessage: string
  if (isFollowUp) {
    testMessage = '测试信息: 想的怎么样了?'
  } else {
    const content = lastMsg.content || '[media]'
    testMessage = `测试信息: [...${content.slice(0, 30)}...]`
  }

  // 4. 调用AI服务或使用Mock
  if (settings.value.useAIReply) {
    const aiResult = await aiService.processTestMessage(
      testMessage,
      settings.value.aiServerUrl,
      settings.value.aiReplyTimeout,
      serial
    )

    if (aiResult.success && aiResult.reply) {
      panel.pendingMessage = aiResult.reply // AI生成的回复
    } else {
      panel.pendingMessage = testMessage // 降级使用Mock消息
    }
  } else {
    panel.pendingMessage = testMessage // 直接使用Mock消息
  }
}
```

---

## 后端API流程

### 文件位置

`wecom-desktop/backend/routers/sidecar.py`

### API 端点

#### 1. 直接发送: `POS../03-impl-and-arch/{serial}/send`

```python
@router.post("/{serial}/send")
async def send_sidecar_message(serial: str, request: SendMessageRequest):
    """直接发送消息到设备"""
    session = get_session(serial)
    message = request.message.strip()

    success = await session.send_message(message)
    return SendMessageResponse(success=success)
```

#### 2. 发送并保存: `POS../03-impl-and-arch/{serial}/send-and-save`

```python
@router.post("/{serial}/send-and-save")
async def send_and_save_message(serial: str, request: SendAndSaveRequest):
    """发送消息并保存到数据库（同步中使用）"""
    session = get_session(serial)

    # 1. 发送消息
    success = await session.send_message(message)

    if success:
        # 2. 查找客户
        customer = find_customer(contact_name, channel)

        # 3. 保存到数据库
        cursor.execute("""
            INSERT INTO messages (customer_id, content, message_type, is_from_kefu, ...)
            VALUES (?, ?, 'text', 1, ...)
        """, (customer_id, message, ...))

    return SendAndSaveResponse(success=success, message_saved=True)
```

#### 3. 队列发送: `POS../03-impl-and-arch/{serial}/queue/send/{message_id}`

```python
@router.post("/{serial}/queue/send/{message_id}")
async def send_queued_message(serial: str, message_id: str):
    """发送队列中的消息"""
    queue = _get_queue(serial)
    msg = next((m for m in queue if m.id == message_id), None)

    msg.status = MessageStatus.SENDING
    success = await session.send_message(msg.message)

    if success:
        msg.status = MessageStatus.SENT
        # 通知等待中的同步进程
        event = _get_waiting_event(serial)
        event.set()
```

### SidecarSession 类

```python
class SidecarSession:
    """管理每个设备的会话"""

    async def send_message(self, text: str) -> bool:
        """通过自动化服务发送消息"""
        self._send_idle.clear()  # 标记正在发送
        try:
            async with self.lock:
                await self.ensure_connected()
                success, _ = await self.service.send_message(text)
                return success
        finally:
            self._send_idle.set()  # 发送完成
```

---

## 自动化服务流程

### 文件位置

`src/wecom_automation/services/wecom_service.py`

### 核心函数: `send_message()`

```python
async def send_message(self, text: str) -> Tuple[bool, str]:
    """
    发送文本消息到当前对话

    步骤:
    1. 查找并点击输入框
    2. 输入消息文本
    3. 点击发送按钮
    """
    # 1. 获取UI状态
    ui_tree, elements = await self.adb.get_ui_state()

    # 2. 查找输入框并点击
    input_field = self._find_input_field(elements)
    if input_field:
        await self.adb.tap(input_field["index"])
        await self.adb.wait(self.config.timing.tap_delay)

    # 3. 输入文本
    await self.adb.input_text(text)
    await self.adb.wait(self.config.timing.ui_stabilization_delay)

    # 4. 刷新UI状态
    ui_tree, elements = await self.adb.get_ui_state(force=True)

    # 5. 查找并点击发送按钮
    send_button = self._find_send_button(elements)
    if send_button:
        await self._tap_element(send_button)
        return True, text

    # 6. 降级: 按回车键发送
    await self.adb.press_enter()
    return True, text
```

---

## AI服务集成

### 文件位置

`wecom-desktop/src/services/aiService.ts`

### AI回复流程

```typescript
class AIService {
  /**
   * 解析测试消息，提取AI提示词
   */
  parseTestMessage(message: string): { type: 'followup' | 'reply' | 'unknown'; content: string } {
    // 检查是否是测试消息格式
    if (!message.startsWith('测试信息:')) {
      return { type: 'unknown', content: message }
    }

    const content = message.replace(/^测试信息[:：]\s*/, '').trim()

    // 判断类型
    if (content === '想的怎么样了?') {
      return { type: 'followup', content } // 补刀模式
    }
    return { type: 'reply', content } // 回复模式
  }

  /**
   * 获取AI提示词
   */
  getAIPrompt(parsed): string {
    if (parsed.type === 'followup') {
      // 补刀模式：让AI生成跟进消息
      return '主播没有回复上次的信息，请在生成一个"补刀"信息，再尝试与主播建立联系'
    }
    // 回复模式：直接使用客户消息作为上下文
    return parsed.content
  }

  /**
   * 调用AI服务器获取回复
   */
  async getAIReply(serverUrl: string, prompt: string, timeout: number, serial: string) {
    const requestBody = {
      chatInput: prompt,
      sessionId: `sidecar_${serial}_${Date.now()}`,
      username: `sidecar_${serial}`,
      message_type: 'text',
      metadata: { source: 'sidecar', serial },
    }

    const response = await fetch(`${serverUrl}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody),
    })

    return response.json()
  }
}
```

### AI服务器请求格式

```json
{
  "chatInput": "主播没有回复上次的信息，请在生成一个补刀信息",
  "sessionId": "sidecar_ABC123_1703318400000",
  "username": "sidecar_ABC123",
  "message_type": "text",
  "metadata": {
    "source": "sidecar",
    "serial": "ABC123",
    "timestamp": "2025-12-23T12:00:00Z"
  }
}
```

### AI服务器响应格式

```json
{
  "output": "亲，想好了吗？这个活动马上就要结束了哦～",
  "session_id": "xxx",
  "success": true,
  "metadata": {
    "agent_name": "销售助手",
    "confidence": 0.9,
    "processing_time_ms": 1234
  }
}
```

---

## 消息内容生成规则

### 1. Mock 消息（无AI时）

| 场景                     | 消息格式                             |
| ------------------------ | ------------------------------------ |
| 补刀（客服发的最后一条） | `测试信息: 想的怎么样了?`            |
| 回复（客户发的最后一条） | `测试信息: [...{客户消息前30字}...]` |

### 2. AI 消息（启用AI时）

| 场景 | AI提示词                                         | 预期输出           |
| ---- | ------------------------------------------------ | ------------------ |
| 补刀 | `主播没有回复上次的信息，请在生成一个"补刀"信息` | AI生成的跟进消息   |
| 回复 | `{客户的消息内容}`                               | AI生成的针对性回复 |

### 3. 同步服务中的测试消息

```python
# 文件: src/wecom_automation/services/sync_service.py

async def _send_test_message_and_wait(self, last_msg, customer, wait_seconds):
    # 根据最后一条消息决定发送内容
    if last_msg.is_self:
        # 客服发的最后一条 → 补刀
        test_message = "测试信息: 想的怎么样了?"
    else:
        # 客户发的最后一条 → 引用回复
        content = last_msg.content or "[media]"
        test_message = f"测试信息: [...{content[:30]}...]"

    # 发送消息
    success, actual_message = await self.wecom.send_message(test_message)
```

---

## 配置选项

### Settings (前端)

| 配置项             | 说明                  | 默认值                  |
| ------------------ | --------------------- | ----------------------- |
| `useAIReply`       | 是否启用AI回复        | `false`                 |
| `aiServerUrl`      | AI服务器URL           | `http://localhost:8000` |
| `aiReplyTimeout`   | AI超时时间(秒)        | `10`                    |
| `sendViaSidecar`   | 同步时通过Sidecar发送 | `false`                 |
| `countdownSeconds` | 发送倒计时            | `10`                    |
| `noTestMessages`   | 禁用测试消息          | `false`                 |

### Sync Options (后端)

```python
class SyncOptions:
    db_path: Optional[str] = None
    timing_multiplier: float = 1.0
    auto_placeholder: bool = True
    no_test_messages: bool = False
    send_via_sidecar: bool = False
    countdown_seconds: int = 10
    use_ai_reply: bool = False
    ai_server_url: str = "http://localhost:8000"
    ai_reply_timeout: int = 10
```

---

## 消息流程图

```
用户点击 "Send now"
        │
        ▼
┌───────────────────┐
│ 检查 queueMode?   │
└───────────────────┘
        │
   ┌────┴────┐
   ▼         ▼
 是队列    非队列
   │         │
   ▼         ▼
sendQueued  检查同步状态
Message()      │
               ▼
        ┌──────────────┐
        │ isSyncRunning?│
        └──────────────┘
               │
          ┌────┴────┐
          ▼         ▼
        同步中    非同步
          │         │
          ▼         ▼
  sendAndSave   sendSidecar
  Message()     Message()
          │         │
          └────┬────┘
               ▼
        ┌──────────────┐
        │ 后端 API     │
        │ SidecarSession│
        └──────────────┘
               │
               ▼
        ┌──────────────┐
        │ WeComService  │
        │ send_message()│
        └──────────────┘
               │
               ▼
        ┌──────────────┐
        │ ADB 操作     │
        │ 1. 点击输入框 │
        │ 2. 输入文本   │
        │ 3. 点击发送   │
        └──────────────┘
               │
               ▼
        企业微信发送消息
```

---

## AI 回复模式说明

### 模式对比

| 模式             | send_via_sidecar | use_ai_reply | AI调用位置                 |
| ---------------- | ---------------- | ------------ | -------------------------- |
| 纯Mock模式       | false            | false        | 无AI调用                   |
| 直接+AI模式      | false            | true         | `ai_direct_send_message()` |
| Sidecar+Mock模式 | true             | false        | 无AI调用                   |
| Sidecar+AI模式   | true             | true         | `sidecar_send_message()`   |

### 2025-12-23 修复记录

**问题**: AI 回复只在 Sidecar 模式下工作，直接模式无法调用 AI

**原因**: `ai_service.get_ai_reply()` 只在 `sidecar_send_message` 函数内被调用

**修复**: 在 `initial_sync.py` 中添加 `ai_direct_send_message()` 函数，当 `use_ai_reply=True` 且 `send_via_sidecar=False` 时自动 wrap `send_message` 方法

---

## 总结

消息发送涉及三层架构：

1. **前端 (Vue.js)**: 负责UI交互、消息生成（Mock/AI）、调用API
2. **后端 (FastAPI)**: 管理设备会话、路由请求、数据库操作
3. **自动化服务 (wecom_automation)**: 执行ADB操作，与Android设备交互

关键代码文件：

- `wecom-desktop/src/views/SidecarView.vue` - 前端发送逻辑
- `wecom-desktop/src/services/aiService.ts` - AI服务调用
- `wecom-desktop/backend/routers/sidecar.py` - 后端API
- `src/wecom_automation/services/wecom_service.py` - 设备操作
- `src/wecom_automation/services/sync_service.py` - 同步服务
- `initial_sync.py` - **同步入口，包含 AI 回复集成**
