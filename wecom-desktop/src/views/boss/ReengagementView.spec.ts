// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ReengagementView from './ReengagementView.vue'
import type {
  BossReengagementScanResponse,
  BossReengagementSettings,
  BossRecruiterListResponse,
} from '../../services/bossApi'

const FETCH_GLOBAL = globalThis as unknown as { fetch: typeof fetch }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

interface Route {
  match: (url: string, init?: RequestInit) => boolean
  handler: (url: string, init?: RequestInit) => Response
}

function setupRoutes(routes: Route[]): void {
  FETCH_GLOBAL.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    for (const r of routes) {
      if (r.match(url, init)) return r.handler(url, init)
    }
    return new Response('not mocked: ' + url, { status: 599 })
  })
}

const recruiterPayload: BossRecruiterListResponse = {
  total: 1,
  recruiters: [
    {
      id: 10,
      device_serial: 'EMU-1',
      name: '王经理',
      company: 'ACME',
      position: 'HRBP',
      avatar_path: null,
    },
  ],
}

const settingsPayload: BossReengagementSettings = {
  device_serial: 'EMU-1',
  silent_for_days: 3,
  cooldown_days: 7,
  daily_cap: 50,
  template_id: null,
  enabled: false,
}

const scanPayload: BossReengagementScanResponse = {
  recruiter_id: 10,
  eligible: [
    {
      candidate_id: 1,
      boss_candidate_id: 'CAND-A',
      conversation_id: 11,
      last_outbound_at_iso: '2026-05-03T12:00:00+00:00',
      silent_for_seconds: 4 * 86400,
    },
  ],
}

describe('ReengagementView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows empty-recruiters card when none exist', async () => {
    setupRoutes([
      {
        match: (u) => u.includes('/api/boss/recruiters'),
        handler: () => jsonResponse({ recruiters: [], total: 0 }),
      },
    ])
    const wrapper = mount(ReengagementView)
    await flushPromises()
    expect(wrapper.find('[data-testid="empty-recruiters"]').exists()).toBe(true)
  })

  it('renders settings form populated from API', async () => {
    setupRoutes([
      {
        match: (u) => u.includes('/api/boss/recruiters'),
        handler: () => jsonResponse(recruiterPayload),
      },
      {
        match: (u) => u.includes('/api/boss/reengagement/settings/EMU-1'),
        handler: () => jsonResponse(settingsPayload),
      },
    ])

    const wrapper = mount(ReengagementView)
    await flushPromises()
    await flushPromises()

    const silent = wrapper.find('[data-testid="silent-EMU-1"]')
    expect((silent.element as HTMLInputElement).value).toBe('3')
    const cap = wrapper.find('[data-testid="daily-cap-EMU-1"]')
    expect((cap.element as HTMLInputElement).value).toBe('50')
  })

  it('scan button populates the eligible list', async () => {
    setupRoutes([
      {
        match: (u) => u.includes('/api/boss/recruiters'),
        handler: () => jsonResponse(recruiterPayload),
      },
      {
        match: (u) => u.includes('/api/boss/reengagement/settings/EMU-1'),
        handler: () => jsonResponse(settingsPayload),
      },
      {
        match: (u, init) =>
          u.endsWith('/api/boss/reengagement/scan') && init?.method === 'POST',
        handler: () => jsonResponse(scanPayload),
      },
    ])

    const wrapper = mount(ReengagementView)
    await flushPromises()
    await flushPromises()

    await wrapper.find('[data-testid="scan-EMU-1"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="eligible-1"]').exists()).toBe(true)
  })

  it('run button records the outcome', async () => {
    setupRoutes([
      {
        match: (u) => u.includes('/api/boss/recruiters'),
        handler: () => jsonResponse(recruiterPayload),
      },
      {
        match: (u) => u.includes('/api/boss/reengagement/settings/EMU-1'),
        handler: () => jsonResponse(settingsPayload),
      },
      {
        match: (u, init) =>
          u.endsWith('/api/boss/reengagement/run') && init?.method === 'POST',
        handler: () =>
          jsonResponse({
            outcome: 'dry_run',
            boss_candidate_id: 'CAND-A',
            candidate_id: 1,
            attempt_id: 7,
            detail: null,
          }),
      },
      {
        match: (u, init) =>
          u.endsWith('/api/boss/reengagement/scan') && init?.method === 'POST',
        handler: () => jsonResponse(scanPayload),
      },
    ])

    const wrapper = mount(ReengagementView)
    await flushPromises()
    await flushPromises()

    await wrapper.find('[data-testid="run-EMU-1"]').trigger('click')
    await flushPromises()

    const result = wrapper.find('[data-testid="last-run-EMU-1"]')
    expect(result.exists()).toBe(true)
    expect(result.text()).toContain('空跑')
    expect(result.text()).toContain('CAND-A')
  })
})
