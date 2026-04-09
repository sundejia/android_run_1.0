<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useI18n } from '../composables/useI18n'
import { useDeviceStore } from '../stores/devices'
import LoadingSpinner from '../components/LoadingSpinner.vue'
import Toast from '../components/Toast.vue'

const { t } = useI18n()
const deviceStore = useDeviceStore()

// Tab state
const activeTab = ref<'history' | 'settings'>('history')

// Device selection
const selectedDevice = ref<string>('')

// Settings state
const settings = ref({
  followupEnabled: false,
  maxFollowupPerScan: 5,
  useAIReply: false,
  enableOperatingHours: false,
  startHour: '09:00',
  endHour: '18:00',
  followupMessageTemplates: [
    'Hello, have you considered our offer?',
    'Feel free to contact me if you have any questions',
  ],
  followupPrompt: '',
  idleThresholdMinutes: 30,
  maxAttemptsPerCustomer: 3,
  attemptIntervals: [60, 120, 180],
  avoidDuplicateMessages: false,
})

const savingSettings = ref(false)
const settingsError = ref('')

// History/Data table state
const dataFilters = ref({
  dateFrom: '',
  dateTo: '',
  status: 'All',
  responded: 'All',
  users: 'All Users',
})

const dataList = ref<
  {
    id: number
    userId: string
    attemptNumber: number
    status: 'pending' | 'in_progress' | 'completed' | 'cancelled'
    messagePreview: string
    createdAt: string
    responded: boolean
    responseTime: number | null
  }[]
>([])

const dataTotal = ref(0)
const dataPage = ref(1)
const dataPageSize = ref(20)
const loadingHistory = ref(false)

// Toast state
const showToast = ref(false)
const toastMessage = ref('')
const toastType = ref<'success' | 'error'>('success')

// ============================================
// Settings Functions
// ============================================

// Fetch settings
async function fetchSettings() {
  try {
    const response = await fetch('http://localhost:8765/api/followup/settings')
    if (response.ok) {
      const data = await response.json()
      // Merge settings
      settings.value = { ...settings.value, ...data }
    }
  } catch (error) {
    console.error('Failed to fetch settings:', error)
  }
}

// Save settings
async function saveSettings() {
  savingSettings.value = true
  settingsError.value = ''

  try {
    const response = await fetch('http://localhost:8765/api/followup/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings.value),
    })

    if (response.ok) {
      triggerToast(t('followup_manage.settings_saved'), 'success')
    } else {
      const error = await response.json()
      settingsError.value = error.detail || t('followup_manage.save_failed')
      triggerToast(t('followup_manage.save_failed'), 'error')
    }
  } catch (error) {
    console.error('Failed to save settings:', error)
    settingsError.value = t('followup_manage.save_failed')
    triggerToast(t('followup_manage.save_failed'), 'error')
  } finally {
    savingSettings.value = false
  }
}

// Reset settings to defaults
async function resetSettings() {
  if (!confirm(t('followup_manage.confirm_reset'))) return

  settings.value = {
    followupEnabled: false,
    maxFollowupPerScan: 5,
    useAIReply: false,
    enableOperatingHours: false,
    startHour: '09:00',
    endHour: '18:00',
    followupMessageTemplates: [
      'Hello, have you considered our offer?',
      'Feel free to contact me if you have any questions',
    ],
    followupPrompt: '',
    idleThresholdMinutes: 30,
    maxAttemptsPerCustomer: 3,
    attemptIntervals: [60, 120, 180],
    avoidDuplicateMessages: false,
  }

  triggerToast(t('followup_manage.reset_success'), 'success')
}

// Add message template
function addMessageTemplate() {
  settings.value.followupMessageTemplates.push('')
}

// Remove message template
function removeMessageTemplate(index: number) {
  settings.value.followupMessageTemplates.splice(index, 1)
}

// ============================================
// History/Data Functions
// ============================================

// Fetch data list
async function fetchDataList() {
  if (!selectedDevice.value) {
    dataList.value = []
    dataTotal.value = 0
    return
  }

  loadingHistory.value = true
  try {
    const params = new URLSearchParams({
      device_serial: selectedDevice.value,
      page: dataPage.value.toString(),
      pageSize: dataPageSize.value.toString(),
      status: dataFilters.value.status,
      responded: dataFilters.value.responded,
    })
    if (dataFilters.value.dateFrom) params.append('dateFrom', dataFilters.value.dateFrom)
    if (dataFilters.value.dateTo) params.append('dateTo', dataFilters.value.dateTo)
    if (dataFilters.value.users !== 'All Users') params.append('userId', dataFilters.value.users)

    const response = await fetch(`http://localhost:8765/api/followup/attempts?${params}`)
    if (response.ok) {
      const data = await response.json()
      dataList.value = data.items || []
      dataTotal.value = data.total || 0
    }
  } catch (error) {
    console.error('Failed to fetch data list:', error)
    triggerToast(t('followup_manage.load_failed'), 'error')
  } finally {
    loadingHistory.value = false
  }
}

// Export functions
async function exportCSV() {
  if (!selectedDevice.value) {
    triggerToast(t('followup_manage.select_device_first'), 'error')
    return
  }

  try {
    const response = await fetch(
      `http://localhost:8765/api/followup/export?format=csv&device_serial=${selectedDevice.value}`
    )
    if (response.ok) {
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `followup_${selectedDevice.value}_${new Date().toISOString().slice(0, 10)}.csv`
      a.click()
      URL.revokeObjectURL(url)
      triggerToast(t('followup_manage.export_success'), 'success')
    }
  } catch (error) {
    console.error('Failed to export CSV:', error)
    triggerToast(t('followup_manage.export_failed'), 'error')
  }
}

async function exportExcel() {
  if (!selectedDevice.value) {
    triggerToast(t('followup_manage.select_device_first'), 'error')
    return
  }

  try {
    const response = await fetch(
      `http://localhost:8765/api/followup/export?format=xlsx&device_serial=${selectedDevice.value}`
    )
    if (response.ok) {
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `followup_${selectedDevice.value}_${new Date().toISOString().slice(0, 10)}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
      triggerToast(t('followup_manage.export_success'), 'success')
    }
  } catch (error) {
    console.error('Failed to export Excel:', error)
    triggerToast(t('followup_manage.export_failed'), 'error')
  }
}

async function deleteAll() {
  if (!selectedDevice.value) {
    triggerToast(t('followup_manage.select_device_first'), 'error')
    return
  }

  if (!confirm(t('followup_manage.confirm_delete_all'))) {
    return
  }

  try {
    const response = await fetch(
      `http://localhost:8765/api/followup/attempts?device_serial=${selectedDevice.value}`,
      {
        method: 'DELETE',
      }
    )
    if (response.ok) {
      await fetchDataList()
      triggerToast(t('followup_manage.delete_success'), 'success')
    }
  } catch (error) {
    console.error('Failed to delete all:', error)
    triggerToast(t('followup_manage.delete_failed'), 'error')
  }
}

async function deleteItem(id: number) {
  if (!confirm(t('followup_manage.confirm_delete_item'))) {
    return
  }

  try {
    const response = await fetch(`http://localhost:8765/api/followup/attempts/${id}`, {
      method: 'DELETE',
    })
    if (response.ok) {
      await fetchDataList()
      triggerToast(t('followup_manage.delete_success'), 'success')
    } else {
      triggerToast(t('followup_manage.delete_failed'), 'error')
    }
  } catch (error) {
    console.error('Failed to delete item:', error)
    triggerToast(t('followup_manage.delete_failed'), 'error')
  }
}

// Reset filters
function resetFilters() {
  dataFilters.value = {
    dateFrom: '',
    dateTo: '',
    status: 'All',
    responded: 'All',
    users: 'All Users',
  }
  fetchDataList()
}

function formatResponseTime(seconds: number | null) {
  if (seconds === null || seconds === undefined) return '-'
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  return `${Math.floor(seconds / 3600)}h`
}

// ============================================
// Utility Functions
// ============================================

function triggerToast(message: string, type: 'success' | 'error' = 'success') {
  toastMessage.value = message
  toastType.value = type
  showToast.value = true
  setTimeout(() => {
    showToast.value = false
  }, 3000)
}

function formatDate(dateStr: string | null) {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('en-US', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function getStatusBadgeClass(status: string) {
  switch (status) {
    case 'pending':
      return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
    case 'in_progress':
      return 'bg-blue-500/20 text-blue-400 border-blue-500/30'
    case 'completed':
      return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
    case 'cancelled':
      return 'bg-gray-500/20 text-gray-400 border-gray-500/30'
    default:
      return 'bg-blue-500/20 text-blue-400 border-blue-500/30'
  }
}

function getStatusText(status: string) {
  return t(`followup_manage.status_${status}`)
}

// ============================================
// Watchers and Lifecycle
// ============================================

// Watch selected device change
watch(selectedDevice, () => {
  if (activeTab.value === 'history') {
    dataPage.value = 1 // Reset to first page
    fetchDataList()
  }
})

// Watch tab changes
watch(activeTab, (newTab) => {
  if (newTab === 'history' && selectedDevice.value) {
    fetchDataList()
  }
})

// Load data on mount
onMounted(async () => {
  await deviceStore.fetchDevices()
  await fetchSettings()

  // Auto-select first device if available
  if (deviceStore.devices.length > 0) {
    selectedDevice.value = deviceStore.devices[0].serial
  }
})
</script>

<template>
  <div class="followup-manage-view h-full flex flex-col bg-wecom-darker text-wecom-text">
    <!-- Page Header -->
    <header class="px-6 py-4 border-b border-wecom-border bg-wecom-dark shrink-0">
      <h1 class="text-xl font-display font-semibold text-wecom-text">
        🎯 {{ t('followup_manage.title') }}
      </h1>
      <p class="text-xs text-wecom-muted mt-1">{{ t('followup_manage.subtitle') }}</p>
    </header>

    <!-- Controls Bar -->
    <div
      class="p-4 border-b border-wecom-border flex flex-wrap gap-4 items-center bg-wecom-dark/50"
    >
      <!-- Device Selector (always show) -->
      <div class="flex items-center gap-2">
        <label class="text-sm text-wecom-muted">{{ t('followup_manage.device') }}:</label>
        <select
          v-model="selectedDevice"
          class="bg-wecom-surface border border-wecom-border rounded px-3 py-1.5 text-sm focus:outline-none focus:border-wecom-primary min-w-[200px]"
        >
          <option value="">{{ t('followup_manage.select_device') }}</option>
          <option v-for="device in deviceStore.devices" :key="device.serial" :value="device.serial">
            {{ device.model || device.serial }} ({{ device.serial }})
          </option>
        </select>
      </div>
    </div>

    <!-- Tabs -->
    <div class="px-6 py-3 bg-wecom-dark/30 border-b border-wecom-border flex gap-2">
      <button
        :class="[
          'px-4 py-2 rounded-lg font-medium transition-colors',
          activeTab === 'history'
            ? 'bg-wecom-primary text-white'
            : 'bg-wecom-surface text-wecom-muted hover:text-wecom-text hover:bg-wecom-surface/80 border border-wecom-border',
        ]"
        @click="activeTab = 'history'"
      >
        📊 {{ t('followup_manage.tab_history') }}
      </button>
      <button
        :class="[
          'px-4 py-2 rounded-lg font-medium transition-colors',
          activeTab === 'settings'
            ? 'bg-wecom-primary text-white'
            : 'bg-wecom-surface text-wecom-muted hover:text-wecom-text hover:bg-wecom-surface/80 border border-wecom-border',
        ]"
        @click="activeTab = 'settings'"
      >
        ⚙️ {{ t('followup_manage.tab_settings') }}
      </button>
    </div>

    <!-- History Tab -->
    <div v-if="activeTab === 'history'" class="flex-1 overflow-auto p-6 space-y-6">
      <!-- No Device Selected -->
      <div v-if="!selectedDevice" class="text-center py-12 text-wecom-muted">
        <p class="text-4xl mb-3">📱</p>
        <p>{{ t('followup_manage.select_device_first') }}</p>
      </div>

      <template v-else>
        <!-- Filters -->
        <div class="bg-wecom-dark/80 backdrop-blur rounded-xl p-5 border border-wecom-border">
          <div class="flex flex-wrap items-center gap-4">
            <div class="flex items-center gap-2">
              <label class="text-sm text-wecom-muted">{{ t('followup_manage.date_from') }}:</label>
              <input
                v-model="dataFilters.dateFrom"
                type="date"
                class="px-3 py-2 bg-wecom-surface border border-wecom-border rounded-lg text-sm text-wecom-text"
              />
            </div>

            <div class="flex items-center gap-2">
              <label class="text-sm text-wecom-muted">{{ t('followup_manage.date_to') }}:</label>
              <input
                v-model="dataFilters.dateTo"
                type="date"
                class="px-3 py-2 bg-wecom-surface border border-wecom-border rounded-lg text-sm text-wecom-text"
              />
            </div>

            <div class="flex items-center gap-2">
              <label class="text-sm text-wecom-muted">{{ t('followup_manage.status') }}:</label>
              <select
                v-model="dataFilters.status"
                class="px-3 py-2 bg-wecom-surface border border-wecom-border rounded-lg text-sm text-wecom-text"
              >
                <option>All</option>
                <option>pending</option>
                <option>in_progress</option>
                <option>completed</option>
                <option>cancelled</option>
              </select>
            </div>

            <div class="flex items-center gap-2">
              <label class="text-sm text-wecom-muted">{{ t('followup_manage.responded') }}:</label>
              <select
                v-model="dataFilters.responded"
                class="px-3 py-2 bg-wecom-surface border border-wecom-border rounded-lg text-sm text-wecom-text"
              >
                <option>All</option>
                <option value="yes">{{ t('followup_manage.yes') }}</option>
                <option value="no">{{ t('followup_manage.no') }}</option>
              </select>
            </div>

            <div class="flex-1"></div>

            <button
              class="px-4 py-2 bg-wecom-surface hover:bg-wecom-surface/80 text-wecom-text border border-wecom-border rounded-lg text-sm transition-colors"
              @click="resetFilters"
            >
              {{ t('followup_manage.reset') }}
            </button>

            <button
              class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm flex items-center gap-1 transition-colors"
              @click="fetchDataList"
            >
              🔄 {{ t('followup_manage.refresh') }}
            </button>

            <button
              class="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-sm flex items-center gap-1 transition-colors"
              @click="exportCSV"
            >
              📄 {{ t('followup_manage.export_csv') }}
            </button>

            <button
              class="px-4 py-2 bg-emerald-700 hover:bg-emerald-800 text-white rounded-lg text-sm flex items-center gap-1 transition-colors"
              @click="exportExcel"
            >
              📊 {{ t('followup_manage.export_excel') }}
            </button>

            <button
              class="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg text-sm flex items-center gap-1 transition-colors"
              @click="deleteAll"
            >
              🗑️ {{ t('followup_manage.delete_all') }}
            </button>
          </div>
        </div>

        <!-- Data Table -->
        <div
          class="bg-wecom-dark/80 backdrop-blur rounded-xl border border-wecom-border overflow-hidden relative"
        >
          <LoadingSpinner
            v-if="loadingHistory"
            class="absolute inset-0 flex items-center justify-center bg-wecom-darker/50 z-10"
          />

          <div class="px-5 py-4 border-b border-wecom-border flex items-center justify-between">
            <h3 class="font-semibold text-wecom-text">{{ t('followup_manage.attempts_title') }}</h3>
            <div class="text-sm text-wecom-muted">
              {{ t('followup_manage.total') }}: {{ dataTotal.toLocaleString() }}
              <span class="ml-2 text-wecom-muted/70"
                >{{ t('followup_manage.showing') }} {{ (dataPage - 1) * dataPageSize + 1 }}-{{
                  Math.min(dataPage * dataPageSize, dataTotal)
                }}</span
              >
            </div>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full">
              <thead class="bg-wecom-surface/50 text-left text-xs text-wecom-muted uppercase">
                <tr>
                  <th class="px-4 py-3">{{ t('followup_manage.user_id') }}</th>
                  <th class="px-4 py-3">{{ t('followup_manage.attempt_number') }}</th>
                  <th class="px-4 py-3">{{ t('followup_manage.status') }}</th>
                  <th class="px-4 py-3">{{ t('followup_manage.message_preview') }}</th>
                  <th class="px-4 py-3">{{ t('followup_manage.created_at') }}</th>
                  <th class="px-4 py-3">{{ t('followup_manage.responded') }}</th>
                  <th class="px-4 py-3">{{ t('followup_manage.response_time') }}</th>
                  <th class="px-4 py-3">{{ t('followup_manage.actions') }}</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-wecom-border/50">
                <tr
                  v-for="row in dataList"
                  :key="row.id"
                  class="hover:bg-wecom-surface/30 transition-colors"
                >
                  <td class="px-4 py-3 text-sm font-medium text-wecom-text">{{ row.userId }}</td>
                  <td class="px-4 py-3 text-sm text-wecom-muted">
                    {{ row.attemptNumber }}
                  </td>
                  <td class="px-4 py-3">
                    <span
                      :class="[
                        'px-2 py-1 rounded text-xs font-medium border',
                        getStatusBadgeClass(row.status),
                      ]"
                    >
                      {{ getStatusText(row.status) }}
                    </span>
                  </td>
                  <td class="px-4 py-3 text-sm text-wecom-muted max-w-[200px] truncate">
                    {{ row.messagePreview || '...' }}
                  </td>
                  <td class="px-4 py-3 text-sm text-wecom-muted">
                    {{ formatDate(row.createdAt) }}
                  </td>
                  <td class="px-4 py-3 text-sm text-wecom-muted">
                    {{ row.responded ? t('followup_manage.yes') : t('followup_manage.no') }}
                  </td>
                  <td class="px-4 py-3 text-sm text-wecom-muted">
                    {{ formatResponseTime(row.responseTime) }}
                  </td>
                  <td class="px-4 py-3">
                    <button
                      class="p-2 text-red-500 hover:text-red-600 hover:bg-red-500/10 rounded transition-colors"
                      :title="t('followup_manage.delete')"
                      @click="deleteItem(row.id)"
                    >
                      🗑️
                    </button>
                  </td>
                </tr>
                <tr v-if="dataList.length === 0">
                  <td colspan="8" class="px-4 py-12 text-center text-wecom-muted">
                    {{ t('followup_manage.no_records') }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- Pagination -->
          <div class="px-5 py-4 border-t border-wecom-border flex items-center justify-between">
            <button
              :disabled="dataPage <= 1"
              class="px-4 py-2 bg-wecom-surface hover:bg-wecom-surface/80 text-wecom-text border border-wecom-border rounded-lg text-sm disabled:opacity-50 transition-colors"
              @click="
                () => {
                  dataPage = Math.max(1, dataPage - 1)
                  fetchDataList()
                }
              "
            >
              {{ t('followup_manage.previous') }}
            </button>
            <span class="text-sm text-wecom-muted"
              >{{ t('followup_manage.page') }} {{ dataPage }}</span
            >
            <button
              :disabled="dataPage * dataPageSize >= dataTotal"
              class="px-4 py-2 bg-wecom-surface hover:bg-wecom-surface/80 text-wecom-text border border-wecom-border rounded-lg text-sm disabled:opacity-50 transition-colors"
              @click="
                () => {
                  dataPage++
                  fetchDataList()
                }
              "
            >
              {{ t('followup_manage.next') }}
            </button>
          </div>
        </div>
      </template>
    </div>

    <!-- Settings Tab -->
    <div v-if="activeTab === 'settings'" class="flex-1 overflow-auto p-6">
      <!-- Error Display -->
      <div v-if="settingsError" class="bg-red-500/10 border-l-4 border-red-500 rounded-lg p-4 mb-6">
        <p class="text-sm text-red-400">
          {{ t('followup_manage.save_failed') }}: {{ settingsError }}
        </p>
      </div>

      <!-- Settings Form -->
      <div class="max-w-3xl space-y-6">
        <!-- Basic Settings Card -->
        <div class="bg-wecom-dark/80 backdrop-blur rounded-xl p-6 border border-wecom-border">
          <h3 class="text-sm font-semibold text-wecom-text flex items-center gap-2 mb-4">
            ⚡ {{ t('followup_manage.basic_settings') }}
          </h3>

          <div class="space-y-4">
            <!-- Enable Followup -->
            <div class="flex items-center justify-between">
              <div>
                <label class="text-sm text-wecom-text font-medium">{{
                  t('followup_manage.enable_followup')
                }}</label>
                <p class="text-xs text-wecom-muted mt-1">
                  {{ t('followup_manage.enable_followup_desc') }}
                </p>
              </div>
              <input
                v-model="settings.followupEnabled"
                type="checkbox"
                class="w-12 h-6 rounded-full bg-wecom-surface border border-wecom-border"
              />
            </div>

            <!-- Max Followup Per Scan -->
            <div>
              <label class="block text-sm text-wecom-text font-medium mb-2">
                {{ t('followup_manage.max_followups') }}
              </label>
              <input
                v-model.number="settings.maxFollowupPerScan"
                type="number"
                min="1"
                max="50"
                step="1"
                class="w-full px-4 py-2 bg-wecom-surface border border-wecom-border rounded-lg text-wecom-text"
              />
              <p class="text-xs text-wecom-muted mt-1">
                {{ t('followup_manage.max_followups_desc') }}
              </p>
            </div>

            <!-- Operating Hours -->
            <div class="border-t border-wecom-border pt-4">
              <div class="flex items-center justify-between mb-3">
                <div>
                  <label class="text-sm text-wecom-text font-medium">{{
                    t('followup_manage.enable_operating_hours')
                  }}</label>
                  <p class="text-xs text-wecom-muted mt-1">
                    {{ t('followup_manage.enable_operating_hours_desc') }}
                  </p>
                </div>
                <input
                  v-model="settings.enableOperatingHours"
                  type="checkbox"
                  class="w-12 h-6 rounded-full bg-wecom-surface border border-wecom-border"
                />
              </div>

              <!-- Time Range -->
              <div v-if="settings.enableOperatingHours" class="grid grid-cols-2 gap-4 pl-4">
                <div>
                  <label class="block text-xs text-wecom-muted mb-2">{{
                    t('followup_manage.start_time')
                  }}</label>
                  <input
                    v-model="settings.startHour"
                    type="time"
                    class="w-full px-3 py-2 bg-wecom-surface border border-wecom-border rounded-lg text-sm text-wecom-text"
                  />
                </div>
                <div>
                  <label class="block text-xs text-wecom-muted mb-2">{{
                    t('followup_manage.end_time')
                  }}</label>
                  <input
                    v-model="settings.endHour"
                    type="time"
                    class="w-full px-3 py-2 bg-wecom-surface border border-wecom-border rounded-lg text-sm text-wecom-text"
                  />
                </div>
              </div>
            </div>

            <!-- Attempt Intervals -->
            <div class="border-t border-wecom-border pt-4">
              <label class="block text-sm text-wecom-text font-medium mb-3">
                ⏱️ {{ t('followup_manage.attempt_intervals') }}
              </label>
              <p class="text-xs text-wecom-muted mb-3">
                {{ t('followup_manage.attempt_intervals_desc') }}
              </p>
              <div class="space-y-3">
                <div class="flex items-center gap-3">
                  <span class="text-xs text-wecom-muted w-32">{{
                    t('followup_manage.interval_1')
                  }}</span>
                  <input
                    v-model.number="settings.attemptIntervals[0]"
                    type="number"
                    min="1"
                    max="1440"
                    step="1"
                    class="flex-1 px-3 py-2 bg-wecom-surface border border-wecom-border rounded-lg text-sm text-wecom-text"
                  />
                  <span class="text-xs text-wecom-muted w-8">{{
                    t('followup_manage.minutes')
                  }}</span>
                </div>
                <div class="flex items-center gap-3">
                  <span class="text-xs text-wecom-muted w-32">{{
                    t('followup_manage.interval_2')
                  }}</span>
                  <input
                    v-model.number="settings.attemptIntervals[1]"
                    type="number"
                    min="1"
                    max="1440"
                    step="1"
                    class="flex-1 px-3 py-2 bg-wecom-surface border border-wecom-border rounded-lg text-sm text-wecom-text"
                  />
                  <span class="text-xs text-wecom-muted w-8">{{
                    t('followup_manage.minutes')
                  }}</span>
                </div>
                <div class="flex items-center gap-3">
                  <span class="text-xs text-wecom-muted w-32">{{
                    t('followup_manage.interval_3')
                  }}</span>
                  <input
                    v-model.number="settings.attemptIntervals[2]"
                    type="number"
                    min="1"
                    max="1440"
                    step="1"
                    class="flex-1 px-3 py-2 bg-wecom-surface border border-wecom-border rounded-lg text-sm text-wecom-text"
                  />
                  <span class="text-xs text-wecom-muted w-8">{{
                    t('followup_manage.minutes')
                  }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Message Templates Card -->
        <div class="bg-wecom-dark/80 backdrop-blur rounded-xl p-6 border border-wecom-border">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-sm font-semibold text-wecom-text flex items-center gap-2">
              💬 {{ t('followup_manage.message_templates') }}
            </h3>
            <div class="flex items-center gap-3">
              <!-- Use AI Reply Toggle -->
              <div class="flex items-center gap-2">
                <label class="text-sm text-wecom-text font-medium">{{
                  t('followup_manage.use_ai_reply')
                }}</label>
                <input
                  v-model="settings.useAIReply"
                  type="checkbox"
                  class="w-10 h-5 rounded-full bg-wecom-surface border border-wecom-border"
                />
              </div>
              <button
                :disabled="settings.useAIReply"
                class="px-3 py-1.5 bg-wecom-primary hover:bg-wecom-primary/80 text-white rounded text-xs transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                @click="addMessageTemplate"
              >
                ➕ {{ t('followup_manage.add_template') }}
              </button>
            </div>
          </div>

          <!-- Templates List with Overlay -->
          <div class="relative">
            <!-- Gray Overlay when AI is enabled -->
            <div
              v-if="settings.useAIReply"
              class="absolute inset-0 bg-gray-900/50 backdrop-blur-[2px] rounded-lg z-10 flex items-center justify-center"
            >
              <div class="text-center">
                <p class="text-sm text-wecom-text font-medium">
                  🤖 {{ t('followup_manage.ai_mode_active') }}
                </p>
                <p class="text-xs text-wecom-muted mt-1">{{ t('followup_manage.ai_mode_desc') }}</p>
              </div>
            </div>

            <!-- Templates -->
            <div class="space-y-3">
              <div
                v-for="(_, index) in settings.followupMessageTemplates"
                :key="index"
                class="flex items-center gap-2"
              >
                <span class="text-xs text-wecom-muted w-6">{{ index + 1 }}</span>
                <input
                  v-model="settings.followupMessageTemplates[index]"
                  type="text"
                  :placeholder="t('followup_manage.template_placeholder')"
                  :disabled="settings.useAIReply"
                  class="flex-1 px-3 py-2 bg-wecom-surface border border-wecom-border rounded-lg text-sm text-wecom-text focus:outline-none focus:border-wecom-primary disabled:opacity-50 disabled:cursor-not-allowed"
                />
                <button
                  v-if="settings.followupMessageTemplates.length > 1"
                  :disabled="settings.useAIReply"
                  class="px-2 py-2 bg-red-600 hover:bg-red-700 text-white rounded text-xs transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  :title="t('followup_manage.delete')"
                  @click="removeMessageTemplate(index)"
                >
                  🗑️
                </button>
              </div>
              <p class="text-xs text-wecom-muted mt-2">
                💡 {{ t('followup_manage.template_hint') }}
              </p>
            </div>
          </div>

          <!-- Avoid Duplicate Messages Checkbox -->
          <div class="border-t border-wecom-border pt-4 mt-4">
            <div class="flex items-center gap-2">
              <input
                v-model="settings.avoidDuplicateMessages"
                type="checkbox"
                :disabled="settings.followupMessageTemplates.length < 3"
                class="w-5 h-5 rounded bg-wecom-surface border border-wecom-border disabled:opacity-50"
              />
              <div>
                <label
                  class="text-sm text-wecom-text font-medium"
                  :class="{
                    'text-wecom-muted cursor-not-allowed':
                      settings.followupMessageTemplates.length < 3,
                  }"
                >
                  🎯 {{ t('followup_manage.avoid_duplicate_messages') }}
                </label>
                <p class="text-xs text-wecom-muted mt-1">
                  {{ t('followup_manage.avoid_duplicate_messages_desc') }}
                </p>
              </div>
            </div>

            <!-- Warning when disabled -->
            <p
              v-if="settings.followupMessageTemplates.length < 3"
              class="text-xs text-yellow-400 mt-2"
            >
              ⚠️ {{ t('followup_manage.avoid_duplicate_messages_warning') }}
            </p>
          </div>
        </div>

        <!-- Followup Prompt Card (Only visible when AI Reply is enabled) -->
        <div
          v-if="settings.useAIReply"
          class="bg-wecom-dark/80 backdrop-blur rounded-xl p-6 border border-wecom-border"
        >
          <h3 class="text-sm font-semibold text-wecom-text flex items-center gap-2 mb-4">
            🤖 {{ t('followup_manage.followup_prompt') }}
          </h3>

          <div class="space-y-4">
            <div>
              <label class="block text-sm text-wecom-text font-medium mb-2">
                {{ t('followup_manage.followup_prompt_label') }}
              </label>
              <textarea
                v-model="settings.followupPrompt"
                :placeholder="t('followup_manage.followup_prompt_placeholder')"
                rows="5"
                class="w-full px-4 py-3 bg-wecom-surface border border-wecom-border rounded-lg text-sm text-wecom-text placeholder-wecom-muted resize-none focus:outline-none focus:border-wecom-primary"
              ></textarea>
              <p class="text-xs text-wecom-muted mt-2">
                💡 {{ t('followup_manage.followup_prompt_hint') }}
              </p>
            </div>
          </div>
        </div>

        <!-- Action Buttons -->
        <div class="flex items-center gap-3">
          <button
            :disabled="savingSettings"
            class="px-6 py-3 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg flex items-center gap-2 transition-colors disabled:opacity-50 font-medium"
            @click="saveSettings"
          >
            {{
              savingSettings
                ? '💾 ' + t('followup_manage.saving')
                : '💾 ' + t('followup_manage.save')
            }}
          </button>
          <button
            class="px-6 py-3 bg-wecom-surface hover:bg-wecom-surface/80 text-wecom-text border border-wecom-border rounded-lg transition-colors font-medium"
            @click="resetSettings"
          >
            🔄 {{ t('followup_manage.reset_defaults') }}
          </button>
        </div>

        <!-- Info Box -->
        <div class="bg-blue-500/10 border-l-4 border-blue-500 rounded-xl p-6">
          <h3 class="text-sm font-semibold text-blue-400 flex items-center gap-2 mb-3">
            ℹ️ {{ t('followup_manage.how_it_works') }}
          </h3>
          <div class="space-y-2 text-sm text-wecom-text">
            <p>• {{ t('followup_manage.how_it_works_1') }}</p>
            <p>• {{ t('followup_manage.how_it_works_2') }}</p>
            <p>• {{ t('followup_manage.how_it_works_3') }}</p>
            <p>• {{ t('followup_manage.how_it_works_4') }}</p>
          </div>
        </div>
      </div>
    </div>

    <!-- Toast -->
    <Toast :show="showToast" :message="toastMessage" :type="toastType" @close="showToast = false" />
  </div>
</template>

<style scoped>
/* Dark theme input styling */
input[type='number'],
input[type='date'],
select {
  color-scheme: dark;
}

input[type='checkbox'] {
  accent-color: #1aad19;
}

/* Custom scrollbar for dark theme */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: rgba(31, 41, 55, 0.5);
}

::-webkit-scrollbar-thumb {
  background: rgba(75, 85, 99, 0.8);
  border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
  background: rgba(107, 114, 128, 0.8);
}
</style>
