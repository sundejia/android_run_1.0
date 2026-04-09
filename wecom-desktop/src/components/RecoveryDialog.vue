<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="show" class="recovery-overlay" @click.self="handleBackdropClick">
        <Transition name="slide-up">
          <div v-if="show" class="recovery-dialog">
            <!-- Header -->
            <div class="dialog-header">
              <div class="header-icon">
                <span class="icon-pulse">🔄</span>
              </div>
              <div class="header-text">
                <h2>{{ t('recovery.title') }}</h2>
                <p class="header-subtitle">{{ t('recovery.subtitle') }}</p>
              </div>
              <button class="close-btn" :title="t('recovery.close')" @click="emit('close')">
                ✕
              </button>
            </div>

            <!-- Task List -->
            <div class="dialog-content">
              <div v-if="tasks.length === 0" class="no-tasks">
                <span class="no-tasks-icon">✅</span>
                <p>{{ t('recovery.no_tasks') }}</p>
              </div>

              <div v-else class="task-list">
                <div
                  v-for="task in tasks"
                  :key="task.task_id"
                  class="task-card"
                  :class="{ selected: selectedTaskId === task.task_id }"
                  @click="selectTask(task.task_id)"
                >
                  <div class="task-header">
                    <span class="task-type-badge" :class="task.task_type">
                      {{ getTaskTypeLabel(task.task_type) }}
                    </span>
                    <span class="task-status" :class="task.status">
                      {{ getStatusLabel(task.status) }}
                    </span>
                  </div>

                  <div class="task-device">
                    <span class="device-icon">📱</span>
                    <span class="device-serial">{{
                      task.device_serial || t('recovery.unknown_device')
                    }}</span>
                  </div>

                  <div class="task-progress">
                    <div class="progress-bar">
                      <div
                        class="progress-fill"
                        :style="{ width: task.progress_percent + '%' }"
                      ></div>
                    </div>
                    <div class="progress-text">
                      <span>{{ task.synced_count }} / {{ task.total_count || '?' }} 客户</span>
                      <span class="progress-percent">{{ task.progress_percent }}%</span>
                    </div>
                  </div>

                  <div class="task-stats">
                    <div class="stat-item">
                      <span class="stat-icon">💬</span>
                      <span>{{ task.messages_added }} 条消息</span>
                    </div>
                    <div class="stat-item">
                      <span class="stat-icon">⏱️</span>
                      <span>{{ formatTime(task.last_checkpoint_at) }}</span>
                    </div>
                  </div>

                  <div class="task-actions">
                    <button class="btn-resume" :disabled="loading" @click.stop="handleResume(task)">
                      <span v-if="loading && selectedTaskId === task.task_id">{{
                        t('recovery.resuming')
                      }}</span>
                      <span v-else>▶ {{ t('recovery.resume') }}</span>
                    </button>
                    <button
                      class="btn-discard"
                      :disabled="loading"
                      @click.stop="handleDiscard(task)"
                    >
                      {{ t('recovery.discard') }}
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <!-- Footer -->
            <div v-if="tasks.length > 0" class="dialog-footer">
              <div class="footer-hint">
                <span class="hint-icon">💡</span>
                <span>{{ t('recovery.resume_subtitle') }}</span>
              </div>
              <div class="footer-actions">
                <button class="btn-secondary" :disabled="loading" @click="handleDiscardAll">
                  {{ t('recovery.discard_all') }}
                </button>
                <button class="btn-primary" @click="emit('close')">
                  {{ t('recovery.handle_later') }}
                </button>
              </div>
            </div>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '../composables/useI18n'

const { t } = useI18n()

export interface ResumableTask {
  task_id: string
  task_type: string
  device_serial: string
  status: string
  progress_percent: number
  synced_count: number
  total_count: number
  messages_added: number
  started_at?: string
  last_checkpoint_at?: string
  ui_state?: Record<string, any>
}

const props = defineProps<{
  show: boolean
  tasks: ResumableTask[]
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'resume', task: ResumableTask): void
  (e: 'discard', taskId: string): void
  (e: 'discardAll'): void
}>()

const router = useRouter()
const loading = ref(false)
const selectedTaskId = ref<string | null>(null)

function getTaskTypeLabel(taskType: string): string {
  return t(`common.task_${taskType}`)
}

function getStatusLabel(status: string): string {
  return t(`common.task_${status}`)
}

function formatTime(isoString?: string): string {
  if (!isoString) return t('recovery.unknown_time')
  try {
    const date = new Date(isoString)
    const now = new Date()
    const diff = now.getTime() - date.getTime()

    // 小于1分钟
    if (diff < 60000) return t('recovery.just_now')
    // 小于1小时
    if (diff < 3600000) return t('recovery.minutes_ago', { minutes: Math.floor(diff / 60000) })
    // 小于24小时
    if (diff < 86400000) return t('recovery.hours_ago', { hours: Math.floor(diff / 3600000) })
    // 其他
    return date.toLocaleString()
  } catch {
    return t('recovery.unknown_time')
  }
}

function selectTask(taskId: string) {
  selectedTaskId.value = taskId
}

function handleBackdropClick() {
  // 点击背景不关闭，避免误操作
}

async function handleResume(task: ResumableTask) {
  loading.value = true
  selectedTaskId.value = task.task_id

  try {
    emit('resume', task)

    // 导航到设备列表，带上恢复参数
    await router.push({
      name: 'devices',
      query: {
        resume: 'true',
        device: task.device_serial,
        taskId: task.task_id,
      },
    })

    emit('close')
  } catch (e) {
    console.error('Resume failed:', e)
  } finally {
    loading.value = false
  }
}

async function handleDiscard(task: ResumableTask) {
  loading.value = true
  selectedTaskId.value = task.task_id

  try {
    emit('discard', task.task_id)
  } finally {
    loading.value = false
    selectedTaskId.value = null
  }
}

async function handleDiscardAll() {
  if (!confirm(t('recovery.confirm_discard_all'))) {
    return
  }

  loading.value = true
  try {
    emit('discardAll')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
/* Overlay */
.recovery-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  padding: 1rem;
}

/* Dialog */
.recovery-dialog {
  background: linear-gradient(180deg, #1e2530 0%, #151a22 100%);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  width: 100%;
  max-width: 520px;
  max-height: 85vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-shadow:
    0 25px 50px -12px rgba(0, 0, 0, 0.5),
    0 0 0 1px rgba(255, 255, 255, 0.05);
}

/* Header */
.dialog-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.02);
}

.header-icon {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
  border-radius: 12px;
  font-size: 1.5rem;
}

.icon-pulse {
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.1);
  }
}

.header-text {
  flex: 1;
}

.header-text h2 {
  font-size: 1.125rem;
  font-weight: 600;
  color: #f8fafc;
  margin: 0 0 0.25rem 0;
}

.header-subtitle {
  font-size: 0.875rem;
  color: #94a3b8;
  margin: 0;
}

.close-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  border-radius: 8px;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
}

.close-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #f8fafc;
}

/* Content */
.dialog-content {
  flex: 1;
  overflow-y: auto;
  padding: 1rem 1.5rem;
}

.no-tasks {
  text-align: center;
  padding: 3rem 1rem;
  color: #64748b;
}

.no-tasks-icon {
  display: block;
  font-size: 3rem;
  margin-bottom: 1rem;
}

/* Task List */
.task-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.task-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 1rem;
  cursor: pointer;
  transition: all 0.2s;
}

.task-card:hover {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.12);
}

.task-card.selected {
  border-color: #3b82f6;
  background: rgba(59, 130, 246, 0.1);
}

.task-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.75rem;
}

.task-type-badge {
  padding: 0.25rem 0.75rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 500;
  background: rgba(59, 130, 246, 0.2);
  color: #60a5fa;
}

.task-type-badge.full_sync {
  background: rgba(59, 130, 246, 0.2);
  color: #60a5fa;
}

.task-type-badge.followup_scan {
  background: rgba(16, 185, 129, 0.2);
  color: #34d399;
}

.task-status {
  font-size: 0.75rem;
  color: #94a3b8;
}

.task-status.pending_recovery {
  color: #fbbf24;
}

.task-status.running {
  color: #3b82f6;
}

.task-status.paused {
  color: #94a3b8;
}

.task-device {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.device-icon {
  font-size: 1rem;
}

.device-serial {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.875rem;
  color: #e2e8f0;
}

/* Progress */
.task-progress {
  margin-bottom: 0.75rem;
}

.progress-bar {
  height: 6px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 0.5rem;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6 0%, #60a5fa 100%);
  border-radius: 3px;
  transition: width 0.3s ease;
}

.progress-text {
  display: flex;
  justify-content: space-between;
  font-size: 0.75rem;
  color: #94a3b8;
}

.progress-percent {
  font-weight: 600;
  color: #60a5fa;
}

/* Stats */
.task-stats {
  display: flex;
  gap: 1rem;
  margin-bottom: 1rem;
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.75rem;
  color: #94a3b8;
}

.stat-icon {
  font-size: 0.875rem;
}

/* Actions */
.task-actions {
  display: flex;
  gap: 0.5rem;
}

.btn-resume,
.btn-discard {
  flex: 1;
  padding: 0.5rem 1rem;
  border-radius: 8px;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-resume {
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  border: none;
  color: white;
}

.btn-resume:hover:not(:disabled) {
  background: linear-gradient(135deg, #60a5fa 0%, #3b82f6 100%);
  transform: translateY(-1px);
}

.btn-resume:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-discard {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #94a3b8;
}

.btn-discard:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.1);
  border-color: rgba(239, 68, 68, 0.3);
  color: #f87171;
}

/* Footer */
.dialog-footer {
  padding: 1rem 1.5rem;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.02);
}

.footer-hint {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.75rem;
  color: #64748b;
  margin-bottom: 1rem;
}

.hint-icon {
  font-size: 1rem;
}

.footer-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
}

.btn-secondary,
.btn-primary {
  padding: 0.625rem 1.25rem;
  border-radius: 8px;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-secondary {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #94a3b8;
}

.btn-secondary:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.3);
}

.btn-primary {
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #f8fafc;
}

.btn-primary:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.15);
}

/* Transitions */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.slide-up-enter-active,
.slide-up-leave-active {
  transition: all 0.3s ease;
}

.slide-up-enter-from {
  opacity: 0;
  transform: translateY(20px) scale(0.95);
}

.slide-up-leave-to {
  opacity: 0;
  transform: translateY(-10px) scale(0.95);
}

/* Scrollbar */
.dialog-content::-webkit-scrollbar {
  width: 6px;
}

.dialog-content::-webkit-scrollbar-track {
  background: transparent;
}

.dialog-content::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
}

.dialog-content::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.2);
}
</style>
