<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useKefuStore } from '../stores/kefus'
import { avatarUrlForCustomer } from '../utils/avatars'
import { useI18n } from '../composables/useI18n'

const { t } = useI18n()

const route = useRoute()
const router = useRouter()
const kefuStore = useKefuStore()

const kefuId = computed(() => Number(route.params.id))
const kefu = computed(() => kefuStore.selectedKefu)
const customers = computed(() => kefuStore.customers)

function formatDate(value: string | null | undefined) {
  if (!value) return '—'
  const parsed = new Date(value)
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toLocaleString()
  }
  return value
}

async function load() {
  const id = kefuId.value
  if (Number.isNaN(id)) {
    router.push({ name: 'kefus' })
    return
  }

  try {
    await kefuStore.fetchKefuDetail(id, { customersLimit: 100 })
  } catch (e) {
    console.error('Failed to load kefu detail', e)
  }
}

function openConversation(id: number) {
  router.push({ name: 'conversation-detail', params: { id } })
}

onMounted(load)
watch(
  () => route.params.id,
  () => {
    load()
  }
)
</script>

<template>
  <div class="p-6 space-y-6 animate-fade-in">
    <div class="flex items-center gap-3 text-sm text-wecom-muted">
      <router-link to="/kefus" class="btn-secondary text-xs">
        {{ t('kefus.back_to_kefus') }}
      </router-link>
      <span>{{ t('kefus.kefu_id') }}: {{ kefuId }}</span>
      <span v-if="kefuStore.lastFetchedPath">DB: {{ kefuStore.lastFetchedPath }}</span>
    </div>

    <div
      v-if="kefuStore.detailError"
      class="bg-red-900/20 border border-red-500/30 rounded-lg p-4 flex items-center gap-3"
    >
      <span class="text-red-400">⚠️</span>
      <div>
        <p class="text-red-400 font-medium">{{ t('kefus.detail_load_failed') }}</p>
        <p class="text-red-400/70 text-sm">{{ kefuStore.detailError }}</p>
      </div>
      <button class="btn-secondary text-sm ml-auto" @click="load">
        {{ t('common.retry') }}
      </button>
    </div>

    <div
      v-else-if="kefuStore.detailLoading && !kefu"
      class="bg-wecom-dark border border-wecom-border rounded-xl p-6 flex items-center justify-center text-wecom-muted"
    >
      {{ t('kefus.detail_loading') }}
    </div>

    <div v-else-if="kefu" class="space-y-4">
      <!-- Summary card -->
      <div class="bg-wecom-dark border border-wecom-border rounded-xl p-4 space-y-3">
        <div class="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
          <div>
            <p class="text-sm text-wecom-muted">{{ t('kefus.agent') }}</p>
            <h2 class="text-2xl font-display font-bold text-wecom-text">
              {{ kefu.name }}
            </h2>
            <p class="text-sm text-wecom-muted">
              {{ kefu.department || t('kefus.no_department') }} ·
              {{ kefu.verification_status || t('kefus.not_verified') }}
            </p>
          </div>
          <div class="text-right text-sm text-wecom-muted space-y-1">
            <p>
              {{ t('kefus.last_message_at') }}:
              {{ formatDate(kefu.last_message_at || kefu.last_message_date) }}
            </p>
            <p>{{ t('kefus.updated') }}: {{ formatDate(kefu.updated_at) }}</p>
            <p>{{ t('kefus.created') }}: {{ formatDate(kefu.created_at) }}</p>
          </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 text-sm">
          <div class="bg-wecom-surface border border-wecom-border rounded-lg p-3">
            <p class="text-wecom-muted">{{ t('kefus.device') }}</p>
            <p class="text-wecom-text font-semibold">{{ kefu.device_serial }}</p>
            <p class="text-xs text-wecom-muted">
              {{ kefu.device_model || t('kefus.unknown_model') }}
            </p>
          </div>
          <div class="bg-wecom-surface border border-wecom-border rounded-lg p-3">
            <p class="text-wecom-muted">{{ t('kefus.streamers') }}</p>
            <p class="text-wecom-text font-semibold">{{ kefu.customer_count }}</p>
          </div>
          <div class="bg-wecom-surface border border-wecom-border rounded-lg p-3">
            <p class="text-wecom-muted">{{ t('kefus.messages') }}</p>
            <p class="text-wecom-text font-semibold">
              {{ kefu.message_count }} {{ t('kefus.total') }}
            </p>
            <p class="text-xs text-wecom-muted">
              {{ kefu.sent_by_kefu }} {{ t('kefus.sent_by_agent') }} · {{ kefu.sent_by_customer }}
              {{ t('kefus.sent_by_streamers') }}
            </p>
          </div>
        </div>
      </div>

      <!-- Message breakdown -->
      <div class="bg-wecom-dark border border-wecom-border rounded-xl p-4 space-y-2">
        <div class="flex items-center justify-between">
          <h3 class="text-lg font-display font-semibold text-wecom-text">
            {{ t('kefus.message_breakdown') }}
          </h3>
          <span class="text-xs text-wecom-muted">
            {{ Object.keys(kefuStore.messageBreakdown).length || 0 }} {{ t('kefus.types') }}
          </span>
        </div>
        <div class="flex flex-wrap gap-2 text-xs text-wecom-text">
          <span
            v-for="(count, type) in kefuStore.messageBreakdown"
            :key="type"
            class="px-2 py-1 rounded bg-wecom-surface border border-wecom-border"
          >
            {{ type }}: {{ count }}
          </span>
          <span
            v-if="Object.keys(kefuStore.messageBreakdown).length === 0"
            class="text-wecom-muted"
          >
            {{ t('kefus.no_messages_yet') }}
          </span>
        </div>
      </div>

      <!-- Customers -->
      <div class="bg-wecom-dark border border-wecom-border rounded-xl p-4 space-y-3">
        <div class="flex items-center justify-between">
          <h3 class="text-lg font-display font-semibold text-wecom-text">
            {{ t('kefus.conversations') }} ({{ kefuStore.customersTotal }})
          </h3>
          <button class="btn-secondary text-sm" :disabled="kefuStore.detailLoading" @click="load">
            {{ t('common.refresh') }}
          </button>
        </div>

        <div v-if="customers.length === 0" class="text-wecom-muted text-sm">
          {{ t('kefus.no_conversations_yet') }}
        </div>
        <div v-else class="overflow-auto max-h-[480px]">
          <table class="min-w-full text-sm">
            <thead class="bg-wecom-surface border-b border-wecom-border text-wecom-muted">
              <tr>
                <th class="text-left px-4 py-2">{{ t('kefus.table_streamer') }}</th>
                <th class="text-left px-4 py-2">{{ t('kefus.table_channel') }}</th>
                <th class="text-left px-4 py-2">{{ t('kefus.table_last_message') }}</th>
                <th class="text-left px-4 py-2">{{ t('kefus.table_preview') }}</th>
                <th class="text-left px-4 py-2">{{ t('kefus.table_totals') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="customer in customers"
                :key="customer.id"
                class="border-b border-wecom-border hover:bg-wecom-surface/60 transition-colors cursor-pointer"
                @click="openConversation(customer.id)"
              >
                <td class="px-4 py-2">
                  <div class="flex items-center gap-3">
                    <img
                      :src="avatarUrlForCustomer(customer)"
                      :alt="`Avatar for ${customer.name}`"
                      class="w-10 h-10 rounded-full border border-wecom-border bg-wecom-surface object-cover shrink-0"
                    />
                    <div>
                      <p class="text-wecom-text font-medium">{{ customer.name }}</p>
                      <p class="text-xs text-wecom-muted">
                        {{ customer.kefu_name || '—' }} · {{ customer.device_serial }}
                      </p>
                    </div>
                  </div>
                </td>
                <td class="px-4 py-2 text-wecom-muted">
                  {{ customer.channel || '—' }}
                </td>
                <td class="px-4 py-2 text-wecom-text">
                  {{ formatDate(customer.last_message_at || customer.last_message_date) }}
                </td>
                <td
                  class="px-4 py-2 text-wecom-muted truncate max-w-xs"
                  :title="customer.last_message_preview || undefined"
                >
                  {{ customer.last_message_preview || '—' }}
                </td>
                <td class="px-4 py-2 text-wecom-text">
                  {{ customer.message_count }} msgs · {{ customer.sent_by_kefu }} sent ·
                  {{ customer.sent_by_customer }} recv
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>
