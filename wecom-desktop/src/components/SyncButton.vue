<script setup lang="ts">
defineProps<{
  disabled?: boolean
  loading?: boolean
}>()

const emit = defineEmits<{
  click: []
}>()
</script>

<template>
  <button
    @click="emit('click')"
    :disabled="disabled || loading"
    class="relative overflow-hidden btn-primary flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
  >
    <!-- Loading spinner -->
    <span v-if="loading" class="animate-spin">⏳</span>
    <span v-else>🔄</span>
    
    <!-- Button text -->
    <slot>Start Sync</slot>
    
    <!-- Shine effect on hover -->
    <span
      class="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/10 to-transparent transition-transform duration-500 group-hover:translate-x-full"
    ></span>
  </button>
</template>

