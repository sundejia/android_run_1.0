<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  leftValue: number
  rightValue: number
  leftLabel?: string
  rightLabel?: string
  leftColor?: string
  rightColor?: string
  height?: number
  showLabels?: boolean
}>(), {
  leftLabel: 'Sent',
  rightLabel: 'Received',
  leftColor: '#1AAD19',
  rightColor: '#3B82F6',
  height: 8,
  showLabels: true,
})

const total = computed(() => props.leftValue + props.rightValue)
const leftPercent = computed(() => total.value > 0 ? (props.leftValue / total.value) * 100 : 50)
const rightPercent = computed(() => total.value > 0 ? (props.rightValue / total.value) * 100 : 50)
</script>

<template>
  <div class="space-y-2">
    <!-- Labels row -->
    <div v-if="showLabels" class="flex items-center justify-between text-xs">
      <div class="flex items-center gap-1.5">
        <span 
          class="w-2 h-2 rounded-full" 
          :style="{ backgroundColor: leftColor }"
        />
        <span class="text-wecom-muted">{{ leftLabel }}</span>
        <span class="text-wecom-text font-semibold">{{ leftValue }}</span>
      </div>
      <div class="flex items-center gap-1.5">
        <span class="text-wecom-text font-semibold">{{ rightValue }}</span>
        <span class="text-wecom-muted">{{ rightLabel }}</span>
        <span 
          class="w-2 h-2 rounded-full" 
          :style="{ backgroundColor: rightColor }"
        />
      </div>
    </div>
    
    <!-- Ratio bar -->
    <div 
      class="flex rounded-full overflow-hidden bg-wecom-surface"
      :style="{ height: `${height}px` }"
    >
      <div
        class="transition-all duration-500 ease-out relative overflow-hidden"
        :style="{ 
          width: `${leftPercent}%`,
          backgroundColor: leftColor 
        }"
      >
        <div class="absolute inset-0 bg-gradient-to-b from-white/20 to-transparent" />
      </div>
      <div
        class="transition-all duration-500 ease-out relative overflow-hidden"
        :style="{ 
          width: `${rightPercent}%`,
          backgroundColor: rightColor 
        }"
      >
        <div class="absolute inset-0 bg-gradient-to-b from-white/20 to-transparent" />
      </div>
    </div>
    
    <!-- Percentage labels -->
    <div v-if="showLabels && total > 0" class="flex justify-between text-xs text-wecom-muted">
      <span>{{ leftPercent.toFixed(0) }}%</span>
      <span>{{ rightPercent.toFixed(0) }}%</span>
    </div>
  </div>
</template>

