// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useBossJobsStore } from './bossJobs'
import type {
  BossJob,
  BossJobListResponse,
  BossJobSyncResponse,
} from '../services/bossApi'

const FETCH_GLOBAL = globalThis as unknown as { fetch: typeof fetch }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function mockFetchByUrl(routes: Record<string, () => Response | Promise<Response>>) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString()
    for (const [pattern, handler] of Object.entries(routes)) {
      if (url.includes(pattern)) return handler()
    }
    return new Response('not mocked: ' + url, { status: 599 })
  })
}

function makeJob(overrides: Partial<BossJob> = {}): BossJob {
  return {
    id: 1,
    recruiter_id: 1,
    boss_job_id: 'JD001',
    title: 'Backend Engineer',
    status: 'open',
    salary_min: 30000,
    salary_max: 60000,
    location: '上海',
    education: '本科',
    experience: '5-10年',
    ...overrides,
  }
}

describe('useBossJobsStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('fetchJobs', () => {
    it('populates jobsByRecruiter on success', async () => {
      const payload: BossJobListResponse = {
        jobs: [makeJob({ id: 1, boss_job_id: 'A' }), makeJob({ id: 2, boss_job_id: 'B' })],
        total: 2,
      }
      FETCH_GLOBAL.fetch = mockFetchByUrl({
        '/api/boss/jobs?': () => jsonResponse(payload),
      })

      const store = useBossJobsStore()
      await store.fetchJobs(1)

      expect(store.jobsFor(1)).toHaveLength(2)
      expect(store.error).toBeNull()
      expect(store.totalJobsLoaded).toBe(2)
    })

    it('passes status_filter to API when provided', async () => {
      const seenUrls: string[] = []
      FETCH_GLOBAL.fetch = vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input.toString()
        seenUrls.push(url)
        return jsonResponse({ jobs: [], total: 0 } as BossJobListResponse)
      })

      const store = useBossJobsStore()
      await store.fetchJobs(1, 'closed')

      expect(seenUrls.some((u) => u.includes('status_filter=closed'))).toBe(true)
    })

    it('records error on API failure', async () => {
      FETCH_GLOBAL.fetch = mockFetchByUrl({
        '/api/boss/jobs?': () => jsonResponse({ detail: 'broken' }, 500),
      })
      const store = useBossJobsStore()
      await store.fetchJobs(1)

      expect(store.error).toMatch(/500/)
      expect(store.jobsFor(1)).toEqual([])
    })

    it('captures network rejection', async () => {
      FETCH_GLOBAL.fetch = vi.fn(async () => {
        throw new Error('boom')
      })
      const store = useBossJobsStore()
      await store.fetchJobs(7)
      expect(store.error).toBe('boom')
    })
  })

  describe('syncJobs', () => {
    it('records sync result and refreshes jobs for recruiter', async () => {
      const syncResp: BossJobSyncResponse = {
        recruiter_id: 1,
        total_jobs: 4,
        per_tab: [
          { tab: 'open', count: 3 },
          { tab: 'closed', count: 1 },
        ],
        errors: [],
      }
      const listResp: BossJobListResponse = {
        jobs: [makeJob({ id: 1, boss_job_id: 'NEW' })],
        total: 1,
      }
      FETCH_GLOBAL.fetch = mockFetchByUrl({
        '/api/boss/jobs/sync': () => jsonResponse(syncResp),
        '/api/boss/jobs?': () => jsonResponse(listResp),
      })

      const store = useBossJobsStore()
      const result = await store.syncJobs('EMU-1')

      expect(result).toEqual(syncResp)
      expect(store.lastSyncResults['EMU-1']).toEqual(syncResp)
      expect(store.jobsFor(1)).toHaveLength(1)
      expect(store.isSyncing('EMU-1')).toBe(false)
    })

    it('records error and returns null when sync fails', async () => {
      FETCH_GLOBAL.fetch = mockFetchByUrl({
        '/api/boss/jobs/sync': () => jsonResponse({ detail: 'no recruiter' }, 404),
      })
      const store = useBossJobsStore()
      const result = await store.syncJobs('EMU-MISSING')
      expect(result).toBeNull()
      expect(store.error).toMatch(/404/)
    })

    it('respects explicit recruiterId for the post-sync refresh', async () => {
      const syncResp: BossJobSyncResponse = {
        recruiter_id: 99,
        total_jobs: 0,
        per_tab: [],
        errors: [],
      }
      const listResp: BossJobListResponse = { jobs: [], total: 0 }
      const seenUrls: string[] = []
      FETCH_GLOBAL.fetch = vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input.toString()
        seenUrls.push(url)
        if (url.includes('/sync')) return jsonResponse(syncResp)
        return jsonResponse(listResp)
      })

      const store = useBossJobsStore()
      await store.syncJobs('EMU-X', { recruiterId: 42 })

      expect(seenUrls.some((u) => u.includes('recruiter_id=42'))).toBe(true)
    })
  })

  describe('selectors', () => {
    it('jobsFor returns empty array when no entry exists', () => {
      const store = useBossJobsStore()
      expect(store.jobsFor(123)).toEqual([])
    })

    it('isLoading and isSyncing reflect transient state', async () => {
      const store = useBossJobsStore()
      expect(store.isLoading(1)).toBe(false)
      expect(store.isSyncing('EMU-1')).toBe(false)
    })
  })
})
