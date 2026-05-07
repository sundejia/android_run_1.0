// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useBossMonitoringStore } from './bossMonitoring'
import type {
  BossMonitoringSummaryResponse,
  BossRecruiterSummary,
} from '../services/bossApi'

const FETCH_GLOBAL = globalThis as unknown as { fetch: typeof fetch }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function recruiterSummary(overrides: Partial<BossRecruiterSummary> = {}): BossRecruiterSummary {
  return {
    recruiter_id: 1,
    device_serial: 'EMU-1',
    name: 'Alice',
    company: 'Co',
    position: 'HR',
    jobs_by_status: { open: 2, closed: 1 },
    candidates_by_status: { greeted: 1, new: 1 },
    greet_attempts_last_24h: { sent: 0, cancelled: 0, failed: 0 },
    reengagement_attempts_last_24h: { sent: 1, cancelled: 1, failed: 0 },
    silent_candidates_eligible: 1,
    ...overrides,
  }
}

function summaryPayload(
  overrides: Partial<BossMonitoringSummaryResponse> = {},
): BossMonitoringSummaryResponse {
  return {
    generated_at_iso: '2026-05-07T18:00:00+00:00',
    window_hours: 24,
    recruiters: [recruiterSummary()],
    ...overrides,
  }
}

describe('useBossMonitoringStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('refresh stores summary on success', async () => {
    FETCH_GLOBAL.fetch = vi.fn(async () => jsonResponse(summaryPayload()))
    const store = useBossMonitoringStore()
    const result = await store.refresh()
    expect(result?.recruiters).toHaveLength(1)
    expect(store.recruiters).toHaveLength(1)
    expect(store.summary?.window_hours).toBe(24)
    expect(store.error).toBeNull()
  })

  it('totalSilentEligible aggregates across recruiters', async () => {
    FETCH_GLOBAL.fetch = vi.fn(async () =>
      jsonResponse(
        summaryPayload({
          recruiters: [
            recruiterSummary({ silent_candidates_eligible: 2 }),
            recruiterSummary({
              recruiter_id: 2,
              device_serial: 'EMU-2',
              silent_candidates_eligible: 5,
            }),
          ],
        }),
      ),
    )
    const store = useBossMonitoringStore()
    await store.refresh()
    expect(store.totalSilentEligible).toBe(7)
  })

  it('totalReengagementSent24h aggregates sent counters across recruiters', async () => {
    FETCH_GLOBAL.fetch = vi.fn(async () =>
      jsonResponse(
        summaryPayload({
          recruiters: [
            recruiterSummary({
              reengagement_attempts_last_24h: { sent: 3, cancelled: 1, failed: 1 },
            }),
            recruiterSummary({
              recruiter_id: 2,
              device_serial: 'EMU-2',
              reengagement_attempts_last_24h: { sent: 4, cancelled: 0, failed: 0 },
            }),
          ],
        }),
      ),
    )
    const store = useBossMonitoringStore()
    await store.refresh()
    expect(store.totalReengagementSent24h).toBe(7)
  })

  it('records error and keeps previous summary on failure', async () => {
    FETCH_GLOBAL.fetch = vi
      .fn()
      .mockImplementationOnce(async () => jsonResponse(summaryPayload()))
      .mockImplementationOnce(async () => jsonResponse({ detail: 'down' }, 500))
    const store = useBossMonitoringStore()
    await store.refresh()
    const second = await store.refresh()
    expect(second).toBeNull()
    expect(store.error).toMatch(/500/)
    expect(store.recruiters).toHaveLength(1)
  })

  it('loading flips during refresh', async () => {
    let resolve: ((value: Response) => void) | null = null
    const pending = new Promise<Response>((r) => {
      resolve = r
    })
    FETCH_GLOBAL.fetch = vi.fn(() => pending)
    const store = useBossMonitoringStore()
    const promise = store.refresh()
    expect(store.loading).toBe(true)
    resolve!(jsonResponse(summaryPayload()))
    await promise
    expect(store.loading).toBe(false)
  })
})
