import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  api,
  type KefuActionProfileSummary,
  type KefuActionProfile,
  type EffectiveSettings,
} from '../services/api'

export const useKefuProfilesStore = defineStore('kefuProfiles', () => {
  const profiles = ref<KefuActionProfileSummary[]>([])
  const selectedKefuId = ref<number | null>(null)
  const selectedKefuActions = ref<KefuActionProfile[]>([])
  const effectiveSettings = ref<EffectiveSettings | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchProfiles() {
    loading.value = true
    error.value = null
    try {
      profiles.value = await api.getKefuProfiles()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to load kefu profiles'
    } finally {
      loading.value = false
    }
  }

  async function fetchKefuActions(kefuId: number) {
    loading.value = true
    error.value = null
    try {
      selectedKefuActions.value = await api.getKefuActions(kefuId)
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to load kefu actions'
    } finally {
      loading.value = false
    }
  }

  async function saveKefuAction(
    kefuId: number,
    actionType: string,
    data: { enabled: boolean; config: Record<string, unknown> }
  ) {
    error.value = null
    try {
      const result = await api.upsertKefuAction(kefuId, actionType, data)
      // Update local cache
      const idx = selectedKefuActions.value.findIndex(a => a.action_type === actionType)
      if (idx >= 0) {
        selectedKefuActions.value[idx] = result
      } else {
        selectedKefuActions.value.push(result)
      }
      // Refresh summary
      await fetchProfiles()
      return result
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to save kefu action'
      throw e
    }
  }

  async function deleteKefuAction(kefuId: number, actionType: string) {
    error.value = null
    try {
      await api.deleteKefuAction(kefuId, actionType)
      selectedKefuActions.value = selectedKefuActions.value.filter(a => a.action_type !== actionType)
      await fetchProfiles()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to delete kefu action'
      throw e
    }
  }

  async function fetchEffectiveSettings(kefuId: number) {
    error.value = null
    try {
      effectiveSettings.value = await api.getKefuEffectiveSettings(kefuId)
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to load effective settings'
    }
  }

  function selectKefu(kefuId: number | null) {
    selectedKefuId.value = kefuId
    selectedKefuActions.value = []
    effectiveSettings.value = null
    if (kefuId) {
      fetchKefuActions(kefuId)
    }
  }

  return {
    profiles,
    selectedKefuId,
    selectedKefuActions,
    effectiveSettings,
    loading,
    error,
    fetchProfiles,
    fetchKefuActions,
    saveKefuAction,
    deleteKefuAction,
    fetchEffectiveSettings,
    selectKefu,
  }
})
