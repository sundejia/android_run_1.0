<template>
  <div class="boss-scope min-h-screen bg-boss-dark text-boss-text p-6">
    <header class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-semibold">打招呼调度</h1>
        <p class="text-boss-text-muted text-sm mt-1">
          为每台设备配置打招呼时间段、配额上限、和黑名单策略；保存后立即生效。
        </p>
      </div>
      <button
        type="button"
        class="boss-button-primary"
        :disabled="recruitersStore.loading"
        @click="reloadAll"
        data-testid="reload-button"
      >
        {{ recruitersStore.loading ? '加载中…' : '重新加载招聘者' }}
      </button>
    </header>

    <div
      v-if="bannerError"
      class="boss-card mb-4"
      style="border-color: var(--boss-danger); color: #f4a39e"
      data-testid="error-banner"
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
      <header class="flex items-start justify-between mb-4">
        <div>
          <h2 class="text-lg font-semibold">{{ recruiter.name || recruiter.device_serial }}</h2>
          <p class="text-sm text-boss-text-muted">设备 {{ recruiter.device_serial }}</p>
        </div>
        <label
          v-if="formState[recruiter.device_serial]"
          class="flex items-center gap-2 text-sm"
        >
          <input
            type="checkbox"
            v-model="formState[recruiter.device_serial].enabled"
            :data-testid="`enabled-${recruiter.device_serial}`"
          />
          自动打招呼
        </label>
      </header>
      <p
        v-if="!formState[recruiter.device_serial]"
        class="text-sm text-boss-text-muted"
      >
        配置加载中…
      </p>
      <div v-if="formState[recruiter.device_serial]" class="grid grid-cols-2 gap-4 mb-4">
        <div>
          <h3 class="text-sm text-boss-text-muted mb-2">允许日期</h3>
          <div class="flex gap-2 flex-wrap">
            <label
              v-for="(label, idx) in WEEKDAYS"
              :key="label"
              class="text-xs"
            >
              <input
                type="checkbox"
                :value="idx"
                v-model="formState[recruiter.device_serial].window.weekdays"
                :data-testid="`weekday-${recruiter.device_serial}-${idx}`"
              />
              {{ label }}
            </label>
          </div>
        </div>
        <div>
          <h3 class="text-sm text-boss-text-muted mb-2">时间段（24小时制）</h3>
          <div class="flex items-center gap-2 text-sm">
            <input
              type="time"
              v-model="formState[recruiter.device_serial].startTime"
              class="bg-boss-surface text-boss-text border border-boss-border rounded px-2 py-1"
              :data-testid="`start-time-${recruiter.device_serial}`"
            />
            <span>→</span>
            <input
              type="time"
              v-model="formState[recruiter.device_serial].endTime"
              class="bg-boss-surface text-boss-text border border-boss-border rounded px-2 py-1"
              :data-testid="`end-time-${recruiter.device_serial}`"
            />
          </div>
          <p
            v-if="isCrossMidnight(recruiter.device_serial)"
            class="text-xs text-boss-text-muted mt-1"
          >
            ⚠ 跨日窗口（结束时间小于开始时间）
          </p>
        </div>
      </div>

      <div v-if="formState[recruiter.device_serial]" class="grid grid-cols-3 gap-4 mb-4">
        <label class="text-sm">
          <span class="text-boss-text-muted">每日上限</span>
          <input
            type="number"
            min="1"
            max="500"
            v-model.number="formState[recruiter.device_serial].quota.per_day"
            class="w-full bg-boss-surface text-boss-text border border-boss-border rounded px-2 py-1 mt-1"
            :data-testid="`per-day-${recruiter.device_serial}`"
          />
        </label>
        <label class="text-sm">
          <span class="text-boss-text-muted">每小时上限</span>
          <input
            type="number"
            min="1"
            max="200"
            v-model.number="formState[recruiter.device_serial].quota.per_hour"
            class="w-full bg-boss-surface text-boss-text border border-boss-border rounded px-2 py-1 mt-1"
            :data-testid="`per-hour-${recruiter.device_serial}`"
          />
        </label>
        <label class="text-sm">
          <span class="text-boss-text-muted">每职位上限（可选）</span>
          <input
            type="number"
            min="1"
            v-model.number="formState[recruiter.device_serial].quota.per_job"
            class="w-full bg-boss-surface text-boss-text border border-boss-border rounded px-2 py-1 mt-1"
            :data-testid="`per-job-${recruiter.device_serial}`"
          />
        </label>
      </div>

      <div v-if="formState[recruiter.device_serial]" class="flex items-center gap-3">
        <button
          type="button"
          class="boss-button-primary"
          :disabled="greetStore.isSaving(recruiter.device_serial)"
          @click="save(recruiter.device_serial)"
          :data-testid="`save-${recruiter.device_serial}`"
        >
          {{ greetStore.isSaving(recruiter.device_serial) ? '保存中…' : '保存配置' }}
        </button>
        <button
          type="button"
          class="boss-button-primary"
          style="background: var(--boss-accent)"
          :disabled="greetStore.isTesting(recruiter.device_serial)"
          @click="test(recruiter.device_serial)"
          :data-testid="`test-${recruiter.device_serial}`"
        >
          {{ greetStore.isTesting(recruiter.device_serial) ? '执行中…' : '试运行 1 次' }}
        </button>
        <span
          v-if="lastOutcomeFor(recruiter.device_serial)"
          class="text-xs text-boss-text-muted"
          :data-testid="`outcome-${recruiter.device_serial}`"
        >
          上次结果：{{ outcomeLabel(lastOutcomeFor(recruiter.device_serial)!) }}
        </span>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, watch } from 'vue'
import { useBossRecruitersStore } from '../../stores/bossRecruiters'
import { useBossGreetStore } from '../../stores/bossGreet'
import type { BossGreetOutcome, BossGreetSettings } from '../../services/bossApi'

const recruitersStore = useBossRecruitersStore()
const greetStore = useBossGreetStore()

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']

interface FormState {
  enabled: boolean
  window: BossGreetSettings['window']
  quota: BossGreetSettings['quota']
  startTime: string
  endTime: string
}

const formState = reactive<Record<string, FormState>>({})

const bannerError = computed(() => recruitersStore.error || greetStore.error)

function minuteToTime(minute: number): string {
  const h = Math.floor(minute / 60)
    .toString()
    .padStart(2, '0')
  const m = (minute % 60).toString().padStart(2, '0')
  return `${h}:${m}`
}

function timeToMinute(value: string): number {
  const [h, m] = value.split(':').map((s) => Number(s))
  return (Number.isFinite(h) ? h : 0) * 60 + (Number.isFinite(m) ? m : 0)
}

function ensureFormState(serial: string, settings: BossGreetSettings): void {
  formState[serial] = {
    enabled: settings.enabled,
    window: { ...settings.window, weekdays: [...settings.window.weekdays] },
    quota: { ...settings.quota },
    startTime: minuteToTime(settings.window.start_minute),
    endTime: minuteToTime(settings.window.end_minute),
  }
}

function isCrossMidnight(serial: string): boolean {
  const f = formState[serial]
  if (!f) return false
  return timeToMinute(f.endTime) < timeToMinute(f.startTime)
}

function lastOutcomeFor(serial: string): BossGreetOutcome | undefined {
  return greetStore.lastTestRun[serial]?.outcome
}

function outcomeLabel(outcome: BossGreetOutcome): string {
  switch (outcome) {
    case 'sent':
      return '✅ 发送成功'
    case 'skipped_already_greeted':
      return '已沟通，跳过'
    case 'skipped_blacklisted':
      return '已拉黑，跳过'
    case 'skipped_quota_day':
      return '今日配额已满'
    case 'skipped_quota_hour':
      return '本小时配额已满'
    case 'skipped_quota_job':
      return '该职位配额已满'
    case 'skipped_outside_window':
      return '不在允许时间段'
    case 'skipped_no_candidates':
      return '当前无候选人'
    case 'halted_risk_control':
      return '⛔ 触发风控，已停止'
    case 'halted_unknown_ui':
      return '⛔ UI 异常，已停止'
  }
}

async function reloadAll(): Promise<void> {
  await recruitersStore.fetchAll()
  for (const r of recruitersStore.recruiters) {
    const settings = await greetStore.fetchSettings(r.device_serial)
    if (settings) ensureFormState(r.device_serial, settings)
  }
}

async function save(serial: string): Promise<void> {
  const f = formState[serial]
  if (!f) return
  const updated = await greetStore.saveSettings(serial, {
    enabled: f.enabled,
    window: {
      ...f.window,
      start_minute: timeToMinute(f.startTime),
      end_minute: timeToMinute(f.endTime),
    },
    quota: { ...f.quota, per_job: f.quota.per_job || null },
  })
  if (updated) ensureFormState(serial, updated)
}

async function test(serial: string): Promise<void> {
  await greetStore.runTest(serial)
}

watch(
  () => recruitersStore.recruiters.map((r) => r.device_serial).join(','),
  async (newKey) => {
    if (!newKey) return
    for (const r of recruitersStore.recruiters) {
      if (!formState[r.device_serial]) {
        const settings = await greetStore.fetchSettings(r.device_serial)
        if (settings) ensureFormState(r.device_serial, settings)
      }
    }
  },
)

onMounted(() => {
  void reloadAll()
})
</script>
