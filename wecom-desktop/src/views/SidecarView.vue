<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute } from 'vue-router'
import { useDeviceStore } from '../stores/devices'
import { useSettingsStore } from '../stores/settings'
import { useLogStore } from '../stores/logs'
import LoadingSpinner from '../components/LoadingSpinner.vue'
import LogStream from '../components/LogStream.vue'
import VideoAiReviewSummary from '../components/VideoAiReviewSummary.vue'
import VideoReviewDetailPanel from '../components/VideoReviewDetailPanel.vue'
import {
  api,
  API_BASE,
  type SidecarState,
  type QueuedMessage,
  type SyncQueueState,
  type SidecarKefu,
  type ConversationHistoryMessage,
} from '../services/api'
import { aiService } from '../services/aiService'
import { useI18n } from '../composables/useI18n'
import { useGlobalWebSocketStore } from '../stores/globalWebSocket'
import type { GlobalWebSocketEvent } from '../stores/globalWebSocket'
import {
  getActiveConversationTarget,
  getBlockButtonTitle,
  hasActiveConversationTarget,
  toggleBlockUserForPanel,
} from './sidecarBlock'

const { t } = useI18n()

type PanelState = {
  state: SidecarState | null
  loading: boolean
  error: string | null
  statusMessage: string | null
  pendingMessage: string
  countdown: number | null
  countdownTotal: number | null
  countdownTimer: number | null
  pollTimer: number | null
  baselineHash: string | null
  baselineFocus: string | null
  initialized: boolean
  // Queue state
  queuedMessages: QueuedMessage[]
  syncQueueState: SyncQueueState | null
  currentQueuedMessage: QueuedMessage | null
  queueMode: boolean // Whether we're in queue processing mode
  sendingQueued: boolean // Whether a queued message is currently being sent
  sending: boolean // Any send (queued or manual) is in flight
  manuallyPaused: boolean // Whether user manually paused the countdown
  isEditing: boolean // Whether user is editing the message
  // Logs state
  logsCollapsed: boolean
  logsHeight: number // Height of logs section in pixels
  // AI Reply state
  aiProcessing: boolean // Whether AI is processing
  aiReplySource: 'ai' | 'mock' | 'fallback' | null // Source of current reply
  generating: boolean // Whether we're generating a reply
  // Cached kefu info (set once, not refreshed)
  cachedKefu: SidecarKefu | null
  // Original AI message (for learning tracking)
  originalAiMessage: string | null // Stores the original AI-generated message before editing
  // Conversation history state
  historyCollapsed: boolean
  historyMessages: ConversationHistoryMessage[]
  historyTotalCount: number
  historyLoading: boolean
  historyError: string | null
  historyHeight: number // Height of history section in pixels
  historyLastFetched: { contactName: string | null; channel: string | null } | null
  /** DB file path last used for conversation-history (for video review frame URLs). */
  historyDbPath: string | null
  // New message highlight state
  highlightedMessageIds: Set<number> // Message IDs that should be highlighted
  highlightTimer: number | null // Timer to clear highlights
  // Blacklist state
  isBlacklisted: boolean | null // Current blacklist status of the user
}

const route = useRoute()
/** Optional `?db_path=` on Sidecar route to read history / frames from a non-default DB. */
const sidecarConversationHistoryDbOverride = computed(() => {
  const q = route.query.db_path
  return typeof q === 'string' && q.trim() ? q.trim() : undefined
})
const deviceStore = useDeviceStore()
const settingsStore = useSettingsStore()
const logStore = useLogStore()
const globalWebSocket = useGlobalWebSocketStore()
const { settings } = storeToRefs(settingsStore)

// Control logs panel visibility based on settings
const showLogs = computed(() => settings.value.sidecarShowLogs)

const maxPanels = computed(() => Math.max(1, Number(settings.value.sidecarMaxPanels || 3)))
const panels = ref<string[]>([])
const focusedSerial = ref<string | null>(null)
const isDragOver = ref(false)
const dropMessage = ref('Drag a device tab into the sidecar area')
const syncTargetSerial = ref<string>('')
const syncActionMessage = ref<string | null>(null)
const syncLoading = ref(false)
const mirrorLoading = reactive<Record<string, boolean>>({})
const skipLoading = reactive<Record<string, boolean>>({})
const blockLoading = reactive<Record<string, boolean>>({})
const stopLoading = reactive<Record<string, boolean>>({})

// Follow-up status cache
type FollowUpDeviceStatus = {
  serial: string
  status: 'idle' | 'starting' | 'running' | 'paused' | 'stopped' | 'error'
  message: string
  responses_detected: number
  replies_sent: number
  started_at: string | null
  last_scan_at: string | null
  errors: string[]
}

const followUpStatus = reactive<Record<string, FollowUpDeviceStatus>>({})

// Image preview state
const previewImageUrl = ref<string | null>(null)
const previewVideoId = ref<number | null>(null)
const previewVideoDuration = ref<string | null>(null)

const videoReviewModalOpen = ref(false)
const videoReviewMessageId = ref(0)
const videoReviewFramesJson = ref<string | null>(null)
const videoReviewAggregateScore = ref<number | null>(null)
const videoReviewDbPath = ref<string | null>(null)

function openVideoReviewDetail(serial: string, msg: ConversationHistoryMessage) {
  const panel = ensurePanel(serial)
  videoReviewMessageId.value = msg.id
  videoReviewFramesJson.value = msg.video_ai_review_frames_json ?? null
  videoReviewAggregateScore.value = msg.video_ai_review_score ?? null
  videoReviewDbPath.value = panel.historyDbPath
  videoReviewModalOpen.value = true
}

// Logs resize state
const resizingSerial = ref<string | null>(null)
const resizeStartY = ref(0)
const resizeStartHeight = ref(0)

// History resize state
const resizingHistorySerial = ref<string | null>(null)
const resizeHistoryStartY = ref(0)
const resizeHistoryStartHeight = ref(0)

const sidecars = reactive<Record<string, PanelState>>({})

const SIDECAR_DRAG_MIME = 'application/x-wecom-device-serial'

const availableDevices = computed(() => deviceStore.devices.map((d) => d.serial))

watch(
  availableDevices,
  (devices) => {
    if (devices.length === 0) {
      syncTargetSerial.value = ''
      return
    }

    if (!devices.includes(syncTargetSerial.value)) {
      syncTargetSerial.value = devices[0]
    }
  },
  { immediate: true }
)

const gridColsClass = computed(() => {
  if (panels.value.length === 1) return 'grid-cols-1'
  if (panels.value.length === 2) return 'grid-cols-2'
  return 'grid-cols-3'
})

// Refs for chat history containers (keyed by serial)
const chatHistoryRefs = ref<Record<string, HTMLElement | null>>({})

// Scroll to bottom of chat history
function scrollToBottom(serial: string) {
  nextTick(() => {
    const container = chatHistoryRefs.value[serial]
    if (container) {
      container.scrollTop = container.scrollHeight
    }
  })
}

type ImageReviewStatus = 'pending' | 'completed' | 'timeout' | 'failed'

function normalizeHistoryTarget(value: string | null | undefined): string | null {
  const normalized = value?.trim()
  return normalized ? normalized : null
}

function matchesHistoryTarget(
  currentContactName: string | null | undefined,
  currentChannel: string | null | undefined,
  customerName: string | null | undefined,
  channel: string | null | undefined
): boolean {
  const targetContactName = normalizeHistoryTarget(currentContactName)
  const targetChannel = normalizeHistoryTarget(currentChannel)
  const eventCustomerName = normalizeHistoryTarget(customerName)
  const eventChannel = normalizeHistoryTarget(channel)

  const nameMatch =
    !!targetContactName &&
    !!eventCustomerName &&
    (targetContactName === eventCustomerName ||
      targetContactName.includes(eventCustomerName) ||
      eventCustomerName.includes(targetContactName))

  const channelMatch = !!targetChannel && !!eventChannel && targetChannel === eventChannel

  return nameMatch || channelMatch
}

function panelMatchesHistoryEvent(
  panel: PanelState,
  customerName: string | null | undefined,
  channel: string | null | undefined
): boolean {
  const target = getActiveConversationTarget(panel)
  return matchesHistoryTarget(target.contactName, target.channel, customerName, channel)
}

function getAiReviewStatus(msg: ConversationHistoryMessage): ImageReviewStatus | null {
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

function shouldShowAiReviewSection(msg: ConversationHistoryMessage): boolean {
  return getAiReviewStatus(msg) !== null
}

function getAiReviewErrorMessage(msg: ConversationHistoryMessage): string | null {
  const error = msg.ai_review_error?.trim()
  return error ? error : null
}

function formatAiReviewLabel(label: string | null | undefined): string {
  const normalized = label?.trim()
  if (!normalized) return '评分项'
  return normalized
    .split(/\s+/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function getHistoryRefreshStatus(
  reason: string | null | undefined,
  score: number | null | undefined
): string | null {
  if (!reason) return null
  if (reason === 'image_review_pending') return 'Image review pending'
  if (reason === 'image_review_timeout') return 'Image review timed out'
  if (reason === 'image_review_failed') return 'Image review failed'
  if (reason === 'image_review_completed') {
    return score != null
      ? `Image review score: ${Number(score).toFixed(1)}`
      : 'Image review completed'
  }
  if (reason === 'video_review_pending') return 'Video review pending'
  if (reason === 'video_review_timeout') return 'Video review timed out'
  if (reason === 'video_review_failed') return 'Video review failed'
  if (reason === 'video_review_partial') return 'Video review partial'
  if (reason === 'video_review_completed') {
    return score != null
      ? `Video review avg: ${Number(score).toFixed(2)}`
      : 'Video review completed'
  }
  return null
}

// ==================== Real-time Message Updates ====================

/**
 * 处理全局 WebSocket 事件
 * 当 followup 或 sync 捕获新消息时，自动刷新 sidecar 的聊天记录
 */
function handleGlobalWebSocketEvent(event: GlobalWebSocketEvent) {
  console.log('[Sidecar] Received WebSocket event:', event.type, event.data)

  if (event.type === 'history_refresh') {
    const { customer_name, channel, reason, review_score } = event.data || {}

    // 遍历所有打开的面板，检查是否有匹配的对话
    for (const serial of panels.value) {
      const panel = ensurePanel(serial)

      // 检查当前面板的对话是否匹配
      const currentTarget = getActiveConversationTarget(panel)
      const currentContactName = currentTarget.contactName
      const currentChannel = currentTarget.channel

      // 多种匹配策略：
      // 1. contact_name 精确匹配 customer_name
      // 2. channel 精确匹配（如果都有 channel）
      // 3. customer_name 包含在 contact_name 中
      // 4. contact_name 包含在 customer_name 中
      const nameMatch =
        currentContactName &&
        customer_name &&
        (currentContactName === customer_name ||
          currentContactName.includes(customer_name) ||
          customer_name.includes(currentContactName))
      const channelMatch = currentChannel && channel && currentChannel === channel

      // 满足任一匹配条件即可刷新
      const shouldRefresh =
        nameMatch || channelMatch || panelMatchesHistoryEvent(panel, customer_name, channel)

      if (shouldRefresh) {
        console.log(
          `[Sidecar] ✓ Match! Refreshing history for ${serial} (name=${currentContactName}, event_name=${customer_name}, channel=${currentChannel})`
        )

        // 刷新聊天记录
        refreshConversationHistory(serial)

        // 添加视觉提示
        const reviewStatus = getHistoryRefreshStatus(reason, review_score)
        if (reviewStatus) {
          addDeviceLog(serial, 'INFO', reviewStatus)
          panel.statusMessage = reviewStatus
        } else {
          addDeviceLog(serial, 'INFO', `💬 New message detected from ${customer_name}`)
          panel.statusMessage = '💬 New message received!'
        }

        // 3秒后清除状态消息
        setTimeout(() => {
          if (
            panel.statusMessage === reviewStatus ||
            panel.statusMessage === '💬 New message received!'
          ) {
            panel.statusMessage = null
          }
        }, 3000)
      } else {
        console.log(
          `[Sidecar] ✗ No match for ${serial}: current=${currentContactName}/${currentChannel}, event=${customer_name}/${channel}`
        )
      }
    }
  } else if (event.type === 'message_added') {
    const { customer_name, channel } = event.data || {}

    // 类似处理，但针对单个新消息
    for (const serial of panels.value) {
      const panel = ensurePanel(serial)
      const target = getActiveConversationTarget(panel)
      const currentContactName = target.contactName
      const currentChannel = target.channel

      // 使用相同的宽松匹配逻辑
      const nameMatch =
        currentContactName &&
        customer_name &&
        (currentContactName === customer_name ||
          currentContactName.includes(customer_name) ||
          customer_name.includes(currentContactName))
      const channelMatch = currentChannel && channel && currentChannel === channel

      if (nameMatch || channelMatch) {
        console.log(`[Sidecar] New message added for ${customer_name}`)
        refreshConversationHistory(serial)
      }
    }
  }
}

/**
 * 设置全局 WebSocket 监听
 * 在组件挂载时调用，建立 WebSocket 连接并监听事件
 */
function setupGlobalWebSocket() {
  // 连接 WebSocket（如果还未连接）
  if (!globalWebSocket.connected && !globalWebSocket.connecting) {
    console.log('[Sidecar] Connecting to global WebSocket...')
    globalWebSocket.connect()
  }

  // 监听所有相关事件
  globalWebSocket.addListener('history_refresh', handleGlobalWebSocketEvent)
  globalWebSocket.addListener('message_added', handleGlobalWebSocketEvent)

  console.log('[Sidecar] ✓ Global WebSocket listeners attached')
}

/**
 * 清理全局 WebSocket 监听
 * 在组件卸载时调用，移除监听器
 */
function cleanupGlobalWebSocket() {
  globalWebSocket.removeListener('history_refresh', handleGlobalWebSocketEvent)
  globalWebSocket.removeListener('message_added', handleGlobalWebSocketEvent)
  console.log('[Sidecar] Global WebSocket listeners removed')
}

/**
 * 高亮新消息
 * @param serial 设备序列号
 * @param messageIds 要高亮的消息 ID 列表
 */
// TODO: Implement message highlighting functionality
// function highlightNewMessages(serial: string, messageIds: number[]) {
//   const panel = ensurePanel(serial)
//
//   if (messageIds.length === 0) return
//
//   // 添加到高亮集合
//   messageIds.forEach(id => panel.highlightedMessageIds.add(id))
//
//   // 清除之前的定时器
//   if (panel.highlightTimer !== null) {
//     clearTimeout(panel.highlightTimer)
//   }
//
//   // 3秒后清除高亮
//   panel.highlightTimer = window.setTimeout(() => {
//     panel.highlightedMessageIds.clear()
//     panel.highlightTimer = null
//   }, 3000)
//
//   console.log(`[Sidecar] Highlighted ${messageIds.length} new messages for ${serial}`)
// }

// Helper function to add log to device logs
function addDeviceLog(
  serial: string,
  level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR',
  message: string
) {
  logStore.addLog(serial, {
    id: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
    level,
    message,
    source: 'system',
  })
}

// Helper function to convert relative image URL to full backend URL
function getImageUrl(imageUrl: string): string {
  if (!imageUrl) return ''
  // If already a full URL, return as-is
  if (imageUrl.startsWith('http://') || imageUrl.startsWith('https://')) {
    return imageUrl
  }
  // Convert /api/sidecar/images?path=... to API_BASE/sidecar/images?path=...
  // Backend endpoint is /sidecar/images, not /api/sidecar/images
  if (imageUrl.startsWith('/api/')) {
    return API_BASE + imageUrl.replace('/api/', '/')
  }
  // Otherwise prepend API_BASE
  return API_BASE + imageUrl
}

// Image preview functions
function openImagePreview(imageUrl: string) {
  previewImageUrl.value = getImageUrl(imageUrl)
}

function closeImagePreview() {
  previewImageUrl.value = null
}

function openVideoPreview(videoId: number, duration?: string | null) {
  previewVideoId.value = videoId
  previewVideoDuration.value = duration ?? null
}

function closeVideoPreview() {
  previewVideoId.value = null
  previewVideoDuration.value = null
}

const countdownDuration = computed(() => {
  const seconds = Number(settings.value.countdownSeconds ?? 10)
  if (Number.isNaN(seconds)) return 10
  return Math.min(30, Math.max(0, seconds))
})

const countdownHint = computed(() =>
  t('sidecar.ready_to_send', { seconds: countdownDuration.value })
)

function ensurePanel(serial: string): PanelState {
  if (!sidecars[serial]) {
    sidecars[serial] = {
      state: null,
      loading: true,
      error: null,
      statusMessage: null,
      pendingMessage: '',
      countdown: null,
      countdownTotal: null,
      countdownTimer: null,
      pollTimer: null,
      baselineHash: null,
      baselineFocus: null,
      initialized: false,
      queuedMessages: [],
      syncQueueState: null,
      currentQueuedMessage: null,
      queueMode: false,
      sendingQueued: false,
      sending: false,
      manuallyPaused: false,
      isEditing: false,
      logsCollapsed: false,
      logsHeight: 256, // Default 256px (h-64)
      aiProcessing: false,
      aiReplySource: null,
      generating: false,
      cachedKefu: null, // Set once on initial load
      originalAiMessage: null, // Stores original AI message before editing
      // Conversation history (always expanded in new layout)
      historyCollapsed: false,
      historyMessages: [],
      historyTotalCount: 0,
      historyLoading: false,
      historyError: null,
      historyHeight: 200, // Default 200px
      historyLastFetched: null,
      historyDbPath: null,
      // New message highlight state
      highlightedMessageIds: new Set<number>(),
      highlightTimer: null,
      // Blacklist state
      isBlacklisted: null,
    }
  }
  return sidecars[serial]
}

async function fetchState(serial: string, forceLoader = false) {
  const panel = ensurePanel(serial)
  const shouldShowLoader = forceLoader || (!panel.initialized && panel.state === null)
  if (shouldShowLoader) {
    panel.loading = true
  }
  try {
    const result = await api.getSidecarState(serial)
    panel.state = result
    panel.error = null
    panel.loading = false
    panel.initialized = true

    // Cache kefu info on first successful load (only set once)
    // PRIORITY: Use device store's kefu info (obtained during device init) first
    // This ensures we use the stable, correctly extracted kefu info
    if (!panel.cachedKefu) {
      const device = deviceStore.devices.find((d) => d.serial === serial)
      if (device?.kefu) {
        panel.cachedKefu = device.kefu
      }
    }

    if (panel.countdown !== null) {
      const currentFocus = (result.focused_text || '').trim()
      const baseline = (panel.baselineFocus || '').trim()
      if (currentFocus && currentFocus !== baseline) {
        pauseCountdown(serial, 'Detected typing on device, countdown paused')
      }
    }

    // Auto-load conversation history on first successful state fetch
    if (panel.historyMessages.length === 0 && result.conversation?.contact_name) {
      fetchConversationHistory(serial)
    }

    // Fetch blacklist status when conversation changes or on first load
    const previousContactName = panel.historyLastFetched?.contactName
    const currentContactName = result.conversation?.contact_name
    if (currentContactName && currentContactName !== previousContactName) {
      fetchBlacklistStatus(serial)
    }
  } catch (e) {
    panel.error = e instanceof Error ? e.message : 'Failed to load sidecar state'
    panel.loading = false
  }
}

async function fetchQueueState(serial: string) {
  const panel = ensurePanel(serial)
  try {
    const result = await api.getSidecarQueueState(serial)
    panel.queuedMessages = result.queue
    panel.syncQueueState = result.syncState

    // Find current ready message
    const readyMessage = result.queue.find((m) => m.status === 'ready')

    if (readyMessage) {
      // New ready message detected
      if (readyMessage.id !== panel.currentQueuedMessage?.id) {
        // Reset countdown and state flags for new message
        clearCountdown(serial)
        panel.manuallyPaused = false
        panel.isEditing = false
        panel.currentQueuedMessage = readyMessage
        panel.queueMode = true

        // Add source to status message
        const sourceLabel =
          readyMessage.source === 'followup'
            ? 'FollowUp'
            : readyMessage.source === 'sync'
              ? 'Sync'
              : 'Manual'
        panel.statusMessage = `${sourceLabel} message for ${readyMessage.customerName}${readyMessage.channel ? ` (${readyMessage.channel})` : ''}`

        // Message already has correct content from backend (AI reply if enabled, or mock message)
        // No frontend AI processing needed - backend handles it before queuing
        panel.pendingMessage = readyMessage.message

        // Store original AI message for learning comparison
        panel.originalAiMessage = readyMessage.message

        // Log what type of message we received (check if it looks like AI reply or mock)
        const isAIReply = !readyMessage.message.startsWith('Test message:')
        if (settings.value.useAIReply) {
          panel.aiReplySource = isAIReply ? 'ai' : 'fallback'
          addDeviceLog(
            serial,
            'INFO',
            `[${isAIReply ? 'AI' : 'Fallback'}] Message ready for ${readyMessage.customerName}`
          )
        } else {
          panel.aiReplySource = 'mock'
          addDeviceLog(serial, 'INFO', `[Mock] Message ready for ${readyMessage.customerName}`)
        }

        // Refresh conversation history when new message is detected (conversation may have changed)
        refreshConversationHistory(serial)
        fetchBlacklistStatus(serial)
      }

      // Auto-start countdown if not paused, not manually paused, not editing, and no active countdown
      if (
        !panel.sendingQueued &&
        !result.syncState?.paused &&
        !panel.manuallyPaused &&
        !panel.isEditing &&
        panel.countdown === null
      ) {
        startCountdown(serial, true /* force */)
      }
    } else {
      // No ready message
      panel.currentQueuedMessage = null
      panel.queueMode = result.queue.some((m) => m.status === 'pending')
      if (!panel.queueMode) {
        fetchBlacklistStatus(serial)
      }
    }
  } catch (e) {
    // Silently fail queue polling - not critical
    console.error(`Failed to fetch queue state for ${serial}:`, e)
  }
}

async function fetchFollowUpStatus(serial: string) {
  try {
    const response = await fetch(`http://localhost:8765/api/realtime/device/${serial}/status`)
    if (response.ok) {
      const status: FollowUpDeviceStatus = await response.json()
      followUpStatus[serial] = status
    } else {
      // Device not found or error - set to idle
      followUpStatus[serial] = {
        serial,
        status: 'idle',
        message: 'No follow-up process',
        responses_detected: 0,
        replies_sent: 0,
        started_at: null,
        last_scan_at: null,
        errors: [],
      }
    }
  } catch (e) {
    // On error, assume idle
    console.error(`Failed to fetch follow-up status for ${serial}:`, e)
    followUpStatus[serial] = {
      serial,
      status: 'idle',
      message: 'No follow-up process',
      responses_detected: 0,
      replies_sent: 0,
      started_at: null,
      last_scan_at: null,
      errors: [],
    }
  }
}

async function fetchConversationHistory(serial: string) {
  const panel = ensurePanel(serial)

  const { contactName, channel } = getActiveConversationTarget(panel)

  // Skip if no conversation context
  if (!contactName && !channel) {
    panel.historyMessages = []
    panel.historyTotalCount = 0
    panel.historyError = null
    panel.historyLastFetched = null
    panel.historyDbPath = null
    return
  }

  // Skip if we already fetched for this conversation
  if (
    panel.historyLastFetched &&
    panel.historyLastFetched.contactName === contactName &&
    panel.historyLastFetched.channel === channel &&
    panel.historyMessages.length > 0
  ) {
    return
  }

  panel.historyLoading = true
  panel.historyError = null
  try {
    const result = await api.getConversationHistory(serial, {
      contactName: contactName || undefined,
      channel: channel || undefined,
      kefuName: panel.state?.kefu?.name || undefined,
      limit: 100,
      dbPath: sidecarConversationHistoryDbOverride.value,
    })

    if (result.success) {
      panel.historyMessages = result.messages
      panel.historyTotalCount = result.total_messages
      panel.historyError = result.error || null
      panel.historyLastFetched = { contactName, channel }
      panel.historyDbPath = result.db_path ?? null
      // Auto scroll to bottom after loading
      scrollToBottom(serial)
    } else {
      panel.historyMessages = []
      panel.historyTotalCount = 0
      panel.historyDbPath = null
      panel.historyError = result.error || 'Failed to load conversation history'
      console.error(`Failed to fetch conversation history for ${serial}:`, result.error)
    }
  } catch (e) {
    console.error(`Failed to fetch conversation history for ${serial}:`, e)
    panel.historyMessages = []
    panel.historyTotalCount = 0
    panel.historyDbPath = null
    panel.historyError = e instanceof Error ? e.message : 'Failed to load conversation history'
  } finally {
    panel.historyLoading = false
  }
}

async function refreshConversationHistory(serial: string) {
  const panel = ensurePanel(serial)
  // Clear last fetched to force refresh
  panel.historyLastFetched = null

  // FIX: 始终刷新 UI 状态，确保获取最新的 contact_name
  // 这对于 WebSocket 事件触发的刷新尤其重要
  await fetchState(serial, false)

  await fetchConversationHistory(serial)
}

async function sendQueuedMessage(serial: string) {
  const panel = ensurePanel(serial)
  if (!panel.currentQueuedMessage) return

  clearCountdown(serial)
  panel.sendingQueued = true
  panel.sending = true
  panel.manuallyPaused = false
  panel.isEditing = false
  panel.statusMessage = t('sidecar.sending')

  try {
    // Get the edited message from the input field
    const editedMessage = panel.pendingMessage.trim()
    const originalMessage = panel.currentQueuedMessage.message
    const wasEdited = editedMessage !== originalMessage

    // Pass the edited message if it's different from the original
    const messageToSend = wasEdited ? editedMessage : undefined

    const result = await api.sendQueuedMessage(serial, panel.currentQueuedMessage.id, messageToSend)
    if (result.success) {
      // Record admin action for AI learning
      // Only record if this was an AI-generated message (has originalAiMessage)
      if (panel.originalAiMessage) {
        const actionType = wasEdited ? 'EDIT' : 'APPROVE'
        const reason = wasEdited
          ? `Operator edited AI reply (original: ${originalMessage.length}, new: ${editedMessage.length})`
          : 'Operator approved AI reply'

        await recordAdminAction(
          serial,
          actionType,
          panel.originalAiMessage, // Original AI-generated content
          wasEdited ? editedMessage : undefined,
          reason
        )

        // Log for visibility
        if (wasEdited) {
          console.log(
            `[AI Learning] Recorded edit: length change ${editedMessage.length - originalMessage.length}`
          )
        }
      }

      panel.statusMessage = t('sidecar.sent')
      panel.currentQueuedMessage = null
      panel.pendingMessage = ''
      panel.originalAiMessage = null // Clear original AI message

      // Fetch updated state
      await fetchQueueState(serial)
      await fetchState(serial)

      // Refresh history after sending and scroll to bottom
      setTimeout(() => {
        refreshConversationHistory(serial)
      }, 500)
    } else {
      panel.statusMessage = result.detail || t('sidecar.send_failed')
    }
  } catch (e) {
    panel.statusMessage = e instanceof Error ? e.message : t('sidecar.send_failed')
  } finally {
    panel.sendingQueued = false
    panel.sending = false
  }
}

function clearCountdown(serial: string) {
  const panel = ensurePanel(serial)
  if (panel.countdownTimer !== null) {
    clearInterval(panel.countdownTimer)
    panel.countdownTimer = null
  }
  panel.countdown = null
  panel.countdownTotal = null
  panel.baselineHash = null
  panel.baselineFocus = null
}

function countdownProgress(panel: PanelState) {
  if (!panel || panel.countdown === null || !panel.countdownTotal) return 0
  const completed = panel.countdownTotal - panel.countdown
  return Math.min(100, Math.max(0, (completed / panel.countdownTotal) * 100))
}

function pauseCountdown(serial: string, reason?: string) {
  const panel = ensurePanel(serial)
  clearCountdown(serial)
  if (reason) {
    panel.statusMessage = reason
  }
}

// Handle message editing events
function handleMessageFocus(serial: string) {
  const panel = ensurePanel(serial)
  if (panel.queueMode && panel.currentQueuedMessage) {
    // User started editing - pause countdown
    panel.isEditing = true
    if (panel.countdown !== null) {
      clearCountdown(serial)
      panel.statusMessage = t('sidecar.editing_paused')
    }
  }
}

function handleMessageInput(serial: string) {
  const panel = ensurePanel(serial)
  if (panel.queueMode && panel.currentQueuedMessage) {
    // User is editing - ensure countdown is paused
    panel.isEditing = true
    if (panel.countdown !== null) {
      clearCountdown(serial)
      panel.statusMessage = t('sidecar.editing_paused')
    }
  }
}

function handleMessageBlur(serial: string) {
  const panel = ensurePanel(serial)
  // Don't auto-resume - user needs to click Resume button
  // Just mark as not actively editing
  if (panel.isEditing) {
    panel.statusMessage = t('sidecar.edit_done')
  }
}

function startCountdown(serial: string, force = false) {
  const panel = ensurePanel(serial)
  if (!panel.pendingMessage.trim()) {
    panel.statusMessage = t('sidecar.no_content')
    return
  }

  // Don't start countdown if sync queue is paused (unless force)
  if (!force && panel.syncQueueState?.paused) {
    panel.statusMessage = t('sidecar.sync_queue_paused')
    return
  }

  // If a countdown is already running for the same message, skip
  if (!force && panel.countdown !== null && panel.currentQueuedMessage) {
    return
  }

  clearCountdown(serial)

  const duration = countdownDuration.value
  if (duration <= 0) {
    panel.statusMessage = t('sidecar.sending_immediate')
    void sendNow(serial)
    return
  }

  panel.baselineHash = panel.state?.tree_hash || null
  panel.baselineFocus = panel.state?.focused_text || null
  panel.countdownTotal = duration
  panel.countdown = duration
  panel.statusMessage = t('sidecar.countdown_started', { seconds: duration })

  panel.countdownTimer = window.setInterval(() => {
    if (panel.countdown === null) return
    // Check if paused during countdown
    if (panel.syncQueueState?.paused) {
      pauseCountdown(serial, 'Sync queue paused')
      return
    }
    if (panel.countdown <= 1) {
      clearCountdown(serial)
      void sendNow(serial)
    } else {
      panel.countdown = (panel.countdown || 0) - 1
    }
  }, 1000)
}

async function sendNow(serial: string) {
  const panel = ensurePanel(serial)
  const message = panel.pendingMessage.trim()
  if (!message) {
    panel.statusMessage = t('sidecar.no_content')
    return
  }

  clearCountdown(serial)
  panel.statusMessage = t('sidecar.sending')

  // If we're in queue mode with a current queued message, send via queue API immediately
  if (panel.queueMode && panel.currentQueuedMessage) {
    await sendQueuedMessage(serial)
    return
  }

  panel.sending = true
  const originalMessage = panel.originalAiMessage
  const wasEdited = originalMessage && originalMessage !== message

  try {
    // Check if sync is running for this device
    const syncStatus = deviceStore.getSyncStatus(serial)
    const isSyncRunning = syncStatus && ['running', 'starting'].includes(syncStatus.status)

    if (isSyncRunning) {
      // Use send-and-save API to ensure message is recorded in database
      // even if sync is interrupted or hasn't reached this conversation yet
      const contactName = panel.state?.conversation?.contact_name
      const channel = panel.state?.conversation?.channel
      const kefuName = panel.state?.kefu?.name

      panel.statusMessage = 'Sending in sync mode, will auto-save...'
      const result = await api.sendAndSaveMessage(
        serial,
        message,
        contactName ?? undefined,
        channel ?? undefined,
        kefuName ?? undefined
      )

      if (!result.success) {
        panel.statusMessage = result.detail || 'Send failed'
        return
      }

      // Record admin action for learning (only for AI-generated messages)
      if (originalMessage) {
        await recordAdminAction(
          serial,
          wasEdited ? 'EDIT' : 'APPROVE',
          originalMessage,
          wasEdited ? message : undefined
        )
      }

      panel.pendingMessage = ''
      panel.originalAiMessage = null
      panel.statusMessage = result.message_saved ? 'Sent and saved' : 'Sent (not saved to database)'
    } else {
      // Normal send without saving (will be captured in next sync)
      const result = await api.sendSidecarMessage(serial, message)
      if (!result.success) {
        panel.statusMessage = result.detail || 'Send failed'
        return
      }

      // Record admin action for learning (only for AI-generated messages)
      if (originalMessage) {
        await recordAdminAction(
          serial,
          wasEdited ? 'EDIT' : 'APPROVE',
          originalMessage,
          wasEdited ? message : undefined
        )
      }

      panel.pendingMessage = ''
      panel.originalAiMessage = null
      panel.statusMessage = 'Sent'
    }

    await fetchState(serial)

    // Refresh history after sending and scroll to bottom
    setTimeout(() => {
      refreshConversationHistory(serial)
    }, 500) // Small delay to ensure message is saved
  } catch (e) {
    panel.statusMessage = e instanceof Error ? e.message : 'Send failed'
  } finally {
    panel.sending = false
  }
}

// Record admin action for AI learning
async function recordAdminAction(
  serial: string,
  actionType: 'EDIT' | 'CANCEL' | 'APPROVE',
  originalContent: string,
  modifiedContent?: string,
  reason?: string
) {
  try {
    const panel = ensurePanel(serial)
    const customerName = panel.state?.conversation?.contact_name || 'Unknown'

    await api.recordAdminAction({
      message_id: `sidecar_${serial}_${Date.now()}`,
      action_type: actionType,
      original_content: originalContent,
      modified_content: modifiedContent,
      reason,
      admin_id: 'sidecar_operator',
      serial,
      customer_name: customerName,
    })

    console.log(`[Learning] Recorded ${actionType} action for ${serial}`)
  } catch (e) {
    // Don't interrupt flow if recording fails
    console.error('Failed to record admin action:', e)
  }
}

const pollIntervalMs = computed(() => {
  const seconds = Number(settings.value.sidecarPollInterval ?? 10)
  if (Number.isNaN(seconds) || seconds <= 0) return 0 // disabled
  return Math.min(20, Math.max(1, seconds)) * 1000
})

function startPolling(serial: string) {
  const panel = ensurePanel(serial)
  stopPolling(serial)
  // First fetch with loader
  if (!panel.sending) {
    fetchState(serial, true)
    fetchQueueState(serial)
    fetchFollowUpStatus(serial) // Also fetch follow-up status
  }
  // If poll interval is 0, no periodic polling (only manual/event-driven refresh)
  const interval = pollIntervalMs.value
  if (interval <= 0) return

  // Counter for periodic history refresh (every 3 polls)
  let pollCount = 0

  panel.pollTimer = window.setInterval(() => {
    if (document.visibilityState === 'hidden') {
      return
    }
    if (panel.sending) {
      return
    }
    fetchState(serial, false)
    fetchQueueState(serial)
    fetchFollowUpStatus(serial) // Also fetch follow-up status periodically

    // Refresh history every 3 polls during sync to keep it updated
    pollCount++
    if (pollCount >= 3) {
      pollCount = 0
      // Only refresh if sync is running
      const syncStatus = deviceStore.getSyncStatus(serial)
      if (syncStatus && ['running', 'starting'].includes(syncStatus.status)) {
        refreshConversationHistory(serial)
      }
    }
  }, interval)
}

function stopPolling(serial: string) {
  const panel = ensurePanel(serial)
  if (panel.pollTimer !== null) {
    clearInterval(panel.pollTimer)
    panel.pollTimer = null
  }
  clearCountdown(serial)
}

function addPanel(serial: string, setFocus = true) {
  if (!serial) return
  if (!panels.value.includes(serial)) {
    if (panels.value.length >= maxPanels.value) {
      dropMessage.value = `Maximum ${maxPanels.value} sidecar panels`
      return
    }
    panels.value = [...panels.value, serial]

    // Try to get kefu info from device store immediately
    const panel = ensurePanel(serial)
    const device = deviceStore.devices.find((d) => d.serial === serial)
    if (device?.kefu && !panel.cachedKefu) {
      panel.cachedKefu = device.kefu
    }

    startPolling(serial)
    // Only connect log stream if logs panel is enabled
    if (showLogs.value) {
      logStore.connectLogStream(serial)
    }
  }
  if (setFocus) {
    focusedSerial.value = serial
  }
}

function removePanel(serial: string) {
  panels.value = panels.value.filter((s) => s !== serial)
  stopPolling(serial)
  logStore.disconnectLogStream(serial)
  if (focusedSerial.value === serial) {
    focusedSerial.value = panels.value[0] ?? null
  }
}

function selectDevice(serial: string) {
  addPanel(serial, true)
}

function handleDragStart(serial: string, event: DragEvent) {
  event.dataTransfer?.setData(SIDECAR_DRAG_MIME, serial)
  event.dataTransfer?.setData('text/plain', serial)
  dropMessage.value = 'Drop to open sidecar side-by-side'
}

function handleDragOver(event: DragEvent) {
  event.preventDefault()
  const hasDeviceData = event.dataTransfer?.types?.includes(SIDECAR_DRAG_MIME)
  isDragOver.value = !!hasDeviceData && panels.value.length < maxPanels.value
}

function handleDragLeave() {
  isDragOver.value = false
}

function handleDrop(event: DragEvent) {
  event.preventDefault()
  isDragOver.value = false

  const serial = event.dataTransfer?.getData(SIDECAR_DRAG_MIME)
  if (!serial) return

  if (!availableDevices.value.includes(serial)) {
    console.warn(`[Sidecar] Rejected drop: "${serial}" is not a known device serial`)
    return
  }

  addPanel(serial, focusedSerial.value === null)
}

function isMirroring(serial: string) {
  return deviceStore.getMirrorStatus(serial)
}

function getSyncProgress(serial: string) {
  return deviceStore.getSyncStatus(serial)
}

// Check if follow-up is running for this device
function isFollowUpRunning(serial: string) {
  const status = followUpStatus[serial]
  return status && ['running', 'starting'].includes(status.status)
}

// Check if we should show progress controls (sync or follow-up running)
function shouldShowProgressControls(serial: string) {
  const syncStatus = getSyncProgress(serial)
  const syncRunning = syncStatus && ['running', 'starting', 'paused'].includes(syncStatus.status)
  const followUpRunning = isFollowUpRunning(serial)
  return syncRunning || followUpRunning
}

// Get the type of progress control: 'sync' or 'followup'
function getProgressControlType(serial: string) {
  if (isFollowUpRunning(serial)) return 'followup'
  const syncStatus = getSyncProgress(serial)
  if (syncStatus && ['running', 'starting', 'paused'].includes(syncStatus.status)) return 'sync'
  return null
}

// Get the appropriate progress message
function getProgressControlMessage(serial: string) {
  const type = getProgressControlType(serial)
  if (type === 'followup') {
    const status = followUpStatus[serial]
    if (!status) return 'Follow-up'
    return (
      status.message ||
      `Follow-up (${status.responses_detected} responses, ${status.replies_sent} replies)`
    )
  }
  const syncStatus = getSyncProgress(serial)
  return syncStatus?.message || 'Sync'
}

async function startDeviceSync(serial: string) {
  const panel = ensurePanel(serial)
  panel.statusMessage = 'Starting sync...'

  try {
    // Pause followup system before starting sync (store handles auto-resume when sync completes)
    await deviceStore.pauseFollowupForSync([serial])

    await deviceStore.startSync([serial], {
      send_via_sidecar: settings.value.sendViaSidecar,
      countdown_seconds: settings.value.countdownSeconds,
      timing_multiplier: settings.value.timingMultiplier,
      auto_placeholder: settings.value.autoPlaceholder,
      no_test_messages: settings.value.noTestMessages,
      use_ai_reply: settings.value.useAIReply,
      ai_server_url: settings.value.aiServerUrl,
      ai_reply_timeout: settings.value.aiReplyTimeout,
      system_prompt: settingsStore.combinedSystemPrompt,
    })
    panel.statusMessage = 'Sync started (followup paused)'
  } catch (e) {
    panel.statusMessage = e instanceof Error ? e.message : 'Failed to start sync'
  }
}

async function skipDeviceSync(serial: string) {
  console.log('[Skip] skipDeviceSync called for serial:', serial)
  skipLoading[serial] = true
  const panel = ensurePanel(serial)
  panel.statusMessage = 'Skipping current user...'

  // Check if this is sync or follow-up
  const controlType = getProgressControlType(serial)
  console.log('[Skip] Control type:', controlType)

  try {
    if (controlType === 'followup') {
      // Use follow-up skip API
      console.log('[Skip] Calling follow-up skip API...')
      const response = await fetch(`http://localhost:8765/api/realtime/device/${serial}/skip`, {
        method: 'POST',
      })

      if (response.ok) {
        const result = await response.json()
        if (result.success) {
          // Clear local state to prevent stale message in input box
          // Without this, the old message stays in the input and can cause
          // a double-send when the next user's message is queued
          panel.currentQueuedMessage = null
          panel.pendingMessage = ''
          panel.queueMode = false
          panel.originalAiMessage = null
          clearCountdown(serial)
          console.log('[Skip] Follow-up local state cleared')

          panel.statusMessage = '✅ Skip requested - follow-up will skip this scan'
          console.log('[Skip] Follow-up skip requested successfully')

          // Wait a bit for the backend to handle the skip
          await new Promise((resolve) => setTimeout(resolve, 500))

          // Refresh state to reflect the skip
          await fetchState(serial, false)
          await fetchQueueState(serial)
        } else {
          panel.statusMessage = result.message || 'Skip request failed'
        }
      } else {
        const error = await response.json()
        panel.statusMessage = error.detail || 'Skip request failed'
      }
    } else {
      // Use sync skip API (original logic)
      console.log('[Skip] Calling sync skip API...')
      const result = await api.requestSkip(serial)
      console.log('[Skip] API returned:', result)

      if (result.success) {
        // Clear local state
        panel.statusMessage = '⏭️ Skip requested - returning to chat list...'
        panel.currentQueuedMessage = null
        panel.pendingMessage = ''
        panel.queueMode = false
        panel.originalAiMessage = null
        clearCountdown(serial) // Clear the countdown progress bar
        console.log('[Skip] Local state cleared')

        // Wait a bit for the sync process to handle the skip
        await new Promise((resolve) => setTimeout(resolve, 500))

        // Refresh state to reflect the skip
        await fetchState(serial, false)
        await fetchQueueState(serial)

        panel.statusMessage = '✅ User skipped'
        console.log('[Skip] Done!')
      } else {
        panel.statusMessage = 'Skip request failed'
      }
    }
  } catch (e) {
    console.error('[Skip] Error:', e)
    panel.statusMessage = e instanceof Error ? e.message : 'Failed to skip'
  } finally {
    skipLoading[serial] = false
    console.log('[Skip] Finally block executed')
  }
}

async function fetchBlacklistStatus(serial: string) {
  const panel = ensurePanel(serial)
  const { contactName, channel } = getActiveConversationTarget(panel)

  if (!contactName) {
    panel.isBlacklisted = null
    return
  }

  try {
    const result = await api.checkBlacklistStatus({
      device_serial: serial,
      customer_name: contactName,
      customer_channel: channel || undefined,
    })

    panel.isBlacklisted = result.is_blacklisted
  } catch (e) {
    console.error('[Sidecar] Failed to fetch blacklist status:', e)
    panel.isBlacklisted = null
  }
}

async function toggleBlockUser(serial: string) {
  const panel = ensurePanel(serial)
  blockLoading[serial] = true

  try {
    await toggleBlockUserForPanel({
      serial,
      panel,
      apiClient: api,
      t,
      addDeviceLog,
      skipCurrentUser: skipDeviceSync,
      refreshBlacklistStatus: fetchBlacklistStatus,
    })
  } finally {
    blockLoading[serial] = false
  }
}

async function stopDeviceSync(serial: string) {
  if (
    !confirm(
      t(
        'sidecar.stop_confirm',
        {},
        'Are you sure you want to STOP synchronization for this device?'
      )
    )
  ) {
    return
  }

  const panel = ensurePanel(serial)
  stopLoading[serial] = true
  panel.statusMessage = t('sidecar.stopping', {}, 'Stopping sync...')

  try {
    await deviceStore.stopSync(serial)
    panel.statusMessage = t('sidecar.stopped', {}, 'Sync stopped')
    addDeviceLog(serial, 'INFO', '[Sync] 用户手动停止了同步')
  } catch (e) {
    panel.statusMessage =
      e instanceof Error ? e.message : t('sidecar.stop_failed', {}, 'Failed to stop sync')
    addDeviceLog(serial, 'ERROR', `[Sync] 停止同步失败: ${e}`)
  } finally {
    stopLoading[serial] = false
  }
}

async function pauseDeviceSync(serial: string) {
  const panel = ensurePanel(serial)
  panel.statusMessage = 'Pausing sync...'

  try {
    await deviceStore.pauseSync(serial)
    panel.statusMessage = 'Sync paused'
  } catch (e) {
    panel.statusMessage = e instanceof Error ? e.message : 'Failed to pause sync'
  }
}

async function resumeDeviceSync(serial: string) {
  const panel = ensurePanel(serial)
  panel.statusMessage = 'Resuming sync...'

  try {
    await deviceStore.resumeSync(serial)
    panel.statusMessage = 'Sync resumed'
  } catch (e) {
    panel.statusMessage = e instanceof Error ? e.message : 'Failed to resume sync'
  }
}

function clearDeviceSyncStatus(serial: string) {
  deviceStore.clearSyncStatus(serial)
  const panel = ensurePanel(serial)
  panel.statusMessage = null
}

async function toggleMirror(serial: string) {
  mirrorLoading[serial] = true
  const panel = ensurePanel(serial)

  try {
    if (isMirroring(serial)) {
      await deviceStore.stopMirror(serial)
      panel.statusMessage = 'Mirror stopped'
    } else {
      const success = await deviceStore.startMirror(serial)
      panel.statusMessage = success ? 'Mirror started' : 'Mirror failed to start'
    }
  } catch (e) {
    panel.statusMessage = e instanceof Error ? e.message : 'Mirror action failed'
  } finally {
    mirrorLoading[serial] = false
  }
}

async function generateReply(serial: string) {
  const panel = ensurePanel(serial)

  if (panel.generating) return

  panel.generating = true
  panel.statusMessage = 'Getting last message...'
  panel.aiReplySource = null

  try {
    // Get the last message from the conversation
    const lastMsgResponse = await api.getLastMessage(serial)

    if (!lastMsgResponse.success || !lastMsgResponse.last_message) {
      panel.statusMessage = lastMsgResponse.error || 'Failed to get last message'
      return
    }

    const lastMsg = lastMsgResponse.last_message
    const isFollowUp = lastMsg.is_from_kefu // If kefu sent last message, it's a follow-up (follow-up mode)

    addDeviceLog(
      serial,
      'INFO',
      `[Generate] Last message is ${isFollowUp ? 'follow-up' : 'reply'}: ${lastMsg.content?.slice(0, 30) || '[media]'}...`
    )

    // Check if customer sent a voice message (not kefu)
    if (!lastMsg.is_from_kefu && lastMsg.message_type === 'voice') {
      const customerName = panel.state?.conversation?.contact_name || 'Unknown'
      const channel = panel.state?.conversation?.channel || undefined
      addDeviceLog(serial, 'WARNING', `[Voice] 🎤 Customer ${customerName} sent a voice message!`)

      // Check settings and report to backend (add to blacklist and send email if enabled)
      if (settings.value.emailNotifyOnVoice) {
        try {
          const result = await api.reportVoiceMessage(customerName, serial, channel)
          addDeviceLog(serial, 'INFO', `[Voice] ${result.message}`)
          panel.statusMessage = '🎤 User sent voice, skipped and blacklisted'
          panel.pendingMessage = ''
          panel.generating = false
          return
        } catch (e) {
          addDeviceLog(
            serial,
            'ERROR',
            `[Voice] Failed to report: ${e instanceof Error ? e.message : 'unknown'}`
          )
        }
      }
    }

    // Build the test message format that the sync uses
    let testMessage: string
    if (isFollowUp) {
      testMessage = 'Test message: How are you thinking?'
    } else {
      const content = lastMsg.content || '[media]'
      testMessage = `Test message: [...${content.slice(0, 30)}...]`
    }

    // Check if AI reply is enabled
    if (settings.value.useAIReply) {
      panel.statusMessage = 'Generating AI reply...'
      panel.aiProcessing = true

      try {
        // Get recent conversation history for context (max 10 messages)
        await fetchConversationHistory(serial)
        const conversationHistory = panel.historyMessages
          .slice(-10) // Get last 10 messages
          .map((msg) => ({
            content: msg.content || '',
            is_from_kefu: msg.is_from_kefu,
          }))
          .filter((msg) => msg.content) // Filter out empty messages

        addDeviceLog(serial, 'INFO', `[AI] Using ${conversationHistory.length} messages as context`)

        const aiResult = await aiService.processTestMessage(
          testMessage,
          settings.value.aiServerUrl,
          settings.value.aiReplyTimeout,
          serial,
          settingsStore.combinedSystemPrompt,
          conversationHistory
        )

        // Check if user requested human agent
        if (aiResult.humanRequested) {
          panel.pendingMessage = ''
          panel.aiReplySource = 'fallback'
          panel.statusMessage = '🙋 User requested human agent, skipped and blacklisted'
          addDeviceLog(serial, 'WARNING', `[AI] 🙋 User requested human agent!`)

          // Report to backend (add to blacklist and send email if enabled)
          const customerName = panel.state?.conversation?.contact_name || 'Unknown'
          const channel = panel.state?.conversation?.channel || undefined
          try {
            const result = await api.reportHumanRequest(
              customerName,
              serial,
              channel,
              'AI detected user wants human agent'
            )
            addDeviceLog(serial, 'INFO', `[Blacklist] ${result.message}`)
          } catch (e) {
            addDeviceLog(
              serial,
              'ERROR',
              `[Blacklist] Failed to report: ${e instanceof Error ? e.message : 'unknown'}`
            )
          }

          // Skip to next customer (don't send any reply)
          panel.aiProcessing = false
          return
        }

        if (aiResult.success && aiResult.reply) {
          panel.pendingMessage = aiResult.reply
          panel.originalAiMessage = aiResult.reply // Save original for learning tracking
          panel.aiReplySource = 'ai'
          panel.statusMessage = `AI reply generated (${aiResult.timing.durationMs}ms)`
          addDeviceLog(serial, 'INFO', `[AI] ✅ Generated: ${aiResult.reply.slice(0, 50)}...`)
        } else {
          // Fallback to mock message
          panel.pendingMessage = testMessage
          panel.aiReplySource = 'fallback'
          panel.statusMessage = `AI failed, using mock: ${aiResult.error || 'unknown error'}`
          addDeviceLog(serial, 'WARNING', `[AI] ⚠️ Fallback to mock: ${aiResult.error}`)
        }
      } finally {
        panel.aiProcessing = false
      }
    } else {
      // Use mock message directly
      panel.pendingMessage = testMessage
      panel.aiReplySource = 'mock'
      panel.statusMessage = 'Mock message generated'
      addDeviceLog(serial, 'INFO', `[Mock] Generated: ${testMessage}`)
    }
  } catch (e) {
    panel.statusMessage = e instanceof Error ? e.message : 'Failed to generate reply'
    addDeviceLog(
      serial,
      'ERROR',
      `[Generate] Error: ${e instanceof Error ? e.message : 'unknown error'}`
    )
  } finally {
    panel.generating = false
  }
}

async function startQuickSync() {
  if (!syncTargetSerial.value) {
    syncActionMessage.value = 'No device available to sync'
    return
  }

  syncLoading.value = true
  syncActionMessage.value = `Starting sync for ${syncTargetSerial.value}...`

  try {
    // Pause followup system before starting sync (store handles auto-resume when sync completes)
    await deviceStore.pauseFollowupForSync([syncTargetSerial.value])

    await deviceStore.startSync([syncTargetSerial.value], {
      send_via_sidecar: settings.value.sendViaSidecar,
      countdown_seconds: settings.value.countdownSeconds,
      timing_multiplier: settings.value.timingMultiplier,
      auto_placeholder: settings.value.autoPlaceholder,
      no_test_messages: settings.value.noTestMessages,
      // AI Reply settings
      use_ai_reply: settings.value.useAIReply,
      ai_server_url: settings.value.aiServerUrl,
      ai_reply_timeout: settings.value.aiReplyTimeout,
      system_prompt: settingsStore.combinedSystemPrompt,
    })
    syncActionMessage.value = `Sync started for ${syncTargetSerial.value} (followup paused)`
  } catch (e) {
    syncActionMessage.value = e instanceof Error ? e.message : 'Failed to start sync'
  } finally {
    syncLoading.value = false
  }
}

function customerLabel(state: SidecarState | null) {
  const contact = state?.conversation?.contact_name
  const channel = state?.conversation?.channel
  if (contact && channel) return `${contact} (${channel})`
  return contact || channel || 'Unknown'
}

function formatHistoryTime(msg: ConversationHistoryMessage): string {
  const ts = msg.timestamp_parsed || msg.created_at
  if (!ts) return ''
  try {
    const date = new Date(ts)
    const now = new Date()
    const isToday = date.toDateString() === now.toDateString()
    const isThisYear = date.getFullYear() === now.getFullYear()

    if (isToday) {
      return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    } else if (isThisYear) {
      return date.toLocaleDateString('zh-CN', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    } else {
      return date.toLocaleDateString('zh-CN', { year: 'numeric', month: 'short', day: 'numeric' })
    }
  } catch {
    return ts
  }
}

function exportLogs(serial: string) {
  const logs = logStore.getDeviceLogs(serial)
  if (logs.length === 0) return

  const content = logs.map((log) => `[${log.timestamp}] [${log.level}] ${log.message}`).join('\n')

  const blob = new Blob([content], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `wecom-logs-${serial}-${Date.now()}.txt`
  a.click()
  URL.revokeObjectURL(url)
}

// Logs resize handlers
function startLogsResize(serial: string, event: MouseEvent) {
  event.preventDefault()
  const panel = ensurePanel(serial)
  resizingSerial.value = serial
  resizeStartY.value = event.clientY
  resizeStartHeight.value = panel.logsHeight

  document.addEventListener('mousemove', handleLogsResize)
  document.addEventListener('mouseup', stopLogsResize)
  document.body.style.cursor = 'ns-resize'
  document.body.style.userSelect = 'none'
}

function handleLogsResize(event: MouseEvent) {
  if (!resizingSerial.value) return

  const panel = sidecars[resizingSerial.value]
  if (!panel) return

  // Dragging up increases height, dragging down decreases
  const deltaY = resizeStartY.value - event.clientY
  const newHeight = Math.max(32, Math.min(500, resizeStartHeight.value + deltaY))
  panel.logsHeight = newHeight

  // Auto-expand if resized from collapsed state
  if (panel.logsCollapsed && newHeight > 32) {
    panel.logsCollapsed = false
  }
}

function stopLogsResize() {
  resizingSerial.value = null
  document.removeEventListener('mousemove', handleLogsResize)
  document.removeEventListener('mouseup', stopLogsResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

function handleHistoryResize(event: MouseEvent) {
  if (!resizingHistorySerial.value) return

  const panel = sidecars[resizingHistorySerial.value]
  if (!panel) return

  // Dragging up increases height, dragging down decreases
  const deltaY = resizeHistoryStartY.value - event.clientY
  const newHeight = Math.max(32, Math.min(400, resizeHistoryStartHeight.value + deltaY))
  panel.historyHeight = newHeight

  // Auto-expand if resized from collapsed state
  if (panel.historyCollapsed && newHeight > 32) {
    panel.historyCollapsed = false
    // Fetch history when expanding via resize
    if (panel.historyMessages.length === 0) {
      fetchConversationHistory(resizingHistorySerial.value)
    }
  }
}

function stopHistoryResize() {
  resizingHistorySerial.value = null
  document.removeEventListener('mousemove', handleHistoryResize)
  document.removeEventListener('mouseup', stopHistoryResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

onMounted(() => {
  settingsStore.load()
  void deviceStore.fetchDevices()

  // Setup global WebSocket for real-time updates
  setupGlobalWebSocket()

  // Check for multiple devices passed via query param
  const devicesQuery = route.query.devices as string | undefined
  if (devicesQuery) {
    const deviceSerials = devicesQuery.split(',').filter((s) => s.trim())
    deviceSerials.forEach((serial, index) => {
      addPanel(serial.trim(), index === 0) // Focus first panel only
    })
  } else if (route.params.serial) {
    addPanel(route.params.serial as string)
  }
})

watch(
  () => route.params.serial,
  (newSerial) => {
    if (newSerial) {
      addPanel(newSerial as string)
    }
  }
)

// Restart polling when poll interval setting changes
watch(pollIntervalMs, () => {
  panels.value.forEach((serial) => startPolling(serial))
})

// Update cached kefu info when device store gets updated with kefu
watch(
  () => deviceStore.devices,
  (devices) => {
    for (const serial of panels.value) {
      const panel = sidecars[serial]
      if (panel && !panel.cachedKefu) {
        const device = devices.find((d) => d.serial === serial)
        if (device?.kefu) {
          panel.cachedKefu = device.kefu
        }
      }
    }
  },
  { deep: true }
)

// Auto-fetch conversation history when conversation changes
watch(
  () => {
    // Build a snapshot of conversation contacts for open panels
    const conversations: Record<string, { contactName: string | null; channel: string | null }> = {}
    for (const serial of panels.value) {
      const panel = sidecars[serial]
      if (panel?.state?.conversation) {
        conversations[serial] = {
          contactName: panel.state.conversation.contact_name || null,
          channel: panel.state.conversation.channel || null,
        }
      }
    }
    return conversations
  },
  (newConversations, oldConversations) => {
    for (const serial of panels.value) {
      const newConv = newConversations[serial]
      const oldConv = oldConversations?.[serial]
      const panel = sidecars[serial]

      // If conversation changed, refresh history
      if (
        panel &&
        newConv &&
        (newConv.contactName !== oldConv?.contactName || newConv.channel !== oldConv?.channel)
      ) {
        panel.historyLastFetched = null // Clear to force refresh
        panel.historyDbPath = null
        fetchConversationHistory(serial)
      }
    }
  },
  { deep: true }
)

watch(sidecarConversationHistoryDbOverride, () => {
  for (const serial of panels.value) {
    const panel = sidecars[serial]
    if (!panel) continue
    panel.historyLastFetched = null
    panel.historyDbPath = null
    void fetchConversationHistory(serial)
  }
})

// Refresh sidecar state when sync status changes for any open panel
watch(
  () => {
    // Build a snapshot of sync statuses for open panels
    const statuses: Record<string, string | undefined> = {}
    for (const serial of panels.value) {
      const status = deviceStore.getSyncStatus(serial)
      statuses[serial] = status?.status
    }
    return statuses
  },
  (newStatuses, oldStatuses) => {
    // Check which panels had a status change
    for (const serial of panels.value) {
      const newStatus = newStatuses[serial]
      const oldStatus = oldStatuses?.[serial]
      if (newStatus !== oldStatus) {
        // Sync status changed, refresh this panel
        fetchState(serial, false)
        fetchQueueState(serial)
      }
    }
  },
  { deep: true }
)

// Watch for changes in showLogs setting to connect/disconnect log streams
watch(showLogs, (newVal) => {
  // Iterate through all current panels
  for (const serial of panels.value) {
    if (newVal) {
      // Logs enabled: connect log stream
      logStore.connectLogStream(serial)
    } else {
      // Logs disabled: disconnect log stream
      logStore.disconnectLogStream(serial)
    }
  }
})

onUnmounted(() => {
  // Cleanup global WebSocket
  cleanupGlobalWebSocket()

  panels.value.forEach((serial) => stopPolling(serial))
  // Clean up any active resize listeners
  document.removeEventListener('mousemove', handleLogsResize)
  document.removeEventListener('mouseup', stopLogsResize)
  document.removeEventListener('mousemove', handleHistoryResize)
  document.removeEventListener('mouseup', stopHistoryResize)
  // Clean up image preview state
  previewImageUrl.value = null
  previewVideoId.value = null
  previewVideoDuration.value = null
})
</script>

<template>
  <div class="h-full flex flex-col animate-fade-in">
    <!-- Header -->
    <div class="p-4 border-b border-wecom-border shrink-0">
      <div class="flex items-center justify-between mb-3">
        <div>
          <h2 class="text-xl font-display font-bold text-wecom-text">
            {{ t('nav.sidecar') }}
          </h2>
          <p class="text-sm text-wecom-muted">{{ t('sidecar.subtitle') }}</p>
        </div>
      </div>

      <!-- Device tabs -->
      <div class="flex border-t border-wecom-border pt-3 overflow-x-auto">
        <button
          v-for="serial in availableDevices"
          :key="serial"
          draggable="true"
          class="px-4 py-2 text-sm font-medium whitespace-nowrap transition-colors"
          :class="[
            panels.includes(serial)
              ? 'text-wecom-primary border-b-2 border-wecom-primary bg-wecom-primary/5'
              : 'text-wecom-muted hover:text-wecom-text hover:bg-wecom-surface',
          ]"
          @dragstart="(event: DragEvent) => handleDragStart(serial, event)"
          @dragend="handleDragLeave"
          @click="selectDevice(serial)"
        >
          {{ serial }}
        </button>

        <div v-if="availableDevices.length === 0" class="px-4 py-2 text-sm text-wecom-muted">
          {{ t('common.no_data') }}
        </div>
      </div>
    </div>

    <!-- Content -->
    <div
      class="flex-1 overflow-hidden relative"
      @dragover.prevent="handleDragOver"
      @dragleave="handleDragLeave"
      @drop.prevent="handleDrop"
    >
      <div
        v-if="isDragOver"
        class="absolute inset-0 z-10 pointer-events-none flex items-center justify-center bg-wecom-primary/10 border-2 border-dashed border-wecom-primary text-wecom-primary font-medium"
      >
        <span>
          {{
            panels.length >= maxPanels
              ? 'Maximum of 3 panels reached'
              : `Release to add ${t('nav.sidecar').toLowerCase()}`
          }}
        </span>
      </div>

      <div v-if="panels.length > 0" class="h-full grid gap-2 p-2" :class="gridColsClass">
        <div
          v-for="serial in panels"
          :key="serial"
          class="flex flex-col min-h-0 border border-wecom-border rounded-lg bg-wecom-dark/60 overflow-hidden"
        >
          <div
            class="flex items-center px-3 py-2 border-b border-wecom-border bg-wecom-dark/80"
            @click="focusedSerial = serial"
          >
            <!-- Device name - fixed, not scrollable -->
            <div class="flex items-center gap-2 shrink-0">
              <span
                class="px-2 py-1 rounded text-xs font-mono"
                :class="
                  focusedSerial === serial
                    ? 'bg-wecom-primary/15 text-wecom-primary'
                    : 'bg-wecom-surface text-wecom-text'
                "
              >
                {{ serial }}
              </span>
            </div>
            <!-- Scrollable buttons container -->
            <div class="flex-1 overflow-x-auto ml-2">
              <div class="flex items-center gap-1 min-w-max">
                <button
                  class="btn-primary text-xs px-2 py-1 flex items-center gap-1"
                  :disabled="
                    sidecars[serial]?.generating ||
                    sidecars[serial]?.aiProcessing ||
                    sidecars[serial]?.sending
                  "
                  :title="
                    settings.useAIReply
                      ? 'Generate AI reply based on last message'
                      : 'Generate mock reply based on last message'
                  "
                  @click.stop="generateReply(serial)"
                >
                  <span v-if="sidecars[serial]?.generating || sidecars[serial]?.aiProcessing"
                    >⏳</span
                  >
                  <span v-else>🤖</span>
                  <span class="hidden sm:inline">Generate</span>
                </button>
                <button
                  class="btn-secondary text-xs px-2 py-1 flex items-center gap-1"
                  :disabled="mirrorLoading[serial] || !deviceStore.mirrorAvailable"
                  :title="
                    deviceStore.mirrorAvailable
                      ? ''
                      : 'Mirror is only available in the desktop app with scrcpy installed'
                  "
                  @click.stop="toggleMirror(serial)"
                >
                  <span v-if="mirrorLoading[serial]">⏳</span>
                  <template v-else>
                    <span>{{ isMirroring(serial) ? '🛑' : '🖥️' }}</span>
                    <span class="hidden sm:inline">
                      {{ isMirroring(serial) ? 'Stop mirror' : 'Mirror' }}
                    </span>
                  </template>
                </button>
                <button
                  class="btn-secondary text-xs px-2 py-1 flex items-center gap-1"
                  title="Start full sync for this device"
                  @click.stop="startDeviceSync(serial)"
                >
                  <span>📥</span>
                  <span class="hidden sm:inline">Sync</span>
                </button>
                <button
                  class="btn-secondary text-xs px-2 py-1"
                  :disabled="sidecars[serial]?.loading"
                  title="Refresh state and history"
                  @click.stop="
                    () => {
                      startPolling(serial)
                      refreshConversationHistory(serial)
                    }
                  "
                >
                  🔄
                </button>
                <button class="btn-secondary text-xs px-2 py-1" @click.stop="removePanel(serial)">
                  ✖️
                </button>
              </div>
            </div>
          </div>

          <div class="flex-1 flex flex-col min-h-0 overflow-hidden">
            <!-- Progress Control Bar (when device is syncing or follow-up is running) -->
            <div
              v-if="shouldShowProgressControls(serial)"
              class="shrink-0 px-3 py-2 border-b"
              :class="
                getProgressControlType(serial) === 'followup'
                  ? 'bg-blue-900/20 border-blue-500/30'
                  : getSyncProgress(serial)?.status === 'paused'
                    ? 'bg-yellow-900/20 border-yellow-500/30'
                    : 'bg-wecom-dark/50 border-wecom-border'
              "
            >
              <div class="flex items-center justify-between text-xs mb-1">
                <span
                  class="truncate flex-1"
                  :class="
                    getProgressControlType(serial) === 'followup'
                      ? 'text-blue-400'
                      : getSyncProgress(serial)?.status === 'paused'
                        ? 'text-yellow-400'
                        : 'text-wecom-muted'
                  "
                >
                  <span v-if="getSyncProgress(serial)?.status === 'paused'">⏸️ </span>
                  <span v-if="getProgressControlType(serial) === 'followup'">🔄 </span>
                  {{ getProgressControlMessage(serial) }}
                </span>
                <div class="flex items-center gap-2 ml-2 shrink-0">
                  <span v-if="getProgressControlType(serial) === 'sync'" class="text-wecom-primary"
                    >{{ getSyncProgress(serial)?.progress }}%</span
                  >
                  <!-- Stop/Pause/Resume buttons - only for sync -->
                  <button
                    v-if="getProgressControlType(serial) === 'sync'"
                    class="btn-secondary text-xs px-2 py-0.5 hover:bg-red-500/20 hover:text-red-400 transition-colors"
                    title="Stop sync"
                    :disabled="stopLoading[serial]"
                    @click.stop="stopDeviceSync(serial)"
                  >
                    <span v-if="stopLoading[serial]">⏳</span>
                    <span v-else>⏹️</span>
                    {{ t('sidecar.stop', {}, 'Stop') }}
                  </button>
                  <button
                    v-if="
                      getProgressControlType(serial) === 'sync' &&
                      getSyncProgress(serial)?.status === 'paused'
                    "
                    class="btn-secondary text-xs px-2 py-0.5 hover:bg-green-500/20 hover:text-green-400 transition-colors"
                    title="Resume sync"
                    @click.stop="resumeDeviceSync(serial)"
                  >
                    ▶️ {{ t('sidecar.resume', {}, 'Resume') }}
                  </button>
                  <button
                    v-if="
                      getProgressControlType(serial) === 'sync' &&
                      getSyncProgress(serial)?.status !== 'paused'
                    "
                    class="btn-secondary text-xs px-2 py-0.5 hover:bg-yellow-500/20 hover:text-yellow-400 transition-colors"
                    title="Pause sync"
                    @click.stop="pauseDeviceSync(serial)"
                  >
                    ⏸️ {{ t('sidecar.pause', {}, 'Pause') }}
                  </button>
                  <!-- Skip and Block buttons - for both sync and follow-up -->
                  <button
                    class="btn-secondary text-xs px-2 py-0.5 hover:bg-yellow-500/20 hover:text-yellow-400 transition-colors"
                    title="Skip current user"
                    :disabled="skipLoading[serial]"
                    @click.stop="skipDeviceSync(serial)"
                  >
                    <span v-if="skipLoading[serial]">⏳</span>
                    <span v-else>⏭️</span>
                    {{ t('sidecar.skip', {}, 'Skip') }}
                  </button>
                  <button
                    :class="[
                      'text-xs px-2 py-0.5 transition-colors',
                      sidecars[serial]?.isBlacklisted === true
                        ? 'btn-secondary hover:bg-green-500/20 hover:text-green-400'
                        : 'btn-secondary hover:bg-red-500/20 hover:text-red-400',
                    ]"
                    :title="getBlockButtonTitle(sidecars[serial]?.isBlacklisted ?? null, t)"
                    :disabled="
                      blockLoading[serial] || !hasActiveConversationTarget(sidecars[serial])
                    "
                    @click.stop="toggleBlockUser(serial)"
                  >
                    <span v-if="blockLoading[serial]">⏳</span>
                    <span v-else-if="sidecars[serial]?.isBlacklisted === true">✓</span>
                    <span v-else>🚫</span>
                    {{
                      sidecars[serial]?.isBlacklisted === true
                        ? t('sidecar.allowed', {}, 'Allowed')
                        : t('sidecar.block', {}, 'Block')
                    }}
                  </button>
                </div>
              </div>
              <!-- Progress bar - only for sync -->
              <div
                v-if="getProgressControlType(serial) === 'sync'"
                class="h-1.5 bg-wecom-surface rounded-full overflow-hidden"
              >
                <div
                  class="h-full transition-all duration-300"
                  :class="
                    getSyncProgress(serial)?.status === 'paused'
                      ? 'bg-yellow-500'
                      : 'bg-wecom-primary'
                  "
                  :style="{ width: `${getSyncProgress(serial)?.progress || 0}%` }"
                ></div>
              </div>
            </div>

            <!-- Sync Completed/Error/Stopped Status -->
            <div
              v-else-if="getSyncProgress(serial)?.status === 'completed'"
              class="shrink-0 px-3 py-2 bg-green-900/20 border-b border-green-500/30"
            >
              <div class="flex items-center justify-between text-xs">
                <span class="text-green-400">✓ {{ getSyncProgress(serial)?.message }}</span>
                <button
                  class="btn-secondary text-xs px-2 py-0.5"
                  title="Clear status"
                  @click.stop="clearDeviceSyncStatus(serial)"
                >
                  ✓ Clear
                </button>
              </div>
            </div>

            <div
              v-else-if="getSyncProgress(serial)?.status === 'error'"
              class="shrink-0 px-3 py-2 bg-red-900/20 border-b border-red-500/30"
            >
              <div class="flex items-center justify-between text-xs">
                <span class="text-red-400">⚠️ {{ getSyncProgress(serial)?.message }}</span>
                <button
                  class="btn-secondary text-xs px-2 py-0.5"
                  title="Clear status"
                  @click.stop="clearDeviceSyncStatus(serial)"
                >
                  ✓ Clear
                </button>
              </div>
            </div>

            <div
              v-else-if="getSyncProgress(serial)?.status === 'stopped'"
              class="shrink-0 px-3 py-2 bg-yellow-900/20 border-b border-yellow-500/30"
            >
              <div class="flex items-center justify-between text-xs">
                <span class="text-yellow-400">⏹ {{ getSyncProgress(serial)?.message }}</span>
                <button
                  class="btn-secondary text-xs px-2 py-0.5"
                  title="Clear status"
                  @click.stop="clearDeviceSyncStatus(serial)"
                >
                  ✓ Clear
                </button>
              </div>
            </div>
            <!-- Error / Loading State -->
            <div
              v-if="sidecars[serial]?.error"
              class="shrink-0 bg-red-900/30 border-b border-red-500/40 px-3 py-2 text-sm flex items-start gap-2"
            >
              <span>⚠️</span>
              <p class="text-red-200 flex-1">{{ sidecars[serial]?.error }}</p>
            </div>

            <div
              v-if="sidecars[serial]?.loading"
              class="shrink-0 px-3 py-2 flex items-center justify-center border-b border-wecom-border"
            >
              <LoadingSpinner label="Loading sidecar..." />
            </div>

            <!-- Compact Info Bar -->
            <div
              v-if="!sidecars[serial]?.loading && !sidecars[serial]?.error"
              class="shrink-0 px-3 py-2 border-b border-wecom-border bg-wecom-darker/50 flex items-center justify-between gap-2 text-xs"
            >
              <div class="flex items-center gap-3 min-w-0">
                <span class="text-wecom-muted">👤</span>
                <span class="text-wecom-text font-medium truncate">{{
                  sidecars[serial]?.cachedKefu?.name || 'Unknown'
                }}</span>
                <span class="text-wecom-muted">→</span>
                <span class="text-wecom-primary font-medium truncate">{{
                  customerLabel(sidecars[serial]?.state || null)
                }}</span>
              </div>
              <div class="flex items-center gap-2 shrink-0">
                <span class="text-wecom-muted"
                  >{{ sidecars[serial]?.historyTotalCount || 0 }} msgs</span
                >
              </div>
            </div>

            <!-- Chat History (Main Area - WeChat Style) -->
            <div
              :ref="(el) => (chatHistoryRefs[serial] = el as HTMLElement)"
              class="flex-1 min-h-0 overflow-auto bg-wecom-dark/30"
            >
              <div
                v-if="
                  sidecars[serial]?.historyLoading && sidecars[serial]?.historyMessages.length === 0
                "
                class="h-full flex items-center justify-center"
              >
                <span class="text-sm text-wecom-muted animate-pulse">Loading conversation...</span>
              </div>
              <div
                v-else-if="sidecars[serial]?.historyMessages.length === 0"
                class="h-full flex items-center justify-center"
              >
                <span class="text-sm text-wecom-muted">
                  {{ sidecars[serial]?.historyError || 'No messages yet' }}
                </span>
              </div>
              <div v-else class="p-3 space-y-3">
                <div
                  v-for="msg in sidecars[serial]?.historyMessages"
                  :key="msg.id"
                  class="flex gap-3 transition-all duration-300"
                  :class="{
                    'flex-row-reverse': msg.is_from_kefu,
                    'animate-pulse-once': sidecars[serial]?.highlightedMessageIds.has(msg.id),
                  }"
                >
                  <!-- Avatar: Agent messages on right (is_from_kefu=true), customer messages on left (is_from_kefu=false) -->
                  <div
                    class="w-8 h-8 rounded-full flex items-center justify-center text-sm shrink-0"
                    :class="
                      msg.is_from_kefu
                        ? 'bg-wecom-primary/30 text-wecom-primary'
                        : 'bg-wecom-surface text-wecom-muted'
                    "
                  >
                    {{ msg.is_from_kefu ? '💼' : '👤' }}
                  </div>
                  <!-- Message Bubble: Agent messages (right) green, customer messages (left) gray -->
                  <div
                    class="max-w-[75%] px-3 py-2 rounded-lg shadow-sm transition-all duration-300"
                    :class="{
                      'bg-wecom-primary text-white rounded-tr-none': msg.is_from_kefu,
                      'bg-wecom-surface text-wecom-text border border-wecom-border rounded-tl-none':
                        !msg.is_from_kefu,
                      'ring-2 ring-blue-400 ring-opacity-70 scale-105': sidecars[
                        serial
                      ]?.highlightedMessageIds.has(msg.id),
                    }"
                  >
                    <div class="break-words whitespace-pre-wrap text-sm">
                      <!-- Image / sticker message with actual image -->
                      <template
                        v-if="
                          (msg.message_type === 'image' || msg.message_type === 'sticker') &&
                          msg.image_url
                        "
                      >
                        <img
                          :src="getImageUrl(msg.image_url)"
                          :alt="
                            msg.content || (msg.message_type === 'sticker' ? 'Sticker' : 'Image')
                          "
                          class="max-w-[200px] max-h-[200px] rounded cursor-pointer hover:opacity-90 transition-opacity hover:shadow-lg"
                          loading="lazy"
                          @click="openImagePreview(msg.image_url)"
                          @error="($event.target as HTMLImageElement).style.display = 'none'"
                        />
                        <div
                          v-if="msg.image_width && msg.image_height"
                          class="text-xs mt-1 opacity-50"
                        >
                          {{ msg.image_width }}×{{ msg.image_height }}
                        </div>
                        <div
                          v-if="shouldShowAiReviewSection(msg)"
                          class="text-xs mt-1.5 pt-1 border-t border-white/10 space-y-0.5 text-left leading-snug"
                          :class="msg.is_from_kefu ? 'border-white/20' : 'border-wecom-border'"
                        >
                          <template v-if="getAiReviewStatus(msg) === 'pending'">
                            <div class="font-medium opacity-90">正在等待图片审核</div>
                          </template>
                          <template v-else-if="getAiReviewStatus(msg) === 'timeout'">
                            <div class="font-medium text-yellow-300">图片审核超时</div>
                            <div
                              v-if="getAiReviewErrorMessage(msg)"
                              class="opacity-80 whitespace-pre-wrap"
                            >
                              {{ getAiReviewErrorMessage(msg) }}
                            </div>
                          </template>
                          <template v-else-if="getAiReviewStatus(msg) === 'failed'">
                            <div class="font-medium text-red-300">图片审核失败</div>
                            <div
                              v-if="getAiReviewErrorMessage(msg)"
                              class="opacity-80 whitespace-pre-wrap"
                            >
                              {{ getAiReviewErrorMessage(msg) }}
                            </div>
                          </template>
                          <div
                            v-if="
                              getAiReviewStatus(msg) === 'completed' && msg.ai_review_score != null
                            "
                            class="font-medium opacity-90"
                          >
                            {{ t('sidecar.ai_review_score', undefined, 'AI 评分') }}:
                            {{ Number(msg.ai_review_score).toFixed(1) }}
                          </div>
                          <div
                            v-if="getAiReviewStatus(msg) === 'completed' && msg.ai_review_decision"
                            class="opacity-85"
                          >
                            {{ msg.ai_review_decision }}
                          </div>
                          <div
                            v-if="getAiReviewStatus(msg) === 'completed' && msg.ai_review_reason"
                            class="opacity-80 whitespace-pre-wrap"
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
                              class="opacity-80 whitespace-pre-wrap"
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
                            <div class="opacity-85">
                              {{ t('sidecar.ai_review_penalties', undefined, '扣分项') }}:
                            </div>
                            <div
                              v-for="(penalty, index) in msg.ai_review_penalties"
                              :key="`${msg.id}-penalty-${index}`"
                              class="opacity-75 whitespace-pre-wrap pl-2"
                            >
                              - {{ penalty }}
                            </div>
                          </div>
                          <div
                            v-if="getAiReviewStatus(msg) === 'completed' && msg.ai_review_at"
                            class="opacity-50 text-[10px] font-mono"
                          >
                            {{ msg.ai_review_at }}
                          </div>
                        </div>
                      </template>

                      <!-- Image / sticker message without actual image file -->
                      <template
                        v-else-if="msg.message_type === 'image' || msg.message_type === 'sticker'"
                      >
                        <div class="flex items-center gap-2 opacity-70">
                          <span>{{ msg.message_type === 'sticker' ? '😀' : '🖼️' }}</span>
                          <span>{{
                            msg.message_type === 'sticker'
                              ? '[Sticker unavailable]'
                              : '[Image unavailable]'
                          }}</span>
                        </div>
                      </template>

                      <!-- Video message with thumbnail / playback -->
                      <template v-else-if="msg.message_type === 'video' && msg.video_id">
                        <div
                          class="relative w-[200px] h-[112px] rounded overflow-hidden cursor-pointer bg-wecom-darker border border-white/10 group"
                          @click="openVideoPreview(msg.video_id, msg.video_duration)"
                        >
                          <div
                            class="absolute inset-0 flex items-center justify-center bg-gradient-to-br from-wecom-dark to-wecom-darker"
                          >
                            <span class="text-4xl opacity-30">🎬</span>
                          </div>
                          <img
                            :src="api.getVideoThumbnailUrl(msg.video_id)"
                            alt="Video thumbnail"
                            class="relative z-[1] w-full h-full object-cover"
                            @error="($event.target as HTMLImageElement).style.display = 'none'"
                          />
                          <div
                            class="absolute inset-0 z-[2] bg-black/20 group-hover:bg-black/40 transition-colors"
                          ></div>
                          <div class="absolute inset-0 z-[3] flex items-center justify-center">
                            <div
                              class="w-12 h-12 rounded-full bg-white/85 text-black flex items-center justify-center shadow-lg group-hover:scale-110 transition-transform"
                            >
                              <svg class="w-6 h-6 ml-0.5" fill="currentColor" viewBox="0 0 24 24">
                                <path d="M8 5v14l11-7z" />
                              </svg>
                            </div>
                          </div>
                          <div
                            v-if="msg.video_duration"
                            class="absolute bottom-2 right-2 z-[4] px-2 py-0.5 bg-black/70 text-white text-xs rounded font-mono"
                          >
                            {{ msg.video_duration }}
                          </div>
                        </div>
                        <VideoAiReviewSummary
                          :message-id="msg.id"
                          :video-ai-review-score="msg.video_ai_review_score"
                          :video-ai-review-status="msg.video_ai_review_status"
                          :video-ai-review-error="msg.video_ai_review_error"
                          :video-ai-review-at="msg.video_ai_review_at"
                          :is-from-kefu="msg.is_from_kefu"
                          @open-detail="openVideoReviewDetail(serial, msg)"
                        />
                      </template>

                      <!-- Video message without file -->
                      <template v-else-if="msg.message_type === 'video'">
                        <div class="flex items-center gap-2 opacity-70">
                          <span>🎬</span>
                          <span>{{ msg.content || '[Video unavailable]' }}</span>
                        </div>
                      </template>

                      <!-- Voice message -->
                      <template v-else-if="msg.message_type === 'voice'">
                        <div class="flex items-center gap-2 opacity-70">
                          <span>🎤</span>
                          <span>{{ msg.content || '[Voice]' }}</span>
                        </div>
                      </template>

                      <!-- Other message types (text, system, etc.) -->
                      <template v-else>
                        <span v-if="msg.message_type !== 'text'" class="opacity-70"
                          >[{{ msg.message_type }}]
                        </span>
                        {{ msg.content || '(no content)' }}
                      </template>
                    </div>
                    <div
                      class="text-[10px] mt-1 opacity-60"
                      :class="msg.is_from_kefu ? 'text-right' : ''"
                    >
                      {{ formatHistoryTime(msg) }}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Input Area (Bottom Fixed - WeChat Style) -->
            <div class="shrink-0 border-t border-wecom-border bg-wecom-darker p-3 space-y-2">
              <!-- AI Reply Indicator -->
              <div
                v-if="sidecars[serial]?.aiProcessing || sidecars[serial]?.aiReplySource"
                class="flex items-center gap-2 text-xs px-2 py-1 rounded"
                :class="{
                  'bg-blue-900/30 text-blue-300 border border-blue-500/30':
                    sidecars[serial]?.aiProcessing,
                  'bg-green-900/30 text-green-300 border border-green-500/30':
                    sidecars[serial]?.aiReplySource === 'ai',
                  'bg-yellow-900/30 text-yellow-300 border border-yellow-500/30':
                    sidecars[serial]?.aiReplySource === 'fallback',
                  'bg-gray-900/30 text-gray-300 border border-gray-500/30':
                    sidecars[serial]?.aiReplySource === 'mock',
                }"
              >
                <span v-if="sidecars[serial]?.aiProcessing" class="animate-pulse"
                  >🤖 Processing AI reply...</span
                >
                <span v-else-if="sidecars[serial]?.aiReplySource === 'ai'">🤖 AI Reply</span>
                <span v-else-if="sidecars[serial]?.aiReplySource === 'fallback'"
                  >⚠️ AI Fallback</span
                >
                <span v-else-if="sidecars[serial]?.aiReplySource === 'mock'">📝 Mock Reply</span>
              </div>

              <!-- Textarea + Send Button -->
              <div class="flex gap-2 items-end">
                <textarea
                  v-model="sidecars[serial].pendingMessage"
                  class="input-field flex-1 min-h-[100px] max-h-[180px] resize-none"
                  :class="{
                    'border-wecom-primary':
                      sidecars[serial]?.queueMode && sidecars[serial]?.currentQueuedMessage,
                    'border-green-500/50': sidecars[serial]?.aiReplySource === 'ai',
                    'border-yellow-500/50': sidecars[serial]?.aiReplySource === 'fallback',
                    'ring-2 ring-yellow-500/50': sidecars[serial]?.isEditing,
                  }"
                  placeholder="Type a message..."
                  :disabled="sidecars[serial]?.aiProcessing"
                  @focus="handleMessageFocus(serial)"
                  @input="handleMessageInput(serial)"
                  @blur="handleMessageBlur(serial)"
                  @keydown.enter.ctrl.exact="sendNow(serial)"
                ></textarea>
                <div class="flex flex-col gap-2 self-stretch">
                  <button
                    class="btn-primary px-6 py-3 text-sm flex-1 min-w-[70px]"
                    :disabled="
                      sidecars[serial]?.aiProcessing || !sidecars[serial]?.pendingMessage?.trim()
                    "
                    title="Send (Ctrl+Enter)"
                    @click="sendNow(serial)"
                  >
                    Send
                  </button>
                  <button
                    v-if="sidecars[serial]?.countdown === null"
                    class="btn-secondary px-6 py-3 text-sm flex-1 min-w-[70px]"
                    :disabled="
                      sidecars[serial]?.syncQueueState?.paused || sidecars[serial]?.aiProcessing
                    "
                    title="Start countdown"
                    @click="startCountdown(serial)"
                  >
                    {{ countdownDuration }}s
                  </button>
                </div>
              </div>

              <!-- Countdown Progress -->
              <div v-if="sidecars[serial]?.countdown !== null" class="space-y-1">
                <div
                  class="w-full bg-wecom-surface border border-wecom-border rounded-full h-1.5 overflow-hidden"
                >
                  <div
                    class="h-full bg-wecom-primary transition-all"
                    :style="{ width: `${countdownProgress(sidecars[serial])}%` }"
                  ></div>
                </div>
                <div class="flex items-center justify-between text-xs gap-2">
                  <div class="flex items-center gap-2 flex-1">
                    <!-- Source badge -->
                    <span
                      v-if="sidecars[serial]?.currentQueuedMessage?.source === 'followup'"
                      class="px-2 py-0.5 text-xs font-medium rounded bg-blue-500/20 text-blue-400 border border-blue-500/30 shrink-0"
                    >
                      🔄 FOLLOWUP
                    </span>
                    <span
                      v-else-if="sidecars[serial]?.currentQueuedMessage?.source === 'sync'"
                      class="px-2 py-0.5 text-xs font-medium rounded bg-green-500/20 text-green-400 border border-green-500/30 shrink-0"
                    >
                      🔃 SYNC
                    </span>
                    <span class="text-wecom-muted truncate">{{
                      sidecars[serial]?.statusMessage || countdownHint
                    }}</span>
                  </div>
                  <button
                    class="text-wecom-primary hover:underline shrink-0"
                    @click="pauseCountdown(serial)"
                  >
                    Pause
                  </button>
                </div>
              </div>
            </div>

            <!-- Logs Section (controlled by settings) -->
            <div
              v-if="showLogs"
              class="shrink-0 border-t border-wecom-border flex flex-col"
              :style="{
                height: sidecars[serial]?.logsCollapsed
                  ? '32px'
                  : `${sidecars[serial]?.logsHeight || 256}px`,
              }"
            >
              <!-- Resize Handle -->
              <div
                class="h-1 bg-transparent hover:bg-wecom-primary/30 cursor-ns-resize transition-colors group relative"
                @mousedown="(e: MouseEvent) => startLogsResize(serial, e)"
              >
                <div class="absolute inset-x-0 -top-1 -bottom-1"></div>
              </div>
              <div
                class="flex items-center justify-between px-3 py-1 bg-wecom-darker cursor-pointer hover:bg-wecom-surface/10 select-none border-b border-wecom-border/50"
                @click="sidecars[serial].logsCollapsed = !sidecars[serial].logsCollapsed"
              >
                <div class="flex items-center gap-2">
                  <span class="text-xs text-wecom-muted font-mono">Logs</span>
                  <span
                    class="text-[10px] px-1.5 py-0.5 rounded-full bg-wecom-surface text-wecom-muted"
                  >
                    {{ logStore.getDeviceLogs(serial).length }}
                  </span>
                </div>
                <div class="flex items-center gap-2">
                  <button
                    class="btn-secondary text-xs px-2 py-1 h-6 flex items-center"
                    :disabled="logStore.getDeviceLogs(serial).length === 0"
                    title="Export logs"
                    @click.stop="exportLogs(serial)"
                  >
                    📥
                  </button>
                  <span class="text-xs text-wecom-muted">
                    {{ sidecars[serial]?.logsCollapsed ? 'Show ▲' : 'Hide ▼' }}
                  </span>
                </div>
              </div>

              <div v-show="!sidecars[serial]?.logsCollapsed" class="flex-1 min-h-0">
                <LogStream :logs="logStore.getDeviceLogs(serial)" :auto-scroll="true" />
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-else class="h-full flex flex-col items-center justify-center text-center p-8">
        <div class="flex flex-wrap items-center justify-center gap-3 mb-6">
          <span class="text-xs uppercase tracking-wider text-wecom-muted"> Quick actions </span>
          <div
            class="flex items-center gap-2 bg-wecom-dark/50 border border-wecom-border rounded-lg px-3 py-2"
          >
            <label class="text-xs text-wecom-muted" for="sidecar-sync-device">Device</label>
            <select
              id="sidecar-sync-device"
              v-model="syncTargetSerial"
              class="bg-transparent text-sm text-wecom-text focus:outline-none"
            >
              <option value="" disabled>Select a device</option>
              <option v-for="serial in availableDevices" :key="serial" :value="serial">
                {{ serial }}
              </option>
            </select>
          </div>
          <button
            class="btn-primary text-sm flex items-center gap-2"
            :disabled="!syncTargetSerial || syncLoading"
            @click="startQuickSync"
          >
            <span v-if="syncLoading">⏳</span>
            <span v-else>🚀</span>
            <span>Sync now</span>
          </button>
        </div>
        <div v-if="syncActionMessage" class="text-xs text-wecom-muted mb-4">
          {{ syncActionMessage }}
        </div>
        <div class="text-5xl mb-4">🚗</div>
        <h3 class="text-lg font-display font-semibold text-wecom-text mb-2">
          Drag a device to open sidecar
        </h3>
        <p class="text-wecom-muted max-w-md">
          {{ dropMessage }}. You can also click a device tab above. Up to 3 devices can be shown
          side-by-side.
        </p>
      </div>
    </div>

    <!-- Image Preview Modal -->
    <Teleport to="body">
      <div
        v-if="previewImageUrl"
        class="fixed inset-0 z-[9999] bg-black/90 flex items-center justify-center cursor-zoom-out"
        @click="closeImagePreview()"
      >
        <!-- Close button -->
        <button
          class="absolute top-4 right-4 text-white/80 hover:text-white text-3xl font-bold z-10 w-10 h-10 flex items-center justify-center rounded-full hover:bg-white/10 transition-colors"
          @click.stop="closeImagePreview()"
        >
          ×
        </button>

        <!-- Image -->
        <img
          :src="previewImageUrl"
          alt="Preview image"
          class="max-w-[90vw] max-h-[90vh] object-contain rounded-lg shadow-2xl cursor-default"
          @click.stop
        />

        <!-- Hint -->
        <div class="absolute bottom-4 left-1/2 -translate-x-1/2 text-white/60 text-sm">
          Click anywhere to close
        </div>
      </div>
    </Teleport>

    <VideoReviewDetailPanel
      v-model="videoReviewModalOpen"
      :message-id="videoReviewMessageId"
      :frames-json="videoReviewFramesJson"
      :aggregate-score="videoReviewAggregateScore"
      :db-path="videoReviewDbPath"
    />

    <!-- Video Preview Modal -->
    <Teleport to="body">
      <div
        v-if="previewVideoId"
        class="fixed inset-0 z-[9999] bg-black/95 flex items-center justify-center"
        @click="closeVideoPreview()"
      >
        <button
          class="absolute top-4 right-4 text-white/80 hover:text-white text-3xl font-bold z-10 w-10 h-10 flex items-center justify-center rounded-full hover:bg-white/10 transition-colors"
          @click.stop="closeVideoPreview()"
        >
          ×
        </button>

        <div class="max-w-[92vw] max-h-[92vh] flex flex-col items-center gap-4" @click.stop>
          <video
            :key="previewVideoId"
            :src="api.getVideoUrl(previewVideoId)"
            controls
            autoplay
            class="max-w-[92vw] max-h-[82vh] rounded-lg shadow-2xl bg-black"
          >
            Your browser does not support the video tag.
          </video>

          <div v-if="previewVideoDuration" class="text-white/70 text-sm font-mono">
            {{ previewVideoDuration }}
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
/* Hide scrollbar for title bar buttons while keeping it scrollable */
.overflow-x-auto::-webkit-scrollbar {
  height: 0;
  display: none;
}
.overflow-x-auto {
  scrollbar-width: none; /* Firefox */
  -ms-overflow-style: none; /* IE and Edge */
}
</style>
