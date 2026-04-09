import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface LogEntry {
  id: string
  timestamp: string
  level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR'
  message: string
  source?: 'sync' | 'followup' | 'system'
}

// BroadcastChannel for syncing logs between windows
const LOG_CHANNEL_NAME = 'wecom-logs-sync'

interface LogSyncMessage {
  type: 'add' | 'clear' | 'sync-request' | 'sync-response'
  serial: string
  entry?: LogEntry
  entries?: LogEntry[]
}

export const useLogStore = defineStore('logs', () => {
  // State - logs per device
  const deviceLogs = ref<Map<string, LogEntry[]>>(new Map())
  const websockets = ref<Map<string, WebSocket>>(new Map())
  const maxLogsPerDevice = 1000
  const knownLogIds = ref<Set<string>>(new Set())

  // BroadcastChannel for cross-window sync
  let logChannel: BroadcastChannel | null = null

  // Initialize broadcast channel
  function initBroadcastChannel() {
    if (logChannel) return
    
    try {
      logChannel = new BroadcastChannel(LOG_CHANNEL_NAME)
      logChannel.onmessage = (event: MessageEvent<LogSyncMessage>) => {
        const msg = event.data
        
        if (msg.type === 'add' && msg.entry) {
          // Add log from another window (without broadcasting again)
          addLogInternal(msg.serial, msg.entry, false)
        } else if (msg.type === 'clear') {
          // Clear logs from another window
          clearLogsInternal(msg.serial, false)
        } else if (msg.type === 'sync-request') {
          // Another window is requesting logs for a device
          const logs = deviceLogs.value.get(msg.serial) || []
          if (logs.length > 0) {
            logChannel?.postMessage({
              type: 'sync-response',
              serial: msg.serial,
              entries: logs,
            } as LogSyncMessage)
          }
        } else if (msg.type === 'sync-response' && msg.entries) {
          // Received logs from another window
          for (const entry of msg.entries) {
            addLogInternal(msg.serial, entry, false)
          }
        }
      }
    } catch (e) {
      console.warn('[LogStore] BroadcastChannel not supported:', e)
    }
  }

  // Request logs from other windows
  function requestLogsFromOtherWindows(serial: string) {
    initBroadcastChannel()
    logChannel?.postMessage({
      type: 'sync-request',
      serial,
    } as LogSyncMessage)
  }

  // Get logs for a specific device
  function getDeviceLogs(serial: string): LogEntry[] {
    return deviceLogs.value.get(serial) || []
  }

  // Internal add log (with option to broadcast)
  function addLogInternal(serial: string, entry: LogEntry, broadcast: boolean) {
    // Skip if we already have this log
    if (knownLogIds.value.has(entry.id)) {
      return
    }
    knownLogIds.value.add(entry.id)

    if (!deviceLogs.value.has(serial)) {
      deviceLogs.value.set(serial, [])
    }
    
    const logs = deviceLogs.value.get(serial)!
    logs.push(entry)
    
    // Trim if exceeds max
    if (logs.length > maxLogsPerDevice) {
      const removed = logs.splice(0, logs.length - maxLogsPerDevice)
      // Clean up known IDs for removed logs
      for (const log of removed) {
        knownLogIds.value.delete(log.id)
      }
    }
    
    // Trigger reactivity
    deviceLogs.value = new Map(deviceLogs.value)

    // Broadcast to other windows
    if (broadcast) {
      initBroadcastChannel()
      logChannel?.postMessage({
        type: 'add',
        serial,
        entry,
      } as LogSyncMessage)
    }
  }

  // Add a log entry for a device (public API)
  function addLog(serial: string, entry: LogEntry) {
    addLogInternal(serial, entry, true)
  }

  // Internal clear logs (with option to broadcast)
  function clearLogsInternal(serial: string, broadcast: boolean) {
    const logs = deviceLogs.value.get(serial) || []
    // Clean up known IDs
    for (const log of logs) {
      knownLogIds.value.delete(log.id)
    }
    
    deviceLogs.value.set(serial, [])
    deviceLogs.value = new Map(deviceLogs.value)

    if (broadcast) {
      initBroadcastChannel()
      logChannel?.postMessage({
        type: 'clear',
        serial,
      } as LogSyncMessage)
    }
  }

  // Clear logs for a device (public API)
  function clearLogs(serial: string) {
    clearLogsInternal(serial, true)
  }

  // Connect to WebSocket for log streaming
  function connectLogStream(serial: string) {
    // Initialize broadcast channel and request logs from other windows
    initBroadcastChannel()
    requestLogsFromOtherWindows(serial)

    // Don't reconnect if already connected
    if (websockets.value.has(serial)) {
      const ws = websockets.value.get(serial)!
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        return
      }
    }

    // Unified WebSocket URL for all devices (sync and followup)
    const wsUrl = `ws://localhost:8765/ws/logs/${serial}`

    const ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      console.log(`[LogStream] Connected for ${serial}`)
      addLog(serial, {
        id: crypto.randomUUID(),
        timestamp: new Date().toISOString(),
        level: 'INFO',
        message: 'Log stream connected',
        source: 'system',
      })
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        addLog(serial, {
          id: crypto.randomUUID(),
          timestamp: data.timestamp || new Date().toISOString(),
          level: data.level || 'INFO',
          message: data.message,
          source: data.source || 'sync',
        })
      } catch {
        // Plain text message
        addLog(serial, {
          id: crypto.randomUUID(),
          timestamp: new Date().toISOString(),
          level: 'INFO',
          message: event.data,
          source: 'sync',
        })
      }
    }

    ws.onerror = (error) => {
      console.error(`[LogStream] Error for ${serial}:`, error)
      addLog(serial, {
        id: crypto.randomUUID(),
        timestamp: new Date().toISOString(),
        level: 'ERROR',
        message: 'Log stream connection error',
        source: 'system',
      })
    }

    ws.onclose = () => {
      console.log(`[LogStream] Disconnected for ${serial}`)
      websockets.value.delete(serial)
      addLog(serial, {
        id: crypto.randomUUID(),
        timestamp: new Date().toISOString(),
        level: 'WARNING',
        message: 'Log stream disconnected',
        source: 'system',
      })
    }

    websockets.value.set(serial, ws)
  }

  // Disconnect log stream
  function disconnectLogStream(serial: string) {
    const ws = websockets.value.get(serial)
    if (ws) {
      ws.close()
      websockets.value.delete(serial)
    }
  }

  // Disconnect all streams
  function disconnectAll() {
    websockets.value.forEach((ws) => ws.close())
    websockets.value.clear()
  }

  // Get all device serials with logs
  const devicesWithLogs = computed(() => Array.from(deviceLogs.value.keys()))

  return {
    deviceLogs,
    getDeviceLogs,
    addLog,
    clearLogs,
    connectLogStream,
    disconnectLogStream,
    disconnectAll,
    devicesWithLogs,
    requestLogsFromOtherWindows,
  }
})

