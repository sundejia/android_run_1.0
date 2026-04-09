<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import { useDeviceStore } from '../stores/devices'
import { api } from '../services/api'
import type { BlacklistEntry } from '../services/api'
import LoadingSpinner from '../components/LoadingSpinner.vue'
import Toast from '../components/Toast.vue'
import { useI18n } from '../composables/useI18n'

const { t } = useI18n()

const deviceStore = useDeviceStore()
const selectedDevice = ref<string>('')
const searchQuery = ref<string>('')

const users = ref<BlacklistEntry[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const processingMap = ref<Record<number, boolean>>({}) // Track processing status for each user by ID

// Toast state
const showToast = ref(false)
const toastMessage = ref('')
const toastType = ref<'success' | 'error'>('success')

// Stats
const totalCount = ref(0)
const blacklistedCount = ref(0)

// Computed filtered users
const filteredUsers = computed(() => {
  if (!searchQuery.value) return users.value
  const query = searchQuery.value.toLowerCase()
  return users.value.filter(user =>
    user.customer_name.toLowerCase().includes(query) ||
    user.customer_channel?.toLowerCase().includes(query)
  )
})

// Load users
async function loadUsers() {
  // device_serial is required by the backend API
  if (!selectedDevice.value) {
    users.value = []
    totalCount.value = 0
    blacklistedCount.value = 0
    return
  }

  loading.value = true
  error.value = null
  try {
    // Use new API with show_all=true to get all records
    const data = await api.getBlacklistEntries({
      device_serial: selectedDevice.value,
      show_all: true
    })
    users.value = data

    // Update stats locally based on fetched data
    totalCount.value = data.length
    blacklistedCount.value = data.filter(u => u.is_blacklisted).length
  } catch (err: any) {
    error.value = err.message || t('blacklist.load_failed')
    triggerToast(t('blacklist.load_failed'), 'error')
  } finally {
    loading.value = false
  }
}

// Watchers
watch([selectedDevice], () => {
  loadUsers()
})

// Debounced search
let searchTimeout: number | undefined
watch(searchQuery, () => {
  if (searchTimeout) clearTimeout(searchTimeout)
  searchTimeout = window.setTimeout(() => {
    // Search is now handled by computed property
  }, 300)
})

// Toggle blacklist status
async function toggleBlacklistStatus(user: BlacklistEntry) {
  if (!selectedDevice.value) {
    triggerToast(t('blacklist.select_device_required'), 'error')
    return
  }

  processingMap.value[user.id] = true

  try {
    const newStatus = !user.is_blacklisted
    await api.updateBlacklistStatus({
      id: user.id,
      is_blacklisted: newStatus
    })

    // Optimistic update
    user.is_blacklisted = newStatus
    if (newStatus) {
      blacklistedCount.value++
      triggerToast(t('blacklist.add_success', { name: user.customer_name }), 'success')
    } else {
      blacklistedCount.value--
      triggerToast(t('blacklist.remove_success', { name: user.customer_name }), 'success')
    }
  } catch (err: any) {
    triggerToast(err.message || t('blacklist.update_failed'), 'error')
    // Revert optimistic update on error
    user.is_blacklisted = !user.is_blacklisted
  } finally {
    processingMap.value[user.id] = false
  }
}

function triggerToast(message: string, type: 'success' | 'error' = 'success') {
  toastMessage.value = message
  toastType.value = type
  showToast.value = true
  setTimeout(() => {
    showToast.value = false
  }, 3000)
}

onMounted(async () => {
  await deviceStore.fetchDevices()
  // Auto-select first device if available
  if (deviceStore.devices.length > 0) {
    selectedDevice.value = deviceStore.devices[0].serial
  }
  // loadUsers will be triggered by watcher when selectedDevice changes
})
</script>

<template>
  <div class="blacklist-view h-full flex flex-col bg-wecom-darker text-wecom-text">
    <!-- Page Title -->
    <header class="px-6 py-4 border-b border-wecom-border bg-wecom-dark shrink-0">
      <h1 class="text-xl font-display font-semibold text-wecom-text">🚫 {{ t('blacklist.title') }}</h1>
      <p class="text-xs text-wecom-muted mt-1">{{ t('blacklist.description') }}</p>
    </header>

    <!-- Controls Bar -->
    <div class="p-4 border-b border-wecom-border flex flex-wrap gap-4 items-center bg-wecom-dark/50">
      <!-- Device Selector -->
      <div class="flex items-center gap-2">
        <label class="text-sm text-wecom-muted">{{ t('blacklist.device') }}:</label>
        <select
          v-model="selectedDevice"
          class="bg-wecom-surface border border-wecom-border rounded px-3 py-1.5 text-sm focus:outline-none focus:border-wecom-primary min-w-[200px]"
        >
          <option value="">{{ t('blacklist.all_devices_disabled') }}</option>
          <option v-for="device in deviceStore.devices" :key="device.serial" :value="device.serial">
            {{ device.model || device.serial }} ({{ device.serial }})
          </option>
        </select>
      </div>

      <!-- Search -->
      <div class="relative flex-1 min-w-[200px]">
        <input
          v-model="searchQuery"
          type="text"
          :placeholder="t('blacklist.search_placeholder')"
          class="w-full bg-wecom-surface border border-wecom-border rounded px-3 py-1.5 text-sm pl-8 focus:outline-none focus:border-wecom-primary"
        />
        <span class="absolute left-2.5 top-1.5 text-wecom-muted">🔍</span>
      </div>
    </div>

    <!-- Stats -->
    <div class="px-6 py-2 bg-wecom-dark/30 text-xs text-wecom-muted flex gap-4 border-b border-wecom-border">
      <span>{{ t('blacklist.total_users', { count: totalCount }) }}</span>
      <span>{{ t('blacklist.blacklisted_count', { count: blacklistedCount }) }}</span>
      <span>{{ t('blacklist.whitelisted_count', { count: totalCount - blacklistedCount }) }}</span>
    </div>

    <!-- Content Area -->
    <div class="flex-1 overflow-auto p-4 relative">
       <LoadingSpinner v-if="loading" class="absolute inset-0 flex items-center justify-center bg-wecom-darker/50 z-10" />

       <div v-if="error" class="text-red-500 text-center py-8">
         {{ error }}
         <button @click="loadUsers" class="block mx-auto mt-2 text-wecom-primary hover:underline">{{ t('common.refresh') }}</button>
       </div>

       <div v-else-if="filteredUsers.length === 0 && !loading" class="text-wecom-muted text-center py-10">
         {{ searchQuery ? t('blacklist.no_users_found') : t('blacklist.no_users_found') }}
       </div>

       <!-- User List -->
       <div v-else class="space-y-2">
          <div
            v-for="user in filteredUsers"
            :key="user.id"
            class="flex items-center justify-between p-3 rounded-lg border transition-colors bg-wecom-surface"
            :class="{
              'border-red-900/50': user.is_blacklisted,
              'border-wecom-border hover:border-wecom-primary/30': !user.is_blacklisted,
              'opacity-75': user.is_blacklisted
            }"
          >
            <div class="flex items-center gap-3">
               <!-- Avatar or Initials -->
               <div class="w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold overflow-hidden shrink-0"
                 :class="user.is_blacklisted ? 'bg-red-900/30 text-red-400' : 'bg-wecom-primary/20 text-wecom-primary'"
               >
                 <img
                   v-if="user.avatar_url"
                   :src="user.avatar_url"
                   :alt="user.customer_name"
                   class="w-full h-full object-cover"
                   @error="(e) => (e.target as HTMLImageElement).style.display = 'none'"
                 />
                 <span v-else>{{ user.customer_name.charAt(0).toUpperCase() }}</span>
               </div>

               <div>
                  <div class="flex items-center gap-2">
                    <span class="font-medium text-wecom-text">{{ user.customer_name }}</span>
                    <span v-if="user.is_blacklisted" class="text-xs px-1.5 py-0.5 rounded bg-red-900/30 text-red-400 border border-red-900/50">
                      🚫 {{ t('blacklist.blocked') }}
                    </span>
                    <span v-else class="text-xs px-1.5 py-0.5 rounded bg-green-900/30 text-green-400 border border-green-900/50">
                      ✓ {{ t('blacklist.allowed') }}
                    </span>
                    <span v-if="user.deleted_by_user" class="text-xs px-1.5 py-0.5 rounded bg-orange-900/30 text-orange-400 border border-orange-900/50">
                      ⚠️ {{ t('blacklist.deleted_by_user') }}
                    </span>
                  </div>
                  <div class="text-xs text-wecom-muted flex gap-2">
                    <span v-if="user.customer_channel">{{ user.customer_channel }}</span>
                    <span v-if="user.reason">• {{ user.reason }}</span>
                  </div>
               </div>
            </div>

            <!-- Checkbox for toggle -->
            <div class="flex items-center gap-3">
               <label class="flex items-center gap-2 cursor-pointer">
                 <input
                   type="checkbox"
                   :checked="user.is_blacklisted"
                   :disabled="processingMap[user.id]"
                   @change="toggleBlacklistStatus(user)"
                   class="w-5 h-5 rounded border-wecom-border bg-wecom-surface text-wecom-primary focus:ring-wecom-primary focus:ring-offset-0 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                 />
                 <span class="text-xs text-wecom-muted">
                   {{ user.is_blacklisted ? t('blacklist.blocked') : t('blacklist.allowed') }}
                 </span>
               </label>
            </div>
          </div>
       </div>
    </div>

    <Toast
      :show="showToast"
      :message="toastMessage"
      :type="toastType"
      @close="showToast = false"
    />
  </div>
</template>

<style scoped>
/* Scoped styles if needed, mostly using Tailwind classes */
</style>
