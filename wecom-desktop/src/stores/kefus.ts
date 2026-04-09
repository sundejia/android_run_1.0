import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  api,
  type CustomerSummary,
  type KefuDeletedInfo,
  type KefuDetailResponse,
  type KefuSummary,
} from '../services/api'

export const useKefuStore = defineStore('kefus', () => {
  // List state
  const kefus = ref<KefuSummary[]>([])
  const total = ref(0)
  const limit = ref(20)
  const offset = ref(0)
  const search = ref('')
  const listLoading = ref(false)
  const listError = ref<string | null>(null)
  const lastFetchedPath = ref<string | null>(null)

  // Detail state
  const selectedKefu = ref<KefuDetailResponse['kefu'] | null>(null)
  const customers = ref<CustomerSummary[]>([])
  const customersTotal = ref(0)
  const messageBreakdown = ref<Record<string, number>>({})
  const detailLoading = ref(false)
  const detailError = ref<string | null>(null)

  // Delete state
  const deleteLoading = ref(false)
  const deleteError = ref<string | null>(null)
  const lastDeletedKefu = ref<KefuDeletedInfo | null>(null)

  const page = computed(() => Math.floor(offset.value / limit.value) + 1)
  const totalPages = computed(() =>
    total.value === 0 ? 1 : Math.ceil(total.value / limit.value),
  )

  async function fetchKefus(options: {
    search?: string
    limit?: number
    offset?: number
  } = {}) {
    if (options.search !== undefined) search.value = options.search
    if (options.limit !== undefined) limit.value = options.limit
    if (options.offset !== undefined) offset.value = options.offset

    listLoading.value = true
    listError.value = null

    try {
      const result = await api.getKefus({
        search: search.value || undefined,
        limit: limit.value,
        offset: offset.value,
      })
      kefus.value = result.items
      total.value = result.total
      limit.value = result.limit
      offset.value = result.offset
      lastFetchedPath.value = result.db_path
    } catch (e) {
      listError.value = e instanceof Error ? e.message : 'Failed to load kefus'
    } finally {
      listLoading.value = false
    }
  }

  async function fetchKefuDetail(
    kefuId: number,
    options: { customersLimit?: number; customersOffset?: number } = {},
  ) {
    detailLoading.value = true
    detailError.value = null
    selectedKefu.value = null
    customers.value = []
    customersTotal.value = 0
    messageBreakdown.value = {}

    try {
      const result = await api.getKefu(kefuId, {
        customersLimit: options.customersLimit,
        customersOffset: options.customersOffset,
      })
      selectedKefu.value = result.kefu
      customers.value = result.customers
      customersTotal.value = result.customers_total
      messageBreakdown.value = result.message_breakdown
      lastFetchedPath.value = result.db_path
      return result
    } catch (e) {
      detailError.value =
        e instanceof Error ? e.message : 'Failed to load kefu details'
      throw e
    } finally {
      detailLoading.value = false
    }
  }

  function setPage(newPage: number) {
    const clamped = Math.max(1, newPage)
    offset.value = (clamped - 1) * limit.value
    return fetchKefus()
  }

  async function deleteKefu(kefuId: number): Promise<KefuDeletedInfo> {
    deleteLoading.value = true
    deleteError.value = null
    lastDeletedKefu.value = null

    try {
      const result = await api.deleteKefu(kefuId)
      lastDeletedKefu.value = result.deleted
      
      // Remove the deleted kefu from the local list
      kefus.value = kefus.value.filter(k => k.id !== kefuId)
      total.value = Math.max(0, total.value - 1)
      
      return result.deleted
    } catch (e) {
      deleteError.value = e instanceof Error ? e.message : 'Failed to delete kefu'
      throw e
    } finally {
      deleteLoading.value = false
    }
  }

  return {
    kefus,
    total,
    limit,
    offset,
    search,
    listLoading,
    listError,
    lastFetchedPath,
    selectedKefu,
    customers,
    customersTotal,
    messageBreakdown,
    detailLoading,
    detailError,
    deleteLoading,
    deleteError,
    lastDeletedKefu,
    page,
    totalPages,
    fetchKefus,
    fetchKefuDetail,
    setPage,
    deleteKefu,
  }
})


