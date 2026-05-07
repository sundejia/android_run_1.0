import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  bossApi,
  type BossJob,
  type BossJobStatus,
  type BossJobSyncResponse,
} from '../services/bossApi'

export const useBossJobsStore = defineStore('bossJobs', () => {
  const jobsByRecruiter = ref<Record<number, BossJob[]>>({})
  const loading = ref<Record<number, boolean>>({})
  const syncing = ref<Record<string, boolean>>({})
  const error = ref<string | null>(null)
  const lastSyncResults = ref<Record<string, BossJobSyncResponse>>({})

  function _setLoading(recruiterId: number, value: boolean): void {
    if (value) {
      loading.value = { ...loading.value, [recruiterId]: true }
    } else {
      const next = { ...loading.value }
      delete next[recruiterId]
      loading.value = next
    }
  }

  function _setSyncing(deviceSerial: string, value: boolean): void {
    if (value) {
      syncing.value = { ...syncing.value, [deviceSerial]: true }
    } else {
      const next = { ...syncing.value }
      delete next[deviceSerial]
      syncing.value = next
    }
  }

  async function fetchJobs(
    recruiterId: number,
    statusFilter?: BossJobStatus,
  ): Promise<void> {
    _setLoading(recruiterId, true)
    error.value = null
    try {
      const response = await bossApi.listJobs(recruiterId, statusFilter)
      jobsByRecruiter.value = {
        ...jobsByRecruiter.value,
        [recruiterId]: response.jobs,
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load jobs'
    } finally {
      _setLoading(recruiterId, false)
    }
  }

  async function syncJobs(
    deviceSerial: string,
    options: { recruiterId?: number; tabs?: BossJobStatus[] } = {},
  ): Promise<BossJobSyncResponse | null> {
    _setSyncing(deviceSerial, true)
    error.value = null
    try {
      const response = await bossApi.syncJobs({
        device_serial: deviceSerial,
        tabs: options.tabs,
      })
      lastSyncResults.value = {
        ...lastSyncResults.value,
        [deviceSerial]: response,
      }
      const recruiterId = options.recruiterId ?? response.recruiter_id
      await fetchJobs(recruiterId)
      return response
    } catch (e) {
      error.value = e instanceof Error ? e.message : `Failed to sync ${deviceSerial}`
      return null
    } finally {
      _setSyncing(deviceSerial, false)
    }
  }

  function jobsFor(recruiterId: number): BossJob[] {
    return jobsByRecruiter.value[recruiterId] ?? []
  }

  function isLoading(recruiterId: number): boolean {
    return Boolean(loading.value[recruiterId])
  }

  function isSyncing(deviceSerial: string): boolean {
    return Boolean(syncing.value[deviceSerial])
  }

  const totalJobsLoaded = computed(() =>
    Object.values(jobsByRecruiter.value).reduce((acc, list) => acc + list.length, 0),
  )

  return {
    jobsByRecruiter,
    loading,
    syncing,
    error,
    lastSyncResults,
    fetchJobs,
    syncJobs,
    jobsFor,
    isLoading,
    isSyncing,
    totalJobsLoaded,
  }
})
