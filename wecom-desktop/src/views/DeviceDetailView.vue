<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDeviceStore } from '../stores/devices'
import { useLogStore } from '../stores/logs'
import { useSettingsStore } from '../stores/settings'
import { useI18n } from '../composables/useI18n'
import { api } from '../services/api'

const route = useRoute()
const router = useRouter()
const deviceStore = useDeviceStore()
const logStore = useLogStore()
const settingsStore = useSettingsStore()
const { t } = useI18n()

// Screenshot state
const screenshotUrl = ref<string | null>(null)
const screenshotLoading = ref(false)
const screenshotError = ref<string | null>(null)
let screenshotRefreshInterval: ReturnType<typeof setInterval> | null = null

const serial = computed(() => route.params.serial as string | undefined)
const device = computed(() =>
  deviceStore.selectedDevice ||
  deviceStore.devices.find((d) => d.serial === serial.value) ||
  null
)
const syncStatus = computed(() =>
  serial.value ? deviceStore.getSyncStatus(serial.value) : undefined
)
const mirroring = computed(() =>
  serial.value ? deviceStore.getMirrorStatus(serial.value) : false
)
const initializing = ref(false)
const initError = ref<string | null>(null)

const statusColor = computed(() => {
  if (!device.value?.is_online) return 'bg-gray-500'
  if (syncStatus.value?.status === 'running') return 'bg-blue-500'
  if (syncStatus.value?.status === 'error') return 'bg-red-500'
  if (syncStatus.value?.status === 'completed') return 'bg-green-500'
  return 'bg-green-500'
})

const statusText = computed(() => {
  if (!device.value?.is_online) return 'Offline'
  if (syncStatus.value?.status === 'running') return 'Syncing...'
  if (syncStatus.value?.status === 'error') return 'Error'
  if (syncStatus.value?.status === 'completed') return 'Synced'
  if (syncStatus.value?.status === 'starting') return 'Starting...'
  return 'Online'
})

async function load() {
  const currentSerial = serial.value
  if (!currentSerial) {
    router.push({ name: 'devices' })
    return
  }

  try {
    await deviceStore.fetchDeviceDetail(currentSerial)
  } catch (e) {
    console.error('Failed to load device detail', e)
  }
}

async function toggleMirror() {
  if (!serial.value) return
  if (mirroring.value) {
    await deviceStore.stopMirror(serial.value)
  } else {
    await deviceStore.startMirror(serial.value)
  }
}

async function startSync() {
  if (!serial.value) return
  await deviceStore.startSync([serial.value])
}

function openLogs() {
  if (!serial.value) return
  // Ensure the log stream is connected so logs appear immediately
  logStore.connectLogStream(serial.value)
  router.push({ name: 'logs', params: { serial: serial.value } })
}

function openSidecar() {
  if (!serial.value) return
  router.push({ name: 'sidecar', params: { serial: serial.value } })
}

async function initWecom() {
  if (!serial.value || initializing.value) return
  initializing.value = true
  initError.value = null
  
  try {
    const result = await deviceStore.initDevice(serial.value)
    if (!result.success) {
      initError.value = result.error || 'Failed to initialize'
    } else {
      // Refresh device detail to show kefu info
      await load()
    }
  } catch (e) {
    initError.value = e instanceof Error ? e.message : 'Failed to initialize WeCom'
  } finally {
    initializing.value = false
  }
}

// Screenshot functions
function refreshScreenshot() {
  if (!serial.value || !device.value?.is_online) return
  screenshotLoading.value = true
  screenshotError.value = null
  // Update the URL with a new timestamp to force refresh
  screenshotUrl.value = api.getScreenshotUrl(serial.value)
}

function onScreenshotLoad() {
  screenshotLoading.value = false
  screenshotError.value = null
}

function onScreenshotError() {
  screenshotLoading.value = false
  screenshotError.value = 'Failed to load screenshot'
}

function startAutoRefresh() {
  stopAutoRefresh()
  const refreshMs = settingsStore.settings.lowSpecMode ? 10000 : 3000
  screenshotRefreshInterval = setInterval(() => {
    if (document.visibilityState === 'hidden') return
    if (device.value?.is_online) {
      refreshScreenshot()
    }
  }, refreshMs)
}

function stopAutoRefresh() {
  if (screenshotRefreshInterval) {
    clearInterval(screenshotRefreshInterval)
    screenshotRefreshInterval = null
  }
}

onMounted(() => {
  settingsStore.load()
  load()
  // Connect to sync status stream for real-time progress updates
  if (serial.value) {
    deviceStore.connectSyncStatusStream(serial.value)
  }
})

// Watch for route changes
watch(
  () => route.params.serial,
  (newSerial, oldSerial) => {
    screenshotUrl.value = null
    screenshotError.value = null
    stopAutoRefresh()
    
    // Disconnect old sync status stream
    if (oldSerial) {
      deviceStore.disconnectSyncStatusStream(oldSerial as string)
    }
    
    // Connect to new sync status stream
    if (newSerial) {
      deviceStore.connectSyncStatusStream(newSerial as string)
    }
    
    load()
  },
)

// Watch for device availability and refresh screenshot
watch(
  () => device.value?.is_online,
  (isOnline) => {
    if (isOnline && serial.value && !screenshotUrl.value && !settingsStore.settings.lowSpecMode) {
      setTimeout(() => refreshScreenshot(), 300)
    }
  },
  { immediate: true }
)

onUnmounted(() => {
  deviceStore.clearSelectedDevice()
  stopAutoRefresh()
  // Disconnect sync status stream when leaving the page
  if (serial.value) {
    deviceStore.disconnectSyncStatusStream(serial.value)
  }
})
</script>

<template>
  <div class="p-6 space-y-6 animate-fade-in">
    <div class="flex items-center gap-3 text-sm text-wecom-muted">
      <router-link
        to="/devices"
        class="btn-secondary text-xs"
      >
        ← {{ t('device_detail.back_to_devices') }}
      </router-link>
      <span v-if="serial">{{ t('device_detail.serial') }}: {{ serial }}</span>
    </div>

    <div
      v-if="deviceStore.detailError"
      class="bg-red-900/20 border border-red-500/30 rounded-lg p-4 flex items-center gap-3"
    >
      <span class="text-red-400">⚠️</span>
      <div>
        <p class="text-red-400 font-medium">{{ t('device_detail.load_failed') }}</p>
        <p class="text-red-400/70 text-sm">{{ deviceStore.detailError }}</p>
      </div>
      <button class="btn-secondary text-sm ml-auto" @click="load">
        {{ t('common.retry') }}
      </button>
    </div>

    <div
      v-else-if="deviceStore.detailLoading && !device"
      class="bg-wecom-dark border border-wecom-border rounded-xl p-6 flex items-center justify-center text-wecom-muted"
    >
      {{ t('device_detail.loading') }}
    </div>

    <div v-else-if="device" class="space-y-4">
      <!-- Summary card -->
      <div class="bg-wecom-dark border border-wecom-border rounded-xl p-4 space-y-4">
        <div class="flex flex-col md:flex-row md:items-start md:justify-between gap-4">
          <div class="flex items-center gap-3">
            <div class="w-12 h-12 rounded-lg bg-wecom-surface flex items-center justify-center text-2xl">
              📱
            </div>
            <div>
              <p class="text-sm text-wecom-muted">Model</p>
              <h2 class="text-2xl font-display font-bold text-wecom-text">
                {{ device.model || 'Unknown device' }}
              </h2>
              <p class="text-sm text-wecom-muted">
                {{ device.manufacturer || 'Unknown manufacturer' }} · Brand: {{ device.brand || '—' }}
              </p>
              <p class="text-sm text-wecom-muted">
                Android {{ device.android_version || '?' }} (SDK {{ device.sdk_version || '—' }})
              </p>
              <p class="text-sm text-wecom-muted">
                Product: {{ device.product || '—' }} · Device: {{ device.device || '—' }}
              </p>
              <p class="text-sm text-wecom-muted">
                State: {{ device.state }}
              </p>
            </div>
          </div>
          <div class="text-right text-sm text-wecom-muted space-y-1">
            <div class="flex items-center justify-end gap-2">
              <span class="w-2 h-2 rounded-full" :class="statusColor"></span>
              <span>{{ statusText }}</span>
            </div>
            <p v-if="device.battery_level">Battery: {{ device.battery_level }} <span v-if="device.battery_status">({{ device.battery_status }})</span></p>
            <p v-if="device.screen_resolution">Resolution: {{ device.screen_resolution }}</p>
            <p v-if="device.screen_density">Density: {{ device.screen_density }}</p>
            <p>Online: {{ device.is_online ? 'Yes' : 'No' }}</p>
          </div>
        </div>

        <div class="flex flex-row gap-4">
          <!-- Device info cards -->
          <div class="flex-1 min-w-0 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 text-sm">
            <!-- Kefu info card (prominent) -->
            <div class="bg-wecom-primary/10 border border-wecom-primary/30 rounded-lg p-3 space-y-1">
              <p class="text-wecom-primary">👤 Agent</p>
              <p v-if="device.kefu" class="text-wecom-text font-semibold">{{ device.kefu.name }}</p>
              <p v-else class="text-wecom-muted font-semibold">Not initialized</p>
              <p v-if="device.kefu?.department" class="text-xs text-wecom-muted">
                Department: {{ device.kefu.department }}
              </p>
              <p v-if="device.kefu?.verification_status" class="text-xs text-wecom-muted">
                Status: {{ device.kefu.verification_status }}
              </p>
              <p v-if="!device.kefu" class="text-xs text-wecom-muted">
                Click "Initialize WeCom" to get kefu info
              </p>
            </div>
            <div class="bg-wecom-surface border border-wecom-border rounded-lg p-3 space-y-1">
              <p class="text-wecom-muted">Android</p>
              <p class="text-wecom-text font-semibold">
                {{ device.android_version || '?' }} (SDK {{ device.sdk_version || '—' }})
              </p>
              <p class="text-xs text-wecom-muted">Patch: {{ device.security_patch || '—' }}</p>
              <p class="text-xs text-wecom-muted">Build: {{ device.build_id || '—' }}</p>
            </div>
            <div class="bg-wecom-surface border border-wecom-border rounded-lg p-3 space-y-1">
              <p class="text-wecom-muted">Hardware</p>
              <p class="text-wecom-text font-semibold">{{ device.hardware || '—' }}</p>
              <p class="text-xs text-wecom-muted">ABI: {{ device.abi || '—' }}</p>
              <p class="text-xs text-wecom-muted" v-if="device.memory_total">Memory: {{ device.memory_total }}</p>
            </div>
            <div class="bg-wecom-surface border border-wecom-border rounded-lg p-3 space-y-1">
              <p class="text-wecom-muted">Storage</p>
              <p class="text-wecom-text font-semibold">{{ device.internal_storage || '—' }}</p>
              <p class="text-xs text-wecom-muted">USB Debugging: {{ device.usb_debugging === undefined ? '—' : device.usb_debugging ? 'Yes' : 'No' }}</p>
              <p class="text-xs text-wecom-muted" v-if="device.wifi_mac">WiFi MAC: {{ device.wifi_mac }}</p>
            </div>
            <div class="bg-wecom-surface border border-wecom-border rounded-lg p-3 space-y-1">
              <p class="text-wecom-muted">Display</p>
              <p class="text-wecom-text font-semibold">{{ device.screen_resolution || '—' }}</p>
              <p class="text-xs text-wecom-muted">Density: {{ device.screen_density || '—' }}</p>
            </div>
            <div class="bg-wecom-surface border border-wecom-border rounded-lg p-3 space-y-1">
              <p class="text-wecom-muted">Connection</p>
              <p class="text-wecom-text font-semibold">{{ device.connection_type || '—' }}</p>
              <p class="text-xs text-wecom-muted">Endpoint: {{ device.endpoint || '—' }}</p>
              <p class="text-xs text-wecom-muted">Transport ID: {{ device.transport_id ?? '—' }}</p>
              <p class="text-xs text-wecom-muted" v-if="device.usb">USB: {{ device.usb }}</p>
              <p class="text-xs text-wecom-muted" v-if="device.ip_address">IP: {{ device.ip_address }}</p>
              <p class="text-xs text-wecom-muted" v-if="device.tcp_port">TCP port: {{ device.tcp_port }}</p>
            </div>
            <div class="bg-wecom-surface border border-wecom-border rounded-lg p-3 space-y-1">
              <p class="text-wecom-muted">Identifiers</p>
              <p class="text-xs text-wecom-muted" v-if="device.features">Features: {{ device.features }}</p>
              <p class="text-xs text-wecom-muted" v-if="device.extra_props && Object.keys(device.extra_props).length === 0">No extra props</p>
              <div v-else-if="device.extra_props" class="space-y-1">
                <p
                  v-for="(val, key) in device.extra_props"
                  :key="key"
                  class="text-xs text-wecom-muted"
                >
                  {{ key }}: {{ val }}
                </p>
              </div>
            </div>
          </div>

          <!-- Phone frame with screenshot -->
          <div class="flex-shrink-0 flex flex-col items-center">
            <div class="phone-frame">
              <!-- Phone outer bezel -->
              <div class="phone-bezel">
                <!-- Speaker/earpiece -->
                <div class="phone-speaker"></div>
                <!-- Screen area -->
                <div class="phone-screen">
                  <div v-if="!device.is_online" class="phone-placeholder">
                    <span class="text-4xl mb-2">📵</span>
                    <span class="text-wecom-muted text-sm">Device Offline</span>
                  </div>
                  <div v-else-if="screenshotLoading && !screenshotUrl" class="phone-placeholder">
                    <span class="text-4xl mb-2 animate-pulse">📱</span>
                    <span class="text-wecom-muted text-sm">Loading...</span>
                  </div>
                  <div v-else-if="screenshotError && !screenshotUrl" class="phone-placeholder">
                    <span class="text-4xl mb-2">⚠️</span>
                    <span class="text-wecom-muted text-sm">{{ screenshotError }}</span>
                  </div>
                  <img 
                    v-else-if="screenshotUrl"
                    :src="screenshotUrl"
                    alt="Device Screenshot"
                    class="phone-screenshot"
                    :class="{ 'opacity-50': screenshotLoading }"
                    @load="onScreenshotLoad"
                    @error="onScreenshotError"
                  />
                  <div v-else class="phone-placeholder">
                    <span class="text-4xl mb-2">📱</span>
                    <span class="text-wecom-muted text-sm">No screenshot</span>
                    <button 
                      class="mt-2 text-xs text-wecom-primary hover:underline"
                      @click="refreshScreenshot"
                    >
                      Take screenshot
                    </button>
                  </div>
                </div>
                <!-- Home button / gesture bar -->
                <div class="phone-home-bar"></div>
              </div>
            </div>
            <!-- Screenshot controls -->
            <div class="flex items-center gap-2 mt-3">
              <button 
                class="btn-secondary text-xs px-2 py-1"
                :disabled="!device.is_online || screenshotLoading"
                @click="refreshScreenshot"
              >
                🔄 Refresh
              </button>
              <button 
                v-if="!screenshotRefreshInterval"
                class="btn-secondary text-xs px-2 py-1"
                :disabled="!device.is_online"
                @click="startAutoRefresh"
              >
                ▶️ Auto
              </button>
              <button 
                v-else
                class="btn-primary text-xs px-2 py-1"
                @click="stopAutoRefresh"
              >
                ⏸️ Stop
              </button>
            </div>
          </div>
        </div>

        <div class="flex flex-wrap gap-2">
          <button
            class="btn-primary text-sm"
            :disabled="!device.is_online || initializing"
            @click="initWecom"
          >
            <span v-if="initializing" class="animate-pulse">⏳</span>
            <span v-else>📱</span>
            {{ initializing ? 'Initializing...' : 'Initialize WeCom' }}
          </button>
          <button
            class="btn-primary text-sm"
            :disabled="!device.is_online || deviceStore.detailLoading"
            @click="startSync"
          >
            🚀 Sync now
          </button>
          <button
            class="btn-secondary text-sm"
            :disabled="!device.is_online || !deviceStore.mirrorAvailable"
            :title="!deviceStore.mirrorAvailable ? 'Mirror is only available in the desktop app with scrcpy installed' : ''"
            @click="toggleMirror"
          >
            {{ mirroring ? '🛑 Stop mirroring' : '🖥️ Start mirroring' }}
          </button>
          <button
            class="btn-secondary text-sm"
            :disabled="!device.is_online"
            @click="openSidecar"
          >
            🚗 Open sidecar
          </button>
          <button
            class="btn-secondary text-sm"
            @click="openLogs"
          >
            📋 View logs
          </button>
          <button
            class="btn-secondary text-sm"
            :disabled="deviceStore.detailLoading"
            @click="load"
          >
            🔄 Refresh
          </button>
        </div>
        
        <div v-if="initError" class="mt-2 text-xs text-red-400">
          ⚠️ {{ initError }}
        </div>
      </div>

      <!-- Sync status -->
      <div class="bg-wecom-dark border border-wecom-border rounded-xl p-4 space-y-3">
        <div class="flex items-center justify-between">
          <h3 class="text-lg font-display font-semibold text-wecom-text">
            Sync status
          </h3>
          <span class="text-xs text-wecom-muted">
            {{ syncStatus ? syncStatus.status : 'idle' }}
          </span>
        </div>

        <div v-if="!syncStatus" class="text-sm text-wecom-muted">
          No sync activity for this device yet.
        </div>

        <div v-else class="space-y-2">
          <div class="flex items-center justify-between text-sm">
            <span class="text-wecom-text">{{ syncStatus.message }}</span>
            <span class="text-wecom-primary font-medium">{{ syncStatus.progress }}%</span>
          </div>
          <div class="h-2 bg-wecom-surface rounded-full overflow-hidden">
            <div
              class="h-full bg-wecom-primary transition-all duration-300"
              :style="{ width: `${syncStatus.progress}%` }"
            ></div>
          </div>
          <div class="text-xs text-wecom-muted flex gap-4 flex-wrap">
            <span v-if="syncStatus.customers_synced !== undefined">
              👥 {{ syncStatus.customers_synced }} streamers
            </span>
            <span v-if="syncStatus.messages_added !== undefined">
              💬 {{ syncStatus.messages_added }} messages
            </span>
            <span v-if="syncStatus.errors?.length">
              ⚠️ {{ syncStatus.errors.length }} errors
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.phone-frame {
  perspective: 1000px;
}

.phone-bezel {
  position: relative;
  width: 180px;
  height: 380px;
  background: linear-gradient(145deg, #2a2a2a 0%, #1a1a1a 50%, #0f0f0f 100%);
  border-radius: 28px;
  padding: 12px 8px 20px 8px;
  box-shadow: 
    0 0 0 2px #3a3a3a,
    0 0 0 4px #1a1a1a,
    0 10px 40px rgba(0, 0, 0, 0.5),
    inset 0 1px 0 rgba(255, 255, 255, 0.1);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.phone-speaker {
  width: 50px;
  height: 4px;
  background: linear-gradient(90deg, #1a1a1a, #2a2a2a, #1a1a1a);
  border-radius: 2px;
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.5);
}

.phone-screen {
  width: 100%;
  height: 320px;
  background: #0a0a0a;
  border-radius: 8px;
  overflow: hidden;
  position: relative;
  box-shadow: inset 0 0 10px rgba(0, 0, 0, 0.5);
}

.phone-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
}

.phone-screenshot {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: top;
  transition: opacity 0.2s ease;
}

.phone-home-bar {
  width: 80px;
  height: 4px;
  background: linear-gradient(90deg, #3a3a3a, #4a4a4a, #3a3a3a);
  border-radius: 2px;
  margin-top: auto;
}

/* Responsive adjustments */
@media (max-width: 1280px) {
  .phone-bezel {
    width: 160px;
    height: 340px;
  }
  
  .phone-screen {
    height: 280px;
  }
}
</style>
