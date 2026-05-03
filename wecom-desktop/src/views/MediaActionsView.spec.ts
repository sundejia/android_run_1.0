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
  },
  review_gate: {
    enabled: true,
    rating_server_url: 'http://127.0.0.1:8080',
    upload_timeout_seconds: 30,
    upload_max_attempts: 3,
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

  it('saves review gate settings', async () => {
    const wrapper = mount(MediaActionsView)
    await flushPromises()

    await wrapper.get('#media-review-server-url').setValue('http://review.local:8080')
    await wrapper.get('#media-review-upload-timeout').setValue(45)
    await wrapper.get('#media-review-upload-attempts').setValue(2)
    await wrapper.get('#media-video-review-policy').setValue('extract_frame')
    await wrapper.get('#save-media-action-settings').trigger('click')
    await flushPromises()

    expect(updateMediaActionSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        review_gate: expect.objectContaining({
          enabled: true,
          rating_server_url: 'http://review.local:8080',
          upload_timeout_seconds: 45,
          upload_max_attempts: 2,
          video_review_policy: 'extract_frame',
        }),
      })
    )
  })
})
