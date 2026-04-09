<script setup lang="ts">
defineProps<{
  size?: 'sm' | 'md' | 'lg'
  color?: string
}>()

const sizeClasses = {
  sm: 'w-4 h-4 border-2',
  md: 'w-8 h-8 border-3',
  lg: 'w-12 h-12 border-4',
}
</script>

<template>
  <div
    class="rounded-full animate-spin border-t-transparent"
    :class="[
      sizeClasses[size || 'md'],
      color || 'border-wecom-primary'
    ]"
  ></div>
</template>

