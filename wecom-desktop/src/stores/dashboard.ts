import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type DashboardOverview } from '../services/api'

export const useDashboardStore = defineStore('dashboard', () => {
  const overview = ref<DashboardOverview | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const lastFetched = ref<string | null>(null)

  async function fetchOverview(dbPath?: string) {
    loading.value = true
    error.value = null
    try {
      overview.value = await api.getDashboardOverview(dbPath)
      lastFetched.value = new Date().toISOString()
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load dashboard'
    } finally {
      loading.value = false
    }
  }

  return {
    overview,
    loading,
    error,
    lastFetched,
    fetchOverview,
  }
})

