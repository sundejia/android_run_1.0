// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useBossTemplatesStore } from './bossTemplates'
import type { BossTemplate } from '../services/bossApi'

const FETCH_GLOBAL = globalThis as unknown as { fetch: typeof fetch }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function template(overrides: Partial<BossTemplate> = {}): BossTemplate {
  return {
    id: 1,
    name: 'default',
    scenario: 'reply',
    content: '您好 {name}',
    is_default: true,
    variables_json: null,
    ...overrides,
  }
}

describe('useBossTemplatesStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('load() populates templatesByScenario', async () => {
    FETCH_GLOBAL.fetch = vi.fn(async () =>
      jsonResponse({ templates: [template(), template({ id: 2, name: 'other', is_default: false })] }),
    )
    const store = useBossTemplatesStore()
    const rows = await store.load('reply')
    expect(rows).toHaveLength(2)
    expect(store.templatesFor('reply')).toHaveLength(2)
    expect(store.total).toBe(2)
  })

  it('create() appends the returned template to the right scenario', async () => {
    FETCH_GLOBAL.fetch = vi.fn(async () => jsonResponse(template({ id: 7 })))
    const store = useBossTemplatesStore()
    const created = await store.create({ name: 'x', scenario: 'reply', content: 'y' })
    expect(created?.id).toBe(7)
    expect(store.templatesFor('reply').map((r) => r.id)).toEqual([7])
  })

  it('update() replaces the existing record in the cache', async () => {
    const initial = template({ id: 1, content: 'old' })
    const updated = template({ id: 1, content: 'new' })
    FETCH_GLOBAL.fetch = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ templates: [initial] }))
      .mockResolvedValueOnce(jsonResponse(updated))

    const store = useBossTemplatesStore()
    await store.load('reply')
    await store.update(1, 'reply', { content: 'new' })
    expect(store.templatesFor('reply')[0].content).toBe('new')
  })

  it('remove() drops the record from the cache', async () => {
    FETCH_GLOBAL.fetch = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ templates: [template({ id: 1 }), template({ id: 2 })] }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))

    const store = useBossTemplatesStore()
    await store.load('reply')
    const ok = await store.remove(1, 'reply')
    expect(ok).toBe(true)
    expect(store.templatesFor('reply').map((r) => r.id)).toEqual([2])
  })

  it('preview() captures result + warnings', async () => {
    FETCH_GLOBAL.fetch = vi.fn(async () =>
      jsonResponse({ text: 'Hi 李雷 {missing}', warnings: ['missing'] }),
    )
    const store = useBossTemplatesStore()
    const result = await store.preview({
      content: 'Hi {name} {missing}',
      context: { name: '李雷' },
    })
    expect(result?.text).toContain('{missing}')
    expect(result?.warnings).toEqual(['missing'])
    expect(store.lastPreview?.warnings).toEqual(['missing'])
  })

  it('records error string on API failure', async () => {
    FETCH_GLOBAL.fetch = vi.fn(async () => jsonResponse({ detail: 'broken' }, 500))
    const store = useBossTemplatesStore()
    const rows = await store.load('reply')
    expect(rows).toEqual([])
    expect(store.error).toMatch(/500/)
  })
})
