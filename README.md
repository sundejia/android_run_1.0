# WeCom Automation

> **Enterprise WeChat (WeCom) Automation Framework for Android**
>
> A modular automation framework for WeCom on Android devices using DroidRun's non-LLM APIs.

**[📖 中文文档](README_zh.md)** | **[📚 Documentation Index](docs/INDEX.md)**

## Features

### Core Automation Framework

- ✅ **Launch WeCom**: Automatically start the WeCom app via ADB
- ✅ **Navigate to Private Chats**: Switch message filter to "Private Chats"
- ✅ **Get Current User Name**: Extract the current logged-in WeCom user's name (客服 name) from the UI
- ✅ **Extract User Details**: Extract name, channel, date, message preview, and avatar for all users
- ✅ **Extract Conversation Messages**: Extract all messages from a conversation (text, images, voice, system messages)
- ✅ **Extract Unread Messages**: Identify users with unread messages and their unread counts from badge numbers
- ✅ **Auto-scroll Extraction**: Scroll through the entire list with deduplication
- ✅ **Avatar Screenshots**: Capture avatar images with intelligent bounds detection
- ✅ **Image Message Download**: Download image messages from conversations to local files
- ✅ **Table Output**: Display results in a formatted table
- ✅ **Modular Architecture**: Clean separation of concerns for maintainability
- ✅ **Comprehensive Testing**: 320+ unit tests with integration test support
- ✅ **DroidRun Overlay Optimization**: Optimized for DroidRun's overlay feature with caching, O(1) lookups, and flat-list optimization

### Desktop Application (wecom-desktop)

- ✅ **Desktop GUI**: Electron-based desktop application for managing WeCom automation
- ✅ **Device Mirroring**: Real-time screen mirroring via scrcpy integration
- ✅ **Multi-Device Support**: Connect and manage multiple Android devices simultaneously
- ✅ **Parallel Sync**: Run initial sync operations on multiple devices in parallel with independent processes
- ✅ **Real-Time Status**: WebSocket-based status streaming with per-device isolation
- ✅ **Real-Time Logging**: Live log streaming from each device's sync process
- ✅ **Sidecar View**: Live mirror-aware context (客服 info, recent messages) with a 10s delayed send that pauses when on-device typing is detected
- ✅ **Process Isolation**: Each device runs in its own subprocess for stability
- ✅ **Per-Device Sync Media Storage**: Sync defaults to `device_storage/<serial>/conversation_*` so concurrent devices do not write media into one shared runtime directory
- ✅ **Graceful Stop**: Stop any device's sync at any time without affecting others
- ✅ **Dashboard**: Unified view of synced conversations, devices, 客服, and customers with aggregated statistics
- ✅ **Kefu Drill-Down**: Browse 客服 with search/pagination, open per-agent detail cards, and jump into their customers
- ✅ **Customer Drill-Down**: Browse all synced customers with search, pagination, and deterministic avatar assignment
- ✅ **Customer Detail View**: View individual customer conversations with message breakdown and history
- ✅ **Device Detail Page**: Comprehensive device information page with hardware specs, system info, connection details, and quick actions (sync, mirror, logs)

## Recent Updates (2026-02-05)

- **Architecture Review**: Completed comprehensive code audit ([view report](docs/05-changelog-and-upgrades/2026-02-05-architecture-review.md))
- **Code Cleanup**: Removed deprecated features (Learning Suggestions, Prompt Updates)
- **Path Unification**: Introduced `get_project_root()` for consistent path resolution
- **Script Reorganization**: Moved scripts to `wecom-desktop/backend/scripts/`
- **Kefu Extraction**: Integrated standalone script into backend utils

## Requirements

### Core Framework

- Python >= 3.11
- [uv](https://github.com/astral-sh/uv) package manager
- Android device with USB debugging enabled
- WeCom installed on the device

### Desktop Application (Optional)

- Node.js >= 18.x
- scrcpy installed and in PATH (for device mirroring)
- ADB installed and in PATH

## Quick Start

### Installation

```bash
# Clone and setup
git clone <repo-url>
cd android_run_test

# Create virtual environment and install
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"
```

### Development Setup (Optional)

Set up Git hooks for code quality (recommended for contributors):

```bash
# Install root dependencies (Husky, commitlint, lint-staged)
npm install

# Install frontend dependencies (ESLint, Prettier)
cd wecom-desktop && npm install && cd ..

# Git hooks are now active
# - pre-commit: lint and format staged files
# - commit-msg: validate commit message format
# - pre-push: run type checks and unit tests
```

See [Git Hooks Documentation](docs/00-meta/how-we-document.md) for details.

### Quick Commands

```bash
# List all conversations with avatars
uv run wecom-automation --skip-launch --capture-avatars --output-dir ./output

# List connected Android devices and details
uv run list_devices.py --full --detailed

# Start desktop application (recommended for multi-device management)
cd wecom-desktop && npm start
```

### Deploying to a New Machine or Android Device

Use these rules when you deploy the project onto new hardware:

- **New host machine**: the backend will create the shared control DB automatically if it does not exist. Conversation history is now stored per device under `device_storage/<serial>/wecom_conversations.db`, while settings and orchestration metadata stay in `WECOM_DB_PATH` / `wecom_conversations.db`.
- **New Android device on the same host**: run an initial sync before relying on the Blacklist page, Sidecar history, or follow-up flows. The first sync links the device to a `kefu`, scans customers, and populates the device-scoped blacklist records used by later features.
- **Fresh database behavior**: a brand-new database starts with empty history and empty blacklist content. Features are available after startup, but they have no prior data until sync or follow-up writes records.
- **Three-device concurrency note**: sync workers, sync media output, and sync conversation DB writes now default to device-local paths under `device_storage/<serial>/`. What remains shared by default is the control/settings DB, the backend orchestration process, host resources, and usually the AI endpoint. Dashboard/customers/resources/streamers read a federated aggregate across discovered device DBs unless `db_path` is explicitly provided.

If you are replacing one Android device with another and want to carry over blacklist decisions immediately, copy the old device's blacklist rows to the new device after the backend is running:

```bash
curl -X POST http://localhost:8765/api/blacklist/copy-device \
  -H "Content-Type: application/json" \
  -d '{
    "source_device_serial": "OLD_DEVICE_SERIAL",
    "target_device_serial": "NEW_DEVICE_SERIAL",
    "include_allowed": true,
    "overwrite_existing": true
  }'
```

Notes:

- `include_allowed: true` copies both blocked and allowed rows so the new device keeps the same blacklist-management state.
- `overwrite_existing: true` lets the source device's status win when the target device already has scanned rows for the same customer.

---

### List All Conversations and Capture Avatars

#### Option 1: CLI Command (Recommended)

The simplest way to list all conversations and capture avatars:

```bash
# Full workflow: launch WeCom, switch to Private Chats, extract users with avatars
wecom-automation --capture-avatars --output-dir ./output

# If WeCom is already open, skip the launch step
wecom-automation --skip-launch --capture-avatars --output-dir ./output

# Also export results to JSON
wecom-automation --skip-launch --capture-avatars --output-json users.json --output-dir ./output

# Debug mode with verbose logging
wecom-automation --skip-launch --capture-avatars --debug --log-file debug.log
```

The avatars will be saved to `./output/avatars/` with filenames like `avatar_01_张三.png`.

#### Option 2: Programmatic Usage

Use it in your own Python code:

```python
import asyncio
from wecom_automation.core.config import Config
from wecom_automation.services import WeComService

async def main():
    config = Config()
    service = WeComService(config)

    # Run full workflow with avatar capture
    result = await service.run_full_workflow(
        skip_launch=False,        # Set True if WeCom is already open
        capture_avatars=True,     # Enable avatar screenshots
        output_dir="./output"     # Where to save avatars
    )

    # Print results
    print(f"Found {result.total_count} users")
    print(result.format_table())  # Pretty table output

    # Access individual users
    for user in result.users:
        print(f"Name: {user.name}")
        print(f"Channel: {user.channel}")
        print(f"Date: {user.last_message_date}")
        print(f"Preview: {user.message_preview}")
        if user.avatar and user.avatar.screenshot_path:
            print(f"Avatar saved: {user.avatar.screenshot_path}")

asyncio.run(main())
```

#### Option 3: Step-by-Step Control

For more granular control:

```python
import asyncio
from wecom_automation.core.config import Config
from wecom_automation.services import WeComService

async def extract_with_avatars():
    service = WeComService(Config())

    # Step 1: Launch WeCom
    await service.launch_wecom()

    # Step 2: Navigate to Private Chats
    await service.switch_to_private_chats()

    # Step 3: Extract users with avatar capture
    result = await service.extract_private_chat_users(
        max_scrolls=30,
        capture_avatars=True,
        output_dir="./output"
    )

    return result

asyncio.run(extract_with_avatars())
```

### How Avatar Extraction Works

Avatar extraction is a multi-step process that captures profile pictures from the WeCom conversation list:

1. **Detection**: During user extraction, the system detects avatar elements in the UI tree by their resource IDs and bounds
2. **Bounds Parsing**: Avatar bounds are extracted from the accessibility tree in format `[x1,y1][x2,y2]`
3. **Screenshot Capture**: Full screenshots are taken as the list is scrolled
4. **Cropping**: Avatars are cropped from screenshots using the detected bounds
5. **Validation**: Bounds are validated (size, position, aspect ratio) before saving
6. **Saving**: Valid avatars are saved as PNG files

#### Avatar File Locations

When `--capture-avatars` is enabled, avatars are saved to:

```
{output_dir}/avatars/avatar_{index:02d}_{name}.png
```

Example:

```
./output/avatars/avatar_01_张三.png
./output/avatars/avatar_02_John_Smith.png
./output/avatars/avatar_03_Li_Si.png
```

#### Working with Avatar Data

Access avatar information from extracted users:

```python
from wecom_automation.services import WeComService
from wecom_automation.core.config import Config

async def access_avatar_data():
    service = WeComService(Config())
    result = await service.run_full_workflow(capture_avatars=True)

    for user in result.users:
        if user.avatar:
            # Check if avatar was captured
            if user.avatar.screenshot_path:
                print(f"Avatar saved: {user.avatar.screenshot_path}")

            # Access avatar bounds
            if user.avatar.parse_bounds():
                print(f"Avatar bounds: ({user.avatar.x1}, {user.avatar.y1}) to ({user.avatar.x2}, {user.avatar.y2})")
                print(f"Avatar size: {user.avatar.width}x{user.avatar.height}")

            # Check if avatar is valid
            if user.avatar.is_valid:
                print(f"Valid avatar for {user.name}")
```

#### AvatarInfo Model

The `AvatarInfo` model provides several useful properties:

```python
from wecom_automation.core.models import AvatarInfo

# AvatarInfo attributes
avatar.bounds              # Original bounds string "[x1,y1][x2,y2]"
avatar.resource_id         # Android resource ID
avatar.screenshot_path     # Path to saved image (None if not captured)
avatar.x1, avatar.y1       # Top-left coordinates
avatar.x2, avatar.y2       # Bottom-right coordinates
avatar.width               # Avatar width in pixels
avatar.height              # Avatar height in pixels
avatar.is_valid           # True if bounds are valid

# Methods
avatar.parse_bounds()      # Parse bounds string, returns True if successful
```

#### Avatar Extraction Tips

- **Ensure Pillow is installed**: Avatar capture requires `Pillow>=10.0.0`
- **Sufficient scrolls**: Use `--max-scrolls` to ensure all users are visible
- **Output directory**: Specify `--output-dir` to control where avatars are saved
- **Validation**: The system automatically validates avatar bounds (size 30-300px, valid position)
- **Batch processing**: Avatars are captured in batches as users scroll into view

---

### Verify Messages Screen

Verify whether the current WeCom screen is the main Messages screen. This is useful for automation workflows that need to ensure the device is on the correct screen before performing operations.

#### Using the Script

```bash
# Basic verification (returns YES/NO)
python verify_messages_screen.py

# With device serial
python verify_messages_screen.py --serial AN2FVB1706003302

# Debug mode - shows detailed evaluation criteria
python verify_messages_screen.py --debug

# Use TCP bridge for faster reads
python verify_messages_screen.py --prefer-tcp --debug
```

#### Output

The script returns:

- **YES** (exit code 0) if on Messages screen
- **NO** (exit code 1) if NOT on Messages screen

In debug mode, you'll see detailed information about:

- Top header label detection and text
- Navigation tabs found vs required
- Tab selection state
- Final decision logic

#### Verification Criteria

The script checks:

1. **Top Header Label**: Must be "Messages" (not "Emails", "Doc", "Workspace", or "Contacts")
2. **Navigation Tabs**: All 5 tabs must be present (Messages, Emails, Doc, Workspace, Contacts)
3. **Selection State**: Attempts to detect if Messages tab is selected/highlighted

#### Use Cases

- **Pre-flight checks**: Verify screen state before running automation
- **Debugging**: Understand why automation might be failing
- **Test suites**: Validate screen state in automated tests

For more details, see [Messages Screen Verification](docs/01-product/2025-12-16-verify-messages-screen.md).

### Get Current User Name (客服 Name)

Extract the current logged-in WeCom user's name (客服 name) directly from the UI tree. This feature extracts the user information from the profile panel area without requiring any interface folding/unfolding.

#### Programmatic Usage

```python
import asyncio
from wecom_automation.core.config import Config
from wecom_automation.services import WeComService

async def get_current_user():
    config = Config()
    service = WeComService(config)

    # Get the current user's information
    kefu_info = await service.get_kefu_name()

    if kefu_info:
        print(f"Current user: {kefu_info.name}")
        if kefu_info.department:
            print(f"Department: {kefu_info.department}")
        if kefu_info.verification_status:
            print(f"Status: {kefu_info.verification_status}")
    else:
        print("Could not extract user name")

asyncio.run(get_current_user())
```

#### KefuInfo Model

The `KefuInfo` model contains information about the current logged-in user:

```python
@dataclass
class KefuInfo:
    name: str                              # User name (e.g., "wgz小号")
    department: Optional[str]              # Department/organization (e.g., "302实验室")
    verification_status: Optional[str]     # Verification status (e.g., "未认证")

    def __str__(self) -> str: ...          # Human-readable format
    def to_dict(self) -> Dict: ...         # JSON serialization
```

#### How It Works

1. **UI Tree Analysis**: Parses the accessibility tree to find text elements in the left panel area (profile region)
2. **Position Filtering**: Only considers elements in the upper-left area (x < 500px) where the profile panel is located
3. **Pattern Matching**: Identifies the user name by excluding common UI elements (buttons, labels, etc.)
4. **Context Extraction**: Optionally extracts department and verification status if present

#### Usage Tips

- **WeCom must be open**: The app should be running and showing the main interface
- **Profile panel visible**: The feature works best when the profile panel is visible (typically when the interface is in a folded state)
- **No interaction needed**: The extraction happens directly from the UI tree without requiring any taps or swipes

### CLI Options

```
wecom-automation [OPTIONS]

Device Options:
  --serial TEXT          ADB device serial (omit if only one device)
  --prefer-tcp           Use TCP bridge for faster reads

Workflow Options:
  --skip-launch          Skip launching WeCom (assumes already open)
  --wait-after-launch    Seconds to wait after launch (default: 3.0)

Extraction Options:
  --max-scrolls INT      Maximum scroll attempts (default: 20)
  --scroll-delay FLOAT   Delay between scrolls (default: 1.0)
  --stable-threshold INT Stop after N scrolls with no new entries (default: 2)

Output Options:
  --output-json FILE     Export results to JSON file
  --output-dir PATH      Directory for output files (default: .)
  --capture-avatars      Capture avatar screenshots

Logging Options:
  --debug                Enable debug logging
  --log-file FILE        Write logs to file
```

### Example Output

```
============================================================
EXTRACTION RESULTS - 10 Users Found
============================================================
----------------------------------------------------------------------------------------------------
|  #  | Avatar | Name                 | Channel    | Date         | Preview                        |
----------------------------------------------------------------------------------------------------
|   1 |   ✓    | 张三                  | @WeChat    | 10:30        | Hello, how are you?            |
|   2 |   ✓    | 李四                  | -          | Yesterday    | See you tomorrow!              |
|   3 |   ✓    | John                 | ＠微信      | 6 mins ago   | Meeting at 3pm                 |
----------------------------------------------------------------------------------------------------
Total: 10 users
```

---

### Desktop Application (wecom-desktop)

For a graphical interface to manage multiple devices and run parallel sync operations, use the desktop application built with Electron and Vue.js.

#### Quick Start

```bash
# Install Node.js dependencies
cd wecom-desktop
npm install

# Install Python backend dependencies
cd backend
pip install -r requirements.txt
# Or using uv:
uv pip install fastapi uvicorn websockets pydantic

# Start backend (Terminal 1)
cd backend
uvicorn main:app --reload --port 8765

# Start Electron app (Terminal 2)
cd ..
npm run dev:electron
```

#### Features

- **Multi-Device Management**: Connect and manage multiple Android devices simultaneously
- **Device Mirroring**: Real-time screen mirroring via scrcpy integration
- **Parallel Sync**: Run initial sync operations on multiple devices in parallel
- **Real-Time Monitoring**: WebSocket-based status and log streaming per device
- **Process Isolation**: Each device runs in its own subprocess for stability
- **Graceful Control**: Stop any device's sync independently without affecting others
- **Dashboard**: Unified view of synced conversations with aggregated statistics for devices, 客服, customers, and messages
- **Kefu Management**: Browse/search 客服, view per-agent stats (customers/messages/message mix), and deep-link into their customers
- **Customer Management**: Browse all synced customers with search, pagination, and deterministic avatar assignment
- **Customer Details**: Drill into individual customer conversations with message breakdown and full history

#### Important: Multi-Device Port Configuration

When running sync on multiple devices simultaneously, each device's droidrun app must be configured with a unique port:

- Device 1: Socket Server Port = 8080
- Device 2: Socket Server Port = 8081
- Device 3: Socket Server Port = 8082
- ...

This prevents port conflicts that would cause sync failures.

For detailed documentation, see [wecom-desktop/README.md](wecom-desktop/README.md).

---

## Project Structure

```
android_run_test-backup/
├── docs/                           # 📚 Documentation (248 files)
│   ├── 00-meta/                    # Meta documentation
│   ├── 01-product/                 # Feature specifications
│   ├── 02-prompts-and-iterations/  # AI prompts and session logs
│   ├── 03-impl-and-arch/          # Implementation & architecture
│   │   └── old-archive/            # ⚠️ Archived completed tasks (26 files)
│   ├── 04-bugs-and-fixes/          # Bug tracking
│   ├── 05-changelog-and-upgrades/  # Version history
│   └── INDEX.md                    # 📖 Documentation index
├── src/
│   └── wecom_automation/           # Main package
│       ├── __init__.py             # Package exports & version (v0.2.1)
│       ├── core/                   # 🏗️ Foundation Layer
│       │   ├── __init__.py
│       │   ├── config.py           # Configuration management
│       │   ├── exceptions.py       # Custom exception hierarchy
│       │   ├── models.py           # Data models (dataclasses)
│       │   └── logging.py          # Structured logging utilities
│       ├── services/               # ⚙️ Business Logic Layer
│       │   ├── __init__.py
│       │   ├── adb_service.py      # Low-level ADB interaction
│       │   ├── device_service.py   # Device discovery and enumeration
│       │   ├── ui_parser.py        # UI tree parsing
│       │   └── wecom_service.py    # High-level orchestration
│       └── cli/                    # 🖥️ User Interface Layer
│           ├── __init__.py
│           └── commands.py         # CLI entry point
├── wecom-desktop/                  # 🖥️ Desktop Application
│   ├── electron/                   # Electron main process
│   │   ├── main.ts                 # App entry, window management
│   │   ├── preload.ts              # Secure IPC bridge
│   │   └── scrcpy/                 # Scrcpy integration
│   │       └── mirror.ts           # Mirror window spawning
│   ├── src/                        # Vue.js renderer
│   │   ├── views/                  # Page components
│   │   ├── components/             # Reusable components
│   │   ├── stores/                 # Pinia state management
│   │   └── services/               # API client
│   ├── backend/                    # FastAPI backend
│   │   ├── main.py                 # FastAPI app
│   │   ├── routers/                # API routers
│   │   └── services/               # Business logic
│   └── README.md                   # Desktop app documentation
├── tests/                          # 🧪 Test Suite
│   ├── __init__.py
│   ├── conftest.py                 # Shared pytest fixtures
│   ├── unit/                       # Unit tests (320+ tests)
│   │   ├── test_config.py
│   │   ├── test_device_service.py  # Device discovery tests
│   │   ├── test_exceptions.py
│   │   ├── test_models.py
│   │   └── test_ui_parser.py
│   └── integration/                # Integration tests
│       └── test_workflow.py
├── assets/                         # 📁 Static assets
├── list_devices.py                 # 🔧 Device discovery script (debugging)
├── verify_messages_screen.py       # 🔍 Verify if current screen is Messages screen
├── pyproject.toml                  # Project config & dependencies
├── uv.lock                         # Locked dependencies
└── README.md
```

---

## System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              User Interface                                  │
├────────────────────────────────┬────────────────────────────────────────────┤
│     Electron Desktop App       │           CLI Commands                      │
│   (Vue.js + Pinia + scrcpy)    │      (wecom-automation)                     │
└────────────────┬───────────────┴────────────────────┬───────────────────────┘
                 │ REST + WebSocket                   │ Direct Call
                 ▼                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FastAPI Backend                                     │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌─────────────┐ │
│  │    Routers    │  │   Services    │  │    Workers    │  │  WebSocket  │ │
│  │   (21 files)  │  │  (12 files)   │  │  (scripts/)   │  │   Manager   │ │
│  └───────────────┘  └───────────────┘  └───────────────┘  └─────────────┘ │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │ import / subprocess
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Core Automation Library                                  │
│                    (wecom_automation package)                               │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌─────────────┐ │
│  │      Core     │  │   Services    │  │   Database    │  │  Handlers  │ │
│  │   (models,    │  │  (ADB, UI,    │  │  (SQLite,     │  │ (message   │ │
│  │    config)    │  │   WeCom)      │  │  repository)  │  │   types)   │ │
│  └───────────────┘  └───────────────┘  └───────────────┘  └─────────────┘ │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │ ADB commands
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Android Device Layer                                  │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌─────────────┐ │
│  │   DroidRun    │  │     ADB       │  │    scrcpy     │  │ WeCom App  │ │
│  │   (overlay)   │  │   (control)   │  │   (mirror)    │  │  (target)  │ │
│  └───────────────┘  └───────────────┘  └───────────────┘  └─────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Three-Tier Architecture (Core Library)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          CLI Layer (cli/)                                    │
│   commands.py: Argument parsing, config building, workflow execution         │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │ uses
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Services Layer (services/)                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  WeComService (Orchestrator)                                        │    │
│  │  • launch_wecom() → switch_to_private_chats() → extract_users()     │    │
│  │  • Avatar capture, conversation extraction, kefu detection          │    │
│  └───────────────┬────────────────────────────┬────────────────────────┘    │
│                  │                            │                              │
│     ┌────────────▼────────────┐  ┌────────────▼────────────┐                │
│     │      ADBService         │  │    UIParserService      │                │
│     │  • Device connection    │  │  • Tree parsing         │                │
│     │  • App launch/control   │  │  • Element detection    │                │
│     │  • Tap/Swipe/Scroll     │  │  • User extraction      │                │
│     │  • Screenshots          │  │  • Pattern matching     │                │
│     │  • UI tree fetch        │  │  • Timestamp detection  │                │
│     └────────────┬────────────┘  └─────────────────────────┘                │
│                  │                                                           │
│     ┌────────────▼────────────────────────────────────────────────────┐     │
│     │  Specialized Services                                            │     │
│     │  • SyncOrchestrator: Database sync with checkpoint/recovery      │     │
│     │  • MessageHandlers: Text, Image, Voice, Video processing         │     │
│     │  • BlacklistChecker: Customer filtering                          │     │
│     │  • EmailNotificationService: Sync completion alerts              │     │
│     └──────────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │ uses
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Core Layer (core/)                                   │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐             │
│  │   Config   │  │ Exceptions │  │   Models   │  │  Logging   │             │
│  │ • Settings │  │ • Hierarchy│  │ • UserDetail│  │ • Structured│            │
│  │ • Timing   │  │ • Context  │  │ • Messages │  │ • Timing   │             │
│  │ • Env vars │  │ • Recovery │  │ • Results  │  │ • Metrics  │             │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘             │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────┐       │
│  │  Database Layer (database/)                                       │       │
│  │  • Schema: devices, kefus, customers, conversations, messages     │       │
│  │  • Repository: CRUD operations with SQLite                        │       │
│  │  • Models: ORM-style data classes                                 │       │
│  └──────────────────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Desktop Application Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Electron Main Process                                 │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │  main.ts: Window management, IPC, native APIs                       │     │
│  │  preload.ts: Secure bridge between main and renderer                │     │
│  │  scrcpy/mirror.ts: Device mirroring window management               │     │
│  └────────────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │ IPC
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Vue.js Renderer Process (src/)                           │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────────────────┐     │
│  │     Views      │  │   Components   │  │         Stores             │     │
│  │  (17 views)    │  │  (charts, UI)  │  │    (Pinia state)           │     │
│  │  • Dashboard   │  │  • DeviceCard  │  │  • devices, customers      │     │
│  │  • Customers   │  │  • LogStream   │  │  • kefus, settings         │     │
│  │  • Sidecar     │  │  • SyncButton  │  │  • sidecarQueue            │     │
│  │  • Settings    │  │  • Charts      │  │  • globalWebSocket         │     │
│  └────────────────┘  └────────────────┘  └────────────────────────────┘     │
│                             │                                                │
│                             │ API calls                                      │
│  ┌──────────────────────────▼───────────────────────────────────────┐       │
│  │  Services: api.ts (REST), aiService.ts, globalWebSocket          │       │
│  └──────────────────────────────────────────────────────────────────┘       │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │ HTTP + WebSocket
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FastAPI Backend (backend/)                           │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │  Routers (21 API modules)                                          │     │
│  │  • devices.py: Device CRUD, status, control                        │     │
│  │  • sync.py: Initial sync operations                                │     │
│  │  • sidecar.py: Real-time context, message queue                    │     │
│  │  • followup_manage.py: Follow-up message configuration             │     │
│  │  • customers.py, kefus.py: Data queries                            │     │
│  │  • dashboard.py: Aggregated statistics                             │     │
│  │  • settings.py: Application configuration                          │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │  Services                                                           │     │
│  │  • DeviceManager: Process lifecycle, subprocess management         │     │
│  │  • FollowUpService: Automated follow-up message scheduling         │     │
│  │  • SettingsService: Configuration persistence (SQLite)             │     │
│  │  • WebSocketManager: Real-time status broadcasting                 │     │
│  │  • RecoveryManager: Checkpoint-based sync recovery                 │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │  Scripts (subprocess workers)                                       │     │
│  │  • initial_sync.py: Per-device sync process                        │     │
│  │  • realtime_reply_process.py: AI reply detection                   │     │
│  └────────────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Data Flow Diagram

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Android    │     │   DroidRun   │     │   Backend    │     │   Frontend   │
│   Device     │     │   + ADB      │     │   (FastAPI)  │     │   (Vue.js)   │
└──────┬───────┘     └──────┬───────┘     └──────┬───────┘     └──────┬───────┘
       │                    │                    │                    │
       │  UI Tree (XML)     │                    │                    │
       │◄───────────────────│                    │                    │
       │                    │                    │                    │
       │                    │  Parse & Extract   │                    │
       │                    │───────────────────►│                    │
       │                    │                    │                    │
       │                    │                    │  Save to SQLite    │
       │                    │                    │─────────┐          │
       │                    │                    │         │          │
       │                    │                    │◄────────┘          │
       │                    │                    │                    │
       │                    │                    │  REST API Response │
       │                    │                    │───────────────────►│
       │                    │                    │                    │
       │                    │                    │  WebSocket Status  │
       │                    │                    │◄──────────────────►│
       │                    │                    │                    │
       │  Tap/Swipe         │                    │                    │
       │◄───────────────────│◄───────────────────│◄───────────────────│
       │                    │                    │                    │
```

### Database Schema

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   devices   │────►│    kefus    │────►│  customers  │
│  (Android   │ 1:N │  (客服账号)  │ 1:N │  (客户)     │
│   devices)  │     │             │     │             │
└─────────────┘     └──────┬──────┘     └──────┬──────┘
                           │                   │
                           └─────────┬─────────┘
                                     │ N:1
                              ┌──────▼──────┐
                              │conversations│
                              │ (会话关联)   │
                              └──────┬──────┘
                                     │ 1:N
                              ┌──────▼──────┐     ┌─────────────┐
                              │  messages   │────►│  resources  │
                              │  (消息)     │ 1:1 │ (媒体文件)   │
                              └─────────────┘     └─────────────┘

Additional Tables:
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  settings   │  │sync_checkpts│  │  ai_replies │  │  blacklist  │
│ (配置存储)   │  │ (同步断点)   │  │ (AI回复记录) │  │  (黑名单)   │
└─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘
```

### Key Design Patterns

| Pattern                 | Implementation                                | Purpose                       |
| ----------------------- | --------------------------------------------- | ----------------------------- |
| **Repository**          | `ConversationRepository`                      | Data access abstraction       |
| **Service Layer**       | `WeComService`, `FollowUpService`             | Business logic orchestration  |
| **Handler Chain**       | `MessageHandlers` (text, image, voice, video) | Extensible message processing |
| **Observer**            | WebSocket broadcasting                        | Real-time UI updates          |
| **Checkpoint/Recovery** | `SyncCheckpoint`                              | Interruptible long operations |
| **Process Isolation**   | Subprocess per device                         | Stability and parallelism     |
| **TTL Cache**           | `UIStateCache`                                | Performance optimization      |

---

## Layer Details

### 1. Core Layer (`src/wecom_automation/core/`)

Foundation components providing shared infrastructure:

| Module          | Purpose                                                     | Key Classes/Functions                                                                                                                          |
| --------------- | ----------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `config.py`     | Centralized configuration with environment variable support | `Config`, `TimingConfig`, `ScrollConfig`, `AppConfig`, `get_project_root()`                                                                    |
| `exceptions.py` | Hierarchical exceptions with context for debugging          | `WeComAutomationError`, `UIElementNotFoundError`, `DeviceConnectionError`, `NavigationError`, `TimeoutError`                                   |
| `models.py`     | Immutable dataclasses for type-safe data handling           | `UserDetail`, `AvatarInfo`, `MessageEntry`, `ExtractionResult`, `ConversationMessage`, `ConversationExtractionResult`, `ImageInfo`, `KefuInfo` |
| `logging.py`    | Structured logging with timing utilities                    | `setup_logger()`, `get_logger()`, `log_operation()`                                                                                            |

### 2. Services Layer (`src/wecom_automation/services/`)

Business logic with clean separation of concerns:

| Service                    | Responsibility                                                                                   | Dependencies                    |
| -------------------------- | ------------------------------------------------------------------------------------------------ | ------------------------------- |
| `WeComService`             | Orchestrate complete workflows: launch → navigate → extract → capture avatars → sync to database | `ADBService`, `UIParserService` |
| `ADBService`               | Device interaction: launch apps, tap, swipe, screenshots, UI tree retrieval                      | `droidrun`, `Config`            |
| `UIParserService`          | Parse accessibility trees, detect elements, extract user data, pattern matching                  | `Config`                        |
| `SyncOrchestrator`         | Database synchronization with checkpoint/recovery support                                        | `CustomerSyncer`, `Repository`  |
| `BlacklistChecker`         | Customer filtering based on configurable rules                                                   | `Repository`                    |
| `EmailNotificationService` | Send completion/error notifications                                                              | SMTP configuration              |

### 3. Backend Layer (`wecom-desktop/backend/`)

FastAPI application providing REST API and WebSocket:

| Component    | Files      | Purpose                                            |
| ------------ | ---------- | -------------------------------------------------- |
| **Routers**  | 21 modules | API endpoints for all features                     |
| **Services** | 12 modules | Business logic and process management              |
| **Scripts**  | 5 scripts  | Subprocess workers for long operations             |
| **Utils**    | 3 modules  | Shared utilities (`path_utils`, `kefu_extraction`) |

### 4. Frontend Layer (`wecom-desktop/src/`)

Vue.js SPA with Pinia state management:

| Component      | Count | Purpose                       |
| -------------- | ----- | ----------------------------- |
| **Views**      | 17    | Page-level components         |
| **Components** | 12    | Reusable UI elements          |
| **Stores**     | 12    | Centralized state management  |
| **Services**   | 2     | API client and AI integration |

**Entry Point:** `wecom-automation` → `cli.commands:main`

---

## Data Models

### DeviceInfo

Information about a connected Android device:

```python
@dataclass
class DeviceInfo:
    serial: str                              # Device serial (USB, emulator, or TCP)
    state: str                               # Connection state (device, offline, etc.)
    product: Optional[str]                   # Product identifier
    model: Optional[str]                     # Device model
    device: Optional[str]                     # Device codename
    manufacturer: Optional[str]              # Manufacturer name
    brand: Optional[str]                     # Brand name
    android_version: Optional[str]            # Android version (e.g., "14")
    sdk_version: Optional[str]               # SDK version (e.g., "34")
    hardware: Optional[str]                   # Hardware platform
    abi: Optional[str]                       # CPU ABI (e.g., "arm64-v8a")
    screen_resolution: Optional[str]          # Screen resolution (e.g., "1080x2400")
    screen_density: Optional[str]            # Screen density (e.g., "420")
    memory_total: Optional[str]               # Total RAM (e.g., "8.00 GB")
    battery_level: Optional[str]             # Battery level (e.g., "85%")
    battery_status: Optional[str]             # Battery status (Charging, Discharging, etc.)
    usb_debugging: Optional[bool]            # USB debugging enabled
    wifi_mac: Optional[str]                  # WiFi MAC address
    internal_storage: Optional[str]           # Storage info (e.g., "20G available of 64G")
    extra_props: Dict[str, str]               # Additional properties

    # Properties
    is_online: bool                          # True if device is ready
    connection_type: str                     # "tcp", "emulator", "usb", or "unknown"
    ip_address: Optional[str]                # IP address (for TCP connections)
    tcp_port: Optional[int]                  # TCP port (for TCP connections)
    endpoint: str                            # Human-readable endpoint description

    def to_dict(self) -> Dict: ...           # JSON serialization
```

### UserDetail

The primary model for extracted chat users:

```python
@dataclass
class UserDetail:
    name: str                              # Contact name (required)
    channel: Optional[str]                 # Source (e.g., "@WeChat")
    last_message_date: Optional[str]       # Timestamp
    message_preview: Optional[str]         # Message snippet
    avatar: Optional[AvatarInfo]           # Avatar information
    droidrun_index: Optional[int]          # DroidRun overlay index for reliable tapping

    def unique_key(self) -> str: ...       # For deduplication
    def merge_with(other) -> UserDetail: ...  # Combine partial data
    def to_dict(self) -> Dict: ...         # JSON serialization
    @classmethod
    def from_dict(cls, data) -> UserDetail: ...  # Deserialization
```

### ExtractionResult

Container for user extraction results with metadata:

```python
@dataclass
class ExtractionResult:
    users: List[UserDetail]          # Extracted users
    extraction_time: datetime        # When extraction ran
    total_scrolls: int               # Scroll count
    duration_seconds: float          # Time taken
    success: bool                    # Success status
    error_message: Optional[str]     # Error if failed

    def format_table(self) -> str: ...    # Pretty table output
    def to_dict(self) -> Dict: ...        # JSON export
```

### ConversationMessage

Represents a single message in a conversation:

```python
@dataclass
class ConversationMessage:
    content: Optional[str]              # Text content
    timestamp: Optional[str]             # Time sent
    is_self: bool                       # True if sent by current user
    message_type: str                   # "text", "image", "voice", "system"
    image: Optional[ImageInfo]          # Image information
    voice_duration: Optional[str]       # Voice duration string
    sender_name: Optional[str]          # Sender name (group chats)
    sender_avatar: Optional[AvatarInfo] # Sender avatar

    def unique_key(self) -> str: ...    # For deduplication
    def format(self, index: int) -> str: ...  # Format for display
    def to_dict(self) -> Dict: ...      # JSON serialization
```

### ConversationExtractionResult

Container for conversation extraction results:

```python
@dataclass
class ConversationExtractionResult:
    messages: List[ConversationMessage]  # All extracted messages
    contact_name: Optional[str]          # Contact name
    contact_channel: Optional[str]       # Contact channel
    extraction_time: datetime            # When extraction ran
    total_scrolls: int                   # Scroll count
    duration_seconds: float              # Time taken
    images_downloaded: int               # Images downloaded
    success: bool                        # Success status

    # Properties
    total_count: int                     # Total message count
    text_count: int                      # Text message count
    image_count: int                     # Image message count
    self_count: int                      # Messages from self
    other_count: int                     # Messages from others

    def format_summary(self) -> str: ...    # Summary output
    def format_messages(self) -> str: ...    # All messages formatted
    def to_dict(self) -> Dict: ...           # JSON export
```

### ImageInfo

Information about an image in a conversation message:

```python
@dataclass
class ImageInfo:
    bounds: Optional[str]            # UI bounds "[x1,y1][x2,y2]"
    resource_id: Optional[str]       # Android resource ID
    content_description: Optional[str]  # Accessibility description
    local_path: Optional[str]        # Path to downloaded image

    # Parsed bounds
    x1, y1, x2, y2: int              # Coordinates
    width: int                        # Image width
    height: int                       # Image height
    is_valid: bool                    # True if bounds are valid

    def parse_bounds(self) -> bool: ...  # Parse bounds string
    def to_dict(self) -> Dict: ...       # JSON serialization
```

### KefuInfo

Information about the current logged-in WeCom user (客服):

```python
@dataclass
class KefuInfo:
    name: str                         # User name (e.g., "wgz小号")
    department: Optional[str]         # Department/organization (e.g., "302实验室")
    verification_status: Optional[str]  # Verification status (e.g., "未认证")

    def __str__(self) -> str: ...     # Human-readable format
    def to_dict(self) -> Dict: ...    # JSON serialization
```

---

## Testing

### Test Organization

**⚠️ IMPORTANT**: All test files MUST be placed in designated test directories. See [Test Organization Rules](docs/development/test-organization.md) for details.

```
tests/
├── conftest.py                    # Shared fixtures (mock configs, sample data)
├── unit/                          # Fast, isolated tests (no device required)
│   ├── test_config.py             # Config loading, env vars, defaults
│   ├── test_exceptions.py         # Exception context, formatting
│   ├── test_models.py             # Serialization, methods, edge cases
│   └── test_ui_parser.py          # Parsing patterns, timestamps, channels
└── integration/                   # Real device tests
    └── test_workflow.py           # Full workflow execution

wecom-desktop/backend/tests/       # Backend API tests
├── test_sidecar_api.py
├── test_followup_device_manager.py
└── test_device_manager.py
```

**Rules**:

- ✅ Place tests in `tests/unit/` or `tests/integration/`
- ❌ Never create `test_*.py` in project root
- ❌ Never create tests in `src/` or `scripts/`

### Run Tests

```bash
# All unit tests
pytest tests/unit/ -v

# With coverage report
pytest tests/unit/ --cov=src/wecom_automation --cov-report=html

# Specific test file
pytest tests/unit/test_ui_parser.py -v

# Integration tests (requires device)
pytest tests/integration/ -v -m integration

# Backend API tests
pytest wecom-desktop/backend/tests/ -v
```

### Test Categories

| Category    | Location                       | Purpose                          | Requirements     |
| ----------- | ------------------------------ | -------------------------------- | ---------------- |
| Unit        | `tests/unit/`                  | Fast, isolated component testing | None             |
| Integration | `tests/integration/`           | Full workflow with real device   | Connected device |
| Backend API | `wecom-desktop/backend/tests/` | FastAPI routes and services      | None             |

---

## Configuration

### Environment Variables

```bash
export WECOM_DEVICE_SERIAL="ABC123"     # Device serial
export WECOM_USE_TCP="true"             # Use TCP bridge
export WECOM_DEBUG="true"               # Enable debug mode
export WECOM_OUTPUT_DIR="./output"      # Output directory
export WECOM_MAX_SCROLLS="30"           # Max scroll attempts
```

### Programmatic Configuration

```python
from wecom_automation.core.config import Config, TimingConfig

# Custom configuration
config = Config(
    timing=TimingConfig(wait_after_launch=5.0),
    device_serial="ABC123",
    debug=True,
)

# Or from environment
config = Config.from_env()

# Override specific values
config = config.with_overrides(debug=True)
```

---

## API Usage

### Basic Usage

```python
import asyncio
from wecom_automation.core.config import Config
from wecom_automation.services import WeComService

async def main():
    config = Config()
    service = WeComService(config)

    # Run full workflow with avatar capture
    result = await service.run_full_workflow(
        skip_launch=False,
        capture_avatars=True,
        output_dir="./output"
    )

    print(f"Extracted {result.total_count} users")
    for user in result.users:
        print(f"  - {user.name}: {user.message_preview}")
        if user.avatar and user.avatar.screenshot_path:
            print(f"    Avatar: {user.avatar.screenshot_path}")

asyncio.run(main())
```

### Using Individual Services

```python
from wecom_automation.core.config import Config
from wecom_automation.services import ADBService, UIParserService, DeviceDiscoveryService

async def low_level_example():
    config = Config()
    adb = ADBService(config)
    parser = UIParserService(config)

    # Get UI tree
    tree = await adb.get_ui_tree()

    # Parse users
    users = parser.extract_users_from_tree(tree)

    # Take screenshot
    filename, data = await adb.take_screenshot()

async def device_discovery_example():
    # List all connected devices
    discovery = DeviceDiscoveryService()
    devices = await discovery.list_devices(
        include_properties=True,
        include_runtime_stats=True,
    )

    for device in devices:
        print(f"{device.serial}: {device.model} ({device.android_version})")
        if device.is_online:
            print(f"  Battery: {device.battery_level}")
            print(f"  Memory: {device.memory_total}")

    # Get specific device info
    device = await discovery.get_device(
        "R58M35XXXX",
        include_properties=True,
        include_runtime_stats=True,
    )
    print(device.to_dict())
```

---

## Extending the Framework

### Add a New Service

```python
# src/wecom_automation/services/my_service.py
from wecom_automation.core.config import Config
from wecom_automation.core.logging import get_logger

class MyService:
    def __init__(self, config: Config):
        self.config = config
        self.logger = get_logger("wecom_automation.my_service")

    async def do_something(self):
        self.logger.info("Doing something...")
        # Implementation
```

### Add Custom Exceptions

```python
from wecom_automation.core.exceptions import WeComAutomationError

class MyCustomError(WeComAutomationError):
    def __init__(self, message: str, custom_field: str = None, **kwargs):
        context = kwargs.pop("context", {})
        if custom_field:
            context["custom_field"] = custom_field
        super().__init__(message, context=context, **kwargs)
```

### Add New Data Models

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class MyModel:
    field1: str
    field2: Optional[str] = None

    def to_dict(self) -> dict:
        return {"field1": self.field1, "field2": self.field2}
```

---

## DroidRun Overlay Optimization

The framework includes comprehensive optimizations for DroidRun's overlay feature, which displays numbered overlays on UI elements. See [docs/overlay_optimization.md](docs/overlay_optimization.md) for full details.

### Key Optimizations

| Optimization       | Benefit                                                                          |
| ------------------ | -------------------------------------------------------------------------------- |
| **UIStateCache**   | TTL-based caching with auto-invalidation after UI-modifying operations           |
| **get_ui_state()** | Single ADB call instead of separate `get_ui_tree()` + `get_clickable_elements()` |
| **Hash Detection** | Skip re-parsing when UI unchanged (useful for scroll-end detection)              |
| **Text Indexing**  | O(1) element lookup instead of O(n) list traversal                               |
| **Flat-List Mode** | Skip recursive child search for flat `clickable_elements_cache`                  |
| **droidrun_index** | Store overlay indices in data models for reliable tapping                        |

### Quick Example

```python
from wecom_automation.services.adb_service import ADBService
from wecom_automation.core.config import Config

async def optimized_workflow():
    adb = ADBService(Config())

    # Single ADB call for both tree and elements
    tree, elements = await adb.get_ui_state()

    # O(1) lookup by text
    messages = adb.find_by_text_indexed("Messages")

    # Direct tap by overlay index
    await adb.tap_by_index(5)

    # Check if UI changed after action
    await adb._refresh_ui_state()
    if adb.is_tree_unchanged():
        print("UI didn't change - maybe reached end of list")
```

---

## Technical Details

| Feature                 | Implementation                                                                     |
| ----------------------- | ---------------------------------------------------------------------------------- |
| **ADB Interaction**     | Uses `droidrun<=0.4.13` for device communication                                   |
| **Image Processing**    | Pillow for avatar screenshot cropping                                              |
| **UI Parsing**          | Heuristic parsing via resource ID keywords and pattern matching                    |
| **Language Support**    | Chinese (中文) and English UI patterns                                             |
| **Timestamp Detection** | Relative times ("6 mins ago", "3分钟前"), dates, day names                         |
| **Avatar Inference**    | When ImageView not in accessibility tree, infers bounds from row layout            |
| **Badge Detection**     | Detects unread badges by position (top-right of avatar), size, and numeric content |
| **Deduplication**       | `UserDetail.unique_key()` based on name + channel                                  |

---

## Troubleshooting

| Issue                    | Solution                                               |
| ------------------------ | ------------------------------------------------------ |
| Device not found         | Check `adb devices`, ensure USB debugging enabled      |
| UI elements not detected | Increase `--wait-after-launch`, ensure device unlocked |
| Import errors            | Ensure Python >= 3.11 (`python --version`)             |
| Tests failing            | Run `pytest tests/unit/ -v` to see specific failures   |
| Avatar capture fails     | Ensure Pillow is installed (`uv pip install Pillow`)   |

For more help, see [Bugs & Fixes](docs/04-bugs-and-fixes/) documentation.

---

## Dependencies

### Runtime

| Package    | Version | Purpose                      |
| ---------- | ------- | ---------------------------- |
| `droidrun` | ≤0.4.13 | ADB device interaction       |
| `Pillow`   | ≥10.0.0 | Image processing for avatars |

### Development

| Package          | Version | Purpose            |
| ---------------- | ------- | ------------------ |
| `pytest`         | ≥7.0.0  | Test framework     |
| `pytest-asyncio` | ≥0.21.0 | Async test support |
| `pytest-cov`     | ≥4.0.0  | Coverage reporting |

---

## License

MIT

---

**Project Status**: ✅ Active Development  
**Last Updated**: 2026-02-05  
**Version**: 0.2.1  
**Documentation**: [docs/INDEX.md](docs/INDEX.md)  
**Architecture Review**: [docs/05-changelog-and-upgrades/2026-02-05-architecture-review.md](docs/05-changelog-and-upgrades/2026-02-05-architecture-review.md)
