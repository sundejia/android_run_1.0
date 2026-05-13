<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../services/api'
import type { MediaAutoActionSettings } from '../services/api'
import { useI18n } from '../composables/useI18n'
import { renderMediaActionTemplate } from '../utils/mediaActionTemplates'
import { useDeviceProfilesStore } from '../stores/deviceProfiles'

const { t } = useI18n()
const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const reachabilityTesting = ref(false)
const reachabilityResult = ref<{ reachable: boolean; message: string } | null>(null)
const toast = ref<{ message: string; type: 'success' | 'error' } | null>(null)

const deviceProfilesStore = useDeviceProfilesStore()

// Per-device profile editing state
const editingDeviceSerial = ref<string | null>(null)
const editingGroupInvite = ref({ enabled: true, group_members: [] as string[], group_name_template: '{customer_name}-{kefu_name}服务群' })
const editingContactShare = ref({ enabled: true, contact_name: '' })
const newProfileMember = ref('')

// Tiny "all-off" placeholder shape used purely as a typed initialiser before
// the API responds. We deliberately avoid maintaining a frontend-side copy of
// real default values — those live in the backend (single source of truth at
// `settings_loader.DEFAULT_MEDIA_AUTO_ACTION_SETTINGS`). Duplicating them here
// was the entry point for the 2026-05-12 dedup bug.
function createPlaceholderSettings(): MediaAutoActionSettings {
  return {
    enabled: false,
    auto_blacklist: {
      enabled: false,
      reason: '',
      skip_if_already_blacklisted: true,
      require_review_pass: false,
    },
    auto_group_invite: {
      enabled: false,
      group_members: [],
      group_name_template: '',
      skip_if_group_exists: true,
      send_message_before_create: false,
      pre_create_message_text: '',
      send_test_message_after_create: true,
      test_message_text: '',
      post_confirm_wait_seconds: 1,
      duplicate_name_policy: 'first',
      video_invite_policy: 'extract_frame',
    },
    auto_contact_share: {
      enabled: false,
      contact_name: '',
      skip_if_already_shared: true,
      cooldown_seconds: 0,
      send_message_before_share: false,
      pre_share_message_text: '',
    },
    review_gate: {
      enabled: false,
      video_review_policy: 'extract_frame',
    },
  }
}

const settings = ref<MediaAutoActionSettings>(createPlaceholderSettings())

const newMember = ref('')
const testCustomerName = ref('测试客户')
const testDeviceSerial = ref('test_device')
const testMessageType = ref<'image' | 'video'>('image')
const testResults = ref<Array<{ action_name: string; status: string; message: string }>>([])
const previewKefuName = '客服A'

const groupMessagePreview = computed(() =>
  renderMediaActionTemplate(settings.value.auto_group_invite.test_message_text, {
    customer_name: testCustomerName.value.trim() || '测试客户',
    kefu_name: previewKefuName,
    device_serial: testDeviceSerial.value.trim() || 'test_device',
  })
)

const contactShareMessagePreview = computed(() =>
  renderMediaActionTemplate(settings.value.auto_contact_share.pre_share_message_text, {
    customer_name: testCustomerName.value.trim() || '测试客户',
    kefu_name: previewKefuName,
    device_serial: testDeviceSerial.value.trim() || 'test_device',
  })
)

const groupPreCreateMessagePreview = computed(() =>
  renderMediaActionTemplate(settings.value.auto_group_invite.pre_create_message_text, {
    customer_name: testCustomerName.value.trim() || '测试客户',
    kefu_name: previewKefuName,
    device_serial: testDeviceSerial.value.trim() || 'test_device',
  })
)

function showToast(message: string, type: 'success' | 'error' = 'success') {
  toast.value = { message, type }
  setTimeout(() => {
    toast.value = null
  }, 3000)
}

async function loadSettings() {
  loading.value = true
  try {
    // Backend already merges DB rows over DEFAULT_MEDIA_AUTO_ACTION_SETTINGS
    // (single source of truth in python core), so the response should be
    // a complete shape. We still defensively merge over the placeholder
    // skeleton so a partial mock or in-flight schema migration never
    // leaves the template with undefined values to .replace() on.
    const loaded = await api.getMediaActionSettings()
    const placeholder = createPlaceholderSettings()
    settings.value = {
      ...placeholder,
      ...loaded,
      auto_blacklist: { ...placeholder.auto_blacklist, ...loaded.auto_blacklist },
      auto_group_invite: { ...placeholder.auto_group_invite, ...loaded.auto_group_invite },
      auto_contact_share: { ...placeholder.auto_contact_share, ...loaded.auto_contact_share },
      review_gate: { ...placeholder.review_gate, ...loaded.review_gate },
    }
    // Also load device profiles
    await deviceProfilesStore.fetchProfiles()
  } catch (err: any) {
    showToast(err.message || t('media_actions.load_failed'), 'error')
  } finally {
    loading.value = false
  }
}

async function saveSettings() {
  saving.value = true
  try {
    settings.value = await api.updateMediaActionSettings(settings.value)
    showToast(t('media_actions.save_success'))
  } catch (err: any) {
    showToast(err.message || t('media_actions.save_failed'), 'error')
  } finally {
    saving.value = false
  }
}

function addMember() {
  const name = newMember.value.trim()
  if (name && !settings.value.auto_group_invite.group_members.includes(name)) {
    settings.value.auto_group_invite.group_members.push(name)
    newMember.value = ''
  }
}

// --- Per-Device Profile Management ---

function startEditDevice(deviceSerial: string) {
  editingDeviceSerial.value = deviceSerial
  const groupAction = deviceProfilesStore.selectedDeviceActions.find(a => a.action_type === 'auto_group_invite')
  const contactAction = deviceProfilesStore.selectedDeviceActions.find(a => a.action_type === 'auto_contact_share')

  editingGroupInvite.value = {
    enabled: groupAction?.enabled ?? true,
    group_members: (groupAction?.config?.group_members as string[]) || [],
    group_name_template: (groupAction?.config?.group_name_template as string) || '{customer_name}-{kefu_name}服务群',
  }
  editingContactShare.value = {
    enabled: contactAction?.enabled ?? true,
    contact_name: (contactAction?.config?.contact_name as string) || '',
  }
  newProfileMember.value = ''
}

function addProfileMember() {
  const name = newProfileMember.value.trim()
  if (name && !editingGroupInvite.value.group_members.includes(name)) {
    editingGroupInvite.value.group_members.push(name)
    newProfileMember.value = ''
  }
}

function removeProfileMember(index: number) {
  editingGroupInvite.value.group_members.splice(index, 1)
}

async function saveDeviceProfile() {
  if (!editingDeviceSerial.value) return
  try {
    if (editingGroupInvite.value.group_members.length > 0) {
      await deviceProfilesStore.saveDeviceAction(editingDeviceSerial.value, 'auto_group_invite', {
        enabled: editingGroupInvite.value.enabled,
        config: {
          group_members: editingGroupInvite.value.group_members,
          group_name_template: editingGroupInvite.value.group_name_template,
        },
      })
    }
    if (editingContactShare.value.contact_name) {
      await deviceProfilesStore.saveDeviceAction(editingDeviceSerial.value, 'auto_contact_share', {
        enabled: editingContactShare.value.enabled,
        config: { contact_name: editingContactShare.value.contact_name },
      })
    }
    showToast('设备专属配置已保存')
  } catch (e: any) {
    showToast(e.message || '保存失败', 'error')
  }
}

async function deleteDeviceProfile(actionType: string) {
  if (!editingDeviceSerial.value) return
  try {
    await deviceProfilesStore.deleteDeviceAction(editingDeviceSerial.value, actionType)
    showToast('已重置为全局默认')
  } catch (e: any) {
    showToast(e.message || '删除失败', 'error')
  }
}

function cancelEditDevice() {
  editingDeviceSerial.value = null
}

function removeMember(index: number) {
  settings.value.auto_group_invite.group_members.splice(index, 1)
}

async function testContactReachability() {
  const contactName = settings.value.auto_contact_share.contact_name.trim()
  const serial = testDeviceSerial.value.trim()
  if (!serial) {
    reachabilityResult.value = {
      reachable: false,
      message: t('media_actions.test_contact_reachability_no_device'),
    }
    return
  }
  reachabilityTesting.value = true
  reachabilityResult.value = null
  try {
    const res = await api.testContactReachability({
      device_serial: serial,
      contact_name: contactName,
    })
    reachabilityResult.value = {
      reachable: res.reachable,
      message: res.reachable
        ? t('media_actions.test_contact_reachability_success')
        : res.message || t('media_actions.test_contact_reachability_failure'),
    }
  } catch (err: any) {
    reachabilityResult.value = {
      reachable: false,
      message: err.message || t('media_actions.test_contact_reachability_failure'),
    }
  } finally {
    reachabilityTesting.value = false
  }
}

async function runTest() {
  testing.value = true
  testResults.value = []
  try {
    const res = await api.testTriggerMediaAction({
      device_serial: testDeviceSerial.value,
      customer_name: testCustomerName.value,
      message_type: testMessageType.value,
    })
    testResults.value = res.results
    showToast(t('media_actions.test_success'))
  } catch (err: any) {
    showToast(err.message || t('media_actions.test_failed'), 'error')
  } finally {
    testing.value = false
  }
}

onMounted(loadSettings)

// Periodically refresh device profiles so newly connected phones appear
let _profileRefreshTimer: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  _profileRefreshTimer = setInterval(() => {
    if (!loading.value) {
      deviceProfilesStore.fetchProfiles()
    }
  }, 10000)
})
onUnmounted(() => {
  if (_profileRefreshTimer) clearInterval(_profileRefreshTimer)
})
</script>

<template>
  <div class="p-6 max-w-4xl mx-auto">
    <!-- Toast -->
    <Transition name="fade">
      <div
        v-if="toast"
        :class="[
          'fixed top-4 right-4 z-50 px-4 py-2 rounded-lg shadow-lg text-sm font-medium',
          toast.type === 'success' ? 'bg-green-600 text-white' : 'bg-red-600 text-white',
        ]"
      >
        {{ toast.message }}
      </div>
    </Transition>

    <!-- Header -->
    <div class="mb-6">
      <h1 class="text-2xl font-bold text-gray-100">{{ t('media_actions.title') }}</h1>
      <p class="text-sm text-gray-400 mt-1">
        {{ t('media_actions.subtitle') }}
      </p>
    </div>

    <div v-if="loading" class="flex items-center justify-center py-20">
      <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
    </div>

    <div v-else class="space-y-6">
      <!-- Global Toggle -->
      <div class="bg-wecom-darker rounded-lg p-5 border border-wecom-border">
        <div class="flex items-center justify-between">
          <div>
            <h2 class="text-lg font-semibold text-gray-100">
              {{ t('media_actions.enable_title') }}
            </h2>
            <p class="text-sm text-gray-400 mt-1">
              {{ t('media_actions.enable_desc') }}
            </p>
          </div>
          <label class="relative inline-flex items-center cursor-pointer">
            <input v-model="settings.enabled" type="checkbox" class="sr-only peer" />
            <div
              class="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"
            ></div>
          </label>
        </div>
      </div>

      <!-- Review Gate Section -->
      <div
        class="bg-wecom-darker rounded-lg p-5 border border-wecom-border"
        :class="{ 'opacity-50': !settings.enabled }"
      >
        <div class="flex items-center justify-between mb-4">
          <div>
            <h2 class="text-lg font-semibold text-gray-100">
              {{ t('media_actions.review_gate_title') }}
            </h2>
            <p class="text-sm text-gray-400 mt-1">
              {{ t('media_actions.review_gate_desc') }}
            </p>
          </div>
          <label class="relative inline-flex items-center cursor-pointer">
            <input
              id="media-review-gate-enabled"
              v-model="settings.review_gate.enabled"
              type="checkbox"
              :disabled="!settings.enabled"
              class="sr-only peer"
            />
            <div
              class="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600 peer-disabled:opacity-50"
            ></div>
          </label>
        </div>

        <div v-if="settings.review_gate.enabled && settings.enabled" class="space-y-4">
          <div
            id="media-review-server-config-hint"
            class="rounded-md border border-blue-500/40 bg-blue-500/10 px-3 py-2 text-xs text-blue-200"
          >
            {{ t('media_actions.review_server_config_hint') }}
          </div>

          <div>
            <label for="media-video-review-policy" class="block text-sm font-medium text-gray-300 mb-1">
              {{ t('media_actions.video_review_policy_label') }}
            </label>
            <select
              id="media-video-review-policy"
              v-model="settings.review_gate.video_review_policy"
              class="w-full bg-gray-700 border border-gray-600 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="extract_frame">{{ t('media_actions.video_review_extract_frame') }}</option>
              <option value="skip">{{ t('media_actions.video_review_skip') }}</option>
              <option value="always">{{ t('media_actions.video_review_always') }}</option>
            </select>
            <p class="text-xs text-gray-500 mt-1">
              {{ t('media_actions.review_gate_hint') }}
            </p>
          </div>
        </div>
      </div>

      <!-- Auto Blacklist Section -->
      <div
        class="bg-wecom-darker rounded-lg p-5 border border-wecom-border"
        :class="{ 'opacity-50': !settings.enabled }"
      >
        <div class="flex items-center justify-between mb-4">
          <div>
            <h2 class="text-lg font-semibold text-gray-100">
              {{ t('media_actions.auto_blacklist') }}
            </h2>
            <p class="text-sm text-gray-400 mt-1">
              {{ t('media_actions.auto_blacklist_desc') }}
            </p>
          </div>
          <label class="relative inline-flex items-center cursor-pointer">
            <input
              v-model="settings.auto_blacklist.enabled"
              type="checkbox"
              :disabled="!settings.enabled"
              class="sr-only peer"
            />
            <div
              class="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600 peer-disabled:opacity-50"
            ></div>
          </label>
        </div>

        <div v-if="settings.auto_blacklist.enabled && settings.enabled" class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">{{
              t('media_actions.blacklist_reason_label')
            }}</label>
            <input
              v-model="settings.auto_blacklist.reason"
              type="text"
              class="w-full bg-gray-700 border border-gray-600 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
              :placeholder="t('media_actions.blacklist_reason_placeholder')"
            />
          </div>

          <div class="flex items-center gap-2">
            <input
              id="skip-blacklisted"
              v-model="settings.auto_blacklist.skip_if_already_blacklisted"
              type="checkbox"
              class="rounded border-gray-600 bg-gray-700 text-blue-600 focus:ring-blue-500"
            />
            <label for="skip-blacklisted" class="text-sm text-gray-300">
              {{ t('media_actions.skip_already_blacklisted') }}
            </label>
          </div>
        </div>
      </div>

      <!-- Auto Group Invite Section -->
      <div
        class="bg-wecom-darker rounded-lg p-5 border border-wecom-border"
        :class="{ 'opacity-50': !settings.enabled }"
      >
        <div class="flex items-center justify-between mb-4">
          <div>
            <h2 class="text-lg font-semibold text-gray-100">
              {{ t('media_actions.auto_group_invite') }}
            </h2>
            <p class="text-sm text-gray-400 mt-1">
              {{ t('media_actions.auto_group_invite_desc') }}
            </p>
          </div>
          <label class="relative inline-flex items-center cursor-pointer">
            <input
              v-model="settings.auto_group_invite.enabled"
              type="checkbox"
              :disabled="!settings.enabled"
              class="sr-only peer"
            />
            <div
              class="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600 peer-disabled:opacity-50"
            ></div>
          </label>
        </div>

        <div v-if="settings.auto_group_invite.enabled && settings.enabled" class="space-y-4">
          <!-- Group Members -->
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-2">{{
              t('media_actions.group_members_label')
            }}</label>
            <div class="flex flex-wrap gap-2 mb-2">
              <span
                v-for="(member, idx) in settings.auto_group_invite.group_members"
                :key="idx"
                class="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-blue-600/20 text-blue-300 text-sm border border-blue-600/30"
              >
                {{ member }}
                <button
                  class="ml-1 text-blue-400 hover:text-red-400 transition-colors"
                  @click="removeMember(idx)"
                >
                  &times;
                </button>
              </span>
              <span
                v-if="settings.auto_group_invite.group_members.length === 0"
                class="text-sm text-gray-500 italic"
              >
                {{ t('media_actions.no_members') }}
              </span>
            </div>
            <div class="flex gap-2">
              <input
                v-model="newMember"
                type="text"
                class="flex-1 bg-gray-700 border border-gray-600 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
                :placeholder="t('media_actions.member_placeholder')"
                @keyup.enter="addMember"
              />
              <button
                class="px-4 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700 transition-colors"
                @click="addMember"
              >
                {{ t('media_actions.add') }}
              </button>
            </div>
          </div>

          <!-- Group Name Template -->
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">{{
              t('media_actions.group_name_template_label')
            }}</label>
            <input
              v-model="settings.auto_group_invite.group_name_template"
              type="text"
              class="w-full bg-gray-700 border border-gray-600 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
              :placeholder="t('media_actions.group_name_template_placeholder')"
            />
            <p class="text-xs text-gray-500 mt-1">
              {{ t('media_actions.group_name_template_hint') }}
            </p>
          </div>

          <div class="space-y-3 rounded-lg border border-gray-700/80 bg-gray-800/40 p-4">
            <div class="flex items-center gap-2">
              <input
                id="send-message-before-group-create"
                v-model="settings.auto_group_invite.send_message_before_create"
                type="checkbox"
                class="rounded border-gray-600 bg-gray-700 text-blue-600 focus:ring-blue-500"
              />
              <label for="send-message-before-group-create" class="text-sm text-gray-300">
                {{ t('media_actions.send_message_before_group_create') }}
              </label>
            </div>

            <div>
              <label
                for="group-pre-create-message-template"
                class="block text-sm font-medium text-gray-300 mb-1"
              >
                {{ t('media_actions.group_pre_create_message_text_label') }}
              </label>
              <textarea
                id="group-pre-create-message-template"
                v-model="settings.auto_group_invite.pre_create_message_text"
                rows="4"
                class="w-full bg-gray-700 border border-gray-600 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
                :placeholder="t('media_actions.group_pre_create_message_text_placeholder')"
              ></textarea>
              <p class="text-xs text-gray-500 mt-1">
                {{ t('media_actions.group_pre_create_message_text_hint') }}
              </p>
            </div>

            <div>
              <div class="text-xs font-medium uppercase tracking-wide text-gray-400">
                {{ t('media_actions.test_message_preview_label') }}
              </div>
              <div
                id="group-pre-create-message-preview"
                class="mt-2 whitespace-pre-wrap rounded-md border border-gray-700 bg-gray-900/60 px-3 py-2 text-sm text-gray-200"
              >
                {{ groupPreCreateMessagePreview }}
              </div>
              <p class="text-xs text-gray-500 mt-1">
                {{ t('media_actions.test_message_preview_hint') }}
              </p>
            </div>
          </div>

          <div class="space-y-3 rounded-lg border border-gray-700/80 bg-gray-800/40 p-4">
            <div class="flex items-center gap-2">
              <input
                id="send-group-message-after-create"
                v-model="settings.auto_group_invite.send_test_message_after_create"
                type="checkbox"
                class="rounded border-gray-600 bg-gray-700 text-blue-600 focus:ring-blue-500"
              />
              <label for="send-group-message-after-create" class="text-sm text-gray-300">
                {{ t('media_actions.send_group_message_after_create') }}
              </label>
            </div>

            <div>
              <label
                for="group-test-message-template"
                class="block text-sm font-medium text-gray-300 mb-1"
              >
                {{ t('media_actions.test_message_text_label') }}
              </label>
              <textarea
                id="group-test-message-template"
                v-model="settings.auto_group_invite.test_message_text"
                rows="4"
                class="w-full bg-gray-700 border border-gray-600 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
                :placeholder="t('media_actions.test_message_text_placeholder')"
              ></textarea>
              <p class="text-xs text-gray-500 mt-1">
                {{ t('media_actions.test_message_text_hint') }}
              </p>
            </div>

            <div>
              <div class="text-xs font-medium uppercase tracking-wide text-gray-400">
                {{ t('media_actions.test_message_preview_label') }}
              </div>
              <div
                id="group-test-message-preview"
                class="mt-2 whitespace-pre-wrap rounded-md border border-gray-700 bg-gray-900/60 px-3 py-2 text-sm text-gray-200"
              >
                {{ groupMessagePreview }}
              </div>
              <p class="text-xs text-gray-500 mt-1">
                {{ t('media_actions.test_message_preview_hint') }}
              </p>
            </div>
          </div>

          <div class="flex items-center gap-2">
            <input
              id="skip-group-exists"
              v-model="settings.auto_group_invite.skip_if_group_exists"
              type="checkbox"
              class="rounded border-gray-600 bg-gray-700 text-blue-600 focus:ring-blue-500"
            />
            <label for="skip-group-exists" class="text-sm text-gray-300">
              {{ t('media_actions.skip_group_exists') }}
            </label>
          </div>
        </div>
      </div>

      <!-- Auto Contact Share Section -->
      <div
        class="bg-wecom-darker rounded-lg p-5 border border-wecom-border"
        :class="{ 'opacity-50': !settings.enabled }"
      >
        <div class="flex items-center justify-between mb-4">
          <div>
            <h2 class="text-lg font-semibold text-gray-100">
              {{ t('media_actions.auto_contact_share') }}
            </h2>
            <p class="text-sm text-gray-400 mt-1">
              {{ t('media_actions.auto_contact_share_desc') }}
            </p>
          </div>
          <label class="relative inline-flex items-center cursor-pointer">
            <input
              v-model="settings.auto_contact_share.enabled"
              type="checkbox"
              :disabled="!settings.enabled"
              class="sr-only peer"
            />
            <div
              class="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600 peer-disabled:opacity-50"
            ></div>
          </label>
        </div>

        <div v-if="settings.auto_contact_share.enabled && settings.enabled" class="space-y-4">
          <!-- Contact Name -->
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">{{
              t('media_actions.contact_name_label')
            }}</label>
            <input
              v-model="settings.auto_contact_share.contact_name"
              type="text"
              class="w-full bg-gray-700 border border-gray-600 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
              :placeholder="t('media_actions.contact_name_placeholder')"
            />
            <p class="text-xs text-amber-400 mt-1">
              {{ t('media_actions.contact_name_hint') }}
            </p>
            <div class="flex items-center gap-3 mt-2">
              <button
                id="test-contact-reachability"
                :disabled="
                  reachabilityTesting ||
                  !settings.auto_contact_share.contact_name.trim() ||
                  !testDeviceSerial.trim()
                "
                class="px-3 py-1.5 bg-amber-600 text-white text-xs font-medium rounded-md hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                @click="testContactReachability"
              >
                {{
                  reachabilityTesting
                    ? t('media_actions.testing_contact_reachability')
                    : t('media_actions.test_contact_reachability')
                }}
              </button>
              <span
                v-if="reachabilityResult"
                :class="[
                  'text-xs',
                  reachabilityResult.reachable ? 'text-green-400' : 'text-red-400',
                ]"
              >
                {{ reachabilityResult.message }}
              </span>
            </div>
            <p class="text-xs text-gray-500 mt-1">
              {{ t('media_actions.test_contact_reachability_hint') }}
            </p>
          </div>

          <div class="space-y-3 rounded-lg border border-gray-700/80 bg-gray-800/40 p-4">
            <div class="flex items-center gap-2">
              <input
                id="send-message-before-contact-share"
                v-model="settings.auto_contact_share.send_message_before_share"
                type="checkbox"
                class="rounded border-gray-600 bg-gray-700 text-blue-600 focus:ring-blue-500"
              />
              <label for="send-message-before-contact-share" class="text-sm text-gray-300">
                {{ t('media_actions.send_message_before_contact_share') }}
              </label>
            </div>

            <div>
              <label
                for="contact-share-message-template"
                class="block text-sm font-medium text-gray-300 mb-1"
              >
                {{ t('media_actions.contact_share_message_text_label') }}
              </label>
              <textarea
                id="contact-share-message-template"
                v-model="settings.auto_contact_share.pre_share_message_text"
                rows="4"
                class="w-full bg-gray-700 border border-gray-600 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
                :placeholder="t('media_actions.contact_share_message_text_placeholder')"
              ></textarea>
              <p class="text-xs text-gray-500 mt-1">
                {{ t('media_actions.contact_share_message_text_hint') }}
              </p>
            </div>

            <div>
              <div class="text-xs font-medium uppercase tracking-wide text-gray-400">
                {{ t('media_actions.test_message_preview_label') }}
              </div>
              <div
                id="contact-share-message-preview"
                class="mt-2 whitespace-pre-wrap rounded-md border border-gray-700 bg-gray-900/60 px-3 py-2 text-sm text-gray-200"
              >
                {{ contactShareMessagePreview }}
              </div>
              <p class="text-xs text-gray-500 mt-1">
                {{ t('media_actions.contact_share_message_preview_hint') }}
              </p>
            </div>
          </div>

          <div class="flex items-center gap-2">
            <input
              id="skip-already-shared"
              v-model="settings.auto_contact_share.skip_if_already_shared"
              type="checkbox"
              class="rounded border-gray-600 bg-gray-700 text-blue-600 focus:ring-blue-500"
            />
            <label for="skip-already-shared" class="text-sm text-gray-300">
              {{ t('media_actions.skip_already_shared') }}
            </label>
          </div>
        </div>
      </div>

      <!-- Per-Device Override Section -->
      <div
        class="bg-wecom-darker rounded-lg p-5 border border-wecom-border"
        :class="{ 'opacity-50': !settings.enabled }"
      >
        <div class="flex items-center justify-between mb-4">
          <div>
            <h2 class="text-lg font-semibold text-gray-100">
              按设备覆盖配置
            </h2>
            <p class="text-sm text-gray-400 mt-1">
              每个设备(手机)可以有独立的拉群和发名片配置。未配置的设备使用上方全局默认。
            </p>
          </div>
        </div>

        <!-- Device selector -->
        <div v-if="deviceProfilesStore.profiles.length > 0" class="space-y-4">
          <div class="flex flex-wrap gap-2">
            <button
              v-for="device in deviceProfilesStore.profiles"
              :key="device.device_serial"
              class="px-3 py-1.5 rounded-lg text-sm font-medium transition-colors border"
              :class="[
                editingDeviceSerial === device.device_serial
                  ? 'bg-blue-600 text-white border-blue-500'
                  : device.has_group_invite_override || device.has_contact_share_override
                    ? 'bg-green-600/20 text-green-300 border-green-600/40 hover:bg-green-600/30'
                    : 'bg-gray-700 text-gray-300 border-gray-600 hover:bg-gray-600'
              ]"
              @click="deviceProfilesStore.selectDevice(device.device_serial); startEditDevice(device.device_serial)"
            >
              {{ device.model || device.device_serial }}
              <span class="ml-1 text-xs text-gray-400">({{ device.device_serial }})</span>
              <span v-if="device.has_group_invite_override || device.has_contact_share_override" class="ml-1 text-xs">(已配置)</span>
            </button>
          </div>

          <!-- Edit panel -->
          <div v-if="editingDeviceSerial" class="bg-gray-800/50 rounded-lg p-4 space-y-4 border border-gray-700">
            <div class="flex items-center justify-between">
              <h3 class="text-md font-semibold text-gray-200">
                {{ deviceProfilesStore.profiles.find(d => d.device_serial === editingDeviceSerial)?.model || editingDeviceSerial }} 的专属配置
              </h3>
              <button
                class="text-gray-400 hover:text-gray-200 text-sm"
                @click="cancelEditDevice"
              >
                关闭
              </button>
            </div>

            <!-- Auto Group Invite -->
            <div class="space-y-3 border-l-2 border-blue-500/30 pl-4">
              <div class="flex items-center gap-2">
                <input
                  v-model="editingGroupInvite.enabled"
                  type="checkbox"
                  class="rounded border-gray-600 bg-gray-700 text-blue-600 focus:ring-blue-500"
                />
                <span class="text-sm font-medium text-gray-200">自动拉群</span>
              </div>

              <div v-if="editingGroupInvite.enabled" class="space-y-3">
                <div>
                  <label class="block text-sm text-gray-400 mb-1">群成员</label>
                  <div class="flex flex-wrap gap-1.5 mb-2">
                    <span
                      v-for="(member, idx) in editingGroupInvite.group_members"
                      :key="idx"
                      class="inline-flex items-center gap-1 px-2 py-0.5 bg-blue-600/20 text-blue-300 rounded text-xs"
                    >
                      {{ member }}
                      <button
                        class="text-blue-400 hover:text-blue-200"
                        @click="removeProfileMember(idx)"
                      >
                        &times;
                      </button>
                    </span>
                  </div>
                  <div class="flex gap-2">
                    <input
                      v-model="newProfileMember"
                      class="flex-1 bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
                      placeholder="添加群成员名"
                      @keydown.enter.prevent="addProfileMember"
                    />
                    <button
                      class="px-2 py-1 text-xs bg-gray-600 text-gray-200 rounded hover:bg-gray-500"
                      @click="addProfileMember"
                    >
                      +
                    </button>
                  </div>
                </div>

                <div>
                  <label class="block text-sm text-gray-400 mb-1">群名模板</label>
                  <input
                    v-model="editingGroupInvite.group_name_template"
                    class="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                  <p class="text-xs text-gray-500 mt-1">可用变量: {customer_name}, {kefu_name}</p>
                </div>
              </div>
            </div>

            <!-- Auto Contact Share -->
            <div class="space-y-3 border-l-2 border-green-500/30 pl-4">
              <div class="flex items-center gap-2">
                <input
                  v-model="editingContactShare.enabled"
                  type="checkbox"
                  class="rounded border-gray-600 bg-gray-700 text-green-600 focus:ring-green-500"
                />
                <span class="text-sm font-medium text-gray-200">自动发名片</span>
              </div>

              <div v-if="editingContactShare.enabled" class="space-y-3">
                <div>
                  <label class="block text-sm text-gray-400 mb-1">名片联系人名称</label>
                  <input
                    v-model="editingContactShare.contact_name"
                    class="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-green-500"
                    placeholder="输入要发送的名片联系人名称"
                  />
                </div>
              </div>
            </div>

            <!-- Save / Reset buttons -->
            <div class="flex items-center gap-3 pt-2">
              <button
                class="px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded hover:bg-blue-700 transition-colors"
                @click="saveDeviceProfile"
              >
                保存设备配置
              </button>
              <button
                v-if="deviceProfilesStore.selectedDeviceActions.length > 0"
                class="px-4 py-1.5 bg-gray-600 text-gray-200 text-sm rounded hover:bg-gray-500 transition-colors"
                @click="deleteDeviceProfile('auto_group_invite'); deleteDeviceProfile('auto_contact_share')"
              >
                重置为全局默认
              </button>
            </div>
          </div>
        </div>

        <div v-else class="text-sm text-gray-500 py-4 text-center">
          暂无设备数据。请先连接设备并进行同步操作以录入设备信息。
        </div>
      </div>

      <!-- Save Button -->
      <div class="flex justify-end">
        <button
          id="save-media-action-settings"
          :disabled="saving"
          class="px-6 py-2.5 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          @click="saveSettings"
        >
          {{ saving ? t('media_actions.saving') : t('media_actions.save') }}
        </button>
      </div>

      <!-- Test Section -->
      <div class="bg-wecom-darker rounded-lg p-5 border border-wecom-border">
        <h2 class="text-lg font-semibold text-gray-100 mb-4">
          {{ t('media_actions.test_title') }}
        </h2>
        <p class="text-sm text-gray-400 mb-4">
          {{ t('media_actions.test_desc') }}
        </p>

        <div class="grid grid-cols-3 gap-4 mb-4">
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">{{
              t('media_actions.test_device_serial')
            }}</label>
            <input
              v-model="testDeviceSerial"
              type="text"
              class="w-full bg-gray-700 border border-gray-600 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">{{
              t('media_actions.test_customer_name')
            }}</label>
            <input
              v-model="testCustomerName"
              type="text"
              class="w-full bg-gray-700 border border-gray-600 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">{{
              t('media_actions.test_message_type')
            }}</label>
            <select
              v-model="testMessageType"
              class="w-full bg-gray-700 border border-gray-600 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="image">{{ t('media_actions.type_image') }}</option>
              <option value="video">{{ t('media_actions.type_video') }}</option>
            </select>
          </div>
        </div>

        <button
          :disabled="testing"
          class="px-4 py-2 bg-amber-600 text-white text-sm font-medium rounded-md hover:bg-amber-700 disabled:opacity-50 transition-colors"
          @click="runTest"
        >
          {{ testing ? t('media_actions.running_test') : t('media_actions.run_test') }}
        </button>

        <!-- Test Results -->
        <div v-if="testResults.length > 0" class="mt-4 space-y-2">
          <h3 class="text-sm font-medium text-gray-300">{{ t('media_actions.test_results') }}</h3>
          <div
            v-for="(result, idx) in testResults"
            :key="idx"
            :class="[
              'flex items-center gap-3 px-3 py-2 rounded-md text-sm',
              result.status === 'success'
                ? 'bg-green-900/30 text-green-300'
                : result.status === 'skipped'
                  ? 'bg-gray-700/50 text-gray-400'
                  : 'bg-red-900/30 text-red-300',
            ]"
          >
            <span class="font-mono">{{ result.action_name }}</span>
            <span
              :class="[
                'px-2 py-0.5 rounded text-xs font-medium',
                result.status === 'success'
                  ? 'bg-green-600/30'
                  : result.status === 'skipped'
                    ? 'bg-gray-600/30'
                    : 'bg-red-600/30',
              ]"
            >
              {{ result.status }}
            </span>
            <span class="text-gray-400">{{ result.message }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
