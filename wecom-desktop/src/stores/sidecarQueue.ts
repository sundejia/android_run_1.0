import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../services/api'
import { useSettingsStore } from './settings'

export interface QueuedMessage {
  id: string
  serial: string
  customerName: string
  channel: string | null
  message: string
  timestamp: number
  status: 'pending' | 'ready' | 'sending' | 'sent' | 'failed' | 'cancelled'
  error?: string
}

export interface SyncQueueState {
  paused: boolean
  currentMessageId: string | null
  totalMessages: number
  processedMessages: number
}

export const useSidecarQueueStore = defineStore('sidecarQueue', () => {
  const settingsStore = useSettingsStore()
  // State
  const queue = ref<Map<string, QueuedMessage[]>>(new Map()) // serial -> messages
  const syncStates = ref<Map<string, SyncQueueState>>(new Map()) // serial -> state
  const pollTimers = ref<Map<string, number>>(new Map())

  // Getters
  const getQueue = computed(() => (serial: string) => queue.value.get(serial) || [])
  
  const getCurrentMessage = computed(() => (serial: string) => {
    const messages = queue.value.get(serial) || []
    const state = syncStates.value.get(serial)
    if (!state?.currentMessageId) return null
    return messages.find(m => m.id === state.currentMessageId) || null
  })

  const getPendingCount = computed(() => (serial: string) => {
    const messages = queue.value.get(serial) || []
    return messages.filter(m => m.status === 'pending' || m.status === 'ready').length
  })

  const getSyncState = computed(() => (serial: string) => syncStates.value.get(serial) || null)

  const isPaused = computed(() => (serial: string) => {
    const state = syncStates.value.get(serial)
    return state?.paused ?? false
  })

  // Actions
  function initSync(serial: string, totalMessages: number) {
    if (!syncStates.value.has(serial)) {
      syncStates.value.set(serial, {
        paused: false,
        currentMessageId: null,
        totalMessages,
        processedMessages: 0,
      })
      syncStates.value = new Map(syncStates.value)
    }
    if (!queue.value.has(serial)) {
      queue.value.set(serial, [])
      queue.value = new Map(queue.value)
    }
  }

  function addMessage(serial: string, message: Omit<QueuedMessage, 'id' | 'timestamp' | 'status'>) {
    initSync(serial, 0)
    
    const msg: QueuedMessage = {
      ...message,
      id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      timestamp: Date.now(),
      status: 'pending',
    }

    const messages = queue.value.get(serial) || []
    messages.push(msg)
    queue.value.set(serial, messages)
    queue.value = new Map(queue.value)

    // Update total count
    const state = syncStates.value.get(serial)
    if (state) {
      state.totalMessages = messages.length
      syncStates.value = new Map(syncStates.value)
    }

    return msg.id
  }

  function setMessageReady(serial: string, messageId: string) {
    const messages = queue.value.get(serial)
    if (!messages) return

    const msg = messages.find(m => m.id === messageId)
    if (msg) {
      msg.status = 'ready'
      queue.value = new Map(queue.value)
    }

    const state = syncStates.value.get(serial)
    if (state) {
      state.currentMessageId = messageId
      syncStates.value = new Map(syncStates.value)
    }
  }

  function markMessageSent(serial: string, messageId: string) {
    const messages = queue.value.get(serial)
    if (!messages) return

    const msg = messages.find(m => m.id === messageId)
    if (msg) {
      msg.status = 'sent'
      queue.value = new Map(queue.value)
    }

    const state = syncStates.value.get(serial)
    if (state) {
      state.processedMessages++
      state.currentMessageId = null
      syncStates.value = new Map(syncStates.value)
    }
  }

  function markMessageFailed(serial: string, messageId: string, error: string) {
    const messages = queue.value.get(serial)
    if (!messages) return

    const msg = messages.find(m => m.id === messageId)
    if (msg) {
      msg.status = 'failed'
      msg.error = error
      queue.value = new Map(queue.value)
    }

    const state = syncStates.value.get(serial)
    if (state) {
      state.processedMessages++
      state.currentMessageId = null
      syncStates.value = new Map(syncStates.value)
    }
  }

  function pauseSync(serial: string) {
    const state = syncStates.value.get(serial)
    if (state) {
      state.paused = true
      syncStates.value = new Map(syncStates.value)
    }
  }

  function resumeSync(serial: string) {
    const state = syncStates.value.get(serial)
    if (state) {
      state.paused = false
      syncStates.value = new Map(syncStates.value)
    }
  }

  function cancelSync(serial: string) {
    // Cancel all pending messages
    const messages = queue.value.get(serial)
    if (messages) {
      for (const msg of messages) {
        if (msg.status === 'pending' || msg.status === 'ready') {
          msg.status = 'cancelled'
        }
      }
      queue.value = new Map(queue.value)
    }

    // Clear sync state
    syncStates.value.delete(serial)
    syncStates.value = new Map(syncStates.value)
  }

  function clearQueue(serial: string) {
    queue.value.delete(serial)
    queue.value = new Map(queue.value)
    
    syncStates.value.delete(serial)
    syncStates.value = new Map(syncStates.value)
  }

  function getNextPendingMessage(serial: string): QueuedMessage | null {
    const messages = queue.value.get(serial) || []
    return messages.find(m => m.status === 'pending') || null
  }

  // Polling for backend queue state
  async function fetchQueueState(serial: string) {
    try {
      const state = await api.getSidecarQueueState(serial)
      if (state.queue.length > 0) {
        // Sync with backend state
        queue.value.set(serial, state.queue)
        queue.value = new Map(queue.value)
      }
      if (state.syncState) {
        syncStates.value.set(serial, state.syncState)
        syncStates.value = new Map(syncStates.value)
      }
    } catch (e) {
      console.error(`Failed to fetch queue state for ${serial}:`, e)
    }
  }

  function startPolling(serial: string) {
    stopPolling(serial)
    fetchQueueState(serial)
    const baseIntervalMs = Math.max(
      settingsStore.settings.lowSpecMode ? 3000 : 1000,
      (settingsStore.settings.sidecarPollInterval || 1) * 1000,
    )
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'hidden') return
      fetchQueueState(serial)
    }, baseIntervalMs)
    pollTimers.value.set(serial, timer)
  }

  function stopPolling(serial: string) {
    const timer = pollTimers.value.get(serial)
    if (timer !== undefined) {
      clearInterval(timer)
      pollTimers.value.delete(serial)
    }
  }

  return {
    // State
    queue,
    syncStates,

    // Getters
    getQueue,
    getCurrentMessage,
    getPendingCount,
    getSyncState,
    isPaused,

    // Actions
    initSync,
    addMessage,
    setMessageReady,
    markMessageSent,
    markMessageFailed,
    pauseSync,
    resumeSync,
    cancelSync,
    clearQueue,
    getNextPendingMessage,
    fetchQueueState,
    startPolling,
    stopPolling,
  }
})

