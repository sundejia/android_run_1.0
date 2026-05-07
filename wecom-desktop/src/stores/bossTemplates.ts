import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  bossApi,
  type BossTemplate,
  type BossTemplateCreateRequest,
  type BossTemplatePreviewRequest,
  type BossTemplatePreviewResponse,
  type BossTemplateScenario,
  type BossTemplateUpdateRequest,
} from '../services/bossApi'

export const useBossTemplatesStore = defineStore('bossTemplates', () => {
  const templatesByScenario = ref<Record<BossTemplateScenario, BossTemplate[]>>({
    first_greet: [],
    reply: [],
    reengage: [],
  })
  const loading = ref(false)
  const saving = ref(false)
  const error = ref<string | null>(null)
  const lastPreview = ref<BossTemplatePreviewResponse | null>(null)

  async function load(scenario: BossTemplateScenario): Promise<BossTemplate[]> {
    loading.value = true
    error.value = null
    try {
      const response = await bossApi.listTemplates(scenario)
      templatesByScenario.value = {
        ...templatesByScenario.value,
        [scenario]: response.templates,
      }
      return response.templates
    } catch (e) {
      error.value = e instanceof Error ? e.message : `Failed to load templates (${scenario})`
      return []
    } finally {
      loading.value = false
    }
  }

  async function create(payload: BossTemplateCreateRequest): Promise<BossTemplate | null> {
    saving.value = true
    error.value = null
    try {
      const created = await bossApi.createTemplate(payload)
      const current = templatesByScenario.value[payload.scenario] ?? []
      templatesByScenario.value = {
        ...templatesByScenario.value,
        [payload.scenario]: [...current, created],
      }
      return created
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to create template'
      return null
    } finally {
      saving.value = false
    }
  }

  async function update(
    id: number,
    scenario: BossTemplateScenario,
    payload: BossTemplateUpdateRequest,
  ): Promise<BossTemplate | null> {
    saving.value = true
    error.value = null
    try {
      const updated = await bossApi.updateTemplate(id, payload)
      const current = templatesByScenario.value[scenario] ?? []
      templatesByScenario.value = {
        ...templatesByScenario.value,
        [scenario]: current.map((row) => (row.id === id ? updated : row)),
      }
      return updated
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to update template'
      return null
    } finally {
      saving.value = false
    }
  }

  async function remove(id: number, scenario: BossTemplateScenario): Promise<boolean> {
    saving.value = true
    error.value = null
    try {
      await bossApi.deleteTemplate(id)
      const current = templatesByScenario.value[scenario] ?? []
      templatesByScenario.value = {
        ...templatesByScenario.value,
        [scenario]: current.filter((row) => row.id !== id),
      }
      return true
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to delete template'
      return false
    } finally {
      saving.value = false
    }
  }

  async function preview(payload: BossTemplatePreviewRequest): Promise<BossTemplatePreviewResponse | null> {
    error.value = null
    try {
      const result = await bossApi.previewTemplate(payload)
      lastPreview.value = result
      return result
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to preview template'
      return null
    }
  }

  function templatesFor(scenario: BossTemplateScenario): BossTemplate[] {
    return templatesByScenario.value[scenario] ?? []
  }

  const total = computed<number>(() =>
    Object.values(templatesByScenario.value).reduce((sum, list) => sum + list.length, 0),
  )

  return {
    templatesByScenario,
    loading,
    saving,
    error,
    lastPreview,
    total,
    load,
    create,
    update,
    remove,
    preview,
    templatesFor,
  }
})
