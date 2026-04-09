import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  api,
  type FilterAgent,
  type FilterDevice,
  type ImageDeletedInfo,
  type ImageResource,
  type ResourceFilters,
  type VideoDeletedInfo,
  type VideoResource,
  type VoiceDeletedInfo,
  type VoiceResource,
} from '../services/api'

// View mode type - persisted to localStorage
export type ViewMode = 'table' | 'gallery'

// Storage key for view preference
const VIEW_MODE_STORAGE_KEY = 'resources-view-mode'

export const useResourcesStore = defineStore('resources', () => {
  // ─────────────────────────────────────────────────────────────────────────
  // Common state
  // ─────────────────────────────────────────────────────────────────────────

  const lastFetchedPath = ref<string | null>(null)
  
  // View mode (persisted)
  const viewMode = ref<ViewMode>(
    (localStorage.getItem(VIEW_MODE_STORAGE_KEY) as ViewMode) || 'table'
  )

  function setViewMode(mode: ViewMode) {
    viewMode.value = mode
    localStorage.setItem(VIEW_MODE_STORAGE_KEY, mode)
  }

  // Filter options (shared across tabs)
  const filterOptions = ref<{
    streamers: string[]
    agents: FilterAgent[]
    devices: FilterDevice[]
  }>({
    streamers: [],
    agents: [],
    devices: [],
  })
  const filterOptionsLoading = ref(false)

  // Resource counts
  const resourceCounts = ref<{
    images: number
    voice: number
    videos: number
  }>({
    images: 0,
    voice: 0,
    videos: 0,
  })

  // ─────────────────────────────────────────────────────────────────────────
  // Images state
  // ─────────────────────────────────────────────────────────────────────────

  const images = ref<ImageResource[]>([])
  const imagesTotalCount = ref(0)
  const imagesLimit = ref(20)
  const imagesOffset = ref(0)
  const imagesFilters = ref<ResourceFilters>({})
  const imagesLoading = ref(false)
  const imagesError = ref<string | null>(null)
  const imagesDeleteLoading = ref(false)
  const imagesDeleteError = ref<string | null>(null)
  const lastDeletedImage = ref<ImageDeletedInfo | null>(null)

  const imagesPage = computed(() => Math.floor(imagesOffset.value / imagesLimit.value) + 1)
  const imagesTotalPages = computed(() =>
    imagesTotalCount.value === 0 ? 1 : Math.ceil(imagesTotalCount.value / imagesLimit.value)
  )

  // ─────────────────────────────────────────────────────────────────────────
  // Voice state
  // ─────────────────────────────────────────────────────────────────────────

  const voiceMessages = ref<VoiceResource[]>([])
  const voiceTotalCount = ref(0)
  const voiceLimit = ref(20)
  const voiceOffset = ref(0)
  const voiceFilters = ref<ResourceFilters>({})
  const voiceLoading = ref(false)
  const voiceError = ref<string | null>(null)
  const voiceDeleteLoading = ref(false)
  const voiceDeleteError = ref<string | null>(null)
  const lastDeletedVoice = ref<VoiceDeletedInfo | null>(null)
  // Transcription state - tracks which messages are being transcribed
  const voiceTranscribingIds = ref<Set<number>>(new Set())
  const voiceTranscribeError = ref<string | null>(null)

  const voicePage = computed(() => Math.floor(voiceOffset.value / voiceLimit.value) + 1)
  const voiceTotalPages = computed(() =>
    voiceTotalCount.value === 0 ? 1 : Math.ceil(voiceTotalCount.value / voiceLimit.value)
  )

  // ─────────────────────────────────────────────────────────────────────────
  // Video state
  // ─────────────────────────────────────────────────────────────────────────

  const videoMessages = ref<VideoResource[]>([])
  const videoTotalCount = ref(0)
  const videoLimit = ref(20)
  const videoOffset = ref(0)
  const videoFilters = ref<ResourceFilters>({})
  const videoLoading = ref(false)
  const videoError = ref<string | null>(null)
  const videoDeleteLoading = ref(false)
  const videoDeleteError = ref<string | null>(null)
  const lastDeletedVideo = ref<VideoDeletedInfo | null>(null)

  const videoPage = computed(() => Math.floor(videoOffset.value / videoLimit.value) + 1)
  const videoTotalPages = computed(() =>
    videoTotalCount.value === 0 ? 1 : Math.ceil(videoTotalCount.value / videoLimit.value)
  )

  // ─────────────────────────────────────────────────────────────────────────
  // Filter options actions
  // ─────────────────────────────────────────────────────────────────────────

  async function fetchFilterOptions() {
    filterOptionsLoading.value = true
    try {
      const result = await api.getResourceFilterOptions()
      filterOptions.value = {
        streamers: result.streamers,
        agents: result.agents,
        devices: result.devices,
      }
      resourceCounts.value = result.counts
      lastFetchedPath.value = result.db_path
    } catch (e) {
      console.error('Failed to load resource filter options:', e)
    } finally {
      filterOptionsLoading.value = false
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Images actions
  // ─────────────────────────────────────────────────────────────────────────

  async function fetchImages(options: {
    limit?: number
    offset?: number
    filters?: ResourceFilters
  } = {}) {
    if (options.limit !== undefined) imagesLimit.value = options.limit
    if (options.offset !== undefined) imagesOffset.value = options.offset
    if (options.filters !== undefined) imagesFilters.value = options.filters

    imagesLoading.value = true
    imagesError.value = null

    try {
      const result = await api.getImages({
        limit: imagesLimit.value,
        offset: imagesOffset.value,
        search: imagesFilters.value.search || undefined,
        streamer: imagesFilters.value.streamer || undefined,
        kefuId: imagesFilters.value.kefuId,
        deviceSerial: imagesFilters.value.deviceSerial || undefined,
        dateFrom: imagesFilters.value.dateFrom || undefined,
        dateTo: imagesFilters.value.dateTo || undefined,
        sortBy: imagesFilters.value.sortBy || undefined,
        sortOrder: imagesFilters.value.sortOrder || undefined,
      })
      images.value = result.items
      imagesTotalCount.value = result.total
      imagesLimit.value = result.limit
      imagesOffset.value = result.offset
      lastFetchedPath.value = result.db_path
    } catch (e) {
      imagesError.value = e instanceof Error ? e.message : 'Failed to load images'
    } finally {
      imagesLoading.value = false
    }
  }

  async function deleteImage(imageId: number): Promise<ImageDeletedInfo> {
    imagesDeleteLoading.value = true
    imagesDeleteError.value = null
    lastDeletedImage.value = null

    try {
      const result = await api.deleteImage(imageId)
      lastDeletedImage.value = result.deleted

      // Remove from local list
      images.value = images.value.filter(i => i.id !== imageId)
      imagesTotalCount.value = Math.max(0, imagesTotalCount.value - 1)

      return result.deleted
    } catch (e) {
      imagesDeleteError.value = e instanceof Error ? e.message : 'Failed to delete image'
      throw e
    } finally {
      imagesDeleteLoading.value = false
    }
  }

  function setImagesPage(newPage: number) {
    const clamped = Math.max(1, newPage)
    imagesOffset.value = (clamped - 1) * imagesLimit.value
    return fetchImages()
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Voice actions
  // ─────────────────────────────────────────────────────────────────────────

  async function fetchVoiceMessages(options: {
    limit?: number
    offset?: number
    filters?: ResourceFilters
  } = {}) {
    if (options.limit !== undefined) voiceLimit.value = options.limit
    if (options.offset !== undefined) voiceOffset.value = options.offset
    if (options.filters !== undefined) voiceFilters.value = options.filters

    voiceLoading.value = true
    voiceError.value = null

    try {
      const result = await api.getVoiceMessages({
        limit: voiceLimit.value,
        offset: voiceOffset.value,
        search: voiceFilters.value.search || undefined,
        streamer: voiceFilters.value.streamer || undefined,
        kefuId: voiceFilters.value.kefuId,
        deviceSerial: voiceFilters.value.deviceSerial || undefined,
        dateFrom: voiceFilters.value.dateFrom || undefined,
        dateTo: voiceFilters.value.dateTo || undefined,
        sortBy: voiceFilters.value.sortBy || undefined,
        sortOrder: voiceFilters.value.sortOrder || undefined,
      })
      voiceMessages.value = result.items
      voiceTotalCount.value = result.total
      voiceLimit.value = result.limit
      voiceOffset.value = result.offset
      lastFetchedPath.value = result.db_path
    } catch (e) {
      voiceError.value = e instanceof Error ? e.message : 'Failed to load voice messages'
    } finally {
      voiceLoading.value = false
    }
  }

  async function deleteVoiceMessage(messageId: number): Promise<VoiceDeletedInfo> {
    voiceDeleteLoading.value = true
    voiceDeleteError.value = null
    lastDeletedVoice.value = null

    try {
      const result = await api.deleteVoiceMessage(messageId)
      lastDeletedVoice.value = result.deleted

      // Remove from local list
      voiceMessages.value = voiceMessages.value.filter(v => v.id !== messageId)
      voiceTotalCount.value = Math.max(0, voiceTotalCount.value - 1)

      return result.deleted
    } catch (e) {
      voiceDeleteError.value = e instanceof Error ? e.message : 'Failed to delete voice message'
      throw e
    } finally {
      voiceDeleteLoading.value = false
    }
  }

  async function transcribeVoiceMessage(messageId: number): Promise<string> {
    voiceTranscribingIds.value.add(messageId)
    voiceTranscribeError.value = null

    try {
      const result = await api.transcribeVoiceMessage(messageId)
      
      // Update the content in the local list
      const voiceMessage = voiceMessages.value.find(v => v.id === messageId)
      if (voiceMessage && result.transcription) {
        voiceMessage.content = result.transcription
      }

      return result.transcription || ''
    } catch (e) {
      voiceTranscribeError.value = e instanceof Error ? e.message : 'Failed to transcribe voice message'
      throw e
    } finally {
      voiceTranscribingIds.value.delete(messageId)
    }
  }

  function isVoiceTranscribing(messageId: number): boolean {
    return voiceTranscribingIds.value.has(messageId)
  }

  function setVoicePage(newPage: number) {
    const clamped = Math.max(1, newPage)
    voiceOffset.value = (clamped - 1) * voiceLimit.value
    return fetchVoiceMessages()
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Video actions
  // ─────────────────────────────────────────────────────────────────────────

  async function fetchVideoMessages(options: {
    limit?: number
    offset?: number
    filters?: ResourceFilters
  } = {}) {
    if (options.limit !== undefined) videoLimit.value = options.limit
    if (options.offset !== undefined) videoOffset.value = options.offset
    if (options.filters !== undefined) videoFilters.value = options.filters

    videoLoading.value = true
    videoError.value = null

    try {
      const result = await api.getVideoMessages({
        limit: videoLimit.value,
        offset: videoOffset.value,
        search: videoFilters.value.search || undefined,
        streamer: videoFilters.value.streamer || undefined,
        kefuId: videoFilters.value.kefuId,
        deviceSerial: videoFilters.value.deviceSerial || undefined,
        dateFrom: videoFilters.value.dateFrom || undefined,
        dateTo: videoFilters.value.dateTo || undefined,
        sortBy: videoFilters.value.sortBy || undefined,
        sortOrder: videoFilters.value.sortOrder || undefined,
      })
      videoMessages.value = result.items
      videoTotalCount.value = result.total
      videoLimit.value = result.limit
      videoOffset.value = result.offset
      lastFetchedPath.value = result.db_path
    } catch (e) {
      videoError.value = e instanceof Error ? e.message : 'Failed to load video messages'
    } finally {
      videoLoading.value = false
    }
  }

  async function deleteVideoMessage(messageId: number): Promise<VideoDeletedInfo> {
    videoDeleteLoading.value = true
    videoDeleteError.value = null
    lastDeletedVideo.value = null

    try {
      const result = await api.deleteVideoMessage(messageId)
      lastDeletedVideo.value = result.deleted

      // Remove from local list
      videoMessages.value = videoMessages.value.filter(v => v.id !== messageId)
      videoTotalCount.value = Math.max(0, videoTotalCount.value - 1)

      return result.deleted
    } catch (e) {
      videoDeleteError.value = e instanceof Error ? e.message : 'Failed to delete video message'
      throw e
    } finally {
      videoDeleteLoading.value = false
    }
  }

  function setVideoPage(newPage: number) {
    const clamped = Math.max(1, newPage)
    videoOffset.value = (clamped - 1) * videoLimit.value
    return fetchVideoMessages()
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Return all state and actions
  // ─────────────────────────────────────────────────────────────────────────

  return {
    // Common
    lastFetchedPath,
    viewMode,
    setViewMode,
    filterOptions,
    filterOptionsLoading,
    resourceCounts,
    fetchFilterOptions,

    // Images
    images,
    imagesTotalCount,
    imagesLimit,
    imagesOffset,
    imagesFilters,
    imagesLoading,
    imagesError,
    imagesDeleteLoading,
    imagesDeleteError,
    lastDeletedImage,
    imagesPage,
    imagesTotalPages,
    fetchImages,
    deleteImage,
    setImagesPage,

    // Voice
    voiceMessages,
    voiceTotalCount,
    voiceLimit,
    voiceOffset,
    voiceFilters,
    voiceLoading,
    voiceError,
    voiceDeleteLoading,
    voiceDeleteError,
    lastDeletedVoice,
    voicePage,
    voiceTotalPages,
    voiceTranscribingIds,
    voiceTranscribeError,
    fetchVoiceMessages,
    deleteVoiceMessage,
    transcribeVoiceMessage,
    isVoiceTranscribing,
    setVoicePage,

    // Video
    videoMessages,
    videoTotalCount,
    videoLimit,
    videoOffset,
    videoFilters,
    videoLoading,
    videoError,
    videoDeleteLoading,
    videoDeleteError,
    lastDeletedVideo,
    videoPage,
    videoTotalPages,
    fetchVideoMessages,
    deleteVideoMessage,
    setVideoPage,
  }
})


