<script setup lang="ts">
import { computed } from 'vue'
import { api } from '../services/api'
import { useI18n } from '../composables/useI18n'
import { isReviewPassingDisplay, toDisplayScore } from '../utils/reviewScore'
import {
  extractAiReviewBreakdown,
  extractAiReviewDecision,
  extractAiReviewReason,
  formatAiReviewLabel,
} from '../utils/aiReviewDetails'

export interface VideoReviewFrameRow {
  frame_index: number
  percent?: number
  time_seconds?: number
  file_path?: string
  review_external_id?: string | null
  ai_review_score?: number | null
  ai_review_details_json?: string | null
  ai_review_status?: string | null
  ai_review_error?: string | null
}

const props = defineProps<{
  modelValue: boolean
  messageId: number
  dbPath?: string | null
  framesJson: string | null | undefined
  aggregateScore: number | null | undefined
}>()

const emit = defineEmits<{ 'update:modelValue': [boolean] }>()
const { t } = useI18n()

interface FrameAiNarrative {
  decision: string | null
  reason: string | null
  scoreReasons: ReturnType<typeof extractAiReviewBreakdown>['scoreReasons']
  penalties: string[]
}

function frameAiNarrative(detailsJson: string | null | undefined): FrameAiNarrative | null {
  if (!detailsJson?.trim()) return null
  const { scoreReasons, penalties } = extractAiReviewBreakdown(detailsJson)
  const decision = extractAiReviewDecision(detailsJson)
  const reason = extractAiReviewReason(detailsJson)
  if (!decision && !reason && scoreReasons.length === 0 && penalties.length === 0) return null
  return { decision, reason, scoreReasons, penalties }
}

const frames = computed((): VideoReviewFrameRow[] => {
  if (!props.framesJson?.trim()) return []
  try {
    const raw = JSON.parse(props.framesJson) as unknown
    if (!Array.isArray(raw)) return []
    return raw as VideoReviewFrameRow[]
  } catch {
    return []
  }
})

type FrameRowWithNarrative = VideoReviewFrameRow & { narrative: FrameAiNarrative | null }

const framesWithNarrative = computed((): FrameRowWithNarrative[] =>
  frames.value.map((f) => ({
    ...f,
    narrative: frameAiNarrative(f.ai_review_details_json),
  }))
)

function parseBreakdown(
  detailsJson: string | null | undefined
): { label: string; score: number }[] {
  if (!detailsJson?.trim()) return []
  try {
    const data = JSON.parse(detailsJson) as Record<string, unknown>
    const result = (data.result as Record<string, unknown>) || data
    const scores = result.scores as Record<string, unknown> | undefined
    if (!scores || typeof scores !== 'object') return []
    const out: { label: string; score: number }[] = []
    for (const [key, item] of Object.entries(scores)) {
      if (!item || typeof item !== 'object') continue
      const o = item as Record<string, unknown>
      const sv = o.score
      let num = 0
      if (typeof sv === 'number') num = sv
      else if (typeof sv === 'string') num = parseFloat(sv) || 0
      const label = String(key).trim().replace(/_/g, ' ')
      out.push({ label, score: num })
    }
    return out
  } catch {
    return []
  }
}

function barPct(score: number, max: number): string {
  if (max <= 0) return '0%'
  return `${Math.min(100, Math.max(0, (score / max) * 100))}%`
}

const summary = computed(() => {
  const list = frames.value
  const scored = list
    .map((f) => f.ai_review_score)
    .filter((s): s is number => s != null && !Number.isNaN(Number(s)))
    .map(Number)
  const best = scored.length ? Math.max(...scored) : null
  const worst = scored.length ? Math.min(...scored) : null
  const consistency = best != null && worst != null ? best - worst : null
  return { best, worst, consistency, count: list.length }
})

function close() {
  emit('update:modelValue', false)
}

function frameImgUrl(idx: number) {
  return api.getVideoReviewFrameUrl(props.messageId, idx, props.dbPath || undefined)
}

function showDimensionBars(f: VideoReviewFrameRow): boolean {
  const narrative = frameAiNarrative(f.ai_review_details_json)
  if (narrative && narrative.scoreReasons.length > 0) return false
  return parseBreakdown(f.ai_review_details_json).length > 0
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="modelValue"
      class="fixed inset-0 z-[10000] bg-black/90 flex items-center justify-center p-4"
      @click.self="close"
    >
      <div
        class="w-full max-w-[min(1200px,96vw)] max-h-[92vh] overflow-hidden rounded-xl border border-wecom-border bg-wecom-darker text-wecom-text shadow-2xl flex flex-col"
        @click.stop
      >
        <div
          class="flex items-center justify-between px-4 py-3 border-b border-wecom-border shrink-0"
        >
          <h2 class="text-sm font-semibold">
            {{ t('sidecar.video_review_detail_title', undefined, '视频审核结果') }}
          </h2>
          <button
            type="button"
            class="text-2xl leading-none text-wecom-muted hover:text-wecom-text px-2"
            aria-label="Close"
            @click="close"
          >
            ×
          </button>
        </div>

        <div class="flex-1 overflow-auto p-4 flex flex-col lg:flex-row gap-4 min-h-0">
          <div class="flex-1 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3 min-w-0">
            <div
              v-for="f in framesWithNarrative"
              :key="f.frame_index"
              class="rounded-lg border border-wecom-border bg-wecom-dark/80 p-2 flex flex-col gap-2 min-w-0"
            >
              <div class="text-xs font-medium flex justify-between gap-2">
                <span
                  >{{ t('sidecar.video_review_frame', undefined, '帧') }}
                  {{ f.frame_index + 1 }}</span
                >
                <span v-if="f.ai_review_score != null" class="font-mono opacity-90">{{
                  Number(f.ai_review_score).toFixed(4)
                }}</span>
              </div>
              <div class="aspect-video rounded overflow-hidden bg-black/40 border border-white/10">
                <img
                  :src="frameImgUrl(f.frame_index)"
                  :alt="`frame ${f.frame_index}`"
                  class="w-full h-full object-contain"
                  loading="lazy"
                  @error="($event.target as HTMLImageElement).style.display = 'none'"
                />
              </div>
              <div
                v-if="f.narrative"
                class="text-[10px] mt-1 space-y-1 text-left leading-snug text-wecom-muted border-t border-white/10 pt-1.5"
              >
                <div v-if="f.narrative.decision" class="text-wecom-text opacity-90">
                  {{ f.narrative.decision }}
                </div>
                <div v-if="f.narrative.reason" class="whitespace-pre-wrap opacity-90">
                  {{ t('sidecar.ai_review_reason', undefined, '原因') }}:
                  {{ f.narrative.reason }}
                </div>
                <div v-if="f.narrative.scoreReasons.length" class="space-y-1 pt-0.5">
                  <div
                    v-for="item in f.narrative.scoreReasons"
                    :key="`${f.frame_index}-${item.key}`"
                    class="whitespace-pre-wrap opacity-90"
                  >
                    {{ formatAiReviewLabel(item.label)
                    }}<template v-if="item.score"> ({{ item.score }})</template>:
                    {{ item.reason }}
                  </div>
                </div>
                <div v-if="f.narrative.penalties.length" class="space-y-1 pt-0.5">
                  <div class="text-wecom-text opacity-90">
                    {{ t('sidecar.ai_review_penalties', undefined, '扣分项') }}:
                  </div>
                  <div
                    v-for="(penalty, pi) in f.narrative.penalties"
                    :key="`${f.frame_index}-penalty-${pi}`"
                    class="whitespace-pre-wrap pl-2 opacity-85"
                  >
                    - {{ penalty }}
                  </div>
                </div>
              </div>
              <div
                v-if="f.ai_review_status && f.ai_review_status !== 'completed'"
                class="text-[10px] text-yellow-300/90"
              >
                {{ f.ai_review_status }}
                <span v-if="f.ai_review_error"> — {{ f.ai_review_error }}</span>
              </div>
              <div
                v-if="showDimensionBars(f)"
                class="space-y-1 flex-1 min-h-0 overflow-y-auto max-h-[220px]"
              >
                <div
                  v-for="(row, ri) in parseBreakdown(f.ai_review_details_json)"
                  :key="`${f.frame_index}-${ri}`"
                  class="text-[10px]"
                >
                  <div class="flex justify-between gap-1 mb-0.5 opacity-80">
                    <span class="truncate" :title="row.label">{{ row.label }}</span>
                    <span class="font-mono shrink-0">{{ row.score.toFixed(3) }}</span>
                  </div>
                  <div class="h-1.5 rounded bg-white/10 overflow-hidden">
                    <div
                      class="h-full rounded bg-emerald-500/80"
                      :style="{
                        width: barPct(
                          row.score,
                          Math.max(
                            ...parseBreakdown(f.ai_review_details_json).map((r) => r.score),
                            0.001
                          )
                        ),
                      }"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div
            class="w-full lg:w-56 shrink-0 rounded-lg border border-emerald-500/25 bg-emerald-950/20 p-3 space-y-2 text-xs"
          >
            <div class="font-semibold text-emerald-100/90">
              {{ t('sidecar.video_review_summary_title', undefined, '汇总') }}
            </div>
            <div v-if="aggregateScore != null" class="space-y-1">
              <div class="opacity-80">
                {{ t('sidecar.video_review_avg', undefined, '平均分') }} ({{
                  t('sidecar.video_review_ten_scale', undefined, '十分制')
                }})
              </div>
              <div class="text-lg font-mono">{{ toDisplayScore(aggregateScore)!.toFixed(2) }}</div>
              <div
                v-if="isReviewPassingDisplay(aggregateScore)"
                class="inline-block px-2 py-0.5 rounded bg-emerald-500/30 text-emerald-100"
              >
                {{ t('sidecar.video_review_pass', undefined, '合格') }}
              </div>
              <div v-else class="inline-block px-2 py-0.5 rounded bg-red-500/25 text-red-100">
                {{ t('sidecar.video_review_fail', undefined, '不合格') }}
              </div>
            </div>
            <div class="pt-2 border-t border-white/10 space-y-1 opacity-90">
              <div>
                {{ t('sidecar.video_review_frames_analyzed', undefined, '分析帧数') }}:
                {{ summary.count }}
              </div>
              <div v-if="summary.best != null">
                {{ t('sidecar.video_review_best_frame', undefined, '最佳帧') }}:
                {{ Number(summary.best).toFixed(4) }}
              </div>
              <div v-if="summary.worst != null">
                {{ t('sidecar.video_review_worst_frame', undefined, '最差帧') }}:
                {{ Number(summary.worst).toFixed(4) }}
              </div>
              <div v-if="summary.consistency != null">
                {{ t('sidecar.video_review_consistency', undefined, '一致性 (max−min)') }}:
                {{ Number(summary.consistency).toFixed(4) }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
