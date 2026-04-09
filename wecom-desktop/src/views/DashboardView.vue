<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useDashboardStore } from '../stores/dashboard'
import { useSettingsStore } from '../stores/settings'
import {
  DonutChart,
  HorizontalBarChart,
  RatioBar,
  StatCard,
  MessageTrendChart,
} from '../components/charts'
import { useI18n } from '../composables/useI18n'

const { t } = useI18n()

const router = useRouter()
const dashboardStore = useDashboardStore()
const settingsStore = useSettingsStore()

let refreshTimer: number | null = null
const refreshIntervalMs = computed(() =>
  settingsStore.settings.lowSpecMode
    ? Math.max(settingsStore.settings.autoRefreshInterval, 30000)
    : 15000
)

onMounted(() => {
  settingsStore.load()
  dashboardStore.fetchOverview()
  refreshTimer = window.setInterval(() => {
    if (document.visibilityState === 'hidden') return
    dashboardStore.fetchOverview()
  }, refreshIntervalMs.value)
})

onUnmounted(() => {
  if (refreshTimer) {
    window.clearInterval(refreshTimer)
  }
})

const overview = computed(() => dashboardStore.overview)

// Transform message types for donut chart (exclude system messages)
const messageTypeChartData = computed(() => {
  const stats = overview.value?.stats
  if (!stats?.messages_by_type) return []

  const colorMap: Record<string, string> = {
    text: '#10B981', // emerald
    image: '#3B82F6', // blue
    voice: '#8B5CF6', // violet
    video: '#F59E0B', // amber
    file: '#EC4899', // pink
    link: '#06B6D4', // cyan
    location: '#EF4444', // red
    unknown: '#6B7280', // gray
  }

  // Filter out system messages and sort by value descending
  return Object.entries(stats.messages_by_type)
    .filter(([type]) => type.toLowerCase() !== 'system')
    .map(([type, count]) => ({
      label: type.charAt(0).toUpperCase() + type.slice(1),
      value: count,
      color: colorMap[type.toLowerCase()] || '#6B7280',
    }))
    .sort((a, b) => b.value - a.value)
})

// Total messages excluding system messages
const totalNonSystemMessages = computed(() => {
  return messageTypeChartData.value.reduce((acc, item) => acc + item.value, 0)
})

// Device comparison bar chart data
const deviceBarChartData = computed(() => {
  const devices = overview.value?.devices || []
  return devices.map((device) => ({
    label: device.model || device.serial.slice(0, 8),
    value: device.message_count,
    subLabel: t('dashboard.device_sublabel', {
      kefuCount: device.kefu_count,
      customerCount: device.customer_count,
    }),
    color: '#1AAD19',
  }))
})

// Total message ratio (kefu vs customer)
const totalMessageRatio = computed(() => {
  const devices = overview.value?.devices || []
  const totalKefu = devices.reduce((acc, d) => acc + d.sent_by_kefu, 0)
  const totalCustomer = devices.reduce((acc, d) => acc + d.sent_by_customer, 0)
  return { sent: totalKefu, received: totalCustomer }
})

function formatDate(value: string | null | undefined) {
  if (!value) return '—'
  const parsed = new Date(value)
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toLocaleString()
  }
  return value
}

function formatRelativeTime(value: string | null | undefined) {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value

  const now = new Date()
  const diff = now.getTime() - parsed.getTime()
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)

  if (minutes < 1) return 'Just now'
  if (minutes < 60) return `${minutes}m ago`
  if (hours < 24) return `${hours}h ago`
  if (days < 7) return `${days}d ago`
  return parsed.toLocaleDateString()
}

function handleMouseMove(e: MouseEvent) {
  const target = e.currentTarget as HTMLElement
  const rect = target.getBoundingClientRect()
  const x = e.clientX - rect.left
  const percentage = (x / rect.width) * 100
  target.style.setProperty('--mouse-x', `${percentage}%`)
}

function navigateToConversation(customerId: number) {
  router.push({ name: 'conversation-detail', params: { id: customerId } })
}
</script>

<template>
  <div
    class="p-6 space-y-8 animate-fade-in min-h-full bg-gradient-to-br from-wecom-darker via-wecom-darker to-wecom-dark/50"
  >
    <!-- Header -->
    <div class="flex items-center justify-between gap-4">
      <div>
        <h2 class="text-3xl font-display font-bold text-wecom-text tracking-tight">
          {{ t('dashboard.title') }}
        </h2>
        <p class="text-sm text-wecom-muted mt-1">
          {{ t('dashboard.subtitle') }}
        </p>
      </div>

      <div class="flex items-center gap-3">
        <div
          class="flex items-center gap-2 px-3 py-2 rounded-lg bg-wecom-surface/50 border border-wecom-border/50"
        >
          <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          <span class="text-xs text-wecom-muted">
            {{ t('dashboard.updated') }} {{ formatRelativeTime(dashboardStore.lastFetched) }}
          </span>
        </div>
        <button
          class="btn-secondary text-sm flex items-center gap-2"
          :disabled="dashboardStore.loading"
          @click="dashboardStore.fetchOverview()"
        >
          <span :class="{ 'animate-spin': dashboardStore.loading }">🔄</span>
          {{ t('common.refresh') }}
        </button>
      </div>
    </div>

    <!-- Error state -->
    <div
      v-if="dashboardStore.error"
      class="bg-gradient-to-r from-red-900/30 to-red-800/20 border border-red-500/40 rounded-xl p-5 flex items-center gap-4"
    >
      <div class="w-12 h-12 rounded-xl bg-red-500/20 flex items-center justify-center">
        <span class="text-2xl">⚠️</span>
      </div>
      <div>
        <p class="text-red-400 font-semibold">{{ t('dashboard.load_failed') }}</p>
        <p class="text-red-400/70 text-sm mt-1">{{ dashboardStore.error }}</p>
      </div>
    </div>

    <!-- Loading state -->
    <div
      v-if="dashboardStore.loading && !overview"
      class="bg-wecom-dark border border-wecom-border rounded-xl p-12 flex flex-col items-center justify-center gap-4"
    >
      <div
        class="w-12 h-12 rounded-full border-4 border-wecom-primary/30 border-t-wecom-primary animate-spin"
      />
      <span class="text-wecom-muted">{{ t('dashboard.loading_data') }}</span>
    </div>

    <div v-if="overview" class="space-y-8">
      <!-- ============================================ -->
      <!-- STAT CARDS GRID -->
      <!-- ============================================ -->
      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-5">
        <div class="h-full">
          <StatCard
            :title="t('dashboard.stat_devices')"
            :value="overview.stats.devices"
            icon="📱"
            gradient="cyan"
          >
            <div class="text-xs text-wecom-muted">
              {{ overview.devices.filter((d) => d.message_count > 0).length }}
              {{ t('dashboard.active') }}
            </div>
          </StatCard>
        </div>

        <div class="h-full">
          <router-link to="/kefus" class="block h-full">
            <StatCard
              :title="t('nav.kefus')"
              :value="overview.stats.kefus"
              icon="🧑‍💼"
              gradient="green"
              :clickable="true"
            />
          </router-link>
        </div>

        <div class="h-full">
          <router-link to="/conversations" class="block h-full">
            <StatCard
              :title="t('dashboard.stat_streamers')"
              :value="overview.stats.customers"
              icon="👥"
              gradient="blue"
              :clickable="true"
            />
          </router-link>
        </div>

        <div class="h-full">
          <StatCard
            :title="t('dashboard.stat_messages')"
            :value="overview.stats.messages"
            icon="💬"
            gradient="purple"
          >
            <RatioBar
              :left-value="totalMessageRatio.sent"
              :right-value="totalMessageRatio.received"
              :left-label="t('dashboard.sent')"
              :right-label="t('dashboard.received')"
              left-color="#10B981"
              right-color="#3B82F6"
              :height="6"
              :show-labels="false"
            />
            <div class="flex justify-between text-xs text-wecom-muted mt-2">
              <span>↑ {{ totalMessageRatio.sent }} {{ t('dashboard.sent').toLowerCase() }}</span>
              <span
                >↓ {{ totalMessageRatio.received }}
                {{ t('dashboard.received').toLowerCase() }}</span
              >
            </div>
          </StatCard>
        </div>
      </div>

      <!-- ============================================ -->
      <!-- CHARTS ROW -->
      <!-- ============================================ -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- Message Types Donut Chart -->
        <div class="bg-wecom-dark/80 backdrop-blur border border-wecom-border rounded-xl p-6">
          <div class="flex items-center justify-between mb-6">
            <div>
              <h3 class="text-lg font-display font-semibold text-wecom-text">
                {{ t('dashboard.message_distribution') }}
              </h3>
              <p class="text-xs text-wecom-muted mt-1">
                {{ t('dashboard.message_distribution_subtitle') }}
              </p>
            </div>
            <span
              class="px-3 py-1.5 rounded-full bg-wecom-surface text-xs text-wecom-muted border border-wecom-border"
            >
              {{ totalNonSystemMessages.toLocaleString() }} {{ t('dashboard.total') }}
            </span>
          </div>

          <div
            v-if="messageTypeChartData.length > 0 || dashboardStore.loading"
            class="flex justify-center"
          >
            <DonutChart
              :data="messageTypeChartData"
              :size="180"
              :stroke-width="28"
              :center-value="totalNonSystemMessages"
              :center-label="t('dashboard.messages_label')"
              :loading="dashboardStore.loading && messageTypeChartData.length === 0"
              :min-segment-percent="4"
            />
          </div>
          <div v-else class="flex flex-col items-center justify-center py-12 text-wecom-muted">
            <span class="text-4xl mb-3 opacity-50">📊</span>
            <span>{{ t('dashboard.no_message_data') }}</span>
          </div>
        </div>

        <!-- Device Activity Bar Chart -->
        <div class="bg-wecom-dark/80 backdrop-blur border border-wecom-border rounded-xl p-6">
          <div class="flex items-center justify-between mb-6">
            <div>
              <h3 class="text-lg font-display font-semibold text-wecom-text">
                {{ t('dashboard.device_activity') }}
              </h3>
              <p class="text-xs text-wecom-muted mt-1">
                {{ t('dashboard.device_activity_subtitle') }}
              </p>
            </div>
            <span
              class="px-3 py-1.5 rounded-full bg-wecom-surface text-xs text-wecom-muted border border-wecom-border"
            >
              {{ overview.devices.length }} {{ t('dashboard.devices_label') }}
            </span>
          </div>

          <div v-if="deviceBarChartData.length > 0">
            <HorizontalBarChart :data="deviceBarChartData" :bar-height="24" />
          </div>
          <div v-else class="flex flex-col items-center justify-center py-12 text-wecom-muted">
            <span class="text-4xl mb-3 opacity-50">📱</span>
            <span>{{ t('dashboard.no_devices_synced') }}</span>
          </div>
        </div>
      </div>

      <!-- ============================================ -->
      <!-- MESSAGE TRENDS LINE CHART -->
      <!-- ============================================ -->
      <MessageTrendChart />

      <!-- ============================================ -->
      <!-- AGENT ENGAGEMENT SECTION -->
      <!-- ============================================ -->
      <section class="space-y-4">
        <div class="flex items-center justify-between">
          <div>
            <h3 class="text-lg font-display font-semibold text-wecom-text">
              {{ t('dashboard.agent_performance') }}
            </h3>
            <p class="text-xs text-wecom-muted mt-1">
              {{ t('dashboard.agent_performance_subtitle') }}
            </p>
          </div>
          <router-link
            to="/kefus"
            class="text-sm text-wecom-primary hover:text-wecom-secondary transition-colors"
          >
            {{ t('dashboard.view_all') }} →
          </router-link>
        </div>

        <div
          v-if="overview.kefus.length === 0"
          class="bg-wecom-dark border border-wecom-border rounded-xl p-8 text-center"
        >
          <span class="text-4xl mb-4 block opacity-50">🧑‍💼</span>
          <p class="text-wecom-muted">{{ t('dashboard.no_agents_yet') }}</p>
          <p class="text-xs text-wecom-muted mt-1">{{ t('dashboard.run_init_sync') }}</p>
        </div>

        <div v-else class="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
          <router-link
            v-for="(kefu, index) in overview.kefus"
            :key="kefu.id"
            :to="{ name: 'kefu-detail', params: { id: kefu.id } }"
            class="group relative bg-wecom-dark/80 backdrop-blur border border-wecom-border rounded-xl p-5 transition-all duration-300 hover:border-wecom-primary/50 hover:shadow-lg hover:shadow-wecom-primary/5 overflow-hidden"
            @mousemove="handleMouseMove"
            @mouseleave="
              (e) => (e.currentTarget as HTMLElement).style.setProperty('--mouse-x', '50%')
            "
          >
            <!-- Rank badge -->
            <div
              class="absolute -top-1 -left-1 w-8 h-8 flex items-center justify-center"
              :class="
                index === 0
                  ? 'text-amber-400'
                  : index === 1
                    ? 'text-gray-400'
                    : index === 2
                      ? 'text-amber-700'
                      : 'text-wecom-muted'
              "
            >
              <span v-if="index < 3" class="text-lg">{{ ['🥇', '🥈', '🥉'][index] }}</span>
              <span v-else class="text-xs font-bold">#{{ index + 1 }}</span>
            </div>

            <!-- Hover glow effect -->
            <div
              class="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"
              style="
                background: linear-gradient(
                  90deg,
                  transparent,
                  rgba(26, 173, 25, 0.1) var(--mouse-x, 50%),
                  transparent
                );
              "
            />

            <div class="relative space-y-4">
              <!-- Header -->
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0 flex-1">
                  <div class="flex items-center gap-2">
                    <h4 class="text-lg font-display font-semibold text-wecom-text truncate">
                      {{ kefu.name }}
                    </h4>
                    <span
                      v-if="kefu.verification_status"
                      class="shrink-0 text-xs px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                    >
                      {{ kefu.verification_status }}
                    </span>
                  </div>
                  <p class="text-xs text-wecom-muted mt-1 truncate">
                    {{ kefu.department || t('dashboard.no_department') }} ·
                    {{ kefu.device_model || kefu.device_serial }}
                  </p>
                </div>
                <span
                  class="text-2xl opacity-70 group-hover:opacity-100 group-hover:scale-110 transition-all"
                >
                  →
                </span>
              </div>

              <!-- Stats grid -->
              <div class="grid grid-cols-3 gap-3 py-3 border-y border-wecom-border/50">
                <div class="text-center">
                  <p class="text-2xl font-display font-bold text-wecom-text">
                    {{ kefu.customer_count }}
                  </p>
                  <p class="text-xs text-wecom-muted">{{ t('dashboard.stat_streamers') }}</p>
                </div>
                <div class="text-center">
                  <p class="text-2xl font-display font-bold text-wecom-text">
                    {{ kefu.message_count }}
                  </p>
                  <p class="text-xs text-wecom-muted">{{ t('dashboard.stat_messages') }}</p>
                </div>
                <div class="text-center">
                  <p class="text-2xl font-display font-bold text-wecom-primary">
                    {{
                      kefu.message_count > 0
                        ? (kefu.message_count / kefu.customer_count).toFixed(1)
                        : '0'
                    }}
                  </p>
                  <p class="text-xs text-wecom-muted">{{ t('dashboard.avg_per_customer') }}</p>
                </div>
              </div>

              <!-- Message ratio bar -->
              <RatioBar
                :left-value="kefu.sent_by_kefu"
                :right-value="kefu.sent_by_customer"
                :left-label="t('dashboard.agent_sent')"
                :right-label="t('dashboard.streamer_sent')"
                left-color="#1AAD19"
                right-color="#3B82F6"
                :height="6"
              />

              <!-- Last activity -->
              <div class="flex items-center justify-between text-xs">
                <span
                  class="text-wecom-muted truncate max-w-[60%]"
                  :title="kefu.last_customer_name || undefined"
                >
                  {{ t('dashboard.latest') }}: {{ kefu.last_customer_name || '—' }}
                </span>
                <span class="text-wecom-muted">
                  {{ formatRelativeTime(kefu.last_message_at) }}
                </span>
              </div>
            </div>
          </router-link>
        </div>
      </section>

      <!-- ============================================ -->
      <!-- RECENT CONVERSATIONS -->
      <!-- ============================================ -->
      <section class="space-y-4">
        <div class="flex items-center justify-between">
          <div>
            <h3 class="text-lg font-display font-semibold text-wecom-text">
              {{ t('dashboard.recent_conversations') }}
            </h3>
            <p class="text-xs text-wecom-muted mt-1">
              {{ t('dashboard.recent_conversations_subtitle') }}
            </p>
          </div>
          <router-link
            to="/conversations"
            class="text-sm text-wecom-primary hover:text-wecom-secondary transition-colors"
          >
            {{ t('dashboard.view_all') }} →
          </router-link>
        </div>

        <div
          class="bg-wecom-dark/80 backdrop-blur border border-wecom-border rounded-xl overflow-hidden"
        >
          <div class="overflow-auto max-h-[520px]">
            <table class="min-w-full text-sm">
              <thead
                class="bg-wecom-surface/80 border-b border-wecom-border text-wecom-muted sticky top-0"
              >
                <tr>
                  <th class="text-left px-4 py-3 font-medium">
                    {{ t('dashboard.table_streamer') }}
                  </th>
                  <th class="text-left px-4 py-3 font-medium">
                    {{ t('dashboard.table_channel') }}
                  </th>
                  <th class="text-left px-4 py-3 font-medium">{{ t('dashboard.table_agent') }}</th>
                  <th class="text-left px-4 py-3 font-medium">
                    {{ t('dashboard.table_activity') }}
                  </th>
                  <th class="text-left px-4 py-3 font-medium">
                    {{ t('dashboard.table_messages') }}
                  </th>
                  <th class="text-left px-4 py-3 font-medium">
                    {{ t('dashboard.table_last_message') }}
                  </th>
                </tr>
              </thead>
              <tbody class="divide-y divide-wecom-border/50">
                <tr
                  v-for="conv in overview.recent_conversations"
                  :key="conv.id"
                  class="hover:bg-wecom-surface/40 transition-colors group cursor-pointer"
                  @click="navigateToConversation(conv.id)"
                >
                  <td class="px-4 py-3">
                    <div class="flex items-center gap-3">
                      <div
                        class="w-8 h-8 rounded-full bg-gradient-to-br from-wecom-primary/30 to-wecom-secondary/30 flex items-center justify-center text-xs font-bold text-wecom-text"
                      >
                        {{ conv.name?.charAt(0)?.toUpperCase() || '?' }}
                      </div>
                      <span class="text-wecom-text font-medium">{{ conv.name }}</span>
                    </div>
                  </td>
                  <td class="px-4 py-3">
                    <span
                      v-if="conv.channel"
                      class="px-2 py-1 rounded-full text-xs bg-wecom-surface border border-wecom-border"
                    >
                      {{ conv.channel }}
                    </span>
                    <span v-else class="text-wecom-muted">—</span>
                  </td>
                  <td class="px-4 py-3 text-wecom-text">
                    {{ conv.kefu_name }}
                  </td>
                  <td class="px-4 py-3">
                    <span class="text-wecom-muted">
                      {{ formatRelativeTime(conv.last_message_at || conv.last_message_date) }}
                    </span>
                  </td>
                  <td class="px-4 py-3">
                    <div class="flex items-center gap-2">
                      <div class="flex items-center gap-1">
                        <span class="w-2 h-2 rounded-full bg-emerald-500" />
                        <span class="text-wecom-text font-medium">{{ conv.sent_by_kefu }}</span>
                      </div>
                      <span class="text-wecom-muted">/</span>
                      <div class="flex items-center gap-1">
                        <span class="w-2 h-2 rounded-full bg-blue-500" />
                        <span class="text-wecom-text font-medium">{{ conv.sent_by_customer }}</span>
                      </div>
                      <span class="text-wecom-muted text-xs ml-1">({{ conv.message_count }})</span>
                    </div>
                  </td>
                  <td class="px-4 py-3">
                    <p
                      class="text-wecom-muted truncate max-w-[200px] group-hover:text-wecom-text transition-colors"
                      :title="conv.last_message_preview || undefined"
                    >
                      {{ conv.last_message_preview || '—' }}
                    </p>
                  </td>
                </tr>
                <tr v-if="overview.recent_conversations.length === 0">
                  <td colspan="6" class="px-4 py-12 text-center">
                    <span class="text-4xl mb-4 block opacity-50">💬</span>
                    <p class="text-wecom-muted">{{ t('dashboard.no_conversations_synced') }}</p>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <!-- ============================================ -->
      <!-- FOOTER INFO -->
      <!-- ============================================ -->
      <div
        class="flex flex-wrap items-center justify-center gap-4 text-xs text-wecom-muted py-4 border-t border-wecom-border/30"
      >
        <div
          class="flex items-center gap-2 px-3 py-1.5 rounded-full bg-wecom-surface/50 border border-wecom-border/50"
        >
          <span class="w-2 h-2 rounded-full bg-wecom-primary" />
          <span
            >{{ t('dashboard.db_label') }}:
            {{ overview?.db_path || 'wecom_conversations.db' }}</span
          >
        </div>
        <div
          class="flex items-center gap-2 px-3 py-1.5 rounded-full bg-wecom-surface/50 border border-wecom-border/50"
        >
          <span class="w-2 h-2 rounded-full bg-blue-500" />
          <span>{{ t('dashboard.last_activity') }}: {{ formatDate(overview?.last_updated) }}</span>
        </div>
        <div
          class="flex items-center gap-2 px-3 py-1.5 rounded-full bg-wecom-surface/50 border border-wecom-border/50"
        >
          <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          <span>{{ t('dashboard.auto_refresh') }}: {{ refreshIntervalMs / 1000 }}s</span>
        </div>
      </div>
    </div>
  </div>
</template>
