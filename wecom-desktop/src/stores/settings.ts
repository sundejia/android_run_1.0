import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { updateApiBase } from '../utils/avatars'

export interface TimezonePreset {
  key: string
  name: string
  timezone: string
}

// AI Prompt Style Presets
export interface PromptStylePreset {
  key: string
  name: string
  description: string
  prompt: string
}

export const PROMPT_STYLE_PRESETS: PromptStylePreset[] = [
  {
    key: 'none',
    name: '无预设',
    description: '不使用预设风格',
    prompt: ''
  },
  {
    key: 'default',
    name: '默认风格',
    description: '礼貌大方，有条理',
    prompt: `语气礼貌大方，使用"您"称呼用户。
回答要直接且有条理，避免冗长。
始终保持耐心，无论用户的情绪如何。`
  },
  {
    key: 'lively',
    name: '活泼风格',
    description: '热情活泼，像朋友一样',
    prompt: `语气要超级热情，多使用"哈喽"、"亲亲"、"么么哒"或"好哒"等词汇。
适当使用表情符号（如 🌈, 🚀, 😊）来让对话更生动。
把用户当成朋友，除了解决问题，也要给用户提供情绪价值。
遇到用户抱怨时，要用超温柔的方式安抚对方，比如："抱抱亲亲，别生气哦，小趣马上帮你想办法！"`
  },
  {
    key: 'professional',
    name: '专业风格',
    description: '正式商务用语',
    prompt: `使用极其正式的商务用语，确保表达的准确性。
回答问题时，请适度采用"第一步、第二步、第三步"的结构化方式。
引用任何数据或政策时需谨慎核实，确保专业度。
保持绝对客观中立，即使在拒绝用户要求时，也要解释清楚基于的政策条款。`
  },
  {
    key: 'minimal',
    name: '极简/高效风格',
    description: '直接高效，不寒暄',
    prompt: `拒绝寒暄。直接识别用户意图并给出答案。
使用精炼的短句，不要使用任何修辞手法。
如果问题需要多个步骤，仅提供最直接的解决方案链接或指令。`
  }
]

export type AppSettings = {
  // General settings
  hostname: string  // Hostname for log file prefixes
  deviceId: string
  personName: string
  logUploadEnabled: boolean
  logUploadTime: string
  logUploadUrl: string
  lowSpecMode: boolean
  
  // Sync settings
  timingMultiplier: number
  autoPlaceholder: boolean
  noTestMessages: boolean
  maxConcurrentSyncDevices: number

  // Mirror settings
  mirrorMaxSize: number
  mirrorBitRate: number
  mirrorMaxFps: number
  mirrorStayAwake: boolean
  mirrorTurnScreenOff: boolean
  mirrorShowTouches: boolean

  // Backend settings
  backendUrl: string

  // UI settings
  autoRefreshInterval: number
  logMaxEntries: number

  // Sidecar settings
  countdownSeconds: number
  sendViaSidecar: boolean
  sidecarPollInterval: number  // 0 = disabled, 1-20 seconds
  sidecarShowLogs: boolean  // Show logs panel in Sidecar view
  sidecarMaxPanels: number

  // AI Reply settings
  useAIReply: boolean  // Toggle between mock reply and AI reply
  aiServerUrl: string  // AI server URL (default http://localhost:8000)
  aiReplyTimeout: number  // Timeout in seconds for AI reply (default 10)

  // AI Analysis settings (DeepSeek for persona analysis)
  aiAnalysisEnabled: boolean  // Enable AI-powered persona analysis
  aiAnalysisProvider: 'deepseek' | 'openai' | 'custom'  // AI provider
  aiAnalysisApiKey: string  // API key for the AI provider
  aiAnalysisBaseUrl: string  // Base URL for the AI provider API
  aiAnalysisModel: string  // Model to use for analysis
  aiAnalysisMaxTokens: number  // Max tokens for analysis response

  // Volcengine ASR settings (Voice transcription)
  volcengineAsrEnabled: boolean  // Enable voice transcription
  volcengineAsrApiKey: string  // Volcengine API key
  volcengineAsrResourceId: string  // Resource ID for ASR

  // Timezone settings
  timezone: string  // IANA timezone identifier (e.g., "Asia/Shanghai")

  // System Prompt
  systemPrompt: string  // System prompt for AI interactions
  promptStyleKey: string  // Selected prompt style preset key
  aiReplyMaxLength: number  // Maximum length for AI replies (20-70 characters)

  // Image review server settings
  imageUploadEnabled: boolean  // Enable auto-upload to image review platform
  imageServerIp: string  // Image review server address (e.g., http://192.168.1.100:8000)
  imageReviewTimeoutSeconds: number  // Timeout for waiting image review results

  // Email notification settings
  emailEnabled: boolean  // Enable email notifications
  emailSmtpServer: string  // SMTP server address
  emailSmtpPort: number  // SMTP port (465 for SSL, 587 for TLS)
  emailSenderEmail: string  // Sender email address
  emailSenderPassword: string  // Email password or authorization code
  emailSenderName: string  // Sender display name
  emailReceiverEmail: string  // Receiver email address
  emailNotifyOnVoice: boolean  // Send email when user sends voice message
  emailNotifyOnHumanRequest: boolean  // Send email when user requests human agent
  emailNotifyOnError: boolean  // Send email on system errors
  emailErrorNotifyMinLevel: string  // Minimum log level for error notifications (ERROR/CRITICAL)
  emailErrorRateLimitMinutes: number  // Minimum minutes between same-error emails

  // Dashboard monitoring settings
  dashboardEnabled: boolean  // Enable heartbeat reporting to device-dashboard
  dashboardUrl: string  // Device-dashboard WebSocket URL
}

export interface PerformanceProfile {
  lowSpecMode: boolean
  effective: {
    maxConcurrentSyncDevices: number
    sidecarPollInterval: number
    scanInterval: number
    sidecarMaxPanels: number
    mirrorMaxFps: number
    mirrorBitRate: number
    imageReviewInlineWaitEnabled: boolean
  }
  metrics: {
    startup?: {
      duration_ms?: number | null
    }
    runtime?: {
      memory_mb?: number | null
    }
    adb?: {
      total_calls?: number
    }
    sqlite?: {
      slow_queries?: number
    }
  }
}

const STORAGE_KEY = 'wecom-desktop-settings'

// Timezone presets for quick selection
export const TIMEZONE_PRESETS: TimezonePreset[] = [
  { key: 'china', name: '中国 (北京/上海)', timezone: 'Asia/Shanghai' },
  { key: 'hongkong', name: '香港', timezone: 'Asia/Hong_Kong' },
  { key: 'taiwan', name: '台湾', timezone: 'Asia/Taipei' },
  { key: 'singapore', name: '新加坡', timezone: 'Asia/Singapore' },
  { key: 'tokyo', name: '日本 (东京)', timezone: 'Asia/Tokyo' },
  { key: 'seoul', name: '韩国 (首尔)', timezone: 'Asia/Seoul' },
  { key: 'us_pacific', name: '美国太平洋时间', timezone: 'America/Los_Angeles' },
  { key: 'us_eastern', name: '美国东部时间', timezone: 'America/New_York' },
  { key: 'uk', name: '英国 (伦敦)', timezone: 'Europe/London' },
  { key: 'utc', name: 'UTC', timezone: 'UTC' },
]

export const DEFAULT_SETTINGS: AppSettings = {
  hostname: '',
  deviceId: '',
  personName: '',
  logUploadEnabled: false,
  logUploadTime: '02:00',
  logUploadUrl: '',
  lowSpecMode: false,
  timingMultiplier: 1.0,
  autoPlaceholder: true,
  noTestMessages: false,
  maxConcurrentSyncDevices: 3,
  mirrorMaxSize: 1080,
  mirrorBitRate: 8,
  mirrorMaxFps: 60,
  mirrorStayAwake: true,
  mirrorTurnScreenOff: false,
  mirrorShowTouches: false,
  backendUrl: 'http://localhost:8765',
  autoRefreshInterval: 5000,
  logMaxEntries: 1000,
  countdownSeconds: 0,
  sendViaSidecar: false,
  sidecarPollInterval: 2,  // default 2 seconds (lowered from 10 to avoid multi-device send clustering)
  sidecarShowLogs: false,  // default to hide logs
  sidecarMaxPanels: 3,
  // AI Reply defaults
  useAIReply: false,  // Default to mock reply (existing behavior)
  aiServerUrl: 'http://localhost:8000',
  aiReplyTimeout: 10,  // 10 seconds timeout
  // AI Analysis defaults (DeepSeek)
  aiAnalysisEnabled: true,
  aiAnalysisProvider: 'deepseek',
  aiAnalysisApiKey: 'sk-d98ab8a7e2694ed99b70eecd54b1643d',  // DeepSeek API key
  aiAnalysisBaseUrl: 'https://api.deepseek.com',
  aiAnalysisModel: 'deepseek-chat',
  aiAnalysisMaxTokens: 4096,
  // Volcengine ASR defaults
  volcengineAsrEnabled: true,
  volcengineAsrApiKey: '30327791-8bb8-43c0-ac5b-dc86e2ed4fc8',
  volcengineAsrResourceId: 'volc.seedasr.auc',
  // Timezone default
  timezone: 'Asia/Shanghai',  // Default to China timezone
  // System Prompt default
  systemPrompt: '',  // Empty by default
  promptStyleKey: 'none',  // No preset by default
  aiReplyMaxLength: 50,  // Default max length for AI replies
  // Image review server defaults
  imageUploadEnabled: true,
  imageServerIp: '',  // Empty by default — not active until configured
  imageReviewTimeoutSeconds: 40,

  // Email notification defaults
  emailEnabled: false,  // Disabled by default
  emailSmtpServer: 'smtp.qq.com',  // Default to QQ mail
  emailSmtpPort: 465,  // SSL port
  emailSenderEmail: '',
  emailSenderPassword: '',
  emailSenderName: 'WeCom 同步系统',
  emailReceiverEmail: '',
  emailNotifyOnVoice: true,  // Notify when user sends voice
  emailNotifyOnHumanRequest: true,  // Notify when user requests human agent
  emailNotifyOnError: false,  // Error email notifications disabled by default
  emailErrorNotifyMinLevel: 'ERROR',  // Notify on ERROR and above
  emailErrorRateLimitMinutes: 30,  // 30 min between same-error emails

  // Dashboard monitoring defaults
  dashboardEnabled: false,  // Disabled by default
  dashboardUrl: '',  // Empty by default
}

function clampCountdown(value: unknown) {
  const parsed = Math.round(Number(value))
  if (Number.isNaN(parsed)) return DEFAULT_SETTINGS.countdownSeconds
  return Math.min(30, Math.max(0, parsed))
}

function clampPollInterval(value: unknown) {
  const parsed = Math.round(Number(value))
  if (Number.isNaN(parsed)) return DEFAULT_SETTINGS.sidecarPollInterval
  return Math.min(20, Math.max(0, parsed))
}

function clampImageReviewTimeout(value: unknown) {
  const parsed = Math.round(Number(value))
  if (Number.isNaN(parsed)) return DEFAULT_SETTINGS.imageReviewTimeoutSeconds
  return Math.min(300, Math.max(1, parsed))
}

function clampMaxConcurrentSyncDevices(value: unknown) {
  const parsed = Math.round(Number(value))
  if (Number.isNaN(parsed)) return DEFAULT_SETTINGS.maxConcurrentSyncDevices
  return Math.min(8, Math.max(1, parsed))
}

function clampSidecarMaxPanels(value: unknown) {
  const parsed = Math.round(Number(value))
  if (Number.isNaN(parsed)) return DEFAULT_SETTINGS.sidecarMaxPanels
  return Math.min(3, Math.max(1, parsed))
}

function normalizeSettings(partial: Partial<AppSettings>): AppSettings {
  return {
    ...DEFAULT_SETTINGS,
    ...partial,
    countdownSeconds: clampCountdown(
      partial.countdownSeconds ?? DEFAULT_SETTINGS.countdownSeconds,
    ),
    sidecarPollInterval: clampPollInterval(
      partial.sidecarPollInterval ?? DEFAULT_SETTINGS.sidecarPollInterval,
    ),
    maxConcurrentSyncDevices: clampMaxConcurrentSyncDevices(
      partial.maxConcurrentSyncDevices ?? DEFAULT_SETTINGS.maxConcurrentSyncDevices,
    ),
    sidecarMaxPanels: clampSidecarMaxPanels(
      partial.sidecarMaxPanels ?? DEFAULT_SETTINGS.sidecarMaxPanels,
    ),
    imageReviewTimeoutSeconds: clampImageReviewTimeout(
      partial.imageReviewTimeoutSeconds ?? DEFAULT_SETTINGS.imageReviewTimeoutSeconds,
    ),
  }
}

export const useSettingsStore = defineStore('settings', () => {
  const settings = ref<AppSettings>({ ...DEFAULT_SETTINGS })
  const loaded = ref(false)
  const backendSynced = ref(false)  // Track if we've synced with backend
  const isSyncing = ref(false)  // Prevent recursive sync calls

  function load() {
    if (loaded.value || typeof window === 'undefined') return

    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      try {
        const parsed = JSON.parse(saved) as Partial<AppSettings>
        settings.value = normalizeSettings(parsed)
      } catch (error) {
        console.error('Failed to load settings', error)
        settings.value = { ...DEFAULT_SETTINGS }
      }
    } else {
      settings.value = { ...DEFAULT_SETTINGS }
    }

    loaded.value = true
  }

  async function loadFromBackend() {
    // Try to load settings from backend database
    if (typeof window === 'undefined') return
    
    try {
      const response = await fetch(`${settings.value.backendUrl}/settings`)
      if (response.ok) {
        const data = await response.json()
        // Merge backend settings with current settings
        const merged = normalizeSettings({ ...settings.value, ...data })
        settings.value = merged
        // Update localStorage
        localStorage.setItem(STORAGE_KEY, JSON.stringify(settings.value))
        backendSynced.value = true
        console.debug('Settings loaded from backend database')

        // Update avatar API base URL
        updateApiBase(settings.value.backendUrl)
      }
    } catch (error) {
      // Backend might not be running, use local settings
      console.debug('Backend not available, using local settings')
    }
  }

  function save() {
    if (typeof window === 'undefined') return
    const normalized = normalizeSettings(settings.value)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized))

    // Sync with backend (debounce 500ms)
    syncWithBackend()
  }

  let syncTimeout: number | undefined
  async function syncWithBackend() {
    // Prevent recursive calls
    if (isSyncing.value) {
      return
    }

    if (syncTimeout) clearTimeout(syncTimeout)

    syncTimeout = window.setTimeout(async () => {
      isSyncing.value = true
      try {
        // First, send settings to backend
        const updateResponse = await fetch(`${settings.value.backendUrl}/settings/update`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            hostname: settings.value.hostname,
            person_name: settings.value.personName,
            log_upload_enabled: settings.value.logUploadEnabled,
            log_upload_time: settings.value.logUploadTime,
            log_upload_url: settings.value.logUploadUrl,
            // AI Settings
            ai_server_url: settings.value.aiServerUrl,
            system_prompt: settings.value.systemPrompt,  // 只保存自定义提示词（不含预设）
            prompt_style_key: settings.value.promptStyleKey,  // 保存预设风格选择
            ai_reply_timeout: settings.value.aiReplyTimeout,
            ai_reply_max_length: settings.value.aiReplyMaxLength,
            use_ai_reply: settings.value.useAIReply,  // 保存 AI 回复开关

            // Sidecar Settings
            send_via_sidecar: settings.value.sendViaSidecar,  // 保存 Sidecar 开关
            sidecar_poll_interval: settings.value.sidecarPollInterval,
            countdown_seconds: settings.value.countdownSeconds,
            sidecar_show_logs: settings.value.sidecarShowLogs,  // 保存日志面板开关

            // Image review server
            image_upload_enabled: settings.value.imageUploadEnabled,
            image_server_ip: settings.value.imageServerIp,
            image_review_timeout_seconds: settings.value.imageReviewTimeoutSeconds,
            low_spec_mode: settings.value.lowSpecMode,
            max_concurrent_sync_devices: settings.value.maxConcurrentSyncDevices,
            sidecar_max_panels: settings.value.sidecarMaxPanels,

            // Generic
            timezone: settings.value.timezone,
            email_enabled: settings.value.emailEnabled,
            email_smtp_server: settings.value.emailSmtpServer,
            email_smtp_port: settings.value.emailSmtpPort,
            email_sender_email: settings.value.emailSenderEmail,
            email_sender_password: settings.value.emailSenderPassword,
            email_sender_name: settings.value.emailSenderName,
            email_receiver_email: settings.value.emailReceiverEmail,
            email_notify_on_voice: settings.value.emailNotifyOnVoice,
            email_notify_on_human_request: settings.value.emailNotifyOnHumanRequest,
            email_notify_on_error: settings.value.emailNotifyOnError,
            email_error_notify_min_level: settings.value.emailErrorNotifyMinLevel,
            email_error_rate_limit_minutes: settings.value.emailErrorRateLimitMinutes,

            // Dashboard
            dashboard_enabled: settings.value.dashboardEnabled,
            dashboard_url: settings.value.dashboardUrl,
          })
        })

        if (updateResponse.ok) {
          // Settings successfully saved to backend
          backendSynced.value = true

          // Update avatar API base URL when backend URL changes
          updateApiBase(settings.value.backendUrl)
        } else {
          console.error('Failed to update settings on backend:', updateResponse.status)
        }
      } catch (error) {
        console.error('Failed to sync settings with backend:', error)
      } finally {
        isSyncing.value = false
      }
    }, 500)
  }

  function update(partial: Partial<AppSettings>) {
    settings.value = normalizeSettings({ ...settings.value, ...partial })
    save()
  }

  function reset() {
    settings.value = { ...DEFAULT_SETTINGS }
    save()
  }

  function setCountdownSeconds(seconds: number) {
    update({ countdownSeconds: seconds })
  }

  async function setTimezone(timezone: string) {
    // Update local settings
    update({ timezone })

    // Sync with backend
    try {
      const response = await fetch(`${settings.value.backendUrl}/settings/timezone`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ timezone }),
      })
      if (!response.ok) {
        console.error('Failed to sync timezone with backend')
      }
    } catch (error) {
      console.error('Failed to sync timezone with backend:', error)
    }
  }

  async function loadTimezoneFromBackend() {
    // Try to load timezone from backend on startup
    try {
      const response = await fetch(`${settings.value.backendUrl}/settings/timezone`)
      if (response.ok) {
        const data = await response.json()
        if (data.timezone && data.timezone !== settings.value.timezone) {
          settings.value.timezone = data.timezone
          save()
        }
      }
    } catch (error) {
      // Backend might not be running, use local settings
      console.debug('Backend not available, using local timezone settings')
    }
  }

  async function fetchPerformanceProfile(): Promise<PerformanceProfile | null> {
    try {
      const response = await fetch(`${settings.value.backendUrl}/settings/performance/profile`)
      if (!response.ok) return null
      return await response.json()
    } catch (error) {
      console.debug('Failed to load performance profile', error)
      return null
    }
  }

  // Attempt to load immediately for first use
  load()

  // Auto-save on changes
  watch(
    settings,
    () => {
      if (loaded.value && !isSyncing.value) {
        save()
      }
    },
    { deep: true }
  )

  // Get the combined system prompt (style preset + custom prompt)
  const combinedSystemPrompt = computed(() => {
    const stylePreset = PROMPT_STYLE_PRESETS.find(p => p.key === settings.value.promptStyleKey)
    const stylePrompt = stylePreset?.prompt || ''
    const customPrompt = settings.value.systemPrompt || ''

    // Build base prompt: Custom prompt first, then style preset
    let basePrompt = ''
    if (customPrompt && stylePrompt) {
      basePrompt = `${customPrompt}\n\n${stylePrompt}`
    } else {
      basePrompt = customPrompt || stylePrompt
    }

    return basePrompt
  })

  return {
    settings,
    loaded,
    backendSynced,
    load,
    loadFromBackend,
    save,
    update,
    reset,
    setCountdownSeconds,
    setTimezone,
    loadTimezoneFromBackend,
    fetchPerformanceProfile,
    timezonePresets: TIMEZONE_PRESETS,
    promptStylePresets: PROMPT_STYLE_PRESETS,
    combinedSystemPrompt,
  }
})
