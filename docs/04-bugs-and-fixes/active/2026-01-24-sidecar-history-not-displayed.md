# Sidecar 历史消息显示问题分析

> 文档版本: 1.1  
> 创建时间: 2026-01-24  
> 更新时间: 2026-01-24 14:29  
> 作者: 架构设计师

---

## 问题描述

Sidecar 的 Message 界面无法显示任何历史消息。

---

## 系统架构分析

### 数据流

系统使用 **两套 WebSocket** 进行实时消息推送：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         消息保存与通知流程                                    │
└─────────────────────────────────────────────────────────────────────────────┘

  FollowUp 实时回复处理
         │
         ▼
  _store_messages_to_db()
    (response_detector.py)
         │
         ▼
  MessageProcessor.process()  ◄────── ❌ 因 MessageContext 参数缺失而失败！
         │
         ▼ (if stored_count > 0)
   ┌─────┴─────┐
   │           │
   ▼           ▼
  Global WS   Sidecar WS
  (History)   (Sidecar)
   │           │
   ▼           ▼
  broadcast_history_refresh()    notify_history_refresh()
  (routers/global_websocket.py)   (services/message_publisher.py)
   │           │
   ▼           ▼
  /ws/global ../03-impl-and-arch/{serial}/ws/messages
   │           │
   ▼           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            前端                                              │
├───────────────────────────────┬─────────────────────────────────────────────┤
│  globalWebSocket.ts           │  sidecarMessages.ts                         │
│  - history_refresh 事件        │  - history_refresh 事件                     │
│  - 触发 History 界面刷新       │  - 触发 Sidecar 历史刷新                    │
├───────────────────────────────┴─────────────────────────────────────────────┤
│  SidecarView.vue                                                            │
│  handleGlobalWebSocketEvent() → refreshConversationHistory()                │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 关键代码位置

| 文件                   | 函数/组件                      | 行号      | 说明               |
| ---------------------- | ------------------------------ | --------- | ------------------ |
| `response_detector.py` | `_store_messages_to_db()`      | 928-1089  | 存储消息并广播通知 |
| `response_detector.py` | `broadcast_history_refresh()`  | 1069-1077 | 通知 Global WS     |
| `global_websocket.py`  | `broadcast_history_refresh()`  | 209-242   | 广播到所有连接     |
| `globalWebSocket.ts`   | emit/addListener               | 66-122    | 前端事件分发       |
| `SidecarView.vue`      | `handleGlobalWebSocketEvent()` | 136-192   | 处理 WS 事件       |
| `SidecarView.vue`      | `fetchConversationHistory()`   | 442-490   | 获取历史消息       |
| `sidecar.py`           | `get_conversation_history()`   | 628-799   | 后端 API 实现      |

---

## 🔴 根本原因分析

### 问题链路

从日志截图可以看到：

```
[GlobalWS] ✓ Connected
[GlobalWS] No listeners for "connected"
```

这表明：

1. ✅ WebSocket 连接成功
2. ⚠️ `"connected"` 事件没有监听器（这是正常的，因为 Sidecar 只监听 `history_refresh` 和 `message_added`）

**但真正的问题是**：由于 `MessageContext` 参数缺失，消息保存失败，`stored_count = 0`，所以 WebSocket 通知**从未被触发**！

```python
# response_detector.py 第 1066-1077 行
# Notify frontend to refresh history if messages were stored
if stored_count > 0:  # ← 这个条件永远为 False！
    try:
        from routers.global_websocket import broadcast_history_refresh
        # ...
```

### 关联 Bug

这个问题与 **"客户消息不保存"** Bug 是同一个根因：

```
Error: MessageContext.__init__() missing 1 required positional argument: 'channel'
```

由于 `MessageContext` 初始化失败：

1. ❌ 消息没有保存到数据库
2. ❌ `stored_count` 保持为 0
3. ❌ `broadcast_history_refresh()` 从未被调用
4. ❌ 前端 WebSocket 没有收到刷新通知
5. ❌ Sidecar 历史消息为空

### 第二个问题：名称不匹配

即使消息保存成功，仍然存在**名称匹配**问题：

```
UI 解析出的 contact_name: "尤子涵"
数据库存储的 customer_name: "B2304308832"
WebSocket 事件的 customer_name: "B2304308832"
```

**问题链路**：

1. ❌ 前端 `handleGlobalWebSocketEvent` 使用精确匹配 `currentContactName === customer_name`
2. ❌ 匹配失败，不触发 `refreshConversationHistory`
3. ❌ 即使手动刷新，后端 `get_conversation_history` 也使用精确匹配
4. ❌ 返回 "Customer not found in database"

### 已修复（2026-01-24 14:45）

**修复 1：前端 WebSocket 事件匹配**

修改 `SidecarView.vue` 中的 `handleGlobalWebSocketEvent` 函数，使用**宽松匹配**：

```typescript
// 多种匹配策略：
// 1. contact_name 精确匹配 customer_name
// 2. channel 精确匹配（如果都有 channel）
// 3. customer_name 包含在 contact_name 中
// 4. contact_name 包含在 customer_name 中
const nameMatch =
  currentContactName &&
  customer_name &&
  (currentContactName === customer_name ||
    currentContactName.includes(customer_name) ||
    customer_name.includes(currentContactName))
const channelMatch = currentChannel && channel && currentChannel === channel
const shouldRefresh = nameMatch || channelMatch
```

**修复 2：后端客户查询**

修改 `sidecar.py` 中的 `get_conversation_history` 函数，使用**级联匹配**：

1. 首先尝试精确匹配（name + channel）
2. 如果失败，尝试仅匹配 channel
3. 如果仍失败，尝试 LIKE 模糊匹配 name

---

## 可能的问题原因

### 1. 🔴 设备没有关联 kefu

**问题描述**：`get_conversation_history()` 首先查询 kefu：

```python
# sidecar.py 第 659-677 行
cursor.execute(
    """
    SELECT k.id, k.name
    FROM kefus k
    JOIN kefu_devices kd ON k.id = kd.kefu_id
    JOIN devices d ON kd.device_id = d.id
    WHERE d.serial = ?
    ORDER BY k.updated_at DESC
    LIMIT 1
    """,
    (serial,)
)
kefu_row = cursor.fetchone()

if not kefu_row:
    return ConversationHistoryResponse(
        success=False,
        error=f"No kefu found for device {serial}"
    )
```

**排查方法**：

```sql
-- 检查 kefu_devices 关联
SELECT k.id, k.name, d.serial
FROM kefus k
JOIN kefu_devices kd ON k.id = kd.kefu_id
JOIN devices d ON kd.device_id = d.id;
```

**可能原因**：

- 设备没有进行过全量同步
- kefu 信息没有正确保存到数据库
- `kefu_devices` 关联表中没有数据

---

### 2. 🔴 客户不存在于数据库

**问题描述**：即使 kefu 存在，还需要根据 `contact_name` 和 `channel` 找到客户：

```python
# sidecar.py 第 695-714 行
cursor.execute(
    f"""
    SELECT c.id, c.name, c.channel
    FROM customers c
    WHERE {" AND ".join(where_conditions)}
    ORDER BY c.updated_at DESC
    LIMIT 1
    """,
    params
)
customer_row = cursor.fetchone()

if not customer_row:
    return ConversationHistoryResponse(
        success=True,
        kefu_name=kefu_name,
        messages=[],
        total_messages=0,
        error="Customer not found in database"
    )
```

**排查方法**：

```sql
-- 查看客户是否存在
SELECT * FROM customers WHERE name = '目标客户名称';
```

**可能原因**：

- 客户还没有被同步到数据库
- `contact_name` 与数据库中的 `name` 不匹配（大小写、空格等）

---

### 3. 🔴 前端没有正确传递 contactName 和 channel

**问题描述**：在 `fetchConversationHistory()` 中：

```typescript
// SidecarView.vue 第 442-452 行
async function fetchConversationHistory(serial: string) {
  const panel = ensurePanel(serial)
  const contactName = panel.state?.conversation?.contact_name || null
  const channel = panel.state?.conversation?.channel || null

  // Skip if no conversation context
  if (!contactName && !channel) {
    panel.historyMessages = []
    panel.historyTotalCount = 0
    return
  }
  // ...
}
```

如果 `panel.state?.conversation` 为空或者 `contact_name` 为 null，则不会发起 API 请求。

**排查方法**：

1. 在浏览器控制台检查 `panel.state?.conversation` 的值
2. 检查../03-impl-and-arch/{serial}/state` API 的返回值

**可能原因**：

- 设备没有进入对话界面
- UI 状态解析错误

---

### 4. 🟡 消息确实为空（因为之前的 Bug）

**问题关联**：根据前面分析的"客户消息不保存"问题：

```
Error: MessageContext.__init__() missing 1 required positional argument: 'channel'
```

由于 `MessageContext` 缺少参数，导致**所有消息都没有被保存到数据库**！

**验证方法**：

```sql
-- 检查消息表是否有数据
SELECT COUNT(*) FROM messages;

-- 检查最近的消息
SELECT * FROM messages ORDER BY id DESC LIMIT 10;
```

---

### 5. 🟡 缓存导致不刷新

**问题描述**：在 `fetchConversationHistory()` 中有缓存逻辑：

```typescript
// SidecarView.vue 第 455-462 行
// Skip if we already fetched for this conversation
if (
  panel.historyLastFetched &&
  panel.historyLastFetched.contactName === contactName &&
  panel.historyLastFetched.channel === channel &&
  panel.historyMessages.length > 0
) {
  return
}
```

如果之前获取了空消息列表，后来消息被添加了，可能不会重新获取。

**解决方法**：手动调用 `refreshConversationHistory(serial)` 强制刷新。

---

## 排查清单

### 步骤 1：检查浏览器控制台

打开 Sidecar 页面，在浏览器控制台中检查：

- 是否有 API 错误（红色警告）
- 查看 `[Sidecar]` 开头的日志输出
- 检查网络请求../03-impl-and-arch/{serial}/conversation-history` 的响应

### 步骤 2：检查 API 响应

直接在浏览器中访问：

```
http://localhost:87../03-impl-and-arch/{serial}/conversation-history?contact_name={名称}
```

检查返回的 JSON：

- `success` 是否为 `true`
- `error` 字段是否有错误信息
- `messages` 数组是否有内容

### 步骤 3：检查数据库

```sql
-- 1. 检查 kefu_devices 关联
SELECT k.id, k.name, d.serial, d.id as device_id
FROM kefus k
JOIN kefu_devices kd ON k.id = kd.kefu_id
JOIN devices d ON kd.device_id = d.id;

-- 2. 检查客户
SELECT id, name, channel, kefu_id FROM customers LIMIT 20;

-- 3. 检查消息
SELECT id, customer_id, is_from_kefu, content, message_type
FROM messages ORDER BY id DESC LIMIT 20;

-- 4. 检查特定客户的消息
SELECT m.*
FROM messages m
JOIN customers c ON m.customer_id = c.id
WHERE c.name = '目标客户';
```

---

## 已知问题影响

### 与 "客户消息不保存" Bug 的关联

**问题**：由于 `MessageContext` 初始化缺少 `channel` 参数：

```python
# response_detector.py 第 1011-1017 行（之前的错误版本）
context = MessageContext(
    customer_id=customer_id,
    customer_name=user_name,
    device_serial=serial,
    kefu_name=None,  # ← kefu_name 不能是 None
)
# 缺少 channel=user_channel 参数！
```

**影响**：

1. 实时回复中的**所有消息都没有被保存**
2. 即使显示 "1 new customer message(s)"，消息也没有入库
3. Sidecar 从数据库读取的消息为空

**修复状态**：✅ 已修复（见 `2026-01-24-realtime-customer-message-not-saved.md`）

---

## 其他潜在问题

### 1. 设备初始化不完整

如果设备没有正确初始化，可能导致：

- `devices` 表中没有设备记录
- `kefus` 表中没有客服记录
- `kefu_devices` 关联缺失

**解决方法**：

1. 在 UI 中重新初始化设备
2. 进行一次全量同步以建立数据关联

### 2. WebSocket 消息推送失败

`SidecarView.vue` 依赖 WebSocket 推送来刷新历史消息：

```typescript
// SidecarView.vue 第 194-210 行
function setupGlobalWebSocket() {
  if (!globalWebSocket.connected && !globalWebSocket.connecting) {
    console.log('[Sidecar] Connecting to global WebSocket...')
    globalWebSocket.connect()
  }

  globalWebSocket.addListener('history_refresh', handleGlobalWebSocketEvent)
  globalWebSocket.addListener('message_added', handleGlobalWebSocketEvent)
}
```

如果 WebSocket 连接失败，实时更新不会工作。

**验证方法**：在控制台检查是否有 `[Sidecar] ✓ Global WebSocket listeners attached` 日志。

### 3. 对话状态未正确获取

`get_conversation_history()` 依赖前端传入的 `contact_name` 和 `channel`，这些值来自../03-impl-and-arch/{serial}/state` API：

```typescript
// SidecarView.vue 第 372-375 行
// Auto-load conversation history on first successful state fetch
if (panel.historyMessages.length === 0 && result.conversation?.contact_name) {
  fetchConversationHistory(serial)
}
```

如果设备没有进入对话界面，`conversation` 可能为 `null`。

---

## ✅ 解决方案

### 核心修复（已完成）

这个问题的根本原因是 `MessageContext` 参数缺失导致消息保存失败。

**修复文件**：`response_detector.py` 第 1011-1018 行

```python
# 之前（错误）：
context = MessageContext(
    customer_id=customer_id,
    customer_name=user_name,
    device_serial=serial,
    kefu_name=None,  # ← 不能是 None
)
# 缺少 channel 参数！

# 之后（修复）：
context = MessageContext(
    customer_id=customer_id,
    customer_name=user_name,
    channel=user_channel,  # ← 添加缺失的参数
    device_serial=serial,
    kefu_name="",  # ← 使用空字符串
)
```

### 修复后的效果

1. ✅ 消息正确保存到数据库
2. ✅ `stored_count > 0` 条件满足
3. ✅ `broadcast_history_refresh()` 被调用
4. ✅ 前端 WebSocket 收到刷新通知
5. ✅ Sidecar 历史消息正常显示

### 测试验证

修复后，请执行以下验证：

1. **重启 FollowUp 服务**
2. **发送测试消息**
3. **检查日志**：应看到 `→ Global WS: history_refresh for {用户名}`
4. **检查 Sidecar**：历史消息应正常显示

---

## 快速验证脚本

在项目根目录运行：

```powershell
# 检查数据库结构和数据
sqlite3 wecom_conversations.db "SELECT 'kefus:', COUNT(*) FROM kefus; SELECT 'customers:', COUNT(*) FROM customers; SELECT 'messages:', COUNT(*) FROM messages; SELECT 'kefu_devices:', COUNT(*) FROM kefu_devices; SELECT 'devices:', COUNT(*) FROM devices;"
```

期望输出：

```
kefus: N (N > 0)
customers: N (N > 0)
messages: N (N > 0)
kefu_devices: N (N > 0)
devices: N (N > 0)
```

如果任何表为 0，说明数据缺失。

---

**创建时间**: 2026-01-24  
**状态**: ✅ 已修复（通过修复关联 Bug）  
**优先级**: 中  
**关联 Bug**: 2026-01-24-realtime-customer-message-not-saved.md
