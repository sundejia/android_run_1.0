<template>
  <div class="boss-scope min-h-screen bg-boss-dark text-boss-text p-6">
    <header class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-semibold">招聘者账号</h1>
        <p class="text-boss-text-muted text-sm mt-1">
          每台设备绑定一个 BOSS 直聘招聘者账号；点击「刷新」可重新读取设备上的当前账号信息。
        </p>
      </div>
      <button
        type="button"
        class="boss-button-primary"
        :disabled="store.loading"
        @click="reload"
        data-testid="reload-all-button"
      >
        {{ store.loading ? '加载中…' : '重新加载列表' }}
      </button>
    </header>

    <div
      v-if="store.error"
      data-testid="error-banner"
      class="boss-card mb-4"
      style="border-color: var(--boss-danger); color: #f4a39e"
    >
      <strong>加载失败：</strong>
      {{ store.error }}
    </div>

    <div
      v-if="!store.loading && store.recruiters.length === 0"
      data-testid="empty-state"
      class="boss-card text-center"
    >
      <h2 class="text-lg font-medium mb-2">还没有任何招聘者</h2>
      <p class="text-boss-text-muted">
        把 BOSS 直聘 App 安装并登录到一台 ADB 设备上，然后点击右上角「重新加载列表」。
      </p>
    </div>

    <ul
      v-else
      data-testid="recruiter-grid"
      class="boss-data-grid"
    >
      <li
        v-for="recruiter in store.recruiters"
        :key="recruiter.device_serial"
        class="boss-card"
        data-testid="recruiter-card"
      >
        <div class="flex items-start justify-between mb-3">
          <div>
            <h3 class="text-lg font-semibold" data-testid="recruiter-name">
              {{ recruiter.name || '（未读取到姓名）' }}
            </h3>
            <p class="text-sm text-boss-text-muted" data-testid="recruiter-serial">
              {{ recruiter.device_serial }}
            </p>
          </div>
          <span
            class="boss-status-pill"
            :data-status="recruiter.name ? 'open' : 'warning'"
            data-testid="recruiter-status"
          >
            {{ recruiter.name ? '已识别' : '待识别' }}
          </span>
        </div>

        <dl class="text-sm space-y-1">
          <div class="flex justify-between">
            <dt class="text-boss-text-muted">公司</dt>
            <dd data-testid="recruiter-company">{{ recruiter.company || '—' }}</dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-boss-text-muted">职位</dt>
            <dd data-testid="recruiter-position">{{ recruiter.position || '—' }}</dd>
          </div>
        </dl>

        <div class="boss-divider"></div>

        <button
          type="button"
          class="boss-button-primary w-full"
          :disabled="store.refreshing[recruiter.device_serial]"
          @click="refreshOne(recruiter.device_serial)"
          :data-testid="`refresh-${recruiter.device_serial}`"
        >
          {{ store.refreshing[recruiter.device_serial] ? '刷新中…' : '刷新此设备' }}
        </button>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useBossRecruitersStore } from '../../stores/bossRecruiters'

const store = useBossRecruitersStore()

async function reload(): Promise<void> {
  await store.fetchAll()
}

async function refreshOne(deviceSerial: string): Promise<void> {
  // M1 only supports operator-supplied snapshots. The on-device
  // re-scan happens via a sync subprocess in M2; this button currently
  // sends a no-op refresh that the backend rejects, surfacing the
  // exact UX gap to the operator.
  await store.refreshOne(deviceSerial, {})
}

onMounted(() => {
  void reload()
})
</script>
