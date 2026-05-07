import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  bossApi,
  type BossMonitoringSummaryResponse,
  type BossRecruiterSummary,
} from '../services/bossApi'

/**
 * BOSS dashboard store.
 *
 * Owns the latest read-only monitoring snapshot returned by
 * ``GET /api/boss/monitoring/summary``. The dashboard view polls
 * ``refresh()`` on a timer; consumers should not mutate the cached
 * summary directly — always go through ``refresh()`` so error handling
 * stays in one place.
 */
export const useBossMonitoringStore = defineStore('bossMonitoring', () => {
  const summary = ref<BossMonitoringSummaryResponse | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const recruiters = computed<BossRecruiterSummary[]>(() => summary.value?.recruiters ?? [])

  const totalSilentEligible = computed<number>(() =>
    recruiters.value.reduce((sum, r) => sum + (r.silent_candidates_eligible ?? 0), 0),
  )

  const totalReengagementSent24h = computed<number>(() =>
    recruiters.value.reduce(
      (sum, r) => sum + (r.reengagement_attempts_last_24h?.sent ?? 0),
      0,
    ),
  )

  const totalGreetSent24h = computed<number>(() =>
    recruiters.value.reduce((sum, r) => sum + (r.greet_attempts_last_24h?.sent ?? 0), 0),
  )

  async function refresh(): Promise<BossMonitoringSummaryResponse | null> {
    loading.value = true
    error.value = null
    try {
      const response = await bossApi.getMonitoringSummary()
      summary.value = response
      return response
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load monitoring summary'
      return null
    } finally {
      loading.value = false
    }
  }

  function recruiterFor(deviceSerial: string): BossRecruiterSummary | null {
    return recruiters.value.find((r) => r.device_serial === deviceSerial) ?? null
  }

  return {
    summary,
    loading,
    error,
    recruiters,
    totalSilentEligible,
    totalReengagementSent24h,
    totalGreetSent24h,
    refresh,
    recruiterFor,
  }
})
