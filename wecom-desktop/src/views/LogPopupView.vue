<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useLogStore } from '../stores/logs'
import LogStream from '../components/LogStream.vue'

const route = useRoute()
const logStore = useLogStore()

// Get serial from route
const serial = computed(() => route.params.serial as string)

// Filter settings
const levelFilter = ref<string>('all')
const searchQuery = ref('')
const autoScroll = ref(true)

// Always on top state (will be synced with Electron)
const isAlwaysOnTop = ref(true)
const isElectron = ref(false)

// Toggle always on top
async function toggleAlwaysOnTop() {
  if (window.electronAPI?.logPopup) {
    const newValue = !isAlwaysOnTop.value
    const result = await window.electronAPI.logPopup.setAlwaysOnTop(newValue)
    // Update state based on actual result from Electron
    isAlwaysOnTop.value = result
  }
}

// Sync initial state with Electron
async function syncAlwaysOnTopState() {
  if (window.electronAPI?.logPopup) {
    isElectron.value = true
    isAlwaysOnTop.value = await window.electronAPI.logPopup.isAlwaysOnTop()
  }
}

// Filtered logs
const filteredLogs = computed(() => {
  let logs = logStore.getDeviceLogs(serial.value)
  
  if (levelFilter.value !== 'all') {
    logs = logs.filter((log) => log.level === levelFilter.value)
  }
  
  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase()
    logs = logs.filter(
      (log) =>
        log.message.toLowerCase().includes(query) ||
        log.source?.toLowerCase().includes(query)
    )
  }
  
  return logs
})

// Clear logs
function clearLogs() {
  logStore.clearLogs(serial.value)
}

// Export logs
function exportLogs() {
  if (filteredLogs.value.length === 0) return

  const content = filteredLogs.value
    .map((log) => `[${log.timestamp}] [${log.level}] ${log.message}`)
    .join('\n')

  const blob = new Blob([content], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `wecom-logs-${serial.value}-${Date.now()}.txt`
  a.click()
  URL.revokeObjectURL(url)
}

// Connect to log stream and sync state
onMounted(async () => {
  if (serial.value) {
    logStore.connectLogStream(serial.value)
  }
  // Sync always-on-top state with Electron
  await syncAlwaysOnTopState()
})

// Watch for serial changes
watch(serial, (newSerial) => {
  if (newSerial) {
    logStore.connectLogStream(newSerial)
  }
})
</script>

<template>
  <div class="h-screen flex flex-col bg-wecom-darker overflow-hidden">
    <!-- Header with drag region for window movement -->
    <header class="drag-region h-10 bg-wecom-dark border-b border-wecom-border flex items-center px-3 shrink-0 gap-2">
      <!-- Traffic lights spacer (macOS) -->
      <div class="w-16 shrink-0"></div>
      
      <!-- Title -->
      <div class="flex-1 text-center">
        <span class="text-xs font-mono text-wecom-text">
          📋 {{ serial }}
        </span>
      </div>
      
      <!-- Always on top toggle -->
      <button
        v-if="isElectron"
        @click="toggleAlwaysOnTop"
        class="no-drag btn-secondary text-xs px-2 py-1"
        :class="isAlwaysOnTop ? '' : 'bg-wecom-primary/20 text-wecom-primary'"
        :title="isAlwaysOnTop ? 'Click to unpin from top' : 'Click to pin on top'"
      >
        {{ isAlwaysOnTop ? '📍' : '📌' }}
      </button>
      <span 
        v-else 
        class="text-xs text-wecom-muted px-2"
        title="Always on top is only available in the desktop app"
      >
        📌
      </span>
    </header>

    <!-- Toolbar -->
    <div class="flex items-center gap-2 p-2 border-b border-wecom-border bg-wecom-dark/50 shrink-0">
      <!-- Level filter -->
      <select
        v-model="levelFilter"
        class="input-field text-xs py-1 px-2"
      >
        <option value="all">All</option>
        <option value="DEBUG">Debug</option>
        <option value="INFO">Info</option>
        <option value="WARNING">Warn</option>
        <option value="ERROR">Error</option>
      </select>
      
      <!-- Search -->
      <input
        v-model="searchQuery"
        type="text"
        placeholder="Search..."
        class="input-field text-xs py-1 px-2 flex-1"
      />
      
      <!-- Auto-scroll -->
      <label class="flex items-center gap-1 text-xs text-wecom-muted cursor-pointer whitespace-nowrap">
        <input
          type="checkbox"
          v-model="autoScroll"
          class="w-3 h-3 rounded border-wecom-border bg-wecom-surface text-wecom-primary"
        />
        Auto
      </label>
      
      <!-- Actions -->
      <button
        @click="clearLogs"
        class="btn-secondary text-xs px-2 py-1"
        title="Clear logs"
      >
        🗑️
      </button>
      <button
        @click="exportLogs"
        :disabled="filteredLogs.length === 0"
        class="btn-secondary text-xs px-2 py-1"
        title="Export logs"
      >
        📥
      </button>
    </div>

    <!-- Log count -->
    <div class="px-2 py-1 text-xs text-wecom-muted bg-wecom-dark/30 border-b border-wecom-border/50 shrink-0">
      {{ filteredLogs.length }} log(s)
    </div>

    <!-- Log content -->
    <div class="flex-1 min-h-0">
      <LogStream
        :logs="filteredLogs"
        :auto-scroll="autoScroll"
      />
    </div>
  </div>
</template>

<style scoped>
.drag-region {
  -webkit-app-region: drag;
}

.no-drag {
  -webkit-app-region: no-drag;
}
</style>
