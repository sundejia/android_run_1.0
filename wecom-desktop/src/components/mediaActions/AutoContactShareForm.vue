<script setup lang="ts">
import { computed } from 'vue'
import type { AutoContactShareSettings } from '../../services/api'
import type { MediaActionTemplateContext } from '../../utils/mediaActionTemplates'
import { renderMediaActionTemplate } from '../../utils/mediaActionTemplates'
import { useI18n } from '../../composables/useI18n'

const props = defineProps<{
  modelValue: AutoContactShareSettings
  disabled?: boolean
  previewContext?: Partial<MediaActionTemplateContext>
}>()

const emit = defineEmits<{
  'update:modelValue': [value: AutoContactShareSettings]
}>()

const { t } = useI18n()

function patch(fields: Partial<AutoContactShareSettings>) {
  emit('update:modelValue', { ...props.modelValue, ...fields })
}

const defaultCtx = computed(() => ({
  customer_name: '测试客户',
  kefu_name: '客服A',
  device_serial: 'test_device',
  ...props.previewContext,
}))

const preSharePreview = computed(() =>
  renderMediaActionTemplate(props.modelValue.pre_share_message_text, defaultCtx.value)
)
</script>

<template>
  <div class="space-y-4">
    <!-- Contact Name -->
    <div>
      <label class="block text-sm font-medium text-gray-300 mb-1">{{
        t('media_actions.contact_name_label')
      }}</label>
      <input
        :value="modelValue.contact_name"
        :disabled="disabled"
        type="text"
        class="w-full bg-gray-700 border border-gray-600 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
        :placeholder="t('media_actions.contact_name_placeholder')"
        @input="patch({ contact_name: ($event.target as HTMLInputElement).value })"
      />
      <p class="text-xs text-amber-400 mt-1">
        {{ t('media_actions.contact_name_hint') }}
      </p>
    </div>

    <!-- Pre-share message -->
    <div class="space-y-3 rounded-lg border border-gray-700/80 bg-gray-800/40 p-4">
      <div class="flex items-center gap-2">
        <input
          id="send-message-before-contact-share"
          :checked="modelValue.send_message_before_share"
          :disabled="disabled"
          type="checkbox"
          class="rounded border-gray-600 bg-gray-700 text-blue-600 focus:ring-blue-500"
          @change="patch({ send_message_before_share: ($event.target as HTMLInputElement).checked })"
        />
        <label for="send-message-before-contact-share" class="text-sm text-gray-300">
          {{ t('media_actions.send_message_before_contact_share') }}
        </label>
      </div>

      <div>
        <label
          for="contact-share-message-template"
          class="block text-sm font-medium text-gray-300 mb-1"
        >
          {{ t('media_actions.contact_share_message_text_label') }}
        </label>
        <textarea
          id="contact-share-message-template"
          :value="modelValue.pre_share_message_text"
          :disabled="disabled"
          rows="4"
          class="w-full bg-gray-700 border border-gray-600 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          :placeholder="t('media_actions.contact_share_message_text_placeholder')"
          @input="patch({ pre_share_message_text: ($event.target as HTMLTextAreaElement).value })"
        ></textarea>
        <p class="text-xs text-gray-500 mt-1">
          {{ t('media_actions.contact_share_message_text_hint') }}
        </p>
      </div>

      <div>
        <div class="text-xs font-medium uppercase tracking-wide text-gray-400">
          {{ t('media_actions.test_message_preview_label') }}
        </div>
        <div
          id="contact-share-message-preview"
          class="mt-2 whitespace-pre-wrap rounded-md border border-gray-700 bg-gray-900/60 px-3 py-2 text-sm text-gray-200"
        >
          {{ preSharePreview }}
        </div>
        <p class="text-xs text-gray-500 mt-1">
          {{ t('media_actions.contact_share_message_preview_hint') }}
        </p>
      </div>
    </div>

    <!-- Skip if already shared -->
    <div class="flex items-center gap-2">
      <input
        id="skip-already-shared"
        :checked="modelValue.skip_if_already_shared"
        :disabled="disabled"
        type="checkbox"
        class="rounded border-gray-600 bg-gray-700 text-blue-600 focus:ring-blue-500"
        @change="patch({ skip_if_already_shared: ($event.target as HTMLInputElement).checked })"
      />
      <label for="skip-already-shared" class="text-sm text-gray-300">
        {{ t('media_actions.skip_already_shared') }}
      </label>
    </div>

    <!-- Cooldown -->
    <div>
      <label class="block text-sm font-medium text-gray-300 mb-1">
        分享冷却时间（秒）
      </label>
      <input
        :value="modelValue.cooldown_seconds"
        :disabled="disabled"
        type="number"
        min="0"
        step="1"
        class="w-32 bg-gray-700 border border-gray-600 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
        @input="patch({ cooldown_seconds: parseInt(($event.target as HTMLInputElement).value) || 0 })"
      />
      <p class="text-xs text-gray-500 mt-1">
        同一联系人两次分享之间的最小间隔，0 表示不限制
      </p>
    </div>
  </div>
</template>
