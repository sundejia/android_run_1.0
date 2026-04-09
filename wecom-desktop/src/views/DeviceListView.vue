<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useDeviceStore } from '../stores/devices'
import { useLogStore } from '../stores/logs'
import { useSettingsStore } from '../stores/settings'
import { useI18n } from '../composables/useI18n'
import DeviceCard from '../components/DeviceCard.vue'
import SyncButton from '../components/SyncButton.vue'

const router = useRouter()
const deviceStore = useDeviceStore()
const logStore = useLogStore()
const settingsStore = useSettingsStore()
const { settings } = storeToRefs(settingsStore)
const { t } = useI18n()

// Refresh interval
let refreshInterval: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  deviceStore.fetchDevices()
  settingsStore.load()
  const refreshMs = settings.value.lowSpecMode
    ? Math.max(settings.value.autoRefreshInterval, 10000)
    : Math.max(settings.value.autoRefreshInterval, 5000)
  refreshInterval = setInterval(() => {
    if (document.visibilityState === 'hidden') return
    deviceStore.fetchDevices()
  }, refreshMs)
})

onUnmounted(() => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
  }
})

// Note: Follow-up pause/resume is now handled automatically by the device store
// when sync status changes to completed/error/stopped

// Handle sync for selected devices
async function handleSyncSelected(resume: boolean = false) {
  const serials = Array.from(deviceStore.selectedDevices)
  if (serials.length === 0) return
  
  console.log(`[Sync] Starting ${resume ? 'RESUME ' : ''}sync for devices:`, serials)
  
  // Pause follow-up system before starting sync (store handles resume automatically)
  await deviceStore.pauseFollowupForSync(serials)
  
  // Connect log streams for all selected devices
  for (const serial of serials) {
    logStore.connectLogStream(serial)
  }
  
  // If sidecar mode is enabled, open sidecar page with first device
  // Additional devices can be added via drag-and-drop in sidecar view
  if (settings.value.sendViaSidecar && serials.length > 0) {
    // Navigate to sidecar with query params for all devices
    router.push({ 
      name: 'sidecar', 
      params: { serial: serials[0] },
      query: { devices: serials.join(',') }
    })
  }
  
  // Start sync (this returns immediately, sync runs in background)
  // The store will automatically resume followup when all syncs finish
  const combinedPrompt = settingsStore.combinedSystemPrompt
  console.log('[Sync] System prompt debug:')
  console.log('  - Custom prompt:', settings.value.systemPrompt ? `${settings.value.systemPrompt.length} chars` : '(empty)')
  console.log('  - Preset style:', settings.value.promptStyleKey)
  console.log('  - Combined prompt:', combinedPrompt ? `${combinedPrompt.length} chars: ${combinedPrompt.slice(0, 100)}...` : '(empty)')
  
  await deviceStore.startSync(serials, {
    send_via_sidecar: settings.value.sendViaSidecar,
    countdown_seconds: settings.value.countdownSeconds,
    timing_multiplier: settings.value.timingMultiplier,
    auto_placeholder: settings.value.autoPlaceholder,
    no_test_messages: settings.value.noTestMessages,
    // AI Reply settings
    use_ai_reply: settings.value.useAIReply,
    ai_server_url: settings.value.aiServerUrl,
    ai_reply_timeout: settings.value.aiReplyTimeout,
    system_prompt: combinedPrompt,
    // Resume from checkpoint
    resume: resume,
  })
}

// Handle resume sync for selected devices
async function handleResumeSync() {
  await handleSyncSelected(true)
}

// Handle mirror toggle
async function handleMirrorToggle(serial: string, start: boolean) {
  if (start) {
    await deviceStore.startMirror(serial)
  } else {
    await deviceStore.stopMirror(serial)
  }
}

function openSidecar(serial: string) {
  router.push({ name: 'sidecar', params: { serial } })
}

function openDeviceDetail(serial: string) {
  router.push({ name: 'device-detail', params: { serial } })
}

function openKefu(name: string, _department: string | null | undefined) {
  // Navigate to kefus page with search query to find the matching kefu
  // Only use the kefu name for search, not the department
  router.push({ name: 'kefus', query: { search: name } })
}
</script>

<template>
  <div class="p-6 space-y-6 animate-fade-in">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-2xl font-display font-bold text-wecom-text">
          {{ t('devices.title') }}
        </h2>
        <p class="text-sm text-wecom-muted mt-1">
          {{ t('devices.description') }}
        </p>
      </div>

      <div class="flex items-center gap-3">
        <!-- Refresh button -->
        <button
          @click="deviceStore.fetchDevices()"
          :disabled="deviceStore.loading"
          class="btn-secondary flex items-center gap-2"
        >
          <span :class="{ 'animate-spin': deviceStore.loading }">🔄</span>
          {{ t('common.refresh') }}
        </button>

        <!-- Sync selected button -->
        <SyncButton
          :disabled="!deviceStore.hasSelectedDevices"
          :loading="false"
          @click="handleSyncSelected(false)"
        >
          {{ t('devices.sync_selected', { count: deviceStore.selectedDevices.size }) }}
        </SyncButton>

        <!-- Resume Sync button -->
        <button
          :disabled="!deviceStore.hasSelectedDevices"
          @click="handleResumeSync"
          class="bg-amber-600 hover:bg-amber-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium py-2 px-4 rounded-lg transition-all duration-200 flex items-center gap-2"
          :title="t('devices.resume_sync_tooltip')"
        >
          <span>↩️</span>
          {{ t('devices.resume_sync') }}
        </button>
      </div>
    </div>

    <!-- Selection controls -->
    <div class="flex items-center gap-4 py-2 border-b border-wecom-border">
      <label class="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          :checked="deviceStore.allSelected"
          @change="deviceStore.selectAll()"
          class="w-4 h-4 rounded border-wecom-border bg-wecom-surface text-wecom-primary focus:ring-wecom-primary focus:ring-offset-wecom-darker"
        />
        <span class="text-sm text-wecom-muted">{{ t('devices.select_all') }}</span>
      </label>

      <span class="text-sm text-wecom-muted">
        {{ t('devices.selected_count', { selected: deviceStore.selectedDevices.size, total: deviceStore.devices.length }) }}
      </span>
    </div>

    <!-- Error state -->
    <div
      v-if="deviceStore.error"
      class="bg-red-900/20 border border-red-500/30 rounded-lg p-4 flex items-center gap-3"
    >
      <span class="text-red-400">⚠️</span>
      <div>
        <p class="text-red-400 font-medium">{{ t('devices.connection_error') }}</p>
        <p class="text-red-400/70 text-sm">{{ deviceStore.error }}</p>
      </div>
      <button
        @click="deviceStore.fetchDevices()"
        class="ml-auto btn-secondary text-sm"
      >
        {{ t('common.retry') }}
      </button>
    </div>

    <!-- Loading state -->
    <div
      v-if="deviceStore.loading && deviceStore.devices.length === 0"
      class="flex flex-col items-center justify-center py-20"
    >
      <div class="w-12 h-12 border-4 border-wecom-primary border-t-transparent rounded-full animate-spin"></div>
      <p class="text-wecom-muted mt-4">{{ t('devices.discovering') }}</p>
    </div>

    <!-- Empty state -->
    <div
      v-else-if="deviceStore.devices.length === 0 && !deviceStore.loading"
      class="flex flex-col items-center justify-center py-20 text-center"
    >
      <div class="text-6xl mb-4">📱</div>
      <h3 class="text-xl font-display font-semibold text-wecom-text mb-2">
        {{ t('devices.no_devices_title') }}
      </h3>
      <p class="text-wecom-muted max-w-md">
        {{ t('devices.no_devices_description') }}
      </p>
      <button
        @click="deviceStore.fetchDevices()"
        class="btn-primary mt-6"
      >
        {{ t('devices.scan_for_devices') }}
      </button>
    </div>

    <!-- Device grid -->
    <div
      v-else
      class="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4"
    >
      <DeviceCard
        v-for="device in deviceStore.devices"
        :key="device.serial"
        :device="device"
        :selected="deviceStore.selectedDevices.has(device.serial)"
        :mirroring="deviceStore.getMirrorStatus(device.serial)"
        :sync-status="deviceStore.getSyncStatus(device.serial)"
        @toggle-select="deviceStore.toggleDeviceSelection(device.serial)"
        @toggle-mirror="(start) => handleMirrorToggle(device.serial, start)"
        @stop-sync="deviceStore.stopSync(device.serial)"
        @clear-sync="deviceStore.clearSyncStatus(device.serial)"
        @open-sidecar="openSidecar(device.serial)"
        @open-detail="openDeviceDetail(device.serial)"
        @open-kefu="openKefu"
      />
    </div>
  </div>
</template>

