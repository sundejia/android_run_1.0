import { describe, expect, it, vi } from 'vitest'
import type { SidecarBlockPanelState } from './sidecarBlock'
import {
  getActiveConversationTarget,
  getBlockButtonTitle,
  hasActiveConversationTarget,
  toggleBlockUserForPanel,
} from './sidecarBlock'

function createPanel(
  overrides: Partial<SidecarBlockPanelState> = {}
): SidecarBlockPanelState {
  return {
    queueMode: false,
    currentQueuedMessage: null,
    state: {
      in_conversation: true,
      conversation: {
        contact_name: 'Alice',
        channel: '@WeChat',
      },
    },
    isBlacklisted: false,
    statusMessage: null,
    ...overrides,
  }
}

const t = (_key: string, vars?: Record<string, unknown>, fallback?: string) => {
  if (!fallback) return _key
  return vars?.name ? fallback.replace('{name}', String(vars.name)) : fallback
}

describe('sidecarBlock helpers', () => {
  it('prefers queued message target over stale sidecar conversation', () => {
    const panel = createPanel({
      queueMode: true,
      currentQueuedMessage: {
        id: 'msg-1',
        serial: 'SERIAL-1',
        customerName: 'Queued User',
        channel: '@Queue',
        message: 'hello',
        timestamp: Date.now(),
        status: 'ready',
        source: 'followup',
      },
      state: {
        in_conversation: false,
        conversation: {
          contact_name: null,
          channel: null,
        },
      },
    })

    expect(getActiveConversationTarget(panel)).toEqual({
      contactName: 'Queued User',
      channel: '@Queue',
    })
    expect(hasActiveConversationTarget(panel)).toBe(true)
  })

  it('returns the correct tooltip for blocked and unblocked states', () => {
    expect(getBlockButtonTitle(false, t)).toBe('Click to block this user')
    expect(getBlockButtonTitle(true, t)).toBe('Click to allow this user')
  })
})

describe('toggleBlockUserForPanel', () => {
  it('blocks the queued user and auto-skips the current task', async () => {
    const panel = createPanel({
      queueMode: true,
      currentQueuedMessage: {
        id: 'msg-1',
        serial: 'SERIAL-1',
        customerName: 'Queued User',
        channel: '@Queue',
        message: 'hello',
        timestamp: Date.now(),
        status: 'ready',
        source: 'followup',
      },
      state: {
        in_conversation: false,
        conversation: {
          contact_name: null,
          channel: null,
        },
      },
    })
    const apiClient = {
      toggleBlacklist: vi.fn().mockResolvedValue({
        success: true,
        message: 'ok',
        is_blacklisted: true,
      }),
    }
    const addDeviceLog = vi.fn()
    const skipCurrentUser = vi.fn().mockResolvedValue(undefined)
    const refreshBlacklistStatus = vi.fn().mockResolvedValue(undefined)

    await toggleBlockUserForPanel({
      serial: 'SERIAL-1',
      panel,
      apiClient,
      t,
      addDeviceLog,
      skipCurrentUser,
      refreshBlacklistStatus,
    })

    expect(apiClient.toggleBlacklist).toHaveBeenCalledWith({
      device_serial: 'SERIAL-1',
      customer_name: 'Queued User',
      customer_channel: '@Queue',
    })
    expect(panel.isBlacklisted).toBe(true)
    expect(panel.statusMessage).toBe('Blocked Queued User')
    expect(skipCurrentUser).toHaveBeenCalledWith('SERIAL-1')
    expect(refreshBlacklistStatus).toHaveBeenCalledWith('SERIAL-1')
    expect(addDeviceLog).toHaveBeenCalledWith(
      'SERIAL-1',
      'INFO',
      '[Block] Blocked user: Queued User'
    )
  })

  it('allows a blocked user without auto-skipping', async () => {
    const panel = createPanel({
      isBlacklisted: true,
      state: {
        in_conversation: true,
        conversation: {
          contact_name: 'Blocked User',
          channel: '@WeChat',
        },
      },
    })
    const apiClient = {
      toggleBlacklist: vi.fn().mockResolvedValue({
        success: true,
        message: 'ok',
        is_blacklisted: false,
      }),
    }
    const addDeviceLog = vi.fn()
    const skipCurrentUser = vi.fn().mockResolvedValue(undefined)
    const refreshBlacklistStatus = vi.fn().mockResolvedValue(undefined)

    await toggleBlockUserForPanel({
      serial: 'SERIAL-2',
      panel,
      apiClient,
      t,
      addDeviceLog,
      skipCurrentUser,
      refreshBlacklistStatus,
    })

    expect(panel.isBlacklisted).toBe(false)
    expect(panel.statusMessage).toBe('Allowed Blocked User')
    expect(skipCurrentUser).not.toHaveBeenCalled()
    expect(refreshBlacklistStatus).toHaveBeenCalledWith('SERIAL-2')
    expect(addDeviceLog).toHaveBeenCalledWith(
      'SERIAL-2',
      'INFO',
      '[Block] Allowed user: Blocked User'
    )
  })
})
