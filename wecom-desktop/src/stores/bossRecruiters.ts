import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  bossApi,
  type BossRecruiter,
  type BossRecruiterRefreshPayload,
} from '../services/bossApi'

export const useBossRecruitersStore = defineStore('bossRecruiters', () => {
  const recruiters = ref<BossRecruiter[]>([])
  const loading = ref(false)
  const refreshing = ref<Record<string, boolean>>({})
  const error = ref<string | null>(null)
  const lastFetchedAt = ref<string | null>(null)

  async function fetchAll(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const response = await bossApi.listRecruiters()
      recruiters.value = response.recruiters
      lastFetchedAt.value = new Date().toISOString()
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load recruiters'
    } finally {
      loading.value = false
    }
  }

  async function refreshOne(
    deviceSerial: string,
    payload: BossRecruiterRefreshPayload,
  ): Promise<BossRecruiter | null> {
    refreshing.value = { ...refreshing.value, [deviceSerial]: true }
    error.value = null
    try {
      const updated = await bossApi.refreshRecruiter(deviceSerial, payload)
      const idx = recruiters.value.findIndex((r) => r.device_serial === deviceSerial)
      if (idx >= 0) {
        recruiters.value.splice(idx, 1, updated)
      } else {
        recruiters.value = [...recruiters.value, updated]
      }
      return updated
    } catch (e) {
      error.value = e instanceof Error ? e.message : `Failed to refresh ${deviceSerial}`
      return null
    } finally {
      const next = { ...refreshing.value }
      delete next[deviceSerial]
      refreshing.value = next
    }
  }

  function getBySerial(deviceSerial: string): BossRecruiter | undefined {
    return recruiters.value.find((r) => r.device_serial === deviceSerial)
  }

  return {
    recruiters,
    loading,
    refreshing,
    error,
    lastFetchedAt,
    fetchAll,
    refreshOne,
    getBySerial,
  }
})
