# Streamers Implementation Fixes

> **Date**: 2025-12-11  
> **Status**: ✅ Fixed  
> **Category**: Bug

## Overview

Multiple issues discovered and fixed during the implementation of the Streamers Database feature.

---

## Bug 1: sqlite3.Row AttributeError

### Symptoms

```
AttributeError: 'sqlite3.Row' object has no attribute 'get'
GET /streamers/{id} returning 500 Internal Server Error
```

### Root Cause

Used `.get()` method on `sqlite3.Row` objects which don't support that method (only dict-like bracket access `row["key"]`).

### Fix

Created helper function `_row_get()` to safely access row values:

```python
def _row_get(row: Any, key: str, default: Any = None) -> Any:
    """Safely get a value from a sqlite3.Row object."""
    if row is None:
        return default
    try:
        return row[key] if key in row.keys() else default
    except (KeyError, TypeError):
        return default
```

Replaced all `row.get("key")` calls with `_row_get(row, "key")`.

### Files Changed

- `wecom-desktop/backend/routers/streamers.py`

---

## Bug 2: Streamers Avatar Display

### Symptoms

- Avatars in `/conversations` page displayed correctly from local files
- Avatars in `/streamers` page showed placeholder images from `ui-avatars.com`

### Root Cause

`StreamersListView.vue` and `StreamerDetailView.vue` used a local `getAvatarUrl()` function that fell back to external API instead of using the project's `avatarUrlFromSeed()` utility.

### Fix

Updated both views to import and use `avatarUrlFromSeed` from `utils/avatars.ts`:

```typescript
import { avatarUrlFromSeed } from '../utils/avatars'

function getAvatarUrl(streamer: { avatar_url: string | null; name: string }) {
  if (streamer.avatar_url) {
    return streamer.avatar_url
  }
  return avatarUrlFromSeed(streamer.name)
}
```

### Files Changed

- `wecom-desktop/src/views/StreamersListView.vue`
- `wecom-desktop/src/views/StreamerDetailView.vue`

---

## Bug 3: Radar Chart Tooltip Blinking

### Symptoms

When hovering over points in the PersonalityRadar chart, the tooltip would blink/flicker rapidly, making it unreadable.

### Root Cause

1. Tooltip was positioned based on mouse event coordinates which changed constantly
2. Tooltip could receive pointer events, causing mouse-enter/leave loops
3. Small hover target (radius 5) made it hard to stay on the point

### Fix

1. Changed to index-based tracking instead of mouse position
2. Added `pointer-events: none` to tooltip
3. Added larger invisible hit area (radius 15) around each point
4. Computed tooltip position from data point location, not mouse:

```typescript
const hoveredIndex = ref<number | null>(null)

function getTooltipPosition(index: number) {
  const angleStep = (2 * Math.PI) / props.dimensions.length
  const angle = angleStep * index - Math.PI / 2
  const dim = props.dimensions[index]
  const pointRadius = (dim.value / 100) * radius.value
  const x = center.value + pointRadius * Math.cos(angle)
  const y = center.value + pointRadius * Math.sin(angle)
  return { x, y }
}
```

### Files Changed

- `wecom-desktop/src/components/charts/PersonalityRadar.vue`

---

## Bug 4: Radar Chart Label Truncation

### Symptoms

Chinese labels like "情绪稳定性" and "开放性" were cut off - only partial characters visible (e.g., "稳" in "稳定性" not shown).

### Root Cause

- Radar chart size (280px) was too small
- Label padding (40px) insufficient for Chinese characters

### Fix

1. Increased default chart size from 280 to 340 pixels
2. Increased label padding from 40 to 60 pixels
3. Increased label radius from 25 to 35 pixels from chart edge

```typescript
const labelPadding = 60
const size = computed(() => props.size || 340)
const radius = computed(() => size.value / 2 - labelPadding)

function getLabelPosition(index: number, total: number) {
  const labelRadius = radius.value + 35 // Increased from 25
  // ...
}
```

### Files Changed

- `wecom-desktop/src/components/charts/PersonalityRadar.vue`
- `wecom-desktop/src/views/StreamerDetailView.vue` (size prop)

---

## Testing

All fixes verified by:

1. Navigating to `/streamers` and clicking on streamer cards
2. Verifying avatars match those in `/conversations`
3. Hovering over radar chart points - tooltip stable
4. Verifying all Chinese labels fully visible in radar chart

## Related Features

- [Streamers Database with Persona Analysis](../01-product/2025-12-11-streamers-database-persona-analysis.md)
