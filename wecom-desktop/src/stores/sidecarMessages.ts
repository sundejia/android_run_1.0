import { defineStore } from 'pinia'
import { ref } from 'vue'

interface MessageEvent {
  type: 'connected' | 'message_added' | 'message_batch' | 'history_refresh' | 'heartbeat'
  timestamp?: string
  message?: string
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

    const wsUrl = `ws://localhost:8765/sidecar/${serial}/ws/messages?${params.toString()}`

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
    connections.value.forEach((state) => {
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
