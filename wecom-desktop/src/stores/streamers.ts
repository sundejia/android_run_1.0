import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, type StreamerDeletedInfo } from '../services/api'

// Streamer profile - extensible design for future fields
export interface StreamerProfile {
  name: string | null
  gender: string | null
  age: number | null
  location: string | null
  height: number | null
  weight: number | null
  education: string | null
  occupation: string | null
  interests: string[] | null
  social_platforms: string[] | null
  notes: string | null
  custom_fields: Record<string, unknown> | null
  updated_at: string | null
}

// Persona dimension for radar chart
export interface PersonaDimension {
  name: string
  value: number  // 0-100
  description: string | null
}

// Streamer persona analysis result
export interface StreamerPersona {
  id: number
  streamer_id: number
  communication_style: string | null
  language_patterns: string[] | null
  tone: string | null
  engagement_level: string | null
  response_time_pattern: string | null
  active_hours: string[] | null
  topics_of_interest: string[] | null
  personality_traits: string[] | null
  dimensions: PersonaDimension[]
  analysis_summary: string | null
  recommendations: string[] | null
  analyzed_at: string | null
  analyzed_messages_count: number
  model_used: string | null
}

// Unique streamer (grouped by name + avatar)
export interface StreamerSummary {
  id: string  // Hash of name + avatar_url for uniqueness
  name: string
  avatar_url: string | null
  conversation_count: number
  total_messages: number
  first_seen: string
  last_seen: string
  agents: string[]  // List of agent names who talked to this streamer
  channels: string[]  // List of channels
  profile: StreamerProfile | null
  has_persona: boolean
}

// Conversation for a specific streamer
export interface StreamerConversation {
  id: number  // Customer ID
  agent_name: string
  agent_department: string | null
  device_serial: string
  channel: string | null
  message_count: number
  last_message_at: string | null
  last_message_preview: string | null
}

// Detailed streamer data
export interface StreamerDetail {
  id: string
  name: string
  avatar_url: string | null
  profile: StreamerProfile
  conversations: StreamerConversation[]
  persona: StreamerPersona | null
  total_messages: number
  first_interaction: string | null
  last_interaction: string | null
}

export interface StreamerListResponse {
  total: number
  limit: number
  offset: number
  items: StreamerSummary[]
}

export interface StreamerDetailResponse {
  streamer: StreamerDetail
  db_path: string
}

export const useStreamerStore = defineStore('streamers', () => {
  // List state
  const streamers = ref<StreamerSummary[]>([])
  const total = ref(0)
  const limit = ref(20)
  const offset = ref(0)
  const search = ref('')
  const listLoading = ref(false)
  const listError = ref<string | null>(null)

  // Detail state
  const selectedStreamer = ref<StreamerDetail | null>(null)
  const detailLoading = ref(false)
  const detailError = ref<string | null>(null)

  // Persona analysis state
  const personaAnalyzing = ref(false)
  const personaError = ref<string | null>(null)

  // Delete state
  const deleteLoading = ref(false)
  const deleteError = ref<string | null>(null)
  const lastDeletedStreamer = ref<StreamerDeletedInfo | null>(null)

  const page = computed(() => Math.floor(offset.value / limit.value) + 1)
  const totalPages = computed(() =>
    total.value === 0 ? 1 : Math.ceil(total.value / limit.value),
  )

  async function fetchStreamers(options: {
    search?: string
    limit?: number
    offset?: number
  } = {}) {
    if (options.search !== undefined) search.value = options.search
    if (options.limit !== undefined) limit.value = options.limit
    if (options.offset !== undefined) offset.value = options.offset

    listLoading.value = true
    listError.value = null

    try {
      const params = new URLSearchParams()
      if (search.value) params.append('search', search.value)
      params.append('limit', limit.value.toString())
      params.append('offset', offset.value.toString())

      const response = await fetch(
        `http://localhost:8765/streamers?${params.toString()}`
      )
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${await response.text()}`)
      }

      const result: StreamerListResponse = await response.json()
      streamers.value = result.items
      total.value = result.total
      limit.value = result.limit
      offset.value = result.offset
    } catch (e) {
      listError.value = e instanceof Error ? e.message : 'Failed to load streamers'
    } finally {
      listLoading.value = false
    }
  }

  async function fetchStreamerDetail(streamerId: string) {
    detailLoading.value = true
    detailError.value = null
    selectedStreamer.value = null

    try {
      const response = await fetch(
        `http://localhost:8765/streamers/${encodeURIComponent(streamerId)}`
      )
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${await response.text()}`)
      }

      const result: StreamerDetailResponse = await response.json()
      selectedStreamer.value = result.streamer
      return result
    } catch (e) {
      detailError.value =
        e instanceof Error ? e.message : 'Failed to load streamer details'
      throw e
    } finally {
      detailLoading.value = false
    }
  }

  async function updateStreamerProfile(
    streamerId: string,
    profile: Partial<StreamerProfile>
  ) {
    try {
      const response = await fetch(
        `http://localhost:8765/streamers/${encodeURIComponent(streamerId)}/profile`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(profile),
        }
      )
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${await response.text()}`)
      }

      // Refresh the detail to get updated data
      await fetchStreamerDetail(streamerId)
    } catch (e) {
      throw new Error(
        e instanceof Error ? e.message : 'Failed to update profile'
      )
    }
  }

  async function analyzePersona(streamerId: string) {
    personaAnalyzing.value = true
    personaError.value = null

    try {
      const response = await fetch(
        `http://localhost:8765/streamers/${encodeURIComponent(streamerId)}/analyze-persona`,
        { method: 'POST' }
      )
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${await response.text()}`)
      }

      // Refresh the detail to get the new persona
      await fetchStreamerDetail(streamerId)
    } catch (e) {
      personaError.value =
        e instanceof Error ? e.message : 'Failed to analyze persona'
      throw e
    } finally {
      personaAnalyzing.value = false
    }
  }

  function setPage(newPage: number) {
    const clamped = Math.max(1, newPage)
    offset.value = (clamped - 1) * limit.value
    return fetchStreamers()
  }

  async function deleteStreamer(streamerId: string): Promise<StreamerDeletedInfo> {
    deleteLoading.value = true
    deleteError.value = null
    lastDeletedStreamer.value = null

    try {
      const result = await api.deleteStreamer(streamerId)
      lastDeletedStreamer.value = result.deleted
      
      // Remove the deleted streamer from the local list
      streamers.value = streamers.value.filter(s => s.id !== streamerId)
      total.value = Math.max(0, total.value - 1)
      
      return result.deleted
    } catch (e) {
      deleteError.value = e instanceof Error ? e.message : 'Failed to delete streamer'
      throw e
    } finally {
      deleteLoading.value = false
    }
  }

  return {
    // List state
    streamers,
    total,
    limit,
    offset,
    search,
    listLoading,
    listError,
    page,
    totalPages,
    
    // Detail state
    selectedStreamer,
    detailLoading,
    detailError,
    
    // Persona state
    personaAnalyzing,
    personaError,
    
    // Delete state
    deleteLoading,
    deleteError,
    lastDeletedStreamer,
    
    // Actions
    fetchStreamers,
    fetchStreamerDetail,
    updateStreamerProfile,
    analyzePersona,
    setPage,
    deleteStreamer,
  }
})
