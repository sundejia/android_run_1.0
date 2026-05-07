import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  bossApi,
  type BossConversation,
  type BossDispatchResponse,
  type BossMessage,
} from '../services/bossApi'

export const useBossMessagesStore = defineStore('bossMessages', () => {
  const conversationsByRecruiter = ref<Record<number, BossConversation[]>>({})
  const messagesByConversation = ref<Record<number, BossMessage[]>>({})
  const lastDispatch = ref<Record<string, BossDispatchResponse>>({})
  const loadingConversations = ref<Record<number, boolean>>({})
  const loadingMessages = ref<Record<number, boolean>>({})
  const dispatching = ref<Record<string, boolean>>({})
  const error = ref<string | null>(null)

  function _setBoolMap<K extends string | number>(
    map: { value: Record<K, boolean> },
    key: K,
    value: boolean,
  ): void {
    if (value) {
      map.value = { ...map.value, [key]: true }
    } else {
      const next = { ...map.value }
      delete next[key]
      map.value = next
    }
  }

  async function loadConversations(recruiterId: number): Promise<BossConversation[]> {
    _setBoolMap(loadingConversations, recruiterId, true)
    error.value = null
    try {
      const response = await bossApi.listConversations(recruiterId)
      conversationsByRecruiter.value = {
        ...conversationsByRecruiter.value,
        [recruiterId]: response.conversations,
      }
      return response.conversations
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load conversations'
      return []
    } finally {
      _setBoolMap(loadingConversations, recruiterId, false)
    }
  }

  async function loadMessages(conversationId: number): Promise<BossMessage[]> {
    _setBoolMap(loadingMessages, conversationId, true)
    error.value = null
    try {
      const response = await bossApi.listMessages(conversationId)
      messagesByConversation.value = {
        ...messagesByConversation.value,
        [conversationId]: response.messages,
      }
      return response.messages
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load messages'
      return []
    } finally {
      _setBoolMap(loadingMessages, conversationId, false)
    }
  }

  async function dispatchReply(deviceSerial: string): Promise<BossDispatchResponse | null> {
    _setBoolMap(dispatching, deviceSerial, true)
    error.value = null
    try {
      const response = await bossApi.dispatchReply(deviceSerial)
      lastDispatch.value = { ...lastDispatch.value, [deviceSerial]: response }
      return response
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to dispatch reply'
      return null
    } finally {
      _setBoolMap(dispatching, deviceSerial, false)
    }
  }

  function conversationsFor(recruiterId: number): BossConversation[] {
    return conversationsByRecruiter.value[recruiterId] ?? []
  }

  function messagesFor(conversationId: number): BossMessage[] {
    return messagesByConversation.value[conversationId] ?? []
  }

  const totalUnread = computed<number>(() => {
    let sum = 0
    for (const list of Object.values(conversationsByRecruiter.value)) {
      for (const conv of list) sum += conv.unread_count
    }
    return sum
  })

  return {
    conversationsByRecruiter,
    messagesByConversation,
    lastDispatch,
    loadingConversations,
    loadingMessages,
    dispatching,
    error,
    totalUnread,
    loadConversations,
    loadMessages,
    dispatchReply,
    conversationsFor,
    messagesFor,
  }
})
