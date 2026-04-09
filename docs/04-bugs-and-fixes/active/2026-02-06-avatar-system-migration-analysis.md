# Avatar System Migration - Technical Analysis

**Date**: 2026-02-06
**Status**: ⚠️ Legacy Code Found - Cleanup Required

## Executive Summary

The `syncAvatarsPlugin` in `electron.vite.config.ts` is **legacy code** that can be safely removed. The project has migrated to a **backend API-based avatar system**, but the old static file synchronization mechanism was not cleaned up.

## Current Architecture (Actual)

### Backend API System (✅ Active)

**File**: `wecom-desktop/src/utils/avatars.ts`

The frontend now fetches avatars dynamically from the backend API:

```typescript
// 1. Load avatar metadata from backend
GET http://localhost:8765/avatars/metadata
→ Returns: [{ filename: "avatar_xxx.png", name: "xxx" }]

// 2. Fetch avatar image from backend
GET http://localhost:8765/avatars/avatar_xxx.png
→ Returns: Image file
```

**Key Features**:

- Dynamic avatar discovery - new avatars captured by backend are automatically available
- No build-time dependency on avatar files
- Supports runtime avatar updates
- Deterministic fallback hash for unmatched customers

**Backend Endpoints**:

- `GET /avatars/metadata` - List all available avatars
- `GET /avatars/{filename}` - Serve avatar image file
- Source: Root directory `avatars/` (served by FastAPI static files)

## Legacy Architecture (❌ Deprecated)

### Static File Synchronization (Dead Code)

**File**: `wecom-desktop/electron.vite.config.ts` (lines 7-34, 69)

```typescript
function syncAvatarsPlugin() {
  // Copies from ../avatars to public/avatars
  // Runs on: dev server start, file changes, build start
}
```

**Flow**:

```
Root/avatars/ (95 files)
    ↓ syncAvatarsPlugin (copy)
public/avatars/ (10 files - stale)
    ↓ Vite build
dist/avatars/ (95 files - build artifact)
```

**Why This is Obsolete**:

1. Frontend no longer references `public/avatars/` as static assets
2. All avatar URLs now use the backend API (`${API_BASE}/avatars/...`)
3. The plugin causes unnecessary file copying on every build/dev server start
4. `public/avatars/` contains only 10 files (stale/incomplete copy)

## Evidence of Migration

### Frontend Code Analysis

**File**: `wecom-desktop/src/utils/avatars.ts` (lines 83-89)

```typescript
const resp = await fetch(`${API_BASE}/avatars/metadata`)
if (resp.ok) {
  const data = await resp.json()
  if (Array.isArray(data) && data.length > 0) {
    avatarFiles = data // ← Dynamic loading, not static files
  }
}
```

**No references to local static avatar paths**:

- ❌ No `/avatars/xxx.png` references
- ❌ No `import avatars from ...`
- ✅ All URLs use `${API_BASE}/avatars/...`

### Git History

```
commit 30008d9
Sync avatars in electron-vite renderer

commit 95d8a98
fix some problem
```

The `syncAvatarsPlugin` was added but not removed when the system migrated to backend API.

## Cleanup Recommendations

### 1. Remove `syncAvatarsPlugin`

**File**: `wecom-desktop/electron.vite.config.ts`

**Action**: Delete lines 7-34 and line 69

```diff
- function syncAvatarsPlugin() {
-   ... (27 lines)
- }
-
  plugins: [vue(), syncAvatarsPlugin()]
+ plugins: [vue()]
```

### 2. Delete Avatar Directories

```bash
# Safe to delete - legacy copy location
rm -rf wecom-desktop/public/avatars/

# Safe to delete - build output (auto-generated)
rm -rf wecom-desktop/dist/avatars/
rm -rf wecom-desktop/dist/

# Keep - source of truth, served by backend
# Root directory avatars/ - DO NOT DELETE
```

### 3. Verify .gitignore

**File**: `.gitignore`

Ensure these patterns are present:

```
# Build output
dist/
wecom-desktop/dist-electron/

# Frontend public assets (auto-copied from root)
wecom-desktop/public/avatars/

# Root avatars (optional - depends on your preference)
# avatars/
```

## Current State Summary

| Location                        | File Count | Purpose                       | Status    |
| ------------------------------- | ---------- | ----------------------------- | --------- |
| `avatars/` (root)               | 95         | Backend source, served by API | ✅ Keep   |
| `wecom-desktop/public/avatars/` | 10         | Legacy copy location          | ❌ Delete |
| `wecom-desktop/dist/avatars/`   | 95         | Build artifact                | ❌ Delete |

## Testing After Cleanup

### Verification Steps

1. **Remove syncAvatarsPlugin** from `electron.vite.config.ts`
2. **Delete public/dist avatar directories**
3. **Restart dev server**: `npm run dev:electron`
4. **Test avatar loading**:
   - Open desktop app
   - Navigate to customers view
   - Verify avatars load from backend API
   - Check browser Network tab for `/avatars/metadata` requests

### Expected Behavior

- ✅ Avatars load from backend API
- ✅ No build errors
- ✅ No missing file errors
- ✅ Faster builds (no file copying)

## Risks

### Low Risk

- **Backend API is stable and working** - no recent changes to avatar serving
- **Frontend fully migrated** - no static file references
- **Root avatars/ preserved** - backend continues serving them

### Mitigation

1. Commit before cleanup
2. Test on dev branch first
3. Revert if backend avatar serving fails

## Related Files

### Active (Backend API)

- `src/utils/avatars.ts` - Frontend avatar loading logic
- `wecom-desktop/backend/routers/resources.py` - Avatar metadata endpoint
- `wecom-desktop/backend/services/avatars.py` - Avatar serving logic
- `avatars/` (root) - Source avatar files

### Legacy (To Remove)

- `wecom-desktop/electron.vite.config.ts` - syncAvatarsPlugin function
- `wecom-desktop/public/avatars/` - Stale copy location
- `wecom-desktop/dist/avatars/` - Build output

## Conclusion

The `syncAvatarsPlugin` is **dead code** from a previous architecture. The project successfully migrated to a backend API system, but cleanup was incomplete. Removing this legacy code will:

1. ✅ Reduce confusion about avatar file locations
2. ✅ Speed up build times (no unnecessary file copying)
3. ✅ Simplify maintenance (one source of truth)
4. ✅ Reduce disk usage (no duplicate files)

**Recommendation**: Remove `syncAvatarsPlugin` and delete `public/dist` avatar directories in next cleanup PR.
