<template>
  <div class="boss-scope min-h-screen bg-boss-dark text-boss-text p-6">
    <header class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-semibold">复聊跟进</h1>
        <p class="text-boss-text-muted text-sm mt-1">
          为每位招聘者配置「沉默多久后跟进」「再次跟进的冷却时间」「每天最多跟进多少人」。
          系统会在执行前再次校验黑名单与候选人是否已回复，避免误发。
        </p>
      </div>
      <button
        type="button"
        class="boss-button-primary"
        :disabled="recruitersStore.loading"
        @click="reloadAll"
        data-testid="reload-recruiters"
      >
        {{ recruitersStore.loading ? '加载中…' : '刷新招聘者' }}
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
      data-testid="empty-recruiters"
      class="boss-card text-center"
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
          <p class="text-sm text-boss-text-muted">设备 {{ recruiter.device_serial }}</p>
        </div>
      </header>

      <div
        v-if="formState[recruiter.device_serial]"
        class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-3"
      >
        <label class="text-sm">
          <span class="block text-boss-text-muted mb-1">沉默天数</span>
          <input
            type="number"
            min="0"
            v-model.number="formState[recruiter.device_serial].silent_for_days"
            class="boss-input"
            :data-testid="`silent-${recruiter.device_serial}`"
          />
        </label>
        <label class="text-sm">
          <span class="block text-boss-text-muted mb-1">冷却天数</span>
          <input
            type="number"
            min="0"
            v-model.number="formState[recruiter.device_serial].cooldown_days"
            class="boss-input"
            :data-testid="`cooldown-${recruiter.device_serial}`"
          />
        </label>
        <label class="text-sm">
          <span class="block text-boss-text-muted mb-1">每日上限</span>
          <input
            type="number"
            min="1"
            v-model.number="formState[recruiter.device_serial].daily_cap"
            class="boss-input"
            :data-testid="`daily-cap-${recruiter.device_serial}`"
          />
        </label>
      </div>

      <div class="flex flex-wrap gap-2 mb-3">
        <button
          type="button"
          class="boss-button-ghost"
          :disabled="store.saving[recruiter.device_serial]"
          :data-testid="`save-${recruiter.device_serial}`"
          @click="save(recruiter.device_serial)"
        >
          {{ store.saving[recruiter.device_serial] ? '保存中…' : '保存设置' }}
        </button>
        <button
          type="button"
          class="boss-button-primary"
          :disabled="store.scanning[recruiter.device_serial]"
          :data-testid="`scan-${recruiter.device_serial}`"
          @click="scan(recruiter.device_serial)"
        >
          {{ store.scanning[recruiter.device_serial] ? '扫描中…' : '扫描沉默候选人' }}
        </button>
        <button
          type="button"
          class="boss-button-primary"
          :disabled="store.running[recruiter.device_serial]"
          :data-testid="`run-${recruiter.device_serial}`"
          @click="run(recruiter.device_serial)"
        >
          {{ store.running[recruiter.device_serial] ? '执行中…' : '执行一次跟进' }}
        </button>
      </div>

      <div
        v-if="store.lastRunBySerial[recruiter.device_serial]"
        class="boss-card mb-3"
        style="background: var(--boss-surface)"
        :data-testid="`last-run-${recruiter.device_serial}`"
      >
        <h3 class="text-sm text-boss-text-muted mb-1">最近一次跟进结果</h3>
        <p class="text-sm">
          <strong>结果：</strong>{{ outcomeLabel(store.lastRunBySerial[recruiter.device_serial].outcome) }}
        </p>
        <p
          v-if="store.lastRunBySerial[recruiter.device_serial].boss_candidate_id"
          class="text-sm mt-1"
        >
          <strong>候选人 ID：</strong>{{ store.lastRunBySerial[recruiter.device_serial].boss_candidate_id }}
        </p>
        <p
          v-if="store.lastRunBySerial[recruiter.device_serial].detail"
          class="text-xs text-boss-text-muted mt-1"
        >
          {{ store.lastRunBySerial[recruiter.device_serial].detail }}
        </p>
      </div>

      <div data-testid="eligible-section">
        <h3 class="text-sm uppercase tracking-wide text-boss-text-muted mb-2">
          沉默候选人（{{ store.eligibleFor(recruiter.device_serial).length }}）
        </h3>
        <p
          v-if="store.eligibleFor(recruiter.device_serial).length === 0"
          class="text-sm text-boss-text-muted"
          :data-testid="`empty-eligible-${recruiter.device_serial}`"
        >
          没有需要跟进的候选人。点击上方「扫描沉默候选人」更新列表。
        </p>
        <ul v-else class="space-y-2">
          <li
            v-for="candidate in store.eligibleFor(recruiter.device_serial)"
            :key="candidate.candidate_id"
            class="boss-row"
            :data-testid="`eligible-${candidate.candidate_id}`"
          >
            <div class="flex items-center justify-between">
              <span>候选人 {{ candidate.boss_candidate_id }}</span>
              <span class="text-sm text-boss-text-muted">
                沉默 {{ formatSeconds(candidate.silent_for_seconds) }}
              </span>
            </div>
          </li>
        </ul>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, watch } from 'vue'
import { useBossRecruitersStore } from '../../stores/bossRecruiters'
import { useBossReengagementStore } from '../../stores/bossReengagement'
import type { BossReengagementOutcome } from '../../services/bossApi'

const recruitersStore = useBossRecruitersStore()
const store = useBossReengagementStore()

interface FormShape {
  silent_for_days: number
  cooldown_days: number
  daily_cap: number
}

const formState = reactive<Record<string, FormShape>>({})

const bannerError = computed(() => store.error || recruitersStore.error)

async function reloadAll(): Promise<void> {
  await recruitersStore.fetchAll()
  await Promise.all(
    recruitersStore.recruiters.map(async (recruiter) => {
      const settings = await store.fetchSettings(recruiter.device_serial)
      if (settings) {
        formState[recruiter.device_serial] = {
          silent_for_days: settings.silent_for_days,
          cooldown_days: settings.cooldown_days,
          daily_cap: settings.daily_cap,
        }
      }
    }),
  )
}

async function save(deviceSerial: string): Promise<void> {
  const form = formState[deviceSerial]
  if (!form) return
  const updated = await store.saveSettings(deviceSerial, {
    silent_for_days: form.silent_for_days,
    cooldown_days: form.cooldown_days,
    daily_cap: form.daily_cap,
  })
  if (updated) {
    formState[deviceSerial] = {
      silent_for_days: updated.silent_for_days,
      cooldown_days: updated.cooldown_days,
      daily_cap: updated.daily_cap,
    }
  }
}

async function scan(deviceSerial: string): Promise<void> {
  await store.scan(deviceSerial)
}

async function run(deviceSerial: string): Promise<void> {
  await store.runOne(deviceSerial)
  await store.scan(deviceSerial)
}

function formatSeconds(seconds: number): string {
  const days = Math.floor(seconds / 86400)
  if (days > 0) return `${days} 天`
  const hours = Math.floor(seconds / 3600)
  if (hours > 0) return `${hours} 小时`
  const minutes = Math.floor(seconds / 60)
  return `${minutes} 分钟`
}

function outcomeLabel(outcome: BossReengagementOutcome): string {
  const map: Record<BossReengagementOutcome, string> = {
    sent: '已发送',
    dry_run: '空跑（未连接设备）',
    skipped_candidate_replied: '跳过：候选人已回复',
    skipped_blacklisted: '跳过：候选人在黑名单',
    skipped_daily_cap: '跳过：达到每日上限',
    no_eligible: '无候选人需跟进',
    failed: '失败',
  }
  return map[outcome] ?? outcome
}

watch(
  () => recruitersStore.recruiters.length,
  async () => {
    await Promise.all(
      recruitersStore.recruiters.map(async (recruiter) => {
        if (formState[recruiter.device_serial]) return
        const settings = await store.fetchSettings(recruiter.device_serial)
        if (settings) {
          formState[recruiter.device_serial] = {
            silent_for_days: settings.silent_for_days,
            cooldown_days: settings.cooldown_days,
            daily_cap: settings.daily_cap,
          }
        }
      }),
    )
  },
)

onMounted(async () => {
  if (recruitersStore.recruiters.length === 0) {
    await recruitersStore.fetchAll()
  }
  for (const recruiter of recruitersStore.recruiters) {
    const settings = await store.fetchSettings(recruiter.device_serial)
    if (settings) {
      formState[recruiter.device_serial] = {
        silent_for_days: settings.silent_for_days,
        cooldown_days: settings.cooldown_days,
        daily_cap: settings.daily_cap,
      }
    }
  }
})
</script>

<style scoped>
.boss-row {
  border: 1px solid var(--boss-border);
  background: var(--boss-surface);
  border-radius: 0.5rem;
  padding: 0.6rem 0.75rem;
}
</style>
