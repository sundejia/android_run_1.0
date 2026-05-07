// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import TemplatesView from './TemplatesView.vue'
import type { BossTemplate } from '../../services/bossApi'

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

describe('TemplatesView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders templates returned from the API on mount', async () => {
    setupRoutes([
      {
        match: (u) => u.includes('/api/boss/templates/?scenario=reply'),
        handler: () =>
          jsonResponse({
            templates: [template(), template({ id: 2, name: 'alt', is_default: false })],
          }),
      },
    ])

    const wrapper = mount(TemplatesView)
    await flushPromises()

    expect(wrapper.find('[data-testid="empty-templates"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="template-row-1"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="template-row-2"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="default-badge"]').exists()).toBe(true)
  })

  it('shows the empty-state when the API returns no templates', async () => {
    setupRoutes([
      {
        match: (u) => u.includes('/api/boss/templates/?scenario=reply'),
        handler: () => jsonResponse({ templates: [] }),
      },
    ])

    const wrapper = mount(TemplatesView)
    await flushPromises()

    expect(wrapper.find('[data-testid="empty-templates"]').exists()).toBe(true)
  })

  it('previewing renders text + warnings', async () => {
    setupRoutes([
      {
        match: (u) => u.includes('/api/boss/templates/?scenario=reply'),
        handler: () => jsonResponse({ templates: [] }),
      },
      {
        match: (u) => u.endsWith('/api/boss/templates/preview'),
        handler: () =>
          jsonResponse({ text: 'Hi 李雷 {missing}', warnings: ['missing'] }),
      },
    ])

    const wrapper = mount(TemplatesView)
    await flushPromises()

    await wrapper.find('[data-testid="new-template-content"]').setValue('Hi {name} {missing}')
    await wrapper.find('[data-testid="preview-new-template"]').trigger('click')
    await flushPromises()

    const output = wrapper.find('[data-testid="preview-output"]')
    expect(output.exists()).toBe(true)
    expect(output.text()).toContain('Hi 李雷')
    expect(wrapper.find('[data-testid="preview-warnings"]').text()).toContain('missing')
  })

  it('switching scenario refetches templates', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('scenario=reply')) {
        return jsonResponse({ templates: [template()] })
      }
      if (url.includes('scenario=first_greet')) {
        return jsonResponse({ templates: [template({ id: 99, scenario: 'first_greet' })] })
      }
      return new Response('not mocked', { status: 599 })
    })
    FETCH_GLOBAL.fetch = fetchMock as typeof fetch

    const wrapper = mount(TemplatesView)
    await flushPromises()

    await wrapper.find('[data-testid="scenario-tab-first_greet"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="template-row-99"]').exists()).toBe(true)
    expect(fetchMock.mock.calls.some(([url]) =>
      typeof url === 'string' && url.includes('scenario=first_greet'),
    )).toBe(true)
  })

  it('creates a template and adds it to the list', async () => {
    setupRoutes([
      {
        match: (u, init) => u.includes('/api/boss/templates/?scenario=reply') && (init?.method ?? 'GET') === 'GET',
        handler: () => jsonResponse({ templates: [] }),
      },
      {
        match: (u, init) => u.endsWith('/api/boss/templates/') && init?.method === 'POST',
        handler: () => jsonResponse(template({ id: 5, name: 'fresh' })),
      },
    ])

    const wrapper = mount(TemplatesView)
    await flushPromises()

    await wrapper.find('[data-testid="new-template-name"]').setValue('fresh')
    await wrapper.find('[data-testid="new-template-content"]').setValue('Hi')
    await wrapper.find('[data-testid="create-template"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="template-row-5"]').exists()).toBe(true)
  })
})
