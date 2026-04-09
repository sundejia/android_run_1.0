# Device Auto-Initialization with WeCom Launch and Kefu Caching

**Date**: 2025-12-08  
**Status**: ✅ Complete  
**Components**: Backend (devices.py), Frontend (api.ts, devices.ts, DeviceCard.vue, DeviceDetailView.vue, SidecarView.vue)

## Overview

This feature automatically initializes devices when they connect by launching WeCom and extracting the 客服 (kefu/customer service rep) information. The kefu info is cached and displayed consistently across all views without dynamic re-extraction.

## Problem Statement

Previously:

1. WeCom had to be manually launched on devices
2. Kefu information was extracted dynamically from the UI tree on every sidecar state refresh
3. Dynamic extraction sometimes picked up wrong text from the conversation (e.g., message content instead of kefu name)
4. Kefu info in sidecar showed "Unknown" or incorrect data

## Solution

1. **Auto-init on device connect**: When devices are discovered, automatically launch WeCom and extract kefu info
2. **Backend caching**: Store kefu info per device serial, include it in all device API responses
3. **Frontend caching**: Cache kefu in device store and sidecar panel state
4. **Stable display**: Sidecar uses cached kefu info (set once) instead of dynamic extraction

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Frontend (Vue.js)                             │
│  fetchDevices() → auto-init devices without kefu                │
│  DeviceCard/DetailView shows cached kefu                        │
│  SidecarView uses cachedKefu (not dynamic state)                │
└────────────────────────┬────────────────────────────────────────┘
                         │ POST /devices/{serial}/init
┌────────────────────────▼────────────────────────────────────────┐
│                    Backend (FastAPI)                             │
│  devices.py: /init endpoint, _kefu_cache dict                   │
│  Launch WeCom → Extract kefu → Cache result                     │
└────────────────────────┬────────────────────────────────────────┘
                         │ Uses get_kefu_name.py
┌────────────────────────▼────────────────────────────────────────┐
│               get_kefu_name.py                                   │
│  extract_kefu_from_tree() - parses UI tree for kefu info        │
└─────────────────────────────────────────────────────────────────┘
```

## API Changes

### New Endpoints

#### `POST /devices/{serial}/init`

Initialize a device by launching WeCom and extracting kefu info.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `launch_wecom` | boolean | `true` | Whether to launch WeCom before extraction |

**Response:**

```json
{
  "success": true,
  "kefu": {
    "name": "wyd",
    "department": "302实验室",
    "verification_status": "未认证"
  },
  "wecom_launched": true,
  "error": null
}
```

#### `DELETE /devices/{serial}/kefu-cache`

Clear cached kefu info for a device (for re-initialization).

### Modified Responses

All device endpoints now include optional `kefu` field:

- `GET /devices` - List devices with kefu info
- `GET /devices/{serial}` - Device detail with kefu info
- `POST /devices/refresh` - Refresh with kefu info

## Data Models

### Backend (`devices.py`)

```python
class KefuInfoModel(BaseModel):
    """Kefu (customer service rep) information model."""
    name: str
    department: Optional[str] = None
    verification_status: Optional[str] = None

class DeviceResponse(BaseModel):
    # ... existing fields ...
    kefu: Optional[KefuInfoModel] = None
```

### Frontend (`api.ts`)

```typescript
export interface DeviceKefu {
  name: string
  department?: string | null
  verification_status?: string | null
}

export interface Device {
  // ... existing fields ...
  kefu?: DeviceKefu | null
}

export interface InitDeviceResponse {
  success: boolean
  kefu?: DeviceKefu | null
  wecom_launched: boolean
  error?: string | null
}
```

## Frontend Integration

### Device Store (`devices.ts`)

New state:

```typescript
const initializedDevices = ref<Set<string>>(new Set())
const initializingDevices = ref<Set<string>>(new Set())
```

New functions:

- `autoInitDevice(serial)` - Background auto-initialization
- `initDevice(serial, launchWecom)` - Manual initialization
- `isDeviceInitializing(serial)` - Check init status

Modified `fetchDevices()`:

- After fetching devices, auto-init any online device without kefu info
- Updates device list with kefu info when init completes

### DeviceCard Component

Shows kefu info when available:

```vue
<div v-if="device.kefu" class="mb-4 p-2 bg-wecom-dark/50 border border-wecom-border rounded-lg">
  <div class="flex items-center gap-2 text-xs">
    <span class="text-wecom-primary">👤</span>
    <span class="font-medium text-wecom-text">{{ device.kefu.name }}</span>
    <span v-if="device.kefu.department" class="text-wecom-muted">· {{ device.kefu.department }}</span>
    <span v-if="device.kefu.verification_status" class="text-wecom-muted text-[10px] px-1.5 py-0.5 bg-wecom-surface rounded">
      {{ device.kefu.verification_status }}
    </span>
  </div>
</div>
```

### DeviceDetailView

- Prominent kefu info card in device details grid
- "Initialize WeCom" button for manual initialization
- Error display for initialization failures

### SidecarView

Key changes for stable kefu display:

1. Added `cachedKefu` field to `PanelState` type
2. Set `cachedKefu` from device store when panel is added
3. Watch for device store updates to populate kefu
4. Template uses `cachedKefu` instead of `state.kefu`

```typescript
// In addPanel()
const device = deviceStore.devices.find((d) => d.serial === serial)
if (device?.kefu && !panel.cachedKefu) {
  panel.cachedKefu = device.kefu
}

// Watch for device store updates
watch(
  () => deviceStore.devices,
  (devices) => {
    for (const serial of panels.value) {
      const panel = sidecars[serial]
      if (panel && !panel.cachedKefu) {
        const device = devices.find((d) => d.serial === serial)
        if (device?.kefu) {
          panel.cachedKefu = device.kefu
        }
      }
    }
  },
  { deep: true }
)
```

## Kefu Extraction Logic

Uses `get_kefu_name.py`'s `extract_kefu_from_tree()` function:

1. **Collect text nodes** from UI tree in left panel area (x < 500)
2. **Filter out** navigation elements (消息, 全部, 私聊, etc.)
3. **Identify department** by patterns (实验室, 部门, etc.)
4. **Identify verification status** (未认证, 已认证)
5. **Score candidates** by position (y: 150-400) and text height
6. **Return best match** as `KefuInfo` dataclass

## User Experience

### Before

- Kefu in sidecar: "Unknown" or random conversation text
- No kefu info in device cards
- Manual WeCom launch required

### After

- Kefu in sidecar: "wyd · 302实验室 · 未认证" (stable)
- Kefu info shown in device cards
- WeCom auto-launches on device connect
- Manual "Initialize WeCom" button available if needed

## Files Changed

| File                             | Changes                                                 |
| -------------------------------- | ------------------------------------------------------- |
| `backend/routers/devices.py`     | Added init endpoint, kefu cache, updated response model |
| `src/services/api.ts`            | Added DeviceKefu, InitDeviceResponse, API methods       |
| `src/stores/devices.ts`          | Added auto-init logic, init state tracking              |
| `src/components/DeviceCard.vue`  | Added kefu info display                                 |
| `src/views/DeviceDetailView.vue` | Added kefu card, init button                            |
| `src/views/SidecarView.vue`      | Cache kefu from device store, not dynamic state         |

## Related

- **[Sidecar Kefu Unknown Bug](../04-bugs-and-fixes/fixed/2025/12-07-sidecar-kefu-unknown.md)**: Previous fix attempted dynamic extraction
- **`get_kefu_name.py`**: Core extraction logic used by init endpoint

## Known Limitations

1. ~~WeCom must be in a state where kefu info is visible (Messages tab)~~ ✅ **Resolved**: Now automatically verified and ensured via [Messages View Verification](2025-12-16-device-init-messages-view-verification.md)
2. First extraction may fail if app hasn't fully loaded
3. Kefu info won't update if account changes (need manual re-init)

## Enhancements

- **[2025-12-16] Messages View Verification**: Integrated automatic verification and recovery to ensure WeCom is on Messages view before extraction. See [Device Initialization with Messages View Verification](2025-12-16-device-init-messages-view-verification.md) for details.
