<script setup lang="ts">
import { computed, ref } from 'vue'
import type { AutoGroupInviteSettings } from '../../services/api'
import type { MediaActionTemplateContext } from '../../utils/mediaActionTemplates'
import { renderMediaActionTemplate } from '../../utils/mediaActionTemplates'
import { useI18n } from '../../composables/useI18n'

const props = defineProps<{
  modelValue: AutoGroupInviteSettings
  disabled?: boolean
  previewContext?: Partial<MediaActionTemplateContext>
}>()

const emit = defineEmits<{
  'update:modelValue': [value: AutoGroupInviteSettings]
}>()

const { t } = useI18n()
const newMember = ref('')

function patch(fields: Partial<AutoGroupInviteSettings>) {
  emit('update:modelValue', { ...props.modelValue, ...fields })
}

function addMember() {
  const name = newMember.value.trim()
  if (name && !props.modelValue.group_members.includes(name)) {
    patch({ group_members: [...props.modelValue.group_members, name] })
    newMember.value = ''
  }
}

function removeMember(index: number) {
  const members = [...props.modelValue.group_members]
  members.splice(index, 1)
  patch({ group_members: members })
}

const defaultCtx = computed(() => ({
  customer_name: '测试客户',
  kefu_name: '客服A',
  device_serial: 'test_device',
  ...props.previewContext,
}))

const preCreatePreview = computed(() =>
  renderMediaActionTemplate(props.modelValue.pre_create_message_text, defaultCtx.value)
)

const testMessagePreview = computed(() =>
  renderMediaActionTemplate(props.modelValue.test_message_text, defaultCtx.value)
)
</script>

<template>
  <div class="space-y-4">
    <!-- Group Members -->
    <div>
      <label class="block text-sm font-medium text-gray-300 mb-2">{{
        t('media_actions.group_members_label')
      }}</label>
      <div class="flex flex-wrap gap-2 mb-2">
        <span
          v-for="(member, idx) in modelValue.group_members"
          :key="idx"
          class="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-blue-600/20 text-blue-300 text-sm border border-blue-600/30"
        >
          {{ member }}
          <button
            class="ml-1 text-blue-400 hover:text-red-400 transition-colors"
            :disabled="disabled"
            @click="removeMember(idx)"
          >
            &times;
          </button>
        </span>
        <span
          v-if="modelValue.group_members.length === 0"
          class="text-sm text-gray-500 italic"
        >
          {{ t('media_actions.no_members') }}
        </span>
      </div>
      <div class="flex gap-2">
        <input
          v-model="newMember"
          :disabled="disabled"
          type="text"
          class="flex-1 bg-gray-700 border border-gray-600 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          :placeholder="t('media_actions.member_placeholder')"
          @keyup.enter="addMember"
        />
        <button
          :disabled="disabled"
          class="px-4 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700 transition-colors disabled:opacity-50"
          @click="addMember"
        >
          {{ t('media_actions.add') }}
        </button>
      </div>
    </div>

    <!-- Group Name Template -->
    <div>
      <label class="block text-sm font-medium text-gray-300 mb-1">{{
        t('media_actions.group_name_template_label')
      }}</label>
      <input
        :value="modelValue.group_name_template"
        :disabled="disabled"
        type="text"
        class="w-full bg-gray-700 border border-gray-600 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
        :placeholder="t('media_actions.group_name_template_placeholder')"
        @input="patch({ group_name_template: ($event.target as HTMLInputElement).value })"
      />
      <p class="text-xs text-gray-500 mt-1">
        {{ t('media_actions.group_name_template_hint') }}
      </p>
    </div>

    <!-- Pre-create message -->
    <div class="space-y-3 rounded-lg border border-gray-700/80 bg-gray-800/40 p-4">
      <div class="flex items-center gap-2">
        <input
          id="send-message-before-group-create"
          :checked="modelValue.send_message_before_create"
          :disabled="disabled"
          type="checkbox"
          class="rounded border-gray-600 bg-gray-700 text-blue-600 focus:ring-blue-500"
          @change="patch({ send_message_before_create: ($event.target as HTMLInputElement).checked })"
        />
        <label for="send-message-before-group-create" class="text-sm text-gray-300">
          {{ t('media_actions.send_message_before_group_create') }}
        </label>
      </div>

      <div>
        <label
          for="group-pre-create-message-template"
          class="block text-sm font-medium text-gray-300 mb-1"
        >
          {{ t('media_actions.group_pre_create_message_text_label') }}
        </label>
        <textarea
          id="group-pre-create-message-template"
          :value="modelValue.pre_create_message_text"
          :disabled="disabled"
          rows="4"
          class="w-full bg-gray-700 border border-gray-600 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          :placeholder="t('media_actions.group_pre_create_message_text_placeholder')"
          @input="patch({ pre_create_message_text: ($event.target as HTMLTextAreaElement).value })"
        ></textarea>
        <p class="text-xs text-gray-500 mt-1">
          {{ t('media_actions.group_pre_create_message_text_hint') }}
        </p>
      </div>

      <div>
        <div class="text-xs font-medium uppercase tracking-wide text-gray-400">
          {{ t('media_actions.test_message_preview_label') }}
        </div>
        <div
          id="group-pre-create-message-preview"
          class="mt-2 whitespace-pre-wrap rounded-md border border-gray-700 bg-gray-900/60 px-3 py-2 text-sm text-gray-200"
        >
          {{ preCreatePreview }}
        </div>
        <p class="text-xs text-gray-500 mt-1">
          {{ t('media_actions.test_message_preview_hint') }}
        </p>
      </div>
    </div>

    <!-- Post-create test message -->
    <div class="space-y-3 rounded-lg border border-gray-700/80 bg-gray-800/40 p-4">
      <div class="flex items-center gap-2">
        <input
          id="send-group-message-after-create"
          :checked="modelValue.send_test_message_after_create"
          :disabled="disabled"
          type="checkbox"
          class="rounded border-gray-600 bg-gray-700 text-blue-600 focus:ring-blue-500"
          @change="patch({ send_test_message_after_create: ($event.target as HTMLInputElement).checked })"
        />
        <label for="send-group-message-after-create" class="text-sm text-gray-300">
          {{ t('media_actions.send_group_message_after_create') }}
        </label>
      </div>

      <div>
        <label
          for="group-test-message-template"
          class="block text-sm font-medium text-gray-300 mb-1"
        >
          {{ t('media_actions.test_message_text_label') }}
        </label>
        <textarea
          id="group-test-message-template"
          :value="modelValue.test_message_text"
          :disabled="disabled"
          rows="4"
          class="w-full bg-gray-700 border border-gray-600 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          :placeholder="t('media_actions.test_message_text_placeholder')"
          @input="patch({ test_message_text: ($event.target as HTMLTextAreaElement).value })"
        ></textarea>
        <p class="text-xs text-gray-500 mt-1">
          {{ t('media_actions.test_message_text_hint') }}
        </p>
      </div>

      <div>
        <div class="text-xs font-medium uppercase tracking-wide text-gray-400">
          {{ t('media_actions.test_message_preview_label') }}
        </div>
        <div
          id="group-test-message-preview"
          class="mt-2 whitespace-pre-wrap rounded-md border border-gray-700 bg-gray-900/60 px-3 py-2 text-sm text-gray-200"
        >
          {{ testMessagePreview }}
        </div>
        <p class="text-xs text-gray-500 mt-1">
          {{ t('media_actions.test_message_preview_hint') }}
        </p>
      </div>
    </div>

    <!-- Skip if group exists -->
    <div class="flex items-center gap-2">
      <input
        id="skip-group-exists"
        :checked="modelValue.skip_if_group_exists"
        :disabled="disabled"
        type="checkbox"
        class="rounded border-gray-600 bg-gray-700 text-blue-600 focus:ring-blue-500"
        @change="patch({ skip_if_group_exists: ($event.target as HTMLInputElement).checked })"
      />
      <label for="skip-group-exists" class="text-sm text-gray-300">
        {{ t('media_actions.skip_group_exists') }}
      </label>
    </div>
  </div>
</template>
