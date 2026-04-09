<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'

export interface DataSeries {
  id: string
  name: string
  data: { time: string; value: number }[]
  color: string
  visible?: boolean
}

const props = withDefaults(defineProps<{
  series: DataSeries[]
  height?: number
  showGrid?: boolean
  showTooltip?: boolean
  animated?: boolean
  loading?: boolean
}>(), {
  height: 300,
  showGrid: true,
  showTooltip: true,
  animated: true,
  loading: false,
})

const emit = defineEmits<{
  (e: 'seriesToggle', seriesId: string, visible: boolean): void
}>()

const containerRef = ref<HTMLDivElement | null>(null)
const svgWidth = ref(600)
const hoveredPoint = ref<{
  x: number
  y: number
  time: string
  values: { name: string; value: number; color: string }[]
} | null>(null)
const isAnimating = ref(true)

const padding = { top: 20, right: 20, bottom: 40, left: 50 }

// Update SVG width on resize
onMounted(() => {
  updateWidth()
  window.addEventListener('resize', updateWidth)
  
  // Trigger animation
  setTimeout(() => {
    isAnimating.value = false
  }, 100)
})

onUnmounted(() => {
  window.removeEventListener('resize', updateWidth)
})

function updateWidth() {
  if (containerRef.value) {
    svgWidth.value = containerRef.value.clientWidth
  }
}

// Get all unique time points across all series
const allTimePoints = computed(() => {
  const times = new Set<string>()
  props.series.forEach(s => {
    if (s.visible !== false) {
      s.data.forEach(d => times.add(d.time))
    }
  })
  return Array.from(times).sort()
})

// Calculate scales
const xScale = computed(() => {
  const times = allTimePoints.value
  const width = svgWidth.value - padding.left - padding.right
  
  return (time: string) => {
    const index = times.indexOf(time)
    if (index === -1) return padding.left
    return padding.left + (index / Math.max(times.length - 1, 1)) * width
  }
})

const yMax = computed(() => {
  let max = 0
  props.series.forEach(s => {
    if (s.visible !== false) {
      s.data.forEach(d => {
        if (d.value > max) max = d.value
      })
    }
  })
  return Math.max(max * 1.1, 10) // Add 10% padding, minimum 10
})

const yScale = computed(() => {
  const height = props.height - padding.top - padding.bottom
  const max = yMax.value
  
  return (value: number) => {
    return padding.top + height - (value / max) * height
  }
})

// Generate path for a series
function getPath(series: DataSeries): string {
  if (series.data.length === 0) return ''
  
  const points = series.data.map(d => ({
    x: xScale.value(d.time),
    y: yScale.value(d.value),
  }))
  
  // Create smooth curve using bezier
  let path = `M ${points[0].x} ${points[0].y}`
  
  for (let i = 1; i < points.length; i++) {
    const prev = points[i - 1]
    const curr = points[i]
    const cpx = (prev.x + curr.x) / 2
    path += ` Q ${cpx} ${prev.y} ${cpx} ${(prev.y + curr.y) / 2}`
    path += ` Q ${cpx} ${curr.y} ${curr.x} ${curr.y}`
  }
  
  return path
}

// Generate area path for gradient fill
function getAreaPath(series: DataSeries): string {
  if (series.data.length === 0) return ''
  
  const points = series.data.map(d => ({
    x: xScale.value(d.time),
    y: yScale.value(d.value),
  }))
  
  const baseline = props.height - padding.bottom
  
  let path = `M ${points[0].x} ${baseline}`
  path += ` L ${points[0].x} ${points[0].y}`
  
  for (let i = 1; i < points.length; i++) {
    const prev = points[i - 1]
    const curr = points[i]
    const cpx = (prev.x + curr.x) / 2
    path += ` Q ${cpx} ${prev.y} ${cpx} ${(prev.y + curr.y) / 2}`
    path += ` Q ${cpx} ${curr.y} ${curr.x} ${curr.y}`
  }
  
  path += ` L ${points[points.length - 1].x} ${baseline}`
  path += ' Z'
  
  return path
}

// Y-axis ticks
const yTicks = computed(() => {
  const max = yMax.value
  const tickCount = 5
  const ticks: number[] = []
  
  for (let i = 0; i <= tickCount; i++) {
    ticks.push(Math.round((max / tickCount) * i))
  }
  
  return ticks
})

// X-axis labels (show subset to avoid crowding)
const xLabels = computed(() => {
  const times = allTimePoints.value
  if (times.length <= 7) return times
  
  const step = Math.ceil(times.length / 7)
  return times.filter((_, i) => i % step === 0 || i === times.length - 1)
})

// Handle mouse move for tooltip
function handleMouseMove(event: MouseEvent) {
  if (!props.showTooltip) return
  
  const svg = event.currentTarget as SVGElement
  const rect = svg.getBoundingClientRect()
  const x = event.clientX - rect.left
  
  // Find closest time point
  const times = allTimePoints.value
  if (times.length === 0) {
    hoveredPoint.value = null
    return
  }
  
  let closestTime = times[0]
  let closestX = xScale.value(times[0])
  let minDist = Math.abs(x - closestX)
  
  for (const time of times) {
    const tx = xScale.value(time)
    const dist = Math.abs(x - tx)
    if (dist < minDist) {
      minDist = dist
      closestTime = time
      closestX = tx
    }
  }
  
  // Get values for all visible series at this time
  const values: { name: string; value: number; color: string }[] = []
  
  props.series.forEach(s => {
    if (s.visible === false) return
    const point = s.data.find(d => d.time === closestTime)
    if (point) {
      values.push({
        name: s.name,
        value: point.value,
        color: s.color,
      })
    }
  })
  
  hoveredPoint.value = {
    x: closestX,
    y: event.clientY - rect.top,
    time: closestTime,
    values,
  }
}

function handleMouseLeave() {
  hoveredPoint.value = null
}

// Format time for display
function formatTimeLabel(time: string): string {
  // Handle different formats
  if (time.includes('W')) {
    // Week format: 2024-W01
    return time
  }
  if (time.length === 7) {
    // Month format: 2024-01
    return time
  }
  if (time.length === 10) {
    // Day format: 2024-01-15
    const date = new Date(time)
    return `${date.getMonth() + 1}/${date.getDate()}`
  }
  if (time.includes(':')) {
    // Hour format: 2024-01-15 14:00
    const parts = time.split(' ')
    return parts[1] || time
  }
  return time
}

// Visible series for rendering
const visibleSeries = computed(() => props.series.filter(s => s.visible !== false))

// Path length for animation
const pathLengths = ref<Record<string, number>>({})

function setPathLength(id: string, el: SVGPathElement | null) {
  if (el) {
    pathLengths.value[id] = el.getTotalLength()
  }
}
</script>

<template>
  <div ref="containerRef" class="relative w-full">
    <!-- Loading state -->
    <div 
      v-if="loading"
      class="absolute inset-0 flex items-center justify-center bg-wecom-dark/50 backdrop-blur-sm rounded-lg z-10"
    >
      <div class="flex flex-col items-center gap-3">
        <div class="w-8 h-8 rounded-full border-2 border-wecom-primary/30 border-t-wecom-primary animate-spin" />
        <span class="text-sm text-wecom-muted">Loading chart data...</span>
      </div>
    </div>
    
    <!-- SVG Chart -->
    <svg 
      :width="svgWidth" 
      :height="height"
      class="overflow-visible"
      @mousemove="handleMouseMove"
      @mouseleave="handleMouseLeave"
    >
      <defs>
        <!-- Gradient definitions for each series -->
        <linearGradient 
          v-for="s in series" 
          :key="`grad-${s.id}`"
          :id="`area-gradient-${s.id}`"
          x1="0%" y1="0%" x2="0%" y2="100%"
        >
          <stop offset="0%" :stop-color="s.color" stop-opacity="0.3" />
          <stop offset="100%" :stop-color="s.color" stop-opacity="0" />
        </linearGradient>
        
        <!-- Glow filter -->
        <filter id="line-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="2" result="coloredBlur"/>
          <feMerge>
            <feMergeNode in="coloredBlur"/>
            <feMergeNode in="SourceGraphic"/>
          </feMerge>
        </filter>
      </defs>
      
      <!-- Grid lines -->
      <g v-if="showGrid" class="grid-lines">
        <!-- Horizontal grid lines -->
        <line 
          v-for="tick in yTicks"
          :key="`grid-h-${tick}`"
          :x1="padding.left"
          :x2="svgWidth - padding.right"
          :y1="yScale(tick)"
          :y2="yScale(tick)"
          stroke="currentColor"
          class="text-wecom-border/30"
          stroke-dasharray="4,4"
        />
        
        <!-- Vertical grid lines for time points -->
        <line 
          v-for="time in xLabels"
          :key="`grid-v-${time}`"
          :x1="xScale(time)"
          :x2="xScale(time)"
          :y1="padding.top"
          :y2="height - padding.bottom"
          stroke="currentColor"
          class="text-wecom-border/20"
          stroke-dasharray="4,4"
        />
      </g>
      
      <!-- Y-axis -->
      <g class="y-axis">
        <line
          :x1="padding.left"
          :x2="padding.left"
          :y1="padding.top"
          :y2="height - padding.bottom"
          stroke="currentColor"
          class="text-wecom-border"
        />
        <g v-for="tick in yTicks" :key="`y-tick-${tick}`">
          <text
            :x="padding.left - 10"
            :y="yScale(tick)"
            text-anchor="end"
            dominant-baseline="middle"
            class="text-xs fill-wecom-muted"
          >
            {{ tick }}
          </text>
        </g>
      </g>
      
      <!-- X-axis -->
      <g class="x-axis">
        <line
          :x1="padding.left"
          :x2="svgWidth - padding.right"
          :y1="height - padding.bottom"
          :y2="height - padding.bottom"
          stroke="currentColor"
          class="text-wecom-border"
        />
        <g v-for="time in xLabels" :key="`x-label-${time}`">
          <text
            :x="xScale(time)"
            :y="height - padding.bottom + 20"
            text-anchor="middle"
            class="text-xs fill-wecom-muted"
          >
            {{ formatTimeLabel(time) }}
          </text>
        </g>
      </g>
      
      <!-- Area fills -->
      <g class="areas">
        <path
          v-for="s in visibleSeries"
          :key="`area-${s.id}`"
          :d="getAreaPath(s)"
          :fill="`url(#area-gradient-${s.id})`"
          class="transition-opacity duration-300"
          :class="{ 'opacity-50': hoveredPoint && !hoveredPoint.values.some(v => v.name === s.name) }"
        />
      </g>
      
      <!-- Line paths -->
      <g class="lines">
        <path
          v-for="s in visibleSeries"
          :key="`line-${s.id}`"
          :ref="(el) => setPathLength(s.id, el as SVGPathElement)"
          :d="getPath(s)"
          fill="none"
          :stroke="s.color"
          stroke-width="2.5"
          stroke-linecap="round"
          stroke-linejoin="round"
          class="transition-all duration-300"
          :class="{ 
            'opacity-30': hoveredPoint && !hoveredPoint.values.some(v => v.name === s.name),
            'drop-shadow-md': hoveredPoint?.values.some(v => v.name === s.name)
          }"
          :filter="hoveredPoint?.values.some(v => v.name === s.name) ? 'url(#line-glow)' : ''"
          :style="animated && isAnimating ? {
            strokeDasharray: pathLengths[s.id] || 1000,
            strokeDashoffset: pathLengths[s.id] || 1000,
            animation: `drawLine 1.5s ease-out forwards`,
            animationDelay: `${visibleSeries.indexOf(s) * 200}ms`
          } : {}"
        />
      </g>
      
      <!-- Data points -->
      <g class="points">
        <template v-for="s in visibleSeries" :key="`points-${s.id}`">
          <circle
            v-for="(d, i) in s.data"
            :key="`point-${s.id}-${i}`"
            :cx="xScale(d.time)"
            :cy="yScale(d.value)"
            :r="hoveredPoint?.time === d.time ? 6 : 0"
            :fill="s.color"
            class="transition-all duration-200"
            :class="{ 'drop-shadow-lg': hoveredPoint?.time === d.time }"
          />
        </template>
      </g>
      
      <!-- Hover line -->
      <line
        v-if="hoveredPoint"
        :x1="hoveredPoint.x"
        :x2="hoveredPoint.x"
        :y1="padding.top"
        :y2="height - padding.bottom"
        stroke="currentColor"
        class="text-wecom-muted"
        stroke-width="1"
        stroke-dasharray="4,4"
      />
    </svg>
    
    <!-- Tooltip -->
    <div
      v-if="hoveredPoint && showTooltip"
      class="absolute pointer-events-none z-20 bg-wecom-dark/95 backdrop-blur border border-wecom-border rounded-lg px-3 py-2 shadow-xl"
      :style="{
        left: `${Math.min(hoveredPoint.x + 10, svgWidth - 150)}px`,
        top: `${Math.max(hoveredPoint.y - 10, 10)}px`,
        transform: hoveredPoint.x > svgWidth - 150 ? 'translateX(-100%)' : ''
      }"
    >
      <div class="text-xs text-wecom-muted mb-2 font-medium">
        {{ hoveredPoint.time }}
      </div>
      <div class="space-y-1">
        <div
          v-for="v in hoveredPoint.values"
          :key="v.name"
          class="flex items-center gap-2 text-sm"
        >
          <span 
            class="w-2.5 h-2.5 rounded-full"
            :style="{ backgroundColor: v.color }"
          />
          <span class="text-wecom-muted">{{ v.name }}:</span>
          <span class="text-wecom-text font-semibold">{{ v.value }}</span>
        </div>
      </div>
    </div>
    
    <!-- No data state -->
    <div
      v-if="!loading && visibleSeries.length === 0"
      class="absolute inset-0 flex items-center justify-center"
    >
      <div class="text-center text-wecom-muted">
        <span class="text-4xl mb-2 block opacity-50">📈</span>
        <span>No data to display</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
@keyframes drawLine {
  to {
    stroke-dashoffset: 0;
  }
}
</style>

