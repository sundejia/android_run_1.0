// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useBossMessagesStore } from './bossMessages'
import type {
  BossConversation,
  BossDispatchResponse,
  BossMessage,
} from '../services/bossApi'

const FETCH_GLOBAL = globalThis as unknown as { fetch: typeof fetch }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function conversation(overrides: Partial<BossConversation> = {}): BossConversation {
  return {
    id: 1,
    recruiter_id: 10,
    candidate_id: 100,
    unread_count: 1,
    last_direction: 'in',
    ...overrides,
  }
}

function message(overrides: Partial<BossMessage> = {}): BossMessage {
  return {
    id: 1,
    direction: 'in',
    content_type: 'text',
    text: '您好',
    sent_at_iso: '2026-05-07T10:00:00+00:00',
    sent_by: 'manual',
    template_id: null,
    ...overrides,
  }
}

describe('useBossMessagesStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('loadConversations stores rows under the recruiter id', async () => {
    FETCH_GLOBAL.fetch = vi.fn(async () =>
      jsonResponse({
        recruiter_id: 10,
        conversations: [conversation(), conversation({ id: 2, unread_count: 3 })],
      }),
    )
    const store = useBossMessagesStore()
    const rows = await store.loadConversations(10)
    expect(rows).toHaveLength(2)
    expect(store.conversationsFor(10)).toHaveLength(2)
    expect(store.totalUnread).toBe(4)
  })

  it('loadMessages stores messages under the conversation id', async () => {
    FETCH_GLOBAL.fetch = vi.fn(async () =>
      jsonResponse({
        conversation_id: 1,
        messages: [message(), message({ id: 2, direction: 'out', text: '你好' })],
      }),
    )
    const store = useBossMessagesStore()
    const rows = await store.loadMessages(1)
    expect(rows).toHaveLength(2)
    expect(store.messagesFor(1)[1].text).toBe('你好')
  })

  it('dispatchReply records last response per device', async () => {
    const response: BossDispatchResponse = {
      outcome: 'sent_template',
      boss_candidate_id: 'CAND-A',
      candidate_name: '李雷',
      text_sent: '您好 李雷',
      template_warnings: [],
    }
    FETCH_GLOBAL.fetch = vi.fn(async () => jsonResponse(response))
    const store = useBossMessagesStore()
    const result = await store.dispatchReply('EMU-1')
    expect(result?.outcome).toBe('sent_template')
    expect(store.lastDispatch['EMU-1']?.text_sent).toBe('您好 李雷')
  })

  it('records error on API failure', async () => {
    FETCH_GLOBAL.fetch = vi.fn(async () => jsonResponse({ detail: 'broken' }, 500))
    const store = useBossMessagesStore()
    const rows = await store.loadConversations(10)
    expect(rows).toEqual([])
    expect(store.error).toMatch(/500/)
  })
})
