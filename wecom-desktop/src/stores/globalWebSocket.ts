/**
 * 全局 WebSocket 管理器
 *
 * 负责管理所有组件的 WebSocket 连接和事件分发。
 * 解决 History 界面无法实时更新的问题。
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { API_BASE } from '../services/api'

export interface GlobalWebSocketEvent {
  type:
    | 'history_refresh'
    | 'customer_updated'
    | 'message_added'
    | 'connected'
    | 'media_action_triggered'
    | 'blacklist_updated'
    | 'media_action_settings_updated'
  timestamp?: string
  data?: any
}

// Event callback type
export type EventCallback = (event: GlobalWebSocketEvent) => void

export interface WebSocketConnectionOptions {
  url?: string
  autoReconnect?: boolean
  maxReconnectAttempts?: number
  reconnectDelay?: number
}

export const useGlobalWebSocketStore = defineStore('globalWebSocket', () => {
  // 状态
  const ws = ref<WebSocket | null>(null)
  const connected = ref(false)
  const connecting = ref(false)
  const reconnectTimer = ref<number | null>(null)
  const reconnectAttempts = ref(0)

  // 配置
  const config = ref<WebSocketConnectionOptions>({
    autoReconnect: true,
    maxReconnectAttempts: 5,
    reconnectDelay: 1000,
  })

  // 事件监听器注册: Map<eventType, Set<callback>>
  const listeners = ref<Map<string, Set<EventCallback>>>(new Map())

  // 统计信息
  const stats = ref({
    totalMessagesReceived: 0,
    totalEventsDispatched: 0,
    connectionCount: 0,
    lastConnectedAt: null as Date | null,
    lastMessageAt: null as Date | null,
  })

  // 计算属性 - 使用与 api.ts 相同的 URL 逻辑
  const wsUrl = computed(() => {
    // 从 API_BASE 提取 host，替换协议
    const url = new URL(API_BASE)
    const protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${url.host}/ws/global`
  })

  const connectionStatus = computed(() => {
    if (connecting.value) return 'connecting'
    if (connected.value) return 'connected'
    return 'disconnected'
  })

  /**
   * 添加事件监听器
   */
  function addListener(eventType: string, callback: EventCallback) {
    if (!listeners.value.has(eventType)) {
      listeners.value.set(eventType, new Set())
    }
    listeners.value.get(eventType)!.add(callback)

    // 调试日志
    if (import.meta.env.DEV) {
      console.log(
        `[GlobalWS] Listener added for "${eventType}" (total: ${listeners.value.get(eventType)!.size})`
      )
    }
  }

  /**
   * 移除事件监听器
   */
  function removeListener(eventType: string, callback: EventCallback) {
    const set = listeners.value.get(eventType)
    if (set) {
      set.delete(callback)
      if (set.size === 0) {
        listeners.value.delete(eventType)
      }
    }

    if (import.meta.env.DEV) {
      console.log(`[GlobalWS] Listener removed for "${eventType}"`)
    }
  }

  /**
   * 分发事件到所有监听器
   */
  function emit(event: GlobalWebSocketEvent) {
    const callbacks = listeners.value.get(event.type)

    if (callbacks && callbacks.size > 0) {
      if (import.meta.env.DEV) {
        console.log(`[GlobalWS] Emitting "${event.type}" to ${callbacks.size} listener(s)`, event)
      }

      callbacks.forEach((callback) => {
        try {
          callback(event)
          stats.value.totalEventsDispatched++
        } catch (error) {
          console.error(`[GlobalWS] Error in listener for "${event.type}":`, error)
        }
      })
    } else {
      if (import.meta.env.DEV) {
        console.log(`[GlobalWS] No listeners for "${event.type}"`)
      }
    }
  }

  /**
   * 连接 WebSocket
   */
  function connect(options?: WebSocketConnectionOptions) {
    // 合并配置
    if (options) {
      config.value = { ...config.value, ...options }
    }

    // 如果已经连接，不重复连接
    if (ws.value?.readyState === WebSocket.OPEN) {
      console.log('[GlobalWS] Already connected')
      return
    }

    // 如果正在连接，不重复连接
    if (connecting.value) {
      console.log('[GlobalWS] Already connecting')
      return
    }

    connecting.value = true

    try {
      const url = config.value.url || wsUrl.value
      console.log(`[GlobalWS] Connecting to ${url}...`)

      ws.value = new WebSocket(url)

      ws.value.onopen = () => {
        console.log('[GlobalWS] ✓ Connected')
        connected.value = true
        connecting.value = false
        reconnectAttempts.value = 0

        stats.value.connectionCount++
        stats.value.lastConnectedAt = new Date()

        // 清除重连定时器
        if (reconnectTimer.value) {
          clearTimeout(reconnectTimer.value)
          reconnectTimer.value = null
        }

        // 发送连接成功事件
        emit({
          type: 'connected',
          timestamp: new Date().toISOString(),
        })
      }

      ws.value.onmessage = (event) => {
        stats.value.totalMessagesReceived++
        stats.value.lastMessageAt = new Date()

        try {
          const data = JSON.parse(event.data) as GlobalWebSocketEvent

          if (import.meta.env.DEV) {
            console.log(`[GlobalWS] ← Received:`, data.type, data)
          }

          emit(data)
        } catch (error) {
          console.error('[GlobalWS] Failed to parse message:', error)
          console.error('[GlobalWS] Raw message:', event.data)
        }
      }

      ws.value.onclose = (event) => {
        const wasConnected = connected.value
        connected.value = false
        connecting.value = false

        console.log(`[GlobalWS] ✗ Disconnected (code: ${event.code}, reason: ${event.reason})`)

        // 自动重连
        if (wasConnected && config.value.autoReconnect) {
          if (reconnectAttempts.value < (config.value.maxReconnectAttempts || 5)) {
            reconnectAttempts.value++
            const delay = Math.min(
              (config.value.reconnectDelay || 1000) * Math.pow(2, reconnectAttempts.value),
              30000
            )
            console.log(
              `[GlobalWS] Reconnecting in ${delay}ms... (attempt ${reconnectAttempts.value})`
            )

            reconnectTimer.value = window.setTimeout(() => {
              connect()
            }, delay)
          } else {
            console.error('[GlobalWS] Max reconnect attempts reached, giving up')
          }
        }
      }

      ws.value.onerror = (error) => {
        console.error('[GlobalWS] Error:', error)
      }
    } catch (error) {
      connecting.value = false
      console.error('[GlobalWS] Failed to create WebSocket:', error)
    }
  }

  /**
   * 断开 WebSocket 连接
   */
  function disconnect() {
    console.log('[GlobalWS] Disconnecting...')

    // 清除重连定时器
    if (reconnectTimer.value) {
      clearTimeout(reconnectTimer.value)
      reconnectTimer.value = null
    }

    reconnectAttempts.value = 0

    // 关闭连接
    if (ws.value) {
      ws.value.close()
      ws.value = null
    }

    connected.value = false
    connecting.value = false
  }

  /**
   * 发送消息到服务器
   */
  function send(type: string, data?: any) {
    if (!connected.value || !ws.value) {
      console.warn('[GlobalWS] Cannot send, not connected')
      return false
    }

    try {
      const message = {
        type,
        timestamp: new Date().toISOString(),
        data,
      }

      ws.value.send(JSON.stringify(message))

      if (import.meta.env.DEV) {
        console.log(`[GlobalWS] → Sent:`, type, data)
      }

      return true
    } catch (error) {
      console.error('[GlobalWS] Failed to send message:', error)
      return false
    }
  }

  /**
   * 获取统计信息
   */
  function getStats() {
    return {
      ...stats.value,
      connected: connected.value,
      status: connectionStatus.value,
      listenerCounts: Object.fromEntries(
        Array.from(listeners.value.entries()).map(([type, set]) => [type, set.size])
      ),
    }
  }

  /**
   * 重置统计信息
   */
  function resetStats() {
    stats.value = {
      totalMessagesReceived: 0,
      totalEventsDispatched: 0,
      connectionCount: 0,
      lastConnectedAt: null,
      lastMessageAt: null,
    }
  }

  return {
    // 状态
    connected,
    connecting,
    connectionStatus,

    // 方法
    connect,
    disconnect,
    send,
    addListener,
    removeListener,

    // 工具方法
    getStats,
    resetStats,
  }
})
