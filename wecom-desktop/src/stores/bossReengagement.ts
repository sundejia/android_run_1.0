import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  bossApi,
  type BossEligibleCandidate,
  type BossReengagementRunResponse,
  type BossReengagementSettings,
  type BossReengagementSettingsUpdate,
} from '../services/bossApi'

export const useBossReengagementStore = defineStore('bossReengagement', () => {
  const settingsBySerial = ref<Record<string, BossReengagementSettings>>({})
  const eligibleBySerial = ref<Record<string, BossEligibleCandidate[]>>({})
  const lastRunBySerial = ref<Record<string, BossReengagementRunResponse>>({})
  const loading = ref<Record<string, boolean>>({})
  const saving = ref<Record<string, boolean>>({})
  const scanning = ref<Record<string, boolean>>({})
  const running = ref<Record<string, boolean>>({})
  const error = ref<string | null>(null)

  function _setBoolMap(map: typeof loading, key: string, value: boolean): void {
    if (value) {
      map.value = { ...map.value, [key]: true }
    } else {
      const next = { ...map.value }
      delete next[key]
      map.value = next
    }
  }

  async function fetchSettings(deviceSerial: string): Promise<BossReengagementSettings | null> {
    _setBoolMap(loading, deviceSerial, true)
    error.value = null
    try {
      const settings = await bossApi.getReengagementSettings(deviceSerial)
      settingsBySerial.value = { ...settingsBySerial.value, [deviceSerial]: settings }
      return settings
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load reengagement settings'
      return null
    } finally {
      _setBoolMap(loading, deviceSerial, false)
    }
  }

  async function saveSettings(
    deviceSerial: string,
    payload: BossReengagementSettingsUpdate,
  ): Promise<BossReengagementSettings | null> {
    _setBoolMap(saving, deviceSerial, true)
    error.value = null
    try {
      const settings = await bossApi.updateReengagementSettings(deviceSerial, payload)
      settingsBySerial.value = { ...settingsBySerial.value, [deviceSerial]: settings }
      return settings
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to save reengagement settings'
      return null
    } finally {
      _setBoolMap(saving, deviceSerial, false)
    }
  }

  async function scan(deviceSerial: string): Promise<BossEligibleCandidate[]> {
    _setBoolMap(scanning, deviceSerial, true)
    error.value = null
    try {
      const response = await bossApi.scanReengagement(deviceSerial)
      eligibleBySerial.value = {
        ...eligibleBySerial.value,
        [deviceSerial]: response.eligible,
      }
      return response.eligible
    } catch (e) {
      error.value = e instanceof Error ? e.message : `Failed to scan ${deviceSerial}`
      return []
    } finally {
      _setBoolMap(scanning, deviceSerial, false)
    }
  }

  async function runOne(deviceSerial: string): Promise<BossReengagementRunResponse | null> {
    _setBoolMap(running, deviceSerial, true)
    error.value = null
    try {
      const response = await bossApi.runReengagement(deviceSerial)
      lastRunBySerial.value = { ...lastRunBySerial.value, [deviceSerial]: response }
      return response
    } catch (e) {
      error.value = e instanceof Error ? e.message : `Failed to run reengagement for ${deviceSerial}`
      return null
    } finally {
      _setBoolMap(running, deviceSerial, false)
    }
  }

  function settingsFor(deviceSerial: string): BossReengagementSettings | null {
    return settingsBySerial.value[deviceSerial] ?? null
  }

  function eligibleFor(deviceSerial: string): BossEligibleCandidate[] {
    return eligibleBySerial.value[deviceSerial] ?? []
  }

  const totalEligible = computed<number>(() =>
    Object.values(eligibleBySerial.value).reduce((sum, list) => sum + list.length, 0),
  )

  return {
    settingsBySerial,
    eligibleBySerial,
    lastRunBySerial,
    loading,
    saving,
    scanning,
    running,
    error,
    totalEligible,
    fetchSettings,
    saveSettings,
    scan,
    runOne,
    settingsFor,
    eligibleFor,
  }
})
