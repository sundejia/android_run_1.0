// @vitest-environment jsdom
/**
 * Log store regression tests.
 *
 * These cover the four behaviors that previously caused users to see a
 * permanent "Log stream disconnected" status after long-running sessions:
 *
 *   1. ping/pong heartbeat frames must never enter the visible log panel
 *   2. passive disconnects (network blip, server restart) must auto-reconnect
 *   3. explicit disconnects (user action) must NOT auto-reconnect
 *   4. the client must actively send "ping" so the server can detect
 *      half-open connections
 */

import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useLogStore } from './logs'

class MockWebSocket {
  static instances: MockWebSocket[] = []
  static OPEN = 1
  static CONNECTING = 0
  static CLOSED = 3

  url: string
  readyState: number = MockWebSocket.CONNECTING
  sent: string[] = []
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
    // Simulate async connection establishment.
    setTimeout(() => {
      this.readyState = MockWebSocket.OPEN
      this.onopen?.(new Event('open'))
    }, 0)
  }

  send(data: string): void {
    this.sent.push(data)
  }

  close(code = 1000, _reason?: string): void {
    if (this.readyState === MockWebSocket.CLOSED) return
    this.readyState = MockWebSocket.CLOSED
    this.onclose?.(new CloseEvent('close', { code, wasClean: code === 1000 }))
  }

  simulateServerClose(code = 1006): void {
    if (this.readyState === MockWebSocket.CLOSED) return
    this.readyState = MockWebSocket.CLOSED
    this.onclose?.(new CloseEvent('close', { code, wasClean: false }))
  }

  receive(data: string): void {
    this.onmessage?.(new MessageEvent('message', { data }))
  }

  static reset(): void {
    MockWebSocket.instances = []
  }
}

;(global as any).WebSocket = MockWebSocket
;(MockWebSocket as any).OPEN = 1
;(MockWebSocket as any).CONNECTING = 0
;(MockWebSocket as any).CLOSED = 3

// Always stub BroadcastChannel: in Node + jsdom the real implementation tries
// to structured-clone Vue's reactive proxies which fails with DataCloneError.
// The store's broadcast behavior is exercised by separate cross-window tests.
;(globalThis as any).BroadcastChannel = class {
  name: string
  onmessage: ((event: MessageEvent) => void) | null = null
  constructor(name: string) {
    this.name = name
  }
  postMessage(_msg: unknown): void {}
  close(): void {}
}

if (typeof crypto === 'undefined' || !('randomUUID' in crypto)) {
  ;(globalThis as any).crypto = {
    randomUUID: () => `uuid-${Math.random().toString(36).slice(2)}`,
  }
}

describe('useLogStore log streaming', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    MockWebSocket.reset()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  async function flushOpen() {
    // Allow the queued setTimeout(..., 0) inside MockWebSocket to fire so
    // ws.onopen runs and the heartbeat timers are armed.
    await vi.advanceTimersByTimeAsync(1)
  }

  it('does not surface ping/pong frames as visible log entries', async () => {
    const store = useLogStore()
    store.connectLogStream('SERIAL_X')
    await flushOpen()

    const ws = MockWebSocket.instances[0]
    ws.receive('pong')
    ws.receive('ping')

    const messages = store.getDeviceLogs('SERIAL_X').map((e) => e.message)
    expect(messages).not.toContain('ping')
    expect(messages).not.toContain('pong')
  })

  it('auto-reconnects after a passive disconnect', async () => {
    const store = useLogStore()
    store.connectLogStream('SERIAL_X')
    await flushOpen()
    expect(MockWebSocket.instances).toHaveLength(1)

    MockWebSocket.instances[0].simulateServerClose(1006)

    // First reconnect attempt fires after RECONNECT_BASE_MS (1000ms).
    await vi.advanceTimersByTimeAsync(1500)
    expect(MockWebSocket.instances.length).toBeGreaterThanOrEqual(2)
  })

  it('does NOT reconnect after an intentional disconnect', async () => {
    const store = useLogStore()
    store.connectLogStream('SERIAL_X')
    await flushOpen()
    expect(MockWebSocket.instances).toHaveLength(1)

    store.disconnectLogStream('SERIAL_X')

    await vi.advanceTimersByTimeAsync(10_000)
    expect(MockWebSocket.instances).toHaveLength(1)
  })

  it('actively sends "ping" frames once the heartbeat fires', async () => {
    const store = useLogStore()
    store.connectLogStream('SERIAL_X')
    await flushOpen()

    // HEARTBEAT_INTERVAL_MS is 25_000 in logs.ts. Advance just past it.
    await vi.advanceTimersByTimeAsync(26_000)

    const ws = MockWebSocket.instances[0]
    expect(ws.sent).toContain('ping')
  })

  it('renders structured JSON log entries from the server', async () => {
    const store = useLogStore()
    store.connectLogStream('SERIAL_X')
    await flushOpen()

    const ws = MockWebSocket.instances[0]
    ws.receive(
      JSON.stringify({
        timestamp: '2026-04-21T10:00:00Z',
        level: 'WARNING',
        message: 'something happened',
        source: 'sync',
      }),
    )

    const entries = store.getDeviceLogs('SERIAL_X')
    const warning = entries.find((e) => e.message === 'something happened')
    expect(warning).toBeDefined()
    expect(warning?.level).toBe('WARNING')
    expect(warning?.source).toBe('sync')
  })
})
