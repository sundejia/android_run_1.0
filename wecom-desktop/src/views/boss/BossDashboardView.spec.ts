// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import BossDashboardView from './BossDashboardView.vue'
import type { BossMonitoringSummaryResponse } from '../../services/bossApi'

const FETCH_GLOBAL = globalThis as unknown as { fetch: typeof fetch }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const fullSummary: BossMonitoringSummaryResponse = {
  generated_at_iso: '2026-05-07T18:00:00+00:00',
  window_hours: 24,
  recruiters: [
    {
      recruiter_id: 1,
      device_serial: 'EMU-1',
      name: '王经理',
      company: 'ACME',
      position: 'HRBP',
      jobs_by_status: { open: 2, closed: 1 },
      candidates_by_status: { greeted: 5, new: 2 },
      greet_attempts_last_24h: { sent: 4, cancelled: 1, failed: 0 },
      reengagement_attempts_last_24h: { sent: 3, cancelled: 1, failed: 1 },
      silent_candidates_eligible: 6,
    },
    {
      recruiter_id: 2,
      device_serial: 'EMU-2',
      name: null,
      company: null,
      position: null,
      jobs_by_status: {},
      candidates_by_status: {},
      greet_attempts_last_24h: { sent: 0, cancelled: 0, failed: 0 },
      reengagement_attempts_last_24h: { sent: 0, cancelled: 0, failed: 0 },
      silent_candidates_eligible: 0,
    },
  ],
}

describe('BossDashboardView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders empty card when no recruiters are returned', async () => {
    FETCH_GLOBAL.fetch = vi.fn(async () =>
      jsonResponse({
        generated_at_iso: '2026-05-07T18:00:00+00:00',
        window_hours: 24,
        recruiters: [],
      } satisfies BossMonitoringSummaryResponse),
    )
    const wrapper = mount(BossDashboardView)
    await flushPromises()
    expect(wrapper.find('[data-testid="empty-recruiters"]').exists()).toBe(true)
  })

  it('renders one card per recruiter with status counts', async () => {
    FETCH_GLOBAL.fetch = vi.fn(async () => jsonResponse(fullSummary))
    const wrapper = mount(BossDashboardView)
    await flushPromises()

    const cards = wrapper.findAll('[data-testid="recruiter-card"]')
    expect(cards).toHaveLength(2)

    const card1 = wrapper.find('[data-testid="recruiter-card-EMU-1"]')
    expect(card1.text()).toContain('王经理')
    expect(card1.text()).toContain('ACME')
    expect(card1.find('[data-testid="silent-eligible-EMU-1"]').text()).toContain('6')
    expect(card1.find('[data-testid="reengage-sent-EMU-1"]').text()).toContain('3')
    expect(card1.find('[data-testid="job-open-EMU-1"]').text()).toContain('2')
    expect(card1.find('[data-testid="job-closed-EMU-1"]').text()).toContain('1')
  })

  it('refresh button reloads the summary', async () => {
    const fetchSpy = vi.fn(async () => jsonResponse(fullSummary))
    FETCH_GLOBAL.fetch = fetchSpy
    const wrapper = mount(BossDashboardView)
    await flushPromises()
    expect(fetchSpy).toHaveBeenCalledTimes(1)

    await wrapper.find('[data-testid="refresh"]').trigger('click')
    await flushPromises()
    expect(fetchSpy).toHaveBeenCalledTimes(2)
  })

  it('renders error banner when summary fetch fails', async () => {
    FETCH_GLOBAL.fetch = vi.fn(async () => jsonResponse({ detail: 'broken' }, 500))
    const wrapper = mount(BossDashboardView)
    await flushPromises()
    expect(wrapper.find('[data-testid="error-banner"]').exists()).toBe(true)
  })

  it('shows aggregated totals at the top', async () => {
    FETCH_GLOBAL.fetch = vi.fn(async () => jsonResponse(fullSummary))
    const wrapper = mount(BossDashboardView)
    await flushPromises()

    const totalSilent = wrapper.find('[data-testid="total-silent"]')
    expect(totalSilent.text()).toContain('6')

    const totalReengage = wrapper.find('[data-testid="total-reengage-sent"]')
    expect(totalReengage.text()).toContain('3')
  })
})
