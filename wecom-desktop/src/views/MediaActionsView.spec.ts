// @vitest-environment jsdom

import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MediaActionsView from './MediaActionsView.vue'

const { getMediaActionSettings, updateMediaActionSettings, testTriggerMediaAction } = vi.hoisted(
  () => ({
    getMediaActionSettings: vi.fn(),
    updateMediaActionSettings: vi.fn(),
    testTriggerMediaAction: vi.fn(),
  })
)

vi.mock('../services/api', () => ({
  api: {
    getMediaActionSettings,
    updateMediaActionSettings,
    testTriggerMediaAction,
  },
}))

vi.mock('../composables/useI18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
}))

const baseSettings = {
  enabled: true,
  auto_blacklist: {
    enabled: false,
    reason: 'Customer sent media (auto)',
    skip_if_already_blacklisted: true,
  },
  auto_group_invite: {
    enabled: true,
    group_members: ['经理A'],
    group_name_template: '{customer_name}-服务群',
    skip_if_group_exists: true,
    send_test_message_after_create: true,
    test_message_text: '您好 {customer_name}，我是 {kefu_name}',
    post_confirm_wait_seconds: 1,
    duplicate_name_policy: 'first',
    video_invite_policy: 'extract_frame',
  },
  auto_contact_share: {
    enabled: false,
    contact_name: '',
    skip_if_already_shared: true,
    cooldown_seconds: 0,
    kefu_overrides: {},
    send_message_before_share: false,
    pre_share_message_text: '',
  },
  review_gate: {
    enabled: true,
    video_review_policy: 'extract_frame',
  },
}

describe('MediaActionsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getMediaActionSettings.mockResolvedValue(structuredClone(baseSettings))
    updateMediaActionSettings.mockImplementation(async (payload) => payload)
    testTriggerMediaAction.mockResolvedValue({ results: [] })
  })

  it('shows custom group message controls and preview', async () => {
    const wrapper = mount(MediaActionsView)
    await flushPromises()

    expect(wrapper.find('#send-group-message-after-create').exists()).toBe(true)
    expect(wrapper.find('#group-test-message-template').exists()).toBe(true)
    expect(wrapper.get('#group-test-message-preview').text()).toContain('测试客户')
    expect(wrapper.get('#group-test-message-preview').text()).toContain('客服A')
  })

  it('saves custom group message settings', async () => {
    const wrapper = mount(MediaActionsView)
    await flushPromises()

    await wrapper.get('#send-group-message-after-create').setValue(false)
    await wrapper.get('#group-test-message-template').setValue('欢迎 {customer_name}')
    await wrapper.get('#save-media-action-settings').trigger('click')
    await flushPromises()

    expect(updateMediaActionSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        auto_group_invite: expect.objectContaining({
          send_test_message_after_create: false,
          test_message_text: '欢迎 {customer_name}',
        }),
      })
    )
  })

  it('shows contact share pre-message controls and preview', async () => {
    getMediaActionSettings.mockResolvedValueOnce({
      ...structuredClone(baseSettings),
      auto_contact_share: {
        ...baseSettings.auto_contact_share,
        enabled: true,
        pre_share_message_text: '您好 {customer_name}，我是 {kefu_name}',
      },
    })

    const wrapper = mount(MediaActionsView)
    await flushPromises()

    expect(wrapper.find('#send-message-before-contact-share').exists()).toBe(true)
    expect(wrapper.find('#contact-share-message-template').exists()).toBe(true)
    expect(wrapper.get('#contact-share-message-preview').text()).toContain('测试客户')
    expect(wrapper.get('#contact-share-message-preview').text()).toContain('客服A')
  })

  it('saves contact share pre-message settings', async () => {
    getMediaActionSettings.mockResolvedValueOnce({
      ...structuredClone(baseSettings),
      auto_contact_share: {
        ...baseSettings.auto_contact_share,
        enabled: true,
      },
    })

    const wrapper = mount(MediaActionsView)
    await flushPromises()

    await wrapper.get('#send-message-before-contact-share').setValue(true)
    await wrapper.get('#contact-share-message-template').setValue('您好 {customer_name}，这是主管名片')
    await wrapper.get('#save-media-action-settings').trigger('click')
    await flushPromises()

    expect(updateMediaActionSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        auto_contact_share: expect.objectContaining({
          send_message_before_share: true,
          pre_share_message_text: '您好 {customer_name}，这是主管名片',
        }),
      })
    )
  })

  it('saves review gate settings (URL/timeout removed in 2026-05-12 dedup)', async () => {
    const wrapper = mount(MediaActionsView)
    await flushPromises()

    await wrapper.get('#media-video-review-policy').setValue('skip')
    await wrapper.get('#save-media-action-settings').trigger('click')
    await flushPromises()

    expect(updateMediaActionSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        review_gate: expect.objectContaining({
          enabled: true,
          video_review_policy: 'skip',
        }),
      })
    )
    // Legacy URL/timeout/attempts inputs no longer exist on the page.
    expect(wrapper.find('#media-review-server-url').exists()).toBe(false)
    expect(wrapper.find('#media-review-upload-timeout').exists()).toBe(false)
    expect(wrapper.find('#media-review-upload-attempts').exists()).toBe(false)
    // The page must point users at the unified settings location instead.
    expect(wrapper.find('#media-review-server-config-hint').exists()).toBe(true)
  })
})
