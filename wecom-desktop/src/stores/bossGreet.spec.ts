// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useBossGreetStore } from './bossGreet'
import type { BossGreetSettings, BossGreetTestRunResponse } from '../services/bossApi'

const FETCH_GLOBAL = globalThis as unknown as { fetch: typeof fetch }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function settingsFixture(overrides: Partial<BossGreetSettings> = {}): BossGreetSettings {
  return {
    device_serial: 'EMU-1',
    enabled: false,
    window: {
      weekdays: [0, 1, 2, 3, 4],
      start_minute: 540,
      end_minute: 1080,
      timezone: 'Asia/Shanghai',
    },
    quota: { per_day: 80, per_hour: 15, per_job: null },
    ...overrides,
  }
}

describe('useBossGreetStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('fetchSettings', () => {
    it('stores settings on success', async () => {
      FETCH_GLOBAL.fetch = vi.fn(async () => jsonResponse(settingsFixture()))
      const store = useBossGreetStore()

      const result = await store.fetchSettings('EMU-1')

      expect(result?.window.start_minute).toBe(540)
      expect(store.settingsFor('EMU-1')).not.toBeNull()
      expect(store.error).toBeNull()
      expect(store.isLoading('EMU-1')).toBe(false)
    })

    it('records error on API failure', async () => {
      FETCH_GLOBAL.fetch = vi.fn(async () => jsonResponse({ detail: 'broken' }, 500))
      const store = useBossGreetStore()

      const result = await store.fetchSettings('EMU-X')
      expect(result).toBeNull()
      expect(store.error).toMatch(/500/)
    })
  })

  describe('saveSettings', () => {
    it('persists and updates the local cache', async () => {
      const updated = settingsFixture({ enabled: true, quota: { per_day: 50, per_hour: 8, per_job: null } })
      FETCH_GLOBAL.fetch = vi.fn(async () => jsonResponse(updated))

      const store = useBossGreetStore()
      const result = await store.saveSettings('EMU-1', {
        enabled: true,
        quota: { per_day: 50, per_hour: 8, per_job: null },
      })

      expect(result?.enabled).toBe(true)
      expect(store.settingsFor('EMU-1')?.quota.per_day).toBe(50)
    })

    it('records error on API failure', async () => {
      FETCH_GLOBAL.fetch = vi.fn(async () => jsonResponse({ detail: 'bad request' }, 400))
      const store = useBossGreetStore()
      const result = await store.saveSettings('EMU-1', { enabled: true })
      expect(result).toBeNull()
      expect(store.error).toMatch(/400/)
    })
  })

  describe('runTest', () => {
    it('records the outcome on success', async () => {
      const outcome: BossGreetTestRunResponse = {
        outcome: 'sent',
        boss_candidate_id: 'CAND-A',
        candidate_name: '李雷',
        detail: null,
      }
      FETCH_GLOBAL.fetch = vi.fn(async () => jsonResponse(outcome))
      const store = useBossGreetStore()

      const result = await store.runTest('EMU-1')

      expect(result?.outcome).toBe('sent')
      expect(store.lastTestRun['EMU-1']).toEqual(outcome)
      expect(store.isTesting('EMU-1')).toBe(false)
    })

    it('records error on API failure', async () => {
      FETCH_GLOBAL.fetch = vi.fn(async () => jsonResponse({ detail: 'no recruiter' }, 404))
      const store = useBossGreetStore()
      const result = await store.runTest('EMU-MISSING')
      expect(result).toBeNull()
      expect(store.error).toMatch(/404/)
    })
  })
})
