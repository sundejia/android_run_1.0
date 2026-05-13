import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  api,
  type DeviceActionProfileSummary,
  type DeviceActionProfile,
  type DeviceEffectiveSettings,
} from '../services/api'

export const useDeviceProfilesStore = defineStore('deviceProfiles', () => {
  const profiles = ref<DeviceActionProfileSummary[]>([])
  const selectedDeviceSerial = ref<string | null>(null)
  const selectedDeviceActions = ref<DeviceActionProfile[]>([])
  const effectiveSettings = ref<DeviceEffectiveSettings | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchProfiles() {
    loading.value = true
    error.value = null
    try {
      profiles.value = await api.getDeviceProfiles()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to load device profiles'
    } finally {
      loading.value = false
    }
  }

  async function fetchDeviceActions(deviceSerial: string) {
    loading.value = true
    error.value = null
    try {
      selectedDeviceActions.value = await api.getDeviceActions(deviceSerial)
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to load device actions'
    } finally {
      loading.value = false
    }
  }

  async function saveDeviceAction(
    deviceSerial: string,
    actionType: string,
    data: { enabled: boolean; config: Record<string, unknown> }
  ) {
    error.value = null
    try {
      const result = await api.upsertDeviceAction(deviceSerial, actionType, data)
      const idx = selectedDeviceActions.value.findIndex(a => a.action_type === actionType)
      if (idx >= 0) {
        selectedDeviceActions.value[idx] = result
      } else {
        selectedDeviceActions.value.push(result)
      }
      await fetchProfiles()
      return result
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to save device action'
      throw e
    }
  }

  async function deleteDeviceAction(deviceSerial: string, actionType: string) {
    error.value = null
    try {
      await api.deleteDeviceAction(deviceSerial, actionType)
      selectedDeviceActions.value = selectedDeviceActions.value.filter(a => a.action_type !== actionType)
      await fetchProfiles()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to delete device action'
      throw e
    }
  }

  async function fetchEffectiveSettings(deviceSerial: string) {
    error.value = null
    try {
      effectiveSettings.value = await api.getDeviceEffectiveSettings(deviceSerial)
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to load effective settings'
    }
  }

  function selectDevice(deviceSerial: string | null) {
    selectedDeviceSerial.value = deviceSerial
    selectedDeviceActions.value = []
    effectiveSettings.value = null
    if (deviceSerial) {
      fetchDeviceActions(deviceSerial)
    }
  }

  return {
    profiles,
    selectedDeviceSerial,
    selectedDeviceActions,
    effectiveSettings,
    loading,
    error,
    fetchProfiles,
    fetchDeviceActions,
    saveDeviceAction,
    deleteDeviceAction,
    fetchEffectiveSettings,
    selectDevice,
  }
})
