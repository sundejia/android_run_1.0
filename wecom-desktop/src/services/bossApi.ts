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
}
