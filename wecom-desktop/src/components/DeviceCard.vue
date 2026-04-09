<script setup lang="ts">
import { computed } from 'vue'
import type { Device, SyncStatus } from '../services/api'
import { useDeviceStore } from '../stores/devices'

const props = defineProps<{
  device: Device
  selected: boolean
  mirroring: boolean
  syncStatus?: SyncStatus
}>()

const emit = defineEmits<{
  toggleSelect: []
  toggleMirror: [start: boolean]
  stopSync: []
  clearSync: []
  openSidecar: []
  openDetail: []
  openKefu: [name: string, department: string | null | undefined]
}>()

const deviceStore = useDeviceStore()

// Status color based on device state
const statusColor = computed(() => {
  if (!props.device.is_online) return 'bg-gray-500'
  if (props.syncStatus?.status === 'running') return 'bg-blue-500 status-pulse'
  if (props.syncStatus?.status === 'error') return 'bg-red-500'
  if (props.syncStatus?.status === 'completed') return 'bg-green-500'
  return 'bg-green-500'
})

// Status text
const statusText = computed(() => {
  if (!props.device.is_online) return 'Offline'
  if (props.syncStatus?.status === 'running') return 'Syncing...'
  if (props.syncStatus?.status === 'error') return 'Error'
  if (props.syncStatus?.status === 'completed') return 'Synced'
  if (props.syncStatus?.status === 'starting') return 'Starting...'
  return 'Online'
})

// Is sync in progress
const isSyncing = computed(() => 
  props.syncStatus?.status === 'running' || props.syncStatus?.status === 'starting'
)

// Is sync finished (completed, error, or stopped)
const isSyncFinished = computed(() =>
  props.syncStatus?.status === 'completed' || 
  props.syncStatus?.status === 'error' || 
  props.syncStatus?.status === 'stopped'
)
</script>

<template>
  <div
    class="bg-wecom-surface border rounded-xl p-4 card-hover transition-all duration-200 cursor-pointer"
    @click="emit('openDetail')"
    :class="[
      selected ? 'border-wecom-primary glow-green' : 'border-wecom-border',
      !device.is_online && 'opacity-60'
    ]"
  >
    <!-- Header -->
    <div class="flex items-start gap-3 mb-4">
      <!-- Selection checkbox -->
      <input
        type="checkbox"
        :checked="selected"
        @click.stop
        @change="emit('toggleSelect')"
        :disabled="!device.is_online"
        class="mt-1 w-4 h-4 rounded border-wecom-border bg-wecom-dark text-wecom-primary focus:ring-wecom-primary focus:ring-offset-wecom-surface cursor-pointer"
      />
      
      <!-- Device icon -->
      <div class="w-10 h-10 rounded-lg bg-wecom-dark flex items-center justify-center text-xl">
        📱
      </div>
      
      <!-- Device info -->
      <div class="flex-1 min-w-0">
        <h3 class="font-display font-semibold text-wecom-text truncate">
          {{ device.model || 'Unknown Device' }}
        </h3>
        <p class="text-xs text-wecom-muted font-mono truncate">
          {{ device.serial }}
        </p>
      </div>
      
      <!-- Status indicator -->
      <div class="flex items-center gap-2">
        <span
          class="w-2 h-2 rounded-full"
          :class="statusColor"
        ></span>
        <span class="text-xs text-wecom-muted">{{ statusText }}</span>
      </div>
    </div>

    <!-- Device details -->
    <div class="grid grid-cols-2 gap-2 mb-4 text-xs">
      <div class="flex items-center gap-2 text-wecom-muted">
        <span>🏭</span>
        <span>{{ device.manufacturer || 'Unknown' }}</span>
      </div>
      <div class="flex items-center gap-2 text-wecom-muted">
        <span>🤖</span>
        <span>Android {{ device.android_version || '?' }}</span>
      </div>
      <div v-if="device.battery_level" class="flex items-center gap-2 text-wecom-muted">
        <span>🔋</span>
        <span>{{ device.battery_level }}</span>
      </div>
      <div v-if="device.screen_resolution" class="flex items-center gap-2 text-wecom-muted">
        <span>📐</span>
        <span>{{ device.screen_resolution }}</span>
      </div>
    </div>

    <!-- Kefu info (if available) -->
    <div 
      v-if="device.kefu" 
      class="mb-4 p-2 bg-wecom-dark/50 border border-wecom-border rounded-lg cursor-pointer hover:bg-wecom-dark hover:border-wecom-primary/50 transition-colors"
      @click.stop="emit('openKefu', device.kefu.name, device.kefu.department)"
      title="Click to view kefu details"
    >
      <div class="flex items-center gap-2 text-xs">
        <span class="text-wecom-primary">👤</span>
        <span class="font-medium text-wecom-text">{{ device.kefu.name }}</span>
        <span v-if="device.kefu.department" class="text-wecom-muted">· {{ device.kefu.department }}</span>
        <span v-if="device.kefu.verification_status" class="text-wecom-muted text-[10px] px-1.5 py-0.5 bg-wecom-surface rounded">
          {{ device.kefu.verification_status }}
        </span>
      </div>
    </div>

    <!-- Kefu loading skeleton -->
    <div 
      v-else-if="device.is_online && deviceStore.isDeviceInitializing(device.serial)"
      class="mb-4 p-2 bg-wecom-dark/50 border border-wecom-border rounded-lg relative overflow-hidden"
    >
      <div class="flex items-center gap-2 text-xs">
        <!-- Icon skeleton -->
        <span class="text-wecom-primary/40">👤</span>
        <!-- Name skeleton -->
        <div class="h-3.5 w-16 bg-wecom-border/50 rounded animate-pulse"></div>
        <!-- Department skeleton -->
        <span class="text-wecom-muted/40">·</span>
        <div class="h-3.5 w-20 bg-wecom-border/50 rounded animate-pulse" style="animation-delay: 150ms"></div>
      </div>
      <!-- Shimmer overlay -->
      <div class="kefu-shimmer"></div>
    </div>

    <!-- Sync progress -->
    <div v-if="syncStatus && isSyncing" class="mb-4">
      <div class="flex items-center justify-between text-xs mb-1">
        <span class="text-wecom-muted">{{ syncStatus.message }}</span>
        <span class="text-wecom-primary">{{ syncStatus.progress }}%</span>
      </div>
      <div class="h-1.5 bg-wecom-dark rounded-full overflow-hidden">
        <div
          class="h-full bg-wecom-primary transition-all duration-300"
          :style="{ width: `${syncStatus.progress}%` }"
        ></div>
      </div>
      <div v-if="syncStatus.customers_synced" class="flex gap-4 mt-2 text-xs text-wecom-muted">
        <span>👥 {{ syncStatus.customers_synced }} streamers</span>
        <span>💬 {{ syncStatus.messages_added || 0 }} messages</span>
      </div>
    </div>

    <!-- Error display -->
    <div
      v-if="syncStatus?.status === 'error'"
      class="mb-4 p-2 bg-red-900/20 border border-red-500/30 rounded-lg"
    >
      <p class="text-xs text-red-400">{{ syncStatus.message }}</p>
    </div>

    <!-- Completed display -->
    <div
      v-if="syncStatus?.status === 'completed'"
      class="mb-4 p-2 bg-green-900/20 border border-green-500/30 rounded-lg"
    >
      <p class="text-xs text-green-400">✓ {{ syncStatus.message }}</p>
      <div v-if="syncStatus.customers_synced" class="flex gap-4 mt-1 text-xs text-green-400/70">
        <span>👥 {{ syncStatus.customers_synced }} streamers</span>
        <span>💬 {{ syncStatus.messages_added || 0 }} messages</span>
      </div>
    </div>

    <!-- Stopped display -->
    <div
      v-if="syncStatus?.status === 'stopped'"
      class="mb-4 p-2 bg-yellow-900/20 border border-yellow-500/30 rounded-lg"
    >
      <p class="text-xs text-yellow-400">⏹ {{ syncStatus.message }}</p>
    </div>

    <!-- Actions -->
    <div class="flex items-center gap-2">
      <!-- Mirror button -->
      <button
        @click.stop="emit('toggleMirror', !mirroring)"
        :disabled="!device.is_online || !deviceStore.mirrorAvailable"
        class="flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-all duration-200"
        :class="[
          mirroring
            ? 'bg-wecom-primary text-white'
            : 'bg-wecom-dark text-wecom-muted hover:text-wecom-text hover:bg-wecom-border'
        ]"
        :title="!deviceStore.mirrorAvailable ? 'Mirror is only available in the desktop app with scrcpy installed' : ''"
      >
        {{ mirroring ? '🖥️ Mirroring' : '🖥️ Mirror' }}
      </button>

      <!-- Sidecar button -->
      <button
        @click.stop="emit('openSidecar')"
        :disabled="!device.is_online"
        class="flex-1 py-2 px-3 rounded-lg text-sm font-medium bg-wecom-surface border border-wecom-border text-wecom-text hover:border-wecom-primary transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        🚗 Sidecar
      </button>
      
      <!-- Stop sync button (when syncing) -->
      <button
        v-if="isSyncing"
        @click.stop="emit('stopSync')"
        class="py-2 px-3 rounded-lg text-sm font-medium bg-red-600/20 text-red-400 hover:bg-red-600/30 transition-colors"
      >
        ⏹️ Stop
      </button>
      
      <!-- Clear button (when sync finished) -->
      <button
        v-if="isSyncFinished"
        @click.stop="emit('clearSync')"
        class="py-2 px-3 rounded-lg text-sm font-medium bg-wecom-dark text-wecom-muted hover:text-wecom-text hover:bg-wecom-border transition-colors"
      >
        ✓ Clear
      </button>
    </div>
  </div>
</template>

<style scoped>
/* Kefu loading shimmer effect */
.kefu-shimmer {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(26, 173, 25, 0.08) 20%,
    rgba(26, 173, 25, 0.15) 50%,
    rgba(26, 173, 25, 0.08) 80%,
    transparent 100%
  );
  animation: shimmerSlide 1.8s ease-in-out infinite;
  pointer-events: none;
}

@keyframes shimmerSlide {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(100%);
  }
}
</style>
