<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useLogStore, type LogEntry } from '../stores/logs'
import { useDeviceStore } from '../stores/devices'
import { useI18n } from '../composables/useI18n'
import LogStream from '../components/LogStream.vue'

const route = useRoute()
const logStore = useLogStore()
const deviceStore = useDeviceStore()
const { t } = useI18n()

// Filter settings shared across panels
const levelFilter = ref<string>('all')
const sourceFilter = ref<'all' | 'sync' | 'followup'>('all')
const searchQuery = ref('')

// Auto-scroll setting
const autoScroll = ref(true)

// Multi-pane state
const maxPanels = 3
const panels = ref<string[]>([])
const focusedSerial = ref<string | null>(null)
const isDragOver = ref(false)
const dropMessage = ref(t('logs.drag_message'))

// Fixed tabs that should always be visible (empty after unified logging)
const FIXED_TABS: string[] = []

// Available devices for tab selection
const availableDevices = computed(() => {
  // Combine fixed tabs, devices from store, and devices with logs (ignore invalid keys)
  const deviceSerials = new Set([
    ...FIXED_TABS,
    ...deviceStore.devices.map((d) => d.serial),
    ...logStore.devicesWithLogs.filter((serial): serial is string => typeof serial === 'string'),
  ])
  return Array.from(deviceSerials)
})

const gridColsClass = computed(() => {
  if (panels.value.length === 1) return 'grid-cols-1'
  if (panels.value.length === 2) return 'grid-cols-2'
  return 'grid-cols-3'
})

// Currently focused serial for toolbar actions
const activeSerial = computed(() => focusedSerial.value || panels.value[0] || null)

function applyFilters(logs: LogEntry[]): LogEntry[] {
  let filtered = logs

  if (levelFilter.value !== 'all') {
    filtered = filtered.filter((log) => log.level === levelFilter.value)
  }

  if (sourceFilter.value !== 'all') {
    filtered = filtered.filter((log) => log.source === sourceFilter.value)
  }

  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase()
    filtered = filtered.filter(
      (log) =>
        log.message.toLowerCase().includes(query) || log.source?.toLowerCase().includes(query)
    )
  }

  return filtered
}

// Computed map of filtered logs per device - ensures reactivity when filters change
const filteredLogsMap = computed(() => {
  const map = new Map<string, LogEntry[]>()

  // Access filter values here to ensure Vue tracks them as dependencies
  const query = searchQuery.value
  const level = levelFilter.value
  const source = sourceFilter.value

  // Process all panels
  for (const serial of panels.value) {
    let logs = logStore.getDeviceLogs(serial)

    if (level !== 'all') {
      logs = logs.filter((log) => log.level === level)
    }

    if (source !== 'all') {
      logs = logs.filter((log) => log.source === source)
    }

    if (query) {
      const q = query.toLowerCase()
      logs = logs.filter(
        (log) => log.message.toLowerCase().includes(q) || log.source?.toLowerCase().includes(q)
      )
    }

    map.set(serial, logs)
  }

  return map
})

function filteredLogsFor(serial: string): LogEntry[] {
  return filteredLogsMap.value.get(serial) || applyFilters(logStore.getDeviceLogs(serial))
}

const filteredActiveLogs = computed(() => {
  if (!activeSerial.value) return []
  return filteredLogsFor(activeSerial.value)
})

function addPanel(serial: string, setFocus = true) {
  if (!serial) return

  if (!panels.value.includes(serial)) {
    if (panels.value.length >= maxPanels) {
      dropMessage.value = t('logs.max_devices_message')
      return
    }
    panels.value = [...panels.value, serial]
  }

  logStore.connectLogStream(serial)

  if (setFocus) {
    focusedSerial.value = serial
  }
}

function removePanel(serial: string) {
  panels.value = panels.value.filter((s) => s !== serial)
  if (focusedSerial.value === serial) {
    focusedSerial.value = panels.value[0] ?? null
  }
}

// Select a device tab (also used for clicks)
function selectDevice(serial: string) {
  addPanel(serial, true)
}

const LOGS_DRAG_MIME = 'application/x-wecom-device-serial'

function handleDragStart(serial: string, event: DragEvent) {
  event.dataTransfer?.setData(LOGS_DRAG_MIME, serial)
  event.dataTransfer?.setData('text/plain', serial)
  dropMessage.value = t('logs.drop_message')
}

function handleDragOver(event: DragEvent) {
  event.preventDefault()
  const hasDeviceData = event.dataTransfer?.types?.includes(LOGS_DRAG_MIME)
  isDragOver.value = !!hasDeviceData && panels.value.length < maxPanels
}

function handleDragLeave() {
  isDragOver.value = false
}

function handleDrop(event: DragEvent) {
  event.preventDefault()
  isDragOver.value = false

  const serial = event.dataTransfer?.getData(LOGS_DRAG_MIME)
  if (!serial) return

  if (!availableDevices.value.includes(serial)) {
    console.warn(`[Logs] Rejected drop: "${serial}" is not a known device serial`)
    return
  }

  addPanel(serial, focusedSerial.value === null)
}

// Clear logs for a specific device (defaults to active panel)
function clearCurrentLogs(serialOrEvent?: string | Event) {
  const target = typeof serialOrEvent === 'string' ? serialOrEvent : activeSerial.value
  if (target) {
    logStore.clearLogs(target)
  }
}

// Clear all logs and reset layout to initial empty state
function clearAllLogs() {
  const serials = new Set(
    [...logStore.devicesWithLogs, ...panels.value].filter(
      (serial): serial is string => typeof serial === 'string'
    )
  )

  serials.forEach((serial) => logStore.clearLogs(serial))
  panels.value = []
  focusedSerial.value = null
  dropMessage.value = t('logs.drag_message')
}

// Export logs for a specific device (defaults to active panel)
function exportLogs(serialOrEvent?: string | Event) {
  const target = typeof serialOrEvent === 'string' ? serialOrEvent : activeSerial.value
  if (!target) return

  const logs = filteredLogsFor(target)
  if (logs.length === 0) return

  const content = logs.map((log) => `[${log.timestamp}] [${log.level}] ${log.message}`).join('\n')

  const blob = new Blob([content], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `wecom-logs-${target}-${Date.now()}.txt`
  a.click()
  URL.revokeObjectURL(url)
}

// Open logs in a popup window (pinned on top)
function openLogPopup(serial: string) {
  if (window.electronAPI?.logPopup) {
    window.electronAPI.logPopup.open(serial)
  } else {
    // Fallback for browser: open in a new small window
    const width = 500
    const height = 400
    const left = window.screenX + window.innerWidth - width - 20
    const top = window.screenY + 20
    window.open(
      `/log-popup/${serial}`,
      `log-popup-${serial}`,
      `width=${width},height=${height},left=${left},top=${top},resizable=yes,scrollbars=yes`
    )
  }
}

// Initialize from route param
onMounted(() => {
  if (route.params.serial) {
    addPanel(route.params.serial as string)
  }
})

// Watch for route changes
watch(
  () => route.params.serial,
  (newSerial) => {
    if (newSerial) {
      addPanel(newSerial as string)
    }
  }
)
</script>

<template>
  <div class="h-full flex flex-col animate-fade-in">
    <!-- Header -->
    <div class="p-4 border-b border-wecom-border shrink-0">
      <div class="flex items-center justify-between mb-4">
        <div>
          <h2 class="text-xl font-display font-bold text-wecom-text">
            {{ t('logs.title') }}
          </h2>
          <p class="text-sm text-wecom-muted">
            {{ t('logs.subtitle') }}
          </p>
        </div>

        <div class="flex items-center gap-2">
          <button class="btn-secondary text-sm" @click="clearAllLogs">
            🗑️ {{ t('logs.clear_all') }}
          </button>
          <button
            :disabled="filteredActiveLogs.length === 0"
            class="btn-secondary text-sm"
            @click="exportLogs"
          >
            📥 {{ t('logs.export') }}
          </button>
        </div>
      </div>

      <!-- Filters -->
      <div class="flex items-center gap-4">
        <!-- Level filter -->
        <select v-model="levelFilter" class="input-field text-sm py-1.5">
          <option value="all">{{ t('logs.all_levels') }}</option>
          <option value="DEBUG">{{ t('logs.level_debug') }}</option>
          <option value="INFO">{{ t('logs.level_info') }}</option>
          <option value="WARNING">{{ t('logs.level_warning') }}</option>
          <option value="ERROR">{{ t('logs.level_error') }}</option>
        </select>

        <!-- Source filter buttons -->
        <div class="flex items-center gap-1 bg-wecom-surface rounded-lg p-1">
          <button
            class="px-3 py-1 text-sm rounded-md transition-colors"
            :class="
              sourceFilter === 'all'
                ? 'bg-wecom-primary text-white'
                : 'text-wecom-muted hover:text-wecom-text'
            "
            @click="sourceFilter = 'all'"
          >
            {{ t('logs.source_all') }}
          </button>
          <button
            class="px-3 py-1 text-sm rounded-md transition-colors"
            :class="
              sourceFilter === 'sync'
                ? 'bg-green-600 text-white'
                : 'text-wecom-muted hover:text-wecom-text'
            "
            @click="sourceFilter = 'sync'"
          >
            {{ t('logs.source_sync') }}
          </button>
          <button
            class="px-3 py-1 text-sm rounded-md transition-colors"
            :class="
              sourceFilter === 'followup'
                ? 'bg-blue-600 text-white'
                : 'text-wecom-muted hover:text-wecom-text'
            "
            @click="sourceFilter = 'followup'"
          >
            {{ t('logs.source_followup') }}
          </button>
        </div>

        <!-- Search -->
        <input
          v-model="searchQuery"
          type="text"
          :placeholder="t('logs.search_placeholder')"
          class="input-field text-sm py-1.5 flex-1 max-w-xs"
        />

        <!-- Auto-scroll toggle -->
        <label class="flex items-center gap-2 text-sm text-wecom-muted cursor-pointer">
          <input
            v-model="autoScroll"
            type="checkbox"
            class="w-4 h-4 rounded border-wecom-border bg-wecom-surface text-wecom-primary"
          />
          {{ t('logs.auto_scroll') }}
        </label>
      </div>
    </div>

    <!-- Device tabs -->
    <div class="flex border-b border-wecom-border shrink-0 overflow-x-auto">
      <button
        v-for="serial in availableDevices"
        :key="serial"
        draggable="true"
        class="px-4 py-2 text-sm font-medium whitespace-nowrap transition-colors"
        :class="[
          panels.includes(serial)
            ? 'text-wecom-primary border-b-2 border-wecom-primary bg-wecom-primary/5'
            : 'text-wecom-muted hover:text-wecom-text hover:bg-wecom-surface',
        ]"
        @dragstart="(event) => handleDragStart(serial, event)"
        @dragend="handleDragLeave"
        @click="selectDevice(serial)"
      >
        <span v-if="serial === 'followup'" class="flex items-center gap-1">
          🔄 {{ t('logs.tab_followup') }}
        </span>
        <span v-else>{{ serial }}</span>
        <span
          v-if="logStore.getDeviceLogs(serial).length > 0"
          class="ml-2 px-1.5 py-0.5 text-xs rounded-full bg-wecom-surface"
        >
          {{ logStore.getDeviceLogs(serial).length }}
        </span>
      </button>

      <div v-if="availableDevices.length === 0" class="px-4 py-2 text-sm text-wecom-muted">
        {{ t('logs.no_devices') }}
      </div>
    </div>

    <!-- Log content -->
    <div
      class="flex-1 overflow-hidden relative"
      @dragover.prevent="handleDragOver"
      @dragleave="handleDragLeave"
      @drop.prevent="handleDrop"
    >
      <div
        v-if="isDragOver"
        class="absolute inset-0 z-10 pointer-events-none flex items-center justify-center bg-wecom-primary/10 border-2 border-dashed border-wecom-primary text-wecom-primary font-medium"
      >
        <span>
          {{ panels.length >= maxPanels ? t('logs.max_panels_reached') : t('logs.release_to_add') }}
        </span>
      </div>

      <div v-if="panels.length > 0" class="h-full grid gap-2 p-2" :class="gridColsClass">
        <div
          v-for="serial in panels"
          :key="serial"
          class="flex flex-col min-h-0 border border-wecom-border rounded-lg bg-wecom-dark/60 overflow-hidden"
        >
          <div
            class="flex items-center justify-between px-3 py-2 border-b border-wecom-border bg-wecom-dark/80"
            @click="focusedSerial = serial"
          >
            <div class="flex items-center gap-2">
              <span
                class="px-2 py-1 rounded text-xs"
                :class="[
                  focusedSerial === serial
                    ? 'bg-wecom-primary/15 text-wecom-primary'
                    : 'bg-wecom-surface text-wecom-text',
                  serial !== 'followup' ? 'font-mono' : '',
                ]"
              >
                <template v-if="serial === 'followup'">🔄 {{ t('logs.tab_followup') }}</template>
                <template v-else>{{ serial }}</template>
              </span>
            </div>
            <div class="flex items-center gap-1">
              <button
                class="btn-secondary text-xs px-2 py-1"
                :title="t('logs.open_popup')"
                @click.stop="openLogPopup(serial)"
              >
                📌
              </button>
              <button
                class="btn-secondary text-xs px-2 py-1"
                :title="t('logs.clear_logs')"
                @click.stop="clearCurrentLogs(serial)"
              >
                🗑️
              </button>
              <button
                class="btn-secondary text-xs px-2 py-1"
                :disabled="filteredLogsFor(serial).length === 0"
                :title="t('logs.export_logs')"
                @click.stop="exportLogs(serial)"
              >
                📥
              </button>
              <button
                class="btn-secondary text-xs px-2 py-1"
                :title="t('logs.close_panel')"
                @click.stop="removePanel(serial)"
              >
                ✖️
              </button>
            </div>
          </div>
          <div class="flex-1 min-h-0">
            <LogStream :logs="filteredLogsFor(serial)" :auto-scroll="autoScroll" />
          </div>
        </div>
      </div>

      <div v-else class="h-full flex flex-col items-center justify-center text-center p-8">
        <div class="text-5xl mb-4">📋</div>
        <h3 class="text-lg font-display font-semibold text-wecom-text mb-2">
          {{ t('logs.empty_title') }}
        </h3>
        <p class="text-wecom-muted max-w-md">
          {{ dropMessage }}. {{ t('logs.empty_description') }}
        </p>
      </div>
    </div>
  </div>
</template>
