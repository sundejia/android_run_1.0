<script setup lang="ts">
import type { AutoBlacklistSettings } from '../../services/api'
import { useI18n } from '../../composables/useI18n'

const props = defineProps<{
  modelValue: AutoBlacklistSettings
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: AutoBlacklistSettings]
}>()

const { t } = useI18n()

function patch(fields: Partial<AutoBlacklistSettings>) {
  emit('update:modelValue', { ...props.modelValue, ...fields })
}
</script>

<template>
  <div class="space-y-4">
    <div>
      <label class="block text-sm font-medium text-gray-300 mb-1">{{
        t('media_actions.blacklist_reason_label')
      }}</label>
      <input
        :value="modelValue.reason"
        :disabled="disabled"
        type="text"
        class="w-full bg-gray-700 border border-gray-600 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
        :placeholder="t('media_actions.blacklist_reason_placeholder')"
        @input="patch({ reason: ($event.target as HTMLInputElement).value })"
      />
    </div>

    <div class="flex items-center gap-2">
      <input
        id="skip-blacklisted"
        :checked="modelValue.skip_if_already_blacklisted"
        :disabled="disabled"
        type="checkbox"
        class="rounded border-gray-600 bg-gray-700 text-blue-600 focus:ring-blue-500"
        @change="patch({ skip_if_already_blacklisted: ($event.target as HTMLInputElement).checked })"
      />
      <label for="skip-blacklisted" class="text-sm text-gray-300">
        {{ t('media_actions.skip_already_blacklisted') }}
      </label>
    </div>
  </div>
</template>
