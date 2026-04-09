import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  api,
  type CustomerDeletedInfo,
  type CustomerDetailResponse,
  type CustomerMessage,
  type CustomerSummary,
  type FilterAgent,
  type FilterDevice,
} from '../services/api'
import type { GlobalWebSocketEvent } from './globalWebSocket'
import { useGlobalWebSocketStore } from './globalWebSocket'

export interface CustomerFilters {
  search?: string
  streamer?: string
  kefuId?: number
  deviceSerial?: string
  dateFrom?: string
  dateTo?: string
  sortBy?: string
  sortOrder?: 'asc' | 'desc'
}

export const useCustomerStore = defineStore('customers', () => {
  // List state
  const customers = ref<CustomerSummary[]>([])
  const total = ref(0)
  const limit = ref(20)
  const offset = ref(0)
  const search = ref('')
  const listLoading = ref(false)
  const listError = ref<string | null>(null)
  const lastFetchedPath = ref<string | null>(null)

  // Filter state
  const filters = ref<CustomerFilters>({})
  const filterOptions = ref<{
    streamers: string[]
    agents: FilterAgent[]
    devices: FilterDevice[]
  }>({
    streamers: [],
    agents: [],
    devices: [],
  })
  const filterOptionsLoading = ref(false)

  // Detail state
  const selectedCustomer = ref<CustomerDetailResponse['customer'] | null>(null)
  const messages = ref<CustomerMessage[]>([])
  const messageBreakdown = ref<Record<string, number>>({})
  const detailLoading = ref(false)
  const detailError = ref<string | null>(null)

  // Delete state
  const deleteLoading = ref(false)
  const deleteError = ref<string | null>(null)
  const lastDeletedCustomer = ref<CustomerDeletedInfo | null>(null)

  // Global WebSocket state
  const wsConnected = ref(false)
  const wsListenerAttached = ref(false)
  let wsUnlisten: (() => void) | null = null

  const page = computed(() => Math.floor(offset.value / limit.value) + 1)
  const totalPages = computed(() =>
    total.value === 0 ? 1 : Math.ceil(total.value / limit.value),
  )

  async function fetchFilterOptions() {
    filterOptionsLoading.value = true
    try {
      const result = await api.getCustomerFilterOptions()
      filterOptions.value = {
        streamers: result.streamers,
        agents: result.agents,
        devices: result.devices,
      }
    } catch (e) {
      console.error('Failed to load filter options:', e)
    } finally {
      filterOptionsLoading.value = false
    }
  }

  async function fetchCustomers(options: {
    search?: string
    limit?: number
    offset?: number
    filters?: CustomerFilters
  } = {}) {
    if (options.search !== undefined) search.value = options.search
    if (options.limit !== undefined) limit.value = options.limit
    if (options.offset !== undefined) offset.value = options.offset
    if (options.filters !== undefined) filters.value = options.filters

    listLoading.value = true
    listError.value = null

    try {
      const result = await api.getCustomers({
        search: search.value || undefined,
        limit: limit.value,
        offset: offset.value,
        streamer: filters.value.streamer || undefined,
        kefuId: filters.value.kefuId,
        deviceSerial: filters.value.deviceSerial || undefined,
        dateFrom: filters.value.dateFrom || undefined,
        dateTo: filters.value.dateTo || undefined,
        sortBy: filters.value.sortBy || undefined,
        sortOrder: filters.value.sortOrder || undefined,
      })
      customers.value = result.items
      total.value = result.total
      limit.value = result.limit
      offset.value = result.offset
      lastFetchedPath.value = result.db_path
    } catch (e) {
      listError.value = e instanceof Error ? e.message : 'Failed to load customers'
    } finally {
      listLoading.value = false
    }
  }

  async function fetchCustomerDetail(
    customerId: number,
    options: { messagesLimit?: number; messagesOffset?: number } = {},
  ) {
    detailLoading.value = true
    detailError.value = null
    selectedCustomer.value = null
    messages.value = []
    messageBreakdown.value = {}

    try {
      const result = await api.getCustomer(customerId, {
        messagesLimit: options.messagesLimit,
        messagesOffset: options.messagesOffset,
      })
      selectedCustomer.value = result.customer
      messages.value = result.messages
      messageBreakdown.value = result.message_breakdown
      lastFetchedPath.value = result.db_path
      return result
    } catch (e) {
      detailError.value =
        e instanceof Error ? e.message : 'Failed to load customer details'
      throw e
    } finally {
      detailLoading.value = false
    }
  }

  function setPage(newPage: number) {
    const clamped = Math.max(1, newPage)
    offset.value = (clamped - 1) * limit.value
    return fetchCustomers()
  }

  async function deleteCustomer(customerId: number): Promise<CustomerDeletedInfo> {
    deleteLoading.value = true
    deleteError.value = null
    lastDeletedCustomer.value = null

    try {
      const result = await api.deleteCustomer(customerId)
      lastDeletedCustomer.value = result.deleted

      // Remove the deleted customer from the local list
      customers.value = customers.value.filter(c => c.id !== customerId)
      total.value = Math.max(0, total.value - 1)

      return result.deleted
    } catch (e) {
      deleteError.value = e instanceof Error ? e.message : 'Failed to delete conversation'
      throw e
    } finally {
      deleteLoading.value = false
    }
  }

  // ==================== Global WebSocket 集成 ====================

  /**
   * 设置全局 WebSocket 监听
   *
   * 当打开 History 界面时调用，建立 WebSocket 连接并监听 history_refresh 事件
   */
  function setupGlobalWebSocket() {
    // 防止重复添加监听器
    if (wsListenerAttached.value) {
      console.log('[Customers] WebSocket listener already attached, skipping')
      return
    }

    console.log('[Customers] setupGlobalWebSocket called')
    const globalWs = useGlobalWebSocketStore()

    console.log('[Customers] Setting up global WebSocket')
    console.log('[Customers] GlobalWS connected:', globalWs.connected)
    console.log('[Customers] GlobalWS connecting:', globalWs.connecting)

    // 连接 WebSocket（如果还未连接且未在连接中）
    if (!globalWs.connected && !globalWs.connecting) {
      console.log('[Customers] Connecting to global WebSocket...')
      globalWs.connect()
    } else if (!globalWs.connected && globalWs.connecting) {
      console.log('[Customers] WebSocket is connecting, waiting for connection...')
    } else {
      console.log('[Customers] WebSocket already connected')
    }

    // 监听连接状态变化
    wsConnected.value = globalWs.connected

    // 监听 history_refresh 事件
    const handleHistoryRefresh = async (event: GlobalWebSocketEvent) => {
      console.log('[Customers] Received WebSocket event:', event.type, event.data)

      const { customer_name, channel } = event.data || {}

      // 检查是否是当前查看的客户
      if (selectedCustomer.value &&
          selectedCustomer.value.name === customer_name &&
          selectedCustomer.value.channel === channel) {

        console.log('[Customers] ✓ Match! Reloading messages for', customer_name)

        try {
          // 重新加载消息
          await fetchCustomerDetail(selectedCustomer.value.id)
          console.log('[Customers] ✓ Messages reloaded successfully')
        } catch (e) {
          console.error('[Customers] ✗ Failed to refresh messages:', e)
        }
      } else {
        console.log('[Customers] ✗ No match (current:', selectedCustomer.value?.name, 'vs event:', customer_name, ')')
      }
    }

    // 添加监听器
    globalWs.addListener('history_refresh', handleHistoryRefresh)
    wsListenerAttached.value = true

    // 保存清理函数
    wsUnlisten = () => {
      console.log('[Customers] Removing WebSocket listener')
      globalWs.removeListener('history_refresh', handleHistoryRefresh)
    }

    console.log('[Customers] ✓ Global WebSocket listener attached')
  }

  /**
   * 清理全局 WebSocket 监听
   *
   * 当离开 History 界面时调用，移除监听器
   */
  function cleanupGlobalWebSocket() {
    if (wsUnlisten) {
      console.log('[Customers] Cleaning up global WebSocket listener')
      wsUnlisten()
      wsUnlisten = null
      wsListenerAttached.value = false
    }
  }

  /**
   * 手动触发刷新（用于测试或强制刷新）
   */
  async function forceRefreshMessages() {
    if (selectedCustomer.value) {
      console.log('[Customers] Force refreshing messages...')
      await fetchCustomerDetail(selectedCustomer.value.id)
    }
  }

  return {
    customers,
    total,
    limit,
    offset,
    search,
    listLoading,
    listError,
    lastFetchedPath,
    filters,
    filterOptions,
    filterOptionsLoading,
    selectedCustomer,
    messages,
    messageBreakdown,
    detailLoading,
    detailError,
    deleteLoading,
    deleteError,
    lastDeletedCustomer,
    page,
    totalPages,
    fetchFilterOptions,
    fetchCustomers,
    fetchCustomerDetail,
    setPage,
    deleteCustomer,
    // Global WebSocket
    wsConnected,
    wsListenerAttached,
    setupGlobalWebSocket,
    cleanupGlobalWebSocket,
    forceRefreshMessages,
  }
})

