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
}
