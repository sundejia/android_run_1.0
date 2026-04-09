/**
 * 恢复检测 Hook
 *
 * 提供全局恢复任务检测功能，用于在应用启动或任意界面检测未完成的任务。
 * 支持 WebSocket 实时通知。
 */

import { ref, onMounted, onUnmounted } from 'vue'
import { api } from '../services/api'

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

export interface DeviceEvent {
  type: 'device_connected' | 'device_disconnected'
  device_serial: string
  has_resumable_tasks?: boolean
  resumable_tasks?: ResumableTask[]
  marked_tasks?: any[]
}

// 全局状态（跨组件共享）
const hasChecked = ref(false)
const hasResumableTasks = ref(false)
const resumableTasks = ref<ResumableTask[]>([])
const showRecoveryDialog = ref(false)
const isLoading = ref(false)
const lastCheckTime = ref<Date | null>(null)

// WebSocket 相关状态
const wsConnected = ref(false)
const lastDeviceEvent = ref<DeviceEvent | null>(null)
let wsInstance: WebSocket | null = null
let wsReconnectTimer: ReturnType<typeof setTimeout> | null = null
const WS_RECONNECT_INTERVAL = 5000

/**
 * 恢复检测 Hook
 *
 * 使用方法:
 * ```typescript
 * const {
 *   hasResumableTasks,
 *   resumableTasks,
 *   showRecoveryDialog,
 *   checkForResumableTasks,
 *   closeDialog,
 *   resumeTask,
 *   discardTask,
 *   discardAllTasks,
 * } = useRecoveryCheck()
 * ```
 */
export function useRecoveryCheck(
  options: {
    autoCheck?: boolean
    checkOnMount?: boolean
    checkInterval?: number // 自动检查间隔（毫秒）
  } = {}
) {
  const { autoCheck = false, checkOnMount = true, checkInterval = 0 } = options

  let intervalId: ReturnType<typeof setInterval> | null = null

  /**
   * 检查可恢复任务
   */
  async function checkForResumableTasks(force = false) {
    // 避免重复检查（除非强制）
    if (!force && hasChecked.value && lastCheckTime.value) {
      const timeSinceLastCheck = Date.now() - lastCheckTime.value.getTime()
      if (timeSinceLastCheck < 5000) {
        // 5秒内不重复检查
        return
      }
    }

    isLoading.value = true

    try {
      const response = await api.checkAllResumableTasks()

      hasResumableTasks.value = response.has_resumable
      resumableTasks.value = response.tasks || []
      hasChecked.value = true
      lastCheckTime.value = new Date()

      // 如果有可恢复任务且未显示对话框，则显示
      if (response.has_resumable && resumableTasks.value.length > 0) {
        showRecoveryDialog.value = true
        console.log(`[Recovery] Found ${resumableTasks.value.length} resumable tasks`)
      }
    } catch (e) {
      console.error('[Recovery] Failed to check resumable tasks:', e)
      // 出错时不显示对话框，但标记已检查
      hasChecked.value = true
    } finally {
      isLoading.value = false
    }
  }

  /**
   * 检查特定设备的可恢复任务
   */
  async function checkDeviceRecovery(deviceSerial: string): Promise<ResumableTask[]> {
    try {
      const response = await api.checkDeviceResumableTasks(deviceSerial)
      return response.tasks || []
    } catch (e) {
      console.error(`[Recovery] Failed to check device ${deviceSerial}:`, e)
      return []
    }
  }

  /**
   * 关闭恢复对话框
   */
  function closeDialog() {
    showRecoveryDialog.value = false
  }

  /**
   * 恢复任务
   */
  async function resumeTask(taskId: string): Promise<boolean> {
    try {
      const response = await api.resumeRecoveryTask(taskId)

      if (response.success) {
        // 从列表中移除已恢复的任务
        resumableTasks.value = resumableTasks.value.filter((t) => t.task_id !== taskId)

        // 如果没有更多任务，关闭对话框
        if (resumableTasks.value.length === 0) {
          hasResumableTasks.value = false
          showRecoveryDialog.value = false
        }

        return true
      }
      return false
    } catch (e) {
      console.error(`[Recovery] Failed to resume task ${taskId}:`, e)
      return false
    }
  }

  /**
   * 放弃任务
   */
  async function discardTask(taskId: string): Promise<boolean> {
    try {
      const response = await api.discardRecoveryTask(taskId)

      if (response.success) {
        // 从列表中移除
        resumableTasks.value = resumableTasks.value.filter((t) => t.task_id !== taskId)

        // 如果没有更多任务，关闭对话框
        if (resumableTasks.value.length === 0) {
          hasResumableTasks.value = false
          showRecoveryDialog.value = false
        }

        return true
      }
      return false
    } catch (e) {
      console.error(`[Recovery] Failed to discard task ${taskId}:`, e)
      return false
    }
  }

  /**
   * 放弃所有任务
   */
  async function discardAllTasks(): Promise<boolean> {
    try {
      // 依次放弃所有任务
      for (const task of resumableTasks.value) {
        await api.discardRecoveryTask(task.task_id)
      }

      resumableTasks.value = []
      hasResumableTasks.value = false
      showRecoveryDialog.value = false

      return true
    } catch (e) {
      console.error('[Recovery] Failed to discard all tasks:', e)
      // 即使失败也刷新列表
      await checkForResumableTasks(true)
      return false
    }
  }

  /**
   * 保存任务的 UI 状态
   */
  async function saveTaskUIState(taskId: string, uiState: Record<string, any>): Promise<boolean> {
    try {
      await api.saveTaskUIState(taskId, uiState)
      return true
    } catch (e) {
      console.error(`[Recovery] Failed to save UI state for task ${taskId}:`, e)
      return false
    }
  }

  /**
   * 开始自动检查
   */
  function startAutoCheck(interval: number) {
    if (intervalId) {
      clearInterval(intervalId)
    }
    intervalId = setInterval(() => {
      checkForResumableTasks()
    }, interval)
  }

  /**
   * 停止自动检查
   */
  function stopAutoCheck() {
    if (intervalId) {
      clearInterval(intervalId)
      intervalId = null
    }
  }

  /**
   * 连接 WebSocket 接收实时通知
   */
  function connectWebSocket() {
    if (wsInstance && wsInstance.readyState === WebSocket.OPEN) {
      return
    }

    // 获取 WebSocket URL
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.hostname || 'localhost'
    const port = 8765 // 后端端口
    const wsUrl = `${protocol}//${host}:${port}/api/recovery/ws`

    try {
      wsInstance = new WebSocket(wsUrl)

      wsInstance.onopen = () => {
        console.log('[Recovery] WebSocket connected')
        wsConnected.value = true

        // 清除重连定时器
        if (wsReconnectTimer) {
          clearTimeout(wsReconnectTimer)
          wsReconnectTimer = null
        }
      }

      wsInstance.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data)
          handleWebSocketMessage(message)
        } catch (e) {
          console.error('[Recovery] Failed to parse WebSocket message:', e)
        }
      }

      wsInstance.onclose = () => {
        console.log('[Recovery] WebSocket disconnected')
        wsConnected.value = false

        // 自动重连
        if (!wsReconnectTimer) {
          wsReconnectTimer = setTimeout(() => {
            wsReconnectTimer = null
            connectWebSocket()
          }, WS_RECONNECT_INTERVAL)
        }
      }

      wsInstance.onerror = (error) => {
        console.error('[Recovery] WebSocket error:', error)
      }
    } catch (e) {
      console.error('[Recovery] Failed to connect WebSocket:', e)
    }
  }

  /**
   * 处理 WebSocket 消息
   */
  function handleWebSocketMessage(message: any) {
    const { type, data } = message

    switch (type) {
      case 'initial_state':
        // 初始状态
        if (data.resumable_tasks && data.resumable_tasks.length > 0) {
          resumableTasks.value = data.resumable_tasks
          hasResumableTasks.value = true
          showRecoveryDialog.value = true
        }
        break

      case 'device_connected':
        // 设备连接
        console.log(`[Recovery] Device connected: ${data.device_serial}`)
        lastDeviceEvent.value = {
          type: 'device_connected',
          device_serial: data.device_serial,
          has_resumable_tasks: data.has_resumable_tasks,
          resumable_tasks: data.resumable_tasks,
        }

        // 如果有可恢复任务，刷新并显示对话框
        if (data.has_resumable_tasks && data.resumable_tasks?.length > 0) {
          resumableTasks.value = data.resumable_tasks
          hasResumableTasks.value = true
          showRecoveryDialog.value = true
        }
        break

      case 'device_disconnected':
        // 设备断开
        console.log(`[Recovery] Device disconnected: ${data.device_serial}`)
        lastDeviceEvent.value = {
          type: 'device_disconnected',
          device_serial: data.device_serial,
          marked_tasks: data.marked_tasks,
        }

        // 如果有任务被标记为待恢复，刷新任务列表
        if (data.tasks_marked_count > 0) {
          checkForResumableTasks(true)
        }
        break

      case 'refresh_response':
        // 刷新响应
        if (data.resumable_tasks) {
          resumableTasks.value = data.resumable_tasks
          hasResumableTasks.value = data.count > 0
        }
        break

      case 'heartbeat':
      case 'pong':
        // 心跳响应，忽略
        break

      default:
        console.log(`[Recovery] Unknown message type: ${type}`)
    }
  }

  /**
   * 断开 WebSocket 连接
   */
  function disconnectWebSocket() {
    if (wsReconnectTimer) {
      clearTimeout(wsReconnectTimer)
      wsReconnectTimer = null
    }

    if (wsInstance) {
      wsInstance.close()
      wsInstance = null
    }

    wsConnected.value = false
  }

  // 组件挂载时检查
  onMounted(() => {
    if (checkOnMount && !hasChecked.value) {
      checkForResumableTasks()
    }

    if (autoCheck && checkInterval > 0) {
      startAutoCheck(checkInterval)
    }

    // 连接 WebSocket
    connectWebSocket()
  })

  // 组件卸载时清理
  onUnmounted(() => {
    stopAutoCheck()
    // 注意：不断开 WebSocket，因为它是全局共享的
  })

  return {
    // 状态
    hasChecked,
    hasResumableTasks,
    resumableTasks,
    showRecoveryDialog,
    isLoading,
    lastCheckTime,
    wsConnected,
    lastDeviceEvent,

    // 方法
    checkForResumableTasks,
    checkDeviceRecovery,
    closeDialog,
    resumeTask,
    discardTask,
    discardAllTasks,
    saveTaskUIState,
    startAutoCheck,
    stopAutoCheck,
    connectWebSocket,
    disconnectWebSocket,
  }
}

/**
 * 获取任务类型的显示名称（翻译键）
 */
export function getTaskTypeLabel(taskType: string): string {
  const labels: Record<string, string> = {
    full_sync: 'common.task_full_sync',
    followup_scan: 'common.task_followup_scan',
    phase2_scan: 'common.task_phase2_scan',
  }
  return labels[taskType] || taskType
}

/**
 * 获取任务状态的显示名称（翻译键）
 */
export function getTaskStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    running: 'common.task_running',
    paused: 'common.task_paused',
    pending_recovery: 'common.task_pending_recovery',
    failed: 'common.task_failed',
    completed: 'common.task_completed',
  }
  return labels[status] || status
}
