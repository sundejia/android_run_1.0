<script setup lang="ts">
import { useI18n } from '../composables/useI18n'
import { isReviewPassingDisplay, toDisplayScore } from '../utils/reviewScore'

const props = defineProps<{
  messageId: number
  videoAiReviewScore?: number | null
  videoAiReviewStatus?: string | null
  videoAiReviewError?: string | null
  videoAiReviewAt?: string | null
  isFromKefu: boolean
}>()

const emit = defineEmits<{
  openDetail: []
}>()

const { t } = useI18n()

function videoReviewStatus(): string | null {
  const s = props.videoAiReviewStatus?.trim()
  if (s) return s
  if (props.videoAiReviewScore != null || props.videoAiReviewAt) return 'completed'
  return null
}

function shouldShow(): boolean {
  return videoReviewStatus() !== null
}

function borderClass(): string {
  return props.isFromKefu ? 'border-white/20' : 'border-wecom-border'
}
</script>

<template>
  <div
    v-if="shouldShow()"
    class="text-xs mt-1.5 pt-1 border-t space-y-0.5 text-left leading-snug"
    :class="borderClass()"
    @click.stop
  >
    <template v-if="videoReviewStatus() === 'pending'">
      <div class="font-medium opacity-90">
        {{ t('sidecar.video_review_pending', undefined, '正在等待视频审核') }}
      </div>
    </template>
    <template v-else-if="videoReviewStatus() === 'timeout'">
      <div class="font-medium text-yellow-300">
        {{ t('sidecar.video_review_timeout', undefined, '视频审核超时') }}
      </div>
      <div v-if="videoAiReviewError?.trim()" class="opacity-80 whitespace-pre-wrap">
        {{ videoAiReviewError }}
      </div>
    </template>
    <template v-else-if="videoReviewStatus() === 'failed'">
      <div class="font-medium text-red-300">
        {{ t('sidecar.video_review_failed', undefined, '视频审核失败') }}
      </div>
      <div v-if="videoAiReviewError?.trim()" class="opacity-80 whitespace-pre-wrap">
        {{ videoAiReviewError }}
      </div>
    </template>
    <template v-else-if="videoReviewStatus() === 'partial'">
      <div class="font-medium text-yellow-200/90">
        {{ t('sidecar.video_review_partial', undefined, '部分帧审核失败') }}
      </div>
      <div
        v-if="videoAiReviewScore != null"
        class="font-medium opacity-90 flex flex-wrap items-center gap-2"
      >
        <span
          >{{ t('sidecar.video_review_avg', undefined, '平均分') }}:
          {{ toDisplayScore(videoAiReviewScore)!.toFixed(1) }}</span
        >
        <span
          v-if="isReviewPassingDisplay(videoAiReviewScore)"
          class="px-1.5 py-0.5 rounded text-[10px] bg-emerald-500/25 text-emerald-200"
          >{{ t('sidecar.video_review_pass', undefined, '合格') }}</span
        >
        <span v-else class="px-1.5 py-0.5 rounded text-[10px] bg-red-500/20 text-red-200">{{
          t('sidecar.video_review_fail', undefined, '不合格')
        }}</span>
      </div>
      <button
        type="button"
        class="text-wecom-primary hover:underline text-left mt-0.5"
        @click.stop="emit('openDetail')"
      >
        {{ t('sidecar.video_review_open_detail', undefined, '点击查看详细审核结果') }}
      </button>
    </template>
    <template v-else-if="videoReviewStatus() === 'completed' && videoAiReviewScore != null">
      <div class="font-medium opacity-90 flex flex-wrap items-center gap-2">
        <span
          >{{ t('sidecar.video_review_avg', undefined, '平均分') }}:
          {{ toDisplayScore(videoAiReviewScore)!.toFixed(1) }}</span
        >
        <span
          v-if="isReviewPassingDisplay(videoAiReviewScore)"
          class="px-1.5 py-0.5 rounded text-[10px] bg-emerald-500/25 text-emerald-200"
          >{{ t('sidecar.video_review_pass', undefined, '合格') }}</span
        >
        <span v-else class="px-1.5 py-0.5 rounded text-[10px] bg-red-500/20 text-red-200">{{
          t('sidecar.video_review_fail', undefined, '不合格')
        }}</span>
      </div>
      <button
        type="button"
        class="text-wecom-primary hover:underline text-left mt-0.5"
        @click.stop="emit('openDetail')"
      >
        {{ t('sidecar.video_review_open_detail', undefined, '点击查看详细审核结果') }}
      </button>
      <div v-if="videoAiReviewAt" class="opacity-50 text-[10px] font-mono">
        {{ videoAiReviewAt }}
      </div>
    </template>
  </div>
</template>
