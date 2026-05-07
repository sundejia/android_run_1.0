// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import RecruitersListView from './RecruitersListView.vue'
import type { BossRecruiterListResponse } from '../../services/bossApi'

const FETCH_GLOBAL = globalThis as unknown as { fetch: typeof fetch }

function mockFetch(body: BossRecruiterListResponse | { detail: string }, status = 200) {
  FETCH_GLOBAL.fetch = vi.fn(async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

describe('RecruitersListView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the empty state when no recruiters are returned', async () => {
    mockFetch({ recruiters: [], total: 0 })
    const wrapper = mount(RecruitersListView)
    await flushPromises()

    expect(wrapper.find('[data-testid="empty-state"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="recruiter-grid"]').exists()).toBe(false)
  })

  it('renders one card per recruiter with name, company, position', async () => {
    mockFetch({
      total: 2,
      recruiters: [
        {
          id: 1,
          device_serial: 'EMU-A',
          name: '王经理',
          company: 'ACME',
          position: 'HRBP',
          avatar_path: null,
        },
        {
          id: 2,
          device_serial: 'EMU-B',
          name: null,
          company: null,
          position: null,
          avatar_path: null,
        },
      ],
    })
    const wrapper = mount(RecruitersListView)
    await flushPromises()

    const cards = wrapper.findAll('[data-testid="recruiter-card"]')
    expect(cards).toHaveLength(2)

    const namedCard = cards[0]
    expect(namedCard.find('[data-testid="recruiter-name"]').text()).toBe('王经理')
    expect(namedCard.find('[data-testid="recruiter-serial"]').text()).toBe('EMU-A')
    expect(namedCard.find('[data-testid="recruiter-company"]').text()).toBe('ACME')
    expect(namedCard.find('[data-testid="recruiter-position"]').text()).toBe('HRBP')
    expect(namedCard.find('[data-testid="recruiter-status"]').text()).toBe('已识别')
    expect(namedCard.find('[data-testid="recruiter-status"]').attributes('data-status')).toBe('open')

    const unnamedCard = cards[1]
    expect(unnamedCard.find('[data-testid="recruiter-name"]').text()).toBe('（未读取到姓名）')
    expect(unnamedCard.find('[data-testid="recruiter-status"]').text()).toBe('待识别')
    expect(unnamedCard.find('[data-testid="recruiter-status"]').attributes('data-status')).toBe('warning')
  })

  it('shows the error banner when the API call fails', async () => {
    mockFetch({ detail: 'service unavailable' }, 500)
    const wrapper = mount(RecruitersListView)
    await flushPromises()

    expect(wrapper.find('[data-testid="error-banner"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="error-banner"]').text()).toMatch(/500/)
  })

  it('reload button triggers another fetch', async () => {
    mockFetch({ recruiters: [], total: 0 })
    const wrapper = mount(RecruitersListView)
    await flushPromises()

    expect(FETCH_GLOBAL.fetch).toHaveBeenCalledTimes(1)

    await wrapper.find('[data-testid="reload-all-button"]').trigger('click')
    await flushPromises()

    expect(FETCH_GLOBAL.fetch).toHaveBeenCalledTimes(2)
  })
})
