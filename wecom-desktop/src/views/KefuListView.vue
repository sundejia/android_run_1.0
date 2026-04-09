<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useKefuStore } from '../stores/kefus'
import { useI18n } from '../composables/useI18n'
import type { KefuSummary } from '../services/api'

const kefuStore = useKefuStore()
const router = useRouter()
const route = useRoute()
const { t } = useI18n()

const searchInput = ref(kefuStore.search)
const currentPage = ref(1)
const pageSize = ref(kefuStore.limit || 20)
const pageSizeOptions = [10, 20, 50, 100]

// Delete confirmation state
const showDeleteModal = ref(false)
const kefuToDelete = ref<KefuSummary | null>(null)
const deleteSuccessMessage = ref<string | null>(null)

const totalPages = computed(() =>
  Math.max(1, Math.ceil(kefuStore.total / pageSize.value)),
)

const showingFrom = computed(() => {
  if (kefuStore.total === 0) return 0
  return (currentPage.value - 1) * pageSize.value + 1
})

const showingTo = computed(() => {
  return Math.min(kefuStore.total, currentPage.value * pageSize.value)
})

function formatDate(value: string | null | undefined) {
  if (!value) return '—'
  const parsed = new Date(value)
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toLocaleString()
  }
  return value
}

async function load(page: number = currentPage.value) {
  currentPage.value = page
  const offset = (currentPage.value - 1) * pageSize.value
  await kefuStore.fetchKefus({
    search: searchInput.value.trim(),
    limit: pageSize.value,
    offset,
  })
}

function handleSearch() {
  currentPage.value = 1
  load(1)
}

function clearSearch() {
  searchInput.value = ''
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

function openKefu(id: number) {
  router.push({ name: 'kefu-detail', params: { id } })
}

function openDeleteModal(kefu: KefuSummary, event: Event) {
  event.stopPropagation()
  kefuToDelete.value = kefu
  showDeleteModal.value = true
}

function closeDeleteModal() {
  showDeleteModal.value = false
  kefuToDelete.value = null
}

async function confirmDelete() {
  if (!kefuToDelete.value) return

  try {
    const deleted = await kefuStore.deleteKefu(kefuToDelete.value.id)
    deleteSuccessMessage.value = t('kefus.delete_success', {
      name: deleted.kefu_name,
      customers: deleted.customers_removed,
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

onMounted(() => {
  // Check for search query parameter from URL (e.g., navigated from devices page)
  const urlSearch = route.query.search
  if (urlSearch && typeof urlSearch === 'string') {
    searchInput.value = urlSearch
    // Clear the query param from URL to avoid persisting it on refresh
    router.replace({ query: {} })
  }
  load(1)
})

watch(
  () => kefuStore.total,
  () => {
    const maxPage = Math.max(1, Math.ceil(kefuStore.total / pageSize.value))
    if (currentPage.value > maxPage) {
      currentPage.value = maxPage
    }
  },
)
</script>

<template>
  <div class="p-6 space-y-6 animate-fade-in">
    <!-- Header -->
    <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
      <div>
        <h2 class="text-2xl font-display font-bold text-wecom-text">
          {{ t('kefus.title') }}
        </h2>
        <p class="text-sm text-wecom-muted mt-1">
          {{ t('kefus.subtitle') }}
        </p>
        <p v-if="kefuStore.lastFetchedPath" class="text-xs text-wecom-muted mt-2">
          {{ t('kefus.db_label') }}: {{ kefuStore.lastFetchedPath }}
        </p>
      </div>

      <div class="flex items-center gap-2">
        <button
          class="btn-secondary text-sm"
          :disabled="kefuStore.listLoading"
          @click="load()"
        >
          <span :class="{ 'animate-spin': kefuStore.listLoading }">🔄</span>
          {{ t('common.refresh') }}
        </button>
      </div>
    </div>

    <!-- Filters -->
    <div class="bg-wecom-dark border border-wecom-border rounded-xl p-4 space-y-3">
      <div class="flex flex-col lg:flex-row gap-3 lg:items-center lg:justify-between">
        <div class="flex flex-1 items-center gap-2">
          <input
            v-model="searchInput"
            type="text"
            :placeholder="t('kefus.search_placeholder')"
            class="flex-1 px-3 py-2 rounded-lg bg-wecom-surface border border-wecom-border text-sm text-wecom-text focus:outline-none focus:ring-2 focus:ring-wecom-primary"
            @keyup.enter="handleSearch"
          />
          <button
            class="btn-primary text-sm"
            :disabled="kefuStore.listLoading"
            @click="handleSearch"
          >
            {{ t('common.search') }}
          </button>
          <button
            class="btn-secondary text-sm"
            :disabled="kefuStore.listLoading && kefuStore.kefus.length === 0"
            @click="clearSearch"
          >
            {{ t('kefus.clear') }}
          </button>
        </div>

        <div class="flex items-center gap-3 text-sm text-wecom-muted">
          <span class="text-wecom-text font-semibold">{{ kefuStore.total }}</span>
          {{ t('kefus.total_label') }}

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
    </div>

    <!-- Error state -->
    <div
      v-if="kefuStore.listError"
      class="bg-red-900/20 border border-red-500/30 rounded-lg p-4 flex items-center gap-3"
    >
      <span class="text-red-400">⚠️</span>
      <div>
        <p class="text-red-400 font-medium">{{ t('kefus.load_failed') }}</p>
        <p class="text-red-400/70 text-sm">{{ kefuStore.listError }}</p>
      </div>
      <button class="btn-secondary text-sm ml-auto" @click="load()">
        {{ t('common.retry') }}
      </button>
    </div>

    <!-- Loading state -->
    <div
      v-else-if="kefuStore.listLoading && kefuStore.kefus.length === 0"
      class="bg-wecom-dark border border-wecom-border rounded-xl p-6 flex items-center justify-center text-wecom-muted"
    >
      {{ t('kefus.loading') }}
    </div>

    <!-- Empty state -->
    <div
      v-else-if="!kefuStore.listLoading && kefuStore.kefus.length === 0"
      class="bg-wecom-dark border border-wecom-border rounded-xl p-6 text-center text-wecom-muted"
    >
      {{ t('kefus.empty_state') }}
    </div>

    <!-- Table -->
    <div
      v-else
      class="bg-wecom-dark border border-wecom-border rounded-xl overflow-hidden"
    >
      <div class="overflow-auto max-h-[540px]">
        <table class="min-w-full text-sm">
          <thead class="bg-wecom-surface border-b border-wecom-border text-wecom-muted">
            <tr>
              <th class="text-left px-4 py-2">{{ t('kefus.table_agent') }}</th>
              <th class="text-left px-4 py-2">{{ t('kefus.table_devices') }}</th>
              <th class="text-left px-4 py-2">{{ t('kefus.table_streamers') }}</th>
              <th class="text-left px-4 py-2">{{ t('kefus.table_messages') }}</th>
              <th class="text-left px-4 py-2">{{ t('kefus.table_last_message') }}</th>
              <th class="text-left px-4 py-2">{{ t('kefus.table_latest_streamer') }}</th>
              <th class="text-left px-4 py-2 w-20">{{ t('common.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="kefu in kefuStore.kefus"
              :key="kefu.id"
              class="border-b border-wecom-border hover:bg-wecom-surface/60 transition-colors cursor-pointer"
              @click="openKefu(kefu.id)"
            >
              <td class="px-4 py-2 text-wecom-text">
                <p class="font-medium">{{ kefu.name }}</p>
                <p class="text-xs text-wecom-muted">
                  {{ kefu.department || t('kefus.no_dept') }} · {{ kefu.verification_status || t('kefus.not_verified') }}
                </p>
              </td>
              <td class="px-4 py-2 text-wecom-muted">
                <div v-if="kefu.devices && kefu.devices.length > 0">
                  <p class="text-wecom-text font-medium">{{ kefu.devices.length }} {{ t('kefus.device_count', { count: kefu.devices.length }) }}</p>
                  <p class="text-xs truncate max-w-[150px]" :title="kefu.devices.map((d: any) => d.serial).join(', ')">
                    {{ kefu.devices.map((d: any) => d.serial).join(', ') }}
                  </p>
                </div>
                <div v-else>
                  <p class="text-wecom-muted">{{ t('kefus.no_devices') }}</p>
                </div>
              </td>
              <td class="px-4 py-2 text-wecom-text">
                {{ kefu.customer_count }}
              </td>
              <td class="px-4 py-2 text-wecom-text">
                {{ t('kefus.message_stats', { count: kefu.message_count, sent: kefu.sent_by_kefu, recv: kefu.sent_by_customer }) }}
              </td>
              <td class="px-4 py-2 text-wecom-text">
                {{ formatDate(kefu.last_message_at || kefu.last_message_date) }}
              </td>
              <td class="px-4 py-2 text-wecom-muted truncate max-w-xs" :title="kefu.last_message_preview || undefined">
                {{ kefu.last_customer_name || '—' }}
                <span v-if="kefu.last_customer_channel">({{ kefu.last_customer_channel }})</span>
                · {{ kefu.last_message_preview || '—' }}
              </td>
              <td class="px-4 py-2">
                <button
                  class="text-red-400 hover:text-red-300 hover:bg-red-900/30 p-1.5 rounded transition-colors"
                  :title="t('kefus.delete_agent')"
                  @click="openDeleteModal(kefu, $event)"
                >
                  🗑️
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div class="flex flex-col md:flex-row items-center justify-between gap-3 px-4 py-3 bg-wecom-surface border-t border-wecom-border text-sm">
        <div class="text-wecom-muted">
          {{ t('kefus.showing', { from: showingFrom, to: showingTo, total: kefuStore.total }) }}
        </div>
        <div class="flex items-center gap-2">
          <button
            class="btn-secondary text-xs"
            :disabled="currentPage === 1"
            @click="prevPage"
          >
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
          <div class="bg-wecom-dark border border-wecom-border rounded-xl p-6 max-w-md w-full mx-4 shadow-xl">
            <h3 class="text-lg font-semibold text-wecom-text mb-2">
              {{ t('kefus.delete_title') }}
            </h3>
            <p class="text-wecom-muted text-sm mb-4">
              {{ t('kefus.delete_confirm', { name: kefuToDelete?.name, department: kefuToDelete?.department }) }}
            </p>

            <div class="bg-red-900/20 border border-red-500/30 rounded-lg p-3 mb-4">
              <p class="text-red-400 text-sm font-medium mb-1">{{ t('kefus.delete_warning_title') }}</p>
              <ul class="text-red-400/80 text-xs space-y-0.5 ml-4 list-disc">
                <li>{{ t('kefus.delete_warning_conversations', { count: kefuToDelete?.customer_count || 0 }) }}</li>
                <li>{{ t('kefus.delete_warning_messages', { count: kefuToDelete?.message_count || 0 }) }}</li>
                <li>{{ t('kefus.delete_warning_devices', { count: kefuToDelete?.devices?.length || 0 }) }}</li>
              </ul>
            </div>

            <p class="text-wecom-muted text-xs mb-4">
              {{ t('kefus.delete_tip') }}
            </p>

            <div v-if="kefuStore.deleteError" class="bg-red-900/20 border border-red-500/30 rounded-lg p-3 mb-4">
              <p class="text-red-400 text-sm">{{ kefuStore.deleteError }}</p>
            </div>

            <div class="flex justify-end gap-3">
              <button
                class="btn-secondary text-sm"
                :disabled="kefuStore.deleteLoading"
                @click="closeDeleteModal"
              >
                {{ t('common.cancel') }}
              </button>
              <button
                class="bg-red-600 hover:bg-red-500 text-white px-4 py-2 rounded-lg text-sm transition-colors disabled:opacity-50"
                :disabled="kefuStore.deleteLoading"
                @click="confirmDelete"
              >
                <span v-if="kefuStore.deleteLoading">{{ t('kefus.deleting') }}</span>
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

