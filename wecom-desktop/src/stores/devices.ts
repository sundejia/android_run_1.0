import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  api,
  type Device,
  type SyncStatus,
  type SyncOptions,
  type InitDeviceResponse,
} from '../services/api'

export const useDeviceStore = defineStore('devices', () => {
  // State
  const devices = ref<Device[]>([])
  const selectedDevices = ref<Set<string>>(new Set())
  const syncStatuses = ref<Map<string, SyncStatus>>(new Map())
  const mirrorStatuses = ref<Map<string, boolean>>(new Map())
  const syncWebsockets = ref<Map<string, WebSocket>>(new Map())
  const loading = ref(false)
  const error = ref<string | null>(null)
  const backendConnected = ref(false)
  const selectedDevice = ref<Device | null>(null)
  const detailLoading = ref(false)
  const detailError = ref<string | null>(null)
  // Track which devices have been initialized (to avoid re-initializing)
  const initializedDevices = ref<Set<string>>(new Set())
  const initializingDevices = ref<Set<string>>(new Set())
  // Track previously seen online devices to detect hot-plug reconnections
  const previouslyOnlineDevices = ref<Set<string>>(new Set())
  // Track devices being synced for follow-up pause/resume
  const syncingDevicesForFollowup = ref<Set<string>>(new Set())
  const followupPausedForSync = ref(false)

  // Getters
  const mirrorAvailable = computed(
    () => typeof window !== 'undefined' && Boolean(window.electronAPI?.mirror)
  )

  const selectedDeviceList = computed(() =>
    devices.value.filter((d) => selectedDevices.value.has(d.serial))
  )

  const hasSelectedDevices = computed(() => selectedDevices.value.size > 0)

  const allSelected = computed(
    () =>
      devices.value.length > 0 && devices.value.every((d) => selectedDevices.value.has(d.serial))
  )

  // Actions
  async function fetchDevices() {
    loading.value = true
    error.value = null

    try {
      const result = await api.getDevices()
      devices.value = result
      backendConnected.value = true

      // Keep selected device in sync when present in the list
      if (selectedDevice.value) {
        const updated = result.find((d) => d.serial === selectedDevice.value?.serial)
        if (updated) {
          selectedDevice.value = updated
        }
      }

      // Update mirror statuses
      if (mirrorAvailable.value) {
        for (const device of result) {
          const status = await window.electronAPI!.mirror.status(device.serial)
          mirrorStatuses.value.set(device.serial, status)
        }
      }

      // Get current online device serials
      const currentOnlineDevices = new Set(result.filter((d) => d.is_online).map((d) => d.serial))

      // Detect hot-plug reconnections: devices that were previously online,
      // went offline (not in previous fetch), and are now back online
      // Also handle devices that are online but we've already marked as initialized
      // (backend may have cached kefu, but WeCom might not be running)
      for (const device of result) {
        if (device.is_online) {
          const wasInitialized = initializedDevices.value.has(device.serial)
          const wasPreviouslyOnline = previouslyOnlineDevices.value.has(device.serial)

          // Device reconnected: was initialized before but wasn't in the last device list
          // This means it was unplugged and plugged back in
          if (wasInitialized && !wasPreviouslyOnline) {
            console.log(
              `[Device] 🔌 Hot-plug detected for ${device.serial}, re-initializing WeCom...`
            )

            // Clear frontend initialized state
            initializedDevices.value.delete(device.serial)
            initializedDevices.value = new Set(initializedDevices.value)

            // Clear backend kefu cache (so WeCom will be launched)
            try {
              await api.clearKefuCache(device.serial)
              console.log(`[Device] Cleared kefu cache for ${device.serial}`)
            } catch (e) {
              console.warn(`[Device] Failed to clear kefu cache for ${device.serial}:`, e)
            }

            // Trigger auto-init to launch WeCom
            autoInitDevice(device.serial)
          }
          // New device or device that hasn't been initialized yet
          else if (
            !device.kefu &&
            !wasInitialized &&
            !initializingDevices.value.has(device.serial)
          ) {
            // Auto-init in the background (don't await)
            autoInitDevice(device.serial)
          }

          // Mark devices with kefu info as initialized
          if (device.kefu) {
            initializedDevices.value.add(device.serial)
          }
        }
      }

      // Update the set of previously online devices for the next fetch
      previouslyOnlineDevices.value = currentOnlineDevices
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to fetch devices'
      backendConnected.value = false
    } finally {
      loading.value = false
    }
  }

  // Auto-initialize a device (launch WeCom and get kefu info)
  async function autoInitDevice(serial: string) {
    if (initializingDevices.value.has(serial) || initializedDevices.value.has(serial)) {
      return
    }

    initializingDevices.value.add(serial)
    initializingDevices.value = new Set(initializingDevices.value)

    console.log(`[Device] Auto-initializing ${serial}...`)

    try {
      const result = await api.initDevice(serial, true)
      if (result.success && result.kefu) {
        console.log(`[Device] ✓ Initialized ${serial}: ${result.kefu.name}`)
        initializedDevices.value.add(serial)
        initializedDevices.value = new Set(initializedDevices.value)

        // Update the device in the list with kefu info
        const deviceIndex = devices.value.findIndex((d) => d.serial === serial)
        if (deviceIndex >= 0) {
          devices.value[deviceIndex] = { ...devices.value[deviceIndex], kefu: result.kefu }
          devices.value = [...devices.value]
        }

        // Update selected device if it's the same
        if (selectedDevice.value?.serial === serial) {
          selectedDevice.value = { ...selectedDevice.value, kefu: result.kefu }
        }
      } else {
        console.warn(`[Device] Failed to initialize ${serial}: ${result.error}`)
      }
    } catch (e) {
      console.error(`[Device] Error initializing ${serial}:`, e)
    } finally {
      initializingDevices.value.delete(serial)
      initializingDevices.value = new Set(initializingDevices.value)
    }
  }

  // Manual device initialization (can be called by UI)
  async function initDevice(
    serial: string,
    launchWecom: boolean = true
  ): Promise<InitDeviceResponse> {
    initializingDevices.value.add(serial)
    initializingDevices.value = new Set(initializingDevices.value)

    try {
      const result = await api.initDevice(serial, launchWecom)
      if (result.success && result.kefu) {
        initializedDevices.value.add(serial)
        initializedDevices.value = new Set(initializedDevices.value)

        // Update the device in the list with kefu info
        const deviceIndex = devices.value.findIndex((d) => d.serial === serial)
        if (deviceIndex >= 0) {
          devices.value[deviceIndex] = { ...devices.value[deviceIndex], kefu: result.kefu }
          devices.value = [...devices.value]
        }

        // Update selected device if it's the same
        if (selectedDevice.value?.serial === serial) {
          selectedDevice.value = { ...selectedDevice.value, kefu: result.kefu }
        }
      }
      return result
    } finally {
      initializingDevices.value.delete(serial)
      initializingDevices.value = new Set(initializingDevices.value)
    }
  }

  function isDeviceInitializing(serial: string): boolean {
    return initializingDevices.value.has(serial)
  }

  function toggleDeviceSelection(serial: string) {
    if (selectedDevices.value.has(serial)) {
      selectedDevices.value.delete(serial)
    } else {
      selectedDevices.value.add(serial)
    }
    // Trigger reactivity
    selectedDevices.value = new Set(selectedDevices.value)
  }

  function selectAll() {
    if (allSelected.value) {
      selectedDevices.value = new Set()
    } else {
      selectedDevices.value = new Set(devices.value.map((d) => d.serial))
    }
  }

  async function startMirror(serial: string) {
    if (!mirrorAvailable.value) {
      console.warn('[Mirror] Electron bridge unavailable; start skipped')
      return false
    }

    try {
      const success = await window.electronAPI!.mirror.start(serial)
      mirrorStatuses.value.set(serial, success)
      mirrorStatuses.value = new Map(mirrorStatuses.value)
      return success
    } catch (e) {
      console.error(`[Mirror] Failed to start mirror for ${serial}:`, e)
      mirrorStatuses.value.set(serial, false)
      mirrorStatuses.value = new Map(mirrorStatuses.value)
      return false
    }
  }

  async function stopMirror(serial: string) {
    if (!mirrorAvailable.value) {
      console.warn('[Mirror] Electron bridge unavailable; stop skipped')
      return false
    }

    try {
      const success = await window.electronAPI!.mirror.stop(serial)
      if (success) {
        mirrorStatuses.value.set(serial, false)
        mirrorStatuses.value = new Map(mirrorStatuses.value)
      }
      return success
    } catch (e) {
      console.error(`[Mirror] Failed to stop mirror for ${serial}:`, e)
      return false
    }
  }

  // Connect to sync status WebSocket for a device
  function connectSyncStatusStream(serial: string) {
    // Don't reconnect if already connected
    if (syncWebsockets.value.has(serial)) {
      const ws = syncWebsockets.value.get(serial)!
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        return
      }
    }

    const ws = new WebSocket(`ws://localhost:8765/ws/sync/${serial}`)

    ws.onopen = () => {
      console.log(`[SyncStatus] Connected for ${serial}`)
    }

    ws.onmessage = (event) => {
      try {
        const status = JSON.parse(event.data) as SyncStatus
        console.log(`[SyncStatus] ${serial}:`, status)
        syncStatuses.value.set(serial, status)
        syncStatuses.value = new Map(syncStatuses.value)

        // Check if this device finished syncing (completed, error, or stopped)
        if (syncingDevicesForFollowup.value.has(serial)) {
          if (
            status.status === 'completed' ||
            status.status === 'error' ||
            status.status === 'stopped'
          ) {
            console.log(`[SyncStatus] Device ${serial} finished with status: ${status.status}`)
            checkAndResumeFollowup()
          }
        }
      } catch (e) {
        console.error('Failed to parse sync status:', e)
      }
    }

    ws.onerror = (error) => {
      console.error(`[SyncStatus] Error for ${serial}:`, error)
    }

    ws.onclose = () => {
      console.log(`[SyncStatus] Disconnected for ${serial}`)
      syncWebsockets.value.delete(serial)
    }

    syncWebsockets.value.set(serial, ws)
  }

  // Disconnect sync status stream
  function disconnectSyncStatusStream(serial: string) {
    const ws = syncWebsockets.value.get(serial)
    if (ws) {
      ws.close()
      syncWebsockets.value.delete(serial)
    }
  }

  async function startSync(serials: string[], options: SyncOptions = {}) {
    for (const serial of serials) {
      syncStatuses.value.set(serial, {
        status: 'starting',
        progress: 0,
        message: options.send_via_sidecar
          ? 'Initializing sync with sidecar...'
          : 'Initializing sync...',
      })
      // Connect to sync status WebSocket for real-time updates
      connectSyncStatusStream(serial)
    }
    syncStatuses.value = new Map(syncStatuses.value)

    try {
      await api.startSync(serials, options)
    } catch (e) {
      for (const serial of serials) {
        syncStatuses.value.set(serial, {
          status: 'error',
          progress: 0,
          message: e instanceof Error ? e.message : 'Failed to start sync',
        })
      }
      syncStatuses.value = new Map(syncStatuses.value)
    }
  }

  async function stopSync(serial: string) {
    // Disconnect WebSocket FIRST to prevent status updates from overriding
    disconnectSyncStatusStream(serial)

    // Update status immediately for responsive UI
    syncStatuses.value.set(serial, {
      status: 'stopped',
      progress: syncStatuses.value.get(serial)?.progress || 0,
      message: 'Stopping sync...',
    })
    syncStatuses.value = new Map(syncStatuses.value)

    try {
      await api.stopSync(serial)
      // Update status after successful stop
      syncStatuses.value.set(serial, {
        status: 'stopped',
        progress: syncStatuses.value.get(serial)?.progress || 0,
        message: 'Sync stopped',
      })
      syncStatuses.value = new Map(syncStatuses.value)
    } catch (e) {
      console.error('Failed to stop sync:', e)
      // Update UI to stopped state even on error
      syncStatuses.value.set(serial, {
        status: 'stopped',
        progress: syncStatuses.value.get(serial)?.progress || 0,
        message: 'Sync stopped (with error)',
      })
      syncStatuses.value = new Map(syncStatuses.value)
    }
  }

  async function pauseSync(serial: string) {
    try {
      await api.pauseSync(serial)
      // Update status immediately for responsive UI
      syncStatuses.value.set(serial, {
        status: 'paused',
        progress: syncStatuses.value.get(serial)?.progress || 0,
        message: 'Sync paused',
      })
      syncStatuses.value = new Map(syncStatuses.value)
    } catch (e) {
      console.error('Failed to pause sync:', e)
    }
  }

  async function resumeSync(serial: string) {
    try {
      await api.resumeSync(serial)
      // Update status immediately for responsive UI
      syncStatuses.value.set(serial, {
        status: 'running',
        progress: syncStatuses.value.get(serial)?.progress || 0,
        message: 'Sync resumed',
      })
      syncStatuses.value = new Map(syncStatuses.value)
    } catch (e) {
      console.error('Failed to resume sync:', e)
    }
  }

  // Clear sync status for a device (reset to idle)
  function clearSyncStatus(serial: string) {
    syncStatuses.value.delete(serial)
    syncStatuses.value = new Map(syncStatuses.value)
    disconnectSyncStatusStream(serial)
  }

  function updateSyncStatus(serial: string, status: SyncStatus) {
    syncStatuses.value.set(serial, status)
    syncStatuses.value = new Map(syncStatuses.value)
  }

  function getSyncStatus(serial: string): SyncStatus | undefined {
    return syncStatuses.value.get(serial)
  }

  function getMirrorStatus(serial: string): boolean {
    return mirrorStatuses.value.get(serial) || false
  }

  async function fetchDeviceDetail(serial: string) {
    detailLoading.value = true
    detailError.value = null
    try {
      const device = await api.getDevice(serial)
      selectedDevice.value = device

      // Keep list in sync
      const index = devices.value.findIndex((d) => d.serial === serial)
      if (index >= 0) {
        const updated = [...devices.value]
        updated[index] = { ...updated[index], ...device }
        devices.value = updated
      } else {
        devices.value = [...devices.value, device]
      }

      return device
    } catch (e) {
      detailError.value = e instanceof Error ? e.message : 'Failed to load device details'
      throw e
    } finally {
      detailLoading.value = false
    }
  }

  function clearSelectedDevice() {
    selectedDevice.value = null
    detailError.value = null
  }

  // Pause followup system before starting sync
  async function pauseFollowupForSync(serials: string[]) {
    try {
      console.log('[Followup] Pausing for sync, devices:', serials)
      syncingDevicesForFollowup.value = new Set(serials)
      followupPausedForSync.value = true

      // NEW: Pause each device individually using multi-device API
      for (const serial of serials) {
        try {
          const response = await fetch(
            `http://localhost:8765/api/realtime/device/${serial}/pause`,
            {
              method: 'POST',
            }
          )
          if (response.ok) {
            const data = await response.json()
            console.log(`[Followup] Paused device ${serial}:`, data)
          }
        } catch (error) {
          console.warn(`[Followup] Failed to pause device ${serial}:`, error)
        }
      }

      console.log('[Followup] All devices paused for sync')
    } catch (error) {
      console.warn('[Followup] Failed to pause:', error)
    }
  }

  // Check if all syncs are finished and resume followup
  async function checkAndResumeFollowup() {
    if (!followupPausedForSync.value) return
    if (syncingDevicesForFollowup.value.size === 0) return

    // Check if all tracked devices are finished
    let allFinished = true
    for (const serial of syncingDevicesForFollowup.value) {
      const status = syncStatuses.value.get(serial)
      if (status) {
        const isFinished =
          status.status === 'completed' || status.status === 'error' || status.status === 'stopped'
        if (!isFinished) {
          console.log(`[Followup] Device ${serial} still running: ${status.status}`)
          allFinished = false
          break
        }
      }
    }

    if (allFinished) {
      console.log('[Followup] All syncs finished, resuming followup system')
      await resumeFollowupAfterSync()
    }
  }

  // Resume followup system after sync
  async function resumeFollowupAfterSync(retryCount = 0) {
    if (!followupPausedForSync.value) return

    const maxRetries = 3

    try {
      console.log(`[Followup] Calling resume API (attempt ${retryCount + 1}/${maxRetries + 1})...`)

      // NEW: Resume each device individually using multi-device API
      const serialsToResume = Array.from(syncingDevicesForFollowup.value)
      let resumedCount = 0

      for (const serial of serialsToResume) {
        try {
          const response = await fetch(
            `http://localhost:8765/api/realtime/device/${serial}/resume`,
            {
              method: 'POST',
            }
          )

          if (response.ok) {
            const data = await response.json()
            if (data.success) {
              resumedCount++
              console.log(`[Followup] Resumed device ${serial}:`, data)
            }
          }
        } catch (error) {
          console.warn(`[Followup] Failed to resume device ${serial}:`, error)
        }
      }

      // Clear tracking state
      syncingDevicesForFollowup.value.clear()
      followupPausedForSync.value = false

      console.log(
        `[Followup] ✅ Resumed ${resumedCount}/${serialsToResume.length} devices successfully`
      )
    } catch (error) {
      console.warn('[Followup] Failed to resume:', error)
      if (retryCount < maxRetries) {
        console.log('[Followup] Retrying in 1 second...')
        setTimeout(() => resumeFollowupAfterSync(retryCount + 1), 1000)
      }
    }
  }

  return {
    // State
    devices,
    selectedDevices,
    syncStatuses,
    mirrorStatuses,
    loading,
    error,
    backendConnected,
    selectedDevice,
    detailLoading,
    detailError,
    initializedDevices,
    initializingDevices,
    syncingDevicesForFollowup,
    followupPausedForSync,

    // Getters
    selectedDeviceList,
    hasSelectedDevices,
    allSelected,
    mirrorAvailable,

    // Actions
    fetchDevices,
    toggleDeviceSelection,
    selectAll,
    startMirror,
    stopMirror,
    startSync,
    stopSync,
    pauseSync,
    resumeSync,
    updateSyncStatus,
    getSyncStatus,
    getMirrorStatus,
    clearSyncStatus,
    connectSyncStatusStream,
    disconnectSyncStatusStream,
    fetchDeviceDetail,
    clearSelectedDevice,
    initDevice,
    autoInitDevice,
    isDeviceInitializing,
    pauseFollowupForSync,
    checkAndResumeFollowup,
    resumeFollowupAfterSync,
  }
})
