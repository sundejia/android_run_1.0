<template>
  <div class="boss-scope min-h-screen bg-boss-dark text-boss-text p-6">
    <header class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-semibold">回复话术模板</h1>
        <p class="text-boss-text-muted text-sm mt-1">
          管理「首次打招呼 / 候选人回复 / 复聊跟进」三个场景的话术模板。
          使用 <code class="bg-boss-surface px-1 rounded">{name}</code>、
          <code class="bg-boss-surface px-1 rounded">{position}</code>、
          <code class="bg-boss-surface px-1 rounded">{company}</code> 等占位符自动填充候选人简历信息。
        </p>
      </div>
      <button
        type="button"
        class="boss-button-primary"
        :disabled="store.loading"
        @click="reload"
        data-testid="reload-templates"
      >
        {{ store.loading ? '加载中…' : '刷新' }}
      </button>
    </header>

    <div
      v-if="store.error"
      class="boss-card mb-4"
      style="border-color: var(--boss-danger); color: #f4a39e"
      data-testid="error-banner"
    >
      <strong>操作失败：</strong>{{ store.error }}
    </div>

    <nav class="flex gap-2 mb-4" data-testid="scenario-tabs">
      <button
        v-for="tab in scenarios"
        :key="tab.value"
        type="button"
        class="boss-tab"
        :class="{ 'boss-tab-active': activeScenario === tab.value }"
        :data-testid="`scenario-tab-${tab.value}`"
        @click="setScenario(tab.value)"
      >
        {{ tab.label }}
      </button>
    </nav>

    <section class="boss-card mb-5">
      <h2 class="text-lg font-medium mb-3">新增模板</h2>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
        <label class="text-sm">
          <span class="block text-boss-text-muted mb-1">模板名称</span>
          <input
            v-model="newTemplate.name"
            class="boss-input"
            placeholder="例如：首聊-Java工程师"
            data-testid="new-template-name"
          />
        </label>
        <label class="text-sm flex items-end">
          <span class="boss-checkbox-row">
            <input
              type="checkbox"
              v-model="newTemplate.is_default"
              data-testid="new-template-default"
            />
            设为该场景默认模板
          </span>
        </label>
      </div>
      <label class="text-sm block mt-3">
        <span class="block text-boss-text-muted mb-1">模板内容</span>
        <textarea
          v-model="newTemplate.content"
          rows="4"
          class="boss-input"
          placeholder="您好 {name}，看到您 {position} 经历，方便聊聊吗？"
          data-testid="new-template-content"
        />
      </label>
      <div class="flex gap-2 justify-end mt-3">
        <button
          type="button"
          class="boss-button-ghost"
          :disabled="!canPreview || store.saving"
          @click="previewNew"
          data-testid="preview-new-template"
        >
          预览
        </button>
        <button
          type="button"
          class="boss-button-primary"
          :disabled="!canCreate || store.saving"
          @click="createTemplate"
          data-testid="create-template"
        >
          {{ store.saving ? '保存中…' : '保存模板' }}
        </button>
      </div>

      <div
        v-if="store.lastPreview"
        class="boss-card mt-3"
        style="background: var(--boss-surface)"
        data-testid="preview-output"
      >
        <h3 class="text-sm text-boss-text-muted mb-1">预览结果</h3>
        <p class="whitespace-pre-wrap">{{ store.lastPreview.text }}</p>
        <p
          v-if="store.lastPreview.warnings.length"
          class="text-xs text-boss-warn mt-2"
          data-testid="preview-warnings"
        >
          未填充变量：{{ store.lastPreview.warnings.join('，') }}
        </p>
      </div>
    </section>

    <section
      class="boss-card"
      data-testid="templates-list"
    >
      <h2 class="text-lg font-medium mb-3">{{ activeLabel }} 模板（{{ rows.length }}）</h2>
      <p
        v-if="!store.loading && rows.length === 0"
        class="text-boss-text-muted"
        data-testid="empty-templates"
      >
        当前场景没有模板。请在上方表单创建第一个模板。
      </p>
      <ul class="space-y-3">
        <li
          v-for="row in rows"
          :key="row.id"
          class="boss-row"
          :data-testid="`template-row-${row.id}`"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="flex-1">
              <p class="font-medium flex items-center gap-2">
                {{ row.name }}
                <span
                  v-if="row.is_default"
                  class="boss-pill-default"
                  data-testid="default-badge"
                >默认</span>
              </p>
              <p class="text-sm text-boss-text-muted mt-1 whitespace-pre-wrap">{{ row.content }}</p>
            </div>
            <div class="flex flex-col gap-2">
              <button
                type="button"
                class="boss-button-ghost"
                :disabled="store.saving"
                :data-testid="`set-default-${row.id}`"
                @click="setDefault(row.id, row.is_default)"
              >
                {{ row.is_default ? '取消默认' : '设为默认' }}
              </button>
              <button
                type="button"
                class="boss-button-danger"
                :disabled="store.saving"
                :data-testid="`delete-${row.id}`"
                @click="confirmDelete(row.id)"
              >
                删除
              </button>
            </div>
          </div>
        </li>
      </ul>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useBossTemplatesStore } from '../../stores/bossTemplates'
import type { BossTemplateScenario } from '../../services/bossApi'

const store = useBossTemplatesStore()

const scenarios: { value: BossTemplateScenario; label: string }[] = [
  { value: 'first_greet', label: '首次打招呼' },
  { value: 'reply', label: '消息回复' },
  { value: 'reengage', label: '复聊跟进' },
]

const activeScenario = ref<BossTemplateScenario>('reply')

interface NewTemplateForm {
  name: string
  content: string
  is_default: boolean
}

const newTemplate = reactive<NewTemplateForm>({
  name: '',
  content: '',
  is_default: false,
})

const rows = computed(() => store.templatesFor(activeScenario.value))
const activeLabel = computed(
  () => scenarios.find((s) => s.value === activeScenario.value)?.label ?? '',
)
const canCreate = computed(
  () => newTemplate.name.trim().length > 0 && newTemplate.content.trim().length > 0,
)
const canPreview = computed(() => newTemplate.content.trim().length > 0)

async function setScenario(scenario: BossTemplateScenario): Promise<void> {
  activeScenario.value = scenario
  await store.load(scenario)
}

async function reload(): Promise<void> {
  await store.load(activeScenario.value)
}

async function createTemplate(): Promise<void> {
  if (!canCreate.value) return
  const created = await store.create({
    name: newTemplate.name.trim(),
    scenario: activeScenario.value,
    content: newTemplate.content,
    is_default: newTemplate.is_default,
  })
  if (created) {
    newTemplate.name = ''
    newTemplate.content = ''
    newTemplate.is_default = false
  }
}

async function setDefault(id: number, isCurrentlyDefault: boolean): Promise<void> {
  await store.update(id, activeScenario.value, { is_default: !isCurrentlyDefault })
}

async function confirmDelete(id: number): Promise<void> {
  if (!window.confirm('确定要删除该模板？删除后无法恢复。')) return
  await store.remove(id, activeScenario.value)
}

async function previewNew(): Promise<void> {
  if (!canPreview.value) return
  await store.preview({
    content: newTemplate.content,
    context: {
      name: '李雷',
      position: '高级Java工程师',
      company: 'ByteDance',
      expected_salary: '40K-60K',
      expected_location: '上海',
    },
  })
}

onMounted(async () => {
  await store.load(activeScenario.value)
})
</script>

<style scoped>
.boss-tab {
  background: transparent;
  border: 1px solid var(--boss-border);
  color: var(--boss-text-muted);
  padding: 0.4rem 0.9rem;
  border-radius: 999px;
  font-size: 0.875rem;
}
.boss-tab-active {
  background: var(--boss-primary);
  color: #fff;
  border-color: var(--boss-primary);
}
.boss-row {
  border: 1px solid var(--boss-border);
  background: var(--boss-surface);
  border-radius: 0.6rem;
  padding: 0.85rem 1rem;
}
.boss-pill-default {
  background: var(--boss-accent);
  color: #1a1a1a;
  font-size: 0.7rem;
  padding: 0.1rem 0.45rem;
  border-radius: 999px;
}
</style>
