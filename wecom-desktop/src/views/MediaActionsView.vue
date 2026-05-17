<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../services/api'
import type { MediaAutoActionSettings } from '../services/api'
import { useI18n } from '../composables/useI18n'
import { useDeviceProfilesStore } from '../stores/deviceProfiles'
import { useGlobalWebSocketStore } from '../stores/globalWebSocket'
import type { GlobalWebSocketEvent } from '../stores/globalWebSocket'

import ReviewGateForm from '../components/mediaActions/ReviewGateForm.vue'
import AutoBlacklistForm from '../components/mediaActions/AutoBlacklistForm.vue'
import AutoGroupInviteForm from '../components/mediaActions/AutoGroupInviteForm.vue'
import AutoContactShareForm from '../components/mediaActions/AutoContactShareForm.vue'

const { t } = useI18n()
const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const reachabilityTesting = ref(false)
const reachabilityResult = ref<{ reachable: boolean; message: string } | null>(null)
const toast = ref<{ message: string; type: 'success' | 'error' } | null>(null)

const realtimeNotifications = ref<Array<{ action_name: string; status: string; message: string; timestamp: string; device_serial?: string; customer_name?: string }>>([])
const MAX_NOTIFICATIONS = 20

const deviceProfilesStore = useDeviceProfilesStore()
const wsStore = useGlobalWebSocketStore()

// --- Selection state ---
const selectedSerial = ref<string>('')
const activeTab = ref<'review_gate' | 'auto_blacklist' | 'auto_group_invite' | 'auto_contact_share'>('auto_group_invite')

// Frontend code defaults — must stay in sync with DEFAULT_MEDIA_AUTO_ACTION_SETTINGS
// in src/wecom_automation/services/media_actions/settings_loader.py
function createDefaultSettings(): MediaAutoActionSettings {
  return {
    enabled: false,
    auto_blacklist: {
      enabled: false,
      reason: 'Customer sent media (auto)',
      skip_if_already_blacklisted: true,
      require_review_pass: false,
    },
    auto_group_invite: {
      enabled: false,
      group_members: [],
      group_name_template: '{customer_name}-服务群',
      skip_if_group_exists: true,
      send_message_before_create: false,
      pre_create_message_text: '',
      send_test_message_after_create: true,
      test_message_text: '测试',
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

// Current device's editable settings (local copy)
const settings = ref<MediaAutoActionSettings>(createDefaultSettings())
// Tracks which action types have been modified locally (need saving)
const dirtySections = ref<Set<string>>(new Set())
const masterDirty = ref(false)

const selectedDevice = computed(() =>
  deviceProfilesStore.profiles.find(d => d.device_serial === selectedSerial.value)
)

const testCustomerName = ref('测试客户')
const testMessageType = ref<'image' | 'video'>('image')
const testResults = ref<Array<{ action_name: string; status: string; message: string }>>([])

const previewCtx = computed(() => ({
  customer_name: testCustomerName.value.trim() || '测试客户',
  kefu_name: '客服A',
  device_serial: selectedSerial.value || 'test_device',
}))

const TAB_META: Record<string, { labelKey: string; color: string }> = {
  review_gate: { labelKey: 'media_actions.review_gate_title', color: 'purple' },
  auto_blacklist: { labelKey: 'media_actions.auto_blacklist', color: 'red' },
  auto_group_invite: { labelKey: 'media_actions.auto_group_invite', color: 'blue' },
  auto_contact_share: { labelKey: 'media_actions.auto_contact_share', color: 'green' },
}

const SECTION_KEYS = ['review_gate', 'auto_blacklist', 'auto_group_invite', 'auto_contact_share'] as const

function showToast(message: string, type: 'success' | 'error' = 'success') {
  toast.value = { message, type }
  setTimeout(() => { toast.value = null }, 3000)
}

// --- Device settings load/save ---

function selectDevice(serial: string) {
  selectedSerial.value = serial
  loadDeviceSettings(serial)
}

async function loadDeviceSettings(serial: string) {
  loading.value = true
  try {
    // Fetch all action profiles for this device
    const actions = await api.getDeviceActions(serial)

    // Start from code defaults
    const result = createDefaultSettings()
    dirtySections.value = new Set()
    masterDirty.value = false

    for (const action of actions) {
      if (action.action_type === '_master') {
        result.enabled = action.enabled
        continue
      }

      const sectionKey = action.action_type as keyof Pick<MediaAutoActionSettings, 'auto_blacklist' | 'auto_group_invite' | 'auto_contact_share' | 'review_gate'>
      if (sectionKey in result) {
        const section = (result as any)[sectionKey] as Record<string, any>
        section.enabled = action.enabled
        if (action.config && typeof action.config === 'object') {
          for (const [k, v] of Object.entries(action.config)) {
            if (k !== 'enabled') section[k] = v
          }
        }
      }
    }

    settings.value = result
  } catch (err: any) {
    showToast(err.message || '加载设备配置失败', 'error')
    settings.value = createDefaultSettings()
  } finally {
    loading.value = false
  }
}

async function saveDeviceSettings() {
  if (!selectedSerial.value) return
  saving.value = true
  try {
    const serial = selectedSerial.value

    // Save master switch
    if (masterDirty.value) {
      await api.upsertDeviceAction(serial, '_master', {
        enabled: settings.value.enabled,
        config: {},
      })
      masterDirty.value = false
    }

    // Save each dirty section
    for (const sectionKey of dirtySections.value) {
      const section = (settings.value as any)[sectionKey] as Record<string, any>
      const { enabled, ...config } = section
      await api.upsertDeviceAction(serial, sectionKey, {
        enabled: !!enabled,
        config,
      })
    }
    dirtySections.value = new Set()

    showToast('配置已保存')
    await deviceProfilesStore.fetchProfiles()
  } catch (err: any) {
    showToast(err.message || '保存失败', 'error')
  } finally {
    saving.value = false
  }
}

// Mark a section as dirty when its form emits an update
function onSectionUpdate(sectionKey: string, value: any) {
  const section = (settings.value as any)[sectionKey] as Record<string, any>
  for (const [k, v] of Object.entries(value)) {
    section[k] = v
  }
  dirtySections.value.add(sectionKey)
}

// Mark a section enabled change
function onSectionEnabledChange(sectionKey: string, enabled: boolean) {
  const section = (settings.value as any)[sectionKey] as Record<string, any>
  section.enabled = enabled
  dirtySections.value.add(sectionKey)
}

// Master switch change
function onMasterSwitchChange(enabled: boolean) {
  settings.value.enabled = enabled
  masterDirty.value = true
}

// Auto-save after debounce
let _saveTimeout: ReturnType<typeof setTimeout> | null = null
function scheduleAutoSave() {
  if (_saveTimeout) clearTimeout(_saveTimeout)
  _saveTimeout = setTimeout(() => {
    if (selectedSerial.value && (dirtySections.value.size > 0 || masterDirty.value)) {
      saveDeviceSettings()
    }
  }, 1500)
}

// Watch for dirty changes and auto-save
watch(dirtySections, () => scheduleAutoSave(), { deep: true })
watch(() => masterDirty.value, () => scheduleAutoSave())

// --- Reachability test ---

async function testContactReachability() {
  const contactName = settings.value.auto_contact_share.contact_name.trim()
  const serial = selectedSerial.value
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
    const res = await api.testContactReachability({ device_serial: serial, contact_name: contactName })
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

// --- Test trigger ---

async function runTest() {
  testing.value = true
  testResults.value = []
  try {
    const res = await api.testTriggerMediaAction({
      device_serial: selectedSerial.value || 'test_device',
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

// --- Lifecycle ---

async function init() {
  loading.value = true
  try {
    await deviceProfilesStore.fetchProfiles()
    // Auto-select first device
    if (deviceProfilesStore.profiles.length > 0) {
      selectDevice(deviceProfilesStore.profiles[0].device_serial)
    } else {
      loading.value = false
    }
  } catch (err: any) {
    showToast(err.message || '加载失败', 'error')
    loading.value = false
  }
}

onMounted(init)

let _profileRefreshTimer: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  _profileRefreshTimer = setInterval(() => {
    if (!loading.value) deviceProfilesStore.fetchProfiles()
  }, 10000)
})

// WebSocket listeners for real-time media action feedback
function _onMediaActionTriggered(event: GlobalWebSocketEvent) {
  const data = event.data
  if (!data?.results) return
  for (const r of data.results) {
    realtimeNotifications.value.unshift({
      action_name: r.action_name || '',
      status: r.status || '',
      message: r.message || '',
      timestamp: event.timestamp || new Date().toISOString(),
      device_serial: data.device_serial,
      customer_name: data.customer_name,
    })
  }
  if (realtimeNotifications.value.length > MAX_NOTIFICATIONS) {
    realtimeNotifications.value = realtimeNotifications.value.slice(0, MAX_NOTIFICATIONS)
  }
}

function _onProfileUpdated(event: GlobalWebSocketEvent) {
  // Another session updated device profiles — reload current device
  if (!loading.value && !saving.value && selectedSerial.value) {
    const data = event.data
    if (data?.device_serial === selectedSerial.value) {
      loadDeviceSettings(selectedSerial.value)
    }
  }
}

onMounted(() => {
  wsStore.addListener('media_action_triggered', _onMediaActionTriggered)
  wsStore.addListener('device_action_profile_updated', _onProfileUpdated)
})

onUnmounted(() => {
  if (_profileRefreshTimer) clearInterval(_profileRefreshTimer)
  wsStore.removeListener('media_action_triggered', _onMediaActionTriggered)
  wsStore.removeListener('device_action_profile_updated', _onProfileUpdated)
})

// Auto-dismiss old notifications after 10s
let _notifCleanupTimer: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  _notifCleanupTimer = setInterval(() => {
    const cutoff = Date.now() - 30_000
    realtimeNotifications.value = realtimeNotifications.value.filter(n => {
      return new Date(n.timestamp).getTime() > cutoff
    })
  }, 10_000)
})
onUnmounted(() => {
  if (_notifCleanupTimer) clearInterval(_notifCleanupTimer)
})
</script>

<template>
  <div class="p-6 max-w-6xl mx-auto">
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
      <p class="text-sm text-gray-400 mt-1">每台设备独立配置，互不影响</p>
    </div>

    <div v-if="loading && !selectedSerial" class="flex items-center justify-center py-20">
      <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
    </div>

    <!-- No devices -->
    <div v-else-if="deviceProfilesStore.profiles.length === 0" class="text-center py-20 text-gray-500">
      <p class="text-lg">暂无连接设备</p>
      <p class="text-sm mt-2">请先连接 Android 设备并确保 ADB 可用</p>
    </div>

    <div v-else class="flex gap-6">
      <!-- ====== LEFT SIDEBAR ====== -->
      <div class="w-56 shrink-0 space-y-3">
        <div class="text-xs font-medium uppercase tracking-wide text-gray-500 px-1">选择设备</div>

        <button
          v-for="device in deviceProfilesStore.profiles"
          :key="device.device_serial"
          class="w-full text-left px-4 py-3 rounded-lg border transition-colors"
          :class="[
            selectedSerial === device.device_serial
              ? 'bg-blue-600/20 border-blue-500/50 text-blue-300'
              : 'bg-wecom-darker border-wecom-border text-gray-300 hover:bg-gray-700/50',
          ]"
          @click="selectDevice(device.device_serial)"
        >
          <div class="font-medium text-sm truncate">{{ device.model || device.device_serial }}</div>
          <div class="flex items-center gap-1.5 mt-1">
            <span
              v-for="key in SECTION_KEYS"
              :key="key"
              class="inline-block w-2 h-2 rounded-full"
              :class="device.overrides?.[key]?.enabled != null ? 'bg-green-500' : 'bg-gray-600'"
              :title="key"
            ></span>
            <span class="text-xs text-gray-500 ml-1">{{ device.device_serial }}</span>
          </div>
        </button>
      </div>

      <!-- ====== MAIN CONTENT ====== -->
      <div v-if="selectedSerial" class="flex-1 min-w-0 space-y-5">
        <!-- Context header + Master switch -->
        <div class="flex items-center justify-between">
          <div>
            <h2 class="text-lg font-semibold text-gray-100">
              {{ selectedDevice?.model || selectedSerial }}
            </h2>
            <p class="text-xs text-gray-500 mt-0.5">{{ selectedSerial }}</p>
          </div>
          <div class="flex items-center gap-3">
            <span class="text-sm font-medium text-gray-200">总开关</span>
            <label class="relative inline-flex items-center cursor-pointer">
              <input
                :checked="settings.enabled"
                type="checkbox"
                class="sr-only peer"
                @change="onMasterSwitchChange(($event.target as HTMLInputElement).checked)"
              />
              <div
                class="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"
              ></div>
            </label>
          </div>
        </div>

        <!-- Tabs -->
        <div class="flex border-b border-gray-700 gap-1">
          <button
            v-for="key in SECTION_KEYS"
            :key="key"
            class="px-4 py-2 text-sm font-medium rounded-t-lg transition-colors"
            :class="[
              activeTab === key
                ? 'bg-wecom-darker text-white border border-gray-700 border-b-transparent -mb-px'
                : 'text-gray-400 hover:text-gray-200',
            ]"
            @click="activeTab = key"
          >
            {{ t(TAB_META[key].labelKey) }}
          </button>
        </div>

        <!-- Section card -->
        <div class="bg-wecom-darker rounded-lg border border-wecom-border p-5" :class="{ 'opacity-50 pointer-events-none': !settings.enabled }">
          <!-- Section header + enabled toggle -->
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-base font-semibold text-gray-100">{{ t(TAB_META[activeTab].labelKey) }}</h3>
            <div class="flex items-center gap-2">
              <input
                :checked="(settings as any)[activeTab].enabled"
                type="checkbox"
                class="rounded border-gray-600 bg-gray-700 text-blue-600 focus:ring-blue-500"
                @change="onSectionEnabledChange(activeTab, ($event.target as HTMLInputElement).checked)"
              />
              <span class="text-sm text-gray-300">启用</span>
            </div>
          </div>

          <!-- Form content -->
          <div v-show="(settings as any)[activeTab].enabled && settings.enabled">
            <ReviewGateForm
              v-if="activeTab === 'review_gate'"
              :model-value="settings.review_gate"
              :disabled="!settings.enabled"
              @update:model-value="onSectionUpdate('review_gate', $event)"
            />
            <AutoBlacklistForm
              v-if="activeTab === 'auto_blacklist'"
              :model-value="settings.auto_blacklist"
              :disabled="!settings.enabled"
              @update:model-value="onSectionUpdate('auto_blacklist', $event)"
            />
            <AutoGroupInviteForm
              v-if="activeTab === 'auto_group_invite'"
              :model-value="settings.auto_group_invite"
              :disabled="!settings.enabled"
              :preview-context="previewCtx"
              @update:model-value="onSectionUpdate('auto_group_invite', $event)"
            />
            <AutoContactShareForm
              v-if="activeTab === 'auto_contact_share'"
              :model-value="settings.auto_contact_share"
              :disabled="!settings.enabled"
              :preview-context="previewCtx"
              @update:model-value="onSectionUpdate('auto_contact_share', $event)"
            />

            <!-- Reachability test for contact share -->
            <div v-if="activeTab === 'auto_contact_share'" class="mt-4 flex items-center gap-3">
              <button
                :disabled="
                  reachabilityTesting ||
                  !settings.auto_contact_share.contact_name.trim() ||
                  !selectedSerial
                "
                class="px-3 py-1.5 bg-amber-600 text-white text-xs font-medium rounded-md hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                @click="testContactReachability"
              >
                {{ reachabilityTesting ? t('media_actions.testing_contact_reachability') : t('media_actions.test_contact_reachability') }}
              </button>
              <span
                v-if="reachabilityResult"
                :class="['text-xs', reachabilityResult.reachable ? 'text-green-400' : 'text-red-400']"
              >
                {{ reachabilityResult.message }}
              </span>
            </div>
          </div>
        </div>

        <!-- Save button (manual save, also auto-save fires) -->
        <div class="flex justify-end">
          <button
            id="save-media-action-settings"
            :disabled="saving || (!dirtySections.size && !masterDirty)"
            class="px-6 py-2.5 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            @click="saveDeviceSettings"
          >
            {{ saving ? t('media_actions.saving') : t('media_actions.save') }}
          </button>
        </div>

        <!-- Test Section -->
        <div class="bg-wecom-darker rounded-lg p-5 border border-wecom-border">
          <h2 class="text-lg font-semibold text-gray-100 mb-4">
            {{ t('media_actions.test_title') }}
          </h2>
          <p class="text-sm text-gray-400 mb-4">{{ t('media_actions.test_desc') }}</p>

          <div class="grid grid-cols-2 gap-4 mb-4">
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

        <!-- Real-time Action Notifications -->
        <div v-if="realtimeNotifications.length > 0" class="bg-wecom-darker rounded-lg p-5 border border-cyan-800/40">
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-sm font-semibold text-cyan-300">实时动作通知</h2>
            <button
              class="text-xs text-gray-500 hover:text-gray-300 transition-colors"
              @click="realtimeNotifications = []"
            >
              清空
            </button>
          </div>
          <div class="space-y-1.5 max-h-48 overflow-y-auto">
            <div
              v-for="(n, idx) in realtimeNotifications"
              :key="idx"
              :class="[
                'flex items-center gap-2 px-3 py-1.5 rounded text-xs',
                n.status === 'success'
                  ? 'bg-green-900/20 text-green-300'
                  : n.status === 'skipped'
                    ? 'bg-gray-700/30 text-gray-500'
                    : n.status === 'error'
                      ? 'bg-red-900/20 text-red-300'
                      : 'bg-gray-700/30 text-gray-400',
              ]"
            >
              <span class="font-mono shrink-0 w-28 truncate">{{ n.action_name }}</span>
              <span
                :class="[
                  'px-1.5 py-0.5 rounded text-[10px] font-medium shrink-0',
                  n.status === 'success'
                    ? 'bg-green-600/20'
                    : n.status === 'error'
                      ? 'bg-red-600/20'
                      : 'bg-gray-600/20',
                ]"
              >
                {{ n.status }}
              </span>
              <span v-if="n.customer_name" class="text-gray-500 shrink-0">{{ n.customer_name }}</span>
              <span class="text-gray-600 truncate flex-1">{{ n.message }}</span>
              <span class="text-gray-600 shrink-0 tabular-nums">{{ new Date(n.timestamp).toLocaleTimeString() }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- No device selected yet -->
      <div v-else class="flex-1 text-center py-20 text-gray-500">
        <p>请从左侧选择一台设备</p>
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
