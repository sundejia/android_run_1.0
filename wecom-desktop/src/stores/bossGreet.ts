import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  bossApi,
  type BossGreetSettings,
  type BossGreetSettingsUpdate,
  type BossGreetTestRunResponse,
} from '../services/bossApi'

export const useBossGreetStore = defineStore('bossGreet', () => {
  const settingsBySerial = ref<Record<string, BossGreetSettings>>({})
  const loading = ref<Record<string, boolean>>({})
  const saving = ref<Record<string, boolean>>({})
  const testing = ref<Record<string, boolean>>({})
  const lastTestRun = ref<Record<string, BossGreetTestRunResponse>>({})
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

  async function fetchSettings(deviceSerial: string): Promise<BossGreetSettings | null> {
    _setBoolMap(loading, deviceSerial, true)
    error.value = null
    try {
      const settings = await bossApi.getGreetSettings(deviceSerial)
      settingsBySerial.value = { ...settingsBySerial.value, [deviceSerial]: settings }
      return settings
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load greet settings'
      return null
    } finally {
      _setBoolMap(loading, deviceSerial, false)
    }
  }

  async function saveSettings(
    deviceSerial: string,
    payload: BossGreetSettingsUpdate,
  ): Promise<BossGreetSettings | null> {
    _setBoolMap(saving, deviceSerial, true)
    error.value = null
    try {
      const settings = await bossApi.updateGreetSettings(deviceSerial, payload)
      settingsBySerial.value = { ...settingsBySerial.value, [deviceSerial]: settings }
      return settings
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to save greet settings'
      return null
    } finally {
      _setBoolMap(saving, deviceSerial, false)
    }
  }

  async function runTest(deviceSerial: string): Promise<BossGreetTestRunResponse | null> {
    _setBoolMap(testing, deviceSerial, true)
    error.value = null
    try {
      const result = await bossApi.greetTestRun(deviceSerial)
      lastTestRun.value = { ...lastTestRun.value, [deviceSerial]: result }
      return result
    } catch (e) {
      error.value = e instanceof Error ? e.message : `Failed to test-run on ${deviceSerial}`
      return null
    } finally {
      _setBoolMap(testing, deviceSerial, false)
    }
  }

  function settingsFor(deviceSerial: string): BossGreetSettings | null {
    return settingsBySerial.value[deviceSerial] ?? null
  }

  function isLoading(deviceSerial: string): boolean {
    return Boolean(loading.value[deviceSerial])
  }

  function isSaving(deviceSerial: string): boolean {
    return Boolean(saving.value[deviceSerial])
  }

  function isTesting(deviceSerial: string): boolean {
    return Boolean(testing.value[deviceSerial])
  }

  return {
    settingsBySerial,
    loading,
    saving,
    testing,
    lastTestRun,
    error,
    fetchSettings,
    saveSettings,
    runTest,
    settingsFor,
    isLoading,
    isSaving,
    isTesting,
  }
})
