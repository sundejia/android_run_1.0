<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { api, type MessageTimeseriesResponse } from '../../services/api'
import InteractiveLineChart, { type DataSeries } from './InteractiveLineChart.vue'

interface KefuOption {
  id: number
  name: string
  selected: boolean
  color: string
}

const props = withDefaults(defineProps<{
  kefuList?: { id: number; name: string }[]
}>(), {
  kefuList: () => [],
})

// State
const loading = ref(false)
const error = ref<string | null>(null)
const timeseriesData = ref<MessageTimeseriesResponse | null>(null)

// Chart settings
const metric = ref<'total' | 'incoming' | 'outgoing' | 'compare'>('total')
const granularity = ref<'hour' | 'day' | 'week' | 'month'>('day')
const timeRange = ref<'7d' | '30d' | '90d' | 'all'>('30d')
const showOverall = ref(true)
const selectedKefus = ref<number[]>([])

// Colors for series
const kefuColors = [
  '#10B981', // emerald
  '#3B82F6', // blue
  '#8B5CF6', // violet
  '#F59E0B', // amber
  '#EC4899', // pink
  '#06B6D4', // cyan
  '#EF4444', // red
  '#84CC16', // lime
]

const metricColors = {
  total: '#10B981',
  incoming: '#3B82F6',
  outgoing: '#F59E0B',
}

// Compute date range
const dateRange = computed(() => {
  const now = new Date()
  let startDate: Date | null = null
  
  switch (timeRange.value) {
    case '7d':
      startDate = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)
      break
    case '30d':
      startDate = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000)
      break
    case '90d':
      startDate = new Date(now.getTime() - 90 * 24 * 60 * 60 * 1000)
      break
    case 'all':
    default:
      startDate = null
  }
  
  return {
    startDate: startDate?.toISOString().split('T')[0] || undefined,
    endDate: undefined,
  }
})

// Fetch data
async function fetchData() {
  loading.value = true
  error.value = null
  
  try {
    timeseriesData.value = await api.getMessageTimeseries({
      startDate: dateRange.value.startDate,
      endDate: dateRange.value.endDate,
      granularity: granularity.value,
      kefuIds: selectedKefus.value.length > 0 ? selectedKefus.value : undefined,
    })
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Failed to load data'
  } finally {
    loading.value = false
  }
}

// Transform data to chart series
const chartSeries = computed<DataSeries[]>(() => {
  if (!timeseriesData.value) return []
  
  const series: DataSeries[] = []
  
  if (metric.value === 'compare') {
    // Show incoming vs outgoing
    if (showOverall.value) {
      series.push({
        id: 'overall-incoming',
        name: 'Incoming (Streamer → Agent)',
        color: metricColors.incoming,
        data: timeseriesData.value.overall.map(d => ({
          time: d.time,
          value: d.incoming,
        })),
      })
      
      series.push({
        id: 'overall-outgoing',
        name: 'Outgoing (Agent → Streamer)',
        color: metricColors.outgoing,
        data: timeseriesData.value.overall.map(d => ({
          time: d.time,
          value: d.outgoing,
        })),
      })
    }
  } else {
    // Show single metric
    const metricKey = metric.value
    
    if (showOverall.value) {
      series.push({
        id: 'overall',
        name: 'Overall',
        color: metricColors[metricKey],
        data: timeseriesData.value.overall.map(d => ({
          time: d.time,
          value: d[metricKey],
        })),
      })
    }
    
    // Add per-kefu series
    selectedKefus.value.forEach((kefuId, index) => {
      const kefuData = timeseriesData.value?.by_kefu[kefuId]
      const kefuName = timeseriesData.value?.kefu_names[kefuId] || `Agent ${kefuId}`
      
      if (kefuData) {
        series.push({
          id: `kefu-${kefuId}`,
          name: kefuName,
          color: kefuColors[index % kefuColors.length],
          data: kefuData.map(d => ({
            time: d.time,
            value: d[metricKey],
          })),
        })
      }
    })
  }
  
  return series
})

// Available kefus from the data
const availableKefus = computed<KefuOption[]>(() => {
  if (!timeseriesData.value) return []
  
  return Object.entries(timeseriesData.value.kefu_names).map(([id, name], index) => ({
    id: parseInt(id),
    name,
    selected: selectedKefus.value.includes(parseInt(id)),
    color: kefuColors[index % kefuColors.length],
  }))
})

// Toggle kefu selection
function toggleKefu(kefuId: number) {
  const index = selectedKefus.value.indexOf(kefuId)
  if (index === -1) {
    selectedKefus.value.push(kefuId)
  } else {
    selectedKefus.value.splice(index, 1)
  }
}

// Select all / none
function selectAllKefus() {
  selectedKefus.value = availableKefus.value.map(k => k.id)
}

function clearKefuSelection() {
  selectedKefus.value = []
}

// Watch for changes and refetch
watch([granularity, timeRange], () => {
  fetchData()
})

// Initial fetch
onMounted(() => {
  fetchData()
})

// Expose refresh method
defineExpose({ refresh: fetchData })
</script>

<template>
  <div class="bg-wecom-dark/80 backdrop-blur border border-wecom-border rounded-xl p-6 space-y-4">
    <!-- Header -->
    <div class="flex items-start justify-between gap-4 flex-wrap">
      <div>
        <h3 class="text-lg font-display font-semibold text-wecom-text">
          Message Trends
        </h3>
        <p class="text-xs text-wecom-muted mt-1">
          Message volume over time
        </p>
      </div>
      
      <!-- Quick stats -->
      <div v-if="timeseriesData" class="flex items-center gap-3">
        <div class="text-center px-3 py-1 rounded-lg bg-wecom-surface/50">
          <p class="text-lg font-display font-bold text-wecom-text">
            {{ timeseriesData.overall.reduce((a, d) => a + d.total, 0).toLocaleString() }}
          </p>
          <p class="text-xs text-wecom-muted">Total messages</p>
        </div>
      </div>
    </div>
    
    <!-- Controls -->
    <div class="flex flex-wrap items-center gap-4 border-b border-wecom-border pb-4">
      <!-- Metric selector -->
      <div class="flex items-center gap-2">
        <span class="text-xs text-wecom-muted">Metric:</span>
        <div class="flex rounded-lg bg-wecom-surface border border-wecom-border overflow-hidden">
          <button
            v-for="m in [
              { value: 'total', label: 'Total' },
              { value: 'incoming', label: 'Incoming' },
              { value: 'outgoing', label: 'Outgoing' },
              { value: 'compare', label: 'Compare' },
            ]"
            :key="m.value"
            class="px-3 py-1.5 text-xs font-medium transition-colors"
            :class="metric === m.value 
              ? 'bg-wecom-primary text-white' 
              : 'text-wecom-muted hover:text-wecom-text hover:bg-wecom-surface'"
            @click="metric = m.value as typeof metric"
          >
            {{ m.label }}
          </button>
        </div>
      </div>
      
      <!-- Time range selector -->
      <div class="flex items-center gap-2">
        <span class="text-xs text-wecom-muted">Period:</span>
        <div class="flex rounded-lg bg-wecom-surface border border-wecom-border overflow-hidden">
          <button
            v-for="t in [
              { value: '7d', label: '7 days' },
              { value: '30d', label: '30 days' },
              { value: '90d', label: '90 days' },
              { value: 'all', label: 'All time' },
            ]"
            :key="t.value"
            class="px-3 py-1.5 text-xs font-medium transition-colors"
            :class="timeRange === t.value 
              ? 'bg-wecom-primary text-white' 
              : 'text-wecom-muted hover:text-wecom-text hover:bg-wecom-surface'"
            @click="timeRange = t.value as typeof timeRange"
          >
            {{ t.label }}
          </button>
        </div>
      </div>
      
      <!-- Granularity selector -->
      <div class="flex items-center gap-2">
        <span class="text-xs text-wecom-muted">Group by:</span>
        <select
          v-model="granularity"
          class="bg-wecom-surface border border-wecom-border rounded-lg px-3 py-1.5 text-xs text-wecom-text focus:outline-none focus:border-wecom-primary"
        >
          <option value="hour">Hour</option>
          <option value="day">Day</option>
          <option value="week">Week</option>
          <option value="month">Month</option>
        </select>
      </div>
      
      <!-- Refresh button -->
      <button
        class="ml-auto px-3 py-1.5 text-xs font-medium text-wecom-muted hover:text-wecom-text bg-wecom-surface border border-wecom-border rounded-lg transition-colors flex items-center gap-1"
        :disabled="loading"
        @click="fetchData"
      >
        <span :class="{ 'animate-spin': loading }">🔄</span>
        Refresh
      </button>
    </div>
    
    <!-- Series toggles -->
    <div class="flex flex-wrap items-center gap-3">
      <!-- Overall toggle -->
      <label class="flex items-center gap-2 cursor-pointer group">
        <input
          v-model="showOverall"
          type="checkbox"
          class="w-4 h-4 rounded border-wecom-border bg-wecom-surface text-wecom-primary focus:ring-wecom-primary focus:ring-offset-0"
        />
        <span class="text-sm text-wecom-muted group-hover:text-wecom-text transition-colors">
          Overall
        </span>
      </label>
      
      <div class="w-px h-4 bg-wecom-border" />
      
      <!-- Kefu toggles -->
      <div class="flex items-center gap-2 flex-wrap">
        <span class="text-xs text-wecom-muted">Agents:</span>
        
        <button
          v-for="kefu in availableKefus"
          :key="kefu.id"
          class="flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs font-medium transition-all"
          :class="kefu.selected 
            ? 'bg-wecom-surface border-2' 
            : 'bg-transparent border border-wecom-border/50 opacity-60 hover:opacity-100'"
          :style="kefu.selected ? { borderColor: kefu.color } : {}"
          @click="toggleKefu(kefu.id)"
        >
          <span 
            class="w-2 h-2 rounded-full"
            :style="{ backgroundColor: kefu.color }"
          />
          <span :class="kefu.selected ? 'text-wecom-text' : 'text-wecom-muted'">
            {{ kefu.name }}
          </span>
        </button>
        
        <template v-if="availableKefus.length > 0">
          <button
            class="text-xs text-wecom-primary hover:text-wecom-secondary transition-colors"
            @click="selectAllKefus"
          >
            Select all
          </button>
          <button
            v-if="selectedKefus.length > 0"
            class="text-xs text-wecom-muted hover:text-wecom-text transition-colors"
            @click="clearKefuSelection"
          >
            Clear
          </button>
        </template>
      </div>
    </div>
    
    <!-- Error state -->
    <div
      v-if="error"
      class="bg-red-900/20 border border-red-500/30 rounded-lg p-4 flex items-center gap-3"
    >
      <span class="text-red-400">⚠️</span>
      <div>
        <p class="text-red-400 font-medium text-sm">Failed to load chart data</p>
        <p class="text-red-400/70 text-xs">{{ error }}</p>
      </div>
      <button
        class="ml-auto text-xs text-red-400 hover:text-red-300 transition-colors"
        @click="fetchData"
      >
        Retry
      </button>
    </div>
    
    <!-- Chart -->
    <div class="relative" style="min-height: 300px;">
      <InteractiveLineChart
        :series="chartSeries"
        :height="300"
        :loading="loading"
        :animated="true"
      />
    </div>
    
    <!-- Legend -->
    <div v-if="chartSeries.length > 0" class="flex flex-wrap items-center gap-4 pt-2 border-t border-wecom-border">
      <div
        v-for="s in chartSeries"
        :key="s.id"
        class="flex items-center gap-2 text-xs"
      >
        <span 
          class="w-3 h-0.5 rounded"
          :style="{ backgroundColor: s.color }"
        />
        <span class="text-wecom-muted">{{ s.name }}</span>
      </div>
    </div>
  </div>
</template>

