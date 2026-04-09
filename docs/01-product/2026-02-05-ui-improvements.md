# UI Improvements - Dashboard, Realtime Reply, and Sticker Display

**Date:** 2026-02-05
**Status:** ✅ Complete
**Authors:** Claude Code

## Overview

Fixed multiple UI issues across the application:

1. Unified dashboard stat card heights
2. Made Realtime Reply AI settings always enabled
3. Fixed sticker (emoji) display in conversation detail view

---

## 1. Dashboard Stat Card Height Unification

### Problem

The four stat cards on the dashboard (Devices, Agents/Kefus, Streamers/Customers, Messages) had inconsistent heights:

- **Devices** card had extra content showing active device count
- **Messages** card had a ratio bar and sent/received stats
- **Agents** and **Streamers** cards had no extra content
- Result: Cards appeared misaligned and visually inconsistent

### Solution

**Modified Files:**

- `wecom-desktop/src/components/charts/StatCard.vue`
- `wecom-desktop/src/views/DashboardView.vue`

**Changes:**

1. **StatCard.vue** - Added flex layout and minimum height:

   ```vue
   <template>
     <div
       class="relative overflow-hidden rounded-xl border transition-all duration-300 flex flex-col"
       style="min-height: 140px;"
       ...
     >
       <div class="relative p-5 flex-1 flex flex-col">
         <!-- Content -->
         <div v-if="$slots.default" class="mt-auto pt-4">
           <slot />
         </div>
       </div>
     </div>
   </template>
   ```

2. **DashboardView.vue** - Added wrapper divs with `h-full`:
   ```vue
   <div class="h-full">
     <StatCard ...> ... </StatCard>
   </div>
   ```

**Result:**

- All four cards now have consistent minimum height (140px)
- Extra content (when present) is pushed to bottom with `mt-auto`
- Cards stretch to fill grid cells uniformly

---

## 2. Realtime Reply Settings - Always Enabled

### Problem

Realtime Reply had two critical settings that users could accidentally disable:

- **"使用 AI 回复"** (Use AI Reply)
- **"通过侧边栏发送"** (Send via Sidecar)

These options are essential for the Realtime Reply feature to work correctly and should always be enabled.

### Solution

**Modified Files:**

- `wecom-desktop/src/views/RealtimeView.vue`
- `wecom-desktop/backend/routers/realtime_reply.py`
- `wecom-desktop/backend/servic../03-impl-and-arch/key-modules/defaults.py`
- `wecom-desktop/backend/servic../03-impl-and-arch/key-modules/models.py`

**Changes:**

1. **RealtimeView.vue** - Made checkboxes non-interactive but visually normal:

   ```vue
   <input
     :checked="true"
     type="checkbox"
     @click.prevent
     class="w-12 h-6 rounded-full bg-wecom-surface border border-wecom-border cursor-not-allowed"
     title="此选项始终启用"
   />
   ```

   - Removed `disabled` attribute (keeps checkbox green, not grayed out)
   - Added `@click.prevent` to prevent unchecking
   - Added `cursor-not-allowed` and tooltip for UX feedback

2. **realtime_reply.py** - Force values to `True`:

   ```python
   @router.get("/settings")
   async def get_realtime_settings():
       use_ai_reply = True  # Always enabled
       send_via_sidecar = True  # Always enabled
       ...

   @router.post("/settings")
   async def update_realtime_settings(settings: RealtimeSettings):
       updates = {
           "scan_interval": settings.scan_interval,
           "use_ai_reply": True,  # Force to True
           "send_via_sidecar": True,  # Force to True
       }
       ...
   ```

3. **defaults.py** - Updated default values:

   ```python
   (SettingCategory.REALTIME.value, "use_ai_reply", ValueType.BOOLEAN.value, True,
       "使用 AI 回复 (始终启用)", False),
   (SettingCategory.REALTIME.value, "send_via_sidecar", ValueType.BOOLEAN.value, True,
       "通过 Sidecar 发送 (始终启用)", False),
   ```

4. **models.py** - Updated dataclass defaults:
   ```python
   @dataclass
   class RealtimeSettings:
       scan_interval: int = 60
       use_ai_reply: bool = True  # Always enabled
       send_via_sidecar: bool = True  # Always enabled
   ```

**Result:**

- Checkboxes appear normally (green, checked) but cannot be unchecked
- Backend ignores any attempt to disable these settings
- Settings are always enabled regardless of user interaction

---

## 3. Sticker (Emoji) Display Fix

### Problem

Stickers (表情包) were not displaying in the conversation detail view, even though:

- The image file paths were correct
- Regular images displayed properly
- The issue was specifically with sticker-type messages

### Root Cause

The `fetchAllImageInfo()` function in `CustomerDetailView.vue` only loaded image info for `message_type === 'image'`, but stickers have `message_type === 'sticker'`:

```typescript
// BEFORE (broken)
async function fetchAllImageInfo() {
  const imageMessages = messages.value.filter((m) => m.message_type === 'image')
  await Promise.all(imageMessages.map((m) => fetchImageInfo(m.id)))
}
```

### Solution

**Modified File:**

- `wecom-desktop/src/views/CustomerDetailView.vue`

**Change:**

```typescript
// AFTER (fixed)
async function fetchAllImageInfo() {
  const imageMessages = messages.value.filter(
    (m) => m.message_type === 'image' || m.message_type === 'sticker'
  )
  await Promise.all(imageMessages.map((m) => fetchImageInfo(m.id)))
}
```

**Result:**

- Stickers now load image info correctly
- Sticker images display with proper thumbnails
- Clicking sticker opens image viewer modal (same as regular images)

---

## Testing

### Dashboard Cards

- ✅ All four cards have equal height
- ✅ Cards with extra content (Devices, Messages) show content at bottom
- ✅ Responsive layout works on mobile/tablet/desktop

### Realtime Reply Settings

- ✅ Checkboxes appear green and checked
- ✅ Clicking checkboxes has no effect (cannot uncheck)
- ✅ Hover shows "disabled" cursor and tooltip
- ✅ Backend API always returns `true` for both settings
- ✅ Saving settings has no effect on these values (always `true`)

### Sticker Display

- ✅ Stickers load and display in conversation view
- ✅ Sticker thumbnails appear correctly
- ✅ Clicking sticker opens image viewer
- ✅ Regular images still work as before

---

## Files Modified

```
wecom-desktop/src/components/charts/StatCard.vue
wecom-desktop/src/views/DashboardView.vue
wecom-desktop/src/views/RealtimeView.vue
wecom-desktop/src/views/CustomerDetailView.vue
wecom-desktop/backend/routers/realtime_reply.py
wecom-desktop/backend/servic../03-impl-and-arch/key-modules/defaults.py
wecom-desktop/backend/servic../03-impl-and-arch/key-modules/models.py
```

---

## Related Documentation

- [Dashboard Visual Enhancements](2025-12-09-dashboard-visual-enhancements.md)
- [Resources Media Browser](2025-12-12-resources-media-browser.md)
- [Realtime Reply Architecture](../../03-impl-and-arch/instant-response-sidecar-upgrade.md)
