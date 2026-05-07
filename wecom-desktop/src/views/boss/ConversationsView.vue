<template>
  <div class="boss-scope min-h-screen bg-boss-dark text-boss-text p-6">
    <header class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-semibold">候选人对话</h1>
        <p class="text-boss-text-muted text-sm mt-1">
          按招聘者查看候选人对话历史，并可一键触发「自动回复」走完一次发送流程。
        </p>
      </div>
      <button
        type="button"
        class="boss-button-primary"
        :disabled="recruitersStore.loading"
        @click="reloadRecruiters"
        data-testid="reload-recruiters"
      >
        {{ recruitersStore.loading ? '加载中…' : '刷新招聘者' }}
      </button>
    </header>

    <div
      v-if="bannerError"
      data-testid="error-banner"
      class="boss-card mb-4"
      style="border-color: var(--boss-danger); color: #f4a39e"
    >
      <strong>操作失败：</strong>{{ bannerError }}
    </div>

    <div
      v-if="!recruitersStore.loading && recruitersStore.recruiters.length === 0"
      class="boss-card text-center"
      data-testid="empty-recruiters"
    >
      <h2 class="text-lg font-medium mb-2">暂无招聘者</h2>
      <p class="text-boss-text-muted">
        请先在「招聘者账号」页面绑定 BOSS 直聘账号。
      </p>
    </div>

    <section
      v-for="recruiter in recruitersStore.recruiters"
      :key="recruiter.device_serial"
      class="boss-card mb-5"
      data-testid="recruiter-section"
    >
      <header class="flex items-start justify-between mb-3">
        <div>
          <h2 class="text-lg font-semibold">{{ recruiter.name || recruiter.device_serial }}</h2>
          <p class="text-sm text-boss-text-muted">
            设备 {{ recruiter.device_serial }} ·
            未读 {{ totalUnread(recruiter.id) }} 条
          </p>
        </div>
        <div class="flex gap-2">
          <button
            type="button"
            class="boss-button-ghost"
            :disabled="messagesStore.loadingConversations[recruiter.id]"
            @click="loadConversations(recruiter.id)"
            :data-testid="`refresh-${recruiter.device_serial}`"
          >
            {{ messagesStore.loadingConversations[recruiter.id] ? '加载…' : '刷新对话' }}
          </button>
          <button
            type="button"
            class="boss-button-primary"
            :disabled="messagesStore.dispatching[recruiter.device_serial]"
            @click="dispatch(recruiter.device_serial)"
            :data-testid="`dispatch-${recruiter.device_serial}`"
          >
            {{ messagesStore.dispatching[recruiter.device_serial] ? '回复中…' : '一键回复一条' }}
          </button>
        </div>
      </header>

      <div
        v-if="messagesStore.lastDispatch[recruiter.device_serial]"
        class="boss-card mb-3"
        style="background: var(--boss-surface)"
        :data-testid="`dispatch-result-${recruiter.device_serial}`"
      >
        <h3 class="text-sm text-boss-text-muted mb-1">最近一次回复</h3>
        <p class="text-sm">
          <strong>结果：</strong>{{ outcomeLabel(messagesStore.lastDispatch[recruiter.device_serial].outcome) }}
        </p>
        <p
          v-if="messagesStore.lastDispatch[recruiter.device_serial].text_sent"
          class="text-sm whitespace-pre-wrap mt-1"
        >
          <strong>已发送：</strong>{{ messagesStore.lastDispatch[recruiter.device_serial].text_sent }}
        </p>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <div class="lg:col-span-4">
          <h3 class="text-sm uppercase tracking-wide text-boss-text-muted mb-2">对话列表</h3>
          <p
            v-if="conversationsFor(recruiter.id).length === 0"
            class="text-sm text-boss-text-muted"
            :data-testid="`empty-conversations-${recruiter.device_serial}`"
          >
            没有已记录的对话。先「一键回复」让系统抓取消息。
          </p>
          <ul class="space-y-2">
            <li
              v-for="conv in conversationsFor(recruiter.id)"
              :key="conv.id"
              class="boss-row"
              :class="{ 'boss-row-active': activeConversationId === conv.id }"
              :data-testid="`conversation-${conv.id}`"
              @click="selectConversation(conv.id)"
            >
              <div class="flex items-center justify-between">
                <span>候选人 #{{ conv.candidate_id }}</span>
                <span
                  v-if="conv.unread_count > 0"
                  class="boss-pill-warn"
                  :data-testid="`unread-${conv.id}`"
                >未读 {{ conv.unread_count }}</span>
              </div>
              <p class="text-xs text-boss-text-muted mt-1">
                方向：{{ directionLabel(conv.last_direction) }}
              </p>
            </li>
          </ul>
        </div>

        <div class="lg:col-span-8">
          <h3 class="text-sm uppercase tracking-wide text-boss-text-muted mb-2">消息记录</h3>
          <p
            v-if="!activeConversationId"
            class="text-sm text-boss-text-muted"
          >
            选择左侧任意对话查看完整聊天历史。
          </p>
          <p
            v-else-if="messagesStore.messagesFor(activeConversationId).length === 0"
            class="text-sm text-boss-text-muted"
            data-testid="empty-messages"
          >
            该对话没有已落库的消息。
          </p>
          <ul
            v-else
            class="space-y-2"
            :data-testid="`messages-${activeConversationId}`"
          >
            <li
              v-for="msg in messagesStore.messagesFor(activeConversationId)"
              :key="msg.id"
              class="boss-message"
              :class="msg.direction === 'out' ? 'boss-message-out' : 'boss-message-in'"
            >
              <p class="text-sm whitespace-pre-wrap">{{ msg.text }}</p>
              <p class="text-xs text-boss-text-muted mt-1">
                {{ msg.direction === 'out' ? '我方' : '候选人' }} ·
                {{ formatTime(msg.sent_at_iso) }}
              </p>
            </li>
          </ul>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useBossRecruitersStore } from '../../stores/bossRecruiters'
import { useBossMessagesStore } from '../../stores/bossMessages'
import type { BossDispatchOutcome } from '../../services/bossApi'

const recruitersStore = useBossRecruitersStore()
const messagesStore = useBossMessagesStore()
const activeConversationId = ref<number | null>(null)

const bannerError = computed(
  () => messagesStore.error || recruitersStore.error,
)

function conversationsFor(recruiterId: number) {
  return messagesStore.conversationsFor(recruiterId)
}

function totalUnread(recruiterId: number): number {
  return messagesStore.conversationsFor(recruiterId).reduce(
    (sum, conv) => sum + conv.unread_count,
    0,
  )
}

async function reloadRecruiters(): Promise<void> {
  await recruitersStore.fetchAll()
  await Promise.all(
    recruitersStore.recruiters.map((r) => messagesStore.loadConversations(r.id)),
  )
}

async function loadConversations(recruiterId: number): Promise<void> {
  await messagesStore.loadConversations(recruiterId)
}

async function dispatch(deviceSerial: string): Promise<void> {
  const result = await messagesStore.dispatchReply(deviceSerial)
  if (result) {
    const recruiter = recruitersStore.recruiters.find((r) => r.device_serial === deviceSerial)
    if (recruiter) await messagesStore.loadConversations(recruiter.id)
  }
}

async function selectConversation(conversationId: number): Promise<void> {
  activeConversationId.value = conversationId
  await messagesStore.loadMessages(conversationId)
}

function directionLabel(direction: string | null): string {
  if (direction === 'in') return '候选人最新'
  if (direction === 'out') return '我方最新'
  return '未知'
}

function outcomeLabel(outcome: BossDispatchOutcome): string {
  const map: Record<BossDispatchOutcome, string> = {
    sent_template: '已发送（模板）',
    sent_ai: '已发送（AI 生成）',
    skipped_no_unread: '跳过：无未读',
    skipped_blacklisted: '跳过：候选人在黑名单',
    halted_unknown_ui: '中止：UI 未识别',
  }
  return map[outcome] ?? outcome
}

function formatTime(iso: string): string {
  try {
    const date = new Date(iso)
    return date.toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

watch(
  () => recruitersStore.recruiters.length,
  async () => {
    if (recruitersStore.recruiters.length === 0) return
    await Promise.all(
      recruitersStore.recruiters.map((r) => messagesStore.loadConversations(r.id)),
    )
  },
)

onMounted(async () => {
  if (recruitersStore.recruiters.length === 0) {
    await recruitersStore.fetchAll()
  }
  await Promise.all(
    recruitersStore.recruiters.map((r) => messagesStore.loadConversations(r.id)),
  )
})
</script>

<style scoped>
.boss-row {
  cursor: pointer;
  border: 1px solid var(--boss-border);
  background: var(--boss-surface);
  border-radius: 0.5rem;
  padding: 0.6rem 0.75rem;
  transition: background 0.15s ease;
}
.boss-row:hover {
  background: rgba(255, 255, 255, 0.04);
}
.boss-row-active {
  border-color: var(--boss-primary);
  background: rgba(31, 78, 140, 0.18);
}
.boss-pill-warn {
  background: var(--boss-accent);
  color: #1a1a1a;
  font-size: 0.7rem;
  padding: 0.1rem 0.45rem;
  border-radius: 999px;
}
.boss-message {
  border-radius: 0.5rem;
  padding: 0.6rem 0.85rem;
  max-width: 80%;
  border: 1px solid var(--boss-border);
  background: var(--boss-surface);
}
.boss-message-in {
  margin-right: auto;
}
.boss-message-out {
  margin-left: auto;
  border-color: var(--boss-primary);
  background: rgba(31, 78, 140, 0.18);
}
</style>
