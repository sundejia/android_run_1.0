# WeCom Desktop 企业微信桌面管控应用

A desktop application for WeCom (企业微信) automation on Android devices. Built with Electron, Vue.js, and FastAPI.

企业微信自动化桌面应用，用于管理和同步多台Android设备上的企业微信数据。

## Features 功能特性

- **Device Mirroring 设备镜像**: Real-time screen mirroring via scrcpy / 通过scrcpy实时镜像设备屏幕
- **Multi-Device Support 多设备支持**: Connect and manage multiple Android devices simultaneously / 同时连接和管理多台Android设备
- **Parallel Sync 并行同步**: Run initial sync operations on multiple devices in parallel with independent processes / 在多台设备上并行运行同步操作，每台设备独立进程
- **Real-Time Status 实时状态**: WebSocket-based status streaming with per-device isolation / 基于WebSocket的实时状态推送，每台设备独立隔离
- **Real-Time Logging 实时日志**: Live log streaming from each device's sync process; drag device tabs into the Logs area to view multiple devices side-by-side (limit is settings-driven, defaults to 3) / 每台设备同步进程的实时日志流；将设备标签拖入日志区域可并排查看多台设备（数量由设置驱动，默认3台）
- **Sidecar 实时侧边窗**: Live mirrored context pane with conversation detection, 客服信息, and a delayed-send workflow that pauses if the device is typing; open from the sidebar and view multiple devices side-by-side (limit is settings-driven, defaults to 3) / 实时侧边窗展示会话状态与客服信息，提供延迟发送并在设备输入时自动暂停；可从侧边栏打开，并行显示多台设备（数量由设置驱动，默认3台）
- **Process Isolation 进程隔离**: Each device runs in its own subprocess for stability / 每台设备在独立子进程中运行，确保稳定性
- **Graceful Stop 优雅停止**: Stop any device's sync at any time without affecting others / 随时停止任意设备的同步，不影响其他设备
- **Dashboard 仪表盘**: Unified view of synced conversations, devices, 客服, and customers / 统一的会话、设备、客服和客户视图
- **Customers Drill-Down 客户下钻**: Click “Customers” to browse all synced customers, view avatars, and open per-customer conversation details / 点击“Customers”浏览已同步客户，查看头像并进入单个客户会话详情
- **Kefu Drill-Down 客服下钻**: Click “客服” to browse all agents, then open a specific 客服 to see their customers and jump into any customer detail / 点击“客服”浏览所有客服，再进入单个客服查看其客户并继续跳转到客户详情
- **Device Detail Page 设备详情页**: Click any device card to view full hardware/build/connection stats (brand, SDK/API, security patch, hardware/ABI, density, memory, storage, battery status, USB debugging, endpoint/IP/transport, extra props) and act (mirror, sync, logs) directly / 点击设备卡片可查看完整硬件、系统、连接信息（品牌、SDK/API、安全补丁、硬件/ABI、屏幕密度、内存、存储、电池状态、USB调试、终端/IP/传输ID、额外属性）并直接操作镜像、同步、日志

## Architecture 架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Electron App (Vue.js)                    │
│                    Electron 桌面应用                          │
├─────────────────────────────────────────────────────────────┤
│  Device List │ Mirror Windows │ Logs Panel │ Sync Controls  │
│  设备列表     │ 镜像窗口        │ 日志面板    │ 同步控制       │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST + WebSocket
┌──────────────────────────▼──────────────────────────────────┐
│                   FastAPI Backend                            │
│                   FastAPI 后端服务                            │
├─────────────────────────────────────────────────────────────┤
│  /devices │ /sync │ /ws/logs/{serial} │ /ws/sync/{serial}   │
│  设备管理   │ 同步   │ 日志WebSocket      │ 状态WebSocket      │
└──────────────────────────┬──────────────────────────────────┘
                           │ Subprocess (独立子进程)
┌──────────────────────────▼──────────────────────────────────┐
│            wecom_automation package (Python)                 │
│  InitialSyncService, ADBService, ConversationRepository     │
│  初始同步服务, ADB服务, 会话数据仓库                            │
└─────────────────────────────────────────────────────────────┘
```

## Prerequisites

- **Node.js** >= 18.x
- **Python** >= 3.11
- **scrcpy** installed (we auto-detect bundled paths, common install paths like `/opt/homebrew/bin/scrcpy`, `/usr/local/bin/scrcpy`, and honor `SCRCPY_PATH` when PATH is missing)
- **ADB** installed and in PATH
- Android device(s) with USB debugging enabled

### Installing scrcpy

**macOS (Homebrew)**:
```bash
brew install scrcpy
```

**Windows (Chocolatey)**:
```bash
choco install scrcpy
```

**Linux**:
```bash
sudo apt install scrcpy  # Debian/Ubuntu
```

## Installation

### 1. Install Node.js dependencies

```bash
cd wecom-desktop
npm install
```

### 2. Install Python dependencies

There is **no** `requirements.txt` under `backend/`. Install the **workspace Python package** from the **repository root** (editable install with dev extras):

```bash
cd ..   # repository root (parent of wecom-desktop)
uv sync --extra dev
```

Run the API with the same environment (from `backend/`):

```bash
cd wecom-desktop/backend
uv run uvicorn main:app --reload --port 8765
```

If you use a project `.venv` only, activate it first, then `pip install -e ".[dev]"` from the repo root per the main [README.md](../README.md).

## Running the Application

### Development Mode

**Terminal 1 - Start the backend:**
```bash
cd wecom-desktop/backend
uvicorn main:app --reload --port 8765
```

**Terminal 2 - Start the Electron app:**
```bash
cd wecom-desktop
npm run dev:electron
```

Or run both together:
```bash
npm start
```

### One-Click Dev Redeploy (stop → build → restart)

From repo root, run:
```bash
cd wecom-desktop
./scripts/redeploy-dev.sh
```

What it does:
- Stops anything on ports `5173` (frontend) and `8765` (backend)
- Builds renderer/electron (`npm run build`) unless you pass `--skip-build`
- Restarts backend (`uvicorn main:app --reload --port 8765`) and frontend (`npm run dev -- --host --port 5173`)
- Writes logs to `wecom-desktop/logs/backend.dev.log` and `wecom-desktop/logs/frontend.dev.log`

Use `./scripts/redeploy-dev.sh --skip-build` if you just want a fast restart without the build step.

### Production Build

```bash
npm run build
```

## API Endpoints

### Devices
- `GET /devices` - List all connected devices (returns rich metadata: state, product/model/device/brand, SDK/API, security patch, build ID, hardware/ABI, screen density/resolution, memory, battery level/status, USB debugging, storage, connection info, endpoint/IP/transport, extra props)
- `GET /devices/{serial}` - Get device details (same rich fields as above)
- `POST /devices/refresh` - Refresh device list

### Sync

- `POST /sync/start` - Start sync on device(s)
- `POST /sync/stop/{serial}` - Stop sync on a device
- `GET /sync/status/{serial}` - Get sync status
- `GET /sync/status` - Get all sync statuses

### Dashboard

- `GET /dashboard/overview` - Get aggregated dashboard data (stats, devices, 客服, recent conversations) across discovered device DBs by default

### Kefu 客服

- `GET /kefus` - List kefu with coverage stats (supports `limit`, `offset`, `search`)
- `GET /kefus/{id}` - Kefu detail with customers list and message-type breakdown (supports `customers_limit`, `customers_offset`)

### Customers

- `GET /customers` - List customers with conversation metadata (supports `limit`, `offset`, `search`) and federates across device DBs unless `db_path` is provided
- `GET /customers/{id}` - Customer detail with latest messages and per-type breakdown (supports `messages_limit`, `messages_offset`)

### Sidecar

- `GET /sidecar/{serial}/state` - Snapshot the mirrored device UI state (conversation flag, 客服 info, last focus text, and the five most recent messages)
- `POST /sidecar/{serial}/send` - Send a prepared message from the device (used by the 10s delayed send workflow in the sidecar view)

### Settings

- `GET /settings/performance/profile` - Get effective performance profile (low-spec resolution + runtime metrics snapshot)

### WebSocket

- `ws://localhost:8765/ws/logs/{serial}` - Real-time log stream
- `ws://localhost:8765/ws/sync/{serial}` - Real-time sync status

## Project Structure

```
wecom-desktop/
├── electron/                 # Electron main process
│   ├── main.ts              # App entry, window management
│   ├── preload.ts           # Secure IPC bridge
│   └── scrcpy/              # Scrcpy integration
│       └── mirror.ts        # Mirror window spawning
├── src/                     # Vue.js renderer
│   ├── views/               # Page components
│   ├── components/          # Reusable components
│   ├── stores/              # Pinia state management
│   └── services/            # API client
├── backend/                 # FastAPI backend
│   ├── main.py              # FastAPI app
│   ├── routers/             # API routers
│   └── services/            # Business logic
└── package.json
```

## Usage 使用说明

1. **Connect Devices 连接设备**: Connect your Android device(s) via USB with USB debugging enabled / 通过USB连接Android设备并启用USB调试
2. **Configure droidrun ports 配置droidrun端口**: Each device must use a unique droidrun socket port (e.g., 8080, 8081) / 每台设备必须使用不同的droidrun端口
3. **Start Backend 启动后端**: Run the FastAPI backend server / 运行FastAPI后端服务
4. **Launch App 启动应用**: Start the Electron application / 启动Electron应用
5. **Select Devices 选择设备**: Check the devices you want to work with / 勾选要操作的设备
6. **Start Mirror 启动镜像**: Click the Mirror button to see the device screen / 点击Mirror按钮查看设备屏幕
7. **Run Sync 运行同步**: Click "Sync Selected" to start the WeCom conversation sync / 点击"Sync Selected"开始同步企业微信会话
8. **View Logs 查看日志**: Navigate to the Logs tab to see real-time progress; drag a device tab into the log area (or click it) to open panes side-by-side (limit is controlled by settings) / 切换到Logs标签查看实时进度；将设备标签拖入日志区域（或直接点击）即可并排打开面板（数量由设置控制）
9. **Stop Anytime 随时停止**: Click Stop on any device to halt its sync without affecting others / 点击任意设备的Stop按钮停止同步，不影响其他设备
10. **View Device Details 查看设备详情**: Click any device card to open the detailed device information page / 点击任意设备卡片打开设备详细信息页面

## New Device Onboarding 新设备上线

- **New host / 新主机**: backend startup will create the shared control DB automatically. Existing settings/orchestration metadata can be carried over via `WECOM_DB_PATH`, while synced conversation history now lives in per-device DBs under `device_storage/<serial>/wecom_conversations.db`.
- **New Android device / 新安卓设备**: connect the phone, start the backend, and run an initial sync before relying on the Blacklist page, Sidecar history, or follow-up workflows. The first sync creates the device-to-kefu link and writes the scanned customer rows used by those features.
- **Optional blacklist migration / 可选黑名单迁移**: if you are replacing an old Android device, you can copy the old device's blacklist rows to the new one with:

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

- `include_allowed: true` keeps both blocked and allowed records in sync between devices.
- `overwrite_existing: true` applies the source device's status when the target device already has matching scanned rows.

## Sidecar View 侧边窗

- **Access 访问**: Open `/sidecar/{serial}` in the renderer (dev server or Electron) to monitor the mirrored device and prepare messages without launching the full mirror window / 在渲染进程中打开 `/sidecar/{serial}`，无需启动完整镜像即可监控设备并准备消息
- **Features 功能**: Shows conversation presence, cached 客服信息, last 5 messages, and a 10s delayed send that pauses when device focus/text changes (typing detected) / 展示会话状态、客服缓存、最近5条消息，并提供10秒延迟发送；检测设备焦点/文本变化时自动暂停

## Device Detail Page 设备详情页

The Device Detail Page provides comprehensive information about a specific Android device, including hardware specifications, system information, connection details, and runtime statistics.

设备详情页提供特定Android设备的全面信息，包括硬件规格、系统信息、连接详情和运行时统计。

### Features 功能特性

- **Hardware Information 硬件信息**: Model, manufacturer, brand, hardware platform, ABI, memory, storage / 型号、制造商、品牌、硬件平台、ABI、内存、存储
- **System Information 系统信息**: Android version, SDK version, security patch level, build ID / Android版本、SDK版本、安全补丁级别、构建ID
- **Display Information 显示信息**: Screen resolution, density / 屏幕分辨率、密度
- **Battery Status 电池状态**: Battery level and charging status / 电池电量和充电状态
- **Connection Details 连接详情**: Connection type (USB/TCP), endpoint, IP address, TCP port, transport ID / 连接类型（USB/TCP）、终端、IP地址、TCP端口、传输ID
- **Device State 设备状态**: Online/offline status, USB debugging status, WiFi MAC address / 在线/离线状态、USB调试状态、WiFi MAC地址
- **Extra Properties 额外属性**: Additional device-specific properties / 额外的设备特定属性
- **Sync Status 同步状态**: Real-time sync progress with progress bar, customer count, message count, and error information / 实时同步进度，包含进度条、客户数量、消息数量和错误信息
- **Quick Actions 快速操作**: Direct access to sync, mirror, logs, and refresh actions / 直接访问同步、镜像、日志和刷新操作

### Navigation 导航

- **From Device List 从设备列表**: Click any device card in the Device List view / 在设备列表视图中点击任意设备卡片
- **Back Navigation 返回导航**: Use the "← Back to devices" button at the top of the detail page / 使用详情页顶部的"← Back to devices"按钮返回

### Information Display 信息展示

The detail page organizes device information into several sections:

详情页将设备信息组织成多个部分：

1. **Summary Card 摘要卡片**: Device model, manufacturer, brand, Android version, SDK version, product, device codename, state, battery level, screen resolution, density, and online status / 设备型号、制造商、品牌、Android版本、SDK版本、产品、设备代号、状态、电池电量、屏幕分辨率、密度和在线状态

2. **Information Grid 信息网格**: Six cards displaying:
   - **Android 系统**: Android version, SDK, security patch, build ID / Android版本、SDK、安全补丁、构建ID
   - **Hardware 硬件**: Hardware platform, ABI, memory / 硬件平台、ABI、内存
   - **Storage 存储**: Internal storage, USB debugging status, WiFi MAC / 内部存储、USB调试状态、WiFi MAC
   - **Display 显示**: Screen resolution and density / 屏幕分辨率和密度
   - **Connection 连接**: Connection type, endpoint, transport ID, USB info, IP address, TCP port / 连接类型、终端、传输ID、USB信息、IP地址、TCP端口
   - **Identifiers 标识符**: Features and extra properties / 功能和额外属性

3. **Sync Status Section 同步状态部分**: Real-time sync progress with:
   - Status indicator (idle, starting, running, completed, error, stopped) / 状态指示器（空闲、启动中、运行中、已完成、错误、已停止）
   - Progress bar showing completion percentage / 显示完成百分比的进度条
   - Customer and message counts / 客户和消息计数
   - Error information if sync fails / 同步失败时的错误信息

### Actions 操作

The detail page provides quick access to common device operations:

详情页提供常用设备操作的快速访问：

- **🚀 Sync now 立即同步**: Start synchronization for this device / 为此设备启动同步
- **🖥️ Start mirroring / 🛑 Stop mirroring 启动镜像/停止镜像**: Toggle device screen mirroring / 切换设备屏幕镜像
- **📋 View logs 查看日志**: Navigate to the logs view filtered for this device / 导航到为此设备过滤的日志视图
- **🔄 Refresh 刷新**: Reload device information from the backend / 从后端重新加载设备信息

## Logs View: Multi-Pane Drag & Drop 日志面板多窗拖拽

- **Open 打开**: Drag a device tab into the log area (or click it) to open a pane for that device.
- **Side-by-side 并排**: Show multiple devices simultaneously; max panel count is configurable via settings (default **3**, low-spec mode enforces **1**).
- **Per-pane controls 独立控制**: Each pane has Clear (🗑️) and Export (📥); the header Clear/Export act on the focused pane.
- **Focus 焦点**: Click a pane header to focus it so shared actions and filters apply to that device.
- **Shared filters 共享过滤**: Level filter, search, and auto-scroll apply to all panes.

### Important: Multi-Device Port Configuration 重要：多设备端口配置

When running sync on multiple devices simultaneously, each device's droidrun app must be configured with a unique port:

同时在多台设备上运行同步时，每台设备的droidrun应用必须配置不同的端口：

- Device 1: Socket Server Port = 8080
- Device 2: Socket Server Port = 8081
- Device 3: Socket Server Port = 8082
- ...

This prevents port conflicts that would cause one device's sync to fail.

这可以防止端口冲突导致某台设备同步失败。

## Dashboard 仪表盘

The Dashboard provides a unified view of synced conversation data by federating reads across discovered device-local conversation DBs. If a caller passes `db_path`, the backend scopes the request to that single DB. It displays:

仪表盘提供统一视图，默认会聚合读取已发现的设备本地会话数据库；如果调用方显式传入 `db_path`，后端则只读取该单库数据：

- **Overall Statistics 总体统计**: Total counts for devices, 客服, customers, messages, and images / 设备、客服、客户、消息和图片的总数
- **Device Coverage 设备覆盖**: Per-device conversation statistics including 客服 count, customer count, and message counts / 每台设备的会话统计，包括客服数量、客户数量和消息数量
- **客服 Overview 客服概览**: Per-客服 summaries with customer engagement metrics and latest customer activity / 每个客服的摘要，包括客户参与度指标和最新客户活动
- **Recent Conversations 最近会话**: List of recent conversations ordered by last activity across all devices / 按最后活动时间排序的最近会话列表

The dashboard auto-refreshes every 15 seconds and can be manually refreshed at any time.

仪表盘每15秒自动刷新，也可以随时手动刷新。

### Navigation paths 导航路径

- Click the “客服” card to enter the full kefu list, then open any kefu to see their customers; from there you can click a customer to open the existing customer detail page / 点击“客服”卡片进入完整客服列表，再进入某个客服查看其客户；在该列表中可继续点击客户进入已有的客户详情页
- Click the “Customers” card to jump directly into the customer list / 点击“Customers”卡片直接进入客户列表

## Customers & Avatars 客户与头像

The Customers feature provides a comprehensive view of all synced customers with drill-down capabilities.

客户功能提供所有已同步客户的全面视图，支持下钻查看详细信息。

### Customer List 客户列表

- **Access**: Navigate from the sidebar "Customers" menu item or click the "Customers" card on the Dashboard
- **Search**: Filter customers by name or channel using the search bar
- **Pagination**: Browse through customers with configurable page size (10, 20, 50, 100)
- **Avatars**: Each customer displays a deterministic avatar based on their name, channel, and ID hash
- **Metadata**: View customer name, channel, associated 客服, device, last message time, preview, and message counts

访问方式：从侧边栏"Customers"菜单项或点击仪表盘上的"Customers"卡片进入
搜索：使用搜索栏按客户名称或渠道筛选
分页：可配置每页显示数量（10、20、50、100）浏览客户
头像：每个客户显示基于其名称、渠道和ID哈希的确定性头像
元数据：查看客户名称、渠道、关联客服、设备、最后消息时间、预览和消息计数

### Kefu List & Detail 客服列表与详情

- **Access**: Sidebar “客服” or the Dashboard “客服” card / 通过侧边栏“客服”或仪表盘“客服”卡片进入
- **Search**: Filter by kefu name, department, or device serial / 按客服姓名、部门或设备序列号搜索
- **Pagination**: Configurable page size (10, 20, 50, 100) / 可配置每页 10、20、50、100
- **Kefu detail**: Shows device, customer/message counts, message-type breakdown, and the customer list for that kefu / 详情页展示设备、客户/消息计数、消息类型分布以及该客服的客户列表
- **Deep link**: Click any customer in the kefu detail to open the existing customer detail view / 在客服详情页点击客户可继续进入已有的客户详情页

### Customer Detail View 客户详情页

- **Overview**: Customer summary card with avatar, name, channel, and timestamps
- **Message Breakdown**: Visual breakdown of message types (text, image, voice, etc.) with counts
- **Conversation History**: Chronological list of messages with sender indicators (客服 vs customer)
- **Metadata**: View associated 客服 information, device details, and message statistics

概览：客户摘要卡片，包含头像、名称、渠道和时间戳
消息分类：消息类型（文本、图片、语音等）的可视化分类统计
会话历史：按时间顺序排列的消息列表，带有发送者标识（客服 vs 客户）
元数据：查看关联的客服信息、设备详情和消息统计

### Avatar System 头像系统

- **Deterministic Assignment**: Avatars are consistently assigned based on a hash of customer name, channel, and ID
- **Source of Truth**: Avatar PNGs live in the repo root `avatars/` directory (also used by init sync); Vite copies them into `wecom-desktop/public/avatars/` for dev/build so the frontend can serve `/avatars/...`
- **Customization**: Add or replace files in `avatars/`, then restart/reload the dev server (or rebuild) to refresh the copied assets
- **Default Avatars**: 10 pre-configured avatar images (avatar_01_wa.png through avatar_10_wgz_302_.png)

确定性分配：头像基于客户名称、渠道和ID的哈希值一致分配
头像源目录：PNG 存放在仓库根目录 `avatars/`（初始同步也写入这里），Vite 在开发/构建时复制到 `wecom-desktop/public/avatars/` 供前端通过 `/avatars/...` 访问
自定义：在 `avatars/` 中新增或替换文件，重启/刷新 dev server（或重新构建）即可同步
默认头像：10 个预配置的头像图片（avatar_01_wa.png 到 avatar_10_wgz_302_.png）

### API Endpoints

- `GET /customers` - List customers with pagination and search (supports `limit`, `offset`, `search`)
- `GET /customers/{id}` - Get customer detail with messages and breakdown (supports `messages_limit`, `messages_offset`)

## AI Reply Integration AI回复集成

The sync process can be configured to use an external AI chatbot server for generating intelligent replies instead of mock test messages.

同步过程可配置使用外部AI聊天机器人服务器生成智能回复，而非模拟测试消息。

### Configuration 配置

1. **Enable in Settings 在设置中启用**: Navigate to Settings → AI Reply Settings / 导航到设置 → AI回复设置
2. **Toggle "Use AI Reply" 开启"使用AI回复"**: Enable AI-powered responses / 启用AI驱动的回复
3. **AI Server URL AI服务器URL**: Default `http://localhost:8000` (configure if different) / 默认 `http://localhost:8000`（如不同可配置）
4. **Timeout 超时**: Set max wait time for AI response (1-30 seconds) / 设置AI响应最大等待时间（1-30秒）

### How It Works 工作原理

When AI Reply is enabled during sync:
- **Follow-up messages 跟进消息** (when kefu sent last): AI generates a "补刀" message to re-engage the customer / AI生成"补刀"消息重新联系客户
- **Reply messages 回复消息** (when customer sent last): AI generates a contextual response based on the customer's message / AI根据客户消息生成上下文相关回复

If AI server is unavailable or times out, the system falls back to mock messages automatically.

如果AI服务器不可用或超时，系统自动回退到模拟消息。

### Sidecar Indicators 侧边窗指示器

- 🤖 **AI Reply** (green): AI-generated response / AI生成的回复
- ⚠️ **AI Fallback** (yellow): AI failed, using mock / AI失败，使用模拟
- 📝 **Mock Reply** (gray): AI disabled / AI已禁用

### Generate Button 生成按钮

The sidecar panel header includes a **🤖 Generate** button that allows on-demand reply generation without running a sync:

侧边窗面板标题栏包含一个 **🤖 生成** 按钮，可在不运行同步的情况下按需生成回复：

1. Navigate to any conversation on the device / 在设备上导航到任意会话
2. Click **🤖 Generate** in the panel header / 点击面板标题栏中的 **🤖 生成**
3. The system detects the last message and determines reply type (补刀 or reply) / 系统检测最后一条消息并确定回复类型（补刀或回复）
4. AI (if enabled) or mock reply is generated into the textarea / AI（如果启用）或模拟回复生成到文本框
5. Review, edit, and send manually / 审核、编辑后手动发送

Button order in header 标题栏按钮顺序: `🤖 Generate | 🖥️ Mirror | 🔄 | ✖️`

### Requirements 要求

- AI chatbot server running at configured URL / AI聊天机器人服务器在配置的URL运行
- Server must expose POST `/chat` endpoint with `chatInput` field / 服务器必须暴露POST `/chat`端点，包含`chatInput`字段

## Future Plans 未来计划

- Data analytics and performance metrics / 数据分析和性能指标
- Hot plug/unplug device support with resume capability / 设备热插拔支持和断点续传
- Enhanced AI agent capabilities / 增强AI代理功能

## Testing 测试

Run the backend tests:
```bash
cd wecom-desktop/backend
python -m pytest tests/ -v
```

Tests cover:
- Single device sync operations
- Multi-device parallel sync
- Stop functionality (individual and concurrent)
- Process cleanup and restart
- Log and status callbacks

## License

MIT

