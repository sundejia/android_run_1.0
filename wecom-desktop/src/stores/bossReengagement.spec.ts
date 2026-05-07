// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useBossReengagementStore } from './bossReengagement'
import type {
  BossEligibleCandidate,
  BossReengagementRunResponse,
  BossReengagementSettings,
} from '../services/bossApi'

const FETCH_GLOBAL = globalThis as unknown as { fetch: typeof fetch }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function settings(overrides: Partial<BossReengagementSettings> = {}): BossReengagementSettings {
  return {
    device_serial: 'EMU-1',
    silent_for_days: 3,
    cooldown_days: 7,
    daily_cap: 50,
    template_id: null,
    enabled: false,
    ...overrides,
  }
}

function eligible(overrides: Partial<BossEligibleCandidate> = {}): BossEligibleCandidate {
  return {
    candidate_id: 1,
    boss_candidate_id: 'CAND-A',
    conversation_id: 11,
    last_outbound_at_iso: '2026-05-03T12:00:00+00:00',
    silent_for_seconds: 4 * 86400,
    ...overrides,
  }
}

describe('useBossReengagementStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('fetchSettings stores settings on success', async () => {
    FETCH_GLOBAL.fetch = vi.fn(async () => jsonResponse(settings()))
    const store = useBossReengagementStore()
    const result = await store.fetchSettings('EMU-1')
    expect(result?.silent_for_days).toBe(3)
    expect(store.settingsFor('EMU-1')?.daily_cap).toBe(50)
  })

  it('saveSettings updates the local cache', async () => {
    FETCH_GLOBAL.fetch = vi.fn(async () =>
      jsonResponse(settings({ silent_for_days: 5, daily_cap: 30 })),
    )
    const store = useBossReengagementStore()
    const result = await store.saveSettings('EMU-1', { silent_for_days: 5, daily_cap: 30 })
    expect(result?.silent_for_days).toBe(5)
    expect(store.settingsFor('EMU-1')?.daily_cap).toBe(30)
  })

  it('scan stores eligible candidates', async () => {
    FETCH_GLOBAL.fetch = vi.fn(async () =>
      jsonResponse({ recruiter_id: 10, eligible: [eligible(), eligible({ candidate_id: 2 })] }),
    )
    const store = useBossReengagementStore()
    const list = await store.scan('EMU-1')
    expect(list).toHaveLength(2)
    expect(store.eligibleFor('EMU-1')).toHaveLength(2)
    expect(store.totalEligible).toBe(2)
  })

  it('runOne records the last response', async () => {
    const response: BossReengagementRunResponse = {
      outcome: 'sent',
      boss_candidate_id: 'CAND-A',
      candidate_id: 1,
      attempt_id: 99,
      detail: null,
    }
    FETCH_GLOBAL.fetch = vi.fn(async () => jsonResponse(response))
    const store = useBossReengagementStore()
    const result = await store.runOne('EMU-1')
    expect(result?.outcome).toBe('sent')
    expect(store.lastRunBySerial['EMU-1']?.attempt_id).toBe(99)
  })

  it('records error on API failure', async () => {
    FETCH_GLOBAL.fetch = vi.fn(async () => jsonResponse({ detail: 'broken' }, 500))
    const store = useBossReengagementStore()
    const result = await store.fetchSettings('EMU-1')
    expect(result).toBeNull()
    expect(store.error).toMatch(/500/)
  })
})
