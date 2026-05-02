export const API_BASE = 'http://localhost:8765'

export interface DeviceKefu {
  name: string
  department?: string | null
  verification_status?: string | null
}

export interface Device {
  serial: string
  state: string
  product: string | null
  model: string | null
  device: string | null
  transport_id?: number | null
  usb?: string | null
  features?: string | null
  manufacturer: string | null
  brand?: string | null
  android_version: string | null
  sdk_version?: string | null
  security_patch?: string | null
  build_id?: string | null
  hardware?: string | null
  abi?: string | null
  battery_level: string | null
  battery_status?: string | null
  screen_resolution: string | null
  screen_density?: string | null
  memory_total?: string | null
  usb_debugging?: boolean | null
  wifi_mac?: string | null
  internal_storage?: string | null
  connection_type?: string | null
  ip_address?: string | null
  tcp_port?: number | null
  endpoint?: string | null
  extra_props?: Record<string, string>
  is_online: boolean
  // Kefu info (populated after initialization)
  kefu?: DeviceKefu | null
}

export interface InitDeviceResponse {
  success: boolean
  kefu?: DeviceKefu | null
  wecom_launched: boolean
  error?: string | null
}

export interface SyncStatus {
  status: 'idle' | 'starting' | 'running' | 'paused' | 'completed' | 'error' | 'stopped'
  progress: number
  message: string
  customers_synced?: number
  messages_added?: number
  errors?: string[]
}

export interface SyncOptions {
  db_path?: string
  images_dir?: string
  timing_multiplier?: number
  auto_placeholder?: boolean
  no_test_messages?: boolean
  send_via_sidecar?: boolean
  countdown_seconds?: number
  // AI Reply settings
  use_ai_reply?: boolean
  ai_server_url?: string
  ai_reply_timeout?: number
  system_prompt?: string // System prompt for AI behavior
  // Resume functionality
  resume?: boolean // Resume from last checkpoint if available
}

// ==========================================================================
// AI Learning Types (Admin Action Recording)
// ==========================================================================

export interface RecordAdminActionRequest {
  message_id: string
  action_type: 'EDIT' | 'CANCEL' | 'APPROVE'
  original_content: string
  modified_content?: string
  reason?: string
  admin_id?: string
  serial?: string
  customer_name?: string
}

export interface DashboardOverview {
  db_path: string
  last_updated: string | null
  stats: {
    devices: number
    kefus: number
    customers: number
    messages: number
    images: number
    messages_by_type: Record<string, number>
  }
  devices: Array<{
    id: number
    serial: string
    model: string | null
    manufacturer: string | null
    android_version: string | null
    created_at: string
    updated_at: string
    kefu_count: number
    customer_count: number
    message_count: number
    sent_by_kefu: number
    sent_by_customer: number
    last_message_at: string | null
  }>
  kefus: Array<{
    id: number
    name: string
    department: string | null
    verification_status: string | null
    device_id: number
    device_serial: string
    device_model: string | null
    customer_count: number
    message_count: number
    sent_by_kefu: number
    sent_by_customer: number
    last_message_at: string | null
    last_customer_name: string | null
    last_customer_channel: string | null
    last_message_preview: string | null
    last_message_date: string | null
    created_at: string
    updated_at: string
  }>
  recent_conversations: Array<{
    id: number
    name: string
    channel: string | null
    last_message_preview: string | null
    last_message_date: string | null
    updated_at: string
    created_at: string
    kefu_id: number
    kefu_name: string
    device_serial: string
    device_model: string | null
    message_count: number
    sent_by_kefu: number
    sent_by_customer: number
    last_message_at: string | null
  }>
}

// Time series data for charts
export interface TimeseriesDataPoint {
  time: string
  total: number
  outgoing: number
  incoming: number
}

export interface MessageTimeseriesResponse {
  db_path: string
  overall: TimeseriesDataPoint[]
  by_kefu: Record<number, TimeseriesDataPoint[]>
  kefu_names: Record<number, string>
  granularity: string
}

export interface KefuSummary {
  id: number
  name: string
  department: string | null
  verification_status: string | null
  device_id: number
  device_serial: string
  device_model: string | null
  customer_count: number
  message_count: number
  sent_by_kefu: number
  sent_by_customer: number
  last_message_at: string | null
  last_customer_name: string | null
  last_customer_channel: string | null
  last_message_preview: string | null
  last_message_date: string | null
  created_at: string
  updated_at: string
  // Devices associated with this kefu (for displaying in list view)
  devices?: Array<{
    serial: string
    model: string | null
  }>
}

export interface KefuListResponse {
  db_path: string
  total: number
  limit: number
  offset: number
  items: KefuSummary[]
}

export interface CustomerSummary {
  id: number
  name: string
  channel: string | null
  kefu_id: number
  kefu_name: string
  kefu_department: string | null
  kefu_verification_status: string | null
  device_serial: string
  device_model: string | null
  last_message_preview: string | null
  last_message_date: string | null
  last_message_at: string | null
  message_count: number
  sent_by_kefu: number
  sent_by_customer: number
  created_at: string
  updated_at: string
}

export interface CustomerListResponse {
  db_path: string
  total: number
  limit: number
  offset: number
  items: CustomerSummary[]
}

export interface FilterAgent {
  id: number
  name: string
  department: string | null
}

export interface FilterDevice {
  serial: string
  model: string | null
}

export interface CustomerFilterOptions {
  db_path: string
  streamers: string[]
  agents: FilterAgent[]
  devices: FilterDevice[]
}

export interface CustomerMessage {
  id: number
  content: string | null
  message_type: string
  is_from_kefu: boolean
  timestamp_raw: string | null
  timestamp_parsed: string | null
  extra_info: string | null
  created_at: string
  /** From joined `images` row — same contract as Sidecar conversation history */
  ai_review_score?: number | null
  ai_review_decision?: string | null
  ai_review_reason?: string | null
  ai_review_score_reasons?: Array<{
    key: string
    label: string
    score: string
    reason: string
  }>
  ai_review_penalties?: string[]
  ai_review_at?: string | null
  ai_review_status?: 'pending' | 'completed' | 'timeout' | 'failed' | null
  ai_review_error?: string | null
  ai_review_requested_at?: string | null
  /** From joined `videos` row — multi-frame video AI review */
  video_ai_review_score?: number | null
  video_ai_review_status?: string | null
  video_ai_review_error?: string | null
  video_ai_review_requested_at?: string | null
  video_ai_review_at?: string | null
  video_ai_review_frames_json?: string | null
}

export interface CustomerDetailResponse {
  db_path: string
  customer: CustomerSummary
  messages: CustomerMessage[]
  message_breakdown: Record<string, number>
}

export interface MessageSearchResult {
  message_id: number
  content: string | null
  content_preview: string
  match_position: number
  message_type: string
  is_from_kefu: boolean
  timestamp: string | null
  customer_id: number
  customer_name: string
  customer_channel: string | null
  kefu_name: string
  kefu_department: string | null
  device_serial: string
}

export interface MessageSearchResponse {
  db_path: string
  query: string
  total: number
  results: MessageSearchResult[]
}

export interface KefuDetailResponse {
  db_path: string
  kefu: KefuSummary
  customers: CustomerSummary[]
  customers_total: number
  message_breakdown: Record<string, number>
}

export interface KefuDeletedInfo {
  kefu_id: number
  kefu_name: string
  department: string | null
  device_links_removed: number
  customers_removed: number
  messages_removed: number
}

export interface KefuDeleteResponse {
  success: boolean
  message: string
  deleted: KefuDeletedInfo
  db_path: string
}

export interface CustomerDeletedInfo {
  customer_id: number
  customer_name: string
  channel: string | null
  kefu_name: string
  messages_removed: number
  images_removed: number
}

export interface CustomerDeleteResponse {
  success: boolean
  message: string
  deleted: CustomerDeletedInfo
  db_path: string
}

export interface StreamerDeletedInfo {
  streamer_id: string
  streamer_name: string
  conversations_removed: number
  messages_removed: number
  profile_removed: boolean
  personas_removed: number
}

export interface StreamerDeleteResponse {
  success: boolean
  message: string
  deleted: StreamerDeletedInfo
  db_path: string
}

export interface SidecarConversation {
  contact_name: string | null
  channel: string | null
}

export interface SidecarKefu {
  name: string
  department?: string | null
  verification_status?: string | null
}

export interface SidecarState {
  in_conversation: boolean
  tree_hash?: string | null
  focused_text?: string | null
  kefu?: SidecarKefu | null
  conversation?: SidecarConversation | null
}

export interface LastMessageInfo {
  is_from_kefu: boolean
  content: string | null
  message_type: string
}

export interface LastMessageResponse {
  success: boolean
  last_message: LastMessageInfo | null
  error?: string
}

export interface SendMessageResponse {
  success: boolean
  detail?: string
}

export type MessageStatus = 'pending' | 'ready' | 'sending' | 'sent' | 'failed' | 'cancelled'

export interface QueuedMessage {
  id: string
  serial: string
  customerName: string
  channel: string | null
  message: string
  timestamp: number
  status: MessageStatus
  error?: string
  source: 'manual' | 'sync' | 'followup' // Message source
}

export interface SyncQueueState {
  paused: boolean
  currentMessageId: string | null
  totalMessages: number
  processedMessages: number
}

export interface QueueStateResponse {
  queue: QueuedMessage[]
  syncState: SyncQueueState | null
}

export interface AddMessageRequest {
  customerName: string
  channel?: string | null
  message: string
  source?: 'manual' | 'sync' | 'followup' // Message source
}

export interface WaitForSendResponse {
  success: boolean
  reason: 'sent' | 'failed' | 'cancelled' | 'timeout' | 'not_found'
  error?: string
}

export interface ConversationHistoryMessage {
  id: number
  content: string | null
  message_type: string
  is_from_kefu: boolean
  timestamp_raw: string | null
  timestamp_parsed: string | null
  extra_info: string | null
  created_at: string
  // Image fields for displaying images in Sidecar
  image_url?: string | null
  image_width?: number | null
  image_height?: number | null
  // AI image review (image-rating-server → local images table)
  ai_review_score?: number | null
  ai_review_decision?: string | null
  ai_review_reason?: string | null
  ai_review_score_reasons?: Array<{
    key: string
    label: string
    score: string
    reason: string
  }>
  ai_review_penalties?: string[]
  ai_review_at?: string | null
  ai_review_status?: 'pending' | 'completed' | 'timeout' | 'failed' | null
  ai_review_error?: string | null
  ai_review_requested_at?: string | null
  // Video fields for Sidecar playback
  video_id?: number | null
  video_duration?: string | null
  video_ai_review_score?: number | null
  video_ai_review_status?: string | null
  video_ai_review_error?: string | null
  video_ai_review_requested_at?: string | null
  video_ai_review_at?: string | null
  video_ai_review_frames_json?: string | null
}

export interface ConversationHistoryResponse {
  success: boolean
  customer_id?: number | null
  customer_name?: string | null
  channel?: string | null
  kefu_name?: string | null
  messages: ConversationHistoryMessage[]
  total_messages: number
  error?: string | null
  /** Absolute DB path used by the backend for this history (pass to review-frame URLs when non-default). */
  db_path?: string | null
}

// Resource types
export interface ImageResource {
  id: number
  message_id: number
  file_path: string
  file_name: string | null
  original_bounds: string | null
  width: number | null
  height: number | null
  file_size: number | null
  created_at: string
  customer_id: number
  message_content: string | null
  is_from_kefu: boolean
  message_timestamp: string | null
  streamer_name: string
  channel: string | null
  kefu_id: number
  kefu_name: string
  kefu_department: string | null
  device_serial: string
  device_model: string | null
}

export interface ImageListResponse {
  db_path: string
  total: number
  limit: number
  offset: number
  items: ImageResource[]
}

export interface ImageDetailResponse {
  db_path: string
  image: ImageResource & {
    timestamp_raw: string | null
    extra_info: string | null
  }
}

export interface ImageDeletedInfo {
  image_id: number
  file_path: string
  file_name: string | null
  streamer_name: string
  channel: string | null
  customer_id: number
}

export interface ImageDeleteResponse {
  success: boolean
  message: string
  deleted: ImageDeletedInfo
  db_path: string
}

export interface VoiceResource {
  id: number
  customer_id: number
  content: string | null
  is_from_kefu: boolean
  timestamp_raw: string | null
  timestamp_parsed: string | null
  extra_info: string | null
  created_at: string
  streamer_name: string
  channel: string | null
  kefu_id: number
  kefu_name: string
  kefu_department: string | null
  device_serial: string
  device_model: string | null
  // Voice-specific fields parsed from extra_info
  voice_duration: string | null
  voice_file_path: string | null
  voice_file_size: number | null
  voice_file_exists: boolean
}

export interface VoiceListResponse {
  db_path: string
  total: number
  limit: number
  offset: number
  items: VoiceResource[]
}

export interface VoiceDeletedInfo {
  message_id: number
  content: string | null
  is_from_kefu: boolean
  streamer_name: string
  channel: string | null
  customer_id: number
}

export interface VoiceDeleteResponse {
  success: boolean
  message: string
  deleted: VoiceDeletedInfo
  db_path: string
}

export interface VoiceTranscribeResponse {
  success: boolean
  message_id: number
  transcription: string | null
  db_path: string
  error?: string
}

export interface VolcengineAsrSettings {
  enabled: boolean
  api_key: string
  resource_id: string
}

export interface VideoResource {
  id: number
  customer_id: number
  content: string | null
  is_from_kefu: boolean
  timestamp_raw: string | null
  timestamp_parsed: string | null
  extra_info: string | null
  created_at: string
  streamer_name: string
  channel: string | null
  kefu_id: number
  kefu_name: string
  kefu_department: string | null
  device_serial: string
  device_model: string | null
  // Video file info (from videos table join)
  video_id: number | null
  video_file_path: string | null
  video_file_name: string | null
  video_duration: string | null
  duration_seconds: number | null
  video_file_size: number | null
  thumbnail_path: string | null
}

export interface VideoListResponse {
  db_path: string
  total: number
  limit: number
  offset: number
  items: VideoResource[]
}

export interface VideoDeletedInfo {
  message_id: number
  content: string | null
  is_from_kefu: boolean
  streamer_name: string
  channel: string | null
  customer_id: number
}

export interface VideoDeleteResponse {
  success: boolean
  message: string
  deleted: VideoDeletedInfo
  db_path: string
}

// Video info for a specific message (used in conversation detail)
export interface VideoInfo {
  video_id: number
  message_id: number
  file_path: string
  file_name: string | null
  duration: string | null
  duration_seconds: number | null
  thumbnail_path: string | null
  width: number | null
  height: number | null
  file_size: number | null
  created_at: string
  ai_review_score?: number | null
  ai_review_frames_json?: string | null
  ai_review_at?: string | null
  ai_review_status?: string | null
  ai_review_error?: string | null
  ai_review_requested_at?: string | null
}

export interface VideoByMessageResponse {
  db_path: string
  video: VideoInfo | null
}

// Image info for a specific message (used in conversation detail)
export interface ImageInfo {
  image_id: number
  message_id: number
  file_path: string
  file_name: string | null
  original_bounds: string | null
  width: number | null
  height: number | null
  file_size: number | null
  created_at: string
}

export interface ImageByMessageResponse {
  db_path: string
  image: ImageInfo | null
}

// Voice info for a specific message (used in conversation detail)
export interface VoiceInfo {
  message_id: number
  customer_id: number
  content: string | null
  is_from_kefu: boolean
  created_at: string
  streamer_name: string
  channel: string | null
  duration: string | null
  file_path: string | null
  file_size: number | null
  file_exists: boolean
}

export interface VoiceByMessageResponse {
  db_path: string
  message_id: number
  voice: VoiceInfo | null
}

export interface ResourceFilterOptions {
  db_path: string
  streamers: string[]
  agents: FilterAgent[]
  devices: FilterDevice[]
  counts: {
    images: number
    voice: number
    videos: number
  }
}

export interface ResourceFilters {
  search?: string
  streamer?: string
  kefuId?: number
  deviceSerial?: string
  dateFrom?: string
  dateTo?: string
  sortBy?: string
  sortOrder?: 'asc' | 'desc'
}

// ==========================================================================
// Blacklist System Types
// ==========================================================================

export interface BlacklistEntry {
  id: number
  device_serial: string
  customer_name: string
  customer_channel?: string
  reason?: string
  deleted_by_user?: boolean
  is_blacklisted?: boolean
  avatar_url?: string
  created_at: string
  updated_at: string
}

export interface CustomerWithBlacklistStatus {
  customer_name: string
  customer_channel?: string | null
  is_blacklisted: boolean
  blacklist_reason?: string | null
  deleted_by_user?: boolean
  last_message_at?: string | null
  message_count: number
}

export interface BlacklistAddRequest {
  device_serial: string
  customer_name: string
  customer_channel?: string
  reason?: string
  deleted_by_user?: boolean
}

export interface BlacklistRemoveRequest {
  device_serial: string
  customer_name: string
  customer_channel?: string
}

export interface BlacklistUpdateRequest {
  id: number
  is_blacklisted: boolean
}

export interface BlacklistCheckRequest {
  device_serial: string
  customer_name: string
  customer_channel?: string
}

export interface BlacklistCheckResponse {
  is_blacklisted: boolean
  reason?: string | null
}

export interface BlacklistToggleResponse {
  success: boolean
  message: string
  is_blacklisted: boolean
}

export interface BatchUpdateStatusRequest {
  ids: number[]
  is_blacklisted: boolean
}

export interface ScannedUser {
  customer_name: string
  customer_channel?: string
  avatar_url?: string
  reason?: string
}

export interface UpsertScannedUsersRequest {
  device_serial: string
  users: ScannedUser[]
}

export interface BlacklistCopyRequest {
  source_device_serial: string
  target_device_serial: string
  include_allowed?: boolean
  overwrite_existing?: boolean
}

export interface BlacklistCopyResponse {
  success: boolean
  copied_count: number
  updated_count: number
  skipped_count: number
  total_source_entries: number
  message: string
}

// ==========================================================================
// Media Auto-Actions Types
// ==========================================================================

export interface AutoBlacklistSettings {
  enabled: boolean
  reason: string
  skip_if_already_blacklisted: boolean
}

export interface AutoGroupInviteSettings {
  enabled: boolean
  group_members: string[]
  group_name_template: string
  skip_if_group_exists: boolean
  member_source?: string
  send_test_message_after_create: boolean
  test_message_text: string
  post_confirm_wait_seconds: number
  duplicate_name_policy: string
}

export interface AutoContactShareSettings {
  enabled: boolean
  contact_name: string
  skip_if_already_shared: boolean
  cooldown_seconds: number
  kefu_overrides: Record<string, string>
}

export interface MediaAutoActionSettings {
  enabled: boolean
  auto_blacklist: AutoBlacklistSettings
  auto_group_invite: AutoGroupInviteSettings
  auto_contact_share: AutoContactShareSettings
}

export interface MediaActionLogEntry {
  id: number
  device_serial: string
  customer_name: string
  action_name: string
  status: string
  message: string
  details?: Record<string, any>
  created_at: string
}

class ApiClient {
  private baseUrl: string

  constructor(baseUrl: string = API_BASE) {
    this.baseUrl = baseUrl
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`

    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
      throw new Error(error.detail || `HTTP ${response.status}`)
    }

    return response.json()
  }

  // Device endpoints
  async getDevices(): Promise<Device[]> {
    return this.request<Device[]>('/devices')
  }

  async getDevice(serial: string): Promise<Device> {
    return this.request<Device>(`/devices/${serial}`)
  }

  async refreshDevices(): Promise<Device[]> {
    return this.request<Device[]>('/devices/refresh', { method: 'POST' })
  }

  async initDevice(serial: string, launchWecom: boolean = true): Promise<InitDeviceResponse> {
    const params = new URLSearchParams()
    params.append('launch_wecom', launchWecom.toString())
    return this.request<InitDeviceResponse>(`/devices/${serial}/init?${params.toString()}`, {
      method: 'POST',
    })
  }

  async clearKefuCache(serial: string): Promise<{ success: boolean; message: string }> {
    return this.request(`/devices/${serial}/kefu-cache`, { method: 'DELETE' })
  }

  // Sync endpoints
  async startSync(serials: string[], options: SyncOptions = {}): Promise<{ message: string }> {
    return this.request('/sync/start', {
      method: 'POST',
      body: JSON.stringify({ serials, options }),
    })
  }

  async stopSync(serial: string): Promise<{ message: string }> {
    return this.request(`/sync/stop/${serial}`, { method: 'POST' })
  }

  async pauseSync(serial: string): Promise<{ message: string }> {
    return this.request(`/sync/pause/${serial}`, { method: 'POST' })
  }

  async resumeSync(serial: string): Promise<{ message: string }> {
    return this.request(`/sync/resume/${serial}`, { method: 'POST' })
  }

  async getSyncStatus(serial: string): Promise<SyncStatus> {
    return this.request<SyncStatus>(`/sync/status/${serial}`)
  }

  async getAllSyncStatuses(): Promise<Record<string, SyncStatus>> {
    return this.request<Record<string, SyncStatus>>('/sync/status')
  }

  // Dashboard endpoints
  async getDashboardOverview(dbPath?: string, limit?: number): Promise<DashboardOverview> {
    const params = new URLSearchParams()
    if (dbPath) params.append('db_path', dbPath)
    if (limit) params.append('limit', limit.toString())
    const query = params.toString()
    return this.request<DashboardOverview>(`/dashboard/overview${query ? `?${query}` : ''}`)
  }

  async getMessageTimeseries(
    params: {
      dbPath?: string
      kefuIds?: number[]
      startDate?: string
      endDate?: string
      granularity?: 'hour' | 'day' | 'week' | 'month'
    } = {}
  ): Promise<MessageTimeseriesResponse> {
    const query = new URLSearchParams()
    if (params.dbPath) query.append('db_path', params.dbPath)
    if (params.kefuIds && params.kefuIds.length > 0) {
      query.append('kefu_ids', params.kefuIds.join(','))
    }
    if (params.startDate) query.append('start_date', params.startDate)
    if (params.endDate) query.append('end_date', params.endDate)
    if (params.granularity) query.append('granularity', params.granularity)
    const qs = query.toString()
    return this.request<MessageTimeseriesResponse>(`/dashboard/timeseries${qs ? `?${qs}` : ''}`)
  }

  async getKefus(
    params: {
      dbPath?: string
      limit?: number
      offset?: number
      search?: string
    } = {}
  ): Promise<KefuListResponse> {
    const query = new URLSearchParams()
    if (params.dbPath) query.append('db_path', params.dbPath)
    if (params.limit) query.append('limit', params.limit.toString())
    if (params.offset !== undefined) query.append('offset', params.offset.toString())
    if (params.search) query.append('search', params.search)

    const qs = query.toString()
    return this.request<KefuListResponse>(`/kefus${qs ? `?${qs}` : ''}`)
  }

  async getCustomerFilterOptions(dbPath?: string): Promise<CustomerFilterOptions> {
    const query = new URLSearchParams()
    if (dbPath) query.append('db_path', dbPath)
    const qs = query.toString()
    return this.request<CustomerFilterOptions>(`/customers/filter-options${qs ? `?${qs}` : ''}`)
  }

  async getCustomers(
    params: {
      dbPath?: string
      limit?: number
      offset?: number
      search?: string
      streamer?: string
      kefuId?: number
      deviceSerial?: string
      dateFrom?: string
      dateTo?: string
      sortBy?: string
      sortOrder?: 'asc' | 'desc'
    } = {}
  ): Promise<CustomerListResponse> {
    const query = new URLSearchParams()
    if (params.dbPath) query.append('db_path', params.dbPath)
    if (params.limit) query.append('limit', params.limit.toString())
    if (params.offset !== undefined) query.append('offset', params.offset.toString())
    if (params.search) query.append('search', params.search)
    if (params.streamer) query.append('streamer', params.streamer)
    if (params.kefuId !== undefined) query.append('kefu_id', params.kefuId.toString())
    if (params.deviceSerial) query.append('device_serial', params.deviceSerial)
    if (params.dateFrom) query.append('date_from', params.dateFrom)
    if (params.dateTo) query.append('date_to', params.dateTo)
    if (params.sortBy) query.append('sort_by', params.sortBy)
    if (params.sortOrder) query.append('sort_order', params.sortOrder)

    const qs = query.toString()
    return this.request<CustomerListResponse>(`/customers${qs ? `?${qs}` : ''}`)
  }

  async getCustomer(
    customerId: number,
    params: {
      dbPath?: string
      messagesLimit?: number
      messagesOffset?: number
    } = {}
  ): Promise<CustomerDetailResponse> {
    const query = new URLSearchParams()
    if (params.dbPath) query.append('db_path', params.dbPath)
    if (params.messagesLimit) query.append('messages_limit', params.messagesLimit.toString())
    if (params.messagesOffset !== undefined) {
      query.append('messages_offset', params.messagesOffset.toString())
    }
    const qs = query.toString()
    return this.request<CustomerDetailResponse>(`/customers/${customerId}${qs ? `?${qs}` : ''}`)
  }

  async deleteCustomer(customerId: number, dbPath?: string): Promise<CustomerDeleteResponse> {
    const query = new URLSearchParams()
    if (dbPath) query.append('db_path', dbPath)
    const qs = query.toString()
    return this.request<CustomerDeleteResponse>(`/customers/${customerId}${qs ? `?${qs}` : ''}`, {
      method: 'DELETE',
    })
  }

  async searchMessages(params: {
    q: string
    dbPath?: string
    limit?: number
  }): Promise<MessageSearchResponse> {
    const query = new URLSearchParams()
    query.append('q', params.q)
    if (params.dbPath) query.append('db_path', params.dbPath)
    if (params.limit) query.append('limit', params.limit.toString())
    const qs = query.toString()
    return this.request<MessageSearchResponse>(`/customers/messages/search?${qs}`)
  }

  async deleteStreamer(streamerId: string, dbPath?: string): Promise<StreamerDeleteResponse> {
    const query = new URLSearchParams()
    if (dbPath) query.append('db_path', dbPath)
    const qs = query.toString()
    return this.request<StreamerDeleteResponse>(
      `/streamers/${encodeURIComponent(streamerId)}${qs ? `?${qs}` : ''}`,
      {
        method: 'DELETE',
      }
    )
  }

  async getKefu(
    kefuId: number,
    params: {
      dbPath?: string
      customersLimit?: number
      customersOffset?: number
    } = {}
  ): Promise<KefuDetailResponse> {
    const query = new URLSearchParams()
    if (params.dbPath) query.append('db_path', params.dbPath)
    if (params.customersLimit) query.append('customers_limit', params.customersLimit.toString())
    if (params.customersOffset !== undefined) {
      query.append('customers_offset', params.customersOffset.toString())
    }
    const qs = query.toString()
    return this.request<KefuDetailResponse>(`/kefus/${kefuId}${qs ? `?${qs}` : ''}`)
  }

  async deleteKefu(kefuId: number, dbPath?: string): Promise<KefuDeleteResponse> {
    const query = new URLSearchParams()
    if (dbPath) query.append('db_path', dbPath)
    const qs = query.toString()
    return this.request<KefuDeleteResponse>(`/kefus/${kefuId}${qs ? `?${qs}` : ''}`, {
      method: 'DELETE',
    })
  }

  // Sidecar endpoints
  async getSidecarState(serial: string): Promise<SidecarState> {
    return this.request<SidecarState>(`/sidecar/${serial}/state`)
  }

  async getLastMessage(serial: string): Promise<LastMessageResponse> {
    return this.request<LastMessageResponse>(`/sidecar/${serial}/last-message`)
  }

  async getConversationHistory(
    serial: string,
    params: {
      contactName?: string
      channel?: string
      kefuName?: string
      limit?: number
      dbPath?: string
    } = {}
  ): Promise<ConversationHistoryResponse> {
    const query = new URLSearchParams()
    if (params.contactName) query.append('contact_name', params.contactName)
    if (params.channel) query.append('channel', params.channel)
    if (params.kefuName) query.append('kefu_name', params.kefuName)
    if (params.limit) query.append('limit', params.limit.toString())
    if (params.dbPath) query.append('db_path', params.dbPath)
    const qs = query.toString()
    return this.request<ConversationHistoryResponse>(
      `/sidecar/${serial}/conversation-history${qs ? `?${qs}` : ''}`
    )
  }

  async sendSidecarMessage(serial: string, message: string): Promise<SendMessageResponse> {
    return this.request<SendMessageResponse>(`/sidecar/${serial}/send`, {
      method: 'POST',
      body: JSON.stringify({ message }),
    })
  }

  /**
   * Send a message and save it to the database immediately.
   * Use this when sending during sync to ensure the message is recorded.
   */
  async sendAndSaveMessage(
    serial: string,
    message: string,
    contactName?: string,
    channel?: string,
    kefuName?: string
  ): Promise<{ success: boolean; message_saved: boolean; detail?: string }> {
    return this.request(`/sidecar/${serial}/send-and-save`, {
      method: 'POST',
      body: JSON.stringify({
        message,
        contact_name: contactName,
        channel: channel,
        kefu_name: kefuName,
      }),
    })
  }

  // Sidecar Queue endpoints
  async getSidecarQueueState(serial: string): Promise<QueueStateResponse> {
    return this.request<QueueStateResponse>(`/sidecar/${serial}/queue`)
  }

  async addToSidecarQueue(
    serial: string,
    data: AddMessageRequest
  ): Promise<{ id: string; success: boolean }> {
    return this.request(`/sidecar/${serial}/queue/add`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  }

  async setQueueMessageReady(serial: string, messageId: string): Promise<{ success: boolean }> {
    return this.request(`/sidecar/${serial}/queue/ready/${messageId}`, {
      method: 'POST',
    })
  }

  async sendQueuedMessage(
    serial: string,
    messageId: string,
    editedMessage?: string
  ): Promise<SendMessageResponse> {
    return this.request<SendMessageResponse>(`/sidecar/${serial}/queue/send/${messageId}`, {
      method: 'POST',
      body: editedMessage ? JSON.stringify({ edited_message: editedMessage }) : undefined,
    })
  }

  async pauseSidecarQueue(serial: string): Promise<{ success: boolean }> {
    return this.request(`/sidecar/${serial}/queue/pause`, {
      method: 'POST',
    })
  }

  async resumeSidecarQueue(serial: string): Promise<{ success: boolean }> {
    return this.request(`/sidecar/${serial}/queue/resume`, {
      method: 'POST',
    })
  }

  async cancelSidecarQueue(serial: string): Promise<{ success: boolean }> {
    return this.request(`/sidecar/${serial}/queue/cancel`, {
      method: 'POST',
    })
  }

  async clearSidecarQueue(serial: string): Promise<{ success: boolean }> {
    return this.request(`/sidecar/${serial}/queue`, {
      method: 'DELETE',
    })
  }

  // Skip API - independent skip mechanism
  async requestSkip(serial: string): Promise<{ success: boolean; message: string }> {
    return this.request(`/sidecar/${serial}/skip`, {
      method: 'POST',
    })
  }

  async getSkipStatus(serial: string): Promise<{ skip_requested: boolean }> {
    return this.request(`/sidecar/${serial}/skip`)
  }

  async clearSkipFlag(serial: string): Promise<{ success: boolean }> {
    return this.request(`/sidecar/${serial}/skip`, {
      method: 'DELETE',
    })
  }
  async waitForSidecarSend(
    serial: string,
    messageId: string,
    timeout: number = 60
  ): Promise<WaitForSendResponse> {
    return this.request<WaitForSendResponse>(
      `/sidecar/${serial}/queue/wait/${messageId}?timeout=${timeout}`,
      {
        method: 'POST',
      }
    )
  }

  // Resource endpoints
  async getResourceFilterOptions(dbPath?: string): Promise<ResourceFilterOptions> {
    const query = new URLSearchParams()
    if (dbPath) query.append('db_path', dbPath)
    const qs = query.toString()
    return this.request<ResourceFilterOptions>(`/resources/filter-options${qs ? `?${qs}` : ''}`)
  }

  async getImages(
    params: {
      dbPath?: string
      limit?: number
      offset?: number
      search?: string
      streamer?: string
      kefuId?: number
      deviceSerial?: string
      dateFrom?: string
      dateTo?: string
      sortBy?: string
      sortOrder?: 'asc' | 'desc'
    } = {}
  ): Promise<ImageListResponse> {
    const query = new URLSearchParams()
    if (params.dbPath) query.append('db_path', params.dbPath)
    if (params.limit) query.append('limit', params.limit.toString())
    if (params.offset !== undefined) query.append('offset', params.offset.toString())
    if (params.search) query.append('search', params.search)
    if (params.streamer) query.append('streamer', params.streamer)
    if (params.kefuId !== undefined) query.append('kefu_id', params.kefuId.toString())
    if (params.deviceSerial) query.append('device_serial', params.deviceSerial)
    if (params.dateFrom) query.append('date_from', params.dateFrom)
    if (params.dateTo) query.append('date_to', params.dateTo)
    if (params.sortBy) query.append('sort_by', params.sortBy)
    if (params.sortOrder) query.append('sort_order', params.sortOrder)

    const qs = query.toString()
    return this.request<ImageListResponse>(`/resources/images${qs ? `?${qs}` : ''}`)
  }

  async getImage(imageId: number, dbPath?: string): Promise<ImageDetailResponse> {
    const query = new URLSearchParams()
    if (dbPath) query.append('db_path', dbPath)
    const qs = query.toString()
    return this.request<ImageDetailResponse>(`/resources/images/${imageId}${qs ? `?${qs}` : ''}`)
  }

  async deleteImage(imageId: number, dbPath?: string): Promise<ImageDeleteResponse> {
    const query = new URLSearchParams()
    if (dbPath) query.append('db_path', dbPath)
    const qs = query.toString()
    return this.request<ImageDeleteResponse>(`/resources/images/${imageId}${qs ? `?${qs}` : ''}`, {
      method: 'DELETE',
    })
  }

  async getVoiceMessages(
    params: {
      dbPath?: string
      limit?: number
      offset?: number
      search?: string
      streamer?: string
      kefuId?: number
      deviceSerial?: string
      dateFrom?: string
      dateTo?: string
      sortBy?: string
      sortOrder?: 'asc' | 'desc'
    } = {}
  ): Promise<VoiceListResponse> {
    const query = new URLSearchParams()
    if (params.dbPath) query.append('db_path', params.dbPath)
    if (params.limit) query.append('limit', params.limit.toString())
    if (params.offset !== undefined) query.append('offset', params.offset.toString())
    if (params.search) query.append('search', params.search)
    if (params.streamer) query.append('streamer', params.streamer)
    if (params.kefuId !== undefined) query.append('kefu_id', params.kefuId.toString())
    if (params.deviceSerial) query.append('device_serial', params.deviceSerial)
    if (params.dateFrom) query.append('date_from', params.dateFrom)
    if (params.dateTo) query.append('date_to', params.dateTo)
    if (params.sortBy) query.append('sort_by', params.sortBy)
    if (params.sortOrder) query.append('sort_order', params.sortOrder)

    const qs = query.toString()
    return this.request<VoiceListResponse>(`/resources/voice${qs ? `?${qs}` : ''}`)
  }

  async deleteVoiceMessage(messageId: number, dbPath?: string): Promise<VoiceDeleteResponse> {
    const query = new URLSearchParams()
    if (dbPath) query.append('db_path', dbPath)
    const qs = query.toString()
    return this.request<VoiceDeleteResponse>(`/resources/voice/${messageId}${qs ? `?${qs}` : ''}`, {
      method: 'DELETE',
    })
  }

  async transcribeVoiceMessage(
    messageId: number,
    dbPath?: string
  ): Promise<VoiceTranscribeResponse> {
    const query = new URLSearchParams()
    if (dbPath) query.append('db_path', dbPath)
    const qs = query.toString()
    return this.request<VoiceTranscribeResponse>(
      `/resources/voice/${messageId}/transcribe${qs ? `?${qs}` : ''}`,
      {
        method: 'POST',
      }
    )
  }

  async getVideoMessages(
    params: {
      dbPath?: string
      limit?: number
      offset?: number
      search?: string
      streamer?: string
      kefuId?: number
      deviceSerial?: string
      dateFrom?: string
      dateTo?: string
      sortBy?: string
      sortOrder?: 'asc' | 'desc'
    } = {}
  ): Promise<VideoListResponse> {
    const query = new URLSearchParams()
    if (params.dbPath) query.append('db_path', params.dbPath)
    if (params.limit) query.append('limit', params.limit.toString())
    if (params.offset !== undefined) query.append('offset', params.offset.toString())
    if (params.search) query.append('search', params.search)
    if (params.streamer) query.append('streamer', params.streamer)
    if (params.kefuId !== undefined) query.append('kefu_id', params.kefuId.toString())
    if (params.deviceSerial) query.append('device_serial', params.deviceSerial)
    if (params.dateFrom) query.append('date_from', params.dateFrom)
    if (params.dateTo) query.append('date_to', params.dateTo)
    if (params.sortBy) query.append('sort_by', params.sortBy)
    if (params.sortOrder) query.append('sort_order', params.sortOrder)

    const qs = query.toString()
    return this.request<VideoListResponse>(`/resources/videos${qs ? `?${qs}` : ''}`)
  }

  async deleteVideoMessage(messageId: number, dbPath?: string): Promise<VideoDeleteResponse> {
    const query = new URLSearchParams()
    if (dbPath) query.append('db_path', dbPath)
    const qs = query.toString()
    return this.request<VideoDeleteResponse>(
      `/resources/videos/${messageId}${qs ? `?${qs}` : ''}`,
      {
        method: 'DELETE',
      }
    )
  }

  // Get video info by message ID (for conversation detail)
  async getVideoByMessageId(messageId: number, dbPath?: string): Promise<VideoByMessageResponse> {
    const query = new URLSearchParams()
    if (dbPath) query.append('db_path', dbPath)
    const qs = query.toString()
    return this.request<VideoByMessageResponse>(
      `/resources/videos/by-message/${messageId}${qs ? `?${qs}` : ''}`
    )
  }

  // Get image info by message ID (for conversation detail)
  async getImageByMessageId(messageId: number, dbPath?: string): Promise<ImageByMessageResponse> {
    const query = new URLSearchParams()
    if (dbPath) query.append('db_path', dbPath)
    const qs = query.toString()
    return this.request<ImageByMessageResponse>(
      `/resources/images/by-message/${messageId}${qs ? `?${qs}` : ''}`
    )
  }

  // Get voice info by message ID (for conversation detail)
  async getVoiceByMessageId(messageId: number, dbPath?: string): Promise<VoiceByMessageResponse> {
    const query = new URLSearchParams()
    if (dbPath) query.append('db_path', dbPath)
    const qs = query.toString()
    return this.request<VoiceByMessageResponse>(
      `/resources/voice/by-message/${messageId}${qs ? `?${qs}` : ''}`
    )
  }

  // Get voice file URL for playback
  getVoiceFileUrl(messageId: number): string {
    return `${this.baseUrl}/resources/voice/${messageId}/file`
  }

  // Health check
  async healthCheck(): Promise<{ status: string; version: string }> {
    return this.request('/health')
  }

  // Volcengine ASR Settings
  async getVolcengineAsrSettings(): Promise<VolcengineAsrSettings> {
    return this.request('/settings/volcengine-asr')
  }

  async updateVolcengineAsrSettings(
    settings: Partial<VolcengineAsrSettings>
  ): Promise<VolcengineAsrSettings> {
    return this.request('/settings/volcengine-asr', {
      method: 'PUT',
      body: JSON.stringify(settings),
    })
  }

  // Screenshot endpoint
  getScreenshotUrl(serial: string): string {
    return `${this.baseUrl}/devices/${serial}/screenshot?t=${Date.now()}`
  }

  // Image file URL
  getImageUrl(imageId: number): string {
    return `${this.baseUrl}/resources/images/${imageId}/file`
  }

  // Video file URL
  getVideoUrl(videoId: number): string {
    return `${this.baseUrl}/resources/videos/${videoId}/file`
  }

  // Video thumbnail URL
  getVideoThumbnailUrl(videoId: number): string {
    return `${this.baseUrl}/resources/videos/${videoId}/thumbnail`
  }

  /** Extracted review frame JPEG (frame_index 0..3) */
  getVideoReviewFrameUrl(messageId: number, frameIndex: number, dbPath?: string): string {
    const q = new URLSearchParams()
    if (dbPath) q.append('db_path', dbPath)
    const qs = q.toString()
    return `${this.baseUrl}/resources/videos/by-message/${messageId}/review-frame/${frameIndex}${qs ? `?${qs}` : ''}`
  }

  // Voice file URL (message_id from messages table)
  getVoiceUrl(messageId: number): string {
    return `${this.baseUrl}/resources/voice/${messageId}/file`
  }

  // ==========================================
  // Human Request & Blacklist Management
  // ==========================================

  /**
   * Report that a user requested human agent.
   * This will add the user to blacklist and send email notification if enabled.
   */
  async reportHumanRequest(
    customerName: string,
    serial: string,
    channel?: string,
    reason: string = 'Requested human agent'
  ): Promise<{ success: boolean; message: string }> {
    return this.request('/settings/email/human-request', {
      method: 'POST',
      body: JSON.stringify({
        customer_name: customerName,
        channel: channel || null,
        serial,
        reason,
      }),
    })
  }

  /**
   * Report that a user sent a voice message.
   * This will add the user to blacklist and send email notification if enabled.
   */
  async reportVoiceMessage(
    customerName: string,
    serial: string,
    channel?: string
  ): Promise<{ success: boolean; message: string }> {
    return this.request('/settings/email/voice-message', {
      method: 'POST',
      body: JSON.stringify({
        customer_name: customerName,
        channel: channel || null,
        serial,
        reason: 'Sent voice message',
      }),
    })
  }

  /**
   * Get all blacklisted users.
   */
  async getBlacklist(): Promise<{
    users: Array<{
      name: string
      channel?: string
      serial: string
      added_at: string
      reason: string
    }>
    updated_at: string | null
  }> {
    return this.request('/settings/email/blacklist')
  }

  /**
   * Remove a user from the blacklist.
   */
  async removeFromBlacklist(
    customerName: string,
    channel?: string
  ): Promise<{ success: boolean; message: string }> {
    const url = channel
      ? `/settings/email/blacklist/${encodeURIComponent(customerName)}?channel=${encodeURIComponent(channel)}`
      : `/settings/email/blacklist/${encodeURIComponent(customerName)}`
    return this.request(url, { method: 'DELETE' })
  }

  // ==========================================================================
  // AI Learning APIs
  // ==========================================================================

  /**
   * Record an admin action on an AI reply.
   */
  async recordAdminAction(
    action: RecordAdminActionRequest
  ): Promise<{ success: boolean; action_id: string }> {
    return this.request('/api/ai/admin-action', {
      method: 'POST',
      body: JSON.stringify(action),
    })
  }

  // ==========================================================================
  // Blacklist System Methods
  // ==========================================================================

  async getFollowupBlacklist(device_serial?: string): Promise<BlacklistEntry[]> {
    const params = new URLSearchParams()
    if (device_serial) params.append('device_serial', device_serial)
    return this.request<BlacklistEntry[]>(`/api/blacklist?${params.toString()}`)
  }

  async getBlacklistCustomers(params: {
    device_serial?: string
    search?: string
    filter?: string
  }): Promise<CustomerWithBlacklistStatus[]> {
    const searchParams = new URLSearchParams()
    if (params.device_serial) searchParams.append('device_serial', params.device_serial)
    if (params.search) searchParams.append('search', params.search)
    if (params.filter) searchParams.append('filter', params.filter)

    return this.request<CustomerWithBlacklistStatus[]>(
      `/api/blacklist/customers?${searchParams.toString()}`
    )
  }

  async addToFollowupBlacklist(
    data: BlacklistAddRequest
  ): Promise<{ success: boolean; message: string }> {
    return this.request('/api/blacklist/add', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  }

  async removeFromFollowupBlacklist(
    data: BlacklistRemoveRequest
  ): Promise<{ success: boolean; message: string }> {
    return this.request('/api/blacklist/remove', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  }

  async batchAddToFollowupBlacklist(
    data: BlacklistAddRequest[]
  ): Promise<{ success: boolean; count: number }> {
    return this.request('/api/blacklist/batch-add', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  }

  async batchRemoveFromFollowupBlacklist(
    data: BlacklistRemoveRequest[]
  ): Promise<{ success: boolean; count: number }> {
    return this.request('/api/blacklist/batch-remove', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  }

  // New methods for extended blacklist functionality

  async getBlacklistEntries(params: {
    device_serial?: string
    show_all?: boolean
  }): Promise<BlacklistEntry[]> {
    const searchParams = new URLSearchParams()
    if (params.device_serial) searchParams.append('device_serial', params.device_serial)
    if (params.show_all) searchParams.append('show_all', 'true')

    return this.request<BlacklistEntry[]>(`/api/blacklist?${searchParams.toString()}`)
  }

  async checkBlacklistStatus(params: BlacklistCheckRequest): Promise<BlacklistCheckResponse> {
    const searchParams = new URLSearchParams({
      device_serial: params.device_serial,
      customer_name: params.customer_name,
    })
    if (params.customer_channel) {
      searchParams.append('customer_channel', params.customer_channel)
    }

    return this.request<BlacklistCheckResponse>(`/api/blacklist/check?${searchParams.toString()}`)
  }

  async toggleBlacklist(data: BlacklistCheckRequest): Promise<BlacklistToggleResponse> {
    return this.request<BlacklistToggleResponse>('/api/blacklist/toggle', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  }

  async upsertScannedUsers(data: UpsertScannedUsersRequest): Promise<{
    success: boolean
    inserted: number
    updated: number
    failed: number
  }> {
    return this.request('/api/blacklist/upsert-scanned', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  }

  async copyBlacklistEntries(data: BlacklistCopyRequest): Promise<BlacklistCopyResponse> {
    return this.request<BlacklistCopyResponse>('/api/blacklist/copy-device', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  }

  async getWhitelist(
    device_serial: string
  ): Promise<Array<{ customer_name: string; customer_channel?: string }>> {
    return this.request(`/api/blacklist/whitelist/${device_serial}`)
  }

  async updateBlacklistStatus(
    data: BlacklistUpdateRequest
  ): Promise<{ success: boolean; message: string }> {
    return this.request('/api/blacklist/update-status', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  }

  async batchUpdateBlacklistStatus(data: BatchUpdateStatusRequest): Promise<{
    success: boolean
    success_count: number
    failed_count: number
  }> {
    return this.request('/api/blacklist/batch-update-status', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  }

  // ==========================================================================
  // Recovery Checkpoint APIs
  // ==========================================================================

  /**
   * Check all devices for resumable tasks.
   */
  async checkAllResumableTasks(): Promise<{
    has_resumable: boolean
    tasks: Array<{
      task_id: string
      task_type: string
      device_serial: string
      status: string
      progress_percent: number
      synced_count: number
      total_count: number
      messages_added: number
      started_at?: string
      last_checkpoint_at?: string
    }>
  }> {
    return this.request('/recovery/check')
  }

  /**
   * Check a specific device for resumable tasks.
   */
  async checkDeviceResumableTasks(deviceSerial: string): Promise<{
    tasks: Array<{
      task_id: string
      task_type: string
      device_serial: string
      status: string
      progress_percent: number
      synced_count: number
      total_count: number
      messages_added: number
      started_at?: string
      last_checkpoint_at?: string
    }>
  }> {
    return this.request(`/recovery/check/${deviceSerial}`)
  }

  /**
   * Resume a recovery task.
   */
  async resumeRecoveryTask(taskId: string): Promise<{
    success: boolean
    message?: string
  }> {
    return this.request(`/recovery/resume/${taskId}`, {
      method: 'POST',
    })
  }

  /**
   * Discard a recovery task.
   */
  async discardRecoveryTask(taskId: string): Promise<{
    success: boolean
    message?: string
  }> {
    return this.request(`/recovery/discard/${taskId}`, {
      method: 'POST',
    })
  }

  /**
   * Save UI state for a recovery task.
   */
  async saveTaskUIState(
    taskId: string,
    uiState: Record<string, any>
  ): Promise<{
    success: boolean
    message?: string
  }> {
    return this.request(`/recovery/ui-state/${taskId}`, {
      method: 'POST',
      body: JSON.stringify({ ui_state: uiState }),
    })
  }

  // ==========================================================================
  // Media Auto-Actions
  // ==========================================================================

  async getMediaActionSettings(): Promise<MediaAutoActionSettings> {
    return this.request<MediaAutoActionSettings>('/api/media-actions/settings')
  }

  async updateMediaActionSettings(
    settings: Partial<MediaAutoActionSettings>
  ): Promise<MediaAutoActionSettings> {
    return this.request<MediaAutoActionSettings>('/api/media-actions/settings', {
      method: 'PUT',
      body: JSON.stringify(settings),
    })
  }

  async getMediaActionLogs(params?: {
    device_serial?: string
    action_name?: string
    limit?: number
    offset?: number
  }): Promise<{ logs: MediaActionLogEntry[]; total: number }> {
    const searchParams = new URLSearchParams()
    if (params?.device_serial) searchParams.append('device_serial', params.device_serial)
    if (params?.action_name) searchParams.append('action_name', params.action_name)
    if (params?.limit) searchParams.append('limit', String(params.limit))
    if (params?.offset) searchParams.append('offset', String(params.offset))

    return this.request(`/api/media-actions/logs?${searchParams.toString()}`)
  }

  async testTriggerMediaAction(params: {
    device_serial?: string
    customer_name?: string
    message_type?: string
  }): Promise<{
    status: string
    results: Array<{
      action_name: string
      status: string
      message: string
      details?: Record<string, any>
    }>
  }> {
    const searchParams = new URLSearchParams()
    if (params.device_serial) searchParams.append('device_serial', params.device_serial)
    if (params.customer_name) searchParams.append('customer_name', params.customer_name)
    if (params.message_type) searchParams.append('message_type', params.message_type)

    return this.request(`/api/media-actions/test-trigger?${searchParams.toString()}`, {
      method: 'POST',
    })
  }
}

export const api = new ApiClient()

// WebSocket connection for real-time sync status updates
export function connectSyncStatusStream(
  serial: string,
  onStatus: (status: SyncStatus) => void,
  onError?: (error: Event) => void
): WebSocket {
  const ws = new WebSocket(`ws://localhost:8765/ws/sync/${serial}`)

  ws.onmessage = (event) => {
    try {
      const status = JSON.parse(event.data) as SyncStatus
      onStatus(status)
    } catch (e) {
      console.error('Failed to parse sync status:', e)
    }
  }

  ws.onerror = (error) => {
    console.error('Sync status WebSocket error:', error)
    onError?.(error)
  }

  return ws
}
