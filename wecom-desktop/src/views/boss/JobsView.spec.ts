// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import JobsView from './JobsView.vue'
import type {
  BossJob,
  BossJobListResponse,
  BossJobSyncResponse,
  BossRecruiterListResponse,
} from '../../services/bossApi'

const FETCH_GLOBAL = globalThis as unknown as { fetch: typeof fetch }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function setupRoutes(routes: Array<{ match: (url: string) => boolean; handler: () => Response }>): void {
  FETCH_GLOBAL.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString()
    for (const r of routes) {
      if (r.match(url)) return r.handler()
    }
    return new Response('not mocked: ' + url, { status: 599 })
  })
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

function makeJob(overrides: Partial<BossJob> = {}): BossJob {
  return {
    id: 100,
    recruiter_id: 1,
    boss_job_id: 'JD001',
    title: 'Senior Backend Engineer',
    status: 'open',
    salary_min: 30000,
    salary_max: 60000,
    location: '上海·浦东新区',
    education: '本科',
    experience: '5-10年',
    ...overrides,
  }
}

describe('JobsView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows the empty-recruiters card when no recruiters exist', async () => {
    setupRoutes([
      {
        match: (u) => u.includes('/api/boss/recruiters'),
        handler: () => jsonResponse({ recruiters: [], total: 0 }),
      },
    ])

    const wrapper = mount(JobsView)
    await flushPromises()

    expect(wrapper.find('[data-testid="empty-recruiters"]').exists()).toBe(true)
  })

  it('renders one section per recruiter and lists their jobs', async () => {
    const jobsResp: BossJobListResponse = {
      total: 2,
      jobs: [
        makeJob({ id: 1, boss_job_id: 'A', title: 'Backend' }),
        makeJob({ id: 2, boss_job_id: 'B', title: 'Frontend', status: 'closed', salary_min: null, salary_max: null }),
      ],
    }

    setupRoutes([
      {
        match: (u) => u.includes('/api/boss/recruiters'),
        handler: () => jsonResponse(recruiterPayload),
      },
      {
        match: (u) => u.includes('/api/boss/jobs?'),
        handler: () => jsonResponse(jobsResp),
      },
    ])

    const wrapper = mount(JobsView)
    await flushPromises()
    await flushPromises()

    const sections = wrapper.findAll('[data-testid="recruiter-section"]')
    expect(sections).toHaveLength(1)
    expect(wrapper.find('[data-testid="recruiter-heading"]').text()).toBe('王经理')

    const cards = wrapper.findAll('[data-testid="job-card"]')
    expect(cards).toHaveLength(2)
    expect(cards[0].find('[data-testid="job-title"]').text()).toBe('Backend')
    expect(cards[0].find('[data-testid="job-salary"]').text()).toBe('30K-60K')
    expect(cards[1].find('[data-testid="job-status"]').text()).toBe('已关闭')
    expect(cards[1].find('[data-testid="job-salary"]').text()).toBe('面议')
  })

  it('clicking sync triggers a sync API call and shows last-sync summary', async () => {
    const syncResp: BossJobSyncResponse = {
      recruiter_id: 1,
      total_jobs: 4,
      per_tab: [
        { tab: 'open', count: 3 },
        { tab: 'closed', count: 1 },
      ],
      errors: [],
    }
    let syncCalls = 0
    setupRoutes([
      {
        match: (u) => u.includes('/api/boss/recruiters'),
        handler: () => jsonResponse(recruiterPayload),
      },
      {
        match: (u) => u.includes('/api/boss/jobs/sync'),
        handler: () => {
          syncCalls += 1
          return jsonResponse(syncResp)
        },
      },
      {
        match: (u) => u.includes('/api/boss/jobs?'),
        handler: () => jsonResponse({ jobs: [], total: 0 }),
      },
    ])

    const wrapper = mount(JobsView)
    await flushPromises()
    await flushPromises()

    await wrapper.find('[data-testid="sync-EMU-1"]').trigger('click')
    await flushPromises()

    expect(syncCalls).toBe(1)
    expect(wrapper.find('[data-testid="last-sync-EMU-1"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="last-sync-EMU-1"]').text()).toMatch(/4/)
  })

  it('shows an error banner when the API fails', async () => {
    setupRoutes([
      {
        match: (u) => u.includes('/api/boss/recruiters'),
        handler: () => jsonResponse({ detail: 'broken' }, 500),
      },
    ])

    const wrapper = mount(JobsView)
    await flushPromises()

    expect(wrapper.find('[data-testid="error-banner"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="error-banner"]').text()).toMatch(/500/)
  })
})
