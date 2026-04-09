<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  data: number[]
  width?: number
  height?: number
  color?: string
  showArea?: boolean
  animated?: boolean
}>(), {
  width: 120,
  height: 32,
  color: '#1AAD19',
  showArea: true,
  animated: true,
})

const points = computed(() => {
  if (props.data.length === 0) return ''
  
  const max = Math.max(...props.data, 1)
  const min = Math.min(...props.data, 0)
  const range = max - min || 1
  
  const stepX = props.width / Math.max(props.data.length - 1, 1)
  const padding = 2
  const usableHeight = props.height - padding * 2
  
  return props.data.map((value, i) => {
    const x = i * stepX
    const y = padding + usableHeight - ((value - min) / range) * usableHeight
    return `${x},${y}`
  }).join(' ')
})

const areaPath = computed(() => {
  if (props.data.length === 0) return ''
  
  const max = Math.max(...props.data, 1)
  const min = Math.min(...props.data, 0)
  const range = max - min || 1
  
  const stepX = props.width / Math.max(props.data.length - 1, 1)
  const padding = 2
  const usableHeight = props.height - padding * 2
  
  const pathPoints = props.data.map((value, i) => {
    const x = i * stepX
    const y = padding + usableHeight - ((value - min) / range) * usableHeight
    return `${x},${y}`
  })
  
  return `M0,${props.height} L${pathPoints.join(' L')} L${props.width},${props.height} Z`
})

const lastValue = computed(() => props.data[props.data.length - 1] || 0)
const prevValue = computed(() => props.data[props.data.length - 2] || 0)
const trend = computed(() => {
  if (prevValue.value === 0) return 0
  return ((lastValue.value - prevValue.value) / prevValue.value) * 100
})
</script>

<template>
  <div class="flex items-center gap-3">
    <svg 
      :width="width" 
      :height="height" 
      class="overflow-visible"
    >
      <defs>
        <linearGradient :id="`sparkline-grad-${$.uid}`" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" :stop-color="color" stop-opacity="0.3" />
          <stop offset="100%" :stop-color="color" stop-opacity="0" />
        </linearGradient>
      </defs>
      
      <!-- Area fill -->
      <path
        v-if="showArea && areaPath"
        :d="areaPath"
        :fill="`url(#sparkline-grad-${$.uid})`"
        class="transition-all duration-500"
      />
      
      <!-- Line -->
      <polyline
        v-if="points"
        :points="points"
        fill="none"
        :stroke="color"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
        class="transition-all duration-500"
        :class="{ 'animate-draw': animated }"
      />
      
      <!-- End dot -->
      <circle
        v-if="data.length > 0"
        :cx="width"
        :cy="points.split(' ').pop()?.split(',')[1] || height / 2"
        r="3"
        :fill="color"
        class="animate-pulse"
      />
    </svg>
    
    <!-- Trend indicator -->
    <div v-if="data.length > 1" class="text-xs">
      <span 
        :class="trend >= 0 ? 'text-emerald-400' : 'text-rose-400'"
        class="font-semibold"
      >
        {{ trend >= 0 ? '↑' : '↓' }} {{ Math.abs(trend).toFixed(0) }}%
      </span>
    </div>
  </div>
</template>

<style scoped>
.animate-draw {
  stroke-dasharray: 1000;
  stroke-dashoffset: 1000;
  animation: draw 1.5s ease-out forwards;
}

@keyframes draw {
  to {
    stroke-dashoffset: 0;
  }
}
</style>

