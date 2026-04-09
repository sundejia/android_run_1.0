<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  message: string
  type?: 'success' | 'error' | 'warning' | 'info'
  duration?: number
  show: boolean
}>()

const emit = defineEmits<{
  close: []
}>()

const visible = ref(props.show)

// Auto-close after duration
watch(() => props.show, (newVal) => {
  visible.value = newVal
  if (newVal && props.duration) {
    setTimeout(() => {
      emit('close')
    }, props.duration)
  }
})

// Icon based on type
const icon = {
  success: '✓',
  error: '✕',
  warning: '⚠',
  info: 'ℹ',
}

// Colors based on type
const colors = {
  success: 'bg-green-900/90 border-green-500/50 text-green-200',
  error: 'bg-red-900/90 border-red-500/50 text-red-200',
  warning: 'bg-yellow-900/90 border-yellow-500/50 text-yellow-200',
  info: 'bg-blue-900/90 border-blue-500/50 text-blue-200',
}

const iconColors = {
  success: 'bg-green-500 text-white',
  error: 'bg-red-500 text-white',
  warning: 'bg-yellow-500 text-black',
  info: 'bg-blue-500 text-white',
}
</script>

<template>
  <Transition
    enter-active-class="transition-all duration-300 ease-out"
    enter-from-class="translate-y-4 opacity-0"
    enter-to-class="translate-y-0 opacity-100"
    leave-active-class="transition-all duration-200 ease-in"
    leave-from-class="translate-y-0 opacity-100"
    leave-to-class="translate-y-4 opacity-0"
  >
    <div
      v-if="show"
      class="fixed bottom-6 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-lg border shadow-xl backdrop-blur-sm"
      :class="colors[type || 'info']"
    >
      <!-- Icon -->
      <span
        class="w-6 h-6 rounded-full flex items-center justify-center text-sm font-bold"
        :class="iconColors[type || 'info']"
      >
        {{ icon[type || 'info'] }}
      </span>
      
      <!-- Message -->
      <span class="text-sm font-medium">{{ message }}</span>
      
      <!-- Close button -->
      <button
        @click="emit('close')"
        class="ml-2 opacity-60 hover:opacity-100 transition-opacity"
      >
        ✕
      </button>
    </div>
  </Transition>
</template>

