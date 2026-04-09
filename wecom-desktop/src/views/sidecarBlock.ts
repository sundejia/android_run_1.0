import type {
  BlacklistCheckRequest,
  BlacklistToggleResponse,
  QueuedMessage,
  SidecarState,
} from '../services/api'

type TranslateFn = (
  key: string,
  vars?: Record<string, unknown>,
  fallback?: string
) => string

export type SidecarBlockPanelState = {
  queueMode: boolean
  currentQueuedMessage: QueuedMessage | null
  state: SidecarState | null
  isBlacklisted: boolean | null
  statusMessage: string | null
}

export type SidecarBlockApi = {
  toggleBlacklist(data: BlacklistCheckRequest): Promise<BlacklistToggleResponse>
}

export type SidecarLogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR'

export function getActiveConversationTarget(panel: SidecarBlockPanelState): {
  contactName: string | null
  channel: string | null
} {
  if (panel.queueMode && panel.currentQueuedMessage) {
    return {
      contactName: panel.currentQueuedMessage.customerName || null,
      channel: panel.currentQueuedMessage.channel || null,
    }
  }

  return {
    contactName: panel.state?.conversation?.contact_name || null,
    channel: panel.state?.conversation?.channel || null,
  }
}

export function hasActiveConversationTarget(panel: SidecarBlockPanelState): boolean {
  return Boolean(getActiveConversationTarget(panel).contactName)
}

export function getBlockButtonTitle(
  isBlacklisted: boolean | null,
  t: TranslateFn
): string {
  return isBlacklisted === true
    ? t('sidecar.allowed_title', {}, 'Click to allow this user')
    : t('sidecar.block_title', {}, 'Click to block this user')
}

export async function toggleBlockUserForPanel({
  serial,
  panel,
  apiClient,
  t,
  addDeviceLog,
  skipCurrentUser,
  refreshBlacklistStatus,
}: {
  serial: string
  panel: SidecarBlockPanelState
  apiClient: SidecarBlockApi
  t: TranslateFn
  addDeviceLog: (serial: string, level: SidecarLogLevel, message: string) => void
  skipCurrentUser: (serial: string) => Promise<void>
  refreshBlacklistStatus: (serial: string) => Promise<void>
}): Promise<void> {
  const { contactName, channel } = getActiveConversationTarget(panel)

  if (!contactName) {
    panel.statusMessage = t('sidecar.block_no_conversation', {}, 'No active conversation to block')
    return
  }

  const isCurrentlyBlocked = panel.isBlacklisted === true
  panel.statusMessage = isCurrentlyBlocked
    ? t('sidecar.allowing', {}, 'Allowing...')
    : t('sidecar.blocking', {}, 'Blocking...')

  try {
    const result = await apiClient.toggleBlacklist({
      device_serial: serial,
      customer_name: contactName,
      customer_channel: channel || undefined,
    })

    if (result.success) {
      panel.isBlacklisted = result.is_blacklisted

      if (result.is_blacklisted) {
        panel.statusMessage = t(
          'sidecar.block_success',
          { name: contactName },
          `Blocked ${contactName}`
        )
        addDeviceLog(serial, 'INFO', `[Block] Blocked user: ${contactName}`)
        await skipCurrentUser(serial)
      } else {
        panel.statusMessage = t(
          'sidecar.allow_success',
          { name: contactName },
          `Allowed ${contactName}`
        )
        addDeviceLog(serial, 'INFO', `[Block] Allowed user: ${contactName}`)
      }

      await refreshBlacklistStatus(serial)
      return
    }

    panel.statusMessage =
      result.message || t('sidecar.block_failed', {}, 'Failed to toggle block status')
    panel.isBlacklisted = null
  } catch (error) {
    panel.statusMessage =
      error instanceof Error ? error.message : t('sidecar.block_failed', {}, 'Toggle request failed')
    addDeviceLog(serial, 'ERROR', `[Block] Toggle failed: ${error}`)
    panel.isBlacklisted = null
  }
}
