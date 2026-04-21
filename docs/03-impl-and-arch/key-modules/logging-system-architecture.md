# 日志系统架构 - Loguru 实现

## 概述

项目使用 **loguru** 实现统一的日志系统，支持：

- ✅ 每设备独立日志文件
- ✅ 自动轮转和清理（午夜轮转，保留 30 天）
- ✅ 多进程安全（`enqueue=True`）
- ✅ 实时日志流转发到前端 WebSocket

## 日志流向

```mermaid
graph LR
    subgraph "子进程 (Sync/FollowUp)"
        A[loguru Logger] --> B[stdout]
        A --> C[设备日志文件]
        A --> D[metrics.jsonl]
    end

    subgraph "后端 (DeviceManager)"
        E[subprocess.PIPE] --> F[_read_output]
        F --> G[解析日志格式]
        G --> H[_broadcast_log]
    end

    subgraph "前端"
        I[WebSocket /ws/logs/{serial}] --> J[LogsPanel.vue]
    end

    B --> E
    H --> I
```

## 日志格式

### stdout 输出格式（供前端捕获）

```
HH:MM:SS | LEVEL    | message
```

示例：

```
14:32:15 | INFO     | Starting sync for device R58M35XXXX
14:32:16 | WARNING  | Customer avatar not found
14:32:20 | ERROR    | Failed to extract message: timeout
```

### 文件日志格式（详细记录）

```
YYYY-MM-DD HH:MM:SS | LEVEL    | module:function:line | message
```

示例：

```
2026-02-06 14:32:15 | INFO     | sync:run:45 | Starting sync for device R58M35XXXX
```

## 配置示例

### 子进程脚本（initial_sync.py, realtime_reply_process.py）

**UPDATED (2026-02-09)**: 子进程现在使用 `serial` 参数进行日志隔离，避免文件锁定冲突。

```python
def setup_logging(serial: str, debug: bool = False):
    """配置日志 - 同时输出到文件和 stdout"""
    from wecom_automation.core.logging import init_logging, get_logger
    from loguru import logger as _loguru_logger

    level = "DEBUG" if debug else "INFO"
    hostname = _get_hostname()

    # 1. 初始化日志（传入 serial 参数，只写设备专属日志，避免文件锁定冲突）
    # - 不创建 global.log（避免多进程文件锁定）
    # - 自动创建 {hostname}-{serial}.log
    init_logging(hostname=hostname, level=level, console=False, serial=serial)

    # 2. 手动添加 stdout handler（供父进程捕获并转发到前端 WebSocket）
    _loguru_logger.add(
        sys.stdout,
        format="{time:HH:mm:ss} | {level:<8} | {message}",
        level=level,
        colorize=False,  # 不使用颜色代码
    )

    # 3. 确保 stdout 实时刷新
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(line_buffering=True)

    return get_logger("sync", device=serial)
```

**关键变化**：

- ✅ 传入 `serial=serial` 参数
- ✅ 不再需要 `add_device_sink()` 调用（内部自动处理）
- ✅ 避免子进程写入 `global.log`（防止文件锁定冲突）

### 后端主服务（main.py）

```python
def setup_backend_logging():
    """配置后端日志"""
    from wecom_automation.core.logging import init_logging

    hostname = _get_hostname()
    print(f"[startup] Initializing logging for hostname: {hostname}")

    # 输出到文件 + stderr（后端不需要 stdout）
    init_logging(hostname=hostname, level="INFO", console=True)

    print(f"[startup] Logging configured: logs/{hostname}-global.log")
```

## 多进程日志隔离 (2026-02-09)

### 问题背景

在多设备并行同步场景下，多个子进程尝试写入同一个 `global.log` 文件会导致 Windows 文件锁定冲突。

### 解决方案

通过 `init_logging(serial=...)` 参数实现进程隔离：

| 进程类型                | 调用方式                                  | 日志文件                  |
| ----------------------- | ----------------------------------------- | ------------------------- |
| **主进程** (main.py)    | `init_logging(console=True)`              | `{hostname}-global.log`   |
| **子进程** (sync/reply) | `init_logging(console=False, serial=xxx)` | `{hostname}-{serial}.log` |

### 技术细节

```python
# src/wecom_automation/core/logging.py
def init_logging(..., serial: str | None = None):
    if serial:
        # 子进程模式：只写设备专属日志，不写 global.log
        # 这样可以完全避免多个子进程竞争写入 global.log
        device_log_file = _log_dir / f"{hostname}-{serial}.log"
        _loguru_logger.add(device_log_file, ...)
    else:
        # 主进程模式：只写 global.log
        _loguru_logger.add(f"{hostname}-global.log", ...)
```

### 优势

1. ✅ **无文件锁定**: 每个进程写独立文件
2. ✅ **语义清晰**: `serial` 参数明确表示设备子进程
3. ✅ **向后兼容**: 主进程不传 `serial`，行为不变
4. ✅ **代码简化**: 不需要环境变量检测或 `add_device_sink()` 调用

### 相关文档

- 修复详情: `docs/04-bugs-and-fixes/resolved/2026-02-09-subprocess-global-log-fix.md`

## 日志文件结构

```
logs/
├── {hostname}-global.log              # 后端全局日志
├── {hostname}-global.2026-02-05.log   # 自动轮转的历史文件
├── {hostname}-R58M35XXXX.log          # 设备 A 所有操作日志
├── {hostname}-R58M35XXXX.2026-02-05.log
├── {hostname}-EMUL5554.log            # 设备 B 所有操作日志
└── metrics/
    ├── {hostname}-R58M35XXXX.jsonl    # 设备 A 业务指标（JSON Lines）
    └── {hostname}-EMUL5554.jsonl      # 设备 B 业务指标
```

## DeviceManager 日志捕获

### 解析逻辑

```python
async def _read_output(self, serial: str, stream: asyncio.StreamReader, is_stderr: bool = False):
    """从子进程读取输出并广播为日志"""
    while True:
        line = await stream.readline()
        if not line:
            break

        text = self._decode_output(line)

        # 解析日志格式：HH:MM:SS | LEVEL | message
        match = re.match(r"[\d:]+\s*\|\s*(\w+)\s*\|\s*(.+)", text)
        if match:
            level = match.group(1).upper()  # DEBUG, INFO, WARNING, ERROR
            message = match.group(2)
        else:
            level = "INFO"
            message = text

        # 广播到 WebSocket
        await self._broadcast_log(serial, level, message)
```

### WebSocket 消息格式

```json
{
  "timestamp": "2026-02-06T14:32:15.123456",
  "level": "INFO",
  "message": "Starting sync for device R58M35XXXX",
  "source": "sync"
}
```

### WebSocket 可靠性与保活（2026-04-21）

长时间运行后若仅依赖「单向发数据」，中间 NAT / 代理 / 笔记本休眠容易让 TCP 进入**半开**状态，浏览器端表现为偶发 `onclose` 或长时间无数据。当前实现分三层：

| 层级 | 位置 | 行为 |
| ---- | ---- | ---- |
| 传输层 | uvicorn | `ws_ping_interval=20`、`ws_ping_timeout=30`（`main.py` 与 `npm run backend` 脚本一致），使用 **RFC 6455 Ping/Pong 控制帧** 检测半开连接 |
| 应用层 | `routers/logs.py` | 客户端定时发送文本 **`ping`** → 服务端回复 **`pong`**；其它上行文本忽略；90s 无上行时仅作兜底探活 |
| 客户端 | `wecom-desktop/src/stores/logs.ts` | 约 25s 发送 `ping`；收到 `ping`/`pong` **不写入**可见日志；被动断开后**指数退避重连**（主动 `disconnectLogStream` 不重连） |

服务端在 `broadcast_log` 发送失败时会 **close** 对应连接并从集合移除；`DeviceManager` / `RealtimeReplyManager` 在回调 `await` 抛错时会 **discard** 该回调，避免僵尸订阅拖慢扇出。

详细故障分析与修复记录：`docs/04-bugs-and-fixes/resolved/2026-04-21-sidecar-log-stream-disconnect.md`。

## 前端 LogsPanel 接收

### WebSocket 连接

实际连接与重连逻辑集中在 **Pinia** `wecom-desktop/src/stores/logs.ts`（`LogsView`、`SidecarView`、`DeviceDetailView` 等调用 `connectLogStream`）。组件内若仍有直连 `WebSocket` 的示例代码，应以 store 为准。

```typescript
// 逻辑位于 src/stores/logs.ts（节选概念）
const ws = new WebSocket(`ws://localhost:8765/ws/logs/${serial}`)
// onopen: 启动定时 send('ping')；onmessage: JSON → addLog；'ping'|'pong' → 更新心跳时间戳不入库
// onclose: 若非用户主动断开 → scheduleReconnect(serial)
```

### 显示样式

```vue
<template>
  <div class="log-entry" :class="`log-${log.level.toLowerCase()}`">
    <span class="timestamp">{{ formatTime(log.timestamp) }}</span>
    <span class="level">{{ log.level }}</span>
    <span class="message">{{ log.message }}</span>
  </div>
</template>

<style>
.log-info {
  color: #2563eb;
}
.log-warning {
  color: #f59e0b;
}
.log-error {
  color: #dc2626;
}
.log-debug {
  color: #6b7280;
}
</style>
```

## 关键配置点

### ✅ stdout vs stderr

| 场景                    | 输出目标   | 原因                              |
| ----------------------- | ---------- | --------------------------------- |
| 子进程（Sync/FollowUp） | **stdout** | 父进程通过 `subprocess.PIPE` 捕获 |
| 后端主服务              | **stderr** | 标准 loguru 行为，不需要被捕获    |

### ✅ 格式化字符串

| 输出目标 | 格式                                                                                | 原因           |
| -------- | ----------------------------------------------------------------------------------- | -------------- |
| stdout   | `{time:HH:mm:ss} \| {level:<8} \| {message}`                                        | 简洁，易解析   |
| 文件     | `{time:YYYY-MM-DD HH:mm:ss} \| {level:<8} \| {name}:{function}:{line} \| {message}` | 详细，便于调试 |

### ✅ 行缓冲

```python
# 确保日志实时输出到 stdout
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
```

## 故障排除

### 前端看不到日志

**检查清单：**

1. ✅ 子进程脚本是否输出到 `stdout`（而非 `stderr`）
2. ✅ 日志格式是否匹配 `HH:MM:SS | LEVEL | message`
3. ✅ DeviceManager 的 `_read_output` 是否正常运行
4. ✅ WebSocket 是否仍 **OPEN**（断开后 store 会自动重连；若反复失败请查后端 `websocket_logs closed … reason=` 与浏览器控制台）

**调试方法：**

```bash
# 1. 直接运行子进程脚本，检查 stdout 输出
python wecom-desktop/backend/scripts/initial_sync.py --serial TEST123

# 2. 检查后端日志
tail -f logs/{hostname}-global.log

# 3. 检查设备日志文件
tail -f logs/{hostname}-R58M35XXXX.log
```

### 日志格式解析失败

如果 DeviceManager 的正则表达式无法匹配：

```python
# 当前正则：[\d:]+\s*\|\s*(\w+)\s*\|\s*(.+)
# 匹配示例：14:32:15 | INFO     | Starting sync

# 如果格式不匹配，检查 loguru format 字符串
format="{time:HH:mm:ss} | {level:<8} | {message}"
       # ^^^^^^^^    ^     ^^^^^^^^    ^ ^^^^^^^^^
       # 时间格式    分隔符  级别（8字符宽）  分隔符  消息
```

## 性能考虑

### 文件写入

- ✅ **异步队列**：`enqueue=True` 确保日志写入不阻塞主线程
- ✅ **批量写入**：loguru 内部使用缓冲
- ✅ **自动轮转**：避免单文件过大

### WebSocket 推送

- ✅ **异步广播**：使用 `asyncio.create_task`
- ✅ **断开检测**：自动移除失效连接
- ✅ **心跳保活**：30 秒 ping/pong

## 最佳实践

### 1. 使用结构化日志

```python
# ✅ 好的做法
logger.info("Synced customer: {}", customer_name)
logger.info("Progress: {}/{}", current, total)

# ❌ 避免
logger.info(f"Synced customer: {customer_name}")  # f-string 在 loguru 中也可以用，但不如 {} 统一
```

### 2. 合理使用日志级别

```python
logger.debug("Detailed trace info")     # 调试信息
logger.info("Normal operation")         # 正常操作
logger.warning("Potential issue")       # 潜在问题
logger.error("Operation failed: {}", e) # 错误
```

### 3. 设备上下文绑定

```python
# 在子进程中
logger = get_logger("sync", device=serial)

# 日志会自动路由到对应设备的日志文件
logger.info("This goes to {hostname}-{serial}.log")
```

## 相关文件

- `src/wecom_automation/core/logging.py` - 核心 loguru 配置
- `wecom-desktop/backend/services/device_manager.py` - 日志捕获和广播
- `wecom-desktop/backend/routers/logs.py` - WebSocket 路由
- `wecom-desktop/backend/scripts/initial_sync.py` - Sync 子进程配置
- `wecom-desktop/backend/scripts/realtime_reply_process.py` - FollowUp 子进程配置
