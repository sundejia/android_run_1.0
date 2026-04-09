<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useCustomerStore, type CustomerFilters } from '../stores/customers'
import { avatarUrlForCustomer, refreshAvatars } from '../utils/avatars'
import { api, type CustomerSummary, type MessageSearchResult } from '../services/api'
import { useI18n } from '../composables/useI18n'

const customerStore = useCustomerStore()
const router = useRouter()
const { t } = useI18n()

const searchInput = ref(customerStore.search)

// Message content search state
const searchMode = ref<'name' | 'message'>('name')
const messageSearchResults = ref<MessageSearchResult[]>([])
const messageSearchLoading = ref(false)
const showSearchDropdown = ref(false)
const selectedResultIndex = ref(-1)
let searchDebounceTimer: number | null = null
const currentPage = ref(1)
const pageSize = ref(customerStore.limit || 20)
const pageSizeOptions = [10, 20, 50, 100]

// Delete confirmation state
const showDeleteModal = ref(false)
const customerToDelete = ref<CustomerSummary | null>(null)
const deleteSuccessMessage = ref<string | null>(null)

// Filter state
const selectedStreamer = ref<string>('')
const selectedAgent = ref<string>('')
const selectedDevice = ref<string>('')
const dateFrom = ref<string>('')
const dateTo = ref<string>('')
const showFilters = ref(false)

// Sort state
const sortBy = ref<string>('last_message_at')
const sortOrder = ref<'asc' | 'desc'>('desc')

// Column definitions for sorting
const sortableColumns = computed(() => [
  { key: 'name', label: t('conversations.table_streamer') },
  { key: 'kefu_name', label: t('conversations.table_agent') },
  { key: 'device_serial', label: t('conversations.table_device') },
  { key: 'last_message_at', label: t('conversations.table_last_message') },
  { key: 'last_message_preview', label: t('conversations.table_preview') },
  { key: 'message_count', label: t('conversations.table_totals') },
  { key: '_actions', label: t('common.actions'), sortable: false },
])

function toggleSort(column: string) {
  if (sortBy.value === column) {
    // Toggle order if same column
    sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
  } else {
    // New column, default to desc
    sortBy.value = column
    sortOrder.value = 'desc'
  }
  currentPage.value = 1
  load(1)
}

function getSortIcon(column: string): string {
  if (sortBy.value !== column) return '↕️'
  return sortOrder.value === 'asc' ? '↑' : '↓'
}

const totalPages = computed(() => Math.max(1, Math.ceil(customerStore.total / pageSize.value)))

const showingFrom = computed(() => {
  if (customerStore.total === 0) return 0
  return (currentPage.value - 1) * pageSize.value + 1
})

const showingTo = computed(() => {
  return Math.min(customerStore.total, currentPage.value * pageSize.value)
})

const activeFiltersCount = computed(() => {
  let count = 0
  if (selectedStreamer.value) count++
  if (selectedAgent.value) count++
  if (selectedDevice.value) count++
  if (dateFrom.value) count++
  if (dateTo.value) count++
  return count
})

function formatDate(value: string | null | undefined) {
  if (!value) return '—'
  const parsed = new Date(value)
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toLocaleString()
  }
  return value
}

function buildFilters(): CustomerFilters {
  return {
    streamer: selectedStreamer.value || undefined,
    kefuId: selectedAgent.value ? parseInt(selectedAgent.value, 10) : undefined,
    deviceSerial: selectedDevice.value || undefined,
    dateFrom: dateFrom.value || undefined,
    dateTo: dateTo.value || undefined,
    sortBy: sortBy.value || undefined,
    sortOrder: sortOrder.value || undefined,
  }
}

async function load(page: number = currentPage.value) {
  currentPage.value = page
  const offset = (currentPage.value - 1) * pageSize.value
  await customerStore.fetchCustomers({
    search: searchInput.value.trim(),
    limit: pageSize.value,
    offset,
    filters: buildFilters(),
  })
}

function handleSearch() {
  if (searchMode.value === 'message' && messageSearchResults.value.length > 0) {
    // If there are message search results and user pressed Enter, go to first result
    goToSearchResult(messageSearchResults.value[0])
    return
  }
  currentPage.value = 1
  load(1)
}

function clearSearch() {
  searchInput.value = ''
  messageSearchResults.value = []
  showSearchDropdown.value = false
  selectedResultIndex.value = -1
  currentPage.value = 1
  load(1)
}

// Message content search functions
async function searchMessages() {
  const query = searchInput.value.trim()
  if (!query || query.length < 2) {
    messageSearchResults.value = []
    showSearchDropdown.value = false
    return
  }

  messageSearchLoading.value = true
  try {
    const response = await api.searchMessages({ q: query, limit: 50 })
    messageSearchResults.value = response.results
    showSearchDropdown.value = response.results.length > 0
    selectedResultIndex.value = -1
  } catch (e) {
    console.error('Message search failed:', e)
    messageSearchResults.value = []
  } finally {
    messageSearchLoading.value = false
  }
}

function handleSearchInput() {
  if (searchMode.value === 'message') {
    // Debounce the message search
    if (searchDebounceTimer) {
      clearTimeout(searchDebounceTimer)
    }
    searchDebounceTimer = window.setTimeout(() => {
      searchMessages()
    }, 300)
  }
}

function goToSearchResult(result: MessageSearchResult) {
  showSearchDropdown.value = false
  selectedResultIndex.value = -1

  // Store all search results in sessionStorage for cross-conversation navigation
  const searchResultIndex = messageSearchResults.value.findIndex(
    (r) => r.message_id === result.message_id && r.customer_id === result.customer_id
  )
  sessionStorage.setItem('messageSearchResults', JSON.stringify(messageSearchResults.value))
  sessionStorage.setItem('messageSearchIndex', searchResultIndex.toString())
  sessionStorage.setItem('messageSearchQuery', searchInput.value.trim())

  // Navigate to conversation detail with highlight and search query for "next match" navigation
  router.push({
    name: 'conversation-detail',
    params: { id: result.customer_id },
    query: {
      highlightMessage: result.message_id.toString(),
      searchQuery: searchInput.value.trim(),
    },
  })
}

function handleSearchKeydown(event: KeyboardEvent) {
  if (searchMode.value !== 'message' || !showSearchDropdown.value) return

  if (event.key === 'ArrowDown') {
    event.preventDefault()
    selectedResultIndex.value = Math.min(
      selectedResultIndex.value + 1,
      messageSearchResults.value.length - 1
    )
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    selectedResultIndex.value = Math.max(selectedResultIndex.value - 1, -1)
  } else if (event.key === 'Enter' && selectedResultIndex.value >= 0) {
    event.preventDefault()
    goToSearchResult(messageSearchResults.value[selectedResultIndex.value])
  } else if (event.key === 'Escape') {
    showSearchDropdown.value = false
    selectedResultIndex.value = -1
  }
}

function handleSearchBlur() {
  // Delay hiding dropdown to allow click events on results
  setTimeout(() => {
    showSearchDropdown.value = false
    selectedResultIndex.value = -1
  }, 200)
}

function highlightSearchTerm(text: string, query: string): string {
  if (!query) return text
  const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
  return text.replace(
    regex,
    '<mark class="bg-yellow-400/50 text-yellow-100 px-0.5 rounded">$1</mark>'
  )
}

function formatSearchResultTime(timestamp: string | null): string {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  if (isNaN(date.getTime())) return ''
  return date.toLocaleString()
}

function clearFilters() {
  selectedStreamer.value = ''
  selectedAgent.value = ''
  selectedDevice.value = ''
  dateFrom.value = ''
  dateTo.value = ''
  currentPage.value = 1
  load(1)
}

function applyFilters() {
  currentPage.value = 1
  load(1)
}

function handlePageSizeChange() {
  currentPage.value = 1
  load(1)
}

function nextPage() {
  if (currentPage.value < totalPages.value) {
    load(currentPage.value + 1)
  }
}

function prevPage() {
  if (currentPage.value > 1) {
    load(currentPage.value - 1)
  }
}

function openCustomer(id: number) {
  router.push({ name: 'conversation-detail', params: { id } })
}

function openDeleteModal(customer: CustomerSummary, event: Event) {
  event.stopPropagation()
  customerToDelete.value = customer
  showDeleteModal.value = true
}

function closeDeleteModal() {
  showDeleteModal.value = false
  customerToDelete.value = null
}

async function confirmDelete() {
  if (!customerToDelete.value) return

  try {
    const deleted = await customerStore.deleteCustomer(customerToDelete.value.id)
    deleteSuccessMessage.value = t('conversations.delete_success', {
      name: deleted.customer_name,
      messages: deleted.messages_removed,
    })
    closeDeleteModal()

    // Auto-hide success message after 5 seconds
    setTimeout(() => {
      deleteSuccessMessage.value = null
    }, 5000)
  } catch {
    // Error is handled by the store
  }
}

onMounted(async () => {
  // Refresh avatar list in case new avatars were captured
  await refreshAvatars()
  customerStore.fetchFilterOptions()
  load(1)
})

watch(
  () => customerStore.total,
  () => {
    const maxPage = Math.max(1, Math.ceil(customerStore.total / pageSize.value))
    if (currentPage.value > maxPage) {
      currentPage.value = maxPage
    }
  }
)
</script>

<template>
  <div class="p-6 space-y-6 animate-fade-in">
    <!-- Header -->
    <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
      <div>
        <h2 class="text-2xl font-display font-bold text-wecom-text">
          {{ t('conversations.title') }}
        </h2>
        <p class="text-sm text-wecom-muted mt-1">
          {{ t('conversations.subtitle') }}
        </p>
        <p v-if="customerStore.lastFetchedPath" class="text-xs text-wecom-muted mt-2">
          {{ t('kefus.db_label') }}: {{ customerStore.lastFetchedPath }}
        </p>
      </div>

      <div class="flex items-center gap-2">
        <button class="btn-secondary text-sm" :disabled="customerStore.listLoading" @click="load()">
          <span :class="{ 'animate-spin': customerStore.listLoading }">🔄</span>
          {{ t('common.refresh') }}
        </button>
      </div>
    </div>

    <!-- Search and Filters -->
    <div class="bg-wecom-dark border border-wecom-border rounded-xl p-4 space-y-4">
      <!-- Search Row -->
      <div class="flex flex-col lg:flex-row gap-3 lg:items-center lg:justify-between">
        <div class="flex flex-1 items-center gap-2">
          <!-- Search Mode Toggle -->
          <div class="flex bg-wecom-surface border border-wecom-border rounded-lg overflow-hidden">
            <button
              class="px-3 py-2 text-xs font-medium transition-colors"
              :class="
                searchMode === 'name'
                  ? 'bg-wecom-primary text-white'
                  : 'text-wecom-muted hover:text-wecom-text'
              "
              @click="
                searchMode = 'name';
                showSearchDropdown = false;
              "
              :title="t('conversations.search_by_name_tooltip')"
            >
              {{ t('conversations.search_mode_name') }}
            </button>
            <button
              class="px-3 py-2 text-xs font-medium transition-colors"
              :class="
                searchMode === 'message'
                  ? 'bg-wecom-primary text-white'
                  : 'text-wecom-muted hover:text-wecom-text'
              "
              @click="
                searchMode = 'message';
                searchMessages();
              "
              :title="t('conversations.search_by_message_tooltip')"
            >
              {{ t('conversations.search_mode_message') }}
            </button>
          </div>

          <!-- Search Input with Dropdown -->
          <div class="relative flex-1">
            <input
              v-model="searchInput"
              type="text"
              :placeholder="
                searchMode === 'name'
                  ? t('conversations.search_name_placeholder')
                  : t('conversations.search_message_placeholder')
              "
              class="w-full px-3 py-2 rounded-lg bg-wecom-surface border border-wecom-border text-sm text-wecom-text focus:outline-none focus:ring-2 focus:ring-wecom-primary"
              @keyup.enter="handleSearch"
              @input="handleSearchInput"
              @keydown="handleSearchKeydown"
              @blur="handleSearchBlur"
              @focus="
                searchMode === 'message' &&
                searchInput.trim().length >= 2 &&
                (showSearchDropdown = messageSearchResults.length > 0)
              "
            />

            <!-- Loading indicator -->
            <div v-if="messageSearchLoading" class="absolute right-3 top-1/2 -translate-y-1/2">
              <span class="animate-spin text-wecom-muted">⏳</span>
            </div>

            <!-- Message Search Results Dropdown -->
            <div
              v-if="
                showSearchDropdown && searchMode === 'message' && messageSearchResults.length > 0
              "
              class="absolute top-full left-0 right-0 mt-1 bg-wecom-dark border border-wecom-border rounded-lg shadow-xl z-50 max-h-[400px] overflow-y-auto"
            >
              <div class="p-2 text-xs text-wecom-muted border-b border-wecom-border">
                {{ t('conversations.search_results_hint', { count: messageSearchResults.length }) }}
              </div>
              <div
                v-for="(result, index) in messageSearchResults"
                :key="result.message_id"
                class="px-3 py-2 cursor-pointer transition-colors border-b border-wecom-border/50 last:border-b-0"
                :class="
                  selectedResultIndex === index
                    ? 'bg-wecom-primary/20 border-l-2 border-l-wecom-primary'
                    : 'hover:bg-wecom-surface'
                "
                @mousedown.prevent="goToSearchResult(result)"
                @mouseenter="selectedResultIndex = index"
              >
                <div class="flex items-center justify-between mb-1">
                  <span class="font-medium text-wecom-text text-sm">
                    {{ result.customer_name }}
                    <span v-if="result.customer_channel" class="text-wecom-muted text-xs ml-1">
                      ({{ result.customer_channel }})
                    </span>
                  </span>
                  <span class="text-xs text-wecom-muted">
                    {{
                      result.is_from_kefu
                        ? t('conversations.table_agent')
                        : t('conversations.table_streamer')
                    }}
                  </span>
                </div>
                <p
                  class="text-sm text-wecom-text/80 line-clamp-2"
                  v-html="highlightSearchTerm(result.content_preview, searchInput)"
                ></p>
                <div class="flex items-center gap-2 mt-1 text-xs text-wecom-muted">
                  <span>{{ result.kefu_name }}</span>
                  <span>·</span>
                  <span>{{ formatSearchResultTime(result.timestamp) }}</span>
                </div>
              </div>
            </div>
          </div>

          <button
            class="btn-primary text-sm"
            :disabled="customerStore.listLoading"
            @click="handleSearch"
          >
            {{ t('common.search') }}
          </button>
          <button
            class="btn-secondary text-sm"
            :disabled="customerStore.listLoading && customerStore.customers.length === 0"
            @click="clearSearch"
          >
            {{ t('kefus.clear') }}
          </button>
          <button
            class="btn-secondary text-sm flex items-center gap-1"
            :class="{ 'ring-2 ring-wecom-primary': showFilters || activeFiltersCount > 0 }"
            @click="showFilters = !showFilters"
          >
            <span>🔽</span>
            {{ t('conversations.filters') }}
            <span
              v-if="activeFiltersCount > 0"
              class="bg-wecom-primary text-white text-xs px-1.5 py-0.5 rounded-full"
            >
              {{ activeFiltersCount }}
            </span>
          </button>
        </div>

        <div class="flex items-center gap-3 text-sm text-wecom-muted">
          <span class="text-wecom-text font-semibold">{{ customerStore.total }}</span>
          {{ t('conversations.total_label') }}

          <label class="flex items-center gap-2">
            <span>{{ t('kefus.per_page') }}</span>
            <select
              v-model.number="pageSize"
              class="bg-wecom-surface border border-wecom-border rounded-lg px-2 py-1 text-wecom-text"
              @change="handlePageSizeChange"
            >
              <option v-for="size in pageSizeOptions" :key="size" :value="size">
                {{ size }}
              </option>
            </select>
          </label>
        </div>
      </div>

      <!-- Filters Panel -->
      <div v-if="showFilters" class="border-t border-wecom-border pt-4 space-y-4">
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <!-- Streamer Filter -->
          <div class="space-y-1">
            <label class="text-xs text-wecom-muted font-medium">{{
              t('conversations.filter_streamer')
            }}</label>
            <select
              v-model="selectedStreamer"
              class="w-full px-3 py-2 rounded-lg bg-wecom-surface border border-wecom-border text-sm text-wecom-text focus:outline-none focus:ring-2 focus:ring-wecom-primary"
            >
              <option value="">{{ t('conversations.filter_all_streamers') }}</option>
              <option
                v-for="streamer in customerStore.filterOptions.streamers"
                :key="streamer"
                :value="streamer"
              >
                {{ streamer }}
              </option>
            </select>
          </div>

          <!-- Agent Filter -->
          <div class="space-y-1">
            <label class="text-xs text-wecom-muted font-medium">{{
              t('conversations.filter_agent')
            }}</label>
            <select
              v-model="selectedAgent"
              class="w-full px-3 py-2 rounded-lg bg-wecom-surface border border-wecom-border text-sm text-wecom-text focus:outline-none focus:ring-2 focus:ring-wecom-primary"
            >
              <option value="">{{ t('conversations.filter_all_agents') }}</option>
              <option
                v-for="agent in customerStore.filterOptions.agents"
                :key="agent.id"
                :value="agent.id.toString()"
              >
                {{ agent.name }}{{ agent.department ? ` (${agent.department})` : '' }}
              </option>
            </select>
          </div>

          <!-- Device Filter -->
          <div class="space-y-1">
            <label class="text-xs text-wecom-muted font-medium">{{
              t('conversations.filter_device')
            }}</label>
            <select
              v-model="selectedDevice"
              class="w-full px-3 py-2 rounded-lg bg-wecom-surface border border-wecom-border text-sm text-wecom-text focus:outline-none focus:ring-2 focus:ring-wecom-primary"
            >
              <option value="">{{ t('conversations.filter_all_devices') }}</option>
              <option
                v-for="device in customerStore.filterOptions.devices"
                :key="device.serial"
                :value="device.serial"
              >
                {{ device.serial }}{{ device.model ? ` (${device.model})` : '' }}
              </option>
            </select>
          </div>

          <!-- Date Range placeholder for grid alignment -->
          <div></div>
        </div>

        <!-- Date Range Row -->
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <!-- Date From -->
          <div class="space-y-1">
            <label class="text-xs text-wecom-muted font-medium">{{
              t('conversations.filter_from_date')
            }}</label>
            <input
              v-model="dateFrom"
              type="date"
              class="w-full px-3 py-2 rounded-lg bg-wecom-surface border border-wecom-border text-sm text-wecom-text focus:outline-none focus:ring-2 focus:ring-wecom-primary"
            />
          </div>

          <!-- Date To -->
          <div class="space-y-1">
            <label class="text-xs text-wecom-muted font-medium">{{
              t('conversations.filter_to_date')
            }}</label>
            <input
              v-model="dateTo"
              type="date"
              class="w-full px-3 py-2 rounded-lg bg-wecom-surface border border-wecom-border text-sm text-wecom-text focus:outline-none focus:ring-2 focus:ring-wecom-primary"
            />
          </div>

          <!-- Apply/Clear Buttons -->
          <div class="flex items-end gap-2 lg:col-span-2">
            <button
              class="btn-primary text-sm px-4"
              :disabled="customerStore.listLoading"
              @click="applyFilters"
            >
              {{ t('conversations.filter_apply') }}
            </button>
            <button
              class="btn-secondary text-sm px-4"
              :disabled="customerStore.listLoading && activeFiltersCount === 0"
              @click="clearFilters"
            >
              {{ t('conversations.filter_clear') }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Error state -->
    <div
      v-if="customerStore.listError"
      class="bg-red-900/20 border border-red-500/30 rounded-lg p-4 flex items-center gap-3"
    >
      <span class="text-red-400">⚠️</span>
      <div>
        <p class="text-red-400 font-medium">{{ t('conversations.load_failed') }}</p>
        <p class="text-red-400/70 text-sm">{{ customerStore.listError }}</p>
      </div>
      <button class="btn-secondary text-sm ml-auto" @click="load()">
        {{ t('common.retry') }}
      </button>
    </div>

    <!-- Loading state -->
    <div
      v-else-if="customerStore.listLoading && customerStore.customers.length === 0"
      class="bg-wecom-dark border border-wecom-border rounded-xl p-6 flex items-center justify-center text-wecom-muted"
    >
      {{ t('conversations.loading') }}
    </div>

    <!-- Empty state -->
    <div
      v-else-if="!customerStore.listLoading && customerStore.customers.length === 0"
      class="bg-wecom-dark border border-wecom-border rounded-xl p-6 text-center text-wecom-muted"
    >
      {{ t('conversations.empty_state') }}
    </div>

    <!-- Table -->
    <div v-else class="bg-wecom-dark border border-wecom-border rounded-xl overflow-hidden">
      <div class="overflow-auto max-h-[540px]">
        <table class="min-w-full text-sm">
          <thead class="bg-wecom-surface border-b border-wecom-border text-wecom-muted">
            <tr>
              <th
                v-for="col in sortableColumns"
                :key="col.key"
                class="text-left px-4 py-2 select-none transition-colors"
                :class="col.key !== '_actions' ? 'cursor-pointer hover:bg-wecom-dark/50' : ''"
                @click="col.key !== '_actions' && toggleSort(col.key)"
              >
                <div class="flex items-center gap-1">
                  <span>{{ col.label }}</span>
                  <span
                    v-if="col.key !== '_actions'"
                    class="text-xs"
                    :class="sortBy === col.key ? 'text-wecom-primary' : 'text-wecom-muted/50'"
                  >
                    {{ getSortIcon(col.key) }}
                  </span>
                </div>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="customer in customerStore.customers"
              :key="customer.id"
              class="border-b border-wecom-border hover:bg-wecom-surface/60 transition-colors cursor-pointer"
              @click="openCustomer(customer.id)"
            >
              <td class="px-4 py-2">
                <div class="flex items-center gap-3">
                  <img
                    :src="avatarUrlForCustomer(customer)"
                    :alt="`Avatar for ${customer.name}`"
                    class="w-10 h-10 rounded-full border border-wecom-border bg-wecom-surface object-cover shrink-0"
                  />
                  <div>
                    <p class="text-wecom-text font-medium">{{ customer.name }}</p>
                    <p class="text-xs text-wecom-muted">
                      {{ customer.channel || '—' }}
                    </p>
                  </div>
                </div>
              </td>
              <td class="px-4 py-2 text-wecom-text">
                <p class="font-medium">{{ customer.kefu_name }}</p>
                <p class="text-xs text-wecom-muted">
                  {{ customer.kefu_department || t('kefus.no_dept') }} ·
                  {{ customer.kefu_verification_status || t('kefus.not_verified') }}
                </p>
              </td>
              <td class="px-4 py-2 text-wecom-muted">
                <p class="text-wecom-text font-medium">{{ customer.device_serial }}</p>
                <p class="text-xs">
                  {{ customer.device_model || t('conversations.unknown_model') }}
                </p>
              </td>
              <td class="px-4 py-2 text-wecom-text">
                {{ formatDate(customer.last_message_at || customer.last_message_date) }}
              </td>
              <td
                class="px-4 py-2 text-wecom-muted truncate max-w-xs"
                :title="customer.last_message_preview || undefined"
              >
                {{ customer.last_message_preview || '—' }}
              </td>
              <td class="px-4 py-2 text-wecom-text">
                {{
                  t('conversations.message_stats', {
                    count: customer.message_count,
                    sent: customer.sent_by_kefu,
                    recv: customer.sent_by_customer,
                  })
                }}
              </td>
              <td class="px-4 py-2">
                <button
                  class="text-red-400 hover:text-red-300 hover:bg-red-900/30 p-1.5 rounded transition-colors"
                  :title="t('conversations.delete_conversation')"
                  @click="openDeleteModal(customer, $event)"
                >
                  🗑️
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div
        class="flex flex-col md:flex-row items-center justify-between gap-3 px-4 py-3 bg-wecom-surface border-t border-wecom-border text-sm"
      >
        <div class="text-wecom-muted">
          {{ t('kefus.showing', { from: showingFrom, to: showingTo, total: customerStore.total }) }}
        </div>
        <div class="flex items-center gap-2">
          <button class="btn-secondary text-xs" :disabled="currentPage === 1" @click="prevPage">
            {{ t('common.previous') }}
          </button>
          <span class="text-wecom-text text-sm">
            {{ t('kefus.page_current', { current: currentPage, total: totalPages }) }}
          </span>
          <button
            class="btn-secondary text-xs"
            :disabled="currentPage >= totalPages"
            @click="nextPage"
          >
            {{ t('common.next') }}
          </button>
        </div>
      </div>
    </div>

    <!-- Delete Success Message -->
    <Transition name="fade">
      <div
        v-if="deleteSuccessMessage"
        class="fixed bottom-4 right-4 bg-green-900/90 border border-green-500/30 rounded-lg px-4 py-3 flex items-center gap-3 shadow-lg z-50"
      >
        <span class="text-green-400">✓</span>
        <p class="text-green-300 text-sm">{{ deleteSuccessMessage }}</p>
        <button
          class="text-green-400 hover:text-green-300 ml-2"
          @click="deleteSuccessMessage = null"
        >
          ✕
        </button>
      </div>
    </Transition>

    <!-- Delete Confirmation Modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showDeleteModal"
          class="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
          @click.self="closeDeleteModal"
        >
          <div
            class="bg-wecom-dark border border-wecom-border rounded-xl p-6 max-w-md w-full mx-4 shadow-xl"
          >
            <h3 class="text-lg font-semibold text-wecom-text mb-2">
              {{ t('conversations.delete_title') }}
            </h3>
            <p class="text-wecom-muted text-sm mb-4">
              {{
                t('conversations.delete_confirm', {
                  name: customerToDelete?.name,
                  channel: customerToDelete?.channel,
                })
              }}
            </p>

            <div class="bg-red-900/20 border border-red-500/30 rounded-lg p-3 mb-4">
              <p class="text-red-400 text-sm font-medium mb-1">
                {{ t('conversations.delete_warning_title') }}
              </p>
              <ul class="text-red-400/80 text-xs space-y-0.5 ml-4 list-disc">
                <li>
                  {{
                    t('conversations.delete_warning_messages', {
                      count: customerToDelete?.message_count || 0,
                    })
                  }}
                </li>
                <li>{{ t('conversations.delete_warning_images') }}</li>
              </ul>
            </div>

            <p class="text-wecom-muted text-xs mb-4">
              {{ t('conversations.delete_tip') }}
            </p>

            <div
              v-if="customerStore.deleteError"
              class="bg-red-900/20 border border-red-500/30 rounded-lg p-3 mb-4"
            >
              <p class="text-red-400 text-sm">{{ customerStore.deleteError }}</p>
            </div>

            <div class="flex justify-end gap-3">
              <button
                class="btn-secondary text-sm"
                :disabled="customerStore.deleteLoading"
                @click="closeDeleteModal"
              >
                {{ t('common.cancel') }}
              </button>
              <button
                class="bg-red-600 hover:bg-red-500 text-white px-4 py-2 rounded-lg text-sm transition-colors disabled:opacity-50"
                :disabled="customerStore.deleteLoading"
                @click="confirmDelete"
              >
                <span v-if="customerStore.deleteLoading">{{ t('kefus.deleting') }}</span>
                <span v-else>{{ t('common.delete') }}</span>
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
.modal-enter-active .bg-wecom-dark,
.modal-leave-active .bg-wecom-dark {
  transition: transform 0.2s ease;
}
.modal-enter-from .bg-wecom-dark,
.modal-leave-to .bg-wecom-dark {
  transform: scale(0.95);
}
</style>
