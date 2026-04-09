<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useStreamerStore, type StreamerSummary } from '../stores/streamers'
import { useI18n } from '../composables/useI18n'
import { avatarUrlFromSeed, refreshAvatars } from '../utils/avatars'

const streamerStore = useStreamerStore()
const router = useRouter()
const { t } = useI18n()

const searchInput = ref(streamerStore.search)
const currentPage = ref(1)
const pageSize = ref(streamerStore.limit || 20)
const pageSizeOptions = [10, 20, 50, 100]

// Delete confirmation state
const showDeleteModal = ref(false)
const streamerToDelete = ref<StreamerSummary | null>(null)
const deleteSuccessMessage = ref<string | null>(null)

// View mode: 'card' or 'table'
const STORAGE_KEY = 'streamers-view-mode'
const viewMode = ref<'card' | 'table'>(
  (localStorage.getItem(STORAGE_KEY) as 'card' | 'table') || 'card'
)

function setViewMode(mode: 'card' | 'table') {
  viewMode.value = mode
  localStorage.setItem(STORAGE_KEY, mode)
}

const totalPages = computed(() =>
  Math.max(1, Math.ceil(streamerStore.total / pageSize.value)),
)

const showingFrom = computed(() => {
  if (streamerStore.total === 0) return 0
  return (currentPage.value - 1) * pageSize.value + 1
})

const showingTo = computed(() => {
  return Math.min(streamerStore.total, currentPage.value * pageSize.value)
})

function formatDate(value: string | null | undefined) {
  if (!value) return '—'
  const parsed = new Date(value)
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toLocaleDateString()
  }
  return value
}

async function load(page: number = currentPage.value) {
  currentPage.value = page
  const offset = (currentPage.value - 1) * pageSize.value
  await streamerStore.fetchStreamers({
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

function openStreamer(id: string) {
  router.push({ name: 'streamer-detail', params: { id } })
}

function getAvatarUrl(streamer: { avatar_url: string | null; name: string }) {
  if (streamer.avatar_url) {
    return streamer.avatar_url
  }
  // Use the same avatar utility as conversations view
  return avatarUrlFromSeed(streamer.name)
}

function openDeleteModal(streamer: StreamerSummary, event: Event) {
  event.stopPropagation()
  streamerToDelete.value = streamer
  showDeleteModal.value = true
}

function closeDeleteModal() {
  showDeleteModal.value = false
  streamerToDelete.value = null
}

async function confirmDelete() {
  if (!streamerToDelete.value) return

  try {
    const deleted = await streamerStore.deleteStreamer(streamerToDelete.value.id)
    deleteSuccessMessage.value = t('streamers.delete_success', {
      name: deleted.streamer_name,
      conversations: deleted.conversations_removed,
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
  load(1)
})

watch(
  () => streamerStore.total,
  () => {
    const maxPage = Math.max(1, Math.ceil(streamerStore.total / pageSize.value))
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
          {{ t('streamers.title') }}
        </h2>
        <p class="text-sm text-wecom-muted mt-1">
          {{ t('streamers.subtitle') }}
        </p>
      </div>

      <div class="flex items-center gap-2">
        <!-- View toggle buttons -->
        <div class="flex items-center bg-wecom-surface border border-wecom-border rounded-lg p-0.5">
          <button
            class="px-3 py-1.5 text-sm rounded-md transition-colors"
            :class="viewMode === 'card' 
              ? 'bg-wecom-primary text-white' 
              : 'text-wecom-muted hover:text-wecom-text'"
            @click="setViewMode('card')"
          >
            <span class="mr-1">▦</span> {{ t('streamers.view_cards') }}
          </button>
          <button
            class="px-3 py-1.5 text-sm rounded-md transition-colors"
            :class="viewMode === 'table'
              ? 'bg-wecom-primary text-white'
              : 'text-wecom-muted hover:text-wecom-text'"
            @click="setViewMode('table')"
          >
            <span class="mr-1">☰</span> {{ t('streamers.view_table') }}
          </button>
        </div>

        <button
          class="btn-secondary text-sm"
          :disabled="streamerStore.listLoading"
          @click="load()"
        >
          <span :class="{ 'animate-spin': streamerStore.listLoading }">🔄</span>
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
            :placeholder="t('streamers.search_placeholder')"
            class="flex-1 px-3 py-2 rounded-lg bg-wecom-surface border border-wecom-border text-sm text-wecom-text focus:outline-none focus:ring-2 focus:ring-wecom-primary"
            @keyup.enter="handleSearch"
          />
          <button
            class="btn-primary text-sm"
            :disabled="streamerStore.listLoading"
            @click="handleSearch"
          >
            {{ t('common.search') }}
          </button>
          <button
            class="btn-secondary text-sm"
            :disabled="streamerStore.listLoading && streamerStore.streamers.length === 0"
            @click="clearSearch"
          >
            {{ t('common.clear') }}
          </button>
        </div>

        <div class="flex items-center gap-3 text-sm text-wecom-muted">
          <span class="text-wecom-text font-semibold">{{ streamerStore.total }}</span>
          {{ t('streamers.total_streamers') }}

          <label class="flex items-center gap-2">
            <span>{{ t('common.per_page') }}</span>
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
      v-if="streamerStore.listError"
      class="bg-red-900/20 border border-red-500/30 rounded-lg p-4 flex items-center gap-3"
    >
      <span class="text-red-400">⚠️</span>
      <div>
        <p class="text-red-400 font-medium">{{ t('streamers.load_failed') }}</p>
        <p class="text-red-400/70 text-sm">{{ streamerStore.listError }}</p>
      </div>
      <button class="btn-secondary text-sm ml-auto" @click="load()">
        {{ t('common.retry') }}
      </button>
    </div>

    <!-- Loading state -->
    <div
      v-else-if="streamerStore.listLoading && streamerStore.streamers.length === 0"
      class="bg-wecom-dark border border-wecom-border rounded-xl p-6 flex items-center justify-center text-wecom-muted"
    >
      {{ t('streamers.loading') }}
    </div>

    <!-- Empty state -->
    <div
      v-else-if="!streamerStore.listLoading && streamerStore.streamers.length === 0"
      class="bg-wecom-dark border border-wecom-border rounded-xl p-6 text-center text-wecom-muted"
    >
      {{ t('streamers.empty_state') }}
    </div>

    <!-- Card View -->
    <div
      v-else-if="viewMode === 'card'"
      class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
    >
      <div
        v-for="streamer in streamerStore.streamers"
        :key="streamer.id"
        class="bg-wecom-dark border border-wecom-border rounded-xl p-4 hover:border-wecom-primary/50 transition-all cursor-pointer group"
        @click="openStreamer(streamer.id)"
      >
        <!-- Header with avatar and name -->
        <div class="flex items-start gap-3 mb-3">
          <img
            :src="getAvatarUrl(streamer)"
            :alt="`Avatar for ${streamer.name}`"
            class="w-14 h-14 rounded-full border-2 border-wecom-border bg-wecom-surface object-cover shrink-0 group-hover:border-wecom-primary/50 transition-colors"
          />
          <div class="flex-1 min-w-0">
            <h3 class="text-lg font-semibold text-wecom-text truncate group-hover:text-wecom-primary transition-colors">
              {{ streamer.name }}
            </h3>
            <p class="text-xs text-wecom-muted">
              {{ streamer.conversation_count }} {{ t('streamers.conversation', { count: streamer.conversation_count }) }}
            </p>
            <div class="flex flex-wrap gap-1 mt-1">
              <span
                v-for="channel in streamer.channels.slice(0, 2)"
                :key="channel"
                class="text-xs px-1.5 py-0.5 rounded bg-wecom-surface text-wecom-muted"
              >
                {{ channel }}
              </span>
              <span
                v-if="streamer.channels.length > 2"
                class="text-xs px-1.5 py-0.5 rounded bg-wecom-surface text-wecom-muted"
              >
                +{{ streamer.channels.length - 2 }}
              </span>
            </div>
          </div>
          
          <!-- Status indicators and delete button -->
          <div class="flex flex-col items-end gap-1">
            <button
              class="text-red-400 hover:text-red-300 hover:bg-red-900/30 p-1 rounded transition-colors opacity-0 group-hover:opacity-100"
              :title="t('streamers.delete_streamer')"
              @click="openDeleteModal(streamer, $event)"
            >
              🗑️
            </button>
            <span
              v-if="streamer.has_persona"
              class="text-xs px-2 py-0.5 rounded-full bg-green-500/20 text-green-400"
              :title="t('streamers.persona_analyzed')"
            >
              🧠 {{ t('streamers.analyzed') }}
            </span>
            <span
              v-if="streamer.profile?.name"
              class="text-xs px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-400"
              :title="t('streamers.profile_completed')"
            >
              📋 {{ t('streamers.profile') }}
            </span>
          </div>
        </div>

        <!-- Stats -->
        <div class="grid grid-cols-3 gap-2 text-center border-t border-wecom-border pt-3">
          <div>
            <p class="text-lg font-semibold text-wecom-text">{{ streamer.total_messages }}</p>
            <p class="text-xs text-wecom-muted">{{ t('streamers.messages') }}</p>
          </div>
          <div>
            <p class="text-lg font-semibold text-wecom-text">{{ streamer.agents.length }}</p>
            <p class="text-xs text-wecom-muted">{{ t('streamers.agents') }}</p>
          </div>
          <div>
            <p class="text-sm text-wecom-text">{{ formatDate(streamer.last_seen) }}</p>
            <p class="text-xs text-wecom-muted">{{ t('streamers.last_seen') }}</p>
          </div>
        </div>

        <!-- Agents preview -->
        <div class="mt-3 pt-3 border-t border-wecom-border">
          <p class="text-xs text-wecom-muted mb-1">{{ t('streamers.agents') }}:</p>
          <div class="flex flex-wrap gap-1">
            <span
              v-for="agent in streamer.agents.slice(0, 3)"
              :key="agent"
              class="text-xs px-2 py-0.5 rounded bg-wecom-primary/10 text-wecom-primary"
            >
              {{ agent }}
            </span>
            <span
              v-if="streamer.agents.length > 3"
              class="text-xs px-2 py-0.5 rounded bg-wecom-surface text-wecom-muted"
            >
              +{{ streamer.agents.length - 3 }} {{ t('streamers.more') }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Table View -->
    <div
      v-else
      class="bg-wecom-dark border border-wecom-border rounded-xl overflow-hidden"
    >
      <table class="w-full">
        <thead class="bg-wecom-surface border-b border-wecom-border">
          <tr>
            <th class="px-4 py-3 text-left text-xs font-semibold text-wecom-muted uppercase tracking-wider">
              {{ t('streamers.table_streamer') }}
            </th>
            <th class="px-4 py-3 text-left text-xs font-semibold text-wecom-muted uppercase tracking-wider">
              {{ t('streamers.table_channels') }}
            </th>
            <th class="px-4 py-3 text-center text-xs font-semibold text-wecom-muted uppercase tracking-wider">
              {{ t('streamers.table_conversations') }}
            </th>
            <th class="px-4 py-3 text-center text-xs font-semibold text-wecom-muted uppercase tracking-wider">
              {{ t('streamers.table_messages') }}
            </th>
            <th class="px-4 py-3 text-center text-xs font-semibold text-wecom-muted uppercase tracking-wider">
              {{ t('streamers.table_agents') }}
            </th>
            <th class="px-4 py-3 text-center text-xs font-semibold text-wecom-muted uppercase tracking-wider">
              {{ t('streamers.table_status') }}
            </th>
            <th class="px-4 py-3 text-left text-xs font-semibold text-wecom-muted uppercase tracking-wider">
              {{ t('streamers.table_last_seen') }}
            </th>
            <th class="px-4 py-3 text-center text-xs font-semibold text-wecom-muted uppercase tracking-wider w-20">
              {{ t('common.actions') }}
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-wecom-border">
          <tr
            v-for="streamer in streamerStore.streamers"
            :key="streamer.id"
            class="hover:bg-wecom-surface/50 transition-colors cursor-pointer"
            @click="openStreamer(streamer.id)"
          >
            <td class="px-4 py-3">
              <div class="flex items-center gap-3">
                <img
                  :src="getAvatarUrl(streamer)"
                  :alt="`Avatar for ${streamer.name}`"
                  class="w-10 h-10 rounded-full border border-wecom-border bg-wecom-surface object-cover shrink-0"
                />
                <span class="text-sm font-medium text-wecom-text hover:text-wecom-primary transition-colors">
                  {{ streamer.name }}
                </span>
              </div>
            </td>
            <td class="px-4 py-3">
              <div class="flex flex-wrap gap-1">
                <span
                  v-for="channel in streamer.channels.slice(0, 2)"
                  :key="channel"
                  class="text-xs px-1.5 py-0.5 rounded bg-wecom-surface text-wecom-muted"
                >
                  {{ channel }}
                </span>
                <span
                  v-if="streamer.channels.length > 2"
                  class="text-xs px-1.5 py-0.5 rounded bg-wecom-surface text-wecom-muted"
                >
                  +{{ streamer.channels.length - 2 }}
                </span>
              </div>
            </td>
            <td class="px-4 py-3 text-center text-sm text-wecom-text">
              {{ streamer.conversation_count }}
            </td>
            <td class="px-4 py-3 text-center text-sm text-wecom-text font-medium">
              {{ streamer.total_messages }}
            </td>
            <td class="px-4 py-3 text-center">
              <div class="flex flex-wrap justify-center gap-1">
                <span
                  v-for="agent in streamer.agents.slice(0, 2)"
                  :key="agent"
                  class="text-xs px-1.5 py-0.5 rounded bg-wecom-primary/10 text-wecom-primary"
                >
                  {{ agent }}
                </span>
                <span
                  v-if="streamer.agents.length > 2"
                  class="text-xs px-1.5 py-0.5 rounded bg-wecom-surface text-wecom-muted"
                >
                  +{{ streamer.agents.length - 2 }}
                </span>
              </div>
            </td>
            <td class="px-4 py-3 text-center">
              <div class="flex justify-center gap-1">
                <span
                  v-if="streamer.has_persona"
                  class="text-xs px-2 py-0.5 rounded-full bg-green-500/20 text-green-400"
                  :title="t('streamers.persona_analyzed')"
                >
                  🧠
                </span>
                <span
                  v-if="streamer.profile?.name"
                  class="text-xs px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-400"
                  :title="t('streamers.profile_completed')"
                >
                  📋
                </span>
                <span
                  v-if="!streamer.has_persona && !streamer.profile?.name"
                  class="text-xs text-wecom-muted"
                >
                  —
                </span>
              </div>
            </td>
            <td class="px-4 py-3 text-sm text-wecom-muted">
              {{ formatDate(streamer.last_seen) }}
            </td>
            <td class="px-4 py-3 text-center">
              <button
                class="text-red-400 hover:text-red-300 hover:bg-red-900/30 p-1.5 rounded transition-colors"
                :title="t('streamers.delete_streamer')"
                @click="openDeleteModal(streamer, $event)"
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
      v-if="streamerStore.streamers.length > 0"
      class="flex flex-col md:flex-row items-center justify-between gap-3 px-4 py-3 bg-wecom-dark border border-wecom-border rounded-xl text-sm"
    >
      <div class="text-wecom-muted">
        {{ t('streamers.showing', { from: showingFrom, to: showingTo, total: streamerStore.total }) }}
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
          {{ t('common.page_of', { current: currentPage, total: totalPages }) }}
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
              {{ t('streamers.delete_title') }}
            </h3>
            <p class="text-wecom-muted text-sm mb-4">
              {{ t('streamers.delete_confirm', { name: streamerToDelete?.name }) }}
            </p>

            <div class="bg-red-900/20 border border-red-500/30 rounded-lg p-3 mb-4">
              <p class="text-red-400 text-sm font-medium mb-1">{{ t('streamers.delete_warning') }}</p>
              <ul class="text-red-400/80 text-xs space-y-0.5 ml-4 list-disc">
                <li>{{ streamerToDelete?.conversation_count || 0 }} {{ t('streamers.conversation', { count: streamerToDelete?.conversation_count || 0 }) }}</li>
                <li>{{ streamerToDelete?.total_messages || 0 }} {{ t('streamers.message', { count: streamerToDelete?.total_messages || 0 }) }}</li>
                <li v-if="streamerToDelete?.has_persona">{{ t('streamers.delete_persona') }}</li>
                <li v-if="streamerToDelete?.profile?.name">{{ t('streamers.delete_profile') }}</li>
              </ul>
            </div>

            <p class="text-wecom-muted text-xs mb-4">
              💡 {{ t('streamers.delete_tip') }}
            </p>

            <div v-if="streamerStore.deleteError" class="bg-red-900/20 border border-red-500/30 rounded-lg p-3 mb-4">
              <p class="text-red-400 text-sm">{{ streamerStore.deleteError }}</p>
            </div>

            <div class="flex justify-end gap-3">
              <button
                class="btn-secondary text-sm"
                :disabled="streamerStore.deleteLoading"
                @click="closeDeleteModal"
              >
                {{ t('common.cancel') }}
              </button>
              <button
                class="bg-red-600 hover:bg-red-500 text-white px-4 py-2 rounded-lg text-sm transition-colors disabled:opacity-50"
                :disabled="streamerStore.deleteLoading"
                @click="confirmDelete"
              >
                <span v-if="streamerStore.deleteLoading">{{ t('streamers.deleting') }}</span>
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
