<script setup lang="ts">
import { ref, watch, nextTick, onMounted, computed } from 'vue'
import type { LogEntry } from '../stores/logs'

const props = defineProps<{
  logs: LogEntry[]
  autoScroll?: boolean
}>()

// "AI Down" badge: scan the most recent ~80 log entries for tell-tale upstream
// AI failures (server disconnect, HTTP error from the AI server, circuit
// breaker tripped). When several recent entries match, surface a sticky
// warning so an operator can see at a glance that the device isn't "stuck"
// — it's the AI server that's failing.
const AI_DOWN_PATTERNS = [
  /ServerDisconnectedError/i,
  /AI REQUEST ERROR/i,
  /AI server returned [45]\d\d/i,
  /CircuitBreaker.*open/i,
  /ai_failures=[1-9]/i,
] as const

const RECENT_WINDOW = 80
const AI_DOWN_THRESHOLD = 2

const aiDown = computed(() => {
  const recent = props.logs.slice(-RECENT_WINDOW)
  let hits = 0
  let lastHit: LogEntry | null = null
  for (const entry of recent) {
    const message = entry?.message ?? ''
    if (AI_DOWN_PATTERNS.some((re) => re.test(message))) {
      hits += 1
      lastHit = entry
      if (hits >= AI_DOWN_THRESHOLD) {
        break
      }
    }
  }
  return hits >= AI_DOWN_THRESHOLD ? { active: true as const, lastHit } : { active: false as const, lastHit: null }
})

const containerRef = ref<HTMLElement | null>(null)

// Level colors
const levelColors: Record<string, string> = {
  DEBUG: 'text-gray-400',
  INFO: 'text-blue-400',
  WARNING: 'text-yellow-400',
  ERROR: 'text-red-400',
}

// Level backgrounds
const levelBgs: Record<string, string> = {
  DEBUG: 'bg-gray-500/10',
  INFO: 'bg-blue-500/10',
  WARNING: 'bg-yellow-500/10',
  ERROR: 'bg-red-500/10',
}

// Source colors
const sourceColors: Record<string, string> = {
  sync: 'text-green-400',
  followup: 'text-blue-400',
}

// Source backgrounds
const sourceBgs: Record<string, string> = {
  sync: 'bg-green-500/10',
  followup: 'bg-blue-500/10',
}

// Format timestamp
function formatTime(timestamp: string): string {
  try {
    const date = new Date(timestamp)
    return date.toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return timestamp
  }
}

// Auto-scroll when new logs arrive
// Watch the last log's ID instead of length to handle the case when
// logs are trimmed (after reaching maxLogsPerDevice=1000, length stays constant)
watch(
  () => props.logs[props.logs.length - 1]?.id,
  async () => {
    if (props.autoScroll && containerRef.value) {
      await nextTick()
      containerRef.value.scrollTop = containerRef.value.scrollHeight
    }
  }
)

// Initial scroll to bottom
onMounted(async () => {
  if (props.autoScroll && containerRef.value) {
    await nextTick()
    containerRef.value.scrollTop = containerRef.value.scrollHeight
  }
})
</script>

<template>
  <div
    ref="containerRef"
    class="h-full overflow-y-auto bg-wecom-darker font-mono text-sm relative"
  >
    <!-- AI Down sticky banner -->
    <div
      v-if="aiDown.active"
      class="sticky top-0 z-10 px-3 py-1.5 bg-yellow-500/15 border-b border-yellow-500/30 text-yellow-200 text-xs flex items-center gap-2"
      title="Recent logs show repeated upstream AI failures. The device is alive — the AI server is the bottleneck."
    >
      <span class="px-1.5 py-0.5 rounded bg-yellow-500/30 font-semibold uppercase tracking-wide">AI Down</span>
      <span class="opacity-90">
        Upstream AI failing — replies will retry automatically.
      </span>
    </div>

    <!-- Empty state -->
    <div
      v-if="logs.length === 0"
      class="h-full flex flex-col items-center justify-center text-center p-8"
    >
      <div class="text-4xl mb-3 opacity-50">📝</div>
      <p class="text-wecom-muted">No logs yet</p>
      <p class="text-wecom-muted/50 text-xs mt-1">
        Logs will appear here when sync operations run
      </p>
    </div>

    <!-- Log entries -->
    <div v-else class="p-2 space-y-0.5">
      <div
        v-for="log in logs"
        :key="log.id"
        class="flex items-start gap-2 py-1 px-2 rounded hover:bg-wecom-surface/50 transition-colors log-entry-enter-active"
        :class="levelBgs[log.level]"
      >
        <!-- Timestamp -->
        <span class="text-wecom-muted/60 shrink-0 w-20">
          {{ formatTime(log.timestamp) }}
        </span>
        
        <!-- Level badge -->
        <span
          class="shrink-0 w-16 text-xs font-semibold"
          :class="levelColors[log.level]"
        >
          [{{ log.level }}]
        </span>

        <!-- Source badge (if available and not system) -->
        <span
          v-if="log.source && log.source !== 'system'"
          class="shrink-0 px-1.5 text-xs font-semibold rounded"
          :class="[sourceColors[log.source], sourceBgs[log.source]]"
        >
          [{{ log.source === 'followup' ? 'FOLLOWUP' : 'SYNC' }}]
        </span>

        <!-- Message -->
        <span
          class="flex-1 break-all"
          :class="log.level === 'ERROR' ? 'text-red-300' : 'text-wecom-text/90'"
        >
          {{ log.message }}
        </span>
      </div>
    </div>

    <!-- Scroll anchor -->
    <div class="h-1"></div>
  </div>
</template>

<style scoped>
/* Ensure proper scrolling */
:deep(.log-entry-enter-active) {
  animation: slideIn 0.15s ease-out;
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(-5px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>

