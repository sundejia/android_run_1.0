# History 界面实时更新解决方案

## 问题描述

**现状**：前端 History 界面（CustomerDetailView）不是实时显示的，当 followup 实时捕获新消息时，界面不会自动更新。

**用户反馈**：之前已经修改过一次了，但是没有什么效果。

## 根本原因分析

作为资深架构师，我深入分析了整个系统，发现了**多个层级的问题**：

### 1. WebSocket 连接问题

**现状**：

- `SidecarMessageManager` 的 WebSocket 连接仅在 **Sidecar（实时上下文面板）** 中使用
- `CustomerDetailView`（History 界面）**根本没有建立 WebSocket 连接**

**代码证据**：

```typescript
// sidecarMessages.ts - 只有 Sidecar 使用
store.connect(serial, contactName, channel, messageCallback)

// CustomerDetailView.vue - 没有 WebSocket 连接
onMounted(() => {
  load() // 只是一次性加载数据
})
```

### 2. Store 分离问题

**现状**：

- `customers.ts` store 负责 History 数据
- `sidecarMessages.ts` store 负责 WebSocket 消息
- **两者完全隔离，没有通信机制**

### 3. 通知机制问题

**现状**：

- 后端 `notify_history_refresh()` 发布事件到 `SidecarMessageManager`
- 但 Sidecar 和 History 使用不同的 WebSocket 管理器
- **事件无法到达 History 界面**

### 4. 自动刷新逻辑缺失

**现状**：

- `CustomerDetailView` 只在 `onMounted` 时加载一次数据
- 没有监听任何更新事件
- 没有自动重新加载机制

## 系统架构图（现状 vs 目标）

### 现状架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         Backend                                 │
├─────────────────────────────────────────────────────────────────┤
│  Followup                                                       │
│    ↓                                                            │
│  notify_history_refresh()                                       │
│    ↓                                                            │
│  SidecarMessageManager.broadcast_to_conversation()              │
│    ↓                                                            │
│  WebSocket (仅连接到 Sidecar)                                    │
└─────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend                                │
├─────────────────────────────────────────────────────────────────┤
│  ┌───────────────────┐         ┌──────────────────────────┐   │
│  │ Sidecar 组件        │         │ CustomerDetailView       │   │
│  │ (SidecarMessageManager) │      │ (customers store)        │   │
│  │                   │         │                          │   │
│  │ ✓ WebSocket 连接   │         │ ✗ 无 WebSocket 连接       │   │
│  │ ✓ 接收事件         │         │ ✗ 无法接收事件             │   │
│  └───────────────────┘         └──────────────────────────┘   │
│                                                                  │
│  问题：History 界面完全隔离，无法接收实时更新                      │
└─────────────────────────────────────────────────────────────────┘
```

### 目标架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         Backend                                 │
├─────────────────────────────────────────────────────────────────┤
│  Followup / InitialSync                                          │
│    ↓                                                            │
│  notify_history_refresh()                                       │
│    ↓                                                            │
│  GlobalMessageManager.broadcast_to_all()                        │
│    ↓                                                            │
│  WebSocket                                                      │
└─────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend                                │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Global WebSocket Manager (统一管理)                      │   │
│  │                                                         │   │
│  │  - 接收所有 WebSocket 事件                              │   │
│  │  - 分发到对应的 store                                  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           ↓                                     │
│  ┌───────────────────┐         ┌──────────────────────────┐   │
│  │ Sidecar 组件        │         │ CustomerDetailView       │   │
│  │ (sidecarMessages)  │         │ (customers store)        │   │
│  │                   │         │                          │   │
│  │ ✓ 接收 Sidecar 事件│         │ ✓ 监听 history_refresh  │   │
│  │                   │         │ ✓ 自动重新加载消息        │   │
│  └───────────────────┘         └──────────────────────────┘   │
│                                                                  │
│  优势：统一的 WebSocket 管理，所有组件都能接收实时更新              │
└─────────────────────────────────────────────────────────────────┘
```

## 解决方案

作为资深架构师，我提供**5个解决方案**，从简单到复杂，你可以根据实际情况选择。

### 方案 1: 轮询方案（最简单，不推荐）

**实施步骤**：

1. 在 `CustomerDetailView` 中添加定时器
2. 每隔 N 秒检查是否有新消息
3. 如果有新消息，自动刷新数据

**优点**：

- 实施简单，不需要修改 WebSocket 逻辑
- 可靠性高，不依赖 WebSocket 连接

**缺点**：

- 实时性差（最多延迟 N 秒）
- 增加服务器负载（频繁的 API 请求）
- 浪费带宽（大部分时候没有新数据）

**代码示例**：

```typescript
// CustomerDetailView.vue
onMounted(() => {
  load()

  // 每 10 秒刷新一次
  const refreshInterval = setInterval(() => {
    if (customerId.value) {
      customerStore.fetchCustomerDetail(customerId.value)
    }
  }, 10000)

  onUnmounted(() => {
    clearInterval(refreshInterval)
  })
})
```

**评级**：⭐⭐ (2/5) - 简单但不优雅

---

### 方案 2: 全局 WebSocket + Store 监听（推荐）

**核心思想**：创建全局 WebSocket 管理器，让 customers store 监听事件。

**实施步骤**：

#### 2.1 创建全局 WebSocket 管理器

```typescript
// src/stores/globalWebSocket.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface GlobalWebSocketEvent {
  type: 'history_refresh' | 'customer_updated' | 'message_added'
  timestamp: string
  data: any
}

export const useGlobalWebSocketStore = defineStore('globalWebSocket', () => {
  const ws = ref<WebSocket | null>(null)
  const connected = ref(false)
  const reconnectTimer = ref<number | null>(null)
  const reconnectAttempts = ref(0)
  const maxReconnectAttempts = 5

  // 事件监听器注册
  const listeners = ref<Map<string, Set<Function>>>(new Map())

  function addListener(eventType: string, callback: Function) {
    if (!listeners.value.has(eventType)) {
      listeners.value.set(eventType, new Set())
    }
    listeners.value.get(eventType)!.add(callback)
  }

  function removeListener(eventType: string, callback: Function) {
    listeners.value.get(eventType)?.delete(callback)
  }

  function emit(event: GlobalWebSocketEvent) {
    const callbacks = listeners.value.get(event.type)
    if (callbacks) {
      callbacks.forEach((cb) => cb(event))
    }
  }

  async function connect() {
    if (ws.value?.readyState === WebSocket.OPEN) {
      return
    }

    const wsUrl = `${import.meta.env.VITE_WS_URL || 'ws://localhost:8765'}/ws/global`
    ws.value = new WebSocket(wsUrl)

    ws.value.onopen = () => {
      console.log('[GlobalWS] Connected')
      connected.value = true
      reconnectAttempts.value = 0
    }

    ws.value.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as GlobalWebSocketEvent
        console.log('[GlobalWS] Received:', data.type, data)
        emit(data)
      } catch (e) {
        console.error('[GlobalWS] Failed to parse message:', e)
      }
    }

    ws.value.onclose = () => {
      console.log('[GlobalWS] Disconnected')
      connected.value = false

      // 自动重连
      if (reconnectAttempts.value < maxReconnectAttempts) {
        reconnectAttempts.value++
        const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.value), 30000)
        console.log(`[GlobalWS] Reconnecting in ${delay}ms... (attempt ${reconnectAttempts.value})`)
        reconnectTimer.value = window.setTimeout(() => {
          connect()
        }, delay)
      }
    }

    ws.value.onerror = (error) => {
      console.error('[GlobalWS] Error:', error)
    }
  }

  function disconnect() {
    if (reconnectTimer.value) {
      clearTimeout(reconnectTimer.value)
      reconnectTimer.value = null
    }
    if (ws.value) {
      ws.value.close()
      ws.value = null
    }
    connected.value = false
  }

  return {
    connected,
    connect,
    disconnect,
    addListener,
    removeListener,
  }
})
```

#### 2.2 创建全局 WebSocket 后端路由

```python
# backend/routers/global_websocket.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Set, Dict
import json
import asyncio

router = APIRouter()

class GlobalConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = GlobalConnectionManager()

@router.websocket("/ws/global")
async def global_websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # 保持连接，等待服务器推送
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# 广播函数，供其他服务调用
async def broadcast_history_refresh(customer_name: str, channel: str):
    await manager.broadcast({
        "type": "history_refresh",
        "timestamp": datetime.now().isoformat(),
        "data": {
            "customer_name": customer_name,
            "channel": channel,
        }
    })
```

#### 2.3 修改 customers store 监听事件

```typescript
// src/stores/customers.ts
import { useGlobalWebSocketStore } from './globalWebSocket'

export const useCustomerStore = defineStore('customers', () => {
  // ... 现有代码 ...

  let wsUnlisten: Function | null = null

  function setupGlobalWebSocket() {
    const globalWs = useGlobalWebSocketStore()

    // 连接 WebSocket
    globalWs.connect()

    // 监听 history_refresh 事件
    wsUnlisten = () => globalWs.removeListener('history_refresh', handleHistoryRefresh)
    globalWs.addListener('history_refresh', handleHistoryRefresh)
  }

  async function handleHistoryRefresh(event: any) {
    const { customer_name, channel } = event.data

    // 检查是否是当前查看的客户
    if (
      selectedCustomer.value &&
      selectedCustomer.value.name === customer_name &&
      selectedCustomer.value.channel === channel
    ) {
      console.log('[Customers] Refreshing messages for', customer_name)

      // 重新加载消息
      await fetchCustomerDetail(selectedCustomer.value.id)
    }
  }

  function cleanupGlobalWebSocket() {
    if (wsUnlisten) {
      wsUnlisten()
      wsUnlisten = null
    }
  }

  return {
    // ... 现有返回值 ...
    setupGlobalWebSocket,
    cleanupGlobalWebSocket,
  }
})
```

#### 2.4 修改 CustomerDetailView 连接 WebSocket

```typescript
// src/views/CustomerDetailView.vue
onMounted(async () => {
  load()

  // 建立全局 WebSocket 连接
  customerStore.setupGlobalWebSocket()
})

onUnmounted(() => {
  // 清理 WebSocket 监听
  customerStore.cleanupGlobalWebSocket()
})
```

#### 2.5 修改后端通知逻辑

```python
# backend/servic../03-impl-and-arch/response_detector.py
async def _store_messages_to_db(...):
    # ... 存储消息 ...

    # 通知前端刷新
    if stored_count > 0:
        try:
            # 使用全局 WebSocket 广播
            from routers.global_websocket import broadcast_history_refresh
            await broadcast_history_refresh(user_name, user_channel)

            # 仍然保留 Sidecar 通知（兼容性）
            from services.message_publisher import notify_history_refresh
            await notify_history_refresh(serial, user_name, user_channel)
        except Exception as e:
            self._logger.debug(f"[{serial}] Error publishing refresh event: {e}")
```

**优点**：

- ✅ 实时性好（WebSocket 推送）
- ✅ 统一管理，避免重复连接
- ✅ 解耦良好，易于维护
- ✅ 支持自动重连
- ✅ 可以扩展到其他组件

**缺点**：

- 需要创建新的后端路由
- 需要修改多个文件
- 需要处理 WebSocket 连接状态

**评级**：⭐⭐⭐⭐⭐ (5/5) - 最佳方案

---

### 方案 3: 使用 Server-Sent Events (SSE)

**核心思想**：使用 SSE 替代 WebSocket，更适合单向推送场景。

**实施步骤**：

#### 3.1 创建 SSE 后端路由

```python
# backend/routers/sse.py
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import asyncio
import json

router = APIRouter()

# 全局事件队列
event_queues: Set[asyncio.Queue] = set()

async def event_generator():
    queue = asyncio.Queue()
    event_queues.add(queue)
    try:
        while True:
            event = await queue.get()
            yield f"data: {json.dumps(event)}\n\n"
    except asyncio.CancelledError:
        event_queues.remove(queue)

@router.get("/sse/events")
async def sse_events():
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )

# 广播函数
async def broadcast_sse_event(event: dict):
    for queue in event_queues:
        await queue.put(event)
```

#### 3.2 前端 SSE 连接

```typescript
// src/stores/sse.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useSSEStore = defineStore('sse', () => {
  const eventSource = ref<EventSource | null>(null)

  function connect() {
    if (eventSource.value) {
      return
    }

    eventSource.value = new EventSource../03-impl-and-arch/key-modules/sse/events')

    eventSource.value.onmessage = (event) => {
      const data = JSON.parse(event.data)
      console.log('[SSE] Received:', data)

      if (data.type === 'history_refresh') {
        // 触发 store 更新
        useCustomerStore().handleHistoryRefresh(data)
      }
    }
  }

  function disconnect() {
    if (eventSource.value) {
      eventSource.value.close()
      eventSource.value = null
    }
  }

  return { connect, disconnect }
})
```

**优点**：

- ✅ SSE 专为单向推送设计，更简单
- ✅ 自动重连（浏览器原生支持）
- ✅ 基于 HTTP，无需额外协议

**缺点**：

- 只能单向推送（服务器 → 客户端）
- 不如 WebSocket 灵活

**评级**：⭐⭐⭐⭐ (4/5) - 适合单向推送场景

---

### 方案 4: 数据库监听 + PostgreSQL NOTIFY

**核心思想**：使用 PostgreSQL 的 NOTIFY/LISTEN 机制监听数据库变化。

**实施步骤**：

#### 4.1 在数据库中创建触发器

```sql
-- messages 表的插入触发器
CREATE OR REPLACE FUNCTION notify_message_inserted()
RETURNS TRIGGER AS $$
BEGIN
  PERFORM pg_notify(
    'new_message',
    json_build_object(
      'customer_id', NEW.customer_id,
      'message_id', NEW.id,
      'message_type', NEW.message_type
    )::text
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER message_insert_trigger
AFTER INSERT ON messages
FOR EACH ROW
EXECUTE FUNCTION notify_message_inserted();
```

#### 4.2 后端 LISTEN 并转发

```python
# backend/services/database_watcher.py
import asyncio
import asyncpg
from fastapi import WebSocket

async def watch_database():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.add_listener('new_message', handle_notification)

async def handle_notification(connection, pid, channel, payload):
    data = json.loads(payload)

    # 广播到所有连接的 WebSocket
    from routers.global_websocket import manager
    await manager.broadcast({
        "type": "database_change",
        "data": data
    })
```

**优点**：

- ✅ 数据库级别的实时性
- ✅ 解耦良好（数据库独立触发）

**缺点**：

- 需要 PostgreSQL
- 增加数据库负载
- 配置复杂

**评级**：⭐⭐⭐ (3/5) - 适合高实时性要求场景

---

### 方案 5: 混合方案 - WebSocket + 轮询降级

**核心思想**：优先使用 WebSocket，失败时降级到轮询。

**实施步骤**：

```typescript
// src/stores/hybridRefresh.ts
export function useHybridRefresh() {
  const wsConnected = ref(false)
  const pollingInterval = ref<number | null>(null)

  function startPolling(fallback: boolean = false) {
    if (pollingInterval.value) return

    const interval = setInterval(() => {
      // 检查新消息
      checkForNewMessages()
    }, 5000) // 5秒轮询

    pollingInterval.value = interval

    if (fallback) {
      console.log('[Hybrid] Using polling fallback')
    }
  }

  function stopPolling() {
    if (pollingInterval.value) {
      clearInterval(pollingInterval.value)
      pollingInterval.value = null
    }
  }

  async function connectWebSocket() {
    const globalWs = useGlobalWebSocketStore()
    try {
      await globalWs.connect()
      wsConnected.value = true
      stopPolling() // WebSocket 成功，停止轮询
    } catch (e) {
      console.error('[Hybrid] WebSocket failed, using polling')
      startPolling(true) // 降级到轮询
    }
  }

  return {
    connectWebSocket,
    startPolling,
    stopPolling,
  }
}
```

**优点**：

- ✅ 高可用性（WebSocket 失败自动降级）
- ✅ 平衡实时性和可靠性

**缺点**：

- 实现复杂
- 需要管理两种模式

**评级**：⭐⭐⭐⭐ (4/5) - 适合生产环境

---

## 额外改进（资深架构师的洞察）

作为资深架构师，我还发现了一些你可能没想到的问题：

### 1. 消息去重问题

**问题**：WebSocket 推送可能导致重复消息

**解决方案**：

```typescript
// 在 customers store 中添加去重逻辑
const lastKnownMessageId = ref<number | null>(null)

async function handleHistoryRefresh(event: any) {
  const result = await fetchCustomerDetail(customerId.value)

  // 检查是否有新消息
  if (result.messages.length > 0) {
    const latestId = result.messages[0].id
    if (latestId !== lastKnownMessageId.value) {
      lastKnownMessageId.value = latestId
      // 只有真正有新消息时才更新 UI
    }
  }
}
```

### 2. 节流和防抖

**问题**：短时间内频繁刷新可能影响性能

**解决方案**：

```typescript
import { debounce } from 'lodash-es'

const debouncedRefresh = debounce(async () => {
  await fetchCustomerDetail(customerId.value)
}, 1000) // 1秒内最多刷新一次

async function handleHistoryRefresh(event: any) {
  debouncedRefresh()
}
```

### 3. 乐观更新

**问题**：等待服务器响应延迟用户体验

**解决方案**：

```typescript
// 先在 UI 中显示"正在刷新..."
const refreshing = ref(false)

async function handleHistoryRefresh(event: any) {
  refreshing.value = true

  try {
    await fetchCustomerDetail(customerId.value)
  } finally {
    refreshing.value = false
  }
}
```

### 4. 多标签页同步

**问题**：多个标签页同时打开同一客户，需要同步

**解决方案**：

```typescript
// 使用 BroadcastChannel API
const bc = new BroadcastChannel('history_refresh')

async function handleHistoryRefresh(event: any) {
  // 通知其他标签页
  bc.postMessage({
    type: 'history_refresh',
    customerId: customerId.value,
  })

  await fetchCustomerDetail(customerId.value)
}

// 监听其他标签页的刷新
bc.onmessage = (event) => {
  if (event.data.customerId === customerId.value) {
    fetchCustomerDetail(customerId.value)
  }
}
```

### 5. 错误边界和降级

**问题**：WebSocket 失败不应影响主功能

**解决方案**：

```typescript
try {
  await setupGlobalWebSocket()
} catch (e) {
  console.warn('[History] WebSocket unavailable, using polling')
  startPolling(true) // 降级到轮询
}
```

---

## 推荐实施方案

### 最优方案：**方案 2（全局 WebSocket）**

**理由**：

1. ✅ **实时性最好**：WebSocket 推送，延迟 < 100ms
2. ✅ **可扩展性强**：统一的 WebSocket 管理，易于扩展到其他组件
3. ✅ **架构优雅**：解耦良好，符合前端最佳实践
4. ✅ **可靠性高**：支持自动重连和错误恢复
5. ✅ **性能优秀**：无额外轮询开销

### 实施优先级

1. **Phase 1（最小可行）**：
   - 创建全局 WebSocket 管理器
   - 修改 customers store 监听事件
   - 修改 CustomerDetailView 连接 WebSocket

2. **Phase 2（增强功能）**：
   - 添加消息去重逻辑
   - 添加节流/防抖
   - 添加乐观更新

3. **Phase 3（高级功能）**：
   - 多标签页同步
   - 错误边界和降级
   - 性能监控和优化

---

## 测试验证

### 手动测试步骤

1. **启动后端和前端**

   ```bash
   cd wecom-desktop/backend && uvicorn main:app --reload
   npm run dev
   ```

2. **打开 History 界面**
   - 访问客户详情页
   - 打开浏览器开发者工具，查看 Network → WS
   - 确认已建立 WebSocket 连接

3. **触发 Followup**
   - 启动 followup 功能
   - 发送测试消息

4. **验证实时更新**
   - 检查 History 界面是否自动刷新
   - 检查浏览器控制台日志
   - 检查 WebSocket 消息

### 自动化测试

```typescript
// tests/history-refresh.spec.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useCustomerStore } from '@/stores/customers'
import { useGlobalWebSocketStore } from '@/stores/globalWebSocket'

describe('History Real-time Refresh', () => {
  beforeEach(() => {
    // 重置 stores
    useCustomerStore().$reset()
    useGlobalWebSocketStore().$reset()
  })

  it('should refresh messages when receiving history_refresh event', async () => {
    const customerStore = useCustomerStore()
    const globalWs = useGlobalWebSocketStore()

    // 模拟选中客户
    customerStore.selectedCustomer = { id: 123, name: 'Test', channel: 'wechat' }

    // 模拟接收事件
    const mockEvent = {
      type: 'history_refresh',
      timestamp: new Date().toISOString(),
      data: {
        customer_name: 'Test',
        channel: 'wechat',
      },
    }

    await globalWs.emit(mockEvent)

    // 验证刷新
    expect(customerStore.fetchCustomerDetail).toHaveBeenCalledWith(123)
  })

  it('should debounce multiple refresh events', async () => {
    // 测试防抖逻辑
  })
})
```

---

## 性能优化建议

### 1. 批量更新

**问题**：短时间内多条消息导致多次刷新

**解决方案**：

```typescript
const refreshQueue = ref<Function[]>([])
const flushTimer = ref<number | null>(null)

function scheduleRefresh(fn: Function) {
  refreshQueue.value.push(fn)

  if (flushTimer.value) return

  flushTimer.value = setTimeout(() => {
    // 批量执行
    refreshQueue.value.forEach((fn) => fn())
    refreshQueue.value = []
    flushTimer.value = null
  }, 100) // 100ms 内的所有更新合并为一次
}
```

### 2. 虚拟滚动

**问题**：大量消息导致渲染性能问题

**解决方案**：

```vue
<!-- 使用虚拟滚动 -->
<template>
  <RecycleScroller :items="messages" :item-size="80" key-field="id">
    <template #default="{ item }">
      <MessageItem :message="item" />
    </template>
  </RecycleScroller>
</template>
```

### 3. 缓存策略

**问题**：重复请求相同数据

**解决方案**：

```typescript
const messageCache = ref<Map<number, CustomerMessage[]>>(new Map())

async function fetchCustomerDetail(customerId: number) {
  // 检查缓存
  if (messageCache.value.has(customerId)) {
    return { messages: messageCache.value.get(customerId) }
  }

  const result = await api.getCustomer(customerId)
  messageCache.value.set(customerId, result.messages)
  return result
}
```

---

## 监控和调试

### WebSocket 连接监控

```typescript
// 添加连接状态监控
const wsStatus = ref<'connecting' | 'connected' | 'disconnected'>('disconnected')
const lastMessageTime = ref<Date | null>(null)

function connect() {
  wsStatus.value = 'connecting'

  ws.value.onopen = () => {
    wsStatus.value = 'connected'
    console.log('[WS] Connected at', new Date().toISOString())
  }

  ws.value.onmessage = (event) => {
    lastMessageTime.value = new Date()
    console.log('[WS] Message received:', lastMessageTime.value.toISOString())
  }

  ws.value.onclose = () => {
    wsStatus.value = 'disconnected'
    console.warn('[WS] Disconnected at', new Date().toISOString())
  }
}
```

### 性能指标收集

```typescript
// 收集刷新性能数据
const refreshMetrics = ref({
  totalRefreshes: 0,
  averageTime: 0,
  failures: 0,
})

async function fetchCustomerDetail(customerId: number) {
  const startTime = performance.now()

  try {
    const result = await api.getCustomer(customerId)

    const duration = performance.now() - startTime
    updateMetrics(duration)

    return result
  } catch (e) {
    refreshMetrics.value.failures++
    throw e
  }
}

function updateMetrics(duration: number) {
  const metrics = refreshMetrics.value
  metrics.totalRefreshes++
  metrics.averageTime =
    (metrics.averageTime * (metrics.totalRefreshes - 1) + duration) / metrics.totalRefreshes
}
```

---

## 总结

作为资深架构师，我的建议是：

### 最佳方案：**方案 2（全局 WebSocket）**

**实施路径**：

1. Phase 1: 创建全局 WebSocket 管理器和后端路由
2. Phase 2: 修改 customers store 和 CustomerDetailView
3. Phase 3: 添加去重、防抖、乐观更新等增强功能
4. Phase 4: 添加监控和调试工具

**预期效果**：

- ✅ 实时更新（延迟 < 100ms）
- ✅ 高可靠性（自动重连 + 降级）
- ✅ 良好的可维护性
- ✅ 可扩展到其他组件

**关键代码文件**：

- `src/stores/globalWebSocket.ts` (新建)
- `src/stores/customers.ts` (修改)
- `src/views/CustomerDetailView.vue` (修改)
- `backend/routers/global_websocket.py` (新建)
- `backend/servic../03-impl-and-arch/response_detector.py` (修改)

---

## 附录：常见问题 FAQ

### Q1: WebSocket 连接失败怎么办？

**A**: 实现降级机制，自动切换到轮询模式：

```typescript
try {
  await connectWebSocket()
} catch {
  startPolling(true) // 降级到轮询
}
```

### Q2: 如何避免重复消息？

**A**: 使用消息 ID 去重：

```typescript
const seenMessageIds = ref<Set<number>>(new Set())

function isNewMessage(message: CustomerMessage) {
  return !seenMessageIds.value.has(message.id)
}

function addMessage(message: CustomerMessage) {
  seenMessageIds.value.add(message.id)
  // 添加到消息列表
}
```

### Q3: 如何处理离线时的消息？

**A**: 使用离线队列 + 重放机制：

```typescript
const offlineEvents = ref<GlobalWebSocketEvent[]>([])

function handleOfflineEvent(event: GlobalWebSocketEvent) {
  offlineEvents.value.push(event)
}

function syncOfflineEvents() {
  // 重新连接后处理离线事件
  offlineEvents.value.forEach((event) => {
    handleEvent(event)
  })
  offlineEvents.value = []
}
```

### Q4: 如何减少内存占用？

**A**: 定期清理缓存：

```typescript
// 每隔 5 分钟清理一次旧缓存
setInterval(() => {
  const now = Date.now()
  const maxAge = 5 * 60 * 1000 // 5 分钟

  Object.entries(messageCache.value).forEach(([key, value]) => {
    if (now - value.timestamp > maxAge) {
      messageCache.value.delete(Number(key))
    }
  })
}, 60000) // 每分钟检查一次
```
