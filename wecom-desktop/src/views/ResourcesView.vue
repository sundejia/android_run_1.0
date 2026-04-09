<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useResourcesStore, type ViewMode } from '../stores/resources'
import { useI18n } from '../composables/useI18n'
import {
  api,
  type ImageResource,
  type VoiceResource,
  type VideoResource,
  type ResourceFilters,
} from '../services/api'

const router = useRouter()
const route = useRoute()
const resourcesStore = useResourcesStore()
const { t } = useI18n()

// Active tab
type TabId = 'images' | 'voice' | 'videos'
const activeTab = ref<TabId>((route.query.tab as TabId) || 'images')

// Keep URL in sync with tab
watch(activeTab, (tab) => {
  router.replace({ query: { ...route.query, tab } })
})

// View mode
const viewMode = computed(() => resourcesStore.viewMode)
function setViewMode(mode: ViewMode) {
  resourcesStore.setViewMode(mode)
}

// Pagination
const pageSize = ref(20)
const pageSizeOptions = [10, 20, 50, 100]

// Filter state
const searchInput = ref('')
const selectedStreamer = ref('')
const selectedAgent = ref('')
const selectedDevice = ref('')
const dateFrom = ref('')
const dateTo = ref('')
const showFilters = ref(false)

// Sort state
const sortBy = ref('created_at')
const sortOrder = ref<'asc' | 'desc'>('desc')

// Delete modal state
const showDeleteModal = ref(false)
const itemToDelete = ref<ImageResource | VoiceResource | VideoResource | null>(null)
const deleteType = ref<'image' | 'voice' | 'video'>('image')
const deleteSuccessMessage = ref<string | null>(null)

// Transcribe success message
const transcribeSuccessMessage = ref<string | null>(null)
const transcribeErrorMessage = ref<string | null>(null)

// Image viewer modal state
const showImageViewer = ref(false)
const viewingImage = ref<ImageResource | null>(null)

// Video player modal state
const showVideoPlayer = ref(false)
const playingVideo = ref<VideoResource | null>(null)

// Voice player state
const showVoicePlayer = ref(false)
const playingVoice = ref<VoiceResource | null>(null)

// Tab definitions
const tabs = computed(() => [
  { id: 'images' as TabId, label: t('resources.tab_images'), icon: '🖼️' },
  { id: 'voice' as TabId, label: t('resources.tab_voice'), icon: '🎤' },
  { id: 'videos' as TabId, label: t('resources.tab_videos'), icon: '🎬' },
])

// Column definitions for each tab
const imageColumns = computed(() => [
  { key: 'file_name', label: t('resources.col_file') },
  { key: 'streamer_name', label: t('resources.col_streamer') },
  { key: 'kefu_name', label: t('resources.col_agent') },
  { key: 'device_serial', label: t('resources.col_device') },
  { key: 'file_size', label: t('resources.col_size') },
  { key: 'created_at', label: t('resources.col_created') },
  { key: '_actions', label: t('common.actions'), sortable: false },
])

const voiceColumns = computed(() => [
  { key: 'content', label: t('resources.col_transcription') },
  { key: 'streamer_name', label: t('resources.col_streamer') },
  { key: 'kefu_name', label: t('resources.col_agent') },
  { key: 'device_serial', label: t('resources.col_device') },
  { key: 'created_at', label: t('resources.col_created') },
  { key: '_actions', label: t('common.actions'), sortable: false },
])

const videoColumns = computed(() => [
  { key: 'content', label: t('resources.col_description') },
  { key: 'streamer_name', label: t('resources.col_streamer') },
  { key: 'kefu_name', label: t('resources.col_agent') },
  { key: 'device_serial', label: t('resources.col_device') },
  { key: 'created_at', label: t('resources.col_created') },
  { key: '_actions', label: t('common.actions'), sortable: false },
])

// Active tab computed values
const currentColumns = computed(() => {
  switch (activeTab.value) {
    case 'images':
      return imageColumns.value
    case 'voice':
      return voiceColumns.value
    case 'videos':
      return videoColumns.value
    default:
      return imageColumns.value
  }
})

const currentItems = computed(() => {
  switch (activeTab.value) {
    case 'images':
      return resourcesStore.images
    case 'voice':
      return resourcesStore.voiceMessages
    case 'videos':
      return resourcesStore.videoMessages
    default:
      return []
  }
})

const currentTotal = computed(() => {
  switch (activeTab.value) {
    case 'images':
      return resourcesStore.imagesTotalCount
    case 'voice':
      return resourcesStore.voiceTotalCount
    case 'videos':
      return resourcesStore.videoTotalCount
    default:
      return 0
  }
})

const currentPage = computed(() => {
  switch (activeTab.value) {
    case 'images':
      return resourcesStore.imagesPage
    case 'voice':
      return resourcesStore.voicePage
    case 'videos':
      return resourcesStore.videoPage
    default:
      return 1
  }
})

const totalPages = computed(() => {
  switch (activeTab.value) {
    case 'images':
      return resourcesStore.imagesTotalPages
    case 'voice':
      return resourcesStore.voiceTotalPages
    case 'videos':
      return resourcesStore.videoTotalPages
    default:
      return 1
  }
})

const isLoading = computed(() => {
  switch (activeTab.value) {
    case 'images':
      return resourcesStore.imagesLoading
    case 'voice':
      return resourcesStore.voiceLoading
    case 'videos':
      return resourcesStore.videoLoading
    default:
      return false
  }
})

const currentError = computed(() => {
  switch (activeTab.value) {
    case 'images':
      return resourcesStore.imagesError
    case 'voice':
      return resourcesStore.voiceError
    case 'videos':
      return resourcesStore.videoError
    default:
      return null
  }
})

const deleteLoading = computed(() => {
  switch (activeTab.value) {
    case 'images':
      return resourcesStore.imagesDeleteLoading
    case 'voice':
      return resourcesStore.voiceDeleteLoading
    case 'videos':
      return resourcesStore.videoDeleteLoading
    default:
      return false
  }
})

const showingFrom = computed(() => {
  if (currentTotal.value === 0) return 0
  return (currentPage.value - 1) * pageSize.value + 1
})

const showingTo = computed(() => {
  return Math.min(currentTotal.value, currentPage.value * pageSize.value)
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

// Format helpers
function formatDate(value: string | null | undefined) {
  if (!value) return '—'
  const parsed = new Date(value)
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toLocaleString()
  }
  return value
}

function formatFileSize(bytes: number | null) {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function buildFilters(): ResourceFilters {
  return {
    search: searchInput.value || undefined,
    streamer: selectedStreamer.value || undefined,
    kefuId: selectedAgent.value ? parseInt(selectedAgent.value, 10) : undefined,
    deviceSerial: selectedDevice.value || undefined,
    dateFrom: dateFrom.value || undefined,
    dateTo: dateTo.value || undefined,
    sortBy: sortBy.value || undefined,
    sortOrder: sortOrder.value || undefined,
  }
}

// Load data for current tab
async function loadData(page: number = 1) {
  const offset = (page - 1) * pageSize.value
  const filters = buildFilters()

  // Clear image errors when loading new data
  if (activeTab.value === 'images') {
    imageErrors.value.clear()
  }

  switch (activeTab.value) {
    case 'images':
      await resourcesStore.fetchImages({ limit: pageSize.value, offset, filters })
      break
    case 'voice':
      await resourcesStore.fetchVoiceMessages({ limit: pageSize.value, offset, filters })
      break
    case 'videos':
      await resourcesStore.fetchVideoMessages({ limit: pageSize.value, offset, filters })
      break
  }
}

function handleSearch() {
  loadData(1)
}

function clearSearch() {
  searchInput.value = ''
  loadData(1)
}

function clearFilters() {
  selectedStreamer.value = ''
  selectedAgent.value = ''
  selectedDevice.value = ''
  dateFrom.value = ''
  dateTo.value = ''
  loadData(1)
}

function applyFilters() {
  loadData(1)
}

function handlePageSizeChange() {
  loadData(1)
}

function nextPage() {
  if (currentPage.value < totalPages.value) {
    loadData(currentPage.value + 1)
  }
}

function prevPage() {
  if (currentPage.value > 1) {
    loadData(currentPage.value - 1)
  }
}

function toggleSort(column: string) {
  if (column === '_actions') return
  if (sortBy.value === column) {
    sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortBy.value = column
    sortOrder.value = 'desc'
  }
  loadData(1)
}

function getSortIcon(column: string): string {
  if (sortBy.value !== column) return '↕️'
  return sortOrder.value === 'asc' ? '↑' : '↓'
}

// Navigation to conversation
function navigateToConversation(customerId: number, messageId: number) {
  router.push({
    name: 'conversation-detail',
    params: { id: customerId },
    query: { highlightMessage: messageId.toString() },
  })
}

// Handle item click (table row or gallery item)
function handleItemClick(item: ImageResource | VoiceResource | VideoResource) {
  const customerId = item.customer_id
  const messageId = 'message_id' in item ? item.message_id : item.id
  navigateToConversation(customerId, messageId)
}

// Image viewer functions
function openImageViewer(image: ImageResource, event: Event) {
  event.stopPropagation()
  viewingImage.value = image
  showImageViewer.value = true
}

function closeImageViewer() {
  showImageViewer.value = false
  viewingImage.value = null
}

// Navigate to next/previous image in viewer
function viewNextImage() {
  if (!viewingImage.value) return
  const images = currentItems.value as ImageResource[]
  const currentIndex = images.findIndex((img) => img.id === viewingImage.value?.id)
  if (currentIndex < images.length - 1) {
    viewingImage.value = images[currentIndex + 1]
  }
}

function viewPrevImage() {
  if (!viewingImage.value) return
  const images = currentItems.value as ImageResource[]
  const currentIndex = images.findIndex((img) => img.id === viewingImage.value?.id)
  if (currentIndex > 0) {
    viewingImage.value = images[currentIndex - 1]
  }
}

// Keyboard navigation for image viewer, video player, and voice player
function handleMediaViewerKeydown(event: KeyboardEvent) {
  if (showImageViewer.value) {
    if (event.key === 'Escape') {
      closeImageViewer()
    } else if (event.key === 'ArrowRight') {
      viewNextImage()
    } else if (event.key === 'ArrowLeft') {
      viewPrevImage()
    }
  } else if (showVideoPlayer.value) {
    if (event.key === 'Escape') {
      closeVideoPlayer()
    } else if (event.key === 'ArrowRight') {
      viewNextVideo()
    } else if (event.key === 'ArrowLeft') {
      viewPrevVideo()
    }
  } else if (showVoicePlayer.value) {
    if (event.key === 'Escape') {
      closeVoicePlayer()
    } else if (event.key === 'ArrowRight') {
      viewNextVoice()
    } else if (event.key === 'ArrowLeft') {
      viewPrevVoice()
    }
  }
}

// Delete handlers
function openDeleteModal(
  item: ImageResource | VoiceResource | VideoResource,
  type: 'image' | 'voice' | 'video',
  event: Event
) {
  event.stopPropagation()
  itemToDelete.value = item
  deleteType.value = type
  showDeleteModal.value = true
}

function closeDeleteModal() {
  showDeleteModal.value = false
  itemToDelete.value = null
}

async function confirmDelete() {
  if (!itemToDelete.value) return

  try {
    let deletedName = ''
    switch (deleteType.value) {
      case 'image': {
        const img = itemToDelete.value as ImageResource
        const deleted = await resourcesStore.deleteImage(img.id)
        deletedName = deleted.file_name || `Image #${deleted.image_id}`
        break
      }
      case 'voice': {
        const voice = itemToDelete.value as VoiceResource
        await resourcesStore.deleteVoiceMessage(voice.id)
        deletedName = `Voice message from ${voice.streamer_name}`
        break
      }
      case 'video': {
        const video = itemToDelete.value as VideoResource
        await resourcesStore.deleteVideoMessage(video.id)
        deletedName = `Video message from ${video.streamer_name}`
        break
      }
    }
    deleteSuccessMessage.value = `Deleted "${deletedName}"`
    closeDeleteModal()

    // Auto-hide success message
    setTimeout(() => {
      deleteSuccessMessage.value = null
    }, 5000)
  } catch {
    // Error handled by store
  }
}

// Transcribe voice message
async function handleTranscribe(voice: VoiceResource, event: Event) {
  event.stopPropagation()

  // Clear any previous messages
  transcribeErrorMessage.value = null
  transcribeSuccessMessage.value = null

  try {
    const transcription = await resourcesStore.transcribeVoiceMessage(voice.id)
    transcribeSuccessMessage.value = `Transcribed: "${transcription.substring(0, 50)}${transcription.length > 50 ? '...' : ''}"`

    // Auto-hide success message
    setTimeout(() => {
      transcribeSuccessMessage.value = null
    }, 5000)
  } catch (error) {
    transcribeErrorMessage.value = error instanceof Error ? error.message : 'Transcription failed'

    // Auto-hide error message
    setTimeout(() => {
      transcribeErrorMessage.value = null
    }, 8000)
  }
}

// Get image URL from backend
function getImageUrl(image: ImageResource): string {
  return api.getImageUrl(image.id)
}

// Get video URL from backend
function getVideoUrl(video: VideoResource): string {
  if (!video.video_id) return ''
  return api.getVideoUrl(video.video_id)
}

// Video player functions
function openVideoPlayer(video: VideoResource, event: Event) {
  event.stopPropagation()
  if (!video.video_id) {
    // No video file available
    return
  }
  playingVideo.value = video
  showVideoPlayer.value = true
}

function closeVideoPlayer() {
  showVideoPlayer.value = false
  playingVideo.value = null
}

// Navigate to next/previous video in player
function viewNextVideo() {
  if (!playingVideo.value) return
  const videos = currentItems.value as VideoResource[]
  const currentIndex = videos.findIndex((v) => v.id === playingVideo.value?.id)
  if (currentIndex < videos.length - 1) {
    playingVideo.value = videos[currentIndex + 1]
  }
}

function viewPrevVideo() {
  if (!playingVideo.value) return
  const videos = currentItems.value as VideoResource[]
  const currentIndex = videos.findIndex((v) => v.id === playingVideo.value?.id)
  if (currentIndex > 0) {
    playingVideo.value = videos[currentIndex - 1]
  }
}

// Voice player functions
function playVoice(voice: VoiceResource) {
  if (!voice.voice_file_exists) return
  playingVoice.value = voice
  showVoicePlayer.value = true
}

function closeVoicePlayer() {
  showVoicePlayer.value = false
  playingVoice.value = null
}

function getVoiceUrl(voice: VoiceResource): string {
  if (!voice.voice_file_exists) return ''
  return api.getVoiceUrl(voice.id)
}

// Navigate to next/previous voice in player
function viewNextVoice() {
  if (!playingVoice.value) return
  const voices = currentItems.value as VoiceResource[]
  const currentIndex = voices.findIndex((v) => v.id === playingVoice.value?.id)
  if (currentIndex < voices.length - 1) {
    playingVoice.value = voices[currentIndex + 1]
  }
}

function viewPrevVoice() {
  if (!playingVoice.value) return
  const voices = currentItems.value as VoiceResource[]
  const currentIndex = voices.findIndex((v) => v.id === playingVoice.value?.id)
  if (currentIndex > 0) {
    playingVoice.value = voices[currentIndex - 1]
  }
}

// Track image load errors for fallback
const imageErrors = ref<Set<number>>(new Set())

// Watch for tab changes and reload data
watch(activeTab, () => {
  loadData(1)
})

// Initialize
onMounted(() => {
  resourcesStore.fetchFilterOptions()
  loadData(1)
  // Add keyboard listener for media viewers
  window.addEventListener('keydown', handleMediaViewerKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleMediaViewerKeydown)
})
</script>

<template>
  <div class="p-6 space-y-6 animate-fade-in">
    <!-- Header -->
    <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
      <div>
        <h2 class="text-2xl font-display font-bold text-wecom-text">
          {{ t('resources.title') }}
        </h2>
        <p class="text-sm text-wecom-muted mt-1">
          {{ t('resources.subtitle') }}
        </p>
        <p v-if="resourcesStore.lastFetchedPath" class="text-xs text-wecom-muted mt-2">
          {{ t('kefus.db_label') }}: {{ resourcesStore.lastFetchedPath }}
        </p>
      </div>

      <div class="flex items-center gap-2">
        <!-- View mode toggle -->
        <div
          class="flex items-center gap-1 bg-wecom-surface border border-wecom-border rounded-lg p-1"
        >
          <button
            class="px-3 py-1 rounded text-sm transition-colors"
            :class="
              viewMode === 'table'
                ? 'bg-wecom-primary/20 text-wecom-primary'
                : 'text-wecom-muted hover:text-wecom-text'
            "
            :title="t('resources.view_table')"
            @click="setViewMode('table')"
          >
            📋 {{ t('resources.view_table_label') }}
          </button>
          <button
            class="px-3 py-1 rounded text-sm transition-colors"
            :class="
              viewMode === 'gallery'
                ? 'bg-wecom-primary/20 text-wecom-primary'
                : 'text-wecom-muted hover:text-wecom-text'
            "
            :title="t('resources.view_gallery')"
            @click="setViewMode('gallery')"
          >
            🖼️ {{ t('resources.view_gallery_label') }}
          </button>
        </div>
        <button class="btn-secondary text-sm" :disabled="isLoading" @click="loadData()">
          <span :class="{ 'animate-spin': isLoading }">🔄</span>
          {{ t('common.refresh') }}
        </button>
      </div>
    </div>

    <!-- Tabs -->
    <div class="flex border-b border-wecom-border">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        class="px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors flex items-center gap-2"
        :class="[
          activeTab === tab.id
            ? 'text-wecom-primary border-b-2 border-wecom-primary bg-wecom-primary/5'
            : 'text-wecom-muted hover:text-wecom-text hover:bg-wecom-surface',
        ]"
        @click="activeTab = tab.id"
      >
        <span>{{ tab.icon }}</span>
        <span>{{ tab.label }}</span>
        <span
          v-if="resourcesStore.resourceCounts[tab.id as keyof typeof resourcesStore.resourceCounts]"
          class="px-1.5 py-0.5 text-xs rounded-full bg-wecom-surface"
        >
          {{ resourcesStore.resourceCounts[tab.id as keyof typeof resourcesStore.resourceCounts] }}
        </span>
      </button>
    </div>

    <!-- Search and Filters -->
    <div class="bg-wecom-dark border border-wecom-border rounded-xl p-4 space-y-4">
      <!-- Search Row -->
      <div class="flex flex-col lg:flex-row gap-3 lg:items-center lg:justify-between">
        <div class="flex flex-1 items-center gap-2">
          <input
            v-model="searchInput"
            type="text"
            :placeholder="
              activeTab === 'images'
                ? t('resources.search_images_placeholder')
                : t('resources.search_content_placeholder')
            "
            class="flex-1 px-3 py-2 rounded-lg bg-wecom-surface border border-wecom-border text-sm text-wecom-text focus:outline-none focus:ring-2 focus:ring-wecom-primary"
            @keyup.enter="handleSearch"
          />
          <button class="btn-primary text-sm" :disabled="isLoading" @click="handleSearch">
            {{ t('common.search') }}
          </button>
          <button
            class="btn-secondary text-sm"
            :disabled="isLoading && currentItems.length === 0"
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
            {{ t('customers.filters') }}
            <span
              v-if="activeFiltersCount > 0"
              class="bg-wecom-primary text-white text-xs px-1.5 py-0.5 rounded-full"
            >
              {{ activeFiltersCount }}
            </span>
          </button>
        </div>

        <div class="flex items-center gap-3 text-sm text-wecom-muted">
          <span class="text-wecom-text font-semibold">{{ currentTotal }}</span>
          {{ t('resources.total_count', { type: activeTab }) }}

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
              t('customers.filter_streamer')
            }}</label>
            <select
              v-model="selectedStreamer"
              class="w-full px-3 py-2 rounded-lg bg-wecom-surface border border-wecom-border text-sm text-wecom-text focus:outline-none focus:ring-2 focus:ring-wecom-primary"
            >
              <option value="">{{ t('customers.filter_all_streamers') }}</option>
              <option
                v-for="streamer in resourcesStore.filterOptions.streamers"
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
              t('customers.filter_agent')
            }}</label>
            <select
              v-model="selectedAgent"
              class="w-full px-3 py-2 rounded-lg bg-wecom-surface border border-wecom-border text-sm text-wecom-text focus:outline-none focus:ring-2 focus:ring-wecom-primary"
            >
              <option value="">{{ t('customers.filter_all_agents') }}</option>
              <option
                v-for="agent in resourcesStore.filterOptions.agents"
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
              t('customers.filter_device')
            }}</label>
            <select
              v-model="selectedDevice"
              class="w-full px-3 py-2 rounded-lg bg-wecom-surface border border-wecom-border text-sm text-wecom-text focus:outline-none focus:ring-2 focus:ring-wecom-primary"
            >
              <option value="">{{ t('customers.filter_all_devices') }}</option>
              <option
                v-for="device in resourcesStore.filterOptions.devices"
                :key="device.serial"
                :value="device.serial"
              >
                {{ device.serial }}{{ device.model ? ` (${device.model})` : '' }}
              </option>
            </select>
          </div>

          <div></div>
        </div>

        <!-- Date Range Row -->
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <!-- Date From -->
          <div class="space-y-1">
            <label class="text-xs text-wecom-muted font-medium">{{
              t('customers.filter_from_date')
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
              t('customers.filter_to_date')
            }}</label>
            <input
              v-model="dateTo"
              type="date"
              class="w-full px-3 py-2 rounded-lg bg-wecom-surface border border-wecom-border text-sm text-wecom-text focus:outline-none focus:ring-2 focus:ring-wecom-primary"
            />
          </div>

          <!-- Apply/Clear Buttons -->
          <div class="flex items-end gap-2 lg:col-span-2">
            <button class="btn-primary text-sm px-4" :disabled="isLoading" @click="applyFilters">
              {{ t('customers.filter_apply') }}
            </button>
            <button
              class="btn-secondary text-sm px-4"
              :disabled="isLoading && activeFiltersCount === 0"
              @click="clearFilters"
            >
              {{ t('customers.filter_clear') }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Error state -->
    <div
      v-if="currentError"
      class="bg-red-900/20 border border-red-500/30 rounded-lg p-4 flex items-center gap-3"
    >
      <span class="text-red-400">⚠️</span>
      <div>
        <p class="text-red-400 font-medium">
          {{ t('resources.load_failed', { type: activeTab }) }}
        </p>
        <p class="text-red-400/70 text-sm">{{ currentError }}</p>
      </div>
      <button class="btn-secondary text-sm ml-auto" @click="loadData()">
        {{ t('common.retry') }}
      </button>
    </div>

    <!-- Loading state -->
    <div
      v-else-if="isLoading && currentItems.length === 0"
      class="bg-wecom-dark border border-wecom-border rounded-xl p-6 flex items-center justify-center text-wecom-muted"
    >
      {{ t('resources.loading', { type: activeTab }) }}
    </div>

    <!-- Empty state -->
    <div
      v-else-if="!isLoading && currentItems.length === 0"
      class="bg-wecom-dark border border-wecom-border rounded-xl p-6 text-center text-wecom-muted"
    >
      <div class="text-5xl mb-4">
        {{ activeTab === 'images' ? '🖼️' : activeTab === 'voice' ? '🎤' : '🎬' }}
      </div>
      <p>{{ t('resources.empty_state', { type: activeTab }) }}</p>
    </div>

    <!-- Table View -->
    <div
      v-else-if="viewMode === 'table'"
      class="bg-wecom-dark border border-wecom-border rounded-xl overflow-hidden"
    >
      <div class="overflow-auto max-h-[540px]">
        <table class="min-w-full text-sm">
          <thead class="bg-wecom-surface border-b border-wecom-border text-wecom-muted">
            <tr>
              <th
                v-for="col in currentColumns"
                :key="col.key"
                class="text-left px-4 py-2 select-none transition-colors"
                :class="col.key !== '_actions' ? 'cursor-pointer hover:bg-wecom-dark/50' : ''"
                @click="toggleSort(col.key)"
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
            <!-- Images table rows -->
            <template v-if="activeTab === 'images'">
              <tr
                v-for="image in currentItems as ImageResource[]"
                :key="image.id"
                class="border-b border-wecom-border hover:bg-wecom-surface/60 transition-colors cursor-pointer"
                @click="handleItemClick(image)"
              >
                <td class="px-4 py-2">
                  <div class="flex items-center gap-2">
                    <div
                      class="w-10 h-10 rounded bg-wecom-surface flex items-center justify-center text-xl overflow-hidden shrink-0 cursor-zoom-in hover:ring-2 hover:ring-wecom-primary transition-all"
                      title="Click to view full image"
                      @click="openImageViewer(image, $event)"
                    >
                      <img
                        v-if="!imageErrors.has(image.id)"
                        :src="getImageUrl(image)"
                        :alt="image.file_name || 'Image'"
                        class="w-full h-full object-cover"
                        @error="imageErrors.add(image.id)"
                      />
                      <span v-else>🖼️</span>
                    </div>
                    <div>
                      <p class="text-wecom-text font-medium truncate max-w-[200px]">
                        {{ image.file_name || 'Unnamed' }}
                      </p>
                      <p class="text-xs text-wecom-muted">
                        {{ image.width || '?' }}×{{ image.height || '?' }}
                      </p>
                    </div>
                  </div>
                </td>
                <td class="px-4 py-2 text-wecom-text">
                  <p class="font-medium">{{ image.streamer_name }}</p>
                  <p class="text-xs text-wecom-muted">{{ image.channel || '—' }}</p>
                </td>
                <td class="px-4 py-2 text-wecom-text">
                  <p class="font-medium">{{ image.kefu_name }}</p>
                  <p class="text-xs text-wecom-muted">{{ image.kefu_department || 'No dept' }}</p>
                </td>
                <td class="px-4 py-2 text-wecom-muted">
                  {{ image.device_serial }}
                </td>
                <td class="px-4 py-2 text-wecom-muted">
                  {{ formatFileSize(image.file_size) }}
                </td>
                <td class="px-4 py-2 text-wecom-muted">
                  {{ formatDate(image.created_at) }}
                </td>
                <td class="px-4 py-2">
                  <button
                    class="text-red-400 hover:text-red-300 hover:bg-red-900/30 p-1.5 rounded transition-colors"
                    title="Delete image"
                    @click="openDeleteModal(image, 'image', $event)"
                  >
                    🗑️
                  </button>
                </td>
              </tr>
            </template>

            <!-- Voice table rows -->
            <template v-else-if="activeTab === 'voice'">
              <tr
                v-for="voice in currentItems as VoiceResource[]"
                :key="voice.id"
                class="border-b border-wecom-border hover:bg-wecom-surface/60 transition-colors cursor-pointer"
                @click="handleItemClick(voice)"
              >
                <td class="px-4 py-2">
                  <div class="flex items-center gap-2">
                    <!-- Voice play button -->
                    <div
                      class="w-10 h-10 rounded bg-wecom-surface flex items-center justify-center overflow-hidden shrink-0 relative group/thumb"
                      :class="
                        voice.voice_file_exists
                          ? 'cursor-pointer hover:ring-2 hover:ring-wecom-primary'
                          : 'opacity-50'
                      "
                      :title="voice.voice_file_exists ? 'Click to play' : 'No audio file'"
                      @click.stop="voice.voice_file_exists ? playVoice(voice) : null"
                    >
                      <span class="text-xl opacity-60">🎤</span>
                      <!-- Play icon overlay -->
                      <div
                        v-if="voice.voice_file_exists"
                        class="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 group-hover/thumb:opacity-100 transition-opacity"
                      >
                        <svg class="w-5 h-5 text-white" fill="currentColor" viewBox="0 0 24 24">
                          <path d="M8 5v14l11-7z" />
                        </svg>
                      </div>
                    </div>
                    <div>
                      <p class="text-wecom-text truncate max-w-[250px]">
                        {{ voice.content || '(No transcription)' }}
                      </p>
                      <p v-if="voice.voice_duration" class="text-xs text-wecom-muted">
                        Duration: {{ voice.voice_duration }}
                      </p>
                    </div>
                  </div>
                </td>
                <td class="px-4 py-2 text-wecom-text">
                  <p class="font-medium">{{ voice.streamer_name }}</p>
                  <p class="text-xs text-wecom-muted">{{ voice.channel || '—' }}</p>
                </td>
                <td class="px-4 py-2 text-wecom-text">
                  <p class="font-medium">{{ voice.kefu_name }}</p>
                  <p class="text-xs text-wecom-muted">{{ voice.kefu_department || 'No dept' }}</p>
                </td>
                <td class="px-4 py-2 text-wecom-muted">
                  {{ voice.device_serial }}
                </td>
                <td class="px-4 py-2 text-wecom-muted">
                  {{ formatDate(voice.created_at) }}
                </td>
                <td class="px-4 py-2">
                  <div class="flex items-center gap-1">
                    <button
                      v-if="
                        voice.voice_file_exists &&
                        (!voice.content || voice.content === '[Voice Message]')
                      "
                      class="text-wecom-primary hover:text-wecom-primary/80 hover:bg-wecom-primary/10 p-1.5 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      :title="
                        resourcesStore.isVoiceTranscribing(voice.id)
                          ? 'Transcribing...'
                          : 'Transcribe voice to text'
                      "
                      :disabled="resourcesStore.isVoiceTranscribing(voice.id)"
                      @click="handleTranscribe(voice, $event)"
                    >
                      <span v-if="resourcesStore.isVoiceTranscribing(voice.id)" class="animate-spin"
                        >⏳</span
                      >
                      <span v-else>✍️</span>
                    </button>
                    <button
                      class="text-red-400 hover:text-red-300 hover:bg-red-900/30 p-1.5 rounded transition-colors"
                      title="Delete voice message"
                      @click="openDeleteModal(voice, 'voice', $event)"
                    >
                      🗑️
                    </button>
                  </div>
                </td>
              </tr>
            </template>

            <!-- Video table rows -->
            <template v-else-if="activeTab === 'videos'">
              <tr
                v-for="video in currentItems as VideoResource[]"
                :key="video.id"
                class="border-b border-wecom-border hover:bg-wecom-surface/60 transition-colors cursor-pointer"
                @click="handleItemClick(video)"
              >
                <td class="px-4 py-2">
                  <div class="flex items-center gap-2">
                    <!-- Video thumbnail / play button -->
                    <div
                      class="w-10 h-10 rounded bg-wecom-surface flex items-center justify-center overflow-hidden shrink-0 relative group/thumb"
                      :class="
                        video.video_id
                          ? 'cursor-pointer hover:ring-2 hover:ring-wecom-primary'
                          : 'opacity-50'
                      "
                      :title="video.video_id ? 'Click to play' : 'No video file'"
                      @click.stop="video.video_id ? openVideoPlayer(video, $event) : null"
                    >
                      <span class="text-xl opacity-60">🎬</span>
                      <!-- Play icon overlay -->
                      <div
                        v-if="video.video_id"
                        class="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 group-hover/thumb:opacity-100 transition-opacity"
                      >
                        <svg class="w-5 h-5 text-white" fill="currentColor" viewBox="0 0 24 24">
                          <path d="M8 5v14l11-7z" />
                        </svg>
                      </div>
                    </div>
                    <div>
                      <p class="text-wecom-text truncate max-w-[250px]">
                        {{ video.content || '(No description)' }}
                      </p>
                      <p v-if="video.video_duration" class="text-xs text-wecom-muted">
                        Duration: {{ video.video_duration }}
                      </p>
                    </div>
                  </div>
                </td>
                <td class="px-4 py-2 text-wecom-text">
                  <p class="font-medium">{{ video.streamer_name }}</p>
                  <p class="text-xs text-wecom-muted">{{ video.channel || '—' }}</p>
                </td>
                <td class="px-4 py-2 text-wecom-text">
                  <p class="font-medium">{{ video.kefu_name }}</p>
                  <p class="text-xs text-wecom-muted">{{ video.kefu_department || 'No dept' }}</p>
                </td>
                <td class="px-4 py-2 text-wecom-muted">
                  {{ video.device_serial }}
                </td>
                <td class="px-4 py-2 text-wecom-muted">
                  {{ formatDate(video.created_at) }}
                </td>
                <td class="px-4 py-2">
                  <div class="flex items-center gap-1">
                    <button
                      v-if="video.video_id"
                      class="text-wecom-primary hover:text-wecom-primary/80 hover:bg-wecom-primary/10 p-1.5 rounded transition-colors"
                      title="Play video"
                      @click="openVideoPlayer(video, $event)"
                    >
                      ▶️
                    </button>
                    <button
                      class="text-red-400 hover:text-red-300 hover:bg-red-900/30 p-1.5 rounded transition-colors"
                      title="Delete video message"
                      @click="openDeleteModal(video, 'video', $event)"
                    >
                      🗑️
                    </button>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div
        class="flex flex-col md:flex-row items-center justify-between gap-3 px-4 py-3 bg-wecom-surface border-t border-wecom-border text-sm"
      >
        <div class="text-wecom-muted">
          Showing {{ showingFrom }}–{{ showingTo }} of {{ currentTotal }}
        </div>
        <div class="flex items-center gap-2">
          <button class="btn-secondary text-xs" :disabled="currentPage === 1" @click="prevPage">
            Prev
          </button>
          <span class="text-wecom-text text-sm"> Page {{ currentPage }} / {{ totalPages }} </span>
          <button
            class="btn-secondary text-xs"
            :disabled="currentPage >= totalPages"
            @click="nextPage"
          >
            Next
          </button>
        </div>
      </div>
    </div>

    <!-- Gallery View -->
    <div v-else-if="viewMode === 'gallery'" class="space-y-4">
      <!-- Images Gallery -->
      <template v-if="activeTab === 'images'">
        <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
          <div
            v-for="image in currentItems as ImageResource[]"
            :key="image.id"
            class="bg-wecom-dark border border-wecom-border rounded-xl overflow-hidden hover:border-wecom-primary/50 transition-colors group"
          >
            <div
              class="aspect-square bg-wecom-surface flex items-center justify-center relative overflow-hidden cursor-zoom-in"
              title="Click to view full image"
              @click="openImageViewer(image, $event)"
            >
              <img
                v-if="!imageErrors.has(image.id)"
                :src="getImageUrl(image)"
                :alt="image.file_name || 'Image'"
                class="w-full h-full object-cover hover:scale-105 transition-transform duration-200"
                @error="imageErrors.add(image.id)"
              />
              <span v-else class="text-4xl">🖼️</span>
              <button
                class="absolute top-2 right-2 p-1.5 rounded bg-red-900/80 text-red-400 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-900"
                title="Delete"
                @click="openDeleteModal(image, 'image', $event)"
              >
                🗑️
              </button>
            </div>
            <div
              class="p-3 space-y-1 cursor-pointer hover:bg-wecom-surface/50 transition-colors"
              title="Click to view in conversation"
              @click="handleItemClick(image)"
            >
              <p class="text-wecom-text font-medium truncate text-sm">
                {{ image.file_name || 'Unnamed' }}
              </p>
              <p class="text-wecom-muted text-xs">
                {{ image.streamer_name }}
              </p>
              <p class="text-wecom-muted text-xs">
                {{ formatDate(image.created_at) }}
              </p>
            </div>
          </div>
        </div>
      </template>

      <!-- Voice Gallery -->
      <template v-else-if="activeTab === 'voice'">
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <div
            v-for="voice in currentItems as VoiceResource[]"
            :key="voice.id"
            class="bg-wecom-dark border border-wecom-border rounded-xl p-4 hover:border-wecom-primary/50 transition-colors cursor-pointer group"
            @click="handleItemClick(voice)"
          >
            <div class="flex items-start justify-between gap-3">
              <div class="flex items-center gap-3">
                <!-- Voice icon with play button -->
                <div
                  class="w-12 h-12 rounded-full bg-wecom-surface flex items-center justify-center text-2xl shrink-0 relative"
                  :class="
                    voice.voice_file_exists
                      ? 'cursor-pointer hover:bg-wecom-primary/20'
                      : 'opacity-50'
                  "
                  :title="voice.voice_file_exists ? 'Click to play' : 'No audio file'"
                  @click.stop="voice.voice_file_exists ? playVoice(voice) : null"
                >
                  🎤
                  <!-- Play overlay -->
                  <div
                    v-if="voice.voice_file_exists"
                    class="absolute inset-0 rounded-full flex items-center justify-center bg-black/40 opacity-0 hover:opacity-100 transition-opacity"
                  >
                    <svg class="w-5 h-5 text-white" fill="currentColor" viewBox="0 0 24 24">
                      <path d="M8 5v14l11-7z" />
                    </svg>
                  </div>
                </div>
                <div class="min-w-0">
                  <p class="text-wecom-text font-medium">{{ voice.streamer_name }}</p>
                  <p class="text-wecom-muted text-xs">{{ voice.channel || '—' }}</p>
                  <p v-if="voice.voice_duration" class="text-wecom-muted text-xs">
                    Duration: {{ voice.voice_duration }}
                  </p>
                </div>
              </div>
              <div class="flex items-center gap-1 shrink-0">
                <button
                  v-if="
                    voice.voice_file_exists &&
                    (!voice.content || voice.content === '[Voice Message]')
                  "
                  class="p-1.5 rounded bg-wecom-primary/80 text-white opacity-0 group-hover:opacity-100 transition-opacity hover:bg-wecom-primary disabled:opacity-50"
                  :title="
                    resourcesStore.isVoiceTranscribing(voice.id) ? 'Transcribing...' : 'Transcribe'
                  "
                  :disabled="resourcesStore.isVoiceTranscribing(voice.id)"
                  @click="handleTranscribe(voice, $event)"
                >
                  <span v-if="resourcesStore.isVoiceTranscribing(voice.id)" class="animate-spin"
                    >⏳</span
                  >
                  <span v-else>✍️</span>
                </button>
                <button
                  class="p-1.5 rounded bg-red-900/80 text-red-400 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-900"
                  title="Delete"
                  @click="openDeleteModal(voice, 'voice', $event)"
                >
                  🗑️
                </button>
              </div>
            </div>
            <p class="text-wecom-muted text-sm mt-3 line-clamp-2">
              {{ voice.content || '(No transcription available)' }}
            </p>
            <div
              class="flex items-center justify-between mt-3 pt-3 border-t border-wecom-border text-xs text-wecom-muted"
            >
              <span>{{ voice.kefu_name }}</span>
              <span>{{ formatDate(voice.created_at) }}</span>
            </div>
          </div>
        </div>
      </template>

      <!-- Video Gallery -->
      <template v-else-if="activeTab === 'videos'">
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <div
            v-for="video in currentItems as VideoResource[]"
            :key="video.id"
            class="bg-wecom-dark border border-wecom-border rounded-xl overflow-hidden hover:border-wecom-primary/50 transition-colors group"
          >
            <!-- Video thumbnail area with play button -->
            <div
              class="aspect-video bg-wecom-surface flex items-center justify-center relative overflow-hidden cursor-pointer"
              :class="video.video_id ? 'hover:bg-wecom-dark/50' : 'opacity-60'"
              :title="video.video_id ? 'Click to play video' : 'Video file not available'"
              @click="video.video_id ? openVideoPlayer(video, $event) : null"
            >
              <!-- Video thumbnail image -->
              <img
                v-if="video.video_id"
                :src="api.getVideoThumbnailUrl(video.video_id)"
                :alt="video.content || 'Video thumbnail'"
                class="absolute inset-0 w-full h-full object-cover"
                @error="($event.target as HTMLImageElement).style.display = 'none'"
              />

              <!-- Fallback gradient background (shows if no thumbnail or on error) -->
              <div
                class="absolute inset-0 bg-gradient-to-br from-wecom-dark/20 to-wecom-darker/60 -z-10"
              ></div>

              <!-- Fallback video icon (shows if no video_id) -->
              <div v-if="!video.video_id" class="relative z-10 flex flex-col items-center gap-2">
                <span class="text-5xl opacity-40">🎬</span>
                <span class="text-xs text-wecom-muted bg-wecom-dark/80 px-2 py-1 rounded">
                  No video file
                </span>
              </div>

              <!-- Play button overlay -->
              <div
                v-if="video.video_id"
                class="absolute inset-0 flex items-center justify-center bg-black/20 group-hover:bg-black/40 transition-colors"
              >
                <div
                  class="w-16 h-16 rounded-full bg-wecom-primary/90 flex items-center justify-center shadow-lg transform transition-transform group-hover:scale-110"
                >
                  <svg class="w-8 h-8 text-white ml-1" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M8 5v14l11-7z" />
                  </svg>
                </div>
              </div>

              <!-- Duration badge -->
              <div
                v-if="video.video_duration"
                class="absolute bottom-2 right-2 px-2 py-0.5 bg-black/70 text-white text-xs rounded font-mono z-10"
              >
                {{ video.video_duration }}
              </div>

              <!-- Delete button -->
              <button
                class="absolute top-2 right-2 p-1.5 rounded bg-red-900/80 text-red-400 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-900 z-20"
                title="Delete"
                @click="openDeleteModal(video, 'video', $event)"
              >
                🗑️
              </button>
            </div>

            <!-- Video info -->
            <div
              class="p-3 space-y-1 cursor-pointer hover:bg-wecom-surface/50 transition-colors"
              title="Click to view in conversation"
              @click="handleItemClick(video)"
            >
              <p class="text-wecom-text font-medium text-sm">
                {{ video.streamer_name }}
              </p>
              <p class="text-wecom-muted text-xs truncate">
                {{ video.content || '(No description)' }}
              </p>
              <div class="flex items-center justify-between text-wecom-muted text-xs">
                <span>{{ video.kefu_name }}</span>
                <span>{{ formatDate(video.created_at) }}</span>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- Gallery Pagination -->
      <div
        class="flex flex-col md:flex-row items-center justify-between gap-3 px-4 py-3 bg-wecom-dark border border-wecom-border rounded-xl text-sm"
      >
        <div class="text-wecom-muted">
          Showing {{ showingFrom }}–{{ showingTo }} of {{ currentTotal }}
        </div>
        <div class="flex items-center gap-2">
          <button class="btn-secondary text-xs" :disabled="currentPage === 1" @click="prevPage">
            Prev
          </button>
          <span class="text-wecom-text text-sm"> Page {{ currentPage }} / {{ totalPages }} </span>
          <button
            class="btn-secondary text-xs"
            :disabled="currentPage >= totalPages"
            @click="nextPage"
          >
            Next
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

    <!-- Transcribe Success Message -->
    <Transition name="fade">
      <div
        v-if="transcribeSuccessMessage"
        class="fixed bottom-4 right-4 bg-blue-900/90 border border-blue-500/30 rounded-lg px-4 py-3 flex items-center gap-3 shadow-lg z-50 max-w-md"
      >
        <span class="text-blue-400">✍️</span>
        <p class="text-blue-300 text-sm">{{ transcribeSuccessMessage }}</p>
        <button
          class="text-blue-400 hover:text-blue-300 ml-2"
          @click="transcribeSuccessMessage = null"
        >
          ✕
        </button>
      </div>
    </Transition>

    <!-- Transcribe Error Message -->
    <Transition name="fade">
      <div
        v-if="transcribeErrorMessage"
        class="fixed bottom-4 right-4 bg-red-900/90 border border-red-500/30 rounded-lg px-4 py-3 flex items-center gap-3 shadow-lg z-50 max-w-md"
      >
        <span class="text-red-400">⚠️</span>
        <p class="text-red-300 text-sm">{{ transcribeErrorMessage }}</p>
        <button class="text-red-400 hover:text-red-300 ml-2" @click="transcribeErrorMessage = null">
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
              {{ t('resources.delete_title', { type: t(`resources.type_${deleteType}`) }) }}
            </h3>
            <p class="text-wecom-muted text-sm mb-4">
              {{
                t('resources.delete_confirm', {
                  type: t(`resources.type_${deleteType}`),
                  streamer: (itemToDelete as any)?.streamer_name,
                })
              }}
            </p>

            <div class="bg-red-900/20 border border-red-500/30 rounded-lg p-3 mb-4">
              <p class="text-red-400 text-sm font-medium mb-1">
                {{ t('resources.delete_warning_title') }}
              </p>
              <ul class="text-red-400/80 text-xs space-y-0.5 ml-4 list-disc">
                <li>{{ t('resources.delete_warning_record') }}</li>
                <li v-if="deleteType !== 'image'">{{ t('resources.delete_warning_content') }}</li>
              </ul>
            </div>

            <p class="text-wecom-muted text-xs mb-4">
              {{ t('customers.delete_tip') }}
            </p>

            <div class="flex justify-end gap-3">
              <button
                class="btn-secondary text-sm"
                :disabled="deleteLoading"
                @click="closeDeleteModal"
              >
                {{ t('common.cancel') }}
              </button>
              <button
                class="bg-red-600 hover:bg-red-500 text-white px-4 py-2 rounded-lg text-sm transition-colors disabled:opacity-50"
                :disabled="deleteLoading"
                @click="confirmDelete"
              >
                <span v-if="deleteLoading">{{ t('kefus.deleting') }}</span>
                <span v-else>{{ t('common.delete') }}</span>
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Image Viewer Modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showImageViewer && viewingImage"
          class="fixed inset-0 bg-black/90 flex items-center justify-center z-50"
          @click.self="closeImageViewer"
        >
          <!-- Close button -->
          <button
            class="absolute top-4 right-4 p-2 rounded-full bg-white/10 text-white hover:bg-white/20 transition-colors z-10"
            title="Close (Esc)"
            @click="closeImageViewer"
          >
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>

          <!-- Previous button -->
          <button
            class="absolute left-4 top-1/2 -translate-y-1/2 p-3 rounded-full bg-white/10 text-white hover:bg-white/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            :disabled="
              (currentItems as ImageResource[]).findIndex((img) => img.id === viewingImage?.id) ===
              0
            "
            title="Previous (←)"
            @click="viewPrevImage"
          >
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M15 19l-7-7 7-7"
              />
            </svg>
          </button>

          <!-- Next button -->
          <button
            class="absolute right-4 top-1/2 -translate-y-1/2 p-3 rounded-full bg-white/10 text-white hover:bg-white/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            :disabled="
              (currentItems as ImageResource[]).findIndex((img) => img.id === viewingImage?.id) ===
              (currentItems as ImageResource[]).length - 1
            "
            title="Next (→)"
            @click="viewNextImage"
          >
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M9 5l7 7-7 7"
              />
            </svg>
          </button>

          <!-- Image container -->
          <div class="max-w-[90vw] max-h-[85vh] flex flex-col items-center">
            <img
              :src="getImageUrl(viewingImage)"
              :alt="viewingImage.file_name || 'Image'"
              class="max-w-full max-h-[75vh] object-contain rounded-lg shadow-2xl"
            />

            <!-- Image info -->
            <div class="mt-4 text-center text-white">
              <p class="font-medium">{{ viewingImage.file_name || 'Unnamed' }}</p>
              <p class="text-sm text-white/70 mt-1">
                {{ viewingImage.streamer_name }}
                <span v-if="viewingImage.channel" class="text-white/50"
                  >· {{ viewingImage.channel }}</span
                >
              </p>
              <p class="text-xs text-white/50 mt-1">
                {{ viewingImage.width || '?' }}×{{ viewingImage.height || '?' }} ·
                {{ formatFileSize(viewingImage.file_size) }}
              </p>
              <div class="flex items-center justify-center gap-3 mt-3">
                <button
                  class="px-3 py-1.5 rounded-lg bg-white/10 text-white text-sm hover:bg-white/20 transition-colors"
                  title="View in conversation"
                  @click="
                    () => {
                      if (viewingImage) handleItemClick(viewingImage)
                      closeImageViewer()
                    }
                  "
                >
                  💬 View in Conversation
                </button>
                <button
                  class="px-3 py-1.5 rounded-lg bg-red-600/80 text-white text-sm hover:bg-red-600 transition-colors"
                  title="Delete image"
                  @click="
                    (e) => {
                      if (viewingImage) openDeleteModal(viewingImage, 'image', e)
                      closeImageViewer()
                    }
                  "
                >
                  🗑️ Delete
                </button>
              </div>
            </div>
          </div>

          <!-- Image counter -->
          <div
            class="absolute bottom-4 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full bg-white/10 text-white text-sm"
          >
            {{
              (currentItems as ImageResource[]).findIndex((img) => img.id === viewingImage?.id) + 1
            }}
            / {{ currentItems.length }}
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Video Player Modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showVideoPlayer && playingVideo"
          class="fixed inset-0 bg-black/95 flex items-center justify-center z-50"
          @click.self="closeVideoPlayer"
        >
          <!-- Close button -->
          <button
            class="absolute top-4 right-4 p-2 rounded-full bg-white/10 text-white hover:bg-white/20 transition-colors z-10"
            title="Close (Esc)"
            @click="closeVideoPlayer"
          >
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>

          <!-- Previous button -->
          <button
            class="absolute left-4 top-1/2 -translate-y-1/2 p-3 rounded-full bg-white/10 text-white hover:bg-white/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            :disabled="
              (currentItems as VideoResource[]).findIndex((v) => v.id === playingVideo?.id) === 0
            "
            title="Previous (←)"
            @click="viewPrevVideo"
          >
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M15 19l-7-7 7-7"
              />
            </svg>
          </button>

          <!-- Next button -->
          <button
            class="absolute right-4 top-1/2 -translate-y-1/2 p-3 rounded-full bg-white/10 text-white hover:bg-white/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            :disabled="
              (currentItems as VideoResource[]).findIndex((v) => v.id === playingVideo?.id) ===
              (currentItems as VideoResource[]).length - 1
            "
            title="Next (→)"
            @click="viewNextVideo"
          >
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M9 5l7 7-7 7"
              />
            </svg>
          </button>

          <!-- Video container -->
          <div class="max-w-[90vw] max-h-[85vh] flex flex-col items-center">
            <video
              v-if="playingVideo.video_id"
              :key="playingVideo.video_id"
              :src="getVideoUrl(playingVideo)"
              controls
              autoplay
              class="max-w-full max-h-[70vh] rounded-lg shadow-2xl bg-black"
            >
              Your browser does not support the video tag.
            </video>

            <!-- Video info -->
            <div class="mt-4 text-center text-white">
              <p class="font-medium">{{ playingVideo.streamer_name }}</p>
              <p v-if="playingVideo.content" class="text-sm text-white/70 mt-1">
                {{ playingVideo.content }}
              </p>
              <p class="text-sm text-white/70 mt-1">
                <span v-if="playingVideo.channel" class="text-white/50"
                  >{{ playingVideo.channel }} ·
                </span>
                <span v-if="playingVideo.video_duration"
                  >Duration: {{ playingVideo.video_duration }}</span
                >
              </p>
              <p class="text-xs text-white/50 mt-1">
                {{ playingVideo.kefu_name }} · {{ formatDate(playingVideo.created_at) }}
              </p>
              <div class="flex items-center justify-center gap-3 mt-3">
                <button
                  class="px-3 py-1.5 rounded-lg bg-white/10 text-white text-sm hover:bg-white/20 transition-colors"
                  title="View in conversation"
                  @click="
                    () => {
                      if (playingVideo) handleItemClick(playingVideo)
                      closeVideoPlayer()
                    }
                  "
                >
                  💬 View in Conversation
                </button>
                <button
                  class="px-3 py-1.5 rounded-lg bg-red-600/80 text-white text-sm hover:bg-red-600 transition-colors"
                  title="Delete video"
                  @click="
                    (e) => {
                      if (playingVideo) openDeleteModal(playingVideo, 'video', e)
                      closeVideoPlayer()
                    }
                  "
                >
                  🗑️ Delete
                </button>
              </div>
            </div>
          </div>

          <!-- Video counter -->
          <div
            class="absolute bottom-4 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full bg-white/10 text-white text-sm"
          >
            {{ (currentItems as VideoResource[]).findIndex((v) => v.id === playingVideo?.id) + 1 }}
            / {{ currentItems.length }}
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Voice Player Modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showVoicePlayer && playingVoice"
          class="fixed inset-0 bg-black/95 flex items-center justify-center z-50"
          @click.self="closeVoicePlayer"
        >
          <!-- Close button -->
          <button
            class="absolute top-4 right-4 p-2 rounded-full bg-white/10 text-white hover:bg-white/20 transition-colors z-10"
            title="Close (Esc)"
            @click="closeVoicePlayer"
          >
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>

          <!-- Previous button -->
          <button
            class="absolute left-4 top-1/2 -translate-y-1/2 p-3 rounded-full bg-white/10 text-white hover:bg-white/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            :disabled="
              (currentItems as VoiceResource[]).findIndex((v) => v.id === playingVoice?.id) === 0
            "
            title="Previous (←)"
            @click="viewPrevVoice"
          >
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M15 19l-7-7 7-7"
              />
            </svg>
          </button>

          <!-- Next button -->
          <button
            class="absolute right-4 top-1/2 -translate-y-1/2 p-3 rounded-full bg-white/10 text-white hover:bg-white/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            :disabled="
              (currentItems as VoiceResource[]).findIndex((v) => v.id === playingVoice?.id) ===
              (currentItems as VoiceResource[]).length - 1
            "
            title="Next (→)"
            @click="viewNextVoice"
          >
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M9 5l7 7-7 7"
              />
            </svg>
          </button>

          <!-- Audio container -->
          <div class="max-w-[90vw] flex flex-col items-center">
            <!-- Large voice icon -->
            <div
              class="w-32 h-32 rounded-full bg-wecom-primary/20 flex items-center justify-center mb-6"
            >
              <span class="text-6xl">🎤</span>
            </div>

            <!-- Audio player -->
            <audio
              v-if="playingVoice.voice_file_exists"
              :key="playingVoice.id"
              :src="getVoiceUrl(playingVoice)"
              controls
              autoplay
              class="w-[400px] max-w-full"
            >
              Your browser does not support the audio tag.
            </audio>

            <!-- Voice info -->
            <div class="mt-6 text-center text-white">
              <p class="font-medium text-lg">{{ playingVoice.streamer_name }}</p>
              <p v-if="playingVoice.voice_duration" class="text-sm text-white/70 mt-2">
                Duration: {{ playingVoice.voice_duration }}
              </p>
              <p v-if="playingVoice.content" class="text-sm text-white/70 mt-2 max-w-md">
                Transcription: {{ playingVoice.content }}
              </p>
              <p class="text-sm text-white/70 mt-2">
                <span v-if="playingVoice.channel" class="text-white/50"
                  >{{ playingVoice.channel }} ·
                </span>
                <span>{{ playingVoice.is_from_kefu ? 'Agent' : 'Streamer' }}</span>
              </p>
              <p class="text-xs text-white/50 mt-1">
                {{ playingVoice.kefu_name }} · {{ formatDate(playingVoice.created_at) }}
              </p>
              <div class="flex items-center justify-center gap-3 mt-4">
                <button
                  class="px-3 py-1.5 rounded-lg bg-white/10 text-white text-sm hover:bg-white/20 transition-colors"
                  title="View in conversation"
                  @click="
                    () => {
                      if (playingVoice) handleItemClick(playingVoice)
                      closeVoicePlayer()
                    }
                  "
                >
                  💬 View in Conversation
                </button>
                <button
                  class="px-3 py-1.5 rounded-lg bg-red-600/80 text-white text-sm hover:bg-red-600 transition-colors"
                  title="Delete voice message"
                  @click="
                    (e) => {
                      if (playingVoice) openDeleteModal(playingVoice, 'voice', e)
                      closeVoicePlayer()
                    }
                  "
                >
                  🗑️ Delete
                </button>
              </div>
            </div>
          </div>

          <!-- Voice counter -->
          <div
            class="absolute bottom-4 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full bg-white/10 text-white text-sm"
          >
            {{ (currentItems as VoiceResource[]).findIndex((v) => v.id === playingVoice?.id) + 1 }}
            / {{ currentItems.length }}
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

.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
