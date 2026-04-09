<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    title: string
    value: number | string
    icon?: string
    trend?: number
    trendLabel?: string
    gradient?: 'green' | 'blue' | 'purple' | 'amber' | 'rose' | 'cyan'
    clickable?: boolean
  }>(),
  {
    gradient: 'green',
    clickable: false,
  }
)

const gradientClasses = computed(() => {
  const gradients: Record<string, string> = {
    green: 'from-emerald-500/20 via-emerald-600/10 to-transparent border-emerald-500/30',
    blue: 'from-blue-500/20 via-blue-600/10 to-transparent border-blue-500/30',
    purple: 'from-violet-500/20 via-violet-600/10 to-transparent border-violet-500/30',
    amber: 'from-amber-500/20 via-amber-600/10 to-transparent border-amber-500/30',
    rose: 'from-rose-500/20 via-rose-600/10 to-transparent border-rose-500/30',
    cyan: 'from-cyan-500/20 via-cyan-600/10 to-transparent border-cyan-500/30',
  }
  return gradients[props.gradient] || gradients.green
})

const iconBgClass = computed(() => {
  const bgs: Record<string, string> = {
    green: 'bg-emerald-500/20 text-emerald-400',
    blue: 'bg-blue-500/20 text-blue-400',
    purple: 'bg-violet-500/20 text-violet-400',
    amber: 'bg-amber-500/20 text-amber-400',
    rose: 'bg-rose-500/20 text-rose-400',
    cyan: 'bg-cyan-500/20 text-cyan-400',
  }
  return bgs[props.gradient] || bgs.green
})

const trendColor = computed(() => {
  if (!props.trend) return 'text-wecom-muted'
  return props.trend > 0 ? 'text-emerald-400' : 'text-rose-400'
})

const trendIcon = computed(() => {
  if (!props.trend) return ''
  return props.trend > 0 ? '↑' : '↓'
})
</script>

<template>
  <div
    class="relative overflow-hidden rounded-xl border transition-all duration-300 flex flex-col"
    :class="[
      `bg-gradient-to-br ${gradientClasses}`,
      clickable ? 'cursor-pointer hover:scale-[1.02] hover:shadow-lg hover:shadow-black/20' : '',
    ]"
    style="min-height: 140px"
  >
    <!-- Decorative elements -->
    <div class="absolute -right-8 -top-8 w-32 h-32 rounded-full bg-white/5 blur-2xl" />
    <div class="absolute -left-4 -bottom-4 w-24 h-24 rounded-full bg-white/3 blur-xl" />

    <div class="relative p-5 flex-1 flex flex-col">
      <div class="flex items-start justify-between">
        <div class="space-y-1">
          <p class="text-sm text-wecom-muted font-medium">{{ title }}</p>
          <p class="text-3xl font-display font-bold text-wecom-text tracking-tight">
            {{ typeof value === 'number' ? value.toLocaleString() : value }}
          </p>

          <!-- Trend indicator -->
          <div v-if="trend !== undefined" class="flex items-center gap-1.5 mt-2">
            <span :class="trendColor" class="text-sm font-semibold">
              {{ trendIcon }} {{ Math.abs(trend) }}%
            </span>
            <span v-if="trendLabel" class="text-xs text-wecom-muted">
              {{ trendLabel }}
            </span>
          </div>
        </div>

        <!-- Icon -->
        <div
          v-if="icon"
          class="w-12 h-12 rounded-xl flex items-center justify-center text-2xl shrink-0"
          :class="iconBgClass"
        >
          {{ icon }}
        </div>
      </div>

      <!-- Slot for additional content -->
      <div v-if="$slots.default" class="mt-auto pt-4">
        <slot />
      </div>
    </div>
  </div>
</template>
