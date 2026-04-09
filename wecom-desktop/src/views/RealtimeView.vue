<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useI18n } from '../composables/useI18n'
import { useSettingsStore } from '../stores/settings'

const { t } = useI18n()
const settingsStore = useSettingsStore()

// Tab state
const activeTab = ref<'analytics' | 'data' | 'settings' | 'devices'>('devices')

// Device state type
interface DeviceFollowUpStatus {
  serial: string
  status: 'idle' | 'starting' | 'running' | 'paused' | 'stopped' | 'error'
  message: string
  responses_detected: number
  replies_sent: number
  started_at: string | null
  last_scan_at: string | null
  errors: string[]
}

interface AllDevicesStatus {
  devices: { [serial: string]: DeviceFollowUpStatus }
  total: number
  running: number
}

// Multi-device management
const devicesStatus = ref<AllDevicesStatus>({ devices: {}, total: 0, running: 0 })
const loadingDevices = ref(false)

// Settings state
const settings = ref({
  enabled: true,
  scanInterval: 60,
  useAIReply: true, // Always enabled
  sendViaSidecar: true, // Always enabled
})

const savingSettings = ref(false)
const settingsError = ref('')

// Scan status (computed from devicesStatus)
const scanStatus = computed(() => ({
  background_scanner_active: devicesStatus.value.running > 0,
  device_count: devicesStatus.value.total,
  next_scan: null as { status: string; seconds_until?: number } | null,
}))

// ============================================
// Multi-Device Management Functions
// ============================================

// Fetch all devices status
async function fetchAllDevicesStatus() {
  loadingDevices.value = true
  try {
    const response = await fetch('http://localhost:8765/api/realtime/devices/status')
    if (response.ok) {
      const data = await response.json()
      devicesStatus.value = data
    }
  } catch (error) {
    console.error('Failed to fetch devices status:', error)
  } finally {
    loadingDevices.value = false
  }
}

// Start follow-up for a device
async function startDeviceFollowUp(serial: string) {
  try {
    const params = new URLSearchParams({
      scan_interval: String(settings.value.scanInterval),
      use_ai_reply: String(settings.value.useAIReply),
      send_via_sidecar: String(settings.value.sendViaSidecar),
    })

    const response = await fetch(
      `http://localhost:8765/api/realtime/device/${serial}/start?${params}`,
      {
        method: 'POST',
      }
    )

    if (response.ok) {
      const data = await response.json()
      if (data.success) {
        await fetchAllDevicesStatus()
      } else {
        alert(data.message || 'Failed to start follow-up')
      }
    }
  } catch (error) {
    console.error('Failed to start device follow-up:', error)
    alert('Failed to start follow-up for device')
  }
}

// Stop follow-up for a device
async function stopDeviceFollowUp(serial: string) {
  try {
    const response = await fetch(`http://localhost:8765/api/realtime/device/${serial}/stop`, {
      method: 'POST',
    })

    if (response.ok) {
      const data = await response.json()
      if (data.success) {
        await fetchAllDevicesStatus()
      }
    }
  } catch (error) {
    console.error('Failed to stop device follow-up:', error)
  }
}

// Pause follow-up for a device
async function pauseDeviceFollowUp(serial: string) {
  try {
    const response = await fetch(`http://localhost:8765/api/realtime/device/${serial}/pause`, {
      method: 'POST',
    })

    if (response.ok) {
      const data = await response.json()
      if (data.success) {
        await fetchAllDevicesStatus()
      }
    }
  } catch (error) {
    console.error('Failed to pause device follow-up:', error)
  }
}

// Resume follow-up for a device
async function resumeDeviceFollowUp(serial: string) {
  try {
    const response = await fetch(`http://localhost:8765/api/realtime/device/${serial}/resume`, {
      method: 'POST',
    })

    if (response.ok) {
      const data = await response.json()
      if (data.success) {
        await fetchAllDevicesStatus()
      }
    }
  } catch (error) {
    console.error('Failed to resume device follow-up:', error)
  }
}

// Start all devices
async function startAllDevices() {
  const serials = Object.keys(devicesStatus.value.devices)
  if (serials.length === 0) {
    alert('No devices available')
    return
  }

  for (const serial of serials) {
    await startDeviceFollowUp(serial)
  }
}

// Stop all devices
async function stopAllDevices() {
  try {
    const response = await fetch('http://localhost:8765/api/realtime/devices/stop-all', {
      method: 'POST',
    })

    if (response.ok) {
      const data = await response.json()
      if (data.success) {
        await fetchAllDevicesStatus()
      }
    }
  } catch (error) {
    console.error('Failed to stop all devices:', error)
  }
}

// ============================================
// Settings Functions
// ============================================

// Fetch settings
async function fetchSettings() {
  try {
    const response = await fetch('http://localhost:8765/api/realtime/settings')
    if (response.ok) {
      const data = await response.json()
      settings.value = { ...settings.value, ...data }
    }
  } catch (error) {
    console.error('Failed to fetch settings:', error)
  }
}

// Save settings
async function saveSettings() {
  savingSettings.value = true
  settingsError.value = ''

  try {
    const response = await fetch('http://localhost:8765/api/realtime/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings.value),
    })

    if (response.ok) {
      const data = await response.json()
      if (data.success) {
        alert(t('realtime.settings_saved'))
        await fetchSettings() // Refresh settings from backend
      } else {
        throw new Error(data.message || 'Failed to save settings')
      }
    } else {
      throw new Error(`HTTP ${response.status}`)
    }
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error)
    settingsError.value = errorMessage
    alert(t('realtime.settings_save_failed') + ' ' + errorMessage)
  } finally {
    savingSettings.value = false
  }
}

// Reset settings to defaults
function resetSettings() {
  settings.value = {
    enabled: true,
    scanInterval: 60,
    useAIReply: true, // Always enabled
    sendViaSidecar: true, // Always enabled
  }
  settingsError.value = ''
}

// Lifecycle
let refreshTimer: number | null = null

onMounted(async () => {
  settingsStore.load()
  // Load device statuses first
  await fetchAllDevicesStatus()
  // Load settings
  await fetchSettings()

  const refreshMs = settingsStore.settings.lowSpecMode ? 15000 : 5000
  refreshTimer = window.setInterval(() => {
    if (document.visibilityState === 'hidden') return
    if (activeTab.value === 'devices') {
      // Refresh device statuses
      fetchAllDevicesStatus()
    }
  }, refreshMs)
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
  }
})

watch(activeTab, (newTab) => {
  if (newTab === 'devices') {
    fetchAllDevicesStatus()
  } else if (newTab === 'settings') {
    fetchSettings()
  }
})

// Format helpers
function formatDate(dateStr: string) {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date
    .toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
    .replace(/\//g, '/')
}
</script>

<template>
  <div
    class="min-h-full bg-gradient-to-br from-wecom-darker via-wecom-darker to-wecom-dark/50 p-6 space-y-6"
  >
    <!-- Header -->
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-3">
        <span class="text-2xl">⚡</span>
        <div>
          <h1 class="text-2xl font-display font-bold text-wecom-text">{{ t('realtime.title') }}</h1>
          <p class="text-sm text-wecom-muted">{{ t('realtime.subtitle') }}</p>
        </div>
      </div>

      <div class="flex items-center gap-3">
        <!-- Background Scanner Status Indicator -->
        <div
          :class="[
            'px-3 py-2 rounded-lg border flex items-center gap-2',
            scanStatus.background_scanner_active
              ? 'bg-emerald-500/10 border-emerald-500/30'
              : 'bg-wecom-surface/50 border-wecom-border',
          ]"
        >
          <span
            :class="[
              'w-2 h-2 rounded-full',
              scanStatus.background_scanner_active ? 'bg-emerald-400 animate-pulse' : 'bg-gray-500',
            ]"
          ></span>
          <span
            class="text-sm"
            :class="scanStatus.background_scanner_active ? 'text-emerald-400' : 'text-wecom-muted'"
          >
            {{
              scanStatus.background_scanner_active ? t('realtime.running') : t('realtime.stopped')
            }}
          </span>
          <span v-if="scanStatus.next_scan" class="text-xs text-wecom-muted">
            <template v-if="scanStatus.next_scan.status === 'imminent'">(starting soon)</template>
            <template v-else-if="scanStatus.next_scan.status === 'paused'">(paused)</template>
            <template v-else-if="scanStatus.next_scan.status === 'waiting_first_scan'"
              >(waiting first)</template
            >
            <template v-else>({{ scanStatus.next_scan.seconds_until }}s)</template>
          </span>
        </div>

        <!-- Device count indicator -->
        <div
          class="px-3 py-2 bg-wecom-surface/50 rounded-lg border border-wecom-border flex items-center gap-2"
        >
          <span class="text-lg">📱</span>
          <span class="text-sm text-wecom-muted">
            <span class="font-semibold text-wecom-text">{{ scanStatus.device_count }}</span>
            device(s)
          </span>
        </div>
      </div>
    </div>

    <!-- Tabs -->
    <div class="flex gap-2">
      <button
        :class="[
          'px-4 py-2 rounded-lg font-medium transition-colors',
          activeTab === 'devices'
            ? 'bg-wecom-primary text-white'
            : 'bg-wecom-surface text-wecom-muted hover:text-wecom-text hover:bg-wecom-surface/80 border border-wecom-border',
        ]"
        @click="activeTab = 'devices'"
      >
        📱 {{ t('realtime.tab_devices') }}
      </button>
      <button
        :class="[
          'px-4 py-2 rounded-lg font-medium transition-colors',
          activeTab === 'settings'
            ? 'bg-wecom-primary text-white'
            : 'bg-wecom-surface text-wecom-muted hover:text-wecom-text hover:bg-wecom-surface/80 border border-wecom-border',
        ]"
        @click="activeTab = 'settings'"
      >
        ⚙️ Settings
      </button>
    </div>

    <!-- Devices Tab -->
    <div v-if="activeTab === 'devices'" class="space-y-6">
      <!-- Devices Header -->
      <div class="flex items-center justify-between">
        <div>
          <h2 class="text-lg font-semibold text-wecom-text">
            {{ t('realtime.device_management') }}
          </h2>
          <p class="text-sm text-wecom-muted">{{ t('realtime.device_management_subtitle') }}</p>
        </div>
        <div class="flex items-center gap-3">
          <div
            class="px-3 py-2 bg-wecom-surface/50 rounded-lg border border-wecom-border flex items-center gap-2"
          >
            <span class="text-lg">📱</span>
            <span class="text-sm text-wecom-muted">
              <span class="font-semibold text-wecom-text">{{ devicesStatus.total }}</span>
              {{ t('realtime.device_count') }},
              <span class="font-semibold text-emerald-400">{{ devicesStatus.running }}</span>
              {{ t('realtime.running_count') }}
            </span>
          </div>
          <button
            :disabled="devicesStatus.total === 0"
            class="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg flex items-center gap-2 transition-colors disabled:opacity-50"
            @click="startAllDevices"
          >
            ▶️ {{ t('realtime.start_all') }}
          </button>
          <button
            :disabled="devicesStatus.running === 0"
            class="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg flex items-center gap-2 transition-colors disabled:opacity-50"
            @click="stopAllDevices"
          >
            ⏹️ {{ t('realtime.stop_all') }}
          </button>
        </div>
      </div>

      <!-- Devices List -->
      <div v-if="Object.keys(devicesStatus.devices).length > 0" class="space-y-4">
        <div
          v-for="(device, serial) in devicesStatus.devices"
          :key="serial"
          class="bg-wecom-dark/80 backdrop-blur rounded-xl p-6 border border-wecom-border"
        >
          <div class="flex items-center justify-between">
            <!-- Device Info -->
            <div class="flex-1">
              <div class="flex items-center gap-3 mb-3">
                <h3 class="text-lg font-semibold text-wecom-text">{{ serial }}</h3>
                <span
                  :class="[
                    'px-2 py-1 rounded text-xs font-medium',
                    device.status === 'running'
                      ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                      : device.status === 'paused'
                        ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                        : device.status === 'starting'
                          ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                          : device.status === 'error'
                            ? 'bg-red-500/20 text-red-400 border border-red-500/30'
                            : 'bg-gray-500/20 text-gray-400 border border-gray-500/30',
                  ]"
                >
                  {{ device.status.toUpperCase() }}
                </span>
              </div>

              <!-- Metrics -->
              <div class="grid grid-cols-4 gap-4 mb-3">
                <div class="bg-wecom-surface/30 rounded-lg p-3">
                  <p class="text-xs text-wecom-muted">{{ t('realtime.responses_detected') }}</p>
                  <p class="text-xl font-semibold text-wecom-text">
                    {{ device.responses_detected }}
                  </p>
                </div>
                <div class="bg-wecom-surface/30 rounded-lg p-3">
                  <p class="text-xs text-wecom-muted">{{ t('realtime.replies_sent') }}</p>
                  <p class="text-xl font-semibold text-wecom-text">{{ device.replies_sent }}</p>
                </div>
                <div class="bg-wecom-surface/30 rounded-lg p-3">
                  <p class="text-xs text-wecom-muted">{{ t('realtime.started_at') }}</p>
                  <p class="text-sm text-wecom-text">
                    {{ device.started_at ? formatDate(device.started_at) : '-' }}
                  </p>
                </div>
                <div class="bg-wecom-surface/30 rounded-lg p-3">
                  <p class="text-xs text-wecom-muted">{{ t('realtime.last_scan') }}</p>
                  <p class="text-sm text-wecom-text">
                    {{ device.last_scan_at ? formatDate(device.last_scan_at) : '-' }}
                  </p>
                </div>
              </div>

              <!-- Message -->
              <p v-if="device.message" class="text-sm text-wecom-muted mb-2">
                ℹ️ {{ device.message }}
              </p>

              <!-- Errors -->
              <div v-if="device.errors && device.errors.length > 0" class="mb-3">
                <p class="text-xs text-red-400 mb-1">{{ t('realtime.errors') }}:</p>
                <div class="space-y-1">
                  <p
                    v-for="(error, idx) in device.errors.slice(-3)"
                    :key="idx"
                    class="text-xs text-red-300 bg-red-500/10 rounded px-2 py-1"
                  >
                    {{ error }}
                  </p>
                </div>
              </div>
            </div>

            <!-- Control Buttons -->
            <div class="flex items-center gap-2 ml-6">
              <button
                v-if="
                  device.status === 'idle' ||
                  device.status === 'stopped' ||
                  device.status === 'error'
                "
                class="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg flex items-center gap-2 transition-colors"
                @click="startDeviceFollowUp(serial)"
              >
                ▶️ {{ t('realtime.start') }}
              </button>
              <button
                v-if="device.status === 'running'"
                class="px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white rounded-lg flex items-center gap-2 transition-colors"
                @click="pauseDeviceFollowUp(serial)"
              >
                ⏸️ {{ t('realtime.pause') }}
              </button>
              <button
                v-if="device.status === 'paused'"
                class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg flex items-center gap-2 transition-colors"
                @click="resumeDeviceFollowUp(serial)"
              >
                ▶️ {{ t('realtime.resume') }}
              </button>
              <button
                v-if="
                  device.status === 'running' ||
                  device.status === 'paused' ||
                  device.status === 'starting'
                "
                class="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg flex items-center gap-2 transition-colors"
                @click="stopDeviceFollowUp(serial)"
              >
                ⏹️ {{ t('realtime.stop') }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Empty State -->
      <div
        v-else
        class="bg-wecom-dark/80 backdrop-blur rounded-xl p-12 border border-wecom-border text-center"
      >
        <p class="text-6xl mb-4">📱</p>
        <h3 class="text-lg font-semibold text-wecom-text mb-2">
          {{ t('realtime.no_devices_title') }}
        </h3>
        <p class="text-sm text-wecom-muted">{{ t('realtime.no_devices_subtitle') }}</p>
      </div>
    </div>

    <!-- Settings Tab -->
    <div v-if="activeTab === 'settings'" class="space-y-6">
      <!-- Settings Header -->
      <div class="flex items-center justify-between">
        <div>
          <h2 class="text-lg font-semibold text-wecom-text">{{ t('realtime.settings_title') }}</h2>
          <p class="text-sm text-wecom-muted">{{ t('realtime.settings_subtitle') }}</p>
        </div>
        <div class="flex items-center gap-3">
          <button
            class="px-4 py-2 bg-wecom-surface hover:bg-wecom-surface/80 text-wecom-text border border-wecom-border rounded-lg text-sm transition-colors"
            @click="resetSettings"
          >
            🔄 {{ t('realtime.reset_defaults') }}
          </button>
          <button
            :disabled="savingSettings"
            class="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg flex items-center gap-2 transition-colors disabled:opacity-50"
            @click="saveSettings"
          >
            {{
              savingSettings
                ? `💾 ${t('realtime.saving_settings')}`
                : `💾 ${t('realtime.save_settings')}`
            }}
          </button>
        </div>
      </div>

      <!-- Error Display -->
      <div v-if="settingsError" class="bg-red-500/10 border-l-4 border-red-500 rounded-lg p-4">
        <p class="text-sm text-red-400">
          {{ t('realtime.settings_save_failed') }} {{ settingsError }}
        </p>
      </div>

      <!-- Settings Cards -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- Basic Settings -->
        <div class="bg-wecom-dark/80 backdrop-blur rounded-xl p-6 border border-wecom-border">
          <h3 class="text-sm font-semibold text-wecom-text flex items-center gap-2 mb-4">
            ⚡ {{ t('realtime.basic_config') }}
          </h3>

          <div class="space-y-4">
            <!-- Scan Interval -->
            <div>
              <label class="block text-sm text-wecom-text font-medium mb-2">
                {{ t('realtime.scan_interval_label') }}
              </label>
              <input
                v-model.number="settings.scanInterval"
                type="number"
                min="10"
                max="3600"
                step="10"
                class="w-full px-4 py-2 bg-wecom-surface border border-wecom-border rounded-lg text-wecom-text"
              />
              <p class="text-xs text-wecom-muted mt-1">
                {{ t('realtime.scan_interval_desc') }}
              </p>
            </div>
          </div>
        </div>

        <!-- AI Reply Settings -->
        <div class="bg-wecom-dark/80 backdrop-blur rounded-xl p-6 border border-wecom-border">
          <h3 class="text-sm font-semibold text-wecom-text flex items-center gap-2 mb-4">
            🤖 {{ t('realtime.ai_config') }}
          </h3>

          <div class="space-y-4">
            <!-- Use AI Reply (Always enabled, cannot be unchecked) -->
            <div class="flex items-center justify-between">
              <div>
                <label class="text-sm text-wecom-text font-medium">{{
                  t('realtime.use_ai_reply')
                }}</label>
                <p class="text-xs text-wecom-muted mt-1">
                  {{ t('realtime.use_ai_reply_desc') }}
                </p>
              </div>
              <input
                :checked="true"
                type="checkbox"
                class="w-12 h-6 rounded-full bg-wecom-surface border border-wecom-border cursor-not-allowed"
                title="此选项始终启用"
                @click.prevent
              />
            </div>

            <!-- Send via Sidecar (Always enabled, cannot be unchecked) -->
            <div class="flex items-center justify-between">
              <div>
                <label class="text-sm text-wecom-text font-medium">{{
                  t('realtime.send_via_sidecar')
                }}</label>
                <p class="text-xs text-wecom-muted mt-1">
                  {{ t('realtime.send_via_sidecar_desc') }}
                </p>
              </div>
              <input
                :checked="true"
                type="checkbox"
                class="w-12 h-6 rounded-full bg-wecom-surface border border-wecom-border cursor-not-allowed"
                title="此选项始终启用"
                @click.prevent
              />
            </div>
          </div>
        </div>
      </div>

      <!-- Info Box -->
      <div class="bg-blue-500/10 border-l-4 border-blue-500 rounded-xl p-6">
        <h3 class="text-sm font-semibold text-blue-400 flex items-center gap-2 mb-3">
          ℹ️ {{ t('realtime.how_it_works') }}
        </h3>
        <div class="space-y-2 text-sm text-wecom-text">
          <p>• {{ t('realtime.how_it_works_1') }}</p>
          <p>• {{ t('realtime.how_it_works_2') }}</p>
          <p>• {{ t('realtime.how_it_works_3') }}</p>
          <p>• {{ t('realtime.how_it_works_4') }}</p>
        </div>
      </div>
    </div>
  </div>
</template>
<style scoped>
/* Dark theme input styling */
input[type='date'],
input[type='number'],
select {
  color-scheme: dark;
}

input[type='checkbox'] {
  accent-color: #1aad19;
}

/* Custom scrollbar for dark theme */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: rgba(31, 41, 55, 0.5);
}

::-webkit-scrollbar-thumb {
  background: rgba(75, 85, 99, 0.8);
  border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
  background: rgba(107, 114, 128, 0.8);
}
</style>
