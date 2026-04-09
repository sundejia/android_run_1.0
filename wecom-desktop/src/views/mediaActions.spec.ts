/**
 * Media Auto-Actions API integration tests
 *
 * Tests the API client methods for media auto-actions.
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import type { MediaAutoActionSettings } from '../services/api'

const mockFetch = vi.fn()
global.fetch = mockFetch

describe('Media Actions API', () => {
  beforeEach(() => {
    mockFetch.mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  function mockJsonResponse(data: any, status = 200) {
    return {
      ok: status >= 200 && status < 300,
      status,
      json: () => Promise.resolve(data),
    }
  }

  describe('getMediaActionSettings', () => {
    it('should fetch settings from the correct endpoint', async () => {
      const expected: MediaAutoActionSettings = {
        enabled: false,
        auto_blacklist: {
          enabled: false,
          reason: 'Customer sent media (auto)',
          skip_if_already_blacklisted: true,
        },
        auto_group_invite: {
          enabled: false,
          group_members: [],
          group_name_template: '{customer_name}-服务群',
          skip_if_group_exists: true,
          send_test_message_after_create: true,
          test_message_text: '测试',
          post_confirm_wait_seconds: 1,
          duplicate_name_policy: 'first',
        },
      }

      mockFetch.mockResolvedValueOnce(mockJsonResponse(expected))

      const { api } = await import('../services/api')
      const result = await api.getMediaActionSettings()

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/media-actions/settings'),
        expect.objectContaining({
          headers: expect.objectContaining({
            'Content-Type': 'application/json',
          }),
        })
      )
      expect(result).toEqual(expected)
    })
  })

  describe('updateMediaActionSettings', () => {
    it('should send PUT request with settings', async () => {
      const update = { enabled: true }
      const response: MediaAutoActionSettings = {
        enabled: true,
        auto_blacklist: {
          enabled: false,
          reason: 'Customer sent media (auto)',
          skip_if_already_blacklisted: true,
        },
        auto_group_invite: {
          enabled: false,
          group_members: [],
          group_name_template: '{customer_name}-服务群',
          skip_if_group_exists: true,
          send_test_message_after_create: true,
          test_message_text: '测试',
          post_confirm_wait_seconds: 1,
          duplicate_name_policy: 'first',
        },
      }

      mockFetch.mockResolvedValueOnce(mockJsonResponse(response))

      const { api } = await import('../services/api')
      const result = await api.updateMediaActionSettings(update)

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/media-actions/settings'),
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify(update),
        })
      )
      expect(result.enabled).toBe(true)
    })

    it('should preserve custom group message fields in request body', async () => {
      const update = {
        auto_group_invite: {
          enabled: true,
          group_members: ['A'],
          group_name_template: '{customer_name}-群',
          skip_if_group_exists: true,
          send_test_message_after_create: false,
          test_message_text: '您好 {customer_name}',
          post_confirm_wait_seconds: 2,
          duplicate_name_policy: 'first',
        },
      }

      mockFetch.mockResolvedValueOnce(
        mockJsonResponse({
          enabled: true,
          auto_blacklist: {
            enabled: false,
            reason: 'Customer sent media (auto)',
            skip_if_already_blacklisted: true,
          },
          auto_group_invite: update.auto_group_invite,
        })
      )

      const { api } = await import('../services/api')
      await api.updateMediaActionSettings(update)

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/media-actions/settings'),
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify(update),
        })
      )
    })
  })

  describe('testTriggerMediaAction', () => {
    it('should send POST with query params', async () => {
      const response = {
        status: 'ok',
        results: [{ action_name: 'auto_blacklist', status: 'skipped', message: 'Disabled' }],
      }

      mockFetch.mockResolvedValueOnce(mockJsonResponse(response))

      const { api } = await import('../services/api')
      const result = await api.testTriggerMediaAction({
        device_serial: 'dev1',
        customer_name: '测试',
        message_type: 'image',
      })

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/media-actions/test-trigger'),
        expect.objectContaining({ method: 'POST' })
      )
      expect(result.status).toBe('ok')
      expect(result.results).toHaveLength(1)
    })
  })

  describe('getMediaActionLogs', () => {
    it('should fetch logs with optional params', async () => {
      const response = { logs: [], total: 0 }

      mockFetch.mockResolvedValueOnce(mockJsonResponse(response))

      const { api } = await import('../services/api')
      const result = await api.getMediaActionLogs({ limit: 10 })

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/media-actions/logs'),
        expect.any(Object)
      )
      expect(result.logs).toEqual([])
    })
  })
})

describe('MediaAutoActionSettings type', () => {
  it('should have correct structure', () => {
    const settings: MediaAutoActionSettings = {
      enabled: true,
      auto_blacklist: {
        enabled: true,
        reason: 'test',
        skip_if_already_blacklisted: false,
      },
      auto_group_invite: {
        enabled: true,
        group_members: ['A', 'B'],
        group_name_template: '{customer_name}-群',
        skip_if_group_exists: true,
        send_test_message_after_create: true,
        test_message_text: '您好 {customer_name}',
        post_confirm_wait_seconds: 1,
        duplicate_name_policy: 'first',
      },
    }

    expect(settings.enabled).toBe(true)
    expect(settings.auto_blacklist.reason).toBe('test')
    expect(settings.auto_group_invite.group_members).toEqual(['A', 'B'])
    expect(settings.auto_group_invite.test_message_text).toBe('您好 {customer_name}')
  })
})
