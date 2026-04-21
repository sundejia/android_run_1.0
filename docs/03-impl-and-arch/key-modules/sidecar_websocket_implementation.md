# Sidecar History 实时推送方案实现文档

> 文档创建于：2026-01-19  
> 版本：v1.0  
> 状态：设计文档

## 目录

1. [概述](#概述)
2. [当前架构分析](#当前架构分析)
3. [方案设计](#方案设计)
4. [后端实现](#后端实现)
5. [前端实现](#前端实现)
6. [消息协议定义](#消息协议定义)
7. [集成测试](#集成测试)
8. [性能考虑](#性能考虑)
9. [实现步骤](#实现步骤)

---

## 概述

### 目标

实现 Sidecar History 页面的实时消息推送，当后端有新消息写入数据库时，立即通知前端刷新显示。

### 方案选择

基于现有系统已有的 WebSocket 基础设施，采用 **WebSocket 推送机制** 实现实时更新。

| 对比项     | 轮询 (当前)        | WebSocket (目标) |
| ---------- | ------------------ | ---------------- |
| 延迟       | 30 秒              | < 100ms          |
| 资源消耗   | 高（频繁请求）     | 低（持久连接）   |
| 服务端负载 | 每次请求查询数据库 | 仅在变化时推送   |
| 实现复杂度 | 简单               | 中等             |

---

## 当前架构分析

### 已有的 WebSocket 实现

系统中已有以下 WebSocket 端点可供参考：

| 端点                                         | 文件                          | 用途 |
| -------------------------------------------- | ----------------------------- | ---- |
| `/ws/logs/{serial}`                          | `wecom-desktop/backend/routers/logs.py` | **统一**设备日志实时流：Sync 与 FollowUp / 实时回复共用此端点，用 JSON 字段 `source`（`sync` / `followup` / `system`）区分来源 |
| `/ws/sync/{serial}`                          | 同上                          | 同步进度推送 |
| `/api/recovery/ws`                           | `wecom-desktop/backend/routers/recovery.py` | Recovery 全局 WebSocket（前缀 `/api/recovery` + 路由 `/ws`） |

> **勘误（2026-04-21）**：旧文档中「独立 `/ws/logs` 跟进端点 + `followup.py`」的描述已过期；跟进与同步日志已合并到上表第一行。详见 `docs/04-bugs-and-fixes/resolved/2026-04-21-sidecar-log-stream-disconnect.md` 与 `followup_log_integration_complete.md`。

### 现有 WebSocket 模式

**后端 (FastAPI)**:

```python
from fastapi import WebSocket, WebSocketDisconnect

_connections: Dict[str, Set[WebSocket]] = {}

@router.websocket("/ws/example/{serial}")
async def websocket_endpoint(websocket: WebSocket, serial: str):
    await websocket.accept()
    _connections.setdefault(serial, set()).add(websocket)
    try:
        while True:
            await websocket.receive_text()  # 保持连接
    except WebSocketDisconnect:
        _connections[serial].discard(websocket)

# 广播消息
async def broadcast(serial: str, message: dict):
    for ws in _connections.get(serial, set()):
        await ws.send_json(message)
```

**前端 (Vue/Pinia)**:

```typescript
const ws = new WebSocket(`ws://localhost:8765/ws/example/${serial}`)
ws.onmessage = (event) => {
  const data = JSON.parse(event.data)
  // 处理消息
}
```

---

## 方案设计

### 架构图

```
┌──────────────────────────────────────────────────────────────────────┐
│                          后端 (FastAPI)                               │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐   │
│  │  Sync Service   │    │ Response Detector│    │ Followup Scanner│   │
│  │ (消息写入)       │    │ (消息写入)        │    │ (消息写入)        │   │
│  └────────┬────────┘    └────────┬─────────┘    └────────┬────────┘   │
│           │                      │                       │            │
│           ▼                      ▼                       ▼            │
│  ┌───────────────────────────────────────────────────────────────┐   │
│  │              Message Event Publisher                           │   │
│  │              (发布消息变更事件)                                  │   │
│  └───────────────────────────────────────────────────────────────┘   │
│                                  │                                    │
│                                  ▼                                    │
│  ┌───────────────────────────────────────────────────────────────┐   │
│  │          WebSocket Connection Manager                          │   │
│  │          /../03-impl-and-arch/{serial}/messages                         │   │
│  │          (管理 WebSocket 连接，广播消息)                         │   │
│  └───────────────────────────────────────────────────────────────┘   │
│                                  │                                    │
└──────────────────────────────────┼───────────────────────────────────┘
                                   │
                                   │ WebSocket
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                          前端 (Vue/Pinia)                             │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐   │
│  │              Sidecar Message Store                             │   │
│  │              (接收推送，更新 historyMessages)                   │   │
│  └───────────────────────────────────────────────────────────────┘   │
│                                  │                                    │
│                                  ▼                                    │
│  ┌───────────────────────────────────────────────────────────────┐   │
│  │              SidecarView.vue                                   │   │
│  │              (History 区域实时显示)                             │   │
│  └───────────────────────────────────────────────────────────────┘   │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### 事件类型

| 事件类型               | 说明         | 触发场景                   |
| ---------------------- | ------------ | -------------------------- |
| `message_added`        | 新消息写入   | 同步/回复/补刀后写入数据库 |
| `message_batch`        | 批量消息更新 | 多条消息同时写入           |
| `conversation_changed` | 对话变更     | 切换到不同客户             |
| `history_refresh`      | 请求完整刷新 | 需要重新加载全部历史       |

---

## 后端实现

### 4.1 创建 WebSocket 管理器

**文件**: `backend/services/websocket_manager.py`

```python
"""
WebSocket 连接管理器

管理 Sidecar 消息推送的 WebSocket 连接。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, Set, Optional, Any
from fastapi import WebSocket


logger = logging.getLogger(__name__)


class SidecarMessageManager:
    """Sidecar 消息 WebSocket 管理器"""

    def __init__(self):
        # 按 serial + conversation 分组的连接
        # Key: f"{serial}:{contact_name}:{channel}"
        self._connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    def _get_key(self, serial: str, contact_name: Optional[str] = None, channel: Optional[str] = None) -> str:
        """生成连接 Key"""
        return f"{serial}:{contact_name or ''}:{channel or ''}"

    async def connect(
        self,
        websocket: WebSocket,
        serial: str,
        contact_name: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> None:
        """注册 WebSocket 连接"""
        await websocket.accept()
        key = self._get_key(serial, contact_name, channel)

        async with self._lock:
            if key not in self._connections:
                self._connections[key] = set()
            self._connections[key].add(websocket)

        logger.info(f"[WS] Sidecar message connection added: {key}")

    async def disconnect(
        self,
        websocket: WebSocket,
        serial: str,
        contact_name: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> None:
        """断开 WebSocket 连接"""
        key = self._get_key(serial, contact_name, channel)

        async with self._lock:
            if key in self._connections:
                self._connections[key].discard(websocket)
                if not self._connections[key]:
                    del self._connections[key]

        logger.debug(f"[WS] Sidecar message connection removed: {key}")

    async def broadcast_to_conversation(
        self,
        serial: str,
        contact_name: Optional[str],
        channel: Optional[str],
        message: Dict[str, Any],
    ) -> int:
        """广播消息到特定对话的所有连接"""
        key = self._get_key(serial, contact_name, channel)
        sent_count = 0

        async with self._lock:
            connections = self._connections.get(key, set()).copy()

        for ws in connections:
            try:
                await ws.send_json(message)
                sent_count += 1
            except Exception as e:
                logger.warning(f"[WS] Failed to send message: {e}")
                # 移除失败的连接
                await self.disconnect(ws, serial, contact_name, channel)

        return sent_count

    async def broadcast_to_device(
        self,
        serial: str,
        message: Dict[str, Any],
    ) -> int:
        """广播消息到设备的所有连接（无论对话）"""
        sent_count = 0
        prefix = f"{serial}:"

        async with self._lock:
            matching_keys = [k for k in self._connections.keys() if k.startswith(prefix)]
            all_connections = []
            for key in matching_keys:
                all_connections.extend(self._connections[key])

        for ws in set(all_connections):
            try:
                await ws.send_json(message)
                sent_count += 1
            except Exception:
                pass

        return sent_count


# 单例实例
_manager: Optional[SidecarMessageManager] = None


def get_sidecar_message_manager() -> SidecarMessageManager:
    """获取 WebSocket 管理器单例"""
    global _manager
    if _manager is None:
        _manager = SidecarMessageManager()
    return _manager
```

### 4.2 添加 WebSocket 端点

**文件**: `backend/routers/sidecar.py` (添加到现有文件)

```python
from fastapi import WebSocket, WebSocketDisconnect
from services.websocket_manager import get_sidecar_message_manager


@router.websocket("/{serial}/ws/messages")
async def websocket_messages(
    websocket: WebSocket,
    serial: str,
    contact_name: str = None,
    channel: str = None,
):
    """
    WebSocket 端点：实时消息推送

    客户端连接后，当该对话有新消息时会收到推送。

    Query Params:
        contact_name: 客户名称（可选）
        channel: 渠道（可选）

    推送消息格式:
        {
            "type": "message_added" | "message_batch" | "history_refresh",
            "data": { ... }
        }
    """
    manager = get_sidecar_message_manager()

    await manager.connect(websocket, serial, contact_name, channel)

    try:
        # 发送连接成功消息
        await websocket.send_json({
            "type": "connected",
            "message": f"Connected to message stream for {serial}",
            "contact_name": contact_name,
            "channel": channel,
        })

        # 保持连接，等待客户端消息（心跳等）
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0
                )

                if data == "ping":
                    await websocket.send_text("pong")

            except asyncio.TimeoutError:
                # 发送心跳
                await websocket.send_json({"type": "heartbeat"})

    except WebSocketDisconnect:
        logger.info(f"[WS] Client disconnected from {serial} messages")
    except Exception as e:
        logger.error(f"[WS] Error in message websocket: {e}")
    finally:
        await manager.disconnect(websocket, serial, contact_name, channel)
```

### 4.3 消息事件发布器

**文件**: `backend/services/message_publisher.py`

```python
"""
消息事件发布器

在消息写入数据库后，发布事件通知前端。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime


logger = logging.getLogger(__name__)


class MessagePublisher:
    """消息事件发布器"""

    @staticmethod
    async def publish_message_added(
        serial: str,
        customer_id: int,
        customer_name: str,
        channel: Optional[str],
        message: Dict[str, Any],
    ) -> None:
        """
        发布单条消息添加事件

        Args:
            serial: 设备序列号
            customer_id: 客户 ID
            customer_name: 客户名称
            channel: 渠道
            message: 消息内容
        """
        from services.websocket_manager import get_sidecar_message_manager

        manager = get_sidecar_message_manager()

        event = {
            "type": "message_added",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "customer_id": customer_id,
                "customer_name": customer_name,
                "channel": channel,
                "message": message,
            }
        }

        sent = await manager.broadcast_to_conversation(
            serial, customer_name, channel, event
        )

        if sent > 0:
            logger.debug(f"[Publisher] Sent message_added to {sent} clients")

    @staticmethod
    async def publish_message_batch(
        serial: str,
        customer_name: str,
        channel: Optional[str],
        messages: List[Dict[str, Any]],
    ) -> None:
        """
        发布批量消息事件

        Args:
            serial: 设备序列号
            customer_name: 客户名称
            channel: 渠道
            messages: 消息列表
        """
        from services.websocket_manager import get_sidecar_message_manager

        manager = get_sidecar_message_manager()

        event = {
            "type": "message_batch",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "customer_name": customer_name,
                "channel": channel,
                "messages": messages,
                "count": len(messages),
            }
        }

        await manager.broadcast_to_conversation(
            serial, customer_name, channel, event
        )

    @staticmethod
    async def publish_history_refresh(
        serial: str,
        customer_name: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> None:
        """
        请求前端刷新完整历史

        Args:
            serial: 设备序列号
            customer_name: 客户名称（可选，为空则广播给设备所有连接）
            channel: 渠道（可选）
        """
        from services.websocket_manager import get_sidecar_message_manager

        manager = get_sidecar_message_manager()

        event = {
            "type": "history_refresh",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "customer_name": customer_name,
                "channel": channel,
            }
        }

        if customer_name:
            await manager.broadcast_to_conversation(
                serial, customer_name, channel, event
            )
        else:
            await manager.broadcast_to_device(serial, event)


# 便捷函数
async def notify_message_added(
    serial: str,
    customer_id: int,
    customer_name: str,
    channel: Optional[str],
    message: Dict[str, Any],
) -> None:
    """通知新消息添加"""
    await MessagePublisher.publish_message_added(
        serial, customer_id, customer_name, channel, message
    )


async def notify_history_refresh(
    serial: str,
    customer_name: Optional[str] = None,
    channel: Optional[str] = None,
) -> None:
    """通知刷新历史"""
    await MessagePublisher.publish_history_refresh(
        serial, customer_name, channel
    )
```

### 4.4 集成到消息写入点

需要在以下位置添加事件发布调用：

**1. `response_detector.py` - `_store_messages_to_db()`**

```python
async def _store_messages_to_db(self, ...):
    # ... 现有代码 ...

    # 存储成功后，发布事件
    if stored_count > 0:
        from services.message_publisher import notify_history_refresh
        await notify_history_refresh(serial, user_name, user_channel)

    return stored_count
```

**2. `response_detector.py` - `_store_sent_message()`**

```python
async def _store_sent_message(self, ...):
    # ... 现有代码 ...

    # 存储成功后，发布事件
    from services.message_publisher import notify_message_added
    await notify_message_added(
        serial,
        customer_id,
        user_name,
        user_channel,
        {
            "content": content,
            "is_from_kefu": True,
            "timestamp": now.isoformat(),
        }
    )
```

**3. `scanner.py` - `_save_kefu_message_via_handler()`**

类似地添加事件发布调用。

**4. `sidecar.py` - `send_and_save_message()`**

在消息保存成功后添加发布调用。

---

## 前端实现

### 5.1 创建 Sidecar 消息 Store

**文件**: `src/stores/sidecarMessages.ts`

```typescript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ConversationHistoryMessage } from '../services/api'

interface MessageEvent {
  type: 'connected' | 'message_added' | 'message_batch' | 'history_refresh' | 'heartbeat'
  timestamp?: string
  data?: any
}

interface ConnectionState {
  websocket: WebSocket | null
  status: 'disconnected' | 'connecting' | 'connected' | 'error'
  lastError: string | null
  contactName: string | null
  channel: string | null
}

export const useSidecarMessagesStore = defineStore('sidecarMessages', () => {
  // 每个 serial 的连接状态
  const connections = ref<Map<string, ConnectionState>>(new Map())

  // 消息更新回调 (由 SidecarView 注册)
  const messageCallbacks = ref<Map<string, (event: MessageEvent) => void>>(new Map())

  /**
   * 连接到消息推送 WebSocket
   */
  function connect(
    serial: string,
    contactName: string | null,
    channel: string | null,
    onMessage: (event: MessageEvent) => void
  ): void {
    // 断开旧连接
    disconnect(serial)

    // 构建 WebSocket URL
    const params = new URLSearchParams()
    if (contactName) params.set('contact_name', contactName)
    if (channel) params.set('channel', channel)

    const wsUrl = `ws://localhost:87../03-impl-and-arch/${serial}/ws/messages?${params.toString()}`

    const state: ConnectionState = {
      websocket: null,
      status: 'connecting',
      lastError: null,
      contactName,
      channel,
    }
    connections.value.set(serial, state)
    messageCallbacks.value.set(serial, onMessage)

    try {
      const ws = new WebSocket(wsUrl)
      state.websocket = ws

      ws.onopen = () => {
        state.status = 'connected'
        state.lastError = null
        console.log(`[SidecarWS] Connected: ${serial}`)
      }

      ws.onmessage = (event) => {
        try {
          const message: MessageEvent = JSON.parse(event.data)

          // 调用回调处理消息
          const callback = messageCallbacks.value.get(serial)
          if (callback) {
            callback(message)
          }
        } catch (e) {
          console.error('[SidecarWS] Failed to parse message:', e)
        }
      }

      ws.onerror = (error) => {
        state.status = 'error'
        state.lastError = 'Connection error'
        console.error(`[SidecarWS] Error: ${serial}`, error)
      }

      ws.onclose = (event) => {
        state.status = 'disconnected'
        console.log(`[SidecarWS] Disconnected: ${serial}, code: ${event.code}`)

        // 自动重连 (5 秒后)
        if (!event.wasClean) {
          setTimeout(() => {
            const currentState = connections.value.get(serial)
            if (currentState && currentState.status === 'disconnected') {
              const callback = messageCallbacks.value.get(serial)
              if (callback) {
                connect(serial, contactName, channel, callback)
              }
            }
          }, 5000)
        }
      }

      // 定期发送 ping 保持连接
      const pingInterval = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send('ping')
        } else {
          clearInterval(pingInterval)
        }
      }, 25000)
    } catch (e) {
      state.status = 'error'
      state.lastError = e instanceof Error ? e.message : 'Connection failed'
      console.error(`[SidecarWS] Failed to connect: ${serial}`, e)
    }

    // 触发响应式更新
    connections.value = new Map(connections.value)
  }

  /**
   * 断开连接
   */
  function disconnect(serial: string): void {
    const state = connections.value.get(serial)
    if (state?.websocket) {
      state.websocket.close()
    }
    connections.value.delete(serial)
    messageCallbacks.value.delete(serial)
    connections.value = new Map(connections.value)
  }

  /**
   * 断开所有连接
   */
  function disconnectAll(): void {
    connections.value.forEach((state, serial) => {
      if (state.websocket) {
        state.websocket.close()
      }
    })
    connections.value.clear()
    messageCallbacks.value.clear()
    connections.value = new Map(connections.value)
  }

  /**
   * 获取连接状态
   */
  function getConnectionStatus(serial: string): ConnectionState['status'] {
    return connections.value.get(serial)?.status || 'disconnected'
  }

  /**
   * 更新订阅的对话 (对话切换时)
   */
  function updateSubscription(
    serial: string,
    contactName: string | null,
    channel: string | null
  ): void {
    const callback = messageCallbacks.value.get(serial)
    if (callback) {
      connect(serial, contactName, channel, callback)
    }
  }

  return {
    connections,
    connect,
    disconnect,
    disconnectAll,
    getConnectionStatus,
    updateSubscription,
  }
})
```

### 5.2 在 SidecarView 中集成

**文件**: `src/views/SidecarView.vue` (修改部分)

```typescript
import { useSidecarMessagesStore } from '../stores/sidecarMessages'

const sidecarMessagesStore = useSidecarMessagesStore()

// 处理 WebSocket 消息
function handleMessageEvent(serial: string, event: MessageEvent) {
  const panel = ensurePanel(serial)

  switch (event.type) {
    case 'message_added':
      // 新消息到达，将其添加到历史列表
      if (event.data?.message) {
        const newMessage: ConversationHistoryMessage = {
          id: Date.now(), // 临时 ID
          content: event.data.message.content,
          message_type: event.data.message.message_type || 'text',
          is_from_kefu: event.data.message.is_from_kefu,
          timestamp_raw: event.data.message.timestamp_raw,
          timestamp_parsed: event.data.message.timestamp,
          created_at: event.data.message.timestamp || new Date().toISOString(),
        }
        panel.historyMessages.push(newMessage)
        panel.historyTotalCount++

        // 自动滚动到底部
        nextTick(() => scrollToBottom(serial))
      }
      break

    case 'message_batch':
      // 批量消息，刷新完整历史
      refreshConversationHistory(serial)
      break

    case 'history_refresh':
      // 请求刷新历史
      refreshConversationHistory(serial)
      break

    case 'connected':
      console.log(`[SidecarWS] Connected to ${serial}`)
      break

    case 'heartbeat':
      // 心跳，忽略
      break
  }
}

// 在 addPanel 中连接 WebSocket
function addPanel(serial: string, setFocus = true) {
  // ... 现有代码 ...

  // 连接消息推送 WebSocket
  const panel = ensurePanel(serial)
  const contactName = panel.state?.conversation?.contact_name || null
  const channel = panel.state?.conversation?.channel || null

  sidecarMessagesStore.connect(serial, contactName, channel, (event) =>
    handleMessageEvent(serial, event)
  )
}

// 在 removePanel 中断开 WebSocket
function removePanel(serial: string) {
  // ... 现有代码 ...

  // 断开消息推送 WebSocket
  sidecarMessagesStore.disconnect(serial)
}

// 当对话变更时更新订阅
watch(
  () => {
    // 监控对话变化
    const conversations: Record<string, { contactName: string | null; channel: string | null }> = {}
    for (const serial of panels.value) {
      const panel = sidecars[serial]
      if (panel?.state?.conversation) {
        conversations[serial] = {
          contactName: panel.state.conversation.contact_name || null,
          channel: panel.state.conversation.channel || null,
        }
      }
    }
    return conversations
  },
  (newConversations, oldConversations) => {
    for (const serial of panels.value) {
      const newConv = newConversations[serial]
      const oldConv = oldConversations?.[serial]

      // 对话变更时更新 WebSocket 订阅
      if (
        newConv &&
        (newConv.contactName !== oldConv?.contactName || newConv.channel !== oldConv?.channel)
      ) {
        sidecarMessagesStore.updateSubscription(serial, newConv.contactName, newConv.channel)
      }
    }
  },
  { deep: true }
)

// 组件卸载时断开所有连接
onUnmounted(() => {
  // ... 现有代码 ...
  sidecarMessagesStore.disconnectAll()
})
```

---

## 消息协议定义

### 6.1 服务端 → 客户端

```typescript
interface ServerMessage {
  type: 'connected' | 'message_added' | 'message_batch' | 'history_refresh' | 'heartbeat'
  timestamp?: string
  message?: string
  data?: MessageAddedData | MessageBatchData | HistoryRefreshData
}

interface MessageAddedData {
  customer_id: number
  customer_name: string
  channel: string | null
  message: {
    content: string
    is_from_kefu: boolean
    message_type: string
    timestamp: string
    image_url?: string
  }
}

interface MessageBatchData {
  customer_name: string
  channel: string | null
  messages: MessageAddedData['message'][]
  count: number
}

interface HistoryRefreshData {
  customer_name: string | null
  channel: string | null
}
```

### 6.2 客户端 → 服务端

```typescript
// 目前仅支持心跳
type ClientMessage = 'ping'
```

---

## 集成测试

### 7.1 测试用例

```python
# tests/test_sidecar_websocket.py

import pytest
import asyncio
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocket


def test_websocket_connection():
    """测试 WebSocket 连接"""
    with TestClient(app) as client:
        with client.websocket_connect../03-impl-and-arch/test-serial/ws/messages") as ws:
            data = ws.receive_json()
            assert data["type"] == "connected"


def test_message_broadcast():
    """测试消息广播"""
    # 1. 连接 WebSocket
    # 2. 触发消息写入
    # 3. 验证收到 message_added 事件
    pass


def test_heartbeat():
    """测试心跳机制"""
    with TestClient(app) as client:
        with client.websocket_connect../03-impl-and-arch/test-serial/ws/messages") as ws:
            ws.receive_json()  # connected
            ws.send_text("ping")
            response = ws.receive_text()
            assert response == "pong"
```

### 7.2 前端测试

```typescript
// tests/sidecarMessages.spec.ts

describe('SidecarMessagesStore', () => {
  it('should connect to WebSocket', async () => {
    const store = useSidecarMessagesStore()

    store.connect('test-serial', 'TestContact', null, (event) => {
      expect(event.type).toBe('connected')
    })

    await nextTick()
    expect(store.getConnectionStatus('test-serial')).toBe('connected')
  })
})
```

---

## 性能考虑

### 8.1 连接管理

- **最大连接数限制**：每个设备最多 10 个 WebSocket 连接
- **心跳间隔**：25 秒（略小于 30 秒超时）
- **自动重连**：断开后 5 秒自动重连

### 8.2 消息优化

- **去重**：使用消息 ID 避免重复显示
- **批量发送**：多条消息合并为 `message_batch` 事件
- **增量更新**：只推送新消息，而非完整历史

### 8.3 资源清理

```python
# 定期清理无效连接
async def cleanup_stale_connections():
    manager = get_sidecar_message_manager()
    for key, connections in list(manager._connections.items()):
        for ws in list(connections):
            if ws.client_state.name != "CONNECTED":
                await manager.disconnect(ws, ...)
```

---

## 实现步骤

### Phase 1: 后端基础设施 (预计 2 小时)

- [ ] 创建 `services/websocket_manager.py`
- [ ] 创建 `services/message_publisher.py`
- [ ] 在 `routers/sidecar.py` 添加 WebSocket 端点

### Phase 2: 集成到消息写入点 (预计 1 小时)

- [ ] 修改 `response_detector.py` 添加事件发布
- [ ] 修改 `scanner.py` 添加事件发布
- [ ] 修改 `sidecar.py` 的 `send_and_save_message` 添加事件发布

### Phase 3: 前端实现 (预计 2 小时)

- [ ] 创建 `stores/sidecarMessages.ts`
- [ ] 修改 `SidecarView.vue` 集成 WebSocket

### Phase 4: 测试与优化 (预计 1 小时)

- [ ] 编写后端测试
- [ ] 端到端测试
- [ ] 性能调优

---

## 相关文件

| 文件                                                     | 类型 | 说明                |
| -------------------------------------------------------- | ---- | ------------------- |
| `backend/services/websocket_manager.py`                  | 新建 | WebSocket 连接管理  |
| `backend/services/message_publisher.py`                  | 新建 | 消息事件发布        |
| `backend/routers/sidecar.py`                             | 修改 | 添加 WebSocket 端点 |
| `backend/servic../03-impl-and-arch/response_detector.py` | 修改 | 集成事件发布        |
| `backend/servic../03-impl-and-arch/scanner.py`           | 修改 | 集成事件发布        |
| `src/stores/sidecarMessages.ts`                          | 新建 | 前端 WebSocket 管理 |
| `src/views/SidecarView.vue`                              | 修改 | 集成 WebSocket      |
