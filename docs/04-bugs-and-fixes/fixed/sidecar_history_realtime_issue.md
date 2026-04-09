# Sidecar History 页面实时性问题分析

> 文档创建于：2026-01-19  
> 问题类型：实时显示延迟

## 问题描述

Sidecar 的对话历史 (History) 页面无法实时显示新消息。当后端同步过程中产生新消息时，前端的历史列表不会立即更新。

---

## 根本原因

### 原因 1：历史数据来自数据库，存在时间差

前端 History 页面的数据来源于 **数据库**，而非实时的 UI 树。

```
数据流程：
后端同步 → 提取消息 → 写入数据库 → API 请求 → 前端显示
                ↑                    ↑
                |                    |
            有延迟               需要主动刷新
```

**代码位置**: `SidecarView.vue` 第 309-356 行

```typescript
async function fetchConversationHistory(serial: string) {
  // ...
  const result = await api.getConversationHistory(serial, {
    contactName: contactName || undefined,
    channel: channel || undefined,
    limit: 100,
  })

  if (result.success) {
    panel.historyMessages = result.messages // 来自数据库
  }
}
```

### 原因 2：防重复获取机制导致不刷新

`fetchConversationHistory()` 有一个 **防重复获取** 的检查，如果当前对话未变化，会跳过刷新：

```typescript
// 第 321-329 行
// Skip if we already fetched for this conversation
if (
  panel.historyLastFetched &&
  panel.historyLastFetched.contactName === contactName &&
  panel.historyLastFetched.channel === channel &&
  panel.historyMessages.length > 0 // ← 如果已有消息，不会刷新
) {
  return // ← 直接返回，不刷新
}
```

**问题**：这意味着在同一个对话中，如果后端写入了新消息，前端不会自动检测到。

### 原因 3：轮询刷新条件过于严格

History 刷新只在以下条件下触发：

| 触发条件                | 代码位置        | 问题                                   |
| ----------------------- | --------------- | -------------------------------------- |
| **每 3 次轮询刷新一次** | 第 723-731 行   | 轮询间隔默认 10 秒，即 30 秒才刷新一次 |
| **仅在同步运行时刷新**  | 第 728-730 行   | 如果同步未运行，永远不会自动刷新       |
| **对话切换时刷新**      | 第 1286-1294 行 | 在同一对话中无效                       |
| **发送消息后刷新**      | 第 427-430 行   | 仅在用户手动发送后触发                 |

**关键代码**：

```typescript
// 第 723-731 行
// Refresh history every 3 polls during sync to keep it updated
pollCount++
if (pollCount >= 3) {
  pollCount = 0
  // Only refresh if sync is running ← 关键限制
  const syncStatus = deviceStore.getSyncStatus(serial)
  if (syncStatus && ['running', 'starting'].includes(syncStatus.status)) {
    refreshConversationHistory(serial)
  }
}
```

### 原因 4：没有 WebSocket/SSE 推送机制

当前系统采用的是 **轮询机制**，而非实时推送：

| 特性             | 当前实现         | 理想实现           |
| ---------------- | ---------------- | ------------------ |
| **消息获取方式** | 定时轮询 API     | WebSocket 实时推送 |
| **刷新触发**     | 需要主动请求     | 服务端事件驱动     |
| **延迟**         | 可能高达 30 秒   | 毫秒级             |
| **资源消耗**     | 频繁请求造成开销 | 只在有变化时传输   |

---

## 刷新触发时机汇总

| 触发场景       | 函数                  | 是否立即刷新       | 备注                      |
| -------------- | --------------------- | ------------------ | ------------------------- |
| 首次加载       | `fetchState()`        | ✅ 是              | 第 243-245 行             |
| 对话切换       | `watch()`             | ✅ 是              | 第 1264-1298 行           |
| 新队列消息到达 | `fetchQueueState()`   | ✅ 是              | 第 290-291 行             |
| 发送消息后     | `sendQueuedMessage()` | ✅ 是 (500ms 延迟) | 第 427-430 行             |
| 轮询周期       | `startPolling()`      | ⚠️ 条件性          | 仅同步运行时，每 3 次轮询 |
| 后端写入新消息 | -                     | ❌ 否              | 没有主动推送机制          |

---

## 详细代码分析

### 1. 首次加载时的刷新

```typescript
// 第 242-245 行
// Auto-load conversation history on first successful state fetch
if (panel.historyMessages.length === 0 && result.conversation?.contact_name) {
  fetchConversationHistory(serial)
}
```

**问题**：只在 `historyMessages.length === 0` 时触发，已有消息后不会自动刷新。

### 2. 轮询刷新的条件

```typescript
// 第 713-732 行
// Counter for periodic history refresh (every 3 polls)
let pollCount = 0

panel.pollTimer = window.setInterval(() => {
  // ...

  // Refresh history every 3 polls during sync to keep it updated
  pollCount++
  if (pollCount >= 3) {
    pollCount = 0
    // Only refresh if sync is running
    const syncStatus = deviceStore.getSyncStatus(serial)
    if (syncStatus && ['running', 'starting'].includes(syncStatus.status)) {
      refreshConversationHistory(serial)
    }
  }
}, interval)
```

**计算实际刷新间隔**：

- 默认轮询间隔：10 秒 (`sidecarPollInterval: 10`)
- 每 3 次轮询刷新一次：10 × 3 = **30 秒**
- **结论**：在同步运行时，历史最多 30 秒刷新一次

### 3. 同步未运行时的问题

如果同步未运行 (`syncStatus` 为空或状态不是 `running`/`starting`)：

- **轮询中的 `refreshConversationHistory()` 永远不会被调用**
- 用户必须手动刷新或切换对话才能看到新消息

---

## 影响场景

| 场景                     | 是否实时          | 原因                            |
| ------------------------ | ----------------- | ------------------------------- |
| 用户手动发送消息后       | ⚠️ 500ms 延迟     | 代码中有 `setTimeout(..., 500)` |
| 后端同步过程中新增消息   | ❌ 最多 30 秒延迟 | 依赖轮询周期                    |
| 后端同步完成后           | ❌ 不刷新         | 轮询刷新条件排除了非运行状态    |
| 手动点击 Generate 按钮后 | ❌ 不刷新         | 没有触发 history 刷新           |
| Follow-up 系统发送消息   | ❌ 不刷新         | 没有推送机制                    |

---

## 解决方案建议

### 方案 1：降低轮询刷新条件 (快速修复)

**修改**：移除"仅同步运行时刷新"的限制

```typescript
// 修改 startPolling() 函数
pollCount++
if (pollCount >= 3) {
  pollCount = 0
  refreshConversationHistory(serial) // 移除 syncStatus 检查
}
```

**风险**：增加 API 请求频率

### 方案 2：增加刷新频率 (快速修复)

**修改**：将每 3 次轮询改为每次轮询

```typescript
// 每次轮询都刷新历史
panel.pollTimer = window.setInterval(() => {
  if (panel.sending) return

  fetchState(serial, false)
  fetchQueueState(serial)
  refreshConversationHistory(serial) // 每次都刷新
}, interval)
```

**风险**：API 负载增加

### 方案 3：WebSocket 推送 (理想方案)

**架构变更**：

1. 后端在写入新消息后，通过 WebSocket 推送更新事件
2. 前端接收到事件后立即刷新 history

```
后端消息写入 → WebSocket 推送 → 前端接收 → 立即刷新
```

**优点**：

- 真正的实时性
- 减少无效请求
- 更好的用户体验

**缺点**：需要较大的架构改动

### 方案 4：手动刷新按钮 (临时方案)

在 History 区域添加一个刷新按钮，让用户可以手动触发刷新。

---

## 相关代码文件

| 文件                         | 功能                                   |
| ---------------------------- | -------------------------------------- |
| `src/views/SidecarView.vue`  | Sidecar 主组件，包含 history 逻辑      |
| `src/services/api.ts`        | API 调用层，`getConversationHistory()` |
| `backend/routers/sidecar.py` | 后端 API，`get_conversation_history()` |

---

## 总结

Sidecar History 无法实时显示的根本原因是：

1. **数据来源于数据库**，而非实时 UI 树
2. **防重复获取机制**阻止了同一对话的重复刷新
3. **轮询刷新条件过于严格**（仅同步运行时，每 30 秒一次）
4. **缺乏实时推送机制**（WebSocket/SSE）

建议优先采用**方案 1 或 2**进行快速修复，长期考虑实现 **WebSocket 推送机制**。
