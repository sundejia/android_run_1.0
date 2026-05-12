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

  const defaultContactShare = {
    enabled: false,
    contact_name: '',
    skip_if_already_shared: true,
    cooldown_seconds: 0,
    kefu_overrides: {},
    send_message_before_share: false,
    pre_share_message_text: '',
  }

  const defaultReviewGate = {
    enabled: false,
    video_review_policy: 'extract_frame',
  }

  const defaultAutoBlacklist = {
    enabled: false,
    reason: 'Customer sent media (auto)',
    skip_if_already_blacklisted: true,
    require_review_pass: false,
  }

  const defaultAutoGroupInvite = {
    enabled: false,
    group_members: [] as string[],
    group_name_template: '{customer_name}-服务群',
    skip_if_group_exists: true,
    send_message_before_create: false,
    pre_create_message_text: '',
    send_test_message_after_create: true,
    test_message_text: '测试',
    post_confirm_wait_seconds: 1,
    duplicate_name_policy: 'first',
    video_invite_policy: 'extract_frame',
  }

  describe('getMediaActionSettings', () => {
    it('should fetch settings from the correct endpoint', async () => {
      const expected: MediaAutoActionSettings = {
        enabled: false,
        auto_blacklist: { ...defaultAutoBlacklist },
        auto_group_invite: { ...defaultAutoGroupInvite },
        auto_contact_share: defaultContactShare,
        review_gate: defaultReviewGate,
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
        auto_blacklist: { ...defaultAutoBlacklist },
        auto_group_invite: { ...defaultAutoGroupInvite },
        auto_contact_share: defaultContactShare,
        review_gate: defaultReviewGate,
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
          send_message_before_create: false,
          pre_create_message_text: '',
          send_test_message_after_create: false,
          test_message_text: '您好 {customer_name}',
          post_confirm_wait_seconds: 2,
          duplicate_name_policy: 'first',
        },
      }

      mockFetch.mockResolvedValueOnce(
        mockJsonResponse({
          enabled: true,
          auto_blacklist: { ...defaultAutoBlacklist },
          auto_group_invite: update.auto_group_invite,
          auto_contact_share: defaultContactShare,
          review_gate: defaultReviewGate,
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

    it('should preserve contact share pre-message fields in request body', async () => {
      const update = {
        auto_contact_share: {
          enabled: true,
          contact_name: '主管王',
          skip_if_already_shared: true,
          cooldown_seconds: 0,
          kefu_overrides: {},
          send_message_before_share: true,
          pre_share_message_text: '您好 {customer_name}，这是主管名片',
        },
      }

      mockFetch.mockResolvedValueOnce(
        mockJsonResponse({
          enabled: true,
          auto_blacklist: { ...defaultAutoBlacklist },
          auto_group_invite: {
            ...defaultAutoGroupInvite,
          },
          auto_contact_share: update.auto_contact_share,
          review_gate: defaultReviewGate,
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
        require_review_pass: false,
      },
      auto_group_invite: {
        enabled: true,
        group_members: ['A', 'B'],
        group_name_template: '{customer_name}-群',
        skip_if_group_exists: true,
        send_message_before_create: false,
        pre_create_message_text: '',
        send_test_message_after_create: true,
        test_message_text: '您好 {customer_name}',
        post_confirm_wait_seconds: 1,
        duplicate_name_policy: 'first',
        video_invite_policy: 'extract_frame',
      },
      auto_contact_share: {
        enabled: true,
        contact_name: '主管王',
        skip_if_already_shared: true,
        cooldown_seconds: 0,
        kefu_overrides: {},
        send_message_before_share: true,
        pre_share_message_text: '您好 {customer_name}，这是主管名片',
      },
      review_gate: {
        enabled: true,
        video_review_policy: 'extract_frame',
      },
    }

    expect(settings.enabled).toBe(true)
    expect(settings.auto_blacklist.reason).toBe('test')
    expect(settings.auto_group_invite.group_members).toEqual(['A', 'B'])
    expect(settings.auto_group_invite.test_message_text).toBe('您好 {customer_name}')
    expect(settings.auto_contact_share.pre_share_message_text).toBe('您好 {customer_name}，这是主管名片')
    expect(settings.review_gate.video_review_policy).toBe('extract_frame')
  })
})
