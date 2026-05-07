<template>
  <div class="boss-scope min-h-screen bg-boss-dark text-boss-text p-6">
    <header class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-semibold">职位管理</h1>
        <p class="text-boss-text-muted text-sm mt-1">
          按招聘者查看 BOSS 直聘上的开放/关闭职位；点击「立即同步」会从设备上重新拉取一遍。
        </p>
      </div>
      <button
        type="button"
        class="boss-button-primary"
        :disabled="recruitersStore.loading"
        @click="reloadRecruiters"
        data-testid="reload-recruiters-button"
      >
        {{ recruitersStore.loading ? '加载中…' : '刷新招聘者列表' }}
      </button>
    </header>

    <div
      v-if="error"
      data-testid="error-banner"
      class="boss-card mb-4"
      style="border-color: var(--boss-danger); color: #f4a39e"
    >
      <strong>操作失败：</strong>{{ error }}
    </div>

    <div
      v-if="!recruitersStore.loading && recruitersStore.recruiters.length === 0"
      data-testid="empty-recruiters"
      class="boss-card text-center"
    >
      <h2 class="text-lg font-medium mb-2">暂无招聘者</h2>
      <p class="text-boss-text-muted">
        请先在「招聘者账号」页面绑定 BOSS 直聘账号，然后回到本页同步职位。
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
          <h2 class="text-lg font-semibold" data-testid="recruiter-heading">
            {{ recruiter.name || recruiter.device_serial }}
          </h2>
          <p class="text-sm text-boss-text-muted">
            {{ recruiter.company || '—' }} · 设备 {{ recruiter.device_serial }}
          </p>
        </div>
        <div class="flex items-center gap-2">
          <select
            v-model="statusFilters[recruiter.id]"
            class="bg-boss-surface text-boss-text border border-boss-border rounded px-2 py-1 text-sm"
            :data-testid="`status-filter-${recruiter.id}`"
            @change="reloadJobs(recruiter.id)"
          >
            <option value="">全部状态</option>
            <option value="open">开放中</option>
            <option value="closed">已关闭</option>
            <option value="hidden">仅我可见</option>
          </select>
          <button
            type="button"
            class="boss-button-primary"
            :disabled="jobsStore.isSyncing(recruiter.device_serial)"
            @click="runSync(recruiter)"
            :data-testid="`sync-${recruiter.device_serial}`"
          >
            {{ jobsStore.isSyncing(recruiter.device_serial) ? '同步中…' : '立即同步' }}
          </button>
        </div>
      </header>

      <div
        v-if="lastSyncFor(recruiter.device_serial)"
        class="text-xs text-boss-text-muted mb-3"
        :data-testid="`last-sync-${recruiter.device_serial}`"
      >
        上次同步结果：共 {{ lastSyncFor(recruiter.device_serial)?.total_jobs }} 个职位
        <span
          v-for="entry in lastSyncFor(recruiter.device_serial)?.per_tab ?? []"
          :key="entry.tab"
          class="ml-2"
        >
          {{ tabLabel(entry.tab) }} {{ entry.count }}
        </span>
      </div>

      <ul
        v-if="jobsStore.jobsFor(recruiter.id).length"
        class="boss-data-grid"
        :data-testid="`jobs-grid-${recruiter.id}`"
      >
        <li
          v-for="job in jobsStore.jobsFor(recruiter.id)"
          :key="job.id"
          class="boss-card"
          data-testid="job-card"
        >
          <div class="flex items-start justify-between">
            <div>
              <h3 class="text-base font-semibold" data-testid="job-title">
                {{ job.title }}
              </h3>
              <p class="text-xs text-boss-text-muted mt-1">ID {{ job.boss_job_id }}</p>
            </div>
            <span
              class="boss-status-pill"
              :data-status="statusToPill(job.status)"
              data-testid="job-status"
            >
              {{ tabLabel(job.status) }}
            </span>
          </div>
          <dl class="text-sm mt-3 space-y-1">
            <div class="flex justify-between">
              <dt class="text-boss-text-muted">薪资</dt>
              <dd data-testid="job-salary">{{ formatSalary(job) }}</dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-boss-text-muted">城市</dt>
              <dd>{{ job.location || '—' }}</dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-boss-text-muted">学历 / 经验</dt>
              <dd>{{ job.education || '—' }} / {{ job.experience || '—' }}</dd>
            </div>
          </dl>
        </li>
      </ul>
      <div
        v-else-if="!jobsStore.isLoading(recruiter.id)"
        class="text-sm text-boss-text-muted"
        :data-testid="`empty-jobs-${recruiter.id}`"
      >
        暂无职位记录。点击右上角「立即同步」从设备拉取。
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useBossRecruitersStore } from '../../stores/bossRecruiters'
import { useBossJobsStore } from '../../stores/bossJobs'
import type { BossJob, BossJobStatus, BossRecruiter } from '../../services/bossApi'

const recruitersStore = useBossRecruitersStore()
const jobsStore = useBossJobsStore()

const statusFilters = ref<Record<number, '' | BossJobStatus>>({})

const error = computed(() => recruitersStore.error || jobsStore.error)

function tabLabel(status: BossJobStatus): string {
  switch (status) {
    case 'open':
      return '开放中'
    case 'closed':
      return '已关闭'
    case 'hidden':
      return '仅我可见'
    case 'draft':
      return '草稿'
  }
  return status
}

function statusToPill(status: BossJobStatus): string {
  if (status === 'open') return 'open'
  if (status === 'closed') return 'closed'
  return 'warning'
}

function formatSalary(job: BossJob): string {
  if (job.salary_min == null || job.salary_max == null) return '面议'
  const min = Math.round(job.salary_min / 1000)
  const max = Math.round(job.salary_max / 1000)
  return `${min}K-${max}K`
}

function lastSyncFor(serial: string) {
  return jobsStore.lastSyncResults[serial]
}

async function reloadRecruiters(): Promise<void> {
  await recruitersStore.fetchAll()
  for (const r of recruitersStore.recruiters) {
    await jobsStore.fetchJobs(r.id)
  }
}

async function reloadJobs(recruiterId: number): Promise<void> {
  const filter = statusFilters.value[recruiterId]
  await jobsStore.fetchJobs(recruiterId, filter || undefined)
}

async function runSync(recruiter: BossRecruiter): Promise<void> {
  await jobsStore.syncJobs(recruiter.device_serial, { recruiterId: recruiter.id })
}

watch(
  () => recruitersStore.recruiters.map((r) => r.id).join(','),
  async (newKey) => {
    if (!newKey) return
    for (const r of recruitersStore.recruiters) {
      if (jobsStore.jobsFor(r.id).length === 0 && !jobsStore.isLoading(r.id)) {
        await jobsStore.fetchJobs(r.id)
      }
    }
  },
)

onMounted(() => {
  void reloadRecruiters()
})
</script>
