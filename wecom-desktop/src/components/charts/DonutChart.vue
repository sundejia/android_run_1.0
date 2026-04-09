<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'

interface ChartData {
  label: string
  value: number
  color: string
}

const props = withDefaults(defineProps<{
  data: ChartData[]
  size?: number
  strokeWidth?: number
  showLegend?: boolean
  centerLabel?: string
  centerValue?: string | number
  loading?: boolean
  minSegmentPercent?: number // Minimum visual percentage for small segments
}>(), {
  size: 160,
  strokeWidth: 24,
  showLegend: true,
  loading: false,
  minSegmentPercent: 3, // Ensure segments are at least 3% visually
})

const isAnimating = ref(true)
const hoveredIndex = ref<number | null>(null)

onMounted(() => {
  // Start animation after mount
  setTimeout(() => {
    isAnimating.value = false
  }, 100)
})

const total = computed(() => props.data.reduce((acc, item) => acc + item.value, 0))

const segments = computed(() => {
  const radius = (props.size - props.strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  
  // Calculate actual percentages
  const actualPercentages = props.data.map(item => ({
    ...item,
    actualPercent: total.value > 0 ? (item.value / total.value) * 100 : 0
  }))
  
  // Apply minimum visual percentage for small but non-zero values
  const adjustedData = actualPercentages.map(item => {
    if (item.value > 0 && item.actualPercent < props.minSegmentPercent) {
      return { ...item, visualPercent: props.minSegmentPercent }
    }
    return { ...item, visualPercent: item.actualPercent }
  })
  
  // Normalize to 100%
  const totalVisualPercent = adjustedData.reduce((acc, item) => acc + item.visualPercent, 0)
  const normalizedData = adjustedData.map(item => ({
    ...item,
    normalizedPercent: totalVisualPercent > 0 ? (item.visualPercent / totalVisualPercent) * 100 : 0
  }))
  
  let currentOffset = 0
  
  return normalizedData.map((item, index) => {
    const percentage = item.normalizedPercent / 100
    const strokeDasharray = `${percentage * circumference} ${circumference}`
    const strokeDashoffset = -currentOffset * circumference
    currentOffset += percentage
    
    return {
      ...item,
      index,
      percentage: item.actualPercent.toFixed(1), // Show actual percentage in legend
      strokeDasharray,
      strokeDashoffset,
      radius,
      circumference,
    }
  })
})

const center = computed(() => props.size / 2)

function onSegmentHover(index: number) {
  hoveredIndex.value = index
}

function onSegmentLeave() {
  hoveredIndex.value = null
}

const hoveredSegment = computed(() => {
  if (hoveredIndex.value === null) return null
  return segments.value[hoveredIndex.value]
})
</script>

<template>
  <div class="flex items-center gap-6">
    <!-- SVG Donut -->
    <div 
      class="relative transition-transform duration-300" 
      :style="{ width: `${size}px`, height: `${size}px` }"
      :class="{ 'scale-105': hoveredIndex !== null }"
    >
      <!-- Loading spinner overlay -->
      <div 
        v-if="loading"
        class="absolute inset-0 flex items-center justify-center"
      >
        <div 
          class="w-full h-full rounded-full border-4 border-wecom-surface"
          :style="{ borderTopColor: '#1AAD19' }"
          style="animation: spin 1s linear infinite;"
        />
      </div>
      
      <svg 
        v-else
        :width="size" 
        :height="size" 
        class="transform -rotate-90 transition-transform duration-300"
        :class="{ 'drop-shadow-lg': hoveredIndex !== null }"
      >
        <!-- Glow filter for hover effect -->
        <defs>
          <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="coloredBlur"/>
            <feMerge>
              <feMergeNode in="coloredBlur"/>
              <feMergeNode in="SourceGraphic"/>
            </feMerge>
          </filter>
        </defs>
        
        <!-- Background circle -->
        <circle
          :cx="center"
          :cy="center"
          :r="(size - strokeWidth) / 2"
          fill="none"
          stroke="currentColor"
          class="text-wecom-surface transition-all duration-300"
          :stroke-width="strokeWidth"
        />
        
        <!-- Data segments -->
        <circle
          v-for="(segment, index) in segments"
          :key="segment.label"
          :cx="center"
          :cy="center"
          :r="segment.radius"
          fill="none"
          :stroke="segment.color"
          :stroke-width="hoveredIndex === index ? strokeWidth + 6 : strokeWidth"
          :stroke-dasharray="segment.strokeDasharray"
          :stroke-dashoffset="isAnimating ? segment.circumference : segment.strokeDashoffset"
          stroke-linecap="round"
          class="transition-all duration-500 ease-out cursor-pointer"
          :class="{ 
            'opacity-40': hoveredIndex !== null && hoveredIndex !== index,
          }"
          :filter="hoveredIndex === index ? 'url(#glow)' : ''"
          :style="{ 
            animationDelay: `${index * 150}ms`,
            transformOrigin: 'center',
          }"
          @mouseenter="onSegmentHover(index)"
          @mouseleave="onSegmentLeave"
        />
      </svg>
      
      <!-- Center text -->
      <div 
        class="absolute inset-0 flex flex-col items-center justify-center transition-all duration-300"
        v-if="!loading && (centerLabel || centerValue)"
      >
        <!-- Show hovered segment info or default -->
        <template v-if="hoveredSegment">
          <span 
            class="text-2xl font-display font-bold transition-all duration-200"
            :style="{ color: hoveredSegment.color }"
          >
            {{ hoveredSegment.value }}
          </span>
          <span class="text-xs text-wecom-muted">{{ hoveredSegment.label }}</span>
          <span class="text-xs font-semibold" :style="{ color: hoveredSegment.color }">
            {{ hoveredSegment.percentage }}%
          </span>
        </template>
        <template v-else>
          <span class="text-2xl font-display font-bold text-wecom-text">
            {{ centerValue }}
          </span>
          <span class="text-xs text-wecom-muted">{{ centerLabel }}</span>
        </template>
      </div>
      
      <!-- Loading center text -->
      <div 
        v-if="loading"
        class="absolute inset-0 flex flex-col items-center justify-center"
      >
        <span class="text-sm text-wecom-muted animate-pulse">Loading...</span>
      </div>
    </div>
    
    <!-- Legend -->
    <div v-if="showLegend && !loading" class="flex flex-col gap-2">
      <div
        v-for="(segment, index) in segments"
        :key="segment.label"
        class="flex items-center gap-2 text-sm px-2 py-1 rounded-lg cursor-pointer transition-all duration-200"
        :class="{ 
          'bg-wecom-surface/80 scale-105': hoveredIndex === index,
          'opacity-50': hoveredIndex !== null && hoveredIndex !== index 
        }"
        @mouseenter="onSegmentHover(index)"
        @mouseleave="onSegmentLeave"
      >
        <span 
          class="w-3 h-3 rounded-full shrink-0 transition-transform duration-200"
          :class="{ 'scale-125': hoveredIndex === index }"
          :style="{ backgroundColor: segment.color }"
        />
        <span class="text-wecom-muted">{{ segment.label }}</span>
        <span class="text-wecom-text font-semibold ml-auto">{{ segment.value }}</span>
        <span class="text-wecom-muted text-xs">({{ segment.percentage }}%)</span>
      </div>
    </div>
    
    <!-- Loading legend skeleton -->
    <div v-if="loading && showLegend" class="flex flex-col gap-2">
      <div 
        v-for="i in 3" 
        :key="i"
        class="flex items-center gap-2 animate-pulse"
      >
        <span class="w-3 h-3 rounded-full bg-wecom-surface" />
        <span class="w-16 h-4 rounded bg-wecom-surface" />
        <span class="w-8 h-4 rounded bg-wecom-surface ml-auto" />
      </div>
    </div>
  </div>
</template>

<style scoped>
@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
