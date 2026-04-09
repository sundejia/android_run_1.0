# 聊天记录显示错误联系人问题分析

**状态：已修复** ✅

## 问题描述

聊天记录可以显示，但是固定显示一个人的记录，与当前正在同步的人不一致。

## 问题现象

- 当FollowUp系统或同步过程切换到新用户时，聊天记录仍然显示之前用户的消息
- 聊天记录的联系人名称没有随着当前对话切换而更新

## 根因分析

### 问题发生位置

问题出现在 `SidecarView.vue` 中的 `fetchConversationHistory` 和 `refreshConversationHistory` 函数。

### 数据流分析

```
1. fetchConversationHistory(serial)
   └─→ 从 panel.state?.conversation?.contact_name 获取联系人名称
       └─→ panel.state 来自 fetchState() 调用
           └─→ panel.state 来../03-impl-and-arch/{serial}/state API

2. refreshConversationHistory(serial)
   └─→ 只有当 panel.state?.conversation?.contact_name 为空时才调用 fetchState()
   └─→ 问题：如果 contact_name 有值（来自前一个用户），则不会刷新state
   └─→ 导致使用过期的 contact_name 来获取聊天记录
```

### 核心问题

在 `SidecarView.vue` 第515-526行：

```typescript
async function refreshConversationHistory(serial: string) {
  const panel = ensurePanel(serial)
  // Clear last fetched to force refresh
  panel.historyLastFetched = null

  // 问题：只有当 contact_name 为空时才刷新 state
  // 如果已有旧的 contact_name，不会去获取最新的UI状态
  if (!panel.state?.conversation?.contact_name) {
    await fetchState(serial, false)
  }

  await fetchConversationHistory(serial)
}
```

同时，在 `fetchQueueState` 函数（第403-461行）中：

```typescript
// 第444-445行
// 当检测到新消息时刷新聊天记录
// 但队列消息中的 customerName 和 panel.state 中的 contact_name 可能不一致！
refreshConversationHistory(serial)
```

### 两个来源的不一致

| 来源     | 变量                                    | 描述                                     |
| -------- | --------------------------------------- | ---------------------------------------- |
| 队列消息 | `readyMessage.customerName`             | 来自FollowUp/Sync系统推送的当前客户名称  |
| UI状态   | `panel.state.conversation.contact_name` | 来自设备UI解析的联系人名称（可能已过期） |

问题：`fetchConversationHistory` 使用的是 `panel.state.conversation.contact_name`，而不是当前队列消息中的 `customerName`。

### 时序问题

```
T1: FollowUp切换到用户A
T2: snapshot() 从UI解析出 contact_name = "用户A"
T3: 显示用户A的聊天记录（正确）
T4: FollowUp切换到用户B，添加队列消息 { customerName: "用户B" }
T5: fetchQueueState() 检测到新消息
T6: refreshConversationHistory() 被调用
T7: panel.state.conversation.contact_name 仍然是 "用户A"（未刷新）
T8: 获取用户A的聊天记录（错误！）
```

## 影响范围

- `wecom-desktop/src/views/SidecarView.vue`
  - `fetchConversationHistory()` 函数
  - `refreshConversationHistory()` 函数
  - `fetchQueueState()` 函数

## 修复方案

### 方案1：优先使用队列消息中的客户名称（推荐）

修改 `fetchConversationHistory` 函数，让其在队列模式下优先使用当前队列消息中的客户信息：

```typescript
async function fetchConversationHistory(serial: string) {
  const panel = ensurePanel(serial)

  // 优先使用当前队列消息中的客户信息
  let contactName = null
  let channel = null

  if (panel.queueMode && panel.currentQueuedMessage) {
    // 队列模式下，使用队列消息中的准确客户信息
    contactName = panel.currentQueuedMessage.customerName || null
    channel = panel.currentQueuedMessage.channel || null
  } else {
    // 非队列模式，使用UI解析的信息（作为后备）
    contactName = panel.state?.conversation?.contact_name || null
    channel = panel.state?.conversation?.channel || null
  }

  // ... 其余代码不变
}
```

### 方案2：强制刷新UI状态

修改 `refreshConversationHistory` 函数，无论如何都刷新UI状态：

```typescript
async function refreshConversationHistory(serial: string) {
  const panel = ensurePanel(serial)
  panel.historyLastFetched = null

  // 始终刷新UI状态，确保获取最新的 contact_name
  await fetchState(serial, false)

  await fetchConversationHistory(serial)
}
```

### 方案3：结合方案1和方案2

最安全的方案是同时应用两种修复：

1. 刷新聊天记录时始终更新UI状态
2. 获取聊天记录时优先使用队列消息中的客户信息

## 建议实施顺序

1. **方案1（高优先级）**：修改 `fetchConversationHistory` 优先使用队列消息中的客户名称
2. **方案2（辅助）**：修改 `refreshConversationHistory` 始终刷新UI状态

## 验证方法

1. 启动FollowUp监控
2. 等待系统切换到不同的用户
3. 验证聊天记录是否显示当前正在同步用户的消息
4. 检查控制台日志确保 `contact_name` 和 `customerName` 一致

## 相关文件

| 文件                                         | 用途                                          |
| -------------------------------------------- | --------------------------------------------- |
| `wecom-desktop/src/views/SidecarView.vue`    | 前端Sidecar界面，聊天记录显示                 |
| `wecom-desktop/backend/routers/sidecar.py`   | 后端Sidecar API，提供conversation-history端点 |
| `src/wecom_automation/services/ui_parser.py` | UI解析，`get_conversation_header_info` 方法   |

## 创建日期

2026-01-24

---

## 实际修复内容（2026-01-24）

### 1. 修改 `fetchConversationHistory` 函数

**文件**: `wecom-desktop/src/views/SidecarView.vue`

**修改内容**: 在队列模式下优先使用队列消息中的 `customerName` 和 `channel`

```typescript
async function fetchConversationHistory(serial: string) {
  const panel = ensurePanel(serial)

  // FIX: 优先使用队列消息中的客户信息，而不是UI解析的 contact_name
  // 这样可以确保在FollowUp/Sync切换用户时，显示正确的客户聊天记录
  let contactName: string | null = null
  let channel: string | null = null

  if (panel.queueMode && panel.currentQueuedMessage) {
    // 队列模式下，使用队列消息中的准确客户信息
    contactName = panel.currentQueuedMessage.customerName || null
    channel = panel.currentQueuedMessage.channel || null
    console.log(`[Sidecar] Using queue message customer: ${contactName}, channel: ${channel}`)
  } else {
    // 非队列模式，使用UI解析的信息（作为后备）
    contactName = panel.state?.conversation?.contact_name || null
    channel = panel.state?.conversation?.channel || null
  }

  // ... 其余代码不变
}
```

### 2. 修改 `refreshConversationHistory` 函数

**修改内容**: 始终刷新 UI 状态，确保获取最新的 `contact_name`。这对于 WebSocket 事件触发的刷新尤其重要。

```typescript
async function refreshConversationHistory(serial: string) {
  const panel = ensurePanel(serial)
  panel.historyLastFetched = null

  // FIX: 始终刷新 UI 状态，确保获取最新的 contact_name
  // 这对于 WebSocket 事件触发的刷新尤其重要
  await fetchState(serial, false)

  await fetchConversationHistory(serial)
}
```

### 修复效果

修复后的数据流：

**队列模式下**：

```
T1: FollowUp切换到用户A
T2: 聊天记录显示用户A的消息（正确）
T3: FollowUp切换到用户B，添加队列消息 { customerName: "用户B" }
T4: fetchQueueState() 检测到新消息，设置 panel.currentQueuedMessage
T5: refreshConversationHistory() 被调用
T6: fetchConversationHistory() 检测到 queueMode=true
T7: 使用 panel.currentQueuedMessage.customerName = "用户B"（正确！）
T8: 获取并显示用户B的聊天记录（正确！）
```

**非队列模式下（WebSocket 事件触发）**：

```
T1: FollowUp切换到用户A
T2: 聊天记录显示用户A的消息（正确）
T3: FollowUp切换到用户B
T4: WebSocket 事件触发 refreshConversationHistory()
T5: refreshConversationHistory() 首先调用 fetchState() 刷新 UI 状态
T6: panel.state.conversation.contact_name 更新为 "用户B"
T7: fetchConversationHistory() 使用最新的 contact_name = "用户B"
T8: 获取并显示用户B的聊天记录（正确！）
```

---

## 验证结果（2026-01-24 15:41）

### 修复验证成功 ✅

修复后，API请求正确使用了当前同步用户的 `contact_name`：

**实际API请求**：

```
GE../03-impl-and-arch/AN2FVB1706003302/conversation-history?contact_name=B2601230072&channel=%EF%BC%A0WeChat&limit=100
```

**解析**：

- **设备序列号**: `AN2FVB1706003302`
- **contact_name**: `B2601230072`（当前正在同步的用户）
- **channel**: `＠WeChat`（URL编码: `%EF%BC%A0WeChat`）
- **limit**: `100`

修复前，这个请求会错误地使用之前用户的 `contact_name`（如 AAA），导致显示错误的聊天记录。

修复后，`refreshConversationHistory()` 会先调用 `fetchState()` 刷新 UI 状态，确保使用最新的 `contact_name` 来获取正确的聊天记录。

---

## 问题二：Channel 字符编码不匹配（2026-01-24 15:45）

### 问题现象

修复了 `contact_name` 问题后，API 请求正确了，但聊天记录仍然显示 `No messages yet`：

```
GE../03-impl-and-arch/AN2FVB1706003302/conversation-history?contact_name=B2601230072&channel=%EF%BC%A0WeChat&limit=100
```

返回结果：`0 msgs` - 没有找到任何消息

### 根因分析

**Channel 格式不匹配**：

- 前端请求的 channel: `＠WeChat`（全角 `＠` = U+FF20，URL编码: `%EF%BC%A0`）
- 数据库存储的 channel: `@WeChat`（半角 `@` = U+0040）

由于全角 `＠` 和半角 `@` 是不同的 Unicode 字符，SQL 精确匹配失败。

### 修复方案

在后端 `get_conversation_history` 函数中，添加 channel 规范化逻辑：

```python
# Normalize channel: convert fullwidth characters to halfwidth
# UI may parse fullwidth ＠ (U+FF20) but database stores halfwidth @ (U+0040)
normalized_channel = channel
if channel:
    # Replace fullwidth @ with halfwidth @
    normalized_channel = channel.replace('＠', '@')
    if normalized_channel != channel:
        print(f"[conversation-history] Normalized channel: '{channel}' -> '{normalized_channel}'")
```

### 修复文件

**`wecom-desktop/backend/routers/sidecar.py`** 第 679-692 行

### Unicode 字符对照表

| 字符 | 名称                             | Unicode | URL编码     |
| ---- | -------------------------------- | ------- | ----------- |
| `@`  | 半角 @ (Commercial At)           | U+0040  | `%40`       |
| `＠` | 全角 @ (Fullwidth Commercial At) | U+FF20  | `%EF%BC%A0` |

### 修复后的匹配流程

```
1. 前端请求: channel=＠WeChat (全角)
2. 后端接收后规范化: ＠WeChat -> @WeChat (半角)
3. 数据库查询使用: channel=@WeChat
4. 匹配成功，返回正确的聊天记录
```
