// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import GreetScheduleView from './GreetScheduleView.vue'
import type {
  BossGreetSettings,
  BossGreetTestRunResponse,
  BossRecruiterListResponse,
} from '../../services/bossApi'

const FETCH_GLOBAL = globalThis as unknown as { fetch: typeof fetch }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function setupRoutes(routes: Array<{ match: (url: string) => boolean; handler: () => Response }>): ReturnType<typeof vi.fn> {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString()
    for (const r of routes) {
      if (r.match(url)) return r.handler()
    }
    return new Response('not mocked: ' + url, { status: 599 })
  })
  FETCH_GLOBAL.fetch = fn
  return fn
}

const recruiterPayload: BossRecruiterListResponse = {
  total: 1,
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
}

function makeSettings(overrides: Partial<BossGreetSettings> = {}): BossGreetSettings {
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

describe('GreetScheduleView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the empty card when no recruiters exist', async () => {
    setupRoutes([
      {
        match: (u) => u.includes('/api/boss/recruiters'),
        handler: () => jsonResponse({ recruiters: [], total: 0 }),
      },
    ])

    const wrapper = mount(GreetScheduleView)
    await flushPromises()

    expect(wrapper.find('[data-testid="empty-recruiters"]').exists()).toBe(true)
  })

  it('renders one section per recruiter and pre-fills the form', async () => {
    setupRoutes([
      {
        match: (u) => u.includes('/api/boss/recruiters'),
        handler: () => jsonResponse(recruiterPayload),
      },
      {
        match: (u) => u.includes('/api/boss/greet/settings/'),
        handler: () => jsonResponse(makeSettings()),
      },
    ])

    const wrapper = mount(GreetScheduleView)
    await flushPromises()
    await flushPromises()

    expect(wrapper.find('[data-testid="recruiter-section"]').exists()).toBe(true)
    expect(
      (wrapper.find('[data-testid="start-time-EMU-1"]').element as HTMLInputElement).value,
    ).toBe('09:00')
    expect(
      (wrapper.find('[data-testid="end-time-EMU-1"]').element as HTMLInputElement).value,
    ).toBe('18:00')
    expect(
      (wrapper.find('[data-testid="per-day-EMU-1"]').element as HTMLInputElement).value,
    ).toBe('80')
  })

  it('save button issues a PUT to the settings endpoint', async () => {
    let putCalls = 0
    const fetchSpy = setupRoutes([
      {
        match: (u) => u.includes('/api/boss/recruiters'),
        handler: () => jsonResponse(recruiterPayload),
      },
      {
        match: (u) => u.includes('/api/boss/greet/settings/'),
        handler: () => {
          // GET first, PUT second; both return the same payload here.
          putCalls += 1
          return jsonResponse(makeSettings({ enabled: true }))
        },
      },
    ])

    const wrapper = mount(GreetScheduleView)
    await flushPromises()
    await flushPromises()

    await wrapper.find('[data-testid="save-EMU-1"]').trigger('click')
    await flushPromises()

    const calls = (fetchSpy.mock.calls as Array<[RequestInfo | URL, RequestInit | undefined]>).filter(
      ([, init]) => init?.method === 'PUT',
    )
    expect(calls.length).toBeGreaterThan(0)
    expect(putCalls).toBeGreaterThan(0)
  })

  it('test-run button shows the outcome label after success', async () => {
    const outcome: BossGreetTestRunResponse = {
      outcome: 'sent',
      boss_candidate_id: 'CAND-A',
      candidate_name: '李雷',
      detail: null,
    }
    setupRoutes([
      {
        match: (u) => u.includes('/api/boss/recruiters'),
        handler: () => jsonResponse(recruiterPayload),
      },
      {
        match: (u) => u.includes('/api/boss/greet/settings/'),
        handler: () => jsonResponse(makeSettings()),
      },
      {
        match: (u) => u.includes('/api/boss/greet/test-run'),
        handler: () => jsonResponse(outcome),
      },
    ])

    const wrapper = mount(GreetScheduleView)
    await flushPromises()
    await flushPromises()

    await wrapper.find('[data-testid="test-EMU-1"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="outcome-EMU-1"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="outcome-EMU-1"]').text()).toContain('发送成功')
  })

  it('shows the error banner on failure', async () => {
    setupRoutes([
      {
        match: (u) => u.includes('/api/boss/recruiters'),
        handler: () => jsonResponse({ detail: 'broken' }, 500),
      },
    ])

    const wrapper = mount(GreetScheduleView)
    await flushPromises()

    expect(wrapper.find('[data-testid="error-banner"]').exists()).toBe(true)
  })
})
