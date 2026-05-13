<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useSettingsStore, type TimezonePreset, type PerformanceProfile } from '../stores/settings'
import { useI18n } from '../composables/useI18n'
import LanguageSwitch from '../components/LanguageSwitch.vue'

const settingsStore = useSettingsStore()
const { settings } = storeToRefs(settingsStore)
const { t } = useI18n()

const performanceProfile = ref<PerformanceProfile | null>(null)
const performanceProfileLoading = ref(false)
let performanceProfileTimer: number | undefined

async function loadPerformanceProfile() {
  performanceProfileLoading.value = true
  try {
    performanceProfile.value = await settingsStore.fetchPerformanceProfile()
  } finally {
    performanceProfileLoading.value = false
  }
}

const saveSettings = () => {
  settingsStore.save()
  if (performanceProfileTimer) {
    window.clearTimeout(performanceProfileTimer)
  }
  performanceProfileTimer = window.setTimeout(() => {
    loadPerformanceProfile()
  }, 800)
}
const resetSettings = () => {
  settingsStore.reset()
  loadPerformanceProfile()
}
const clearSystemPrompt = () => {
  settings.value.systemPrompt = ''
  saveSettings()
}

// Timezone handling
const timezonePresets = settingsStore.timezonePresets
const customTimezone = ref('')
const showCustomTimezone = ref(false)

// Prompt style presets
const promptStylePresets = settingsStore.promptStylePresets
const combinedSystemPrompt = computed(() => settingsStore.combinedSystemPrompt)

// Computed property for selected preset preview - ensures reactive update
const selectedPresetPrompt = computed(() => {
  const key = settings.value.promptStyleKey
  if (!key || key === 'none') return null
  const preset = promptStylePresets.find((p) => p.key === key)
  return preset?.prompt || null
})

// AI Analysis test
const showApiKey = ref(false)
const aiTestLoading = ref(false)
const aiTestResult = ref<{ success: boolean; message: string } | null>(null)

// Volcengine ASR
const showVolcengineApiKey = ref(false)
const volcengineSyncStatus = ref<string | null>(null)
const volcengineTestLoading = ref(false)
const volcengineTestResult = ref<{
  success: boolean
  message: string
  transcription?: string
} | null>(null)

// Email notification
const showEmailPassword = ref(false)
const emailTestLoading = ref(false)
const emailTestResult = ref<{ success: boolean; message: string } | null>(null)

// Image review server test
const imageReviewTestLoading = ref(false)
const imageReviewTestResult = ref<{ success: boolean; message: string } | null>(null)

// Dashboard monitoring test
const dashboardTestLoading = ref(false)
const dashboardTestResult = ref<{ success: boolean; message: string } | null>(null)

async function testImageReviewConnection() {
  imageReviewTestLoading.value = true
  imageReviewTestResult.value = null

  try {
    const response = await fetch(`${settings.value.backendUrl}/settings/image-review/test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })

    const data = await response.json()
    imageReviewTestResult.value = {
      success: data.success,
      message: data.success
        ? t('settings.image_review_test_success', { latency_ms: String(data.latency_ms ?? '') })
        : data.message || t('settings.image_review_test_failed'),
    }
  } catch (e) {
    imageReviewTestResult.value = {
      success: false,
      message: e instanceof Error ? e.message : t('settings.image_review_connection_failed'),
    }
  } finally {
    imageReviewTestLoading.value = false
  }
}

async function testDashboardConnection() {
  dashboardTestLoading.value = true
  dashboardTestResult.value = null

  try {
    const response = await fetch(`${settings.value.backendUrl}/settings/dashboard/test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: settings.value.dashboardUrl }),
    })

    const data = await response.json()
    dashboardTestResult.value = {
      success: data.success,
      message: data.message || (data.success ? 'Connection successful' : 'Connection failed'),
    }
  } catch (e) {
    dashboardTestResult.value = {
      success: false,
      message: e instanceof Error ? e.message : 'Connection failed',
    }
  } finally {
    dashboardTestLoading.value = false
  }
}

// Log upload
const showLogUploadToken = ref(false)
const logUploadLoading = ref(false)
const logUploadResult = ref<{ success: boolean; message: string } | null>(null)
const logUploadStatus = ref<{
  running: boolean
  enabled: boolean
  hostname: string
  device_id: string
  person_name: string
  upload_time: string
  upload_url: string
  has_token: boolean
  timezone: string
  is_uploading: boolean
  config_error?: string | null
  next_run_at?: string | null
  last_run?: {
    status?: string
    started_at?: string
    completed_at?: string
    files_total?: number
    files_uploaded?: number
    files_skipped?: number
    error_message?: string | null
  } | null
} | null>(null)

function formatLogUploadResult(data: {
  success?: boolean
  message?: string
  files_total?: number
  files_uploaded?: number
  files_skipped?: number
  errors?: string[]
}) {
  const filesTotal = Number(data.files_total ?? 0)
  const filesUploaded = Number(data.files_uploaded ?? 0)
  const filesSkipped = Number(data.files_skipped ?? 0)

  if (filesTotal === 0) {
    return {
      success: true,
      message: t('settings.log_upload_no_files'),
    }
  }

  if (filesUploaded === 0 && filesSkipped > 0 && (!data.errors || data.errors.length === 0)) {
    return {
      success: true,
      message: t('settings.log_upload_skipped_only', { count: String(filesSkipped) }),
    }
  }

  return {
    success: Boolean(data.success),
    message:
      data.message ||
      (data.success ? t('settings.log_upload_done') : t('settings.log_upload_failed_generic')),
  }
}

async function testVolcengineConnection() {
  volcengineTestLoading.value = true
  volcengineTestResult.value = null

  try {
    const response = await fetch(`${settings.value.backendUrl}/settings/volcengine-asr/test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })

    const data = await response.json()
    volcengineTestResult.value = {
      success: data.success,
      message: data.success
        ? `Connected! (${data.latency_ms}ms)${data.transcription ? ` - "${data.transcription}"` : ''}`
        : data.message || 'Connection failed',
      transcription: data.transcription,
    }
  } catch (e) {
    volcengineTestResult.value = {
      success: false,
      message: e instanceof Error ? e.message : 'Connection failed',
    }
  } finally {
    volcengineTestLoading.value = false
  }
}

async function testEmailConnection() {
  emailTestLoading.value = true
  emailTestResult.value = null

  try {
    const response = await fetch(`${settings.value.backendUrl}/settings/email/test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        smtp_server: settings.value.emailSmtpServer,
        smtp_port: settings.value.emailSmtpPort,
        sender_email: settings.value.emailSenderEmail,
        sender_password: settings.value.emailSenderPassword,
        sender_name: settings.value.emailSenderName,
        receiver_email: settings.value.emailReceiverEmail,
      }),
    })

    const data = await response.json()
    emailTestResult.value = {
      success: data.success,
      message: data.success ? '✅ Test email sent successfully!' : data.message || 'Send failed',
    }
  } catch (e) {
    emailTestResult.value = {
      success: false,
      message: e instanceof Error ? e.message : 'Connection failed',
    }
  } finally {
    emailTestLoading.value = false
  }
}

async function loadLogUploadStatus() {
  try {
    const response = await fetch(`${settings.value.backendUrl}/api/log-upload/status`)
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }
    logUploadStatus.value = await response.json()
  } catch (error) {
    console.error('Failed to load log upload status:', error)
    logUploadStatus.value = null
  }
}

async function triggerLogUploadNow() {
  logUploadLoading.value = true
  logUploadResult.value = null

  try {
    const response = await fetch(`${settings.value.backendUrl}/api/log-upload/trigger`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
    const data = await response.json()
    logUploadResult.value = formatLogUploadResult(data)
    await loadLogUploadStatus()
  } catch (error) {
    logUploadResult.value = {
      success: false,
      message: error instanceof Error ? error.message : t('settings.log_upload_failed_generic'),
    }
  } finally {
    logUploadLoading.value = false
  }
}

// Save email settings to backend for sync scripts to use
async function syncEmailSettings() {
  try {
    await fetch(`${settings.value.backendUrl}/settings/email/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        enabled: settings.value.emailEnabled,
        smtp_server: settings.value.emailSmtpServer,
        smtp_port: settings.value.emailSmtpPort,
        sender_email: settings.value.emailSenderEmail,
        sender_password: settings.value.emailSenderPassword,
        sender_name: settings.value.emailSenderName,
        receiver_email: settings.value.emailReceiverEmail,
        notify_on_voice: settings.value.emailNotifyOnVoice,
        notify_on_human_request: settings.value.emailNotifyOnHumanRequest,
      }),
    })
  } catch (error) {
    console.error('Failed to sync email settings:', error)
  }
}

// Combined save function for email settings
async function saveEmailSettings() {
  saveSettings()
  await syncEmailSettings()
}

async function syncVolcengineSettings() {
  volcengineSyncStatus.value = 'syncing'
  try {
    await fetch(`${settings.value.backendUrl}/settings/volcengine-asr`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        enabled: settings.value.volcengineAsrEnabled,
        api_key: settings.value.volcengineAsrApiKey,
        resource_id: settings.value.volcengineAsrResourceId,
      }),
    })
    volcengineSyncStatus.value = 'synced'
    setTimeout(() => {
      volcengineSyncStatus.value = null
    }, 2000)
  } catch (error) {
    volcengineSyncStatus.value = 'error'
    console.error('Failed to sync Volcengine settings:', error)
  }
}

async function saveVolcengineSettings() {
  saveSettings()
  await syncVolcengineSettings()
}

async function testAiConnection() {
  aiTestLoading.value = true
  aiTestResult.value = null

  try {
    const response = await fetch(`${settings.value.backendUrl}/streamers/test-ai`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: settings.value.aiAnalysisProvider,
        base_url: settings.value.aiAnalysisBaseUrl,
        api_key: settings.value.aiAnalysisApiKey,
        model: settings.value.aiAnalysisModel,
      }),
    })

    const data = await response.json()
    aiTestResult.value = {
      success: data.success,
      message: data.success
        ? `Connected! (${data.latency_ms}ms)`
        : data.error || 'Connection failed',
    }
  } catch (e) {
    aiTestResult.value = {
      success: false,
      message: e instanceof Error ? e.message : 'Connection failed',
    }
  } finally {
    aiTestLoading.value = false
  }
}

// Get display name for current timezone
const currentTimezoneDisplay = computed(() => {
  const preset = timezonePresets.find((p: TimezonePreset) => p.timezone === settings.value.timezone)
  return preset ? preset.name : settings.value.timezone
})

// Check if current timezone is a preset
const isPresetTimezone = computed(() => {
  return timezonePresets.some((p: TimezonePreset) => p.timezone === settings.value.timezone)
})

async function handleTimezoneChange(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  if (value === '__custom__') {
    showCustomTimezone.value = true
    customTimezone.value = settings.value.timezone
  } else {
    showCustomTimezone.value = false
    await settingsStore.setTimezone(value)
  }
}

async function applyCustomTimezone() {
  if (customTimezone.value) {
    await settingsStore.setTimezone(customTimezone.value)
    showCustomTimezone.value = false
  }
}

onMounted(async () => {
  settingsStore.load()
  // Try to load settings from backend database
  await settingsStore.loadFromBackend()
  // Try to sync timezone from backend
  await settingsStore.loadTimezoneFromBackend()
  await loadLogUploadStatus()
  await loadPerformanceProfile()
})
</script>

<template>
  <div class="p-6 space-y-8 animate-fade-in max-w-3xl">
    <!-- Header -->
    <div>
      <h2 class="text-2xl font-display font-bold text-wecom-text">
        {{ t('settings.title') }}
      </h2>
      <p class="text-sm text-wecom-muted mt-1">
        {{ t('settings.subtitle') }}
      </p>
    </div>

    <!-- General Settings -->
    <section class="space-y-4">
      <h3
        class="text-lg font-display font-semibold text-wecom-text border-b border-wecom-border pb-2"
      >
        {{ t('settings.general_title') }}
      </h3>

      <div class="grid gap-4">
        <!-- Hostname Setting -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">{{
              t('settings.general_hostname')
            }}</label>
            <p class="text-xs text-wecom-muted">
              {{ t('settings.general_hostname_desc') }}
            </p>
          </div>
          <input
            v-model="settings.hostname"
            type="text"
            class="input-field w-56"
            :placeholder="t('settings.general_hostname_placeholder')"
            @change="saveSettings"
          />
        </div>

        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">{{
              t('settings.general_device_id')
            }}</label>
            <p class="text-xs text-wecom-muted">
              {{ t('settings.general_device_id_desc') }}
            </p>
          </div>
          <input
            :value="settings.deviceId || logUploadStatus?.device_id || ''"
            type="text"
            class="input-field w-72 font-mono text-xs opacity-80"
            readonly
          />
        </div>

        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">{{
              t('settings.general_person_name')
            }}</label>
            <p class="text-xs text-wecom-muted">
              {{ t('settings.general_person_name_desc') }}
            </p>
          </div>
          <input
            v-model="settings.personName"
            type="text"
            class="input-field w-56"
            :placeholder="t('settings.general_person_name_placeholder')"
            @change="saveSettings"
          />
        </div>
      </div>
    </section>

    <!-- Timezone Settings -->
    <section class="space-y-4">
      <h3
        class="text-lg font-display font-semibold text-wecom-text border-b border-wecom-border pb-2"
      >
        {{ t('settings.timezone_title') }}
      </h3>

      <div class="grid gap-4">
        <!-- Timezone Selection -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">{{
              t('settings.timezone_label')
            }}</label>
            <p class="text-xs text-wecom-muted">
              {{ t('settings.timezone_description') }}
            </p>
          </div>
          <div class="flex flex-col items-end gap-2">
            <select
              :value="isPresetTimezone ? settings.timezone : '__custom__'"
              class="input-field w-56"
              @change="handleTimezoneChange"
            >
              <option v-for="preset in timezonePresets" :key="preset.key" :value="preset.timezone">
                {{ preset.name }}
              </option>
              <option value="__custom__">{{ t('settings.timezone_custom') }}</option>
            </select>

            <!-- Custom timezone input -->
            <div v-if="showCustomTimezone" class="flex items-center gap-2">
              <input
                v-model="customTimezone"
                type="text"
                :placeholder="t('settings.timezone_custom_placeholder')"
                class="input-field w-48 text-sm"
                @keyup.enter="applyCustomTimezone"
              />
              <button class="btn-primary text-xs px-3 py-1" @click="applyCustomTimezone">
                {{ t('settings.timezone_apply') }}
              </button>
            </div>
          </div>
        </div>

        <!-- Current timezone display -->
        <div class="flex items-center justify-between bg-wecom-surface/50 rounded-lg px-4 py-3">
          <div class="flex items-center gap-2">
            <svg
              class="w-5 h-5 text-wecom-primary"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
            <span class="text-sm text-wecom-text">{{ t('settings.timezone_current') }}:</span>
          </div>
          <span class="text-sm font-medium text-wecom-primary">{{ currentTimezoneDisplay }}</span>
        </div>
      </div>
    </section>

    <!-- Language Settings -->
    <section class="space-y-4">
      <h3
        class="text-lg font-display font-semibold text-wecom-text border-b border-wecom-border pb-2"
      >
        {{ t('settings.language_title') }}
      </h3>

      <div class="grid gap-4">
        <!-- Language Selection -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">{{
              t('settings.language_label')
            }}</label>
            <p class="text-xs text-wecom-muted">
              {{ t('settings.language_description') }}
            </p>
          </div>
          <LanguageSwitch />
        </div>

        <!-- Language Info -->
        <div class="flex items-center justify-between bg-wecom-surface/50 rounded-lg px-4 py-3">
          <div class="flex items-center gap-2">
            <svg
              class="w-5 h-5 text-wecom-primary"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129"
              />
            </svg>
            <span class="text-sm text-wecom-text">{{ t('settings.language_saved_note') }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- Sync Settings -->
    <section class="space-y-4">
      <h3
        class="text-lg font-display font-semibold text-wecom-text border-b border-wecom-border pb-2"
      >
        {{ t('settings.sync_title') }}
      </h3>

      <div class="grid gap-4">
        <!-- Timing Multiplier -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">{{
              t('settings.sync_timing_multiplier')
            }}</label>
            <p class="text-xs text-wecom-muted">{{ t('settings.sync_timing_multiplier_desc') }}</p>
          </div>
          <input
            v-model.number="settings.timingMultiplier"
            type="number"
            min="0.5"
            max="5.0"
            step="0.1"
            class="input-field w-24 text-center"
            @change="saveSettings"
          />
        </div>

        <!-- Auto Placeholder -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">{{
              t('settings.sync_auto_placeholder')
            }}</label>
            <p class="text-xs text-wecom-muted">{{ t('settings.sync_auto_placeholder_desc') }}</p>
          </div>
          <label class="relative inline-flex items-center cursor-pointer">
            <input
              v-model="settings.autoPlaceholder"
              type="checkbox"
              class="sr-only peer"
              @change="saveSettings"
            />
            <div
              class="w-11 h-6 bg-wecom-surface peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-wecom-primary"
            ></div>
          </label>
        </div>

        <!-- No Test Messages -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">{{
              t('settings.sync_no_test_messages')
            }}</label>
            <p class="text-xs text-wecom-muted">{{ t('settings.sync_no_test_messages_desc') }}</p>
          </div>
          <label class="relative inline-flex items-center cursor-pointer">
            <input
              v-model="settings.noTestMessages"
              type="checkbox"
              class="sr-only peer"
              @change="saveSettings"
            />
            <div
              class="w-11 h-6 bg-wecom-surface peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-wecom-primary"
            ></div>
          </label>
        </div>
      </div>
    </section>

    <section class="space-y-4">
      <h3
        class="text-lg font-display font-semibold text-wecom-text border-b border-wecom-border pb-2"
      >
        Performance Mode
      </h3>

      <div class="grid gap-4">
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">Low-spec mode</label>
            <p class="text-xs text-wecom-muted">
              Reduce concurrency, slow down polling, and move AI image review off the sync hot path.
            </p>
          </div>
          <label class="relative inline-flex items-center cursor-pointer">
            <input
              v-model="settings.lowSpecMode"
              type="checkbox"
              class="sr-only peer"
              @change="saveSettings"
            />
            <div
              class="w-11 h-6 bg-wecom-surface peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-wecom-primary"
            ></div>
          </label>
        </div>

        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">Max concurrent sync devices</label>
            <p class="text-xs text-wecom-muted">
              Runtime will cap this to 1 while low-spec mode is enabled.
            </p>
          </div>
          <input
            v-model.number="settings.maxConcurrentSyncDevices"
            type="number"
            min="1"
            max="8"
            class="input-field w-24 text-center"
            @change="saveSettings"
          />
        </div>

        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">Sidecar max panels</label>
            <p class="text-xs text-wecom-muted">
              Limits side-by-side sidecar panes to match the available machine budget.
            </p>
          </div>
          <input
            v-model.number="settings.sidecarMaxPanels"
            type="number"
            min="1"
            max="3"
            class="input-field w-24 text-center"
            @change="saveSettings"
          />
        </div>

        <div class="rounded-xl border border-wecom-border bg-wecom-surface/60 p-4 space-y-2">
          <div class="flex items-center justify-between">
            <span class="text-sm font-medium text-wecom-text">Resolved runtime profile</span>
            <button class="btn-secondary text-xs px-3 py-1" @click="loadPerformanceProfile">
              Refresh
            </button>
          </div>
          <p v-if="performanceProfileLoading" class="text-xs text-wecom-muted">Loading performance metrics...</p>
          <template v-else-if="performanceProfile">
            <div class="grid grid-cols-2 gap-2 text-xs text-wecom-muted">
              <div>
                Effective sync concurrency: {{ performanceProfile.effective.maxConcurrentSyncDevices }}
              </div>
              <div>
                Effective sidecar poll: {{ performanceProfile.effective.sidecarPollInterval }}s
              </div>
              <div>
                Effective realtime scan: {{ performanceProfile.effective.scanInterval }}s
              </div>
              <div>
                Effective sidecar panels: {{ performanceProfile.effective.sidecarMaxPanels }}
              </div>
              <div>
                Startup: {{ performanceProfile.metrics.startup?.duration_ms ?? 'n/a' }} ms
              </div>
              <div>
                Memory: {{ performanceProfile.metrics.runtime?.memory_mb ?? 'n/a' }} MB
              </div>
              <div>
                ADB calls: {{ performanceProfile.metrics.adb?.total_calls ?? 0 }}
              </div>
              <div>
                Slow SQLite queries: {{ performanceProfile.metrics.sqlite?.slow_queries ?? 0 }}
              </div>
            </div>
          </template>
          <p v-else class="text-xs text-wecom-muted">
            Runtime metrics are unavailable until the backend is running.
          </p>
        </div>
      </div>
    </section>

    <!-- Mirror Settings -->
    <section class="space-y-4">
      <h3
        class="text-lg font-display font-semibold text-wecom-text border-b border-wecom-border pb-2"
      >
        {{ t('settings.mirror_title') }}
      </h3>

      <div class="grid gap-4">
        <!-- Max Size -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">{{
              t('settings.mirror_max_resolution')
            }}</label>
            <p class="text-xs text-wecom-muted">{{ t('settings.mirror_max_resolution_desc') }}</p>
          </div>
          <select
            v-model.number="settings.mirrorMaxSize"
            class="input-field w-32"
            @change="saveSettings"
          >
            <option :value="720">720p</option>
            <option :value="1080">1080p</option>
            <option :value="1440">1440p</option>
            <option :value="0">{{ t('settings.mirror_original') }}</option>
          </select>
        </div>

        <!-- Bit Rate -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">{{
              t('settings.mirror_bitrate')
            }}</label>
            <p class="text-xs text-wecom-muted">{{ t('settings.mirror_bitrate_desc') }}</p>
          </div>
          <input
            v-model.number="settings.mirrorBitRate"
            type="number"
            min="1"
            max="32"
            class="input-field w-24 text-center"
            @change="saveSettings"
          />
        </div>

        <!-- Max FPS -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">{{
              t('settings.mirror_max_fps')
            }}</label>
            <p class="text-xs text-wecom-muted">{{ t('settings.mirror_max_fps_desc') }}</p>
          </div>
          <select
            v-model.number="settings.mirrorMaxFps"
            class="input-field w-32"
            @change="saveSettings"
          >
            <option :value="30">30 FPS</option>
            <option :value="60">60 FPS</option>
            <option :value="120">120 FPS</option>
          </select>
        </div>

        <!-- Stay Awake -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">{{
              t('settings.mirror_stay_awake')
            }}</label>
            <p class="text-xs text-wecom-muted">{{ t('settings.mirror_stay_awake_desc') }}</p>
          </div>
          <label class="relative inline-flex items-center cursor-pointer">
            <input
              v-model="settings.mirrorStayAwake"
              type="checkbox"
              class="sr-only peer"
              @change="saveSettings"
            />
            <div
              class="w-11 h-6 bg-wecom-surface peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-wecom-primary"
            ></div>
          </label>
        </div>

        <!-- Show Touches -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">{{
              t('settings.mirror_show_touches')
            }}</label>
            <p class="text-xs text-wecom-muted">{{ t('settings.mirror_show_touches_desc') }}</p>
          </div>
          <label class="relative inline-flex items-center cursor-pointer">
            <input
              v-model="settings.mirrorShowTouches"
              type="checkbox"
              class="sr-only peer"
              @change="saveSettings"
            />
            <div
              class="w-11 h-6 bg-wecom-surface peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-wecom-primary"
            ></div>
          </label>
        </div>
      </div>
    </section>

    <!-- AI Reply Settings -->
    <section class="space-y-4">
      <h3
        class="text-lg font-display font-semibold text-wecom-text border-b border-wecom-border pb-2"
      >
        {{ t('settings.ai_reply_title') }}
      </h3>

      <div class="grid gap-4">
        <!-- Use AI Reply Toggle -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">{{
              t('settings.ai_reply_use')
            }}</label>
            <p class="text-xs text-wecom-muted">
              {{ t('settings.ai_reply_use_desc') }}
            </p>
          </div>
          <label class="relative inline-flex items-center cursor-pointer">
            <input
              v-model="settings.useAIReply"
              type="checkbox"
              class="sr-only peer"
              @change="saveSettings"
            />
            <div
              class="w-11 h-6 bg-wecom-surface peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-wecom-primary"
            ></div>
          </label>
        </div>

        <!-- AI Server URL -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">{{
              t('settings.ai_reply_server_url')
            }}</label>
            <p class="text-xs text-wecom-muted">{{ t('settings.ai_reply_server_url_desc') }}</p>
          </div>
          <input
            v-model="settings.aiServerUrl"
            type="text"
            placeholder="http://localhost:8000"
            class="input-field w-64 text-sm"
            @change="saveSettings"
          />
        </div>

        <!-- AI Reply Timeout -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">{{
              t('settings.ai_reply_timeout')
            }}</label>
            <p class="text-xs text-wecom-muted">
              {{ t('settings.ai_reply_timeout_desc') }}
            </p>
          </div>
          <div class="flex items-center gap-3">
            <input
              v-model.number="settings.aiReplyTimeout"
              type="range"
              min="1"
              max="30"
              class="w-40"
              @input="saveSettings"
            />
            <input
              v-model.number="settings.aiReplyTimeout"
              type="number"
              min="1"
              max="30"
              class="input-field w-20 text-center"
              @change="saveSettings"
            />
            <span class="text-sm text-wecom-muted">{{
              t('settings.ai_reply_timeout_seconds')
            }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- Image Review Server Settings -->
    <section class="space-y-4">
      <h3
        class="text-lg font-display font-semibold text-wecom-text border-b border-wecom-border pb-2"
      >
        🖼️ {{ t('settings.image_review_title') }}
      </h3>
      <p class="text-xs text-wecom-muted">
        {{ t('settings.image_review_intro') }}
      </p>

      <div class="grid gap-4">
        <!-- Enable Image Upload Toggle -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">{{
              t('settings.image_review_auto_upload')
            }}</label>
            <p class="text-xs text-wecom-muted">
              {{ t('settings.image_review_auto_upload_desc') }}
            </p>
          </div>
          <label class="relative inline-flex items-center cursor-pointer">
            <input
              v-model="settings.imageUploadEnabled"
              type="checkbox"
              class="sr-only peer"
              @change="saveSettings"
            />
            <div
              class="w-11 h-6 bg-wecom-surface peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-wecom-primary"
            ></div>
          </label>
        </div>

        <!-- Server address and test — only shown when upload is enabled -->
        <template v-if="settings.imageUploadEnabled">
          <div class="flex items-center justify-between">
            <div>
              <label class="text-sm font-medium text-wecom-text">{{
                t('settings.image_review_server_url')
              }}</label>
              <p class="text-xs text-wecom-muted">
                {{ t('settings.image_review_server_url_desc') }}
              </p>
            </div>
            <input
              v-model="settings.imageServerIp"
              type="text"
              placeholder="http://192.168.1.100:8000"
              class="input-field w-72 text-sm"
              @change="saveSettings"
            />
          </div>

          <div class="flex items-center justify-between">
            <div>
              <label class="text-sm font-medium text-wecom-text">{{
                t('settings.image_review_timeout')
              }}</label>
              <p class="text-xs text-wecom-muted">{{ t('settings.image_review_timeout_desc') }}</p>
            </div>
            <div class="flex items-center gap-3">
              <input
                v-model.number="settings.imageReviewTimeoutSeconds"
                type="number"
                min="1"
                max="300"
                class="input-field w-24 text-center"
                @change="saveSettings"
              />
              <span class="text-sm text-wecom-muted">{{
                t('settings.image_review_seconds_unit')
              }}</span>
            </div>
          </div>

          <!-- Test Upload -->
          <div class="flex items-center justify-between bg-wecom-surface/50 rounded-lg px-4 py-3">
            <div class="flex items-center gap-2 flex-1">
              <span class="text-sm text-wecom-text">{{
                t('settings.image_review_test_send')
              }}</span>
              <span
                v-if="imageReviewTestResult"
                :class="imageReviewTestResult.success ? 'text-green-400' : 'text-red-400'"
                class="text-xs truncate max-w-[300px]"
                :title="imageReviewTestResult.message"
              >
                {{ imageReviewTestResult.message }}
              </span>
            </div>
            <button
              class="btn-secondary text-sm"
              :disabled="imageReviewTestLoading || !settings.imageServerIp"
              @click="testImageReviewConnection"
            >
              <span v-if="imageReviewTestLoading" class="animate-spin">⏳</span>
              <span v-else>🖼️</span>
              {{ t('settings.image_review_test_button') }}
            </button>
          </div>
        </template>
      </div>
    </section>

    <!-- System Prompt Settings -->
    <section class="space-y-4">
      <h3
        class="text-lg font-display font-semibold text-wecom-text border-b border-wecom-border pb-2"
      >
        📝 System Prompt
      </h3>
      <p class="text-xs text-wecom-muted">
        Select a preset style and customize the system prompt. AI will generate replies based on
        these settings.
      </p>

      <div class="grid gap-4">
        <!-- Custom System Prompt Textarea (moved to top) -->
        <div class="space-y-2">
          <label class="text-sm font-medium text-wecom-text"
            >Custom System Prompt <span class="text-wecom-primary">(highest priority)</span></label
          >
          <p class="text-xs text-wecom-muted">
            Enter your system prompt here. It will be placed at the beginning of the final prompt.
          </p>
          <textarea
            v-model="settings.systemPrompt"
            rows="6"
            placeholder="Enter system prompt instructions here..."
            class="input-field w-full text-sm font-mono resize-y min-h-[100px]"
            @change="saveSettings"
          ></textarea>
          <div class="flex items-center justify-between text-xs text-wecom-muted">
            <span>{{ settings.systemPrompt?.length || 0 }} characters</span>
            <button
              type="button"
              class="text-wecom-primary hover:text-wecom-secondary transition-colors"
              @click="clearSystemPrompt"
            >
              Clear
            </button>
          </div>
        </div>

        <!-- Prompt Style Preset Dropdown -->
        <div class="space-y-2">
          <label class="text-sm font-medium text-wecom-text"
            >Prompt Style Preset <span class="text-wecom-muted">(second priority)</span></label
          >
          <p class="text-xs text-wecom-muted">
            Select a preset style. It will be appended after the custom prompt.
          </p>
          <select
            v-model="settings.promptStyleKey"
            class="input-field w-full text-sm"
            @change="saveSettings"
          >
            <option v-for="preset in promptStylePresets" :key="preset.key" :value="preset.key">
              {{ preset.name }} - {{ preset.description }}
            </option>
          </select>

          <!-- Preview of selected preset -->
          <div
            v-if="selectedPresetPrompt"
            class="p-3 bg-wecom-surface/50 rounded-lg border border-wecom-border/50"
          >
            <p class="text-xs text-wecom-muted mb-1">Preset Content Preview:</p>
            <p class="text-xs text-wecom-text whitespace-pre-line">
              {{ selectedPresetPrompt }}
            </p>
          </div>
        </div>

        <!-- Combined Preview -->
        <div class="space-y-2">
          <label class="text-sm font-medium text-wecom-text">Final Prompt Preview</label>
          <p class="text-xs text-wecom-muted">Composition order: Custom prompt → Preset style</p>
          <div
            class="p-3 bg-wecom-darker rounded-lg border border-wecom-border max-h-48 overflow-auto"
          >
            <p class="text-xs text-wecom-text whitespace-pre-line font-mono">
              {{ combinedSystemPrompt || '(none)' }}
            </p>
          </div>
        </div>
      </div>
    </section>

    <!-- AI Analysis Settings (Persona Analysis) -->
    <section class="space-y-4">
      <h3
        class="text-lg font-display font-semibold text-wecom-text border-b border-wecom-border pb-2"
      >
        🧠 AI Persona Analysis Settings
      </h3>
      <p class="text-xs text-wecom-muted">
        Configure AI-powered persona analysis for streamers. This uses conversation history to
        analyze communication patterns, personality traits, and generate actionable insights.
      </p>

      <div class="grid gap-4">
        <!-- Enable AI Analysis -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">Enable AI Analysis</label>
            <p class="text-xs text-wecom-muted">Allow AI-powered persona analysis for streamers</p>
          </div>
          <label class="relative inline-flex items-center cursor-pointer">
            <input
              v-model="settings.aiAnalysisEnabled"
              type="checkbox"
              class="sr-only peer"
              @change="saveSettings"
            />
            <div
              class="w-11 h-6 bg-wecom-surface peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-wecom-primary"
            ></div>
          </label>
        </div>

        <!-- AI Provider -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">AI Provider</label>
            <p class="text-xs text-wecom-muted">Choose the AI service provider for analysis</p>
          </div>
          <select
            v-model="settings.aiAnalysisProvider"
            class="input-field w-48"
            @change="saveSettings"
          >
            <option value="deepseek">DeepSeek</option>
            <option value="openai">OpenAI</option>
            <option value="custom">Custom API</option>
          </select>
        </div>

        <!-- API Base URL -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">API Base URL</label>
            <p class="text-xs text-wecom-muted">Base URL for the AI provider API</p>
          </div>
          <input
            v-model="settings.aiAnalysisBaseUrl"
            type="text"
            placeholder="https://api.deepseek.com"
            class="input-field w-64 text-sm"
            @change="saveSettings"
          />
        </div>

        <!-- API Key -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">API Key</label>
            <p class="text-xs text-wecom-muted">Your API key for the selected AI provider</p>
          </div>
          <div class="flex items-center gap-2">
            <input
              v-model="settings.aiAnalysisApiKey"
              :type="showApiKey ? 'text' : 'password'"
              placeholder="sk-..."
              class="input-field w-64 text-sm font-mono"
              @change="saveSettings"
            />
            <button
              type="button"
              class="btn-secondary text-xs px-2"
              @click="showApiKey = !showApiKey"
            >
              {{ showApiKey ? '🙈' : '👁️' }}
            </button>
          </div>
        </div>

        <!-- Model Selection -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">Model</label>
            <p class="text-xs text-wecom-muted">AI model to use for persona analysis</p>
          </div>
          <select
            v-model="settings.aiAnalysisModel"
            class="input-field w-48"
            @change="saveSettings"
          >
            <optgroup v-if="settings.aiAnalysisProvider === 'deepseek'" label="DeepSeek Models">
              <option value="deepseek-chat">DeepSeek Chat</option>
              <option value="deepseek-coder">DeepSeek Coder</option>
            </optgroup>
            <optgroup v-else-if="settings.aiAnalysisProvider === 'openai'" label="OpenAI Models">
              <option value="gpt-4o">GPT-4o</option>
              <option value="gpt-4o-mini">GPT-4o Mini</option>
              <option value="gpt-4-turbo">GPT-4 Turbo</option>
              <option value="gpt-3.5-turbo">GPT-3.5 Turbo</option>
            </optgroup>
            <optgroup v-else label="Custom">
              <option :value="settings.aiAnalysisModel">{{ settings.aiAnalysisModel }}</option>
            </optgroup>
          </select>
        </div>

        <!-- Max Tokens -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">Max Response Tokens</label>
            <p class="text-xs text-wecom-muted">
              Maximum tokens for analysis response (affects detail level)
            </p>
          </div>
          <div class="flex items-center gap-3">
            <input
              v-model.number="settings.aiAnalysisMaxTokens"
              type="range"
              min="1024"
              max="8192"
              step="256"
              class="w-40"
              @input="saveSettings"
            />
            <input
              v-model.number="settings.aiAnalysisMaxTokens"
              type="number"
              min="1024"
              max="8192"
              step="256"
              class="input-field w-24 text-center"
              @change="saveSettings"
            />
          </div>
        </div>

        <!-- Test Connection -->
        <div class="flex items-center justify-between bg-wecom-surface/50 rounded-lg px-4 py-3">
          <div class="flex items-center gap-2">
            <span class="text-sm text-wecom-text">Test AI Connection</span>
            <span
              v-if="aiTestResult"
              :class="aiTestResult.success ? 'text-green-400' : 'text-red-400'"
              class="text-xs"
            >
              {{ aiTestResult.message }}
            </span>
          </div>
          <button class="btn-secondary text-sm" :disabled="aiTestLoading" @click="testAiConnection">
            <span v-if="aiTestLoading" class="animate-spin">⏳</span>
            <span v-else>🔌</span>
            Test
          </button>
        </div>
      </div>
    </section>

    <!-- Volcengine ASR Settings (Voice Transcription) -->
    <section class="space-y-4">
      <h3
        class="text-lg font-display font-semibold text-wecom-text border-b border-wecom-border pb-2"
      >
        🎤 Volcengine ASR Settings
      </h3>
      <p class="text-xs text-wecom-muted">
        Configure Volcengine (ByteDance) ASR for voice message transcription. This service converts
        voice messages to text.
      </p>

      <div class="grid gap-4">
        <!-- Enable Voice Transcription -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">Enable Voice Transcription</label>
            <p class="text-xs text-wecom-muted">Allow automatic transcription of voice messages</p>
          </div>
          <label class="relative inline-flex items-center cursor-pointer">
            <input
              v-model="settings.volcengineAsrEnabled"
              type="checkbox"
              class="sr-only peer"
              @change="saveVolcengineSettings"
            />
            <div
              class="w-11 h-6 bg-wecom-surface peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-wecom-primary"
            ></div>
          </label>
        </div>

        <!-- API Key -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">API Key</label>
            <p class="text-xs text-wecom-muted">Your Volcengine ASR API key (x-api-key)</p>
          </div>
          <div class="flex items-center gap-2">
            <input
              v-model="settings.volcengineAsrApiKey"
              :type="showVolcengineApiKey ? 'text' : 'password'"
              placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
              class="input-field w-80 text-sm font-mono"
              @change="saveVolcengineSettings"
            />
            <button
              type="button"
              class="btn-secondary text-xs px-2"
              @click="showVolcengineApiKey = !showVolcengineApiKey"
            >
              {{ showVolcengineApiKey ? '🙈' : '👁️' }}
            </button>
          </div>
        </div>

        <!-- Resource ID -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">Resource ID</label>
            <p class="text-xs text-wecom-muted">ASR resource identifier (X-Api-Resource-Id)</p>
          </div>
          <input
            v-model="settings.volcengineAsrResourceId"
            type="text"
            placeholder="volc.seedasr.auc"
            class="input-field w-64 text-sm"
            @change="saveVolcengineSettings"
          />
        </div>

        <!-- Sync status indicator -->
        <div v-if="volcengineSyncStatus" class="flex items-center gap-2 text-xs">
          <span v-if="volcengineSyncStatus === 'syncing'" class="text-wecom-muted animate-pulse">
            ⏳ Syncing with backend...
          </span>
          <span v-else-if="volcengineSyncStatus === 'synced'" class="text-green-400">
            ✓ Settings synced
          </span>
          <span v-else-if="volcengineSyncStatus === 'error'" class="text-red-400">
            ⚠️ Failed to sync
          </span>
        </div>

        <!-- Test Connection -->
        <div class="flex items-center justify-between bg-wecom-surface/50 rounded-lg px-4 py-3">
          <div class="flex items-center gap-2 flex-1">
            <span class="text-sm text-wecom-text">Test ASR Connection</span>
            <span
              v-if="volcengineTestResult"
              :class="volcengineTestResult.success ? 'text-green-400' : 'text-red-400'"
              class="text-xs truncate max-w-[300px]"
              :title="volcengineTestResult.message"
            >
              {{ volcengineTestResult.message }}
            </span>
          </div>
          <button
            class="btn-secondary text-sm"
            :disabled="volcengineTestLoading"
            @click="testVolcengineConnection"
          >
            <span v-if="volcengineTestLoading" class="animate-spin">⏳</span>
            <span v-else>🔌</span>
            Test
          </button>
        </div>

        <!-- Info box -->
        <div class="bg-wecom-surface/50 rounded-lg px-4 py-3">
          <div class="flex items-start gap-2">
            <span class="text-wecom-primary mt-0.5">ℹ️</span>
            <div class="text-xs text-wecom-muted space-y-1">
              <p>
                Volcengine ASR uses the <strong>bigmodel</strong> API for high-quality speech
                recognition.
              </p>
              <p>
                Voice files are sent to Volcengine servers for processing. Ensure you have proper
                authorization.
              </p>
              <p>
                <a
                  href="https://www.volcengine.com/docs/6561/1354868"
                  target="_blank"
                  class="text-wecom-primary hover:underline"
                >
                  View API Documentation →
                </a>
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Email Notification Settings -->
    <section class="space-y-4">
      <h3
        class="text-lg font-display font-semibold text-wecom-text border-b border-wecom-border pb-2"
      >
        📧 Email Notification Settings
      </h3>
      <p class="text-xs text-wecom-muted">
        Configure email notifications to send alerts on sync completion, follow-up messages, or
        errors.
      </p>

      <div class="grid gap-4">
        <!-- Enable Email Notifications -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">Enable Email Notifications</label>
            <p class="text-xs text-wecom-muted">Send email alerts when specific events occur</p>
          </div>
          <label class="relative inline-flex items-center cursor-pointer">
            <input
              v-model="settings.emailEnabled"
              type="checkbox"
              class="sr-only peer"
              @change="saveEmailSettings"
            />
            <div
              class="w-11 h-6 bg-wecom-surface peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-wecom-primary"
            ></div>
          </label>
        </div>

        <!-- SMTP Server Settings (only show when enabled) -->
        <template v-if="settings.emailEnabled">
          <!-- SMTP Server -->
          <div class="flex items-center justify-between">
            <div>
              <label class="text-sm font-medium text-wecom-text">SMTP Server</label>
              <p class="text-xs text-wecom-muted">Email server address (QQ Mail: smtp.qq.com)</p>
            </div>
            <input
              v-model="settings.emailSmtpServer"
              type="text"
              placeholder="smtp.qq.com"
              class="input-field w-64 text-sm"
              @change="saveEmailSettings"
            />
          </div>

          <!-- SMTP Port -->
          <div class="flex items-center justify-between">
            <div>
              <label class="text-sm font-medium text-wecom-text">SMTP Port</label>
              <p class="text-xs text-wecom-muted">SSL port: 465, TLS port: 587</p>
            </div>
            <input
              v-model.number="settings.emailSmtpPort"
              type="number"
              placeholder="465"
              class="input-field w-32 text-sm text-center"
              @change="saveEmailSettings"
            />
          </div>

          <!-- Sender Email -->
          <div class="flex items-center justify-between">
            <div>
              <label class="text-sm font-medium text-wecom-text">Sender Email</label>
              <p class="text-xs text-wecom-muted">Email address used to send notifications</p>
            </div>
            <input
              v-model="settings.emailSenderEmail"
              type="email"
              placeholder="your_email@qq.com"
              class="input-field w-64 text-sm"
              @change="saveEmailSettings"
            />
          </div>

          <!-- Sender Password -->
          <div class="flex items-center justify-between">
            <div>
              <label class="text-sm font-medium text-wecom-text"
                >Authorization Code / Password</label
              >
              <p class="text-xs text-wecom-muted">
                Use authorization code for QQ Mail (not login password)
              </p>
            </div>
            <div class="flex items-center gap-2">
              <input
                v-model="settings.emailSenderPassword"
                :type="showEmailPassword ? 'text' : 'password'"
                placeholder="Authorization code"
                class="input-field w-56 text-sm font-mono"
                @change="saveEmailSettings"
              />
              <button
                type="button"
                class="btn-secondary text-xs px-2"
                @click="showEmailPassword = !showEmailPassword"
              >
                {{ showEmailPassword ? '🙈' : '👁️' }}
              </button>
            </div>
          </div>

          <!-- Sender Name -->
          <div class="flex items-center justify-between">
            <div>
              <label class="text-sm font-medium text-wecom-text">Sender Name</label>
              <p class="text-xs text-wecom-muted">Sender name displayed in emails</p>
            </div>
            <input
              v-model="settings.emailSenderName"
              type="text"
              placeholder="WeCom Sync System"
              class="input-field w-48 text-sm"
              @change="saveEmailSettings"
            />
          </div>

          <!-- Receiver Email -->
          <div class="flex items-center justify-between">
            <div>
              <label class="text-sm font-medium text-wecom-text">Receiver Email</label>
              <p class="text-xs text-wecom-muted">Email address to receive notifications</p>
            </div>
            <input
              v-model="settings.emailReceiverEmail"
              type="email"
              placeholder="receiver@example.com"
              class="input-field w-64 text-sm"
              @change="saveEmailSettings"
            />
          </div>

          <!-- Notification Triggers -->
          <div class="space-y-3 bg-wecom-surface/30 rounded-lg p-4">
            <label class="text-sm font-medium text-wecom-text">Notification Triggers</label>

            <!-- Notify on Voice Message -->
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2">
                <span class="text-lg">🎤</span>
                <span class="text-sm text-wecom-muted">When user sends voice</span>
              </div>
              <label class="relative inline-flex items-center cursor-pointer">
                <input
                  v-model="settings.emailNotifyOnVoice"
                  type="checkbox"
                  class="sr-only peer"
                  @change="saveEmailSettings"
                />
                <div
                  class="w-9 h-5 bg-wecom-surface peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-wecom-primary"
                ></div>
              </label>
            </div>

            <!-- Notify on Human Agent Request -->
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2">
                <span class="text-lg">🙋</span>
                <span class="text-sm text-wecom-muted">When user requests human</span>
              </div>
              <label class="relative inline-flex items-center cursor-pointer">
                <input
                  v-model="settings.emailNotifyOnHumanRequest"
                  type="checkbox"
                  class="sr-only peer"
                  @change="saveEmailSettings"
                />
                <div
                  class="w-9 h-5 bg-wecom-surface peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-wecom-primary"
                ></div>
              </label>
            </div>
          </div>

          <!-- Test Email Button -->
          <div class="flex items-center justify-between bg-wecom-surface/50 rounded-lg px-4 py-3">
            <div class="flex items-center gap-2 flex-1">
              <span class="text-sm text-wecom-text">Test Email Sending</span>
              <span
                v-if="emailTestResult"
                :class="emailTestResult.success ? 'text-green-400' : 'text-red-400'"
                class="text-xs truncate max-w-[300px]"
              >
                {{ emailTestResult.message }}
              </span>
            </div>
            <button
              class="btn-secondary text-sm"
              :disabled="
                emailTestLoading ||
                !settings.emailSenderEmail ||
                !settings.emailSenderPassword ||
                !settings.emailReceiverEmail
              "
              @click="testEmailConnection"
            >
              <span v-if="emailTestLoading" class="animate-spin">⏳</span>
              <span v-else>📤</span>
              Send Test
            </button>
          </div>

          <!-- Info box -->
          <div class="bg-wecom-surface/50 rounded-lg px-4 py-3">
            <div class="flex items-start gap-2">
              <span class="text-wecom-primary mt-0.5">ℹ️</span>
              <div class="text-xs text-wecom-muted space-y-1">
                <p><strong>How to get QQ Mail authorization code:</strong></p>
                <p>1. Login to QQ Mail → Settings → Account</p>
                <p>2. Find "POP3/SMTP service" → Enable</p>
                <p>3. Send SMS verification to generate authorization code</p>
              </div>
            </div>
          </div>
        </template>
      </div>
    </section>

    <!-- Sidecar Settings -->
    <section class="space-y-4">
      <h3
        class="text-lg font-display font-semibold text-wecom-text border-b border-wecom-border pb-2"
      >
        Sidecar Settings
      </h3>

      <div class="grid gap-4">
        <!-- Send via Sidecar -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">Send Messages via Sidecar</label>
            <p class="text-xs text-wecom-muted">
              Route sync messages through Sidecar for review before sending
            </p>
          </div>
          <label class="relative inline-flex items-center cursor-pointer">
            <input
              v-model="settings.sendViaSidecar"
              type="checkbox"
              class="sr-only peer"
              @change="saveSettings"
            />
            <div
              class="w-11 h-6 bg-wecom-surface peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-wecom-primary"
            ></div>
          </label>
        </div>

        <!-- Countdown Duration -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">Countdown Duration</label>
            <p class="text-xs text-wecom-muted">
              Delay before sending Sidecar messages (0–30 seconds, 0 sends immediately)
            </p>
          </div>
          <div class="flex items-center gap-3">
            <input
              v-model.number="settings.countdownSeconds"
              type="range"
              min="0"
              max="30"
              class="w-40"
              @input="saveSettings"
            />
            <input
              v-model.number="settings.countdownSeconds"
              type="number"
              min="0"
              max="30"
              class="input-field w-20 text-center"
              @change="saveSettings"
            />
            <span class="text-sm text-wecom-muted">seconds</span>
          </div>
        </div>

        <!-- Poll Interval -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">State Poll Interval</label>
            <p class="text-xs text-wecom-muted">
              How often Sidecar refreshes device state (0 = disabled, 1–20 seconds)
            </p>
          </div>
          <div class="flex items-center gap-3">
            <input
              v-model.number="settings.sidecarPollInterval"
              type="range"
              min="0"
              max="20"
              class="w-40"
              @input="saveSettings"
            />
            <input
              v-model.number="settings.sidecarPollInterval"
              type="number"
              min="0"
              max="20"
              class="input-field w-20 text-center"
              @change="saveSettings"
            />
            <span class="text-sm text-wecom-muted">seconds</span>
          </div>
        </div>

      </div>
    </section>

    <!-- Log Upload Settings -->
    <section class="space-y-4">
      <h3
        class="text-lg font-display font-semibold text-wecom-text border-b border-wecom-border pb-2"
      >
        {{ t('settings.log_upload_title') }}
      </h3>

      <div class="grid gap-4">
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">{{
              t('settings.log_upload_schedule_enable')
            }}</label>
            <p class="text-xs text-wecom-muted">
              {{ t('settings.log_upload_schedule_enable_desc') }}
            </p>
          </div>
          <label class="relative inline-flex items-center cursor-pointer">
            <input
              v-model="settings.logUploadEnabled"
              type="checkbox"
              class="sr-only peer"
              @change="saveSettings"
            />
            <div
              class="w-11 h-6 bg-wecom-surface peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-wecom-primary"
            ></div>
          </label>
        </div>

        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">{{
              t('settings.log_upload_daily_time')
            }}</label>
            <p class="text-xs text-wecom-muted">{{ t('settings.log_upload_daily_time_desc') }}</p>
          </div>
          <input
            v-model="settings.logUploadTime"
            type="time"
            class="input-field w-40"
            @change="saveSettings"
          />
        </div>

        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">{{
              t('settings.log_upload_platform_url')
            }}</label>
            <p class="text-xs text-wecom-muted">{{ t('settings.log_upload_platform_url_desc') }}</p>
          </div>
          <input
            v-model="settings.logUploadUrl"
            type="text"
            class="input-field w-80 text-sm"
            placeholder="http://localhost:8085"
            @change="saveSettings"
          />
        </div>

        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">{{
              t('settings.log_upload_token')
            }}</label>
            <p class="text-xs text-wecom-muted">{{ t('settings.log_upload_token_desc') }}</p>
          </div>
          <div class="flex items-center gap-2">
            <input
              v-model="settings.logUploadToken"
              :type="showLogUploadToken ? 'text' : 'password'"
              class="input-field w-80 text-sm font-mono"
              placeholder="upload-token"
              @change="saveSettings"
            />
            <button
              type="button"
              class="btn-secondary text-xs px-2"
              @click="showLogUploadToken = !showLogUploadToken"
            >
              {{
                showLogUploadToken
                  ? t('settings.log_upload_hide_token')
                  : t('settings.log_upload_show_token')
              }}
            </button>
          </div>
        </div>

        <div class="bg-wecom-surface/50 rounded-lg px-4 py-3 space-y-2">
          <div class="flex items-center justify-between">
            <span class="text-sm text-wecom-text">{{ t('settings.log_upload_scheduler') }}</span>
            <span class="text-xs text-wecom-muted">
              {{
                logUploadStatus?.running
                  ? t('settings.log_upload_running')
                  : t('settings.log_upload_stopped')
              }}
            </span>
          </div>
          <div class="text-xs text-wecom-muted space-y-1">
            <p>
              {{
                t('settings.log_upload_hostname', {
                  value: logUploadStatus?.hostname || settings.hostname || 'default',
                })
              }}
            </p>
            <p>
              {{
                t('settings.log_upload_device_id', {
                  value: logUploadStatus?.device_id || settings.deviceId || '-',
                })
              }}
            </p>
            <p>
              {{
                t('settings.log_upload_person_name', {
                  value:
                    logUploadStatus?.person_name ||
                    settings.personName ||
                    settings.hostname ||
                    'default',
                })
              }}
            </p>
            <p>
              {{
                t('settings.log_upload_next_run', { value: logUploadStatus?.next_run_at || '-' })
              }}
            </p>
            <p v-if="logUploadStatus?.config_error" class="text-red-400">
              {{
                t('settings.log_upload_config_error', {
                  message: logUploadStatus.config_error || '',
                })
              }}
            </p>
            <p v-if="logUploadStatus?.last_run">
              {{
                t('settings.log_upload_last_summary', {
                  status: logUploadStatus.last_run.status || '-',
                  uploaded: String(logUploadStatus.last_run.files_uploaded || 0),
                  skipped: String(logUploadStatus.last_run.files_skipped || 0),
                })
              }}
            </p>
            <p v-if="logUploadStatus?.last_run?.error_message" class="text-red-400">
              {{
                t('settings.log_upload_last_error', {
                  message: logUploadStatus.last_run.error_message || '',
                })
              }}
            </p>
          </div>
        </div>

        <div class="flex items-center justify-between bg-wecom-surface/50 rounded-lg px-4 py-3">
          <div class="flex items-center gap-2 flex-1">
            <span class="text-sm text-wecom-text">{{ t('settings.log_upload_trigger_now') }}</span>
            <span
              v-if="logUploadResult"
              :class="logUploadResult.success ? 'text-green-400' : 'text-red-400'"
              class="text-xs truncate max-w-[320px]"
            >
              {{ logUploadResult.message }}
            </span>
          </div>
          <button
            class="btn-secondary text-sm"
            :disabled="logUploadLoading || !settings.logUploadUrl || !settings.logUploadToken"
            @click="triggerLogUploadNow"
          >
            <span v-if="logUploadLoading" class="animate-spin">⏳</span>
            <span v-else>{{ t('settings.log_upload_button_upload') }}</span>
          </button>
        </div>
      </div>
    </section>

    <!-- Dashboard Monitoring Settings -->
    <section class="space-y-4">
      <h3
        class="text-lg font-display font-semibold text-wecom-text border-b border-wecom-border pb-2"
      >
        📊 Dashboard Monitoring
      </h3>
      <p class="text-xs text-wecom-muted">
        Connect to Device Dashboard for real-time monitoring. Report device status and heartbeat.
      </p>

      <div class="grid gap-4">
        <!-- Enable Dashboard -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">Enable Dashboard Reporting</label>
            <p class="text-xs text-wecom-muted">Periodically send heartbeat data to the monitoring dashboard</p>
          </div>
          <label class="relative inline-flex items-center cursor-pointer">
            <input
              v-model="settings.dashboardEnabled"
              type="checkbox"
              class="sr-only peer"
              @change="saveSettings"
            />
            <div
              class="w-11 h-6 bg-wecom-surface peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-wecom-primary"
            ></div>
          </label>
        </div>

        <!-- Dashboard URL -->
        <div class="flex items-center justify-between">
          <div>
            <label class="text-sm font-medium text-wecom-text">Dashboard URL</label>
            <p class="text-xs text-wecom-muted">WebSocket address of the Device Dashboard</p>
          </div>
          <input
            v-model="settings.dashboardUrl"
            type="text"
            placeholder="ws://localhost:8090/ws/heartbeat"
            class="input-field w-72 text-sm"
            @change="saveSettings"
          />
        </div>

        <!-- Test Connection -->
        <div class="flex items-center justify-between bg-wecom-surface/50 rounded-lg px-4 py-3">
          <div class="flex items-center gap-2">
            <span class="text-sm text-wecom-text">Test Connection</span>
            <span
              v-if="dashboardTestResult"
              :class="dashboardTestResult.success ? 'text-green-400' : 'text-red-400'"
              class="text-xs"
            >
              {{ dashboardTestResult.message }}
            </span>
          </div>
          <button
            class="btn-secondary text-sm"
            :disabled="dashboardTestLoading || !settings.dashboardUrl"
            @click="testDashboardConnection"
          >
            <span v-if="dashboardTestLoading" class="animate-spin">⏳</span>
            <span v-else>🔗 Test</span>
          </button>
        </div>
      </div>
    </section>

    <!-- Actions -->
    <div class="flex items-center gap-4 pt-4 border-t border-wecom-border">
      <button class="btn-secondary" @click="resetSettings">
        {{ t('settings.reset_defaults') }}
      </button>
      <span class="text-xs text-wecom-muted">{{ t('settings.auto_saved_note') }}</span>
    </div>
  </div>
</template>
