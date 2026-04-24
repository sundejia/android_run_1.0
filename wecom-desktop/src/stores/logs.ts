import { defineStore } from 'pinia'
import { ref, shallowRef, computed, type ShallowRef } from 'vue'

export interface LogEntry {
  id: string
  timestamp: string
  level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR'
  message: string
  source?: 'sync' | 'followup' | 'system'
}

const LOG_CHANNEL_NAME = 'wecom-logs-sync'

interface LogSyncMessage {
  type: 'add' | 'add-batch' | 'clear' | 'sync-request' | 'sync-response'
  serial: string
  entry?: LogEntry
  entries?: LogEntry[]
}

const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 30_000
const RECONNECT_MAX_ATTEMPTS = 20
const HEARTBEAT_INTERVAL_MS = 25_000
const HEARTBEAT_TIMEOUT_MS = 35_000

// Broadcast flush cadence. Small enough to feel real-time; large enough to
// coalesce a burst of WebSocket frames into a single cross-window message.
const BROADCAST_FLUSH_MS = 80

export const useLogStore = defineStore('logs', () => {
  // Per-serial reactive refs. Each device gets its own shallowRef<LogEntry[]>,
  // so a log push on device A only re-renders panels subscribed to device A —
  // not every LogStream instance on the page. This is the key fix for the
  // "15 same-timestamp logs trickle in over 5 seconds" bug: previously, a
  // single shared `ref<Map>` reallocation on every push forced all three
  // SidecarView panels to recompute at once, collapsing throughput to ~3/s.
  const deviceLogRefs = new Map<string, ShallowRef<LogEntry[]>>()

  // Reactive counter bumped whenever a brand-new serial is seen, so the
  // `devicesWithLogs` computed can re-evaluate without depending on a
  // reactive Map.
  const deviceSerialsVersion = ref(0)

  const websockets = ref<Map<string, WebSocket>>(new Map())
  const maxLogsPerDevice = 1000

  // Non-reactive dedupe set. The ids are UUIDs created per entry and are only
  // used for cross-window dedupe, never rendered, so there's no point paying
  // Vue's reactivity tax on it.
  const knownLogIds = new Set<string>()

  // Reconnect bookkeeping (plain Maps/Sets, intentionally non-reactive).
  const reconnectAttempts = new Map<string, number>()
  const reconnectTimers = new Map<string, number>()
  const intentionallyClosed = new Set<string>()
  const heartbeatTimers = new Map<string, { ping: number; watchdog: number }>()
  const lastPongAt = new Map<string, number>()

  // Batched reactivity trigger. Every addLog mutates the underlying array
  // in place (so synchronous reads like `getDeviceLogs()` return the fresh
  // value immediately, which existing unit tests rely on) and then queues a
  // microtask that swaps the ref to a new array reference — once per dirty
  // serial per tick. This replaces the previous O(n_serials) `new Map(...)`
  // reallocation that fired on every single log line.
  const dirtySerials = new Set<string>()
  let triggerScheduled = false

  // Cross-window broadcast batching. A burst of WS frames on one serial
  // should turn into a single `add-batch` message instead of N single-entry
  // postMessage calls.
  const pendingBroadcast = new Map<string, LogEntry[]>()
  let broadcastTimer: number | null = null

  let logChannel: BroadcastChannel | null = null

  function initBroadcastChannel() {
    if (logChannel) return

    try {
      logChannel = new BroadcastChannel(LOG_CHANNEL_NAME)
      logChannel.onmessage = (event: MessageEvent<LogSyncMessage>) => {
        const msg = event.data

        if (msg.type === 'add' && msg.entry) {
          addLogInternal(msg.serial, msg.entry, false)
        } else if (msg.type === 'add-batch' && msg.entries) {
          for (const entry of msg.entries) {
            addLogInternal(msg.serial, entry, false)
          }
        } else if (msg.type === 'clear') {
          clearLogsInternal(msg.serial, false)
        } else if (msg.type === 'sync-request') {
          const r = deviceLogRefs.get(msg.serial)
          const logs = r ? r.value : []
          if (logs.length > 0) {
            logChannel?.postMessage({
              type: 'sync-response',
              serial: msg.serial,
              entries: logs.slice(),
            } as LogSyncMessage)
          }
        } else if (msg.type === 'sync-response' && msg.entries) {
          for (const entry of msg.entries) {
            addLogInternal(msg.serial, entry, false)
          }
        }
      }
    } catch (e) {
      console.warn('[LogStore] BroadcastChannel not supported:', e)
    }
  }

  function requestLogsFromOtherWindows(serial: string) {
    initBroadcastChannel()
    logChannel?.postMessage({
      type: 'sync-request',
      serial,
    } as LogSyncMessage)
  }

  function ensureRef(serial: string): ShallowRef<LogEntry[]> {
    let r = deviceLogRefs.get(serial)
    if (!r) {
      r = shallowRef<LogEntry[]>([])
      deviceLogRefs.set(serial, r)
      deviceSerialsVersion.value += 1
    }
    return r
  }

  function getDeviceLogs(serial: string): LogEntry[] {
    return ensureRef(serial).value
  }

  function scheduleTrigger(serial: string) {
    dirtySerials.add(serial)
    if (triggerScheduled) return
    triggerScheduled = true
    // queueMicrotask runs before paint but after the current task. This
    // coalesces multiple synchronous pushes (e.g., `sync-response` loops
    // replaying another window's history) into one reactivity trigger per
    // serial, without delaying visibility across event-loop tasks — which
    // keeps the "WS message → log visible" pipeline feeling real-time.
    queueMicrotask(flushTriggers)
  }

  function flushTriggers() {
    triggerScheduled = false
    if (dirtySerials.size === 0) return
    const serials = Array.from(dirtySerials)
    dirtySerials.clear()
    for (const serial of serials) {
      const r = deviceLogRefs.get(serial)
      if (!r) continue
      // Swap to a new array reference so child components that receive the
      // array as a prop see `hasChanged(newValue, oldValue) === true` and
      // re-run downstream computeds (e.g., LogStream's aiDown watcher).
      // Contents are unchanged — we just committed in-place mutations.
      r.value = r.value.slice()
    }
  }

  function scheduleBroadcast(serial: string, entry: LogEntry) {
    let queue = pendingBroadcast.get(serial)
    if (!queue) {
      queue = []
      pendingBroadcast.set(serial, queue)
    }
    queue.push(entry)

    if (broadcastTimer !== null) return
    broadcastTimer = window.setTimeout(flushBroadcast, BROADCAST_FLUSH_MS)
  }

  function flushBroadcast() {
    broadcastTimer = null
    if (pendingBroadcast.size === 0) return
    initBroadcastChannel()
    if (!logChannel) {
      pendingBroadcast.clear()
      return
    }
    for (const [serial, entries] of pendingBroadcast) {
      if (entries.length === 0) continue
      if (entries.length === 1) {
        logChannel.postMessage({
          type: 'add',
          serial,
          entry: entries[0],
        } as LogSyncMessage)
      } else {
        logChannel.postMessage({
          type: 'add-batch',
          serial,
          entries: entries.slice(),
        } as LogSyncMessage)
      }
    }
    pendingBroadcast.clear()
  }

  function addLogInternal(serial: string, entry: LogEntry, broadcast: boolean) {
    if (knownLogIds.has(entry.id)) return
    knownLogIds.add(entry.id)

    const r = ensureRef(serial)
    const logs = r.value
    logs.push(entry)

    if (logs.length > maxLogsPerDevice) {
      const removed = logs.splice(0, logs.length - maxLogsPerDevice)
      for (const log of removed) {
        knownLogIds.delete(log.id)
      }
    }

    scheduleTrigger(serial)

    if (broadcast) {
      scheduleBroadcast(serial, entry)
    }
  }

  function addLog(serial: string, entry: LogEntry) {
    addLogInternal(serial, entry, true)
  }

  function clearLogsInternal(serial: string, broadcast: boolean) {
    const r = deviceLogRefs.get(serial)
    if (r) {
      for (const log of r.value) {
        knownLogIds.delete(log.id)
      }
      // Clearing replaces the array reference directly (synchronous trigger)
      // so any pending microtask flush for this serial is harmless — the
      // flush is a no-op reallocation on an empty array.
      r.value = []
    }
    // Cancel any pending broadcast entries for this serial; a `clear`
    // message makes queued `add` entries stale.
    pendingBroadcast.delete(serial)

    if (broadcast) {
      initBroadcastChannel()
      logChannel?.postMessage({
        type: 'clear',
        serial,
      } as LogSyncMessage)
    }
  }

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

  function connectLogStream(serial: string) {
    initBroadcastChannel()
    requestLogsFromOtherWindows(serial)

    intentionallyClosed.delete(serial)

    const existing = websockets.value.get(serial)
    if (
      existing &&
      (existing.readyState === WebSocket.OPEN ||
        existing.readyState === WebSocket.CONNECTING)
    ) {
      return
    }

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

  function disconnectAll() {
    for (const serial of Array.from(websockets.value.keys())) {
      disconnectLogStream(serial)
    }
  }

  const devicesWithLogs = computed(() => {
    // Subscribe to the serials-version counter so this recomputes whenever
    // a brand-new serial is registered.
    void deviceSerialsVersion.value
    return Array.from(deviceLogRefs.keys())
  })

  return {
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
