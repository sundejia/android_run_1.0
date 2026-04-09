<script setup lang="ts">
import { computed } from 'vue'

interface BarData {
  label: string
  value: number
  color?: string
  subLabel?: string
}

const props = withDefaults(defineProps<{
  data: BarData[]
  maxValue?: number
  showValues?: boolean
  barHeight?: number
  animated?: boolean
}>(), {
  showValues: true,
  barHeight: 28,
  animated: true,
})

const max = computed(() => props.maxValue || Math.max(...props.data.map(d => d.value), 1))

const bars = computed(() => {
  return props.data.map((item, index) => ({
    ...item,
    percentage: Math.min((item.value / max.value) * 100, 100),
    color: item.color || getDefaultColor(index),
  }))
})

function getDefaultColor(index: number): string {
  const colors = [
    '#1AAD19', // wecom primary green
    '#07C160', // wecom secondary
    '#10B981', // emerald
    '#3B82F6', // blue
    '#8B5CF6', // violet
    '#F59E0B', // amber
    '#EF4444', // red
    '#EC4899', // pink
  ]
  return colors[index % colors.length]
}
</script>

<template>
  <div class="space-y-3">
    <div
      v-for="(bar, index) in bars"
      :key="bar.label"
      class="group"
    >
      <div class="flex items-center justify-between mb-1.5">
        <div class="flex items-center gap-2">
          <span class="text-sm font-medium text-wecom-text">{{ bar.label }}</span>
          <span v-if="bar.subLabel" class="text-xs text-wecom-muted">{{ bar.subLabel }}</span>
        </div>
        <span v-if="showValues" class="text-sm font-semibold text-wecom-text">
          {{ bar.value.toLocaleString() }}
        </span>
      </div>
      
      <div 
        class="relative w-full bg-wecom-surface rounded-full overflow-hidden"
        :style="{ height: `${barHeight}px` }"
      >
        <!-- Background gradient shimmer -->
        <div 
          class="absolute inset-0 bg-gradient-to-r from-transparent via-white/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity"
          style="animation: shimmer 2s infinite linear;"
        />
        
        <!-- Bar fill -->
        <div
          class="h-full rounded-full relative overflow-hidden transition-all duration-700 ease-out"
          :class="{ 'animate-grow': animated }"
          :style="{ 
            width: `${bar.percentage}%`,
            backgroundColor: bar.color,
            animationDelay: `${index * 100}ms`
          }"
        >
          <!-- Inner glow -->
          <div 
            class="absolute inset-0 bg-gradient-to-b from-white/20 to-transparent"
          />
          <!-- Shine effect -->
          <div 
            class="absolute inset-0 bg-gradient-to-r from-transparent via-white/10 to-transparent"
            style="transform: skewX(-20deg); animation: slide 3s infinite ease-in-out;"
          />
        </div>
        
        <!-- Percentage indicator inside bar -->
        <span 
          v-if="bar.percentage > 15"
          class="absolute right-2 top-1/2 -translate-y-1/2 text-xs font-medium text-white/90"
        >
          {{ bar.percentage.toFixed(0) }}%
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
@keyframes shimmer {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}

@keyframes slide {
  0%, 100% { transform: translateX(-200%) skewX(-20deg); }
  50% { transform: translateX(200%) skewX(-20deg); }
}

.animate-grow {
  animation: grow 0.8s ease-out forwards;
}

@keyframes grow {
  from {
    width: 0%;
  }
}
</style>

