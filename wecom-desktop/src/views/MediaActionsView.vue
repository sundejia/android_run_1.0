<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../services/api'
import type { MediaAutoActionSettings } from '../services/api'
import { useI18n } from '../composables/useI18n'
import { renderMediaActionTemplate } from '../utils/mediaActionTemplates'

const { t } = useI18n()
const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const toast = ref<{ message: string; type: 'success' | 'error' } | null>(null)

const settings = ref<MediaAutoActionSettings>({
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
  auto_contact_share: {
    enabled: false,
    contact_name: '',
    skip_if_already_shared: true,
    cooldown_seconds: 0,
    kefu_overrides: {},
  },
})

const newMember = ref('')
const newKefuName = ref('')
const newKefuContact = ref('')
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

function showToast(message: string, type: 'success' | 'error' = 'success') {
  toast.value = { message, type }
  setTimeout(() => {
    toast.value = null
  }, 3000)
}

async function loadSettings() {
  loading.value = true
  try {
    settings.value = await api.getMediaActionSettings()
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

function removeMember(index: number) {
  settings.value.auto_group_invite.group_members.splice(index, 1)
}

function addKefuOverride() {
  const kefu = newKefuName.value.trim()
  const contact = newKefuContact.value.trim()
  if (kefu && contact) {
    settings.value.auto_contact_share.kefu_overrides[kefu] = contact
    newKefuName.value = ''
    newKefuContact.value = ''
  }
}

function removeKefuOverride(kefuName: string) {
  delete settings.value.auto_contact_share.kefu_overrides[kefuName]
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
          </div>

          <!-- Per-Kefu Overrides -->
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-2">{{
              t('media_actions.kefu_overrides_label')
            }}</label>
            <div class="flex flex-wrap gap-2 mb-2">
              <span
                v-for="(contact, kefu) in settings.auto_contact_share.kefu_overrides"
                :key="kefu"
                class="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-purple-600/20 text-purple-300 text-sm border border-purple-600/30"
              >
                {{ kefu }} → {{ contact }}
                <button
                  class="ml-1 text-purple-400 hover:text-red-400 transition-colors"
                  @click="removeKefuOverride(String(kefu))"
                >
                  &times;
                </button>
              </span>
              <span
                v-if="Object.keys(settings.auto_contact_share.kefu_overrides).length === 0"
                class="text-sm text-gray-500 italic"
              >
                {{ t('media_actions.no_members') }}
              </span>
            </div>
            <div class="flex gap-2">
              <input
                v-model="newKefuName"
                type="text"
                class="flex-1 bg-gray-700 border border-gray-600 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
                :placeholder="t('media_actions.kefu_name_placeholder')"
                @keyup.enter="addKefuOverride"
              />
              <input
                v-model="newKefuContact"
                type="text"
                class="flex-1 bg-gray-700 border border-gray-600 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
                :placeholder="t('media_actions.contact_for_kefu_placeholder')"
                @keyup.enter="addKefuOverride"
              />
              <button
                class="px-4 py-2 bg-purple-600 text-white text-sm rounded-md hover:bg-purple-700 transition-colors"
                @click="addKefuOverride"
              >
                {{ t('media_actions.add') }}
              </button>
            </div>
            <p class="text-xs text-gray-500 mt-1">
              {{ t('media_actions.kefu_overrides_desc') }}
            </p>
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
