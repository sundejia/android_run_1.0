<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useCustomerStore } from '../stores/customers'
import VideoAiReviewSummary from '../components/VideoAiReviewSummary.vue'
import VideoReviewDetailPanel from '../components/VideoReviewDetailPanel.vue'
import { avatarUrlForCustomer } from '../utils/avatars'
import {
  api,
  type VideoInfo,
  type ImageInfo,
  type VoiceInfo,
  type CustomerMessage,
} from '../services/api'
import { useI18n } from '../composables/useI18n'
import { formatAiReviewLabel } from '../utils/aiReviewDetails'

const { t } = useI18n()

type ImageReviewStatus = 'pending' | 'completed' | 'timeout' | 'failed'

function getAiReviewStatus(msg: CustomerMessage): ImageReviewStatus | null {
  if (msg.ai_review_status) {
    return msg.ai_review_status
  }
  if (
    msg.ai_review_score != null ||
    !!msg.ai_review_decision ||
    !!msg.ai_review_reason ||
    !!msg.ai_review_at
  ) {
    return 'completed'
  }
  return null
}

function shouldShowAiReviewSection(msg: CustomerMessage): boolean {
  return getAiReviewStatus(msg) !== null
}

function getAiReviewErrorMessage(msg: CustomerMessage): string | null {
  const error = msg.ai_review_error?.trim()
  return error ? error : null
}

const route = useRoute()
const router = useRouter()
const customerStore = useCustomerStore()

// Video info cache: message_id -> VideoInfo
const videoInfoCache = ref<Map<number, VideoInfo | null>>(new Map())
const videoLoadingIds = ref<Set<number>>(new Set())

// Image info cache: message_id -> ImageInfo
const imageInfoCache = ref<Map<number, ImageInfo | null>>(new Map())
const imageLoadingIds = ref<Set<number>>(new Set())

// Voice info cache: message_id -> VoiceInfo
const voiceInfoCache = ref<Map<number, VoiceInfo | null>>(new Map())
const voiceLoadingIds = ref<Set<number>>(new Set())

// Video player modal state
const showVideoPlayer = ref(false)
const playingVideoInfo = ref<VideoInfo | null>(null)
const playingMessageId = ref<number | null>(null)

const videoReviewModalOpen = ref(false)
const videoReviewMessageId = ref(0)
const videoReviewFramesJson = ref<string | null>(null)
const videoReviewAggregateScore = ref<number | null>(null)

// Image viewer modal state
const showImageViewer = ref(false)
const viewingImageInfo = ref<ImageInfo | null>(null)

// Voice player state
const playingVoiceInfo = ref<VoiceInfo | null>(null)
const playingVoiceMessageId = ref<number | null>(null)
const voiceAudioRef = ref<HTMLAudioElement | null>(null)

const customerId = computed(() => Number(route.params.id))
const customer = computed(() => customerStore.selectedCustomer)
const messages = computed(() => customerStore.messages)

// Highlight message support (from resources navigation)
const highlightedMessageId = ref<number | null>(null)
const messageRefs = ref<Record<number, HTMLElement | null>>({})

// Search within conversation support
const searchQuery = ref<string>('')
const matchingMessageIds = ref<number[]>([])
const currentMatchIndex = ref<number>(0)

// Cross-conversation search support
interface GlobalSearchResult {
  message_id: number
  customer_id: number
  customer_name: string
  content_preview: string
}
const globalSearchResults = ref<GlobalSearchResult[]>([])
const globalSearchIndex = ref<number>(0)

// Computed: unique conversations and current conversation position
const uniqueConversationIds = computed(() => {
  const ids = new Set(globalSearchResults.value.map((r) => r.customer_id))
  return Array.from(ids)
})

const currentConversationIndex = computed(() => {
  const idx = uniqueConversationIds.value.indexOf(customerId.value)
  return idx === -1 ? 0 : idx
})

const totalConversations = computed(() => uniqueConversationIds.value.length)

function setMessageRef(id: number, el: HTMLElement | null) {
  messageRefs.value[id] = el
}

// Flag to track if we're in search navigation mode (for faster transitions)
const isSearchNavigation = ref(false)

function scrollToHighlightedMessage() {
  if (highlightedMessageId.value && messageRefs.value[highlightedMessageId.value]) {
    const el = messageRefs.value[highlightedMessageId.value]
    if (el) {
      // Use instant scroll for search navigation, smooth for normal navigation
      el.scrollIntoView({
        behavior: isSearchNavigation.value ? 'instant' : 'smooth',
        block: 'center',
      })
    }
  }
}

// Find all messages matching the search query
function findMatchingMessages(query: string) {
  if (!query || query.length < 1) {
    matchingMessageIds.value = []
    return
  }

  const lowerQuery = query.toLowerCase()
  matchingMessageIds.value = messages.value
    .filter((m) => m.content && m.content.toLowerCase().includes(lowerQuery))
    .map((m) => m.id)
}

// Jump to next matching message (within current conversation or to next conversation)
function jumpToNextMatch() {
  // If no local matches, try to jump to next conversation
  if (matchingMessageIds.value.length === 0) {
    jumpToNextConversation()
    return
  }

  // Find current position in matches
  const currentIndex = matchingMessageIds.value.indexOf(highlightedMessageId.value || -1)

  // Check if we're at the last match in this conversation
  if (currentIndex >= matchingMessageIds.value.length - 1) {
    // Try to jump to next conversation
    if (jumpToNextConversation()) {
      return // Successfully navigated to next conversation
    }
    // If no next conversation, cycle back to first match in current conversation
  }

  // Calculate next index
  let nextIndex: number
  if (currentIndex === -1 || currentIndex >= matchingMessageIds.value.length - 1) {
    nextIndex = 0 // Start from beginning of current conversation
  } else {
    nextIndex = currentIndex + 1
  }

  currentMatchIndex.value = nextIndex
  highlightedMessageId.value = matchingMessageIds.value[nextIndex]

  // Scroll to the new highlighted message
  nextTick(() => {
    scrollToHighlightedMessage()
  })
}

// Clear search state
function clearSearch() {
  searchQuery.value = ''
  matchingMessageIds.value = []
  globalSearchResults.value = []
  highlightedMessageId.value = null
  currentMatchIndex.value = 0
  globalSearchIndex.value = 0
  isSearchNavigation.value = false
  // Clear sessionStorage
  sessionStorage.removeItem('messageSearchResults')
  sessionStorage.removeItem('messageSearchIndex')
  sessionStorage.removeItem('messageSearchQuery')
  // Clear URL query params
  router.replace({
    name: 'conversation-detail',
    params: { id: customerId.value },
    query: {},
  })
}

// Jump to next conversation with matching messages
function jumpToNextConversation(): boolean {
  if (uniqueConversationIds.value.length <= 1) return false

  // Get current conversation index and calculate next
  const currentIdx = currentConversationIndex.value
  const nextIdx = (currentIdx + 1) % uniqueConversationIds.value.length

  // Get next conversation ID
  const nextCustomerId = uniqueConversationIds.value[nextIdx]

  // Navigate to next conversation (searchQuery will trigger starting from first match)
  router.push({
    name: 'conversation-detail',
    params: { id: nextCustomerId },
    query: {
      searchQuery: searchQuery.value,
    },
  })

  return true
}

// Load global search results from sessionStorage
function loadGlobalSearchResults() {
  try {
    const resultsStr = sessionStorage.getItem('messageSearchResults')
    const indexStr = sessionStorage.getItem('messageSearchIndex')
    const query = sessionStorage.getItem('messageSearchQuery')

    if (resultsStr) {
      globalSearchResults.value = JSON.parse(resultsStr)
    }
    if (indexStr) {
      globalSearchIndex.value = parseInt(indexStr, 10)
    }
    if (query && !searchQuery.value) {
      searchQuery.value = query
    }
  } catch (e) {
    console.error('Failed to load global search results:', e)
  }
}

// Handle keyboard navigation for search
function handleSearchKeydown(event: KeyboardEvent) {
  // Only handle Enter key when not in modal viewers
  if (
    event.key === 'Enter' &&
    !showVideoPlayer.value &&
    !showImageViewer.value &&
    !videoReviewModalOpen.value
  ) {
    if (matchingMessageIds.value.length > 0) {
      event.preventDefault()
      jumpToNextMatch()
    }
  }
}

// Highlight search term in message content
function highlightSearchTerm(content: string): string {
  if (!searchQuery.value || !content) return content
  const query = searchQuery.value
  const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
  return content.replace(
    regex,
    '<mark class="bg-yellow-400/50 text-yellow-100 px-0.5 rounded">$1</mark>'
  )
}

function formatDate(value: string | null | undefined) {
  if (!value) return '—'
  const parsed = new Date(value)
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toLocaleString()
  }
  return value
}

// Fetch video info for a message
async function fetchVideoInfo(messageId: number) {
  if (videoInfoCache.value.has(messageId) || videoLoadingIds.value.has(messageId)) {
    return
  }

  videoLoadingIds.value.add(messageId)
  try {
    const response = await api.getVideoByMessageId(messageId)
    videoInfoCache.value.set(messageId, response.video)
  } catch (e) {
    console.error('Failed to fetch video info for message', messageId, e)
    videoInfoCache.value.set(messageId, null)
  } finally {
    videoLoadingIds.value.delete(messageId)
  }
}

// Get video info from cache
function getVideoInfo(messageId: number): VideoInfo | null | undefined {
  return videoInfoCache.value.get(messageId)
}

// Check if video info is loading
function isVideoLoading(messageId: number): boolean {
  return videoLoadingIds.value.has(messageId)
}

// Get video URL for playback
function getVideoUrl(videoId: number): string {
  return api.getVideoUrl(videoId)
}

// Open video player
function openVideoPlayer(messageId: number, videoInfo: VideoInfo) {
  playingMessageId.value = messageId
  playingVideoInfo.value = videoInfo
  showVideoPlayer.value = true
}

// Close video player
function closeVideoPlayer() {
  showVideoPlayer.value = false
  playingVideoInfo.value = null
  playingMessageId.value = null
}

function openVideoReviewDetail(msg: CustomerMessage) {
  videoReviewMessageId.value = msg.id
  videoReviewFramesJson.value = msg.video_ai_review_frames_json ?? null
  videoReviewAggregateScore.value = msg.video_ai_review_score ?? null
  videoReviewModalOpen.value = true
}

// Fetch image info for a message
async function fetchImageInfo(messageId: number) {
  if (imageInfoCache.value.has(messageId) || imageLoadingIds.value.has(messageId)) {
    return
  }

  imageLoadingIds.value.add(messageId)
  try {
    const response = await api.getImageByMessageId(messageId)
    imageInfoCache.value.set(messageId, response.image)
  } catch (e) {
    console.error('Failed to fetch image info for message', messageId, e)
    imageInfoCache.value.set(messageId, null)
  } finally {
    imageLoadingIds.value.delete(messageId)
  }
}

// Get image info from cache
function getImageInfo(messageId: number): ImageInfo | null | undefined {
  return imageInfoCache.value.get(messageId)
}

// Check if image info is loading
function isImageLoading(messageId: number): boolean {
  return imageLoadingIds.value.has(messageId)
}

// Get image URL for display
function getImageUrl(imageId: number): string {
  return api.getImageUrl(imageId)
}

// Open image viewer
function openImageViewer(imageInfo: ImageInfo) {
  viewingImageInfo.value = imageInfo
  showImageViewer.value = true
}

// Close image viewer
function closeImageViewer() {
  showImageViewer.value = false
  viewingImageInfo.value = null
}

// Fetch voice info for a message
async function fetchVoiceInfo(messageId: number) {
  if (voiceInfoCache.value.has(messageId) || voiceLoadingIds.value.has(messageId)) {
    return
  }

  voiceLoadingIds.value.add(messageId)
  try {
    const response = await api.getVoiceByMessageId(messageId)
    voiceInfoCache.value.set(messageId, response.voice)
  } catch (e) {
    console.error('Failed to fetch voice info for message', messageId, e)
    voiceInfoCache.value.set(messageId, null)
  } finally {
    voiceLoadingIds.value.delete(messageId)
  }
}

// Get voice info from cache
function getVoiceInfo(messageId: number): VoiceInfo | null | undefined {
  return voiceInfoCache.value.get(messageId)
}

// Check if voice info is loading
function isVoiceLoading(messageId: number): boolean {
  return voiceLoadingIds.value.has(messageId)
}

// Get voice file URL for playback
function getVoiceFileUrl(messageId: number): string {
  return api.getVoiceFileUrl(messageId)
}

// Play voice message
function playVoice(messageId: number, voiceInfo: VoiceInfo) {
  // Stop any currently playing voice
  if (voiceAudioRef.value) {
    voiceAudioRef.value.pause()
    voiceAudioRef.value.currentTime = 0
  }

  playingVoiceInfo.value = voiceInfo
  playingVoiceMessageId.value = messageId

  // Create and play audio
  const audio = new Audio(getVoiceFileUrl(messageId))
  voiceAudioRef.value = audio

  audio.onended = () => {
    playingVoiceInfo.value = null
    playingVoiceMessageId.value = null
  }

  audio.onerror = () => {
    console.error('Failed to play voice message')
    playingVoiceInfo.value = null
    playingVoiceMessageId.value = null
  }

  audio.play().catch((e) => {
    console.error('Failed to play voice:', e)
    playingVoiceInfo.value = null
    playingVoiceMessageId.value = null
  })
}

// Stop voice playback
function stopVoice() {
  if (voiceAudioRef.value) {
    voiceAudioRef.value.pause()
    voiceAudioRef.value.currentTime = 0
  }
  playingVoiceInfo.value = null
  playingVoiceMessageId.value = null
}

// Navigate to resource page for media messages
function navigateToResource(messageId: number, messageType: string) {
  // Determine which tab to open based on message type
  let tab = 'images'
  if (messageType === 'video') {
    tab = 'videos'
  } else if (messageType === 'voice') {
    tab = 'voice'
  } else if (messageType === 'image') {
    tab = 'images'
  } else {
    // Not a media message, don't navigate
    return
  }

  router.push({
    path: '/resources',
    query: {
      tab,
      highlightMessage: messageId.toString(),
    },
  })
}

// Check if message is a media type that can link to resources
function isMediaMessage(messageType: string): boolean {
  return ['video', 'image', 'voice', 'sticker'].includes(messageType)
}

// Keyboard handler for media viewers
function handleMediaViewerKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    if (videoReviewModalOpen.value) {
      videoReviewModalOpen.value = false
    } else if (showVideoPlayer.value) {
      closeVideoPlayer()
    } else if (showImageViewer.value) {
      closeImageViewer()
    } else if (playingVoiceInfo.value) {
      stopVoice()
    }
  }
}

// Fetch video info for all video messages
async function fetchAllVideoInfo() {
  const videoMessages = messages.value.filter((m) => m.message_type === 'video')
  await Promise.all(videoMessages.map((m) => fetchVideoInfo(m.id)))
}

// Fetch image info for all image messages (including stickers)
async function fetchAllImageInfo() {
  const imageMessages = messages.value.filter(
    (m) => m.message_type === 'image' || m.message_type === 'sticker'
  )
  await Promise.all(imageMessages.map((m) => fetchImageInfo(m.id)))
}

// Fetch voice info for all voice messages
async function fetchAllVoiceInfo() {
  const voiceMessages = messages.value.filter((m) => m.message_type === 'voice')
  await Promise.all(voiceMessages.map((m) => fetchVoiceInfo(m.id)))
}

async function load() {
  const id = customerId.value
  if (Number.isNaN(id)) {
    router.push({ name: 'conversations' })
    return
  }

  try {
    await customerStore.fetchCustomerDetail(id, { messagesLimit: 200 })

    // Fetch media info for all media messages
    await Promise.all([fetchAllVideoInfo(), fetchAllImageInfo(), fetchAllVoiceInfo()])

    // Handle highlight message and search query from URL params
    const highlightId = route.query.highlightMessage
    const queryParam = route.query.searchQuery as string

    if (queryParam) {
      searchQuery.value = queryParam
      isSearchNavigation.value = true // Enable fast navigation mode
      findMatchingMessages(queryParam)

      // Always start from the FIRST matching message in this conversation (chronological order)
      if (matchingMessageIds.value.length > 0) {
        highlightedMessageId.value = matchingMessageIds.value[0]
        currentMatchIndex.value = 0
        // Scroll to the first matching message
        await nextTick()
        scrollToHighlightedMessage()
      }
    } else if (highlightId) {
      // Non-search navigation (e.g., from resources page)
      highlightedMessageId.value = parseInt(highlightId as string, 10)
      await nextTick()
      scrollToHighlightedMessage()
    }
  } catch (e) {
    console.error('Failed to load customer detail', e)
  }
}

onMounted(() => {
  console.log('[CustomerDetailView] onMounted called')
  loadGlobalSearchResults()
  load()
  window.addEventListener('keydown', handleMediaViewerKeydown)
  window.addEventListener('keydown', handleSearchKeydown)

  // 设置全局 WebSocket 监听（实时更新 History）
  console.log('[CustomerDetailView] About to call setupGlobalWebSocket')
  customerStore.setupGlobalWebSocket()
  console.log('[CustomerDetailView] setupGlobalWebSocket call completed')
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleMediaViewerKeydown)
  window.removeEventListener('keydown', handleSearchKeydown)

  // 清理全局 WebSocket 监听
  customerStore.cleanupGlobalWebSocket()

  // Stop any playing voice
  if (voiceAudioRef.value) {
    voiceAudioRef.value.pause()
    voiceAudioRef.value = null
  }
})

watch(
  () => route.params.id,
  () => {
    // Clear media caches when switching customers
    videoInfoCache.value.clear()
    imageInfoCache.value.clear()
    // Reload global search results (sessionStorage may have been updated)
    loadGlobalSearchResults()
    load()
  }
)

// Watch for query changes (highlight message and search query)
watch(
  () => [route.query.highlightMessage, route.query.searchQuery],
  async ([newId, newQuery]) => {
    // Update search query and find matches
    if (newQuery) {
      searchQuery.value = newQuery as string
      isSearchNavigation.value = true // Enable fast navigation mode
      findMatchingMessages(newQuery as string)

      // Always start from the FIRST matching message in this conversation
      if (matchingMessageIds.value.length > 0) {
        highlightedMessageId.value = matchingMessageIds.value[0]
        currentMatchIndex.value = 0
        await nextTick()
        scrollToHighlightedMessage()
      }
    } else if (newId) {
      // Non-search navigation
      highlightedMessageId.value = parseInt(newId as string, 10)
      await nextTick()
      scrollToHighlightedMessage()
    }
  }
)
</script>

<template>
  <div class="p-6 space-y-6" :class="{ 'animate-fade-in': !isSearchNavigation }">
    <div class="flex items-center gap-3 text-sm text-wecom-muted">
      <router-link to="/conversations" class="btn-secondary text-xs">
        ← Back to conversations
      </router-link>
      <span>Conversation ID: {{ customerId }}</span>
      <span v-if="customerStore.lastFetchedPath">DB: {{ customerStore.lastFetchedPath }}</span>
    </div>

    <!-- Floating search indicator - fixed in top-right corner -->
    <Teleport to="body">
      <div
        v-if="searchQuery"
        class="fixed top-16 right-4 z-50 flex items-center gap-2 px-4 py-2 bg-wecom-dark/95 border border-yellow-500/50 rounded-lg shadow-lg backdrop-blur-sm"
      >
        <span class="text-yellow-400">🔍</span>
        <div class="flex flex-col">
          <span class="text-yellow-300 text-sm">
            "{{ searchQuery }}" -
            <template v-if="matchingMessageIds.length > 0">
              Conversation {{ currentMatchIndex + 1 }}/{{ matchingMessageIds.length }}
            </template>
            <template v-else> No matches in this conversation </template>
            <template v-if="totalConversations > 1">
              · Conversation {{ currentConversationIndex + 1 }}/{{ totalConversations }}
            </template>
          </span>
          <span class="text-yellow-400/70 text-xs">Press Enter to jump to next</span>
        </div>
        <button
          class="ml-2 text-yellow-400/50 hover:text-yellow-400 transition-colors"
          title="Close search"
          @click="clearSearch"
        >
          ✕
        </button>
      </div>
    </Teleport>

    <div
      v-if="customerStore.detailError"
      class="bg-red-900/20 border border-red-500/30 rounded-lg p-4 flex items-center gap-3"
    >
      <span class="text-red-400">⚠️</span>
      <div>
        <p class="text-red-400 font-medium">Failed to load conversation</p>
        <p class="text-red-400/70 text-sm">{{ customerStore.detailError }}</p>
      </div>
      <button class="btn-secondary text-sm ml-auto" @click="load">Retry</button>
    </div>

    <div
      v-else-if="customerStore.detailLoading && !customer"
      class="bg-wecom-dark border border-wecom-border rounded-xl p-6 flex items-center justify-center text-wecom-muted"
    >
      Loading conversation...
    </div>

    <div v-else-if="customer" class="space-y-4">
      <!-- Summary card -->
      <div class="bg-wecom-dark border border-wecom-border rounded-xl p-4 space-y-3">
        <div class="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
          <div class="flex items-center gap-3">
            <img
              :src="avatarUrlForCustomer(customer)"
              :alt="`Avatar for ${customer.name}`"
              class="w-14 h-14 rounded-full border border-wecom-border bg-wecom-surface object-cover"
            />
            <div>
              <p class="text-sm text-wecom-muted">Streamer</p>
              <h2 class="text-2xl font-display font-bold text-wecom-text">
                {{ customer.name }}
              </h2>
              <p class="text-sm text-wecom-muted">Channel: {{ customer.channel || '—' }}</p>
            </div>
          </div>
          <div class="text-right text-sm text-wecom-muted space-y-1">
            <p>
              Last message at:
              {{ formatDate(customer.last_message_at || customer.last_message_date) }}
            </p>
            <p>Updated: {{ formatDate(customer.updated_at) }}</p>
            <p>Created: {{ formatDate(customer.created_at) }}</p>
          </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 text-sm">
          <div class="bg-wecom-surface border border-wecom-border rounded-lg p-3">
            <p class="text-wecom-muted">Agent</p>
            <p class="text-wecom-text font-semibold">{{ customer.kefu_name }}</p>
            <p class="text-xs text-wecom-muted">
              {{ customer.kefu_department || 'No dept' }} ·
              {{ customer.kefu_verification_status || 'Not verified' }}
            </p>
          </div>
          <div class="bg-wecom-surface border border-wecom-border rounded-lg p-3">
            <p class="text-wecom-muted">Device</p>
            <p class="text-wecom-text font-semibold">{{ customer.device_serial }}</p>
            <p class="text-xs text-wecom-muted">
              {{ customer.device_model || 'Unknown model' }}
            </p>
          </div>
          <div class="bg-wecom-surface border border-wecom-border rounded-lg p-3">
            <p class="text-wecom-muted">Messages</p>
            <p class="text-wecom-text font-semibold">{{ customer.message_count }} total</p>
            <p class="text-xs text-wecom-muted">
              {{ customer.sent_by_kefu }} sent · {{ customer.sent_by_customer }} received
            </p>
          </div>
        </div>
      </div>

      <!-- Message breakdown -->
      <div class="bg-wecom-dark border border-wecom-border rounded-xl p-4 space-y-2">
        <div class="flex items-center justify-between">
          <h3 class="text-lg font-display font-semibold text-wecom-text">Message breakdown</h3>
          <span class="text-xs text-wecom-muted">
            {{ Object.keys(customerStore.messageBreakdown).length || 0 }} types
          </span>
        </div>
        <div class="flex flex-wrap gap-2 text-xs text-wecom-text">
          <span
            v-for="(count, type) in customerStore.messageBreakdown"
            :key="type"
            class="px-2 py-1 rounded bg-wecom-surface border border-wecom-border"
          >
            {{ type }}: {{ count }}
          </span>
          <span
            v-if="Object.keys(customerStore.messageBreakdown).length === 0"
            class="text-wecom-muted"
          >
            No messages yet.
          </span>
        </div>
      </div>

      <!-- Conversation -->
      <div class="bg-wecom-dark border border-wecom-border rounded-xl p-4 space-y-3">
        <div class="flex items-center justify-between">
          <h3 class="text-lg font-display font-semibold text-wecom-text">
            Conversation (latest {{ messages.length }} messages)
          </h3>
          <button
            class="btn-secondary text-sm"
            :disabled="customerStore.detailLoading"
            @click="load"
          >
            Refresh
          </button>
        </div>

        <div v-if="messages.length === 0" class="text-wecom-muted text-sm">
          No messages have been synced for this streamer.
        </div>
        <div v-else class="space-y-3">
          <div
            v-for="msg in messages"
            :key="msg.id"
            :ref="(el) => setMessageRef(msg.id, el as HTMLElement)"
            class="border rounded-lg p-3 transition-all duration-150 group/msg"
            :class="[
              msg.is_from_kefu
                ? 'border-wecom-primary/50 bg-wecom-primary/10'
                : 'border-wecom-border bg-wecom-surface/60',
              highlightedMessageId === msg.id
                ? 'ring-2 ring-yellow-400 bg-yellow-400/20 border-yellow-400'
                : '',
              isMediaMessage(msg.message_type) ? 'cursor-pointer hover:border-wecom-accent' : '',
            ]"
            @click="
              isMediaMessage(msg.message_type) ? navigateToResource(msg.id, msg.message_type) : null
            "
          >
            <div class="flex items-center justify-between text-xs text-wecom-muted">
              <span class="flex items-center gap-1">
                {{ msg.is_from_kefu ? 'Agent' : 'Streamer' }} · {{ msg.message_type }}
                <!-- Media link indicator -->
                <span
                  v-if="isMediaMessage(msg.message_type)"
                  class="ml-1 opacity-0 group-hover/msg:opacity-100 transition-opacity text-wecom-primary"
                  title="Click to view in Resources"
                >
                  🔗
                </span>
                <span
                  v-if="highlightedMessageId === msg.id"
                  class="ml-2 px-1.5 py-0.5 rounded bg-yellow-400/30 text-yellow-300 text-[10px]"
                >
                  📍 Highlighted
                </span>
              </span>
              <span>
                {{ formatDate(msg.timestamp_parsed || msg.created_at || msg.timestamp_raw) }}
              </span>
            </div>

            <!-- Video message with thumbnail and play button -->
            <div v-if="msg.message_type === 'video'" class="mt-2">
              <div
                class="relative inline-block rounded-lg overflow-hidden bg-wecom-darker border border-wecom-border"
                :class="
                  getVideoInfo(msg.id)?.video_id
                    ? 'cursor-pointer hover:border-wecom-primary group'
                    : 'opacity-60'
                "
                @click.stop="
                  getVideoInfo(msg.id)?.video_id
                    ? openVideoPlayer(msg.id, getVideoInfo(msg.id)!)
                    : null
                "
              >
                <!-- Video thumbnail image -->
                <img
                  v-if="getVideoInfo(msg.id)?.video_id"
                  :src="api.getVideoThumbnailUrl(getVideoInfo(msg.id)!.video_id)"
                  alt="Video thumbnail"
                  class="w-48 h-28 object-cover"
                  @error="($event.target as HTMLImageElement).style.display = 'none'"
                />

                <!-- Fallback thumbnail placeholder (shows when no video_id or image fails to load) -->
                <div
                  v-if="!getVideoInfo(msg.id)?.video_id"
                  class="w-48 h-28 flex items-center justify-center bg-gradient-to-br from-wecom-dark to-wecom-darker"
                >
                  <span class="text-4xl opacity-40">🎬</span>
                </div>

                <!-- Play button overlay (only if video is available) -->
                <div
                  v-if="getVideoInfo(msg.id)?.video_id"
                  class="absolute inset-0 flex items-center justify-center bg-black/20 group-hover:bg-black/40 transition-colors"
                >
                  <div
                    class="w-12 h-12 rounded-full bg-wecom-primary/90 flex items-center justify-center shadow-lg transform transition-transform group-hover:scale-110"
                  >
                    <svg class="w-6 h-6 text-white ml-0.5" fill="currentColor" viewBox="0 0 24 24">
                      <path d="M8 5v14l11-7z" />
                    </svg>
                  </div>
                </div>

                <!-- Loading indicator -->
                <div
                  v-else-if="isVideoLoading(msg.id)"
                  class="absolute inset-0 flex items-center justify-center bg-black/30"
                >
                  <span class="text-white text-sm animate-pulse">Loading...</span>
                </div>

                <!-- No video file indicator -->
                <div
                  v-else-if="getVideoInfo(msg.id) === null"
                  class="absolute inset-0 flex items-center justify-center bg-black/30"
                >
                  <span class="text-white/70 text-xs px-2 py-1 bg-black/50 rounded"
                    >No video file</span
                  >
                </div>

                <!-- Duration badge -->
                <div
                  v-if="getVideoInfo(msg.id)?.duration"
                  class="absolute bottom-2 right-2 px-2 py-0.5 bg-black/70 text-white text-xs rounded font-mono z-10"
                >
                  {{ getVideoInfo(msg.id)?.duration }}
                </div>
              </div>

              <VideoAiReviewSummary
                v-if="msg.message_type === 'video'"
                :message-id="msg.id"
                :video-ai-review-score="msg.video_ai_review_score"
                :video-ai-review-status="msg.video_ai_review_status"
                :video-ai-review-error="msg.video_ai_review_error"
                :video-ai-review-at="msg.video_ai_review_at"
                :is-from-kefu="msg.is_from_kefu"
                @open-detail="openVideoReviewDetail(msg)"
              />

              <!-- Video content text -->
              <p v-if="msg.content" class="text-wecom-text mt-2 text-sm">
                {{ msg.content }}
              </p>
            </div>

            <!-- Image message with thumbnail -->
            <div v-else-if="msg.message_type === 'image'" class="mt-2">
              <div
                class="relative inline-block rounded-lg overflow-hidden bg-wecom-darker border border-wecom-border"
                :class="
                  getImageInfo(msg.id)?.image_id
                    ? 'cursor-pointer hover:border-wecom-primary group'
                    : 'opacity-60'
                "
                @click.stop="
                  getImageInfo(msg.id)?.image_id ? openImageViewer(getImageInfo(msg.id)!) : null
                "
              >
                <!-- Image thumbnail -->
                <div
                  v-if="getImageInfo(msg.id)?.image_id"
                  class="max-w-[200px] max-h-[150px] overflow-hidden"
                >
                  <img
                    :src="getImageUrl(getImageInfo(msg.id)!.image_id)"
                    :alt="getImageInfo(msg.id)?.file_name || 'Image'"
                    class="w-auto h-auto max-w-[200px] max-h-[150px] object-contain hover:scale-105 transition-transform duration-200"
                  />
                </div>

                <!-- Placeholder when no image -->
                <div
                  v-else
                  class="w-48 h-28 flex items-center justify-center bg-gradient-to-br from-wecom-dark to-wecom-darker"
                >
                  <span class="text-4xl opacity-40">🖼️</span>
                </div>

                <!-- Loading indicator -->
                <div
                  v-if="isImageLoading(msg.id)"
                  class="absolute inset-0 flex items-center justify-center bg-black/30"
                >
                  <span class="text-white text-sm animate-pulse">Loading...</span>
                </div>

                <!-- No image file indicator -->
                <div
                  v-else-if="getImageInfo(msg.id) === null"
                  class="absolute inset-0 flex items-center justify-center bg-black/30"
                >
                  <span class="text-white/70 text-xs px-2 py-1 bg-black/50 rounded"
                    >No image file</span
                  >
                </div>

                <!-- Zoom hint on hover -->
                <div
                  v-if="getImageInfo(msg.id)?.image_id"
                  class="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/20 transition-colors"
                >
                  <span
                    class="text-white text-2xl opacity-0 group-hover:opacity-100 transition-opacity"
                    >🔍</span
                  >
                </div>

                <!-- Dimensions badge -->
                <div
                  v-if="getImageInfo(msg.id)?.width && getImageInfo(msg.id)?.height"
                  class="absolute bottom-2 right-2 px-2 py-0.5 bg-black/70 text-white text-xs rounded font-mono"
                >
                  {{ getImageInfo(msg.id)?.width }}×{{ getImageInfo(msg.id)?.height }}
                </div>
              </div>

              <div
                v-if="shouldShowAiReviewSection(msg)"
                class="text-xs mt-2 pt-2 border-t border-wecom-border space-y-0.5 text-left leading-snug text-wecom-muted"
                @click.stop
              >
                <template v-if="getAiReviewStatus(msg) === 'pending'">
                  <div class="font-medium text-wecom-text">正在等待图片审核</div>
                </template>
                <template v-else-if="getAiReviewStatus(msg) === 'timeout'">
                  <div class="font-medium text-yellow-400">图片审核超时</div>
                  <div v-if="getAiReviewErrorMessage(msg)" class="whitespace-pre-wrap opacity-90">
                    {{ getAiReviewErrorMessage(msg) }}
                  </div>
                </template>
                <template v-else-if="getAiReviewStatus(msg) === 'failed'">
                  <div class="font-medium text-red-400">图片审核失败</div>
                  <div v-if="getAiReviewErrorMessage(msg)" class="whitespace-pre-wrap opacity-90">
                    {{ getAiReviewErrorMessage(msg) }}
                  </div>
                </template>
                <div
                  v-if="getAiReviewStatus(msg) === 'completed' && msg.ai_review_score != null"
                  class="font-medium text-wecom-text"
                >
                  {{ t('sidecar.ai_review_score', undefined, 'AI 评分') }}:
                  {{ Number(msg.ai_review_score).toFixed(1) }}
                </div>
                <div
                  v-if="getAiReviewStatus(msg) === 'completed' && msg.ai_review_decision"
                  class="text-wecom-text opacity-90"
                >
                  {{ msg.ai_review_decision }}
                </div>
                <div
                  v-if="getAiReviewStatus(msg) === 'completed' && msg.ai_review_reason"
                  class="whitespace-pre-wrap opacity-90"
                >
                  {{ t('sidecar.ai_review_reason', undefined, '原因') }}:
                  {{ msg.ai_review_reason }}
                </div>
                <div
                  v-if="
                    getAiReviewStatus(msg) === 'completed' &&
                    msg.ai_review_score_reasons &&
                    msg.ai_review_score_reasons.length
                  "
                  class="space-y-1 pt-1"
                >
                  <div
                    v-for="item in msg.ai_review_score_reasons"
                    :key="`${msg.id}-${item.key}`"
                    class="whitespace-pre-wrap opacity-90"
                  >
                    {{ formatAiReviewLabel(item.label)
                    }}<template v-if="item.score"> ({{ item.score }})</template>:
                    {{ item.reason }}
                  </div>
                </div>
                <div
                  v-if="
                    getAiReviewStatus(msg) === 'completed' &&
                    msg.ai_review_penalties &&
                    msg.ai_review_penalties.length
                  "
                  class="space-y-1 pt-1"
                >
                  <div class="text-wecom-text opacity-90">
                    {{ t('sidecar.ai_review_penalties', undefined, '扣分项') }}:
                  </div>
                  <div
                    v-for="(penalty, index) in msg.ai_review_penalties"
                    :key="`${msg.id}-penalty-${index}`"
                    class="whitespace-pre-wrap pl-2 opacity-85"
                  >
                    - {{ penalty }}
                  </div>
                </div>
                <div
                  v-if="getAiReviewStatus(msg) === 'completed' && msg.ai_review_at"
                  class="opacity-70 text-[10px] font-mono"
                >
                  {{ msg.ai_review_at }}
                </div>
              </div>

              <!-- Image content text -->
              <p v-if="msg.content" class="text-wecom-text mt-2 text-sm">
                {{ msg.content }}
              </p>
            </div>

            <!-- Sticker message (表情包) -->
            <div v-else-if="msg.message_type === 'sticker'" class="mt-2">
              <div
                class="relative inline-block rounded-lg overflow-hidden bg-wecom-darker border border-wecom-border"
                :class="
                  getImageInfo(msg.id)?.image_id
                    ? 'cursor-pointer hover:border-yellow-500 group'
                    : 'opacity-60'
                "
                @click.stop="
                  getImageInfo(msg.id)?.image_id ? openImageViewer(getImageInfo(msg.id)!) : null
                "
              >
                <!-- Sticker thumbnail -->
                <div
                  v-if="getImageInfo(msg.id)?.image_id"
                  class="max-w-[150px] max-h-[150px] overflow-hidden"
                >
                  <img
                    :src="getImageUrl(getImageInfo(msg.id)!.image_id)"
                    :alt="getImageInfo(msg.id)?.file_name || 'Sticker'"
                    class="w-auto h-auto max-w-[150px] max-h-[150px] object-contain hover:scale-105 transition-transform duration-200"
                  />
                </div>

                <!-- Placeholder when no sticker -->
                <div
                  v-else
                  class="w-32 h-32 flex items-center justify-center bg-gradient-to-br from-wecom-dark to-wecom-darker"
                >
                  <span class="text-4xl">😀</span>
                </div>

                <!-- Loading indicator -->
                <div
                  v-if="isImageLoading(msg.id)"
                  class="absolute inset-0 flex items-center justify-center bg-black/30"
                >
                  <span class="text-white text-sm animate-pulse">Loading...</span>
                </div>

                <!-- No sticker file indicator -->
                <div
                  v-else-if="getImageInfo(msg.id) === null"
                  class="absolute inset-0 flex items-center justify-center bg-black/30"
                >
                  <span class="text-white/70 text-xs px-2 py-1 bg-black/50 rounded"
                    >No sticker file</span
                  >
                </div>

                <!-- Sticker badge -->
                <div
                  class="absolute top-2 left-2 px-2 py-0.5 bg-yellow-500/80 text-white text-xs rounded"
                >
                  表情包
                </div>

                <!-- Zoom hint on hover -->
                <div
                  v-if="getImageInfo(msg.id)?.image_id"
                  class="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/20 transition-colors"
                >
                  <span
                    class="text-white text-2xl opacity-0 group-hover:opacity-100 transition-opacity"
                    >🔍</span
                  >
                </div>
              </div>

              <div
                v-if="shouldShowAiReviewSection(msg)"
                class="text-xs mt-2 pt-2 border-t border-wecom-border space-y-0.5 text-left leading-snug text-wecom-muted"
                @click.stop
              >
                <template v-if="getAiReviewStatus(msg) === 'pending'">
                  <div class="font-medium text-wecom-text">正在等待图片审核</div>
                </template>
                <template v-else-if="getAiReviewStatus(msg) === 'timeout'">
                  <div class="font-medium text-yellow-400">图片审核超时</div>
                  <div v-if="getAiReviewErrorMessage(msg)" class="whitespace-pre-wrap opacity-90">
                    {{ getAiReviewErrorMessage(msg) }}
                  </div>
                </template>
                <template v-else-if="getAiReviewStatus(msg) === 'failed'">
                  <div class="font-medium text-red-400">图片审核失败</div>
                  <div v-if="getAiReviewErrorMessage(msg)" class="whitespace-pre-wrap opacity-90">
                    {{ getAiReviewErrorMessage(msg) }}
                  </div>
                </template>
                <div
                  v-if="getAiReviewStatus(msg) === 'completed' && msg.ai_review_score != null"
                  class="font-medium text-wecom-text"
                >
                  {{ t('sidecar.ai_review_score', undefined, 'AI 评分') }}:
                  {{ Number(msg.ai_review_score).toFixed(1) }}
                </div>
                <div
                  v-if="getAiReviewStatus(msg) === 'completed' && msg.ai_review_decision"
                  class="text-wecom-text opacity-90"
                >
                  {{ msg.ai_review_decision }}
                </div>
                <div
                  v-if="getAiReviewStatus(msg) === 'completed' && msg.ai_review_reason"
                  class="whitespace-pre-wrap opacity-90"
                >
                  {{ t('sidecar.ai_review_reason', undefined, '原因') }}:
                  {{ msg.ai_review_reason }}
                </div>
                <div
                  v-if="
                    getAiReviewStatus(msg) === 'completed' &&
                    msg.ai_review_score_reasons &&
                    msg.ai_review_score_reasons.length
                  "
                  class="space-y-1 pt-1"
                >
                  <div
                    v-for="item in msg.ai_review_score_reasons"
                    :key="`${msg.id}-${item.key}-st`"
                    class="whitespace-pre-wrap opacity-90"
                  >
                    {{ formatAiReviewLabel(item.label)
                    }}<template v-if="item.score"> ({{ item.score }})</template>:
                    {{ item.reason }}
                  </div>
                </div>
                <div
                  v-if="
                    getAiReviewStatus(msg) === 'completed' &&
                    msg.ai_review_penalties &&
                    msg.ai_review_penalties.length
                  "
                  class="space-y-1 pt-1"
                >
                  <div class="text-wecom-text opacity-90">
                    {{ t('sidecar.ai_review_penalties', undefined, '扣分项') }}:
                  </div>
                  <div
                    v-for="(penalty, index) in msg.ai_review_penalties"
                    :key="`${msg.id}-penalty-st-${index}`"
                    class="whitespace-pre-wrap pl-2 opacity-85"
                  >
                    - {{ penalty }}
                  </div>
                </div>
                <div
                  v-if="getAiReviewStatus(msg) === 'completed' && msg.ai_review_at"
                  class="opacity-70 text-[10px] font-mono"
                >
                  {{ msg.ai_review_at }}
                </div>
              </div>

              <!-- Content text (should not be shown for stickers usually) -->
              <p
                v-if="msg.content && msg.content !== '[表情包]'"
                class="text-wecom-text mt-2 text-sm"
              >
                {{ msg.content }}
              </p>
            </div>

            <!-- Voice message with play button -->
            <div v-else-if="msg.message_type === 'voice'" class="mt-2">
              <div
                class="inline-flex items-center gap-3 px-4 py-2 rounded-lg bg-wecom-darker border border-wecom-border"
                :class="
                  getVoiceInfo(msg.id)?.file_exists
                    ? 'cursor-pointer hover:border-wecom-primary group'
                    : 'opacity-60'
                "
                @click.stop="
                  getVoiceInfo(msg.id)?.file_exists
                    ? playVoice(msg.id, getVoiceInfo(msg.id)!)
                    : null
                "
              >
                <!-- Play/Stop button -->
                <div
                  class="w-10 h-10 rounded-full flex items-center justify-center transition-colors"
                  :class="
                    playingVoiceMessageId === msg.id
                      ? 'bg-red-500/80'
                      : 'bg-wecom-primary/80 group-hover:bg-wecom-primary'
                  "
                >
                  <!-- Stop icon when playing -->
                  <svg
                    v-if="playingVoiceMessageId === msg.id"
                    class="w-4 h-4 text-white"
                    fill="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <rect x="6" y="6" width="12" height="12" />
                  </svg>
                  <!-- Play icon when not playing -->
                  <svg
                    v-else
                    class="w-5 h-5 text-white ml-0.5"
                    fill="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path d="M8 5v14l11-7z" />
                  </svg>
                </div>

                <!-- Voice info -->
                <div class="min-w-[80px]">
                  <div v-if="getVoiceInfo(msg.id)?.file_exists" class="text-wecom-text text-sm">
                    {{ getVoiceInfo(msg.id)?.duration || 'Voice' }}
                    <span
                      v-if="playingVoiceMessageId === msg.id"
                      class="ml-2 text-wecom-accent animate-pulse"
                      >Playing...</span
                    >
                  </div>
                  <div
                    v-else-if="isVoiceLoading(msg.id)"
                    class="text-wecom-muted text-sm animate-pulse"
                  >
                    Loading...
                  </div>
                  <div v-else class="text-wecom-muted text-sm">No audio file</div>
                </div>

                <!-- Waveform visualization (static for now) -->
                <div v-if="getVoiceInfo(msg.id)?.file_exists" class="flex items-center gap-0.5 h-6">
                  <div
                    v-for="i in 12"
                    :key="i"
                    class="w-1 bg-wecom-primary/60 rounded-full transition-all duration-100"
                    :class="playingVoiceMessageId === msg.id ? 'animate-pulse' : ''"
                    :style="{ height: `${8 + Math.sin(i * 0.8) * 10}px` }"
                  ></div>
                </div>
              </div>

              <!-- Voice transcription text if available -->
              <p
                v-if="msg.content && msg.content !== '[Voice Message]'"
                class="text-wecom-text mt-2 text-sm"
              >
                {{ msg.content }}
              </p>
            </div>

            <!-- Regular text/other message content -->
            <p
              v-else
              class="text-wecom-text mt-1 whitespace-pre-wrap break-words"
              v-html="
                searchQuery
                  ? highlightSearchTerm(msg.content || '(no content)')
                  : msg.content || '(no content)'
              "
            ></p>

            <p v-if="msg.extra_info" class="text-xs text-wecom-muted mt-1">
              Meta: {{ msg.extra_info }}
            </p>
          </div>
        </div>
      </div>
    </div>

    <VideoReviewDetailPanel
      v-model="videoReviewModalOpen"
      :message-id="videoReviewMessageId"
      :frames-json="videoReviewFramesJson"
      :aggregate-score="videoReviewAggregateScore"
      :db-path="customerStore.lastFetchedPath"
    />

    <!-- Video Player Modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showVideoPlayer && playingVideoInfo"
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

          <!-- Video container -->
          <div class="max-w-[90vw] max-h-[85vh] flex flex-col items-center">
            <video
              v-if="playingVideoInfo.video_id"
              :key="playingVideoInfo.video_id"
              :src="getVideoUrl(playingVideoInfo.video_id)"
              controls
              autoplay
              class="max-w-full max-h-[75vh] rounded-lg shadow-2xl bg-black"
            >
              Your browser does not support the video tag.
            </video>

            <!-- Video info -->
            <div class="mt-4 text-center text-white">
              <p v-if="playingVideoInfo.duration" class="font-medium">
                Duration: {{ playingVideoInfo.duration }}
              </p>
              <p v-if="playingVideoInfo.file_name" class="text-sm text-white/70 mt-1">
                {{ playingVideoInfo.file_name }}
              </p>
              <p class="text-xs text-white/50 mt-1">
                {{ formatDate(playingVideoInfo.created_at) }}
              </p>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Image Viewer Modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showImageViewer && viewingImageInfo"
          class="fixed inset-0 bg-black/95 flex items-center justify-center z-50"
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

          <!-- Image container -->
          <div class="max-w-[90vw] max-h-[85vh] flex flex-col items-center">
            <img
              v-if="viewingImageInfo.image_id"
              :src="getImageUrl(viewingImageInfo.image_id)"
              :alt="viewingImageInfo.file_name || 'Image'"
              class="max-w-full max-h-[75vh] object-contain rounded-lg shadow-2xl"
            />

            <!-- Image info -->
            <div class="mt-4 text-center text-white">
              <p v-if="viewingImageInfo.file_name" class="font-medium">
                {{ viewingImageInfo.file_name }}
              </p>
              <p
                v-if="viewingImageInfo.width && viewingImageInfo.height"
                class="text-sm text-white/70 mt-1"
              >
                {{ viewingImageInfo.width }}×{{ viewingImageInfo.height }}
              </p>
              <p class="text-xs text-white/50 mt-1">
                {{ formatDate(viewingImageInfo.created_at) }}
              </p>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
</style>
