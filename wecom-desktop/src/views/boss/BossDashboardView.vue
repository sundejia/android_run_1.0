<template>
  <div class="boss-scope min-h-screen bg-boss-dark text-boss-text p-6">
    <header class="flex items-start justify-between mb-6">
      <div>
        <h1 class="text-2xl font-semibold">招聘运营总览</h1>
        <p class="text-boss-text-muted text-sm mt-1">
          每位招聘者的开放/关闭岗位、候选人状态与最近 24 小时动作概览。数据来自
          <code>/api/boss/monitoring/summary</code>。
        </p>
      </div>
      <button
        type="button"
        class="boss-button-primary"
        :disabled="store.loading"
        data-testid="refresh"
        @click="refresh"
      >
        {{ store.loading ? '加载中…' : '刷新' }}
      </button>
    </header>

    <div
      v-if="store.error"
      class="boss-card mb-4"
      style="border-color: var(--boss-danger); color: #f4a39e"
      data-testid="error-banner"
    >
      <strong>加载失败：</strong>{{ store.error }}
    </div>

    <section class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
      <div class="boss-card">
        <p class="text-xs text-boss-text-muted">招聘者数量</p>
        <p class="text-2xl font-semibold mt-1">{{ store.recruiters.length }}</p>
      </div>
      <div class="boss-card">
        <p class="text-xs text-boss-text-muted">沉默候选人（待复聊）</p>
        <p class="text-2xl font-semibold mt-1" data-testid="total-silent">
          {{ store.totalSilentEligible }}
        </p>
      </div>
      <div class="boss-card">
        <p class="text-xs text-boss-text-muted">近 24h 复聊已发</p>
        <p class="text-2xl font-semibold mt-1" data-testid="total-reengage-sent">
          {{ store.totalReengagementSent24h }}
        </p>
      </div>
    </section>

    <div
      v-if="!store.loading && store.recruiters.length === 0 && !store.error"
      data-testid="empty-recruiters"
      class="boss-card text-center"
    >
      <h2 class="text-lg font-medium mb-2">暂无招聘者</h2>
      <p class="text-boss-text-muted">请先在「招聘者账号」页面绑定 BOSS 直聘账号。</p>
    </div>

    <section
      v-for="recruiter in store.recruiters"
      :key="recruiter.device_serial"
      class="boss-card mb-4"
      data-testid="recruiter-card"
      :data-testid-card="`recruiter-card-${recruiter.device_serial}`"
    >
      <div :data-testid="`recruiter-card-${recruiter.device_serial}`">
        <header class="flex items-start justify-between mb-3">
          <div>
            <h2 class="text-lg font-semibold">
              {{ recruiter.name || recruiter.device_serial }}
            </h2>
            <p class="text-sm text-boss-text-muted">
              <span v-if="recruiter.company">{{ recruiter.company }} · </span>
              <span v-if="recruiter.position">{{ recruiter.position }} · </span>
              设备 {{ recruiter.device_serial }}
            </p>
          </div>
        </header>

        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
          <div class="boss-stat">
            <p class="text-xs text-boss-text-muted">开放岗位</p>
            <p
              class="text-xl font-semibold"
              :data-testid="`job-open-${recruiter.device_serial}`"
            >
              {{ recruiter.jobs_by_status.open ?? 0 }}
            </p>
          </div>
          <div class="boss-stat">
            <p class="text-xs text-boss-text-muted">已关闭岗位</p>
            <p
              class="text-xl font-semibold"
              :data-testid="`job-closed-${recruiter.device_serial}`"
            >
              {{ recruiter.jobs_by_status.closed ?? 0 }}
            </p>
          </div>
          <div class="boss-stat">
            <p class="text-xs text-boss-text-muted">沉默候选人</p>
            <p
              class="text-xl font-semibold"
              :data-testid="`silent-eligible-${recruiter.device_serial}`"
            >
              {{ recruiter.silent_candidates_eligible }}
            </p>
          </div>
          <div class="boss-stat">
            <p class="text-xs text-boss-text-muted">近 24h 复聊已发</p>
            <p
              class="text-xl font-semibold"
              :data-testid="`reengage-sent-${recruiter.device_serial}`"
            >
              {{ recruiter.reengagement_attempts_last_24h.sent }}
            </p>
          </div>
        </div>

        <div class="flex flex-wrap gap-2 text-xs">
          <span
            v-for="(count, status) in recruiter.candidates_by_status"
            :key="status"
            class="boss-chip"
            >{{ statusLabel(String(status)) }} {{ count }}</span
          >
          <span
            v-if="recruiter.reengagement_attempts_last_24h.failed > 0"
            class="boss-chip"
            style="background: rgba(220, 38, 38, 0.15); color: #fca5a5"
          >
            复聊失败 {{ recruiter.reengagement_attempts_last_24h.failed }}
          </span>
        </div>
      </div>
    </section>

    <p v-if="store.summary" class="text-xs text-boss-text-muted mt-4">
      生成时间：{{ store.summary.generated_at_iso }} · 时间窗口：{{ store.summary.window_hours }}h
    </p>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { useBossMonitoringStore } from '../../stores/bossMonitoring'

const store = useBossMonitoringStore()
const REFRESH_MS = 30_000

let timer: ReturnType<typeof setInterval> | null = null

async function refresh(): Promise<void> {
  await store.refresh()
}

const STATUS_LABELS: Record<string, string> = {
  new: '新候选人',
  greeted: '已打招呼',
  replied: '已回复',
  exchanged: '已交换',
  interviewing: '面试中',
  hired: '已入职',
  rejected: '已拒绝',
  silent: '沉默',
  blocked: '已屏蔽',
}

function statusLabel(value: string): string {
  return STATUS_LABELS[value] ?? value
}

onMounted(() => {
  void refresh()
  timer = setInterval(() => {
    void refresh()
  }, REFRESH_MS)
})

onBeforeUnmount(() => {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
})
</script>

<style scoped>
.boss-stat {
  background: rgba(255, 255, 255, 0.04);
  border-radius: 8px;
  padding: 12px;
}

.boss-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
}
</style>
