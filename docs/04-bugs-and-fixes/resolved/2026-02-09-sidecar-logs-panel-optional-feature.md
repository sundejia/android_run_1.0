# Sidecar Logs Panel Optional Feature

> Date: 2026-02-09
> Status: ✅ Implemented
> Feature Type: Enhancement
> Related: Sidecar View, Settings System

## Summary

Added a new setting to optionally show/hide the real-time logs panel in Sidecar view. This allows users to disable the logs panel on slower devices to improve performance.

## Motivation

### Why This Feature Was Needed

1. **Performance on slower devices**: The real-time logs panel can consume significant resources on older or slower devices
2. **User preference**: Some users prefer a cleaner interface without logs
3. **Flexibility**: Advanced users may want logs for debugging, while production users may not need them

## Implementation

### Settings Database

**Files Modified:**
- `wecom-desktop/backend/services/settings/defaults.py`
- `wecom-desktop/backend/services/settings/models.py`
- `wecom-desktop/src/stores/settings.ts`

**Setting Added:**

| Backend Key | Frontend Key | Type | Default | Description |
|-------------|--------------|------|---------|-------------|
| `show_logs` | `sidecarShowLogs` | boolean | `true` | Show logs panel in Sidecar view |

### Frontend Changes

**Files Modified:**
- `wecom-desktop/src/views/SettingsView.vue` - Added toggle control in settings
- `wecom-desktop/src/views/SidecarView.vue` - Implemented conditional rendering

**Settings UI:**

```vue
<!-- Show Logs Panel -->
<div class="flex items-center justify-between">
  <div>
    <label class="text-sm font-medium text-wecom-text">Show Logs Panel</label>
    <p class="text-xs text-wecom-muted">
      Display real-time logs in Sidecar view. Disable to improve performance on slower devices.
    </p>
  </div>
  <label class="relative inline-flex items-center cursor-pointer">
    <input
      v-model="settings.sidecarShowLogs"
      type="checkbox"
      class="sr-only peer"
      @change="saveSettings"
    />
    <div class="w-11 h-6 bg-wecom-surface peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-wecom-primary"></div>
  </label>
</div>
```

**Sidecar View Changes:**

1. **Conditional Rendering**:
```vue
<!-- Logs Section (controlled by settings) -->
<div
  v-if="showLogs"
  class="shrink-0 border-t border-wecom-border flex flex-col"
  :style="{ height: sidecars[serial]?.logsCollapsed ? '40px' : '200px' }"
>
  <!-- logs content -->
</div>
```

2. **Conditional Log Stream Connection**:
```javascript
const showLogs = computed(() => settings.value.sidecarShowLogs)

function addPanel(serial: string, setFocus = true) {
  // ... existing code ...
  startPolling(serial)
  // Only connect log stream if logs panel is enabled
  if (showLogs.value) {
    logStore.connectLogStream(serial)
  }
}

// Watch for setting changes to connect/disconnect existing panels
watch(showLogs, (newVal) => {
  for (const serial of panels.value) {
    if (newVal) {
      logStore.connectLogStream(serial)
    } else {
      logStore.disconnectLogStream(serial)
    }
  }
})
```

## Behavior

### When Logs Are Enabled (Default)

- Logs panel is visible at the bottom of each sidecar
- WebSocket log streams are connected for each device
- Real-time logs are displayed
- Logs can be collapsed to 40px height

### When Logs Are Disabled

- Logs panel is completely hidden (not just collapsed)
- WebSocket log streams are disconnected (saves bandwidth and resources)
- Sidecar view has more vertical space available
- Settings can be changed at runtime to toggle logs

## Testing

- Verified toggle works in settings UI
- Confirmed logs panel shows/hides correctly
- Tested that changing setting affects both new and existing panels
- Verified WebSocket connections are properly managed

## Benefits

1. **Performance improvement**: Devices with limited resources can disable logs
2. **Cleaner UI**: Users who don't need logs get a simpler interface
3. **On-demand debugging**: Users can enable logs when needed for troubleshooting
4. **No breaking changes**: Default behavior (logs enabled) remains the same

## Related Issues

- None (new feature)

## Future Enhancements

Possible future improvements:
- Per-device log visibility settings
- Log level filtering (info, warning, error only)
- Log export functionality
- Search within logs

## References

- Code: `wecom-desktop/src/views/SidecarView.vue:80-82` (computed)
- Code: `wecom-desktop/src/views/SidecarView.vue:1003-1007` (conditional connect)
- Code: `wecom-desktop/src/views/SidecarView.vue:1795-1806` (watch handler)
- Code: `wecom-desktop/src/views/SidecarView.vue:2406` (v-if directive)
- Code: `wecom-desktop/src/views/SettingsView.vue:1362-1383` (settings UI)
