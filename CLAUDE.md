<!-- OPENSPEC:START -->

# Communication Style

**IMPORTANT**: Always address the user as "宝宝" (Baby) at the beginning of every response. This is a personal preference for a friendly interaction style.

# OpenSpec Instructions

These instructions are for AI assistants working in this project.

Always open `@/openspec/AGENTS.md` when the request:

- Mentions planning or proposals (words like proposal, spec, change, plan)
- Introduces new capabilities, breaking changes, architecture shifts, or big performance/security work
- Sounds ambiguous and you need the authoritative spec before coding

Use `@/openspec/AGENTS.md` to learn:

- How to create and apply change proposals
- Spec format and conventions
- Project structure and guidelines

Keep this managed block so 'openspec update' can refresh the instructions.

<!-- OPENSPEC:END -->

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Environment

**IMPORTANT: This project is developed on WINDOWS.**

- **Platform**: Windows (win32)
- **Shell**: Use Windows-compatible commands (cmd/PowerShell syntax)
- **Python**: Managed via `uv` package manager
- **Node.js**: For the desktop application (Electron + Vue.js)

**Shell Command Guidelines:**

- ⚠️ **CRITICAL**: NEVER use `> nul` or `2> nul` in bash/shell commands - it creates actual `nul` files
- For suppressing output in Git Bash: use `> /dev/null 2>&1`
- For suppressing output in PowerShell: use `| Out-Null` or `$null = command 2>&1`
- Use Windows path separators: backslashes `\` or forward slashes `/` (Git Bash handles both)
- Use `&&` to chain commands in PowerShell/cmd
- Use `;` to chain commands only in Git Bash
- Avoid Linux-specific commands: `source`, `grep -r`, `find`, `xargs` (use PowerShell equivalents or Git Bash)
- Use `python` or `py` instead of `python3`
- Use `.\Scripts\activate` for virtual environment, NOT `source .venv/bin/activate`
- For cross-platform scripts, use Git Bash if available

**Example Correct Windows Commands:**

```powershell
# PowerShell/CMD
cd D:\111\android_run_test-backup
pytest tests/unit/ -v
npm run dev

# Git Bash (also works on Windows)
cd /d/111/android_run_test-backup
pytest tests/unit/ -v
npm run dev
```

## Project Overview

This is a **WeCom (企业微信/Enterprise WeChat) Automation Framework** for Android devices with two main components:

1. **Python automation framework** (`src/wecom_automation/`) - Core library using DroidRun for device interaction
2. **Desktop application** (`wecom-desktop/`) - Electron + Vue.js + FastAPI app for multi-device management

The framework extracts conversations, messages, avatars, and media from WeCom on Android devices, with features for parallel sync, real-time monitoring, AI reply integration, and database persistence.

## Common Commands

### Python Framework Development

```bash
# Install dependencies (requires Python >= 3.11)
uv venv --python 3.11
source .venv/bin/activate  # Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"

# Run tests
pytest tests/unit/ -v                          # Unit tests only
pytest tests/integration/ -v -m integration    # Integration tests (requires device)
pytest tests/unit/ --cov=src/wecom_automation --cov-report=html

# Run standalone scripts
uv run list_devices.py --full --detailed
uv run get_kefu_name.py --serial DEVICE_SERIAL
uv run initial_sync.py --serial DEVICE_SERIAL
```

### Desktop Application Development

```bash
cd wecom-desktop

# Install dependencies
npm install

# Start backend (Terminal 1)
cd backend
uvicorn main:app --reload --port 8765 --ws-ping-interval 20 --ws-ping-timeout 30

# Start Electron app (Terminal 2)
cd ..
npm run dev:electron

# Or run both together
npm start

# Production build
npm run build

# Quick redeploy (stops → builds → restarts backend + frontend)
# NOTE: redeploy-dev.sh is Linux-only. On Windows, manually restart backend/frontend.
# PowerShell: Stop processes (Ctrl+C), then run: cd backend && uvicorn main:app --reload --port 8765 --ws-ping-interval 20 --ws-ping-timeout 30
```

### Database Management

The SQLite database is at `wecom_conversations.db` in the project root (configurable via `WECOM_DB_PATH` env var).

```bash
# View database location
python -c "from wecom_automation.core.config import get_default_db_path; print(get_default_db_path())"
```

## High-Level Architecture

### Three-Layer Architecture (Python Framework)

```
┌─────────────────────────────────────────────────────────────┐
│                         CLI Layer                           │
│  (commands.py, list_devices.py, initial_sync.py)           │
│  • Argument parsing, configuration building                 │
│  • Workflow execution & output formatting                   │
└────────────────────────────┬────────────────────────────────┘
                             │ uses
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                     Services Layer                          │
│  ┌──────────────────┐  ┌────────────────┐  ┌─────────────┐ │
│  │  WeComService    │  │  ADBService    │  │ UIParser     │ │
│  │  Orchestrates    │──│  Device I/O    │  │ UI tree      │ │
│  │  workflows       │  │  (droidrun)    │  │ parsing      │ │
│  └──────────────────┘  └────────────────┘  └─────────────┘ │
│  ┌──────────────────┐  ┌────────────────┐  ┌─────────────┐│
│  │ SyncOrchestrator │  │ DeviceDiscovery│  │BlacklistSrv ││
│  │ Database sync    │  │ Device enum    │  │User filtering││
│  └──────────────────┘  └────────────────┘  └─────────────┘│
└────────────────────────────┬────────────────────────────────┘
                             │ uses
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                       Core Layer                            │
│  Config | Exceptions | Models (dataclasses) | Logging       │
└─────────────────────────────────────────────────────────────┘
```

**Key Services:**

- `WeComService` - High-level orchestration: launch → navigate → extract → sync
- `ADBService` - Low-level device interaction via droidrun (tap, swipe, screenshots, UI tree)
- `UIParserService` - Parse accessibility trees, extract users/messages/客服 info
- `SyncOrchestrator` - Modern sync orchestration with checkpoint/recovery support
- `DeviceDiscoveryService` - Enumerate devices, fetch properties and runtime stats
- `BlacklistChecker` + `BlacklistWriter` - Manage blocked users during sync/followup operations

**Message Handlers (`services/message/handlers/`):**

- Extensible handler architecture for different message types
- Handlers: `text.py`, `image.py`, `voice.py`, `video.py`, `sticker.py`
- Each handler: downloads media, extracts metadata, saves to database

### Desktop Application Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Electron (Vue.js)                        │
│  • Device list, mirror windows, logs panel                 │
│  • Dashboard, customers, 客服 views                        │
│  • Pinia stores, components                                 │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST + WebSocket
┌──────────────────────────▼──────────────────────────────────┐
│                   FastAPI Backend                           │
│  routers/: devices, sync, dashboard, kefus, customers, etc.│
│  services/: device_manager, followup, settings, recovery   │
└──────────────────────────┬──────────────────────────────────┘
                           │ Subprocess (per device)
┌──────────────────────────▼──────────────────────────────────┐
│            wecom_automation package (Python)                │
│  SyncOrchestrator, ADBService, ConversationRepository      │
└─────────────────────────────────────────────────────────────┘
```

**Important Multi-Device Requirement:**
Each device's droidrun app must use a unique port (8080, 8081, 8082...) to prevent conflicts during parallel sync.

### Database Schema

**Tables:**

- `devices` - Android device information
- `kefus` - 客服 (WeCom logged-in users/agents)
- `kefu_devices` - Junction table linking kefus to devices
- `customers` - Conversation contacts
- `messages` - Individual messages (text, image, voice, video, etc.)
- `images` - Image message files with bounds and metadata
- `videos` - Video message files with duration and thumbnails
- `blacklist` - Users to skip during sync/followup operations
- `kefu_action_profiles` - Per-kefu overrides for media auto-action settings (auto_group_invite, auto_contact_share); schema v15+ (legacy, superseded by `device_action_profiles`)
- `device_action_profiles` - Per-device overrides for media auto-action settings; schema v16+
- `schema_version` - Database migration version tracking

**Key Relationships:**

- `devices` ↔ `kefus` (many-to-many via `kefu_devices`)
- `kefus` → `customers` (one-to-many: one 客服 serves many customers)
- `customers` → `messages` (one-to-many)
- `messages` → `images` (one-to-one for image messages)
- `messages` → `videos` (one-to-one for video messages)

## Key Implementation Patterns

### 1. DroidRun Overlay Optimization

The framework heavily optimizes DroidRun's overlay feature for performance:

**UIStateCache** (`adb_service.py`):

- TTL-based caching with auto-invalidation after UI-modifying operations (tap, swipe, scroll)
- Single `get_ui_state()` call instead of separate `get_ui_tree()` + `get_clickable_elements()`
- Hash detection to skip re-parsing when UI unchanged (useful for scroll-end detection)

**Text Indexing** (`adb_service.py`):

- O(1) element lookup by text instead of O(n) list traversal
- `find_by_text_indexed()` for fast element finding

**Flat-List Optimization**:

- Skip recursive child search when `clickable_elements_cache` is flat
- Check `node.get("children_count") == clickable_elements_cache.length`

**droidrun_index**:

- Store overlay indices in data models (`UserDetail.droidrun_index`)
- Enables reliable tapping via `tap_by_index()`

### 2. Message Type Handlers

Located in `src/wecom_automation/services/message/handlers/`:

```python
# Base handler interface
class BaseMessageHandler(ABC):
    @abstractmethod
    async def handle(self, message_data: dict, context: dict) -> Optional[dict]:
        """Process message, return dict for database or None"""
        pass

# Handler types:
- TextHandler: Extract text content
- ImageHandler: Screenshot and crop image bounds, save to images/
- VoiceHandler: Download voice files, duration extraction
- VideoHandler: Download video files, thumbnail generation
- StickerHandler: Handle sticker emoji messages
```

Handlers are selected by `MessageProcessor` based on UI patterns (resource IDs, class types, content descriptions).

### 3. Sync Checkpoint & Recovery

**Checkpoint System** (`services/sync/checkpoint.py`):

- Save progress after each customer during sync
- Enables seamless recovery from interruptions (crashes, disconnections, etc.)

**Recovery Workflow** (`services/sync/recovery_checkpoint.py`):

1. Check for existing checkpoint at sync start
2. Resume from last successful customer
3. Handle device state validation (WeCom must be on Messages screen)
4. Clean checkpoint after successful completion

**Universal Recovery**:

- RecoveryManager in `wecom-desktop/backend/services/recovery/` handles screen state navigation
- Uses recovery plans to navigate back to Messages screen from any state

### 4. 客服 (Kefu) Auto-Detection

**Detection** (`services/wecom_service.py:get_kefu_name()`):

- Extracts current logged-in user from UI tree
- Detects name, department, verification status
- Cached per device to avoid repeated extraction

**Auto-Association**:

- `SyncOrchestrator` auto-detects kefu on first sync per device
- Creates/updates `kefus` table entry linked to device
- All customers extracted during sync associate with this kefu

### 5. Avatar System

**Extraction** (during sync):

- Screenshot avatars from conversation list
- Crop using detected bounds from UI tree
- Save to `avatars/` directory in project root
- Deterministic filenames: `avatar_{index}_{name}.png`

**Display** (desktop app):

- Avatars copied to `wecom-desktop/public/avatars/` by Vite
- Deterministic avatar assignment based on hash of `(name, channel, id)`
- Fallback to default avatars if none captured

**Deduplication**:

- Messages table uses SHA256 hash (`message_hash`) to avoid duplicate messages
- Image handler stores bounds and metadata in separate `images` table

### 6. Timestamp Parsing

**Multi-Format Support** (`services/timestamp_parser.py`):

- Relative times: "6 mins ago", "3分钟前", "Yesterday", "昨天"
- Absolute times: "AM 1:41", "11/24", "2025-12-16"
- Timezone-aware: Uses `TimezoneConfig` (default: Asia/Shanghai)
- Fallback to current time when parsing fails

### 7. AI Reply Integration

**Settings** (`wecom-desktop/backend/services/settings/`):

- Unified key-value storage in SQLite table **`settings`** (same database file as conversations: default `wecom_conversations.db` / `WECOM_DB_PATH`, via `get_settings_service()`)
- Enable/disable AI reply and other app options through that table
- Configurable AI server URL, timeout, prompt style
- No separate `settings.db`; optional legacy files may still live under project `settings/` (e.g. Excel exports), but they are not the unified settings store

**Follow-up Service** (`wecom-desktop/backend/services/followup/`):

- **Modern Architecture** (Phase 2+):
  - `FollowUpExecutor` - Executes follow-up attempts
  - `FollowUpQueueManager` - Manages follow-up task queue
  - `ResponseDetector` - Detects when to send follow-up
  - `FollowUpManager` - High-level orchestration
  - `AttemptsRepository` - Tracks follow-up history
- **Response Types**:
  - **补刀 (follow-up)**: When kefu sent last, re-engage customer
  - **回复 (reply)**: When customer sent last, respond to their message
- **10s delayed send** in sidecar: pauses when on-device typing detected
- Automatic fallback to mock messages if AI unavailable

**Realtime Reply Manager** (`wecom-desktop/backend/services/realtime_reply_manager.py`):

- Manages per-device realtime reply subprocesses
- Similar architecture to DeviceManager
- Each device runs in isolated process with independent state
- After uvicorn `--reload`, old subprocess trees can survive while the manager’s `_processes` dict resets; **`orphan_process_cleaner`** terminates matching `realtime_reply_process.py` trees before spawn (per serial) and on **`main.py` startup** (all), preventing duplicate controllers on one device (`docs/03-impl-and-arch/key-modules/realtime-reply-orphan-cleanup.md`)

**Recording**:

- AI-generated replies tracked in settings database
- Follow-up attempts recorded in `followup_attempts` table (settings DB)

### 8. Sidecar (Real-Time Context Pane)

**Purpose**:

- Live UI state monitoring without launching full mirror window
- Shows conversation presence, 客服 info, last 5 messages
- 10s delayed send with typing detection

**Implementation** (`wecom-desktop/backend/services/sidecar.py`):

- Polls device UI tree every 2s (configurable)
- Detects conversation by checking for message list elements
- Extracts kefu info from profile panel area
- Caches messages to reduce bandwidth
- Queue system to prevent messages sent to wrong contacts

**Endpoints**:

- `GET /sidecar/{serial}/state` - Snapshot current UI state
- `POST /sidecar/{serial}/send` - Send prepared message
- `GET /sidecar/{serial}/queue` - Get message queue status
- WebSocket for real-time updates

### 9. Blacklist System

**Purpose**:

- Filter out unwanted users during sync and follow-up operations
- Prevent wasted time on blocked/deleted accounts

**Implementation** (`src/wecom_automation/services/blacklist_service.py`):

- `BlacklistChecker` (classmethod-based) - High-performance blacklist checking with optional caching
- `BlacklistWriter` (instance-based) - All write operations and list queries
- Database-backed blacklist in main `wecom_conversations.db`
- Real-time DB queries by default (use_cache=False) for multi-process safety
- Per-device blacklist support
- Reason tracking (e.g., "blocked by user", "test account")

**Usage**:

- Sync: Skip blacklisted customers during extraction
- Followup: Never send follow-ups to blacklisted users

### Blacklist Send-Safety Rules

When code can enqueue, approve, or actually send a message to a customer, follow these rules:

- Never use fail-open behavior for blacklist or recipient-safety checks. If the latest blacklist lookup fails, skip/cancel the send path.
- Check blacklist state both before enqueueing and immediately before the actual send step. Do not rely on queue-time validation alone.
- For cross-process flows (frontend block button, backend worker, sidecar queue), use real-time DB reads for send-safety decisions. Cache fallback is not acceptable for send authorization.
- If queued work discovers the customer is now blacklisted, has already replied, or the last persisted conversation state changed since the task was created, cancel the pending task instead of sending.
- The final send endpoint is also a safety boundary. If a message can be sent via Sidecar/manual approval/direct API, blacklist validation must exist there too, not only in the upstream caller.
- Any bug fix or feature touching follow-up, realtime reply, sidecar queue, or manual-send paths must add a regression test for mid-flight state changes (for example: queued first, then blacklisted before send).

### 10. Device Manager

**Purpose**:

- Orchestrate sync operations across multiple devices
- Per-device subprocess isolation for safety
- Real-time log streaming via WebSocket callbacks

**Implementation** (`wecom-desktop/backend/services/device_manager.py`):

- Each device runs in isolated subprocess
- Graceful pause/resume/stop controls
- Progress tracking and state management
- Windows Job Object support for process management

### 11. Image Sender (NEW - 2026-02-06)

**Purpose**:

- Send images from WeCom Favorites to contacts
- Modular design for flexible integration
- Support for API and direct code invocation

**Implementation** (`src/wecom_automation/services/message/image_sender.py`):

- `ImageSender` class with dynamic UI element finding
- No hardcoded coordinates - supports different screen resolutions
- Strategy-based element lookup (text, resource_id, position)
- `send_via_favorites(favorite_index)` - Send specific favorite item
- `list_favorites()` - List all available favorites

**API Routes** (`wecom-desktop/backend/routers/image_sender.py`):

- `POST /api/image-sender/send` - Send image from favorites
- `POST /api/image-sender/list-favorites` - List all favorite items

**Usage**:

```python
from wecom_automation.services.message.image_sender import ImageSender

sender = ImageSender(wecom_service)
success = await sender.send_via_favorites(favorite_index=0)
```

**Integration Points**:

- Can be called in realtime_reply_process.py
- Can be integrated into followup workflows
- Can be triggered via REST API from frontend
- Supports conditional sending based on keywords/logic

**Documentation**: `docs/03-impl-and-arch/key-modules/image-sender.md`

### 12. Per-Device Action Profiles (2026-05-13)

**Purpose**:

- Allow each device (phone) to have independent `auto_group_invite` and `auto_contact_share` configurations
- Replace the per-kefu model with a device-centric approach (each phone = independent config)
- Merge global settings with per-device overrides transparently so downstream actions require no code changes

**Database Schema** (`device_action_profiles` table, schema v16):

```sql
CREATE TABLE device_action_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_serial TEXT NOT NULL,
    action_type TEXT NOT NULL,        -- 'auto_blacklist' | 'review_gate' | 'auto_group_invite' | 'auto_contact_share'
    enabled BOOLEAN NOT NULL DEFAULT 1,
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(device_serial, action_type)
);
```

**Settings Resolution Flow** (`device_resolver.py`):

1. Load global settings from `settings` table via `settings_loader.py`
2. Load all `device_action_profiles` rows for that `device_serial`
3. Deep-merge: start from a copy of global settings, then overlay per-device fields
4. Return merged dict with identical structure to global settings

Resolution order (later wins):
1. `DEFAULT_MEDIA_AUTO_ACTION_SETTINGS` (code defaults)
2. `settings` table global overrides
3. `device_action_profiles` rows for the given device

**API Routes** (`wecom-desktop/backend/routers/device_profiles.py`):

- `GET /api/device-profiles/` - List all devices with override status
- `GET /api/device-profiles/{device_serial}/actions` - Get overrides for a device
- `PUT /api/device-profiles/{device_serial}/actions/{action_type}` - Create/update override
- `DELETE /api/device-profiles/{device_serial}/actions/{action_type}` - Delete override
- `GET /api/device-profiles/{device_serial}/effective` - Get fully resolved settings

**Integration Points**:

- `build_media_event_bus()` accepts `device_serial` parameter; when provided, `device_resolver` merges per-device overrides before returning settings
- `response_detector` passes `device_serial=serial` directly to `build_media_event_bus()`
- `AutoContactShareAction._resolve_contact_name()` uses merged settings directly

**Migration**:

- Schema v15 -> v16: creates `device_action_profiles` table, migrates `kefu_action_profiles` data via `kefu_devices` junction table
- Legacy `/api/kefu-profiles` router remains registered for backward compatibility

**Frontend**:

- `MediaActionsView.vue` has a "按设备覆盖配置" section showing connected devices
- `deviceProfiles` Pinia store manages device profile state
- API types: `DeviceActionProfileSummary`, `DeviceActionProfile`, `DeviceEffectiveSettings`

**Documentation**: `docs/implementation/2026-05-13-per-kefu-action-profiles.md`

## Configuration

### Environment Variables

```bash
# Device selection
export WECOM_DEVICE_SERIAL="ABC123"     # ADB device serial
export WECOM_USE_TCP="true"             # Use TCP bridge

# Paths
export WECOM_DB_PATH="./custom.db"      # Database path
export WECOM_PROJECT_ROOT="/path/to/root" # Project root

# Behavior
export WECOM_DEBUG="true"               # Enable debug logging
export WECOM_OUTPUT_DIR="./output"      # Output directory
export WECOM_CAPTURE_AVATARS="true"     # Capture avatars during sync

# Timing
export WECOM_WAIT_AFTER_LAUNCH="5.0"    # Seconds to wait after WeCom launch
export WECOM_MAX_SCROLLS="30"           # Max scroll attempts
export WECOM_SCROLL_DELAY="1.5"         # Delay between scrolls

# Timezone
export WECOM_TIMEZONE="Asia/Shanghai"   # Or preset: "china", "beijing", "utc"
```

### Python Config Objects

```python
from wecom_automation.core.config import Config

# Default config
config = Config()

# From environment
config = Config.from_env()

# Override specific values
config = config.with_overrides(
    device_serial="ABC123",
    debug=True,
    max_scrolls=30
)

# Access sub-configs
config.app.package_name              # "com.tencent.wework"
config.timing.wait_after_launch      # 3.0
config.scroll.max_scrolls            # 20
config.ui_parser.name_resource_id_hints  # ("title", "name", ...)
config.timezone_config.timezone      # "Asia/Shanghai"
```

## Testing

### Test Organization

```
tests/
├── conftest.py                 # Shared fixtures
├── unit/                       # Fast, isolated tests
│   ├── test_config.py
│   ├── test_models.py
│   ├── test_ui_parser.py
│   ├── test_database.py
│   ├── test_sync_service.py
│   └── ...
└── integration/                # Requires real device
    └── test_workflow.py
```

### Running Tests

```bash
# Unit tests only (no device required)
pytest tests/unit/ -v

# With coverage
pytest tests/unit/ --cov=src/wecom_automation --cov-report=html

# Integration tests (requires connected device)
pytest tests/integration/ -v -m integration

# Specific test
pytest tests/unit/test_models.py::test_user_detail_unique_key -v
```

### Fixtures (conftest.py)

- `mock_config` - Mock Config object
- `sample_ui_tree` - Sample accessibility tree
- `sample_device_info` - Sample device information

## Troubleshooting

### Windows-Specific Issues

**Shell command fails with "command not found" or syntax errors:**

- You're likely using Linux/bash syntax on Windows
- Use PowerShell or cmd syntax instead
- Or use Git Bash if you need Linux-like commands
- Example: Use `.\venv\Scripts\activate` NOT `source .venv/bin/activate`

**Path separators not working:**

- Windows accepts both `\` and `/` in most cases
- For PowerShell commands, use `\` or escape properly
- For Git Bash, use `/`
- Avoid mixing them in the same command

**Virtual environment activation fails:**

```powershell
# CORRECT (Windows)
.venv\Scripts\activate

# WRONG (Linux syntax)
source .venv/bin/activate
```

**Script execution fails on Windows:**

- Shell scripts (`.sh`) require Git Bash or WSL
- Use PowerShell scripts (`.ps1`) for native Windows support
- Or run commands directly in PowerShell

**Creating `nul` files accidentally (CRITICAL):**

- ⚠️ **NEVER** redirect output to `nul` using bash syntax in this project
- `nul` is a reserved device name on Windows (like `/dev/null` on Linux)
- Using `> nul` or `2> nul` incorrectly can create actual files named `nul`
- **CORRECT** ways to suppress output:

```bash
# Git Bash - use /dev/null (Linux-style works in Git Bash)
command > /dev/null 2>&1

# PowerShell - use $null or Out-Null
command | Out-Null
# or
$null = command 2>&1

# CMD - use nul without quotes (only in .bat files!)
command > nul 2>&1

# Python subprocess - use DEVNULL or PIPE
from subprocess import DEVNULL
subprocess.run(["command"], stdout=DEVNULL, stderr=DEVNULL)
```

- **WRONG** - Do NOT do this:

```bash
# This can create an actual file named "nul"
command > nul
echo "test" > nul
```

- If a `nul` file is accidentally created, remove it with:

```bash
rm -f "./nul"  # Note: quotes and ./ prefix are important
```

### Common Issues

**Device not found:**

```bash
# Check ADB connection
adb devices

# Verify device is online
uv run list_devices.py --full
```

**UI elements not detected:**

- Increase `WECOM_WAIT_AFTER_LAUNCH` (default: 3.0s)
- Ensure device is unlocked and WeCom is open
- Try `--prefer-tcp` for faster UI tree reads

**Import errors:**

- Verify Python >= 3.11 (`python --version`)
- Reinstall dependencies: `uv pip install -e ".[dev]"`

**Avatar capture fails:**

- Ensure Pillow is installed: `uv pip install Pillow`
- Check output directory permissions

**Sync stuck/not progressing:**

- Check logs for error messages
- Verify WeCom is on Messages screen
- Try recovery mode (automatic checkpoint detection)

**Multi-device sync conflicts:**

- Ensure each device uses unique droidrun port (8080, 8081, 8082...)
- Check device manager: `GET /devices` via backend API

**Database locked:**

- Only one sync process per database at a time
- Close other connections (desktop app, other scripts)

**'Logger' object has no attribute 'addHandler':**

- Root cause: Mixing stdlib logging's `addHandler()` with loguru logger
- Fix: Replace `logging.Handler` with loguru sinks using `logger.add()`
- See: `docs/04-bugs-and-fixes/resolved/2026-02-06-sidecar-addhandler-error.md`

**UnboundLocalError: cannot access local variable 'sidecar_client' where it is not associated with a value:**

- Root cause: Exception in `try` block prevents variable assignment, but variable is used later
- Fix: Add `sidecar_client = None` in the `except` block to ensure variable is always defined
- See: `docs/04-bugs-and-fixes/resolved/2026-02-06-sidecar-unbound-variable-error.md`
- Best practice: Always initialize variables with default values in `except` blocks if they're used later

**Module import errors after refactoring (sys.path conflicts):**

When you encounter `ImportError: cannot import name 'X' from 'module'` after refactoring, especially when the error shows Python is importing from a different directory:

```
ImportError: cannot import name 'init_logging' from 'wecom_automation.core.logging'
(D:\111\android_run_test-main\src\wecom_automation\core\logging.py)
```

**Root Cause**: Virtual environment contains old editable installation pointing to a different directory.

**Solutions**:

1. **Quick fix (for development)**: Force sys.path cleanup in main.py:

```python
# Remove conflicting paths before importing
sys.path = [p for p in sys.path if "old-directory-name" not in p]
sys.path.insert(0, str(project_root / "src"))
```

2. **Proper fix (recommended)**:

```bash
# Reinstall package in editable mode in current directory
cd d:\111\android_run_test-backup
uv pip uninstall wecom-automation
uv pip install -e .
```

3. **Alternative**: Use a fresh virtual environment:

```bash
# Create new venv in current directory
uv venv --python 3.11
source .venv/bin/activate  # Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"
```

**Prevention**: Always ensure your virtual environment is in the same directory tree as your source code, or use absolute paths when installing in editable mode.

**Import errors in subprocess scripts (sys.path order):**

When subprocess scripts (like `realtime_reply_process.py`, `initial_sync.py`) fail with `ModuleNotFoundError: No module named 'utils'`:

```
ModuleNotFoundError: No module named 'utils'
```

**Root Cause**: Trying to import backend modules before configuring `sys.path`.

**Solution**: Always configure `sys.path` BEFORE importing project modules:

```python
# ❌ WRONG: Import before sys.path setup
from utils.path_utils import get_project_root
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# ✅ CORRECT: Configure sys.path first
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
from utils.path_utils import get_project_root
```

**Rule**: `sys.path` manipulation must come before any relative imports from the same codebase.

**NameError after loguru migration (logging not defined):**

When migrating from stdlib `logging` to `loguru`, you may encounter:

```
NameError: name 'logging' is not defined
```

**Root Cause**: Removed `import logging` but forgot to update all `logging.getLogger()` calls.

**Solution**: Search and replace all stdlib logging calls:

```python
# ❌ OLD (stdlib logging)
import logging
logger = logging.getLogger("module_name")
logger.warning("message")

# ✅ NEW (loguru)
from wecom_automation.core.logging import get_logger
logger = get_logger("module_name")
logger.warning("message")
```

**Search pattern to find remaining issues**:

```bash
# Find stdlib logging usage
grep -r "logging\.(getLogger|info|debug|warning|error)" --include="*.py"

# Find missing import
grep -r "logging\." --include="*.py" | grep -v "^import logging"
```

**Note**: Backend services and routers may still use stdlib `logging` - only subprocess scripts (like `initial_sync.py`, `realtime_reply_process.py`) need to use loguru for stdout compatibility.

### Debug Mode

Enable debug logging for detailed output:

```bash
# CLI
uv run initial_sync.py --debug --log-file debug.log

# Script
export WECOM_DEBUG="true"
uv run initial_sync.py
```

## Important File Locations

- **Database**: `wecom_conversations.db` (project root, or `WECOM_DB_PATH`) — holds messages/customers/blacklist, unified **`settings`** table, `followup_attempts`, etc.
- **`settings/` directory** (project root): optional legacy/aux files (e.g. `admin_actions.xlsx`); **not** the SQLite file used by `SettingsService`
- **Avatars**: `avatars/` (project root, copied to `wecom-desktop/public/avatars/`)
- **Sync media output root**: `device_storage/<serial>/` by default when sync is started through the backend device manager
- **Conversation Images**: default sync path is `device_storage/<serial>/conversation_images/`; explicit custom output paths can still override this
- **Conversation Videos**: default sync path is `device_storage/<serial>/conversation_videos/`
- **Conversation Voices**: default sync path is `device_storage/<serial>/conversation_voices/`
- **Logs**: `logs/` directory (check `--log-file` argument or backend logs)
- **Sync checkpoints**: `sync_checkpoint_*.json` files (auto-created/cleaned)

## Special Patterns

### Scroll Deduplication

Uses `stable_threshold` (default: 2 consecutive scrolls with no new items) to detect list end. Checksum-based detection via UI tree hash for early termination.

### Voice Message Playback

Voice files are downloaded under the sync output root, typically `device_storage/<serial>/conversation_voices/`. Playback requires PILK library (`pip install pilk`). Web UI supports playback with controls.

### Video Download

Videos are saved under the sync output root, typically `device_storage/<serial>/conversation_videos/`, with duration metadata and thumbnail generation.

### Multi-Device Isolation Reality

Sync and realtime workers are isolated per device at the subprocess level, but the system is not fully isolated end to end. By default, multiple devices can still share:

- `wecom_conversations.db`
- the host ADB server and USB/CPU/disk resources
- the backend orchestration process
- the same AI service endpoint

Treat the current system as **partial isolation**: device execution and sync media outputs are isolated, while parts of the data plane and host resource plane remain shared.

### Email Notifications

Notification system in `services/notification/email.py` for alerting on sync completion/errors.

### Message Deduplication

Messages table uses SHA256 hash (`message_hash`) to prevent duplicate message storage. Same content across messages is detected as duplicates.

### Sidecar Message Queue

Sidecar maintains a message queue to ensure messages are sent to the correct contact, with state verification before sending.

## Critical Async/Await Patterns

### Common Pitfall: Calling Async Functions Without Await

**Problem**: Calling an `async def` function without `await` returns a coroutine object instead of the result. This causes errors like:

- `'coroutine' object is not subscriptable`
- `'coroutine' object has no attribute 'X'`
- `TypeError: object coroutine can't be used in 'await' expression`

**Example of WRONG code:**

```python
# ❌ BAD: Callback is async but called without await
async def ai_reply_callback(customer_name: str, prompt: str) -> str:
    return await generate_ai_reply(customer_name, prompt)

def generate_message(callback):
    # This returns a coroutine object, NOT a string!
    message = callback("John", "Hello")  # ❌ Missing await
    return message[0]  # ❌ Error: 'coroutine' object is not subscriptable
```

**Example of CORRECT code:**

```python
# ✅ GOOD: Function is async and awaits the callback
async def ai_reply_callback(customer_name: str, prompt: str) -> str:
    return await generate_ai_reply(customer_name, prompt)

async def generate_message(callback):
    # Properly await the async callback
    message = await callback("John", "Hello")  # ✅ Correct
    return message[0] if message else ""
```

### Type Hints for Async Callbacks

When passing async functions as callbacks, use proper type hints:

```python
from collections.abc import Awaitable, Callable

# ✅ Correct type hint for async callback
async def process(
    callback: Callable[[str, str], Awaitable[str | None]] | None = None
) -> str:
    if callback:
        result = await callback("arg1", "arg2")
        return result or "default"
    return "default"

# ❌ Wrong type hint (implies sync callback)
async def process_wrong(
    callback: Callable[[str, str], str] | None = None  # Missing Awaitable!
) -> str:
    if callback:
        result = callback("arg1", "arg2")  # Will return coroutine, not str
        return result
```

### Checklist: Async Function Integration

When integrating async functions as callbacks:

1. ✅ Add `Awaitable` to imports: `from collections.abc import Awaitable, Callable`
2. ✅ Update type hints: `Callable[[args], Awaitable[ReturnType]]`
3. ✅ Make caller function `async def` if it wasn't already
4. ✅ Add `await` when calling the callback
5. ✅ Update all callers to `await` the now-async function
6. ✅ Test the full call chain to ensure no coroutine objects leak

### Real-World Example: FollowUp Queue Manager Fix

**Issue**: `ai_reply_callback` was async but called without await in `queue_manager.py`

**Fixed in commit**: Added `await` and proper type hints in `FollowupQueueManager._generate_message()`:

```python
# Before (wrong):
def _generate_message(
    self,
    customer_name: str,
    settings: FollowUpSettings,
    ai_reply_callback: Callable[[str, str], str] | None = None,  # ❌ Wrong type
) -> str:
    if ai_reply_callback:
        message = ai_reply_callback(customer_name, prompt)  # ❌ Missing await

# After (correct):
async def _generate_message(  # ✅ Now async
    self,
    customer_name: str,
    settings: FollowUpSettings,
    ai_reply_callback: Callable[[str, str], Awaitable[str | None]] | None = None,  # ✅ Correct type
) -> str:
    if ai_reply_callback:
        message = await ai_reply_callback(customer_name, prompt)  # ✅ Properly awaited
```

## Related Documentation

### Architecture & Implementation

- `docs/03-impl-and-arch/key-modules/overlay_optimization.md` - DroidRun optimization details
- `docs/03-impl-and-arch/key-modules/sync-execution-flow.md` - Sync process workflow
- `docs/03-impl-and-arch/experiments/MESSAGE_SENDING_FLOW.md` - Message sending workflow
- `docs/03-impl-and-arch/key-modules/database_logic.md` - Database schema and operations

### Feature Documentation

- `docs/01-product/` - Product feature documentation
- `docs/03-impl-and-arch/key-modules/followup-*.md` - Follow-up system design
- `docs/03-impl-and-arch/key-modules/IMAGE_SENDER_INTEGRATION.md` - Image sender integration
- `docs/03-impl-and-arch/key-modules/USAGE_IMAGE_SENDER.md` - Image sender usage guide
- `docs/01-product/blacklist-system.md` - Blacklist feature docs
- `TECHNICAL_HANDOVER.md` - Technical handover documentation

### Monitoring & Robustness (2026-04-09)

- `docs/implementation/2026-04-09-system-robustness-fixes.md` - AI circuit breaker, failure metrics, heartbeat, health checks, auto-restart, night-mode timeout
- `wecom-desktop/backend/services/followup/circuit_breaker.py` - AI call circuit breaker (CLOSED/OPEN/HALF_OPEN)
- `wecom-desktop/backend/services/heartbeat_service.py` - SQLite-backed process heartbeats + AI health storage
- `wecom-desktop/backend/services/ai_health_checker.py` - Periodic 3-layer AI health probe
- `wecom-desktop/backend/routers/monitoring.py` - `/api/monitoring/*` REST endpoints

### Desktop Application

- `wecom-desktop/README.md` - Desktop app documentation
- `wecom-desktop/docs/` - Desktop-specific documentation

### Bugs & Issues

- `docs/04-bugs-and-fixes/` - Known issues and fixes (organized by status)

### Media Auto-Actions

- `docs/implementation/2026-05-14-review-gate-blacklist-registration-and-realtime-notifications.md` - ReviewGate AutoBlacklistAction registration fix + frontend realtime WebSocket notifications
- `docs/implementation/2026-05-13-per-kefu-action-profiles.md` - Per-device action profiles replacing per-kefu model
- `docs/implementation/2026-05-12-media-actions-settings-dedup-ssot.md` - Settings SSOT (single source of truth) for review gate server URL
- `docs/implementation/2026-05-09-contact-share-review-gate.md` - Contact share + review gate integration
- `docs/implementation/2026-05-07-contact-share-reliability.md` - Contact share UI automation reliability fixes
