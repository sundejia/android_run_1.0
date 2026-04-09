# FollowUp 日志系统改进方案

> 文档创建于：2026-01-19  
> 更新于：2026-01-20  
> 版本：v1.2  
> 状态：实现文档  
> 关联：[docs/followup_system_refactor.md](./followup_system_refactor.md) - 问题 3

## 目录

1. [问题分析](#问题分析)
2. [目标设计](#目标设计)
3. [实现方案](#实现方案)
4. [后端代码实现](#后端代码实现)
5. [前端代码实现](#前端代码实现)
6. [需删除的代码](#需删除的代码)
7. [测试验证](#测试验证)

---

## 问题分析

### 当前日志显示位置

日志需要在**两个地方**正确显示：

| 位置             | 组件              | 说明                               |
| ---------------- | ----------------- | ---------------------------------- |
| **Logs 页面**    | `LogsView.vue`    | 专用日志查看页面，可多设备并排显示 |
| **Sidecar 页面** | `SidecarView.vue` | 操作面板，底部有日志区域           |

### 当前问题

| 问题                               | 说明                                                         |
| ---------------------------------- | ------------------------------------------------------------ |
| **日志来源不明确**                 | 所有设备的 FollowUp 日志都来自 `followup_service`，无法区分  |
| **单独的 WebSocket 端点**          | `/a../03-impl-and-arch/ws/logs` 是独立端点，与设备日志流分离 |
| **Sidecar 无法显示 FollowUp 日志** | 只显示 Sync 日志，FollowUp 日志不显示                        |
| **多设备日志混乱**                 | 多个设备的日志混在一起                                       |
| **无法区分日志来源**               | 无法区分是 Sync 还是 FollowUp 产生的日志                     |

### 当前架构（问题所在）

```
┌─────────────────────────────────────────────────────────────────┐
│                       当前日志架构                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Sync 日志:                                                     │
│  ┌──────────┐     ┌─────────────────────┐    ┌───────────────┐  │
│  │DeviceMgr │────▶│/ws/logs/{serial}    │───▶│ Logs页面      │  │
│  └──────────┘     └─────────────────────┘    │ Sidecar页面   │  │
│                                              └───────────────┘  │
│                                                                 │
│  FollowUp 日志（分离的！）:                                      │
│  ┌──────────┐     ┌─────────────────────┐    ┌───────────────┐  │
│  │FollowUp  │────▶│/a../03-impl-and-arch/ws/logs│───▶│ 独立页面      │  │
│  │Service   │     └─────────────────────┘    │ (无法合并)    │  │
│  └──────────┘                                └───────────────┘  │
│                                                                 │
│  ❌ 两套分离的日志流                                             │
│  ❌ Sidecar 看不到 FollowUp 日志                                 │
│  ❌ 无法按来源过滤                                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 目标设计

### 目标架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           目标日志架构                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │                    统一日志流（per-device）                      │     │
│  │                                                                │     │
│  │  Sync 日志 ──────┐                                              │     │
│  │  (DeviceManager) │     /ws/logs/{serial}                       │     │
│  │                  ├────▶ (统一端点)                              │     │
│  │  FollowUp 日志 ──┘     source: "sync" | "followup"             │     │
│  │  (FollowUpDeviceMgr)                                           │     │
│  │                                                                │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                │                                        │
│                                ▼                                        │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │                      logs.ts Store                              │     │
│  │                                                                │     │
│  │   logs[serial] = [                                             │     │
│  │     { message: "...", source: "sync", ... },                   │     │
│  │     { message: "...", source: "followup", ... },               │     │
│  │     { message: "...", source: "sync", ... },                   │     │
│  │   ]                                                            │     │
│  │                                                                │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                     │                          │                        │
│                     ▼                          ▼                        │
│  ┌─────────────────────────────┐  ┌─────────────────────────────┐      │
│  │       LogsView.vue          │  │      SidecarView.vue        │      │
│  │                             │  │                             │      │
│  │  [All] [Sync] [FollowUp]    │  │  ┌─────────────────────┐    │      │
│  │  ─────────────────────────  │  │  │ 日志区域            │    │      │
│  │  21:30 [SYNC] Starting...   │  │  │ (合并显示)          │    │      │
│  │  21:31 [FOLLOWUP] Check...  │  │  └─────────────────────┘    │      │
│  │  21:32 [SYNC] Complete      │  │                             │      │
│  │                             │  │                             │      │
│  └─────────────────────────────┘  └─────────────────────────────┘      │
│                                                                         │
│   ✅ 统一的 WebSocket 端点                                               │
│   ✅ 两个页面都能看到完整日志                                            │
│   ✅ 可按来源过滤 (All/Sync/FollowUp)                                    │
│   ✅ 日志消息带有 source 字段标识来源                                     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 日志消息格式

```typescript
interface LogEntry {
  id: string
  timestamp: string
  level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR'
  message: string
  source: 'sync' | 'followup' | 'system' // 新增字段
}
```

示例：

```json
// Sync 日志
{
  "timestamp": "2026-01-20T12:15:00.000Z",
  "level": "INFO",
  "message": "Starting sync for 张三...",
  "source": "sync"
}

// FollowUp 日志
{
  "timestamp": "2026-01-20T12:15:01.000Z",
  "level": "INFO",
  "message": "[FollowUp] Checking for unread messages...",
  "source": "followup"
}
```

---

## 实现方案

### 3.1 日志流合并

1. **FollowUp 进程日志** → 输出到 stdout
2. **FollowUpDeviceManager** → 捕获输出，添加 `source: "followup"`
3. **logs.py WebSocket** → 同时注册 Sync 和 FollowUp 回调
4. **前端 logs.ts** → 接收并存储，支持按 source 过滤

### 3.2 Logs 页面过滤按钮

```
┌─────────────────────────────────────────────────────────┐
│  Device Logs                               [Clear] [📥] │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Level: [All ▼]   Search: [____________]   Auto-scroll ☑ │
│                                                         │
│  Source: [All] [Sync] [FollowUp]  ← 新增过滤按钮        │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  [device_A] [device_B]                                  │
├─────────────────────────────────────────────────────────┤
│  12:15:00 [SYNC]     Starting sync for 张三...          │
│  12:15:01 [FOLLOWUP] Checking for unread messages...    │
│  12:15:02 [SYNC]     Found 5 customers                  │
│  12:15:03 [FOLLOWUP] Found 2 unread user(s)             │
│  ...                                                    │
└─────────────────────────────────────────────────────────┘
```

---

## 后端代码实现

### 4.1 FollowUpDeviceManager 日志广播

**文件**: `backend/services/followup_device_manager.py`

```python
class FollowUpDeviceManager:
    """管理多设备的 follow-up 进程"""

    async def _broadcast_log(self, serial: str, level: str, message: str):
        """
        广播日志到该设备的 WebSocket

        使用与 Sync 相同的回调机制，日志会发送到 /ws/logs/{serial}
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
            "source": "followup",  # 关键：标记来源
        }

        if serial in self._log_callbacks:
            for callback in list(self._log_callbacks[serial]):
                try:
                    await callback(log_entry)
                except Exception:
                    pass

    async def _read_output(self, serial: str, stream, is_stderr: bool = False):
        """读取子进程输出并广播到设备日志流"""
        try:
            while True:
                line = await stream.readline()
                if not line:
                    break

                text = self._decode_output(line)
                if not text:
                    continue

                # 解析日志级别
                level = "INFO"
                message = text

                match = re.match(r"[\d:]+\s*\|\s*(\w+)\s*\|\s*(.+)", text)
                if match:
                    parsed_level = match.group(1).upper()
                    if parsed_level in ("DEBUG", "INFO", "WARNING", "ERROR"):
                        level = parsed_level
                    message = match.group(2)

                # 添加 [FollowUp] 前缀便于识别
                if not message.startswith("[FollowUp]"):
                    message = f"[FollowUp] {message}"

                await self._broadcast_log(serial, level, message)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            await self._broadcast_log(serial, "ERROR", f"[FollowUp] Output read error: {e}")
```

### 4.2 修改 logs.py - 双重回调注册

**文件**: `backend/routers/logs.py`

```python
@router.websocket("/ws/logs/{serial}")
async def websocket_logs(websocket: WebSocket, serial: str):
    """
    WebSocket endpoint for real-time log streaming.

    同时接收 Sync 和 FollowUp 的日志，通过 source 字段区分。
    """
    await websocket.accept()

    if serial not in _log_connections:
        _log_connections[serial] = set()
    _log_connections[serial].add(websocket)

    # 创建统一的日志回调
    async def log_callback(message: dict):
        try:
            await websocket.send_json(message)
        except Exception:
            pass

    # 注册 Sync 日志回调
    manager = get_device_manager()
    manager.register_log_callback(serial, log_callback)

    # 注册 FollowUp 日志回调
    followup_registered = False
    try:
        from services.followup_device_manager import get_followup_device_manager
        followup_manager = get_followup_device_manager()
        followup_manager.register_log_callback(serial, log_callback)
        followup_registered = True
    except ImportError:
        pass

    try:
        from datetime import datetime
        await websocket.send_json({
            "timestamp": datetime.now().isoformat(),
            "level": "INFO",
            "message": f"Connected to log stream for {serial}",
            "source": "system",
        })

        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                try:
                    await websocket.send_text("ping")
                except Exception:
                    break

    except WebSocketDisconnect:
        pass
    finally:
        manager.unregister_log_callback(serial, log_callback)
        if followup_registered:
            try:
                followup_manager.unregister_log_callback(serial, log_callback)
            except Exception:
                pass
        if serial in _log_connections:
            _log_connections[serial].discard(websocket)
```

### 4.3 子进程日志格式

**文件**: `followup_process.py`

```python
def setup_logging(serial: str, debug: bool = False):
    """设置日志 - 输出格式化日志到 stdout"""
    level = logging.DEBUG if debug else logging.INFO

    class FollowUpFormatter(logging.Formatter):
        def format(self, record):
            timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
            level = record.levelname.ljust(8)
            message = record.getMessage()
            if not message.startswith("[FollowUp]"):
                message = f"[FollowUp] {message}"
            return f"{timestamp} | {level} | {message}"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(FollowUpFormatter())

    logger = logging.getLogger("followup")
    logger.setLevel(level)
    logger.addHandler(handler)
    sys.stdout.reconfigure(line_buffering=True)

    return logger
```

---

## 前端代码实现

### 5.1 logs.ts - 删除 followup 特殊处理

**文件**: `src/stores/logs.ts`

```typescript
// 修改 connectLogStream 函数

function connectLogStream(serial: string) {
  initBroadcastChannel()
  requestLogsFromOtherWindows(serial)

  if (websockets.value.has(serial)) {
    const ws = websockets.value.get(serial)!
    if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
      return
    }
  }

  // ✅ 统一使用相同的 URL 格式，删除 followup 特殊处理
  const wsUrl = `ws://localhost:8765/ws/logs/${serial}`

  const ws = new WebSocket(wsUrl)

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      addLog(serial, {
        id: crypto.randomUUID(),
        timestamp: data.timestamp || new Date().toISOString(),
        level: data.level || 'INFO',
        message: data.message,
        source: data.source || 'sync', // ✅ 保存 source 字段
      })
    } catch {
      addLog(serial, {
        id: crypto.randomUUID(),
        timestamp: new Date().toISOString(),
        level: 'INFO',
        message: event.data,
        source: 'sync',
      })
    }
  }

  // ... 其余代码保持不变
}

// 更新 LogEntry 类型
export interface LogEntry {
  id: string
  timestamp: string
  level: string
  message: string
  source?: 'sync' | 'followup' | 'system' // ✅ 新增
}
```

### 5.2 LogsView.vue - 添加 Source 过滤按钮

**文件**: `src/views/LogsView.vue`

```vue
<script setup lang="ts">
// ... 现有 imports ...

// 新增：Source 过滤
const sourceFilter = ref<'all' | 'sync' | 'followup'>('all')

// 删除 FIXED_TABS
const FIXED_TABS: string[] = [] // ✅ 改为空数组

// 修改 applyFilters 函数
function applyFilters(logs: LogEntry[]): LogEntry[] {
  let filtered = logs

  // Level 过滤
  if (levelFilter.value !== 'all') {
    filtered = filtered.filter((log) => log.level === levelFilter.value)
  }

  // ✅ 新增：Source 过滤
  if (sourceFilter.value !== 'all') {
    filtered = filtered.filter((log) => log.source === sourceFilter.value)
  }

  // 搜索过滤
  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase()
    filtered = filtered.filter(
      (log) =>
        log.message.toLowerCase().includes(query) || log.source?.toLowerCase().includes(query)
    )
  }

  return filtered
}

// 修改 filteredLogsMap computed
const filteredLogsMap = computed(() => {
  const map = new Map<string, LogEntry[]>()

  const query = searchQuery.value
  const level = levelFilter.value
  const source = sourceFilter.value // ✅ 添加 source

  for (const serial of panels.value) {
    let logs = logStore.getDeviceLogs(serial)

    if (level !== 'all') {
      logs = logs.filter((log) => log.level === level)
    }

    // ✅ 新增：Source 过滤
    if (source !== 'all') {
      logs = logs.filter((log) => log.source === source)
    }

    if (query) {
      const q = query.toLowerCase()
      logs = logs.filter(
        (log) => log.message.toLowerCase().includes(q) || log.source?.toLowerCase().includes(q)
      )
    }

    map.set(serial, logs)
  }

  return map
})
</script>

<template>
  <!-- 在 Filters 区域添加 Source 过滤按钮 -->
  <div class="flex items-center gap-4">
    <!-- Level filter -->
    <select v-model="levelFilter" class="input-field text-sm py-1.5">
      <option value="all">All Levels</option>
      <option value="DEBUG">Debug</option>
      <option value="INFO">Info</option>
      <option value="WARNING">Warning</option>
      <option value="ERROR">Error</option>
    </select>

    <!-- ✅ 新增：Source 过滤按钮组 -->
    <div class="flex items-center gap-1 bg-wecom-surface rounded-lg p-1">
      <button
        @click="sourceFilter = 'all'"
        class="px-3 py-1 text-sm rounded-md transition-colors"
        :class="
          sourceFilter === 'all'
            ? 'bg-wecom-primary text-white'
            : 'text-wecom-muted hover:text-wecom-text'
        "
      >
        All
      </button>
      <button
        @click="sourceFilter = 'sync'"
        class="px-3 py-1 text-sm rounded-md transition-colors"
        :class="
          sourceFilter === 'sync'
            ? 'bg-green-600 text-white'
            : 'text-wecom-muted hover:text-wecom-text'
        "
      >
        Sync
      </button>
      <button
        @click="sourceFilter = 'followup'"
        class="px-3 py-1 text-sm rounded-md transition-colors"
        :class="
          sourceFilter === 'followup'
            ? 'bg-blue-600 text-white'
            : 'text-wecom-muted hover:text-wecom-text'
        "
      >
        FollowUp
      </button>
    </div>

    <!-- Search -->
    <input
      v-model="searchQuery"
      type="text"
      placeholder="Search logs..."
      class="input-field text-sm py-1.5 flex-1 max-w-xs"
    />

    <!-- Auto-scroll toggle -->
    <label class="flex items-center gap-2 text-sm text-wecom-muted cursor-pointer">
      <input
        type="checkbox"
        v-model="autoScroll"
        class="w-4 h-4 rounded border-wecom-border bg-wecom-surface text-wecom-primary"
      />
      Auto-scroll
    </label>
  </div>

  <!-- 删除设备标签中的 followup 特殊处理 -->
  <button
    v-for="serial in availableDevices"
    :key="serial"
    draggable="true"
    @dragstart="(event) => handleDragStart(serial, event)"
    @click="selectDevice(serial)"
    class="px-4 py-2 text-sm font-medium whitespace-nowrap transition-colors"
    :class="[
      panels.includes(serial)
        ? 'text-wecom-primary border-b-2 border-wecom-primary bg-wecom-primary/5'
        : 'text-wecom-muted hover:text-wecom-text hover:bg-wecom-surface',
    ]"
  >
    <!-- ✅ 只显示设备 serial，删除 followup 特殊显示 -->
    <span class="font-mono">{{ serial }}</span>
    <span
      v-if="logStore.getDeviceLogs(serial).length > 0"
      class="ml-2 px-1.5 py-0.5 text-xs rounded-full bg-wecom-surface"
    >
      {{ logStore.getDeviceLogs(serial).length }}
    </span>
  </button>
</template>
```

### 5.3 LogStream.vue - 显示 Source 标记

**文件**: `src/components/LogStream.vue`

```vue
<template>
  <div class="log-entry" :class="`log-${log.level.toLowerCase()}`">
    <span class="log-time">{{ formatTime(log.timestamp) }}</span>

    <!-- ✅ 新增：Source 标记 -->
    <span
      v-if="log.source && log.source !== 'system'"
      class="log-source"
      :class="{
        'source-sync': log.source === 'sync',
        'source-followup': log.source === 'followup',
      }"
    >
      [{{ log.source === 'followup' ? 'FOLLOWUP' : 'SYNC' }}]
    </span>

    <span class="log-message">{{ log.message }}</span>
  </div>
</template>

<style scoped>
.log-source {
  font-weight: 600;
  font-size: 0.75rem;
  padding: 0 4px;
  margin-right: 8px;
  border-radius: 2px;
}

.source-sync {
  color: #22c55e; /* green-500 */
  background: rgba(34, 197, 94, 0.1);
}

.source-followup {
  color: #3b82f6; /* blue-500 */
  background: rgba(59, 130, 246, 0.1);
}
</style>
```

---

## 需删除的代码

### 6.1 后端删除

#### logs.py - 删除 followup 特殊处理

**文件**: `backend/routers/logs.py`

删除第 76-115 行：

```python
# ❌ 删除整个 if serial == "followup" 分支
if serial == "followup":
    from services.followup_service import get_followup_service
    service = get_followup_service()
    # ... 整个分支删除 ...
```

#### followup.py - 删除独立 WebSocket 端点

**文件**: `backend/routers/followup.py`

删除 `/ws/logs` 端点（约第 672-710 行）：

```python
# ❌ 删除整个端点
@router.websocket("/ws/logs")
async def followup_logs_websocket(websocket: WebSocket):
    # ... 整个函数删除 ...
```

### 6.2 前端删除

#### LogsView.vue - 删除 FIXED_TABS 和 followup 特殊显示

**修改 1**: 第 27 行

```javascript
// ❌ 删除
const FIXED_TABS = ['followup']

// ✅ 改为
const FIXED_TABS: string[] = []
```

**修改 2**: 删除第 321-323 行的 followup 特殊显示

```vue
<!-- ❌ 删除 -->
<span v-if="serial === 'followup'" class="flex items-center gap-1">
  🔄 Follow-up
</span>
```

**修改 3**: 删除第 373-377 行的 followup 特殊样式

```vue
<!-- ❌ 删除 serial !== 'followup' 条件 -->
:class="[..., serial !== 'followup' ? 'font-mono' : '']"

<!-- ❌ 删除 -->
<template v-if="serial === 'followup'">🔄 Follow-up</template>
```

#### logs.ts - 删除 followup 特殊 URL

**修改**: 第 165-168 行

```typescript
// ❌ 删除
const wsUrl =
  serial === 'followup'
    ? 'ws://localhost:8765/a../03-impl-and-arch/ws/logs'
    : `ws://localhost:8765/ws/logs/${serial}`

// ✅ 改为
const wsUrl = `ws://localhost:8765/ws/logs/${serial}`
```

---

## 文件变更清单

### 需修改的文件

| 文件                                          | 操作 | 说明                                     |
| --------------------------------------------- | ---- | ---------------------------------------- |
| `backend/services/followup_device_manager.py` | 修改 | 添加 `_broadcast_log()`                  |
| `backend/routers/logs.py`                     | 修改 | 删除 followup 分支，添加双重回调         |
| `backend/routers/followup.py`                 | 修改 | 删除 `/ws/logs` 端点                     |
| `src/stores/logs.ts`                          | 修改 | 删除 followup 特殊 URL，添加 source 字段 |
| `src/views/LogsView.vue`                      | 修改 | 删除 FIXED_TABS，添加 Source 过滤按钮    |
| `src/components/LogStream.vue`                | 修改 | 添加 source 标记显示                     |

### 无需修改的文件

| 文件                        | 说明                                                 |
| --------------------------- | ---------------------------------------------------- |
| `src/views/SidecarView.vue` | 已使用 `logStore.connectLogStream(serial)`，自动生效 |

---

## 测试验证

### 7.1 Logs 页面测试

1. 打开 Logs 页面
2. 选择一个设备
3. 同时启动 Sync 和 FollowUp
4. 验证：
   - 日志同时显示 Sync 和 FollowUp 消息
   - 每条日志有 [SYNC] 或 [FOLLOWUP] 标记
   - 过滤按钮工作正常：
     - 点击 "All" 显示所有日志
     - 点击 "Sync" 只显示 Sync 日志
     - 点击 "FollowUp" 只显示 FollowUp 日志

### 7.2 Sidecar 页面测试

1. 打开 Sidecar 页面
2. 选择一个设备
3. 同时启动 Sync 和 FollowUp
4. 验证日志区域同时显示两种日志

### 7.3 多设备测试

1. 在 Logs 页面同时打开 Device A 和 Device B 的日志
2. 在 Device A 启动 Sync，在 Device B 启动 FollowUp
3. 验证：
   - Device A 只有 Sync 日志
   - Device B 只有 FollowUp 日志
   - 日志不会串台

### 验收标准

| 测试项           | 验收标准                               |
| ---------------- | -------------------------------------- |
| Logs 页面显示    | Sync 和 FollowUp 日志都正确显示        |
| Sidecar 页面显示 | Sync 和 FollowUp 日志都正确显示        |
| Source 过滤      | All/Sync/FollowUp 按钮正常过滤         |
| Source 标记      | 每条日志显示 [SYNC] 或 [FOLLOWUP]      |
| 多设备隔离       | 每个设备只显示自己的日志               |
| 旧端点删除       | `/a../03-impl-and-arch/ws/logs` 不可用 |
