// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useBossRecruitersStore } from './bossRecruiters'
import type { BossRecruiter, BossRecruiterListResponse } from '../services/bossApi'

const FETCH_GLOBAL = globalThis as unknown as { fetch: typeof fetch }

function mockFetch(handler: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    return await handler(url, init)
  })
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('useBossRecruitersStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('fetchAll', () => {
    it('populates recruiters on success', async () => {
      const payload: BossRecruiterListResponse = {
        recruiters: [
          {
            id: 1,
            device_serial: 'EMU-1',
            name: '王经理',
            company: 'ACME',
            position: 'HRBP',
            avatar_path: null,
          },
        ],
        total: 1,
      }
      FETCH_GLOBAL.fetch = mockFetch(() => jsonResponse(payload))

      const store = useBossRecruitersStore()
      await store.fetchAll()

      expect(store.recruiters).toHaveLength(1)
      expect(store.recruiters[0].name).toBe('王经理')
      expect(store.error).toBeNull()
      expect(store.loading).toBe(false)
      expect(store.lastFetchedAt).not.toBeNull()
    })

    it('records error on non-200', async () => {
      FETCH_GLOBAL.fetch = mockFetch(() =>
        jsonResponse({ detail: 'broken' }, 500),
      )

      const store = useBossRecruitersStore()
      await store.fetchAll()

      expect(store.recruiters).toEqual([])
      expect(store.error).not.toBeNull()
      expect(store.error).toMatch(/500/)
    })

    it('handles network rejection', async () => {
      FETCH_GLOBAL.fetch = vi.fn(async () => {
        throw new Error('network down')
      })

      const store = useBossRecruitersStore()
      await store.fetchAll()

      expect(store.error).toBe('network down')
      expect(store.loading).toBe(false)
    })
  })

  describe('refreshOne', () => {
    it('inserts a new recruiter when not yet present', async () => {
      const updated: BossRecruiter = {
        id: 5,
        device_serial: 'EMU-5',
        name: '张猎头',
        company: '北辰',
        position: 'HRBP',
        avatar_path: null,
      }
      FETCH_GLOBAL.fetch = mockFetch((_url, init) => {
        expect(init?.method).toBe('POST')
        return jsonResponse(updated)
      })

      const store = useBossRecruitersStore()
      const result = await store.refreshOne('EMU-5', { name: '张猎头', company: '北辰' })

      expect(result).toEqual(updated)
      expect(store.recruiters).toHaveLength(1)
      expect(store.recruiters[0].device_serial).toBe('EMU-5')
    })

    it('updates an existing recruiter in place', async () => {
      const store = useBossRecruitersStore()
      store.recruiters = [
        { id: 1, device_serial: 'EMU-1', name: 'OLD', company: null, position: null, avatar_path: null },
      ]
      const updated: BossRecruiter = {
        id: 1,
        device_serial: 'EMU-1',
        name: 'NEW',
        company: 'ACME',
        position: 'HRBP',
        avatar_path: null,
      }
      FETCH_GLOBAL.fetch = mockFetch(() => jsonResponse(updated))

      const result = await store.refreshOne('EMU-1', { name: 'NEW', company: 'ACME' })

      expect(result).toEqual(updated)
      expect(store.recruiters).toHaveLength(1)
      expect(store.recruiters[0].name).toBe('NEW')
    })

    it('records error and returns null when API rejects', async () => {
      FETCH_GLOBAL.fetch = mockFetch(() => jsonResponse({ detail: 'bad' }, 400))

      const store = useBossRecruitersStore()
      const result = await store.refreshOne('EMU-9', { name: 'X' })

      expect(result).toBeNull()
      expect(store.error).toMatch(/400/)
    })
  })

  describe('getBySerial', () => {
    it('returns the matching recruiter or undefined', () => {
      const store = useBossRecruitersStore()
      store.recruiters = [
        { id: 1, device_serial: 'EMU-1', name: 'A', company: null, position: null, avatar_path: null },
      ]
      expect(store.getBySerial('EMU-1')?.name).toBe('A')
      expect(store.getBySerial('NOPE')).toBeUndefined()
    })
  })
})
