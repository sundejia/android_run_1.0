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

// Reconnect / heartbeat tunables. The values must stay loosely coordinated
// with the server-side inactivity ceiling in routers/logs.py.
const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 30_000
const RECONNECT_MAX_ATTEMPTS = 20
const HEARTBEAT_INTERVAL_MS = 25_000
const HEARTBEAT_TIMEOUT_MS = 35_000

export const useLogStore = defineStore('logs', () => {
  // State - logs per device
  const deviceLogs = ref<Map<string, LogEntry[]>>(new Map())
  const websockets = ref<Map<string, WebSocket>>(new Map())
  const maxLogsPerDevice = 1000
  const knownLogIds = ref<Set<string>>(new Set())

  // Reconnect bookkeeping (intentionally non-reactive plain Maps/Sets)
  const reconnectAttempts = new Map<string, number>()
  const reconnectTimers = new Map<string, number>()
  const intentionallyClosed = new Set<string>()
  const heartbeatTimers = new Map<string, { ping: number; watchdog: number }>()
  const lastPongAt = new Map<string, number>()

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

  // --- Heartbeat helpers ---

  function stopHeartbeat(serial: string) {
    const t = heartbeatTimers.get(serial)
    if (t) {
      window.clearInterval(t.ping)
      window.clearInterval(t.watchdog)
      heartbeatTimers.delete(serial)
    }
    lastPongAt.delete(serial)
  }

  function startHeartbeat(serial: string, ws: WebSocket) {
    stopHeartbeat(serial)
    lastPongAt.set(serial, Date.now())

    const ping = window.setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        try {
          ws.send('ping')
        } catch {
          // Send failure will be picked up by the watchdog timer below.
        }
      }
    }, HEARTBEAT_INTERVAL_MS)

    const watchdog = window.setInterval(() => {
      const last = lastPongAt.get(serial) ?? 0
      if (Date.now() - last > HEARTBEAT_TIMEOUT_MS) {
        console.warn(
          `[LogStream] Heartbeat timeout for ${serial}, forcing close`,
        )
        try {
          ws.close(4000, 'heartbeat-timeout')
        } catch {
          /* noop */
        }
      }
    }, HEARTBEAT_INTERVAL_MS)

    heartbeatTimers.set(serial, { ping, watchdog })
  }

  // --- Reconnect helpers ---

  function clearReconnectTimer(serial: string) {
    const t = reconnectTimers.get(serial)
    if (t) {
      window.clearTimeout(t)
      reconnectTimers.delete(serial)
    }
  }

  function scheduleReconnect(serial: string) {
    if (intentionallyClosed.has(serial)) return

    const attempts = reconnectAttempts.get(serial) ?? 0
    if (attempts >= RECONNECT_MAX_ATTEMPTS) {
      addLog(serial, {
        id: crypto.randomUUID(),
        timestamp: new Date().toISOString(),
        level: 'ERROR',
        message: `Log stream gave up after ${attempts} reconnect attempts`,
        source: 'system',
      })
      return
    }

    const delay = Math.min(RECONNECT_BASE_MS * 2 ** attempts, RECONNECT_MAX_MS)
    reconnectAttempts.set(serial, attempts + 1)
    clearReconnectTimer(serial)

    const timer = window.setTimeout(() => {
      reconnectTimers.delete(serial)
      connectLogStream(serial)
    }, delay)
    reconnectTimers.set(serial, timer)
  }

  // Connect to WebSocket for log streaming
  function connectLogStream(serial: string) {
    // Initialize broadcast channel and request logs from other windows
    initBroadcastChannel()
    requestLogsFromOtherWindows(serial)

    // Re-entry from a scheduled reconnect (or a fresh user action) means the
    // user wants to be connected; clear any stale "intentional close" flag.
    intentionallyClosed.delete(serial)

    // Don't reconnect if already connected
    const existing = websockets.value.get(serial)
    if (
      existing &&
      (existing.readyState === WebSocket.OPEN ||
        existing.readyState === WebSocket.CONNECTING)
    ) {
      return
    }

    // Unified WebSocket URL for all devices (sync and followup)
    const wsUrl = `ws://localhost:8765/ws/logs/${serial}`

    const ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      console.log(`[LogStream] Connected for ${serial}`)
      reconnectAttempts.delete(serial)
      clearReconnectTimer(serial)
      startHeartbeat(serial, ws)
      addLog(serial, {
        id: crypto.randomUUID(),
        timestamp: new Date().toISOString(),
        level: 'INFO',
        message: 'Log stream connected',
        source: 'system',
      })
    }

    ws.onmessage = (event) => {
      const raw = event.data
      // Heartbeat frames must never enter the visible log panel.
      if (raw === 'pong' || raw === 'ping') {
        lastPongAt.set(serial, Date.now())
        return
      }
      try {
        const data = JSON.parse(raw)
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
          message: typeof raw === 'string' ? raw : String(raw),
          source: 'sync',
        })
      }
    }

    ws.onerror = (error) => {
      console.error(`[LogStream] Error for ${serial}:`, error)
      // Do not surface a synthetic "connection error" entry: ws.onclose will
      // always follow and is the single place that decides whether we tell
      // the user we are reconnecting.
    }

    ws.onclose = (ev) => {
      console.log(`[LogStream] Disconnected for ${serial} (code=${ev.code})`)
      websockets.value.delete(serial)
      stopHeartbeat(serial)

      if (intentionallyClosed.has(serial)) {
        intentionallyClosed.delete(serial)
        addLog(serial, {
          id: crypto.randomUUID(),
          timestamp: new Date().toISOString(),
          level: 'INFO',
          message: 'Log stream closed',
          source: 'system',
        })
        return
      }

      addLog(serial, {
        id: crypto.randomUUID(),
        timestamp: new Date().toISOString(),
        level: 'WARNING',
        message: `Log stream disconnected (code=${ev.code}), retrying...`,
        source: 'system',
      })
      scheduleReconnect(serial)
    }

    websockets.value.set(serial, ws)
  }

  // Disconnect log stream
  function disconnectLogStream(serial: string) {
    intentionallyClosed.add(serial)
    clearReconnectTimer(serial)
    reconnectAttempts.delete(serial)
    stopHeartbeat(serial)
    const ws = websockets.value.get(serial)
    if (ws) {
      try {
        ws.close(1000, 'client-intentional')
      } catch {
        /* noop */
      }
      websockets.value.delete(serial)
    }
  }

  // Disconnect all streams
  function disconnectAll() {
    for (const serial of Array.from(websockets.value.keys())) {
      disconnectLogStream(serial)
    }
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
