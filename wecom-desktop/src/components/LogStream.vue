<script setup lang="ts">
import { ref, shallowRef, watch, onMounted, onBeforeUnmount } from 'vue'
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

// Incremental "AI down" detector.
// Previous implementation re-scanned the last 80 entries (5 regex × 80 =
// 400 matches) inside a `computed` on every prop update. With 3 LogStream
// panels open and rapid log bursts, that was 1200 regex/log — enough to
// throttle the whole UI to ~3 log lines/s under load. Instead we now:
//   1. Maintain a sliding record of indices where AI-down matched, using
//      a single scan per newly-appended entry.
//   2. Recount matches that fall inside the trailing RECENT_WINDOW in O(k)
//      where k = hits, rather than O(80) regex evaluations.
// The component is reset whenever `props.logs` reference changes to a
// different array (e.g., clearLogs() replaces the ref with []).
const aiDown = shallowRef<{ active: boolean; lastHit: LogEntry | null }>({
  active: false,
  lastHit: null,
})

// Indices (into the current logs array, by array position) where an
// AI-down pattern was observed. Kept sorted ascending. When the logs
// array is trimmed (>= maxLogsPerDevice), old indices become negative
// after the shift and are dropped lazily.
let hitIndices: number[] = []
let lastProcessedLength = 0
let lastArrayRef: LogEntry[] | null = null

function resetDetector() {
  hitIndices = []
  lastProcessedLength = 0
  aiDown.value = { active: false, lastHit: null }
}

function matchesAiDown(message: string): boolean {
  for (const re of AI_DOWN_PATTERNS) {
    if (re.test(message)) return true
  }
  return false
}

function updateAiDown(logs: LogEntry[]) {
  // Detect "array identity replacement" (clearLogs or fresh mount) and
  // reset. For the in-place push + slice-on-flush pattern used by logs.ts,
  // the reference changes by one slice per flush and length grows, so we
  // can't rely on identity to keep state. Instead we key on length going
  // backwards as a cheap reset signal.
  if (lastArrayRef === null || logs.length < lastProcessedLength) {
    resetDetector()
    lastArrayRef = logs
  } else {
    lastArrayRef = logs
  }

  // Scan only newly appended entries since the last update.
  for (let i = lastProcessedLength; i < logs.length; i += 1) {
    const entry = logs[i]
    if (entry && matchesAiDown(entry.message ?? '')) {
      hitIndices.push(i)
    }
  }
  lastProcessedLength = logs.length

  // Drop hits that fell outside the trailing RECENT_WINDOW. Since
  // hitIndices is sorted ascending we can snip the prefix in one pass.
  const windowStart = Math.max(0, logs.length - RECENT_WINDOW)
  let drop = 0
  while (drop < hitIndices.length && hitIndices[drop] < windowStart) {
    drop += 1
  }
  if (drop > 0) hitIndices = hitIndices.slice(drop)

  if (hitIndices.length >= AI_DOWN_THRESHOLD) {
    const lastIdx = hitIndices[hitIndices.length - 1]
    aiDown.value = {
      active: true,
      lastHit: logs[lastIdx] ?? null,
    }
  } else {
    aiDown.value = { active: false, lastHit: null }
  }
}

watch(
  () => props.logs,
  (logs: LogEntry[]) => updateAiDown(logs),
  { immediate: true },
)

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

// rAF-throttled auto-scroll.
// The previous implementation watched the last-log id and performed a
// synchronous `scrollTop = scrollHeight` on every push. Reading
// `scrollHeight` forces layout; combined with three panels × bursts of
// logs, this was one of the hot paths starving the log pipeline.
// Now we coalesce into one scroll per animation frame no matter how many
// logs come in during that window.
let rafHandle: number | null = null
let pendingScroll = false

function scheduleAutoScroll() {
  if (!props.autoScroll) return
  pendingScroll = true
  if (rafHandle !== null) return
  rafHandle = requestAnimationFrame(() => {
    rafHandle = null
    if (!pendingScroll) return
    pendingScroll = false
    const el = containerRef.value
    if (!el) return
    el.scrollTop = el.scrollHeight
  })
}

watch(
  () => props.logs.length,
  (newLen: number, oldLen: number) => {
    if (newLen !== oldLen) scheduleAutoScroll()
  },
)

onMounted(() => {
  if (props.autoScroll && containerRef.value) {
    scheduleAutoScroll()
  }
})

onBeforeUnmount(() => {
  if (rafHandle !== null) {
    cancelAnimationFrame(rafHandle)
    rafHandle = null
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
/* Short, lightweight enter animation — the previous 0.15s slide compounded
 * badly when many entries arrived in the same frame, because each required
 * its own composite layer. 0.06s keeps the visual cue without pressuring
 * the compositor. */
:deep(.log-entry-enter-active) {
  animation: slideIn 0.06s ease-out;
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(-3px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
