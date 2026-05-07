// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ConversationsView from './ConversationsView.vue'
import type {
  BossConversationsListResponse,
  BossDispatchResponse,
  BossMessagesListResponse,
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

const conversationsPayload: BossConversationsListResponse = {
  recruiter_id: 10,
  conversations: [
    { id: 1, recruiter_id: 10, candidate_id: 100, unread_count: 2, last_direction: 'in' },
    { id: 2, recruiter_id: 10, candidate_id: 101, unread_count: 0, last_direction: 'out' },
  ],
}

const messagesPayload: BossMessagesListResponse = {
  conversation_id: 1,
  messages: [
    {
      id: 1,
      direction: 'in',
      content_type: 'text',
      text: '您好',
      sent_at_iso: '2026-05-07T10:00:00+00:00',
      sent_by: 'manual',
      template_id: null,
    },
    {
      id: 2,
      direction: 'out',
      content_type: 'text',
      text: '欢迎',
      sent_at_iso: '2026-05-07T10:01:00+00:00',
      sent_by: 'template',
      template_id: 99,
    },
  ],
}

describe('ConversationsView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows empty-recruiters when none exist', async () => {
    setupRoutes([
      {
        match: (u) => u.includes('/api/boss/recruiters'),
        handler: () => jsonResponse({ recruiters: [], total: 0 }),
      },
    ])

    const wrapper = mount(ConversationsView)
    await flushPromises()

    expect(wrapper.find('[data-testid="empty-recruiters"]').exists()).toBe(true)
  })

  it('lists conversations for each recruiter on mount', async () => {
    setupRoutes([
      {
        match: (u) => u.includes('/api/boss/recruiters'),
        handler: () => jsonResponse(recruiterPayload),
      },
      {
        match: (u) => u.includes('/api/boss/messages/recruiters/10/conversations'),
        handler: () => jsonResponse(conversationsPayload),
      },
    ])

    const wrapper = mount(ConversationsView)
    await flushPromises()
    await flushPromises()

    expect(wrapper.find('[data-testid="conversation-1"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="conversation-2"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="unread-1"]').text()).toContain('2')
  })

  it('selecting a conversation loads and renders messages', async () => {
    setupRoutes([
      {
        match: (u) => u.includes('/api/boss/recruiters'),
        handler: () => jsonResponse(recruiterPayload),
      },
      {
        match: (u) => u.includes('/api/boss/messages/recruiters/10/conversations'),
        handler: () => jsonResponse(conversationsPayload),
      },
      {
        match: (u) => u.includes('/api/boss/messages/conversations/1'),
        handler: () => jsonResponse(messagesPayload),
      },
    ])

    const wrapper = mount(ConversationsView)
    await flushPromises()
    await flushPromises()

    await wrapper.find('[data-testid="conversation-1"]').trigger('click')
    await flushPromises()

    const list = wrapper.find('[data-testid="messages-1"]')
    expect(list.exists()).toBe(true)
    expect(list.text()).toContain('您好')
    expect(list.text()).toContain('欢迎')
  })

  it('dispatch button records the outcome and shows it', async () => {
    const dispatchResponse: BossDispatchResponse = {
      outcome: 'sent_template',
      boss_candidate_id: 'CAND-A',
      candidate_name: '李雷',
      text_sent: '您好 李雷，方便聊聊吗？',
      template_warnings: [],
    }
    setupRoutes([
      {
        match: (u) => u.includes('/api/boss/recruiters'),
        handler: () => jsonResponse(recruiterPayload),
      },
      {
        match: (u) => u.includes('/api/boss/messages/recruiters/10/conversations'),
        handler: () => jsonResponse(conversationsPayload),
      },
      {
        match: (u, init) => u.endsWith('/api/boss/messages/dispatch') && init?.method === 'POST',
        handler: () => jsonResponse(dispatchResponse),
      },
    ])

    const wrapper = mount(ConversationsView)
    await flushPromises()
    await flushPromises()

    await wrapper.find('[data-testid="dispatch-EMU-1"]').trigger('click')
    await flushPromises()

    const result = wrapper.find('[data-testid="dispatch-result-EMU-1"]')
    expect(result.exists()).toBe(true)
    expect(result.text()).toContain('已发送')
    expect(result.text()).toContain('李雷')
  })
})
