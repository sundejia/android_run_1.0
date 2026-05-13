<script setup lang="ts">
import type { ReviewGateSettings } from '../../services/api'
import { useI18n } from '../../composables/useI18n'

const props = defineProps<{
  modelValue: ReviewGateSettings
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: ReviewGateSettings]
}>()

const { t } = useI18n()

function patch(fields: Partial<ReviewGateSettings>) {
  emit('update:modelValue', { ...props.modelValue, ...fields })
}
</script>

<template>
  <div class="space-y-4">
    <div
      id="media-review-server-config-hint"
      class="rounded-md border border-blue-500/40 bg-blue-500/10 px-3 py-2 text-xs text-blue-200"
    >
      {{ t('media_actions.review_server_config_hint') }}
    </div>

    <div>
      <label for="media-video-review-policy" class="block text-sm font-medium text-gray-300 mb-1">
        {{ t('media_actions.video_review_policy_label') }}
      </label>
      <select
        id="media-video-review-policy"
        :value="modelValue.video_review_policy"
        :disabled="disabled"
        class="w-full bg-gray-700 border border-gray-600 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
        @change="patch({ video_review_policy: ($event.target as HTMLSelectElement).value })"
      >
        <option value="extract_frame">{{ t('media_actions.video_review_extract_frame') }}</option>
        <option value="skip">{{ t('media_actions.video_review_skip') }}</option>
        <option value="always">{{ t('media_actions.video_review_always') }}</option>
      </select>
      <p class="text-xs text-gray-500 mt-1">
        {{ t('media_actions.review_gate_hint') }}
      </p>
    </div>
  </div>
</template>
