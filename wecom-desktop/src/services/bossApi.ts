/**
 * REST client for the BOSS Zhipin pivot endpoints.
 *
 * This module is intentionally separate from the legacy api.ts so the
 * BOSS feature can ship without bloating the existing surface.
 */

import { API_BASE } from './api'

export interface BossRecruiter {
  id: number
  device_serial: string
  name: string | null
  company: string | null
  position: string | null
  avatar_path: string | null
}

export interface BossRecruiterListResponse {
  recruiters: BossRecruiter[]
  total: number
}

export interface BossRecruiterRefreshPayload {
  name?: string
  company?: string
  position?: string
  avatar_path?: string
}

export type BossJobStatus = 'open' | 'closed' | 'hidden' | 'draft'

export interface BossJob {
  id: number
  recruiter_id: number
  boss_job_id: string
  title: string
  status: BossJobStatus
  salary_min: number | null
  salary_max: number | null
  location: string | null
  education: string | null
  experience: string | null
}

export interface BossJobListResponse {
  jobs: BossJob[]
  total: number
}

export interface BossJobSyncRequest {
  device_serial: string
  tabs?: BossJobStatus[]
}

export interface BossJobSyncTabResult {
  tab: BossJobStatus
  count: number
}

export interface BossJobSyncResponse {
  recruiter_id: number
  total_jobs: number
  per_tab: BossJobSyncTabResult[]
  errors: string[]
}

export interface BossGreetWindow {
  weekdays: number[]
  start_minute: number
  end_minute: number
  timezone: string
}

export interface BossGreetQuota {
  per_day: number
  per_hour: number
  per_job: number | null
}

export interface BossGreetSettings {
  device_serial: string
  enabled: boolean
  window: BossGreetWindow
  quota: BossGreetQuota
}

export interface BossGreetSettingsUpdate {
  enabled?: boolean
  window?: BossGreetWindow
  quota?: BossGreetQuota
}

export type BossGreetOutcome =
  | 'sent'
  | 'skipped_already_greeted'
  | 'skipped_blacklisted'
  | 'skipped_quota_day'
  | 'skipped_quota_hour'
  | 'skipped_quota_job'
  | 'skipped_outside_window'
  | 'skipped_no_candidates'
  | 'halted_risk_control'
  | 'halted_unknown_ui'

export interface BossGreetTestRunResponse {
  outcome: BossGreetOutcome
  boss_candidate_id: string | null
  candidate_name: string | null
  detail: string | null
}

export type BossTemplateScenario = 'first_greet' | 'reply' | 'reengage'

export interface BossTemplate {
  id: number
  name: string
  scenario: BossTemplateScenario
  content: string
  is_default: boolean
  variables_json: string | null
}

export interface BossTemplatesListResponse {
  templates: BossTemplate[]
}

export interface BossTemplateCreateRequest {
  name: string
  scenario: BossTemplateScenario
  content: string
  is_default?: boolean
  variables_json?: string | null
}

export interface BossTemplateUpdateRequest {
  content?: string
  is_default?: boolean
  variables_json?: string | null
}

export interface BossTemplatePreviewRequest {
  content: string
  context: Record<string, string | null>
  max_length?: number
}

export interface BossTemplatePreviewResponse {
  text: string
  warnings: string[]
}

export interface BossConversation {
  id: number
  recruiter_id: number
  candidate_id: number
  unread_count: number
  last_direction: string | null
}

export interface BossConversationsListResponse {
  recruiter_id: number
  conversations: BossConversation[]
}

export interface BossMessage {
  id: number
  direction: 'in' | 'out'
  content_type: string
  text: string | null
  sent_at_iso: string
  sent_by: string | null
  template_id: number | null
}

export interface BossMessagesListResponse {
  conversation_id: number
  messages: BossMessage[]
}

export type BossDispatchOutcome =
  | 'sent_template'
  | 'sent_ai'
  | 'skipped_no_unread'
  | 'skipped_blacklisted'
  | 'halted_unknown_ui'

export interface BossDispatchResponse {
  outcome: BossDispatchOutcome
  boss_candidate_id: string | null
  candidate_name: string | null
  text_sent: string | null
  template_warnings: string[]
}

export interface BossReengagementSettings {
  device_serial: string
  silent_for_days: number
  cooldown_days: number
  daily_cap: number
  template_id: number | null
  enabled: boolean
}

export interface BossReengagementSettingsUpdate {
  silent_for_days?: number
  cooldown_days?: number
  daily_cap?: number
  template_id?: number | null
  enabled?: boolean
}

export interface BossEligibleCandidate {
  candidate_id: number
  boss_candidate_id: string
  conversation_id: number
  last_outbound_at_iso: string
  silent_for_seconds: number
}

export interface BossReengagementScanResponse {
  recruiter_id: number
  eligible: BossEligibleCandidate[]
}

export type BossReengagementOutcome =
  | 'sent'
  | 'dry_run'
  | 'skipped_candidate_replied'
  | 'skipped_blacklisted'
  | 'skipped_daily_cap'
  | 'no_eligible'
  | 'failed'

export interface BossReengagementRunResponse {
  outcome: BossReengagementOutcome
  boss_candidate_id: string | null
  candidate_id: number | null
  attempt_id: number | null
  detail: string | null
}

const BOSS_BASE = `${API_BASE}/api/boss`

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}: ${text || '(empty body)'}`)
  }
  return (await res.json()) as T
}

export const bossApi = {
  async listRecruiters(): Promise<BossRecruiterListResponse> {
    const res = await fetch(`${BOSS_BASE}/recruiters`)
    return jsonOrThrow<BossRecruiterListResponse>(res)
  },

  async getRecruiter(deviceSerial: string): Promise<BossRecruiter> {
    const res = await fetch(`${BOSS_BASE}/recruiters/${encodeURIComponent(deviceSerial)}`)
    return jsonOrThrow<BossRecruiter>(res)
  },

  async refreshRecruiter(
    deviceSerial: string,
    payload: BossRecruiterRefreshPayload,
  ): Promise<BossRecruiter> {
    const res = await fetch(
      `${BOSS_BASE}/recruiters/${encodeURIComponent(deviceSerial)}/refresh`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      },
    )
    return jsonOrThrow<BossRecruiter>(res)
  },

  async listJobs(recruiterId: number, statusFilter?: BossJobStatus): Promise<BossJobListResponse> {
    const params = new URLSearchParams({ recruiter_id: String(recruiterId) })
    if (statusFilter) params.set('status_filter', statusFilter)
    const res = await fetch(`${BOSS_BASE}/jobs?${params.toString()}`)
    return jsonOrThrow<BossJobListResponse>(res)
  },

  async getJob(jobId: number): Promise<BossJob> {
    const res = await fetch(`${BOSS_BASE}/jobs/${jobId}`)
    return jsonOrThrow<BossJob>(res)
  },

  async syncJobs(payload: BossJobSyncRequest): Promise<BossJobSyncResponse> {
    const res = await fetch(`${BOSS_BASE}/jobs/sync`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    return jsonOrThrow<BossJobSyncResponse>(res)
  },

  async getGreetSettings(deviceSerial: string): Promise<BossGreetSettings> {
    const res = await fetch(
      `${BOSS_BASE}/greet/settings/${encodeURIComponent(deviceSerial)}`,
    )
    return jsonOrThrow<BossGreetSettings>(res)
  },

  async updateGreetSettings(
    deviceSerial: string,
    payload: BossGreetSettingsUpdate,
  ): Promise<BossGreetSettings> {
    const res = await fetch(
      `${BOSS_BASE}/greet/settings/${encodeURIComponent(deviceSerial)}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      },
    )
    return jsonOrThrow<BossGreetSettings>(res)
  },

  async greetTestRun(deviceSerial: string): Promise<BossGreetTestRunResponse> {
    const res = await fetch(`${BOSS_BASE}/greet/test-run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_serial: deviceSerial }),
    })
    return jsonOrThrow<BossGreetTestRunResponse>(res)
  },

  async listTemplates(scenario: BossTemplateScenario): Promise<BossTemplatesListResponse> {
    const params = new URLSearchParams({ scenario })
    const res = await fetch(`${BOSS_BASE}/templates/?${params.toString()}`)
    return jsonOrThrow<BossTemplatesListResponse>(res)
  },

  async createTemplate(payload: BossTemplateCreateRequest): Promise<BossTemplate> {
    const res = await fetch(`${BOSS_BASE}/templates/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    return jsonOrThrow<BossTemplate>(res)
  },

  async updateTemplate(id: number, payload: BossTemplateUpdateRequest): Promise<BossTemplate> {
    const res = await fetch(`${BOSS_BASE}/templates/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    return jsonOrThrow<BossTemplate>(res)
  },

  async deleteTemplate(id: number): Promise<void> {
    const res = await fetch(`${BOSS_BASE}/templates/${id}`, { method: 'DELETE' })
    if (!res.ok && res.status !== 204) {
      const text = await res.text().catch(() => '')
      throw new Error(`${res.status} ${res.statusText}: ${text || '(empty body)'}`)
    }
  },

  async previewTemplate(payload: BossTemplatePreviewRequest): Promise<BossTemplatePreviewResponse> {
    const res = await fetch(`${BOSS_BASE}/templates/preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    return jsonOrThrow<BossTemplatePreviewResponse>(res)
  },

  async listConversations(recruiterId: number): Promise<BossConversationsListResponse> {
    const res = await fetch(
      `${BOSS_BASE}/messages/recruiters/${recruiterId}/conversations`,
    )
    return jsonOrThrow<BossConversationsListResponse>(res)
  },

  async listMessages(conversationId: number): Promise<BossMessagesListResponse> {
    const res = await fetch(`${BOSS_BASE}/messages/conversations/${conversationId}`)
    return jsonOrThrow<BossMessagesListResponse>(res)
  },

  async dispatchReply(deviceSerial: string): Promise<BossDispatchResponse> {
    const res = await fetch(`${BOSS_BASE}/messages/dispatch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_serial: deviceSerial }),
    })
    return jsonOrThrow<BossDispatchResponse>(res)
  },

  async getReengagementSettings(deviceSerial: string): Promise<BossReengagementSettings> {
    const res = await fetch(
      `${BOSS_BASE}/reengagement/settings/${encodeURIComponent(deviceSerial)}`,
    )
    return jsonOrThrow<BossReengagementSettings>(res)
  },

  async updateReengagementSettings(
    deviceSerial: string,
    payload: BossReengagementSettingsUpdate,
  ): Promise<BossReengagementSettings> {
    const res = await fetch(
      `${BOSS_BASE}/reengagement/settings/${encodeURIComponent(deviceSerial)}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      },
    )
    return jsonOrThrow<BossReengagementSettings>(res)
  },

  async scanReengagement(deviceSerial: string): Promise<BossReengagementScanResponse> {
    const res = await fetch(`${BOSS_BASE}/reengagement/scan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_serial: deviceSerial }),
    })
    return jsonOrThrow<BossReengagementScanResponse>(res)
  },

  async runReengagement(deviceSerial: string): Promise<BossReengagementRunResponse> {
    const res = await fetch(`${BOSS_BASE}/reengagement/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_serial: deviceSerial }),
    })
    return jsonOrThrow<BossReengagementRunResponse>(res)
  },
}
