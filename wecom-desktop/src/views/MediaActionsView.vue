<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../services/api'
import type { MediaAutoActionSettings } from '../services/api'
import { useI18n } from '../composables/useI18n'
import { useDeviceProfilesStore } from '../stores/deviceProfiles'

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

const deviceProfilesStore = useDeviceProfilesStore()

// --- Selection state ---
// 'global' or a device serial
const selectedTarget = ref<string>('global')
const activeTab = ref<'review_gate' | 'auto_blacklist' | 'auto_group_invite' | 'auto_contact_share'>('auto_group_invite')

// Global settings
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

// Per-device editing state — holds a local copy of each section's config
// for the currently selected device. Populated when user selects a device.
const deviceOverrides = ref<Record<string, { enabled: boolean; config: Record<string, unknown> }>>({})

// Effective settings display for the selected device
const showEffectiveSettings = ref(false)

const isGlobal = computed(() => selectedTarget.value === 'global')
const selectedDevice = computed(() =>
  isGlobal.value ? null : deviceProfilesStore.profiles.find(d => d.device_serial === selectedTarget.value)
)

const testCustomerName = ref('测试客户')
const testDeviceSerial = ref('test_device')
const testMessageType = ref<'image' | 'video'>('image')
const testResults = ref<Array<{ action_name: string; status: string; message: string }>>([])

const previewCtx = computed(() => ({
  customer_name: testCustomerName.value.trim() || '测试客户',
  kefu_name: '客服A',
  device_serial: isGlobal.value ? testDeviceSerial.value.trim() || 'test_device' : selectedTarget.value,
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

// --- Global settings ---

async function loadSettings() {
  loading.value = true
  try {
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

// --- Per-device ---

function selectTarget(target: string) {
  selectedTarget.value = target
  if (target !== 'global') {
    loadDeviceOverrides(target)
  }
}

async function loadDeviceOverrides(serial: string) {
  showEffectiveSettings.value = false
  try {
    await deviceProfilesStore.selectDevice(serial)
    // Build local editing state from the store's loaded actions
    const overrides: Record<string, { enabled: boolean; config: Record<string, unknown> }> = {}
    for (const action of deviceProfilesStore.selectedDeviceActions) {
      overrides[action.action_type] = {
        enabled: action.enabled,
        config: { ...action.config },
      }
    }
    deviceOverrides.value = overrides
    // Pre-fetch effective settings for display
    await deviceProfilesStore.fetchEffectiveSettings(serial)
  } catch {
    deviceOverrides.value = {}
  }
}

function getDeviceOverride(actionType: string): { enabled: boolean; config: Record<string, unknown> } {
  return deviceOverrides.value[actionType] || { enabled: true, config: {} }
}

function isDeviceOverridden(actionType: string): boolean {
  return !!deviceOverrides.value[actionType]
}

function toggleDeviceOverride(actionType: string) {
  if (isDeviceOverridden(actionType)) {
    // Turn off: delete from local state (will delete on save)
    const newOverrides = { ...deviceOverrides.value }
    delete newOverrides[actionType]
    deviceOverrides.value = newOverrides
  } else {
    // Turn on: create an enabled override seeded from global defaults
    const globalSection = (settings.value as any)[actionType] || {}
    const seed: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(globalSection)) {
      if (k !== 'enabled') seed[k] = v
    }
    deviceOverrides.value = {
      ...deviceOverrides.value,
      [actionType]: { enabled: true, config: seed },
    }
  }
}

function patchDeviceSection(actionType: string, fields: Record<string, unknown>) {
  const existing = deviceOverrides.value[actionType]
  if (!existing) return
  deviceOverrides.value = {
    ...deviceOverrides.value,
    [actionType]: {
      ...existing,
      config: { ...existing.config, ...fields },
    },
  }
}

function patchDeviceEnabled(actionType: string, enabled: boolean) {
  const existing = deviceOverrides.value[actionType]
  if (!existing) return
  deviceOverrides.value = {
    ...deviceOverrides.value,
    [actionType]: { ...existing, enabled },
  }
}

async function saveDeviceOverrides() {
  if (isGlobal.value) return
  const serial = selectedTarget.value
  try {
    // Save all overrides that exist locally
    for (const [actionType, data] of Object.entries(deviceOverrides.value)) {
      await deviceProfilesStore.saveDeviceAction(serial, actionType, {
        enabled: data.enabled,
        config: data.config,
      })
    }
    showToast('设备配置已保存')
    await deviceProfilesStore.fetchProfiles()
  } catch (e: any) {
    showToast(e.message || '保存失败', 'error')
  }
}

async function resetDeviceOverride(actionType: string) {
  if (isGlobal.value) return
  try {
    await deviceProfilesStore.deleteDeviceAction(selectedTarget.value, actionType)
    const newOverrides = { ...deviceOverrides.value }
    delete newOverrides[actionType]
    deviceOverrides.value = newOverrides
    showToast('已重置为全局默认')
    await deviceProfilesStore.fetchProfiles()
  } catch (e: any) {
    showToast(e.message || '删除失败', 'error')
  }
}

// --- Reachability test (global only) ---

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

// --- Lifecycle ---

onMounted(loadSettings)

let _profileRefreshTimer: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  _profileRefreshTimer = setInterval(() => {
    if (!loading.value) deviceProfilesStore.fetchProfiles()
  }, 10000)
})
onUnmounted(() => {
  if (_profileRefreshTimer) clearInterval(_profileRefreshTimer)
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
      <p class="text-sm text-gray-400 mt-1">{{ t('media_actions.subtitle') }}</p>
    </div>

    <div v-if="loading" class="flex items-center justify-center py-20">
      <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
    </div>

    <div v-else class="flex gap-6">
      <!-- ====== LEFT SIDEBAR ====== -->
      <div class="w-56 shrink-0 space-y-3">
        <!-- Global toggle -->
        <div class="bg-wecom-darker rounded-lg p-4 border border-wecom-border">
          <div class="flex items-center justify-between">
            <span class="text-sm font-medium text-gray-200">总开关</span>
            <label class="relative inline-flex items-center cursor-pointer">
              <input v-model="settings.enabled" type="checkbox" class="sr-only peer" />
              <div
                class="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"
              ></div>
            </label>
          </div>
        </div>

        <!-- Global defaults -->
        <button
          class="w-full text-left px-4 py-3 rounded-lg border transition-colors"
          :class="[
            isGlobal
              ? 'bg-blue-600/20 border-blue-500/50 text-blue-300'
              : 'bg-wecom-darker border-wecom-border text-gray-300 hover:bg-gray-700/50',
          ]"
          @click="selectTarget('global')"
        >
          <div class="font-medium text-sm">全局默认</div>
          <div class="text-xs text-gray-500 mt-0.5">所有设备的基础配置</div>
        </button>

        <!-- Device list -->
        <div class="text-xs font-medium uppercase tracking-wide text-gray-500 px-1 pt-2">设备</div>

        <template v-if="deviceProfilesStore.profiles.length > 0">
          <button
            v-for="device in deviceProfilesStore.profiles"
            :key="device.device_serial"
            class="w-full text-left px-4 py-3 rounded-lg border transition-colors"
            :class="[
              selectedTarget === device.device_serial
                ? 'bg-blue-600/20 border-blue-500/50 text-blue-300'
                : device.has_any_override
                  ? 'bg-green-600/10 border-green-600/30 text-green-300 hover:bg-green-600/20'
                  : 'bg-wecom-darker border-wecom-border text-gray-300 hover:bg-gray-700/50',
            ]"
            @click="selectTarget(device.device_serial)"
          >
            <div class="font-medium text-sm truncate">{{ device.model || device.device_serial }}</div>
            <div class="flex items-center gap-1.5 mt-1">
              <!-- Override dots: one per section -->
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
        </template>
        <div v-else class="text-xs text-gray-500 py-2 px-1">暂无连接设备</div>
      </div>

      <!-- ====== MAIN CONTENT ====== -->
      <div class="flex-1 min-w-0 space-y-5">
        <!-- Context header -->
        <div class="flex items-center justify-between">
          <div>
            <h2 class="text-lg font-semibold text-gray-100">
              {{ isGlobal ? '全局默认配置' : `${selectedDevice?.model || selectedTarget} 的专属配置` }}
            </h2>
            <p v-if="!isGlobal" class="text-xs text-gray-500 mt-0.5">
              未覆盖的选项自动继承全局默认
            </p>
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
        <div class="bg-wecom-darker rounded-lg border border-wecom-border p-5" :class="{ 'opacity-50': !settings.enabled }">
          <!-- Section enable toggle -->
          <div class="flex items-center justify-between mb-4">
            <div>
              <h3 class="text-base font-semibold text-gray-100">{{ t(TAB_META[activeTab].labelKey) }}</h3>
            </div>

            <!-- Per-device: show override toggle -->
            <template v-if="!isGlobal">
              <div class="flex items-center gap-3">
                <label class="relative inline-flex items-center cursor-pointer">
                  <input
                    :checked="isDeviceOverridden(activeTab)"
                    type="checkbox"
                    class="sr-only peer"
                    @change="toggleDeviceOverride(activeTab)"
                  />
                  <div
                    class="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"
                  ></div>
                </label>
                <span class="text-xs text-gray-400">
                  {{ isDeviceOverridden(activeTab) ? '使用设备专属' : '跟随全局默认' }}
                </span>
              </div>
            </template>

            <!-- Global: show section enabled toggle -->
            <template v-else>
              <label class="relative inline-flex items-center cursor-pointer">
                <input
                  v-model="(settings as any)[activeTab].enabled"
                  type="checkbox"
                  :disabled="!settings.enabled"
                  class="sr-only peer"
                />
                <div
                  class="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600 peer-disabled:opacity-50"
                ></div>
              </label>
            </template>
          </div>

          <!-- Form content — GLOBAL mode -->
          <template v-if="isGlobal">
            <div v-show="(settings as any)[activeTab].enabled && settings.enabled">
              <!-- Review Gate -->
              <ReviewGateForm
                v-if="activeTab === 'review_gate'"
                v-model="settings.review_gate"
                :disabled="!settings.enabled"
              />
              <!-- Auto Blacklist -->
              <AutoBlacklistForm
                v-if="activeTab === 'auto_blacklist'"
                v-model="settings.auto_blacklist"
                :disabled="!settings.enabled"
              />
              <!-- Auto Group Invite -->
              <AutoGroupInviteForm
                v-if="activeTab === 'auto_group_invite'"
                v-model="settings.auto_group_invite"
                :disabled="!settings.enabled"
                :preview-context="previewCtx"
              />
              <!-- Auto Contact Share -->
              <AutoContactShareForm
                v-if="activeTab === 'auto_contact_share'"
                v-model="settings.auto_contact_share"
                :disabled="!settings.enabled"
                :preview-context="previewCtx"
              />

              <!-- Reachability test only for contact share -->
              <div v-if="activeTab === 'auto_contact_share'" class="mt-4 flex items-center gap-3">
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
          </template>

          <!-- Form content — DEVICE mode -->
          <template v-else>
            <template v-if="isDeviceOverridden(activeTab)">
              <!-- Device section enabled toggle -->
              <div class="flex items-center gap-2 mb-4">
                <input
                  :checked="getDeviceOverride(activeTab).enabled"
                  type="checkbox"
                  class="rounded border-gray-600 bg-gray-700 text-blue-600 focus:ring-blue-500"
                  @change="patchDeviceEnabled(activeTab, ($event.target as HTMLInputElement).checked)"
                />
                <span class="text-sm text-gray-300">启用此设备的{{ t(TAB_META[activeTab].labelKey) }}</span>
              </div>

              <div v-show="getDeviceOverride(activeTab).enabled">
                <!-- Review Gate (device) -->
                <ReviewGateForm
                  v-if="activeTab === 'review_gate'"
                  :model-value="{ enabled: true, ...(getDeviceOverride('review_gate').config as any) }"
                  :disabled="false"
                  @update:model-value="patchDeviceSection('review_gate', $event)"
                />
                <!-- Auto Blacklist (device) -->
                <AutoBlacklistForm
                  v-if="activeTab === 'auto_blacklist'"
                  :model-value="{ enabled: true, ...(getDeviceOverride('auto_blacklist').config as any) }"
                  :disabled="false"
                  @update:model-value="patchDeviceSection('auto_blacklist', $event)"
                />
                <!-- Auto Group Invite (device) -->
                <AutoGroupInviteForm
                  v-if="activeTab === 'auto_group_invite'"
                  :model-value="{ enabled: true, ...(getDeviceOverride('auto_group_invite').config as any) }"
                  :disabled="false"
                  :preview-context="previewCtx"
                  @update:model-value="patchDeviceSection('auto_group_invite', $event)"
                />
                <!-- Auto Contact Share (device) -->
                <AutoContactShareForm
                  v-if="activeTab === 'auto_contact_share'"
                  :model-value="{ enabled: true, ...(getDeviceOverride('auto_contact_share').config as any) }"
                  :disabled="false"
                  :preview-context="previewCtx"
                  @update:model-value="patchDeviceSection('auto_contact_share', $event)"
                />
              </div>

              <!-- Reset button -->
              <div class="mt-4 pt-3 border-t border-gray-700/50">
                <button
                  class="text-xs text-gray-500 hover:text-red-400 transition-colors"
                  @click="resetDeviceOverride(activeTab)"
                >
                  重置为全局默认
                </button>
              </div>
            </template>

            <!-- No override — show hint -->
            <template v-else>
              <div class="py-8 text-center text-gray-500 text-sm">
                <p>此设备正在使用全局默认配置</p>
                <p class="mt-1 text-xs text-gray-600">打开上方的开关以设置设备专属配置</p>
              </div>
            </template>
          </template>
        </div>

        <!-- Effective settings preview (device mode only) -->
        <template v-if="!isGlobal">
          <div class="bg-wecom-darker rounded-lg border border-wecom-border">
            <button
              class="w-full flex items-center justify-between px-5 py-3 text-sm font-medium text-gray-300 hover:text-gray-100 transition-colors"
              @click="showEffectiveSettings = !showEffectiveSettings"
            >
              <span>查看有效配置 (全局 + 设备覆盖)</span>
              <span :class="['transition-transform', showEffectiveSettings ? 'rotate-180' : '']">&#9660;</span>
            </button>
            <div v-if="showEffectiveSettings && deviceProfilesStore.effectiveSettings" class="px-5 pb-4 space-y-3">
              <p class="text-xs text-gray-500">以下是此设备最终使用的合并配置（全局默认 + 设备覆盖）</p>
              <div
                v-for="sectionKey in SECTION_KEYS"
                :key="sectionKey"
                class="border border-gray-700/50 rounded-md p-3"
              >
                <div class="flex items-center gap-2 mb-2">
                  <span
                    class="inline-block w-2 h-2 rounded-full"
                    :class="isDeviceOverridden(sectionKey) ? 'bg-green-500' : 'bg-gray-600'"
                  ></span>
                  <span class="text-sm font-medium text-gray-200">{{ t(TAB_META[sectionKey].labelKey) }}</span>
                  <span v-if="isDeviceOverridden(sectionKey)" class="text-xs text-green-400">(已覆盖)</span>
                  <span v-else class="text-xs text-gray-500">(继承全局)</span>
                </div>
                <pre class="text-xs text-gray-400 bg-gray-800/50 rounded p-2 overflow-x-auto">{{
                  JSON.stringify(
                    isDeviceOverridden(sectionKey)
                      ? { enabled: getDeviceOverride(sectionKey).enabled, ...getDeviceOverride(sectionKey).config }
                      : (deviceProfilesStore.effectiveSettings.settings as any)?.[sectionKey] || '未配置',
                    null,
                    2,
                  )
                }}</pre>
              </div>
            </div>
            <div v-else-if="showEffectiveSettings && !deviceProfilesStore.effectiveSettings" class="px-5 pb-4 text-xs text-gray-500">
              加载中...
            </div>
          </div>
        </template>

        <!-- Save -->
        <div class="flex justify-end">
          <button
            id="save-media-action-settings"
            :disabled="saving"
            class="px-6 py-2.5 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            @click="isGlobal ? saveSettings() : saveDeviceOverrides()"
          >
            {{ saving ? t('media_actions.saving') : isGlobal ? t('media_actions.save') : '保存设备配置' }}
          </button>
        </div>

        <!-- Test Section -->
        <div class="bg-wecom-darker rounded-lg p-5 border border-wecom-border">
          <h2 class="text-lg font-semibold text-gray-100 mb-4">
            {{ t('media_actions.test_title') }}
          </h2>
          <p class="text-sm text-gray-400 mb-4">{{ t('media_actions.test_desc') }}</p>

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
