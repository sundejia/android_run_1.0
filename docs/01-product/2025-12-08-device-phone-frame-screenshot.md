# Device Phone Frame with Live Screenshot

**Date**: 2025-12-08  
**Status**: ✅ Complete  
**Components**: Backend (devices.py), Frontend (api.ts, DeviceDetailView.vue, index.html)

## Overview

This feature adds a simulated phone frame to the device detail view that displays a live screenshot of the connected Android device's screen. The phone frame shows the actual device screen content and supports both manual refresh and auto-refresh modes.

## Problem Statement

Previously:

1. Users had no visual preview of what was happening on the connected device
2. To see the device screen, users had to use external screen mirroring tools
3. No quick way to verify device state without opening the sidecar view

## Solution

1. **Backend screenshot endpoint**: New API endpoint that captures the device screen using ADB
2. **Phone frame UI**: Realistic phone bezel design with speaker, screen area, and home bar
3. **Live refresh**: Manual and automatic screenshot refresh capabilities
4. **CSP update**: Content Security Policy updated to allow loading images from the backend

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Frontend (Vue.js)                             │
│  DeviceDetailView shows phone frame with screenshot             │
│  api.getScreenshotUrl(serial) returns image URL                 │
│  Auto-refresh interval (3 seconds) optional                     │
└────────────────────────┬────────────────────────────────────────┘
                         │ GET /devices/{serial}/screenshot
┌────────────────────────▼────────────────────────────────────────┐
│                    Backend (FastAPI)                             │
│  devices.py: /screenshot endpoint                               │
│  Uses AdbTools.take_screenshot() → Returns PNG binary           │
└────────────────────────┬────────────────────────────────────────┘
                         │ ADB screencap command
┌────────────────────────▼────────────────────────────────────────┐
│                    Android Device                                │
│  Screen captured via adb exec-out screencap -p                  │
└─────────────────────────────────────────────────────────────────┘
```

## API Changes

### New Endpoint

#### `GET /devices/{serial}/screenshot`

Capture a screenshot of the device screen.

**Response:**

- Content-Type: `image/png`
- Body: PNG binary data

**Headers:**

```
Cache-Control: no-cache, no-store, must-revalidate
Pragma: no-cache
Expires: 0
```

**Error Response:**

```json
{
  "detail": "Failed to take screenshot: <error message>"
}
```

## Frontend Implementation

### API Service (`api.ts`)

```typescript
// Screenshot endpoint - returns URL with cache-busting timestamp
getScreenshotUrl(serial: string): string {
  return `${this.baseUrl}/devices/${serial}/screenshot?t=${Date.now()}`
}
```

### DeviceDetailView.vue

#### New State Variables

```typescript
const screenshotUrl = ref<string | null>(null)
const screenshotLoading = ref(false)
const screenshotError = ref<string | null>(null)
let screenshotRefreshInterval: ReturnType<typeof setInterval> | null = null
```

#### New Functions

- `refreshScreenshot()` - Manually refresh the screenshot
- `onScreenshotLoad()` - Handle successful image load
- `onScreenshotError()` - Handle image load failure
- `startAutoRefresh()` - Enable 3-second auto-refresh
- `stopAutoRefresh()` - Disable auto-refresh

#### Layout Changes

The info cards grid now uses `flex-row` layout:

- Left side: Device info cards in a responsive grid
- Right side: Phone frame with screenshot

```vue
<div class="flex flex-row gap-4">
  <!-- Device info cards -->
  <div class="flex-1 min-w-0 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
    <!-- Info cards... -->
  </div>

  <!-- Phone frame -->
  <div class="flex-shrink-0 flex flex-col items-center">
    <div class="phone-frame">
      <!-- Phone bezel with screenshot -->
    </div>
  </div>
</div>
```

### Phone Frame UI

The phone frame includes:

1. **Outer bezel**: Dark gradient with realistic shadows
2. **Speaker**: Small bar at the top simulating phone speaker
3. **Screen area**: Contains the screenshot image
4. **Home bar**: Gesture indicator at the bottom
5. **Controls**: Refresh and Auto-refresh buttons

#### Placeholder States

- **Offline**: Shows 📵 icon with "Device Offline" message
- **Loading**: Shows 📱 icon with "Loading..." message
- **Error**: Shows ⚠️ icon with error message
- **No screenshot**: Shows 📱 icon with "Take screenshot" button

### Content Security Policy

Updated `index.html` CSP to allow images from localhost:

```html
<meta
  http-equiv="Content-Security-Policy"
  content="
  default-src 'self'; 
  script-src 'self'; 
  style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; 
  font-src 'self' https://fonts.gstatic.com; 
  img-src 'self' http://localhost:* data:; 
  connect-src 'self' ws://localhost:* http://localhost:*
"
/>
```

**Key change**: Added `img-src 'self' http://localhost:* data:;` to allow loading images from the backend API.

## Styling

### Phone Frame CSS

```css
.phone-frame {
  perspective: 1000px;
}

.phone-bezel {
  width: 180px;
  height: 380px;
  background: linear-gradient(145deg, #2a2a2a 0%, #1a1a1a 50%, #0f0f0f 100%);
  border-radius: 28px;
  padding: 12px 8px 20px 8px;
  box-shadow:
    0 0 0 2px #3a3a3a,
    0 0 0 4px #1a1a1a,
    0 10px 40px rgba(0, 0, 0, 0.5),
    inset 0 1px 0 rgba(255, 255, 255, 0.1);
}

.phone-screen {
  width: 100%;
  height: 320px;
  background: #0a0a0a;
  border-radius: 8px;
  overflow: hidden;
}

.phone-screenshot {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: top;
}
```

### Responsive Design

- Default: 180x380px phone frame
- Below 1280px: 160x340px phone frame

## User Experience

### Before

- No visual preview of device screen in device detail view
- Had to use external tools or sidecar to see device state

### After

- Live phone frame showing actual device screen
- Manual refresh with one click
- Auto-refresh mode for continuous monitoring
- Clear status indicators for offline/loading/error states

## Files Changed

| File                             | Changes                                     |
| -------------------------------- | ------------------------------------------- |
| `backend/routers/devices.py`     | Added `/screenshot` endpoint                |
| `src/services/api.ts`            | Added `getScreenshotUrl()` method           |
| `src/views/DeviceDetailView.vue` | Added phone frame UI, screenshot logic, CSS |
| `index.html`                     | Updated CSP to allow images from localhost  |

## Related

- **Device Detail View**: Main view where phone frame is displayed
- **ADB Service**: Uses `take_screenshot()` from droidrun library

## Known Limitations

1. Screenshot takes ~1-2 seconds to capture and transfer
2. Auto-refresh with 3-second interval may increase network/CPU usage
3. Large screenshots (1080x2340) are transferred in full each time
4. No touch interaction on the screenshot (use mirroring for that)

## Future Improvements

1. Thumbnail mode with click-to-expand
2. Screenshot caching to reduce bandwidth
3. WebSocket streaming for real-time updates
4. Click-to-interact via coordinate mapping
