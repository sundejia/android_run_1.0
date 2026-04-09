# Sidecar Sync Controls with Pause/Resume/Stop

> **Date**: 2025-12-11
> **Status**: ✅ Complete
> **Components**: Frontend (SidecarView.vue), Backend (device_manager.py, sync.py), API (api.ts), Store (devices.ts)

## Overview

Enhanced the sidecar device panels with comprehensive sync controls including:

1. Horizontally scrollable title bar (except device name)
2. Individual device sync button
3. Real-time sync progress bar with Pause/Resume/Stop controls
4. Backend process group signal handling for reliable pause/resume

## Problem Statement

Previously, sidecar panels lacked:

- A way to start sync for individual devices directly from the sidecar
- Progress visibility for ongoing syncs
- Ability to pause, resume, or stop syncs from the sidecar view
- Title bar became cramped with multiple action buttons

## Implementation

### 1. Scrollable Title Bar

The title bar now has two sections:

- **Fixed device name** (`shrink-0`) - Always visible
- **Scrollable buttons container** (`overflow-x-auto`) - Scrolls horizontally when needed

```vue
<div class="flex items-center px-3 py-2 border-b border-wecom-border bg-wecom-dark/80">
  <!-- Device name - fixed, not scrollable -->
  <div class="flex items-center gap-2 shrink-0">
    <span class="px-2 py-1 rounded text-xs font-mono">{{ serial }}</span>
  </div>
  <!-- Scrollable buttons container -->
  <div class="flex-1 overflow-x-auto ml-2">
    <div class="flex items-center gap-1 min-w-max">
      <!-- All action buttons here -->
    </div>
  </div>
</div>
```

Hidden scrollbar CSS:

```css
.overflow-x-auto::-webkit-scrollbar {
  height: 0;
  display: none;
}
.overflow-x-auto {
  scrollbar-width: none; /* Firefox */
  -ms-overflow-style: none; /* IE and Edge */
}
```

### 2. Sync Button States

The sync button dynamically shows different states:

| State   | Button | Icon | Action      |
| ------- | ------ | ---- | ----------- |
| Idle    | Sync   | 📥   | Start sync  |
| Running | Pause  | ⏸️   | Pause sync  |
| Paused  | Resume | ▶️   | Resume sync |

### 3. Progress Bar with Controls

Shows when sync is running or paused:

```
┌─────────────────────────────────────────────────────────┐
│ Opening WeCom...                    45%  ⏸️ Pause  ⏹️ Stop │
│ ████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
└─────────────────────────────────────────────────────────┘
```

When paused:

- Background turns yellow
- Progress bar turns yellow
- Shows ⏸️ icon prefix
- Pause button changes to Resume

### 4. Status Banners

After sync completes/errors/stops, shows colored status banner with Clear button:

| Status    | Color  | Icon |
| --------- | ------ | ---- |
| Completed | Green  | ✓    |
| Error     | Red    | ⚠️   |
| Stopped   | Yellow | ⏹    |

### 5. Backend Process Group Handling

Key changes to `device_manager.py`:

```python
# Create subprocess in its own process group
process = await asyncio.create_subprocess_exec(
    *cmd,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    cwd=str(PROJECT_ROOT),
    start_new_session=True,  # Create new process group
)

# Pause entire process group
async def pause_sync(self, serial: str) -> bool:
    pgid = os.getpgid(process.pid)
    os.killpg(pgid, signal.SIGSTOP)

# Resume entire process group
async def resume_sync(self, serial: str) -> bool:
    pgid = os.getpgid(process.pid)
    os.killpg(pgid, signal.SIGCONT)

# Stop entire process group
async def stop_sync(self, serial: str) -> bool:
    pgid = os.getpgid(process.pid)
    os.killpg(pgid, signal.SIGTERM)
```

### 6. New API Endpoints

Added to `sync.py`:

```python
@router.post("/pause/{serial}")
async def pause_sync(serial: str):
    """Pause a running sync operation."""

@router.post("/resume/{serial}")
async def resume_sync(serial: str):
    """Resume a paused sync operation."""
```

### 7. SyncStatus Type Update

Added `'paused'` status:

```typescript
export interface SyncStatus {
  status: 'idle' | 'starting' | 'running' | 'paused' | 'completed' | 'error' | 'stopped'
  progress: number
  message: string
  customers_synced?: number
  messages_added?: number
  errors?: string[]
}
```

## Files Changed

### Frontend

- `wecom-desktop/src/views/SidecarView.vue` - UI components and handlers
- `wecom-desktop/src/services/api.ts` - Added pauseSync, resumeSync methods
- `wecom-desktop/src/stores/devices.ts` - Added pauseSync, resumeSync actions

### Backend

- `wecom-desktop/backend/services/device_manager.py`:
  - Added `PAUSED` status enum
  - Added `pause_sync()` and `resume_sync()` methods
  - Updated subprocess creation with `start_new_session=True`
  - Changed signal handling to use process groups
- `wecom-desktop/backend/routers/sync.py`:
  - Added `/sync/pause/{serial}` endpoint
  - Added `/sync/resume/{serial}` endpoint

## Technical Notes

### Why Process Groups?

The sync subprocess spawns child processes (like `adb` commands). Using `process.send_signal()` only affects the parent Python process. To properly pause all related processes:

1. Start subprocess with `start_new_session=True` to create a new process group
2. Use `os.killpg(pgid, signal)` to send signals to the entire process group

### Signal Handling

| Signal    | Effect                                         |
| --------- | ---------------------------------------------- |
| `SIGSTOP` | Pause process group (cannot be caught/ignored) |
| `SIGCONT` | Resume paused process group                    |
| `SIGTERM` | Request graceful termination                   |
| `SIGKILL` | Force kill (fallback after timeout)            |

## User Experience

1. Start sync from sidecar with 📥 button
2. See real-time progress in progress bar
3. Pause with ⏸️ to temporarily halt (e.g., to intervene manually)
4. Resume with ▶️ to continue where left off
5. Stop with ⏹️ to cancel completely
6. Clear status banner after completion

## Testing

1. Start sync from sidecar
2. Verify progress bar appears and updates
3. Click Pause - verify sync halts, UI turns yellow
4. Click Resume - verify sync continues from same point
5. Click Stop - verify sync terminates, shows yellow "stopped" banner
6. Clear banner and verify it disappears
