<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useLogStore } from '@/stores/logs'
import LogStream from '@/components/LogStream.vue'
import { TrashIcon, PlayIcon, StopIcon } from '@heroicons/vue/24/outline'

const props = defineProps<{
  active: boolean
}>()

const logStore = useLogStore()
const isAutoScroll = ref(true)
const serial = 'followup'

// Connect to log stream when component is mounted
onMounted(() => {
  logStore.connectLogStream(serial)
})

const clearLogs = () => {
  logStore.clearLogs(serial)
}

const toggleAutoScroll = () => {
  isAutoScroll.value = !isAutoScroll.value
}
</script>

<template>
  <div class="h-full flex flex-col bg-white rounded-lg shadow">
    <!-- Header/Toolbar -->
    <div class="flex items-center justify-between px-4 py-3 border-b">
      <div class="flex items-center space-x-4">
        <h3 class="text-lg font-medium text-gray-900">System Logs</h3>
        <!-- Connection status removed as store doesn't expose it -->
      </div>

      
      <div class="flex items-center space-x-2">
        <button
          @click="toggleAutoScroll"
          class="p-2 text-gray-400 hover:text-gray-600 rounded-full hover:bg-gray-100"
          :class="{ 'text-blue-600 bg-blue-50': isAutoScroll }"
          title="Auto-scroll"
        >
          <PlayIcon v-if="isAutoScroll" class="h-5 w-5" />
          <StopIcon v-else class="h-5 w-5" />
        </button>
        
        <button
          @click="clearLogs"
          class="p-2 text-gray-400 hover:text-red-600 rounded-full hover:bg-gray-100"
          title="Clear Logs"
        >
          <TrashIcon class="h-5 w-5" />
        </button>
      </div>
    </div>

    <!-- Log Stream Area -->
    <div class="flex-1 min-h-0 relative">
      <LogStream
        :logs="logStore.getDeviceLogs(serial)"
        :auto-scroll="isAutoScroll"
        class="absolute inset-0"
      />
    </div>
  </div>
</template>
