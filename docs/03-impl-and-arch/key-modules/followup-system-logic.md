# Follow-up System 逻辑文档

## 概述

Follow-up System（跟进系统）是一个自动化客户跟进模块，现已拆分为两个独立的功能模块：

### 架构拆分（2026-01-29）

系统已拆分为两个独立的页面和功能模块：

1. **⚡ 实时回复（Realtime Reply）** - `/realtime`
   - **原名**：Follow-up System
   - **功能**：Phase 1 - 即时响应检测（Instant Response Detection）
   - **作用**：检测客户回复（红点检测）并通过 AI 自动回复
   - **视图**：`RealtimeView.vue`
   - **后端**：复用现有 `followup_process.py` 和 API

2. **🔄 补刀跟进（Follow-up Management）** - `/followup`
   - **功能**：Phase 2 - 主动跟进管理（Proactive Follow-up）
   - **作用**：针对冷客户的补刀策略、候选人管理、历史记录
   - **视图**：`FollowUpManageView.vue`
   - **后端**：需要新的 API 端点（见 Phase 3）

### 为什么要拆分？

- **概念混淆**："Follow-up"本意是"补刀跟进"，但实际页面主要管理"实时回复"
- **功能独立**：实时回复和补刀跟进是两个不同的业务场景
- **未来扩展**：为 Phase 2 补刀跟进功能预留独立的 UI 和交互

### 核心功能

#### Phase 1: 实时回复（Realtime Reply）

- 红点检测（检测客户是否回复）
- AI 自动回复生成
- 通过 Sidecar 发送消息
- 多设备独立管理
- 实时状态监控

#### Phase 2: 补刀跟进（Follow-up Management）

- 候选人筛选（冷却期结束的客户）
- 跟进策略配置（冷却期、尝试间隔、最大次数）
- 手动触发补刀
- 跟进历史记录和统计

---

## 系统架构 (Multi-Device)

当前采用**多设备独立进程**架构，效仿全量同步的 `DeviceManager` 设计：

```
┌─────────────────────────────────────────────────────────────────────────┐
│                   FollowUpDeviceManager (进程管理器)                     │
│                 (followup_device_manager.py)                            │
│                                                                         │
│  - 每个设备运行独立子进程                                                 │
│  - 进程间互不干扰                                                        │
│  - 日志通过回调广播到 WebSocket                                          │
│  - 支持 Start/Stop/Pause/Resume                                         │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
          ┌──────────────────────┼──────────────────────┐
          │                      │                      │
          ▼                      ▼                      ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Device A       │    │  Device B       │    │  Device C       │
│  Subprocess     │    │  Subprocess     │    │  Subprocess     │
│                 │    │                 │    │                 │
│ followup_       │    │ followup_       │    │ followup_       │
│ process.py      │    │ process.py      │    │ process.py      │
│ --serial A      │    │ --serial B      │    │ --serial C      │
└────────┬────────┘    └────────┬────────┘    └────────┬────────┘
         │                      │                      │
         └──────────────────────┼──────────────────────┘
                                │
                                ▼
                  ┌───────────────────────┐
                  │   ResponseDetector    │
                  │ (response_detector.py)│
                  │                       │
                  │ - 检测红点用户         │
                  │ - 提取消息写入 DB      │
                  │ - 生成 AI 回复         │
                  │ - 通过 Sidecar 发送    │
                  └───────────┬───────────┘
                              │
                              ▼
                  ┌───────────────────────┐
                  │     Repository        │
                  │   (repository.py)     │
                  │                       │
                  │   数据库操作           │
                  │   - find_candidates   │
                  │   - record_attempt    │
                  │   - mark_responded    │
                  └───────────────────────┘
```

### 旧架构 vs 新架构

| 特性         | 旧架构 (BackgroundScheduler) | 新架构 (RealtimeReplyManager) |
| ------------ | ---------------------------- | ----------------------------- |
| 进程模型     | 单进程协程                   | 每设备独立子进程              |
| 设备隔离     | 共享状态                     | 子进程执行隔离（非完全隔离）  |
| 崩溃影响     | 影响所有设备                 | 仅影响单个设备                |
| 资源管理     | 共享                         | 独立                          |
| 暂停/恢复    | 整体暂停                     | 单设备控制                    |
| Windows 支持 | Job Objects                  | Job Objects (每进程)          |

---

## 核心模块

### 0. RealtimeReplyManager (多设备进程管理器)

**文件**: `wecom-desktop/backend/services/realtime_reply_manager.py`

负责管理多设备的实时回复子进程：

> 注意：这里的“独立”主要指进程与设备状态管理独立。数据库、ADB、后端编排进程、AI 服务和宿主机 CPU/磁盘仍可能共享，因此整体上应理解为“部分隔离”，而不是端到端完全隔离。

```python
class RealtimeReplyManager:
    """每个设备运行在独立的子进程中，互不干扰。"""

    _processes: Dict[str, Process]       # serial -> subprocess
    _states: Dict[str, RealtimeReplyState]    # serial -> state
    _log_callbacks: Dict[str, Set]       # serial -> websocket callbacks
    _status_callbacks: Dict[str, Set]    # serial -> status callbacks

    # 核心方法
    async def start_realtime_reply(serial, scan_interval, use_ai_reply, send_via_sidecar)
    async def stop_realtime_reply(serial)
    async def pause_realtime_reply(serial)   # 使用 Job Objects / SIGSTOP
    async def resume_realtime_reply(serial)  # 使用 Job Objects / SIGCONT
    async def stop_all()
```

**RealtimeReplyState 状态**:

```python
class RealtimeReplyStatus(Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"

@dataclass
class RealtimeReplyState:
    status: RealtimeReplyStatus
    message: str
    responses_detected: int    # 检测到的回复数
    replies_sent: int          # 发送的回复数
    errors: List[str]
    started_at: Optional[datetime]
    last_scan_at: Optional[datetime]
```

### 0.1 realtime_reply_process.py (单设备进程脚本)

**文件**: `realtime_reply_process.py`

被 `RealtimeReplyManager` 作为子进程启动：

```bash
uv run realtime_reply_process.py --serial DEVICE_SERIAL [options]

Options:
  --serial          设备序列号 (必需)
  --scan-interval   扫描间隔秒数 (默认 60)
  --use-ai-reply    使用 AI 生成回复
  --send-via-sidecar 通过 Sidecar 发送
  --debug           调试日志
```

**主循环逻辑**:

```python
async def run(args):
    # 初始化组件
    repository = FollowUpRepository(db_path)
    settings_manager = SettingsManager(db_path)
    detector = ResponseDetector(repository, settings_manager, logger)

    # 主循环
    while True:
        # 调用 ResponseDetector 检测并回复
        result = await detector.detect_and_reply(
            device_serial=args.serial,
            interactive_wait_timeout=40,
        )

        # 等待下一个扫描周期
        await asyncio.sleep(args.scan_interval)
```

---

### 1. FollowUpSettings (设置)

```python
@dataclass
class FollowUpSettings:
    enabled: bool = True              # 是否启用 Phase 2 (补刀系统)
    scan_interval: int = 60           # 扫描间隔（秒）
    max_followups: int = 3            # 最大补刀次数
    initial_delay: int = 120          # 首次补刀延迟（秒）
    subsequent_delay: int = 120       # 后续补刀延迟（秒）
    use_exponential_backoff: bool     # 是否使用指数退避
    backoff_multiplier: float = 2.0   # 退避倍数
    enable_operating_hours: bool      # 是否限制工作时间
    start_hour: int = 10              # 工作开始时间
    end_hour: int = 22                # 工作结束时间
    use_ai_reply: bool = False        # 是否使用 AI 生成回复
    enable_instant_response: bool     # 是否启用 Phase 1 (即时响应)
    send_via_sidecar: bool = True     # 是否通过 Sidecar 发送（人工审核）
```

### 2. FollowUpCandidate (候选人模型)

```python
@dataclass
class FollowUpCandidate:
    customer_id: int                       # 客户 ID
    customer_name: str                     # 客户名
    channel: Optional[str]                 # 渠道（如 @微信）
    kefu_id: int                           # 客服 ID
    last_kefu_message_time: datetime       # 客服最后消息时间
    last_customer_message_time: datetime   # 客户最后消息时间
    previous_attempts: int                 # 已发补刀次数
    seconds_since_last_kefu_message: int   # 距上次客服消息的秒数
    required_delay: int                    # 所需延迟（秒）
    is_ready: bool                         # 是否可以发送补刀
```

---

## 调度流程

### 新架构: RealtimeReplyManager (推荐)

```
┌─────────────────────────────────────────────────────────────┐
│                 Frontend: RealtimeView.vue                  │
│                                                             │
│   [Start Device A]  [Start Device B]  [Stop All]           │
└────────────────────────────┬────────────────────────────────┘
                             │ API Call
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              POS../03-impl-and-arch/key-modules/realtime/device/{serial}/start       │
│              POS../03-impl-and-arch/key-modules/realtime/device/{serial}/stop        │
│              POS../03-impl-and-arch/key-modules/realtime/device/{serial}/pause       │
│              POS../03-impl-and-arch/key-modules/realtime/device/{serial}/resume      │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│               RealtimeReplyManager                          │
│                                                             │
│  start_realtime_reply(serial) → 启动子进程 realtime_reply_process.py │
│  stop_realtime_reply(serial)  → taskkill / terminate       │
│  pause_realtime_reply(serial) → Job.suspend / SIGSTOP      │
│  resume_realtime_reply(serial)→ Job.resume / SIGCONT       │
└────────────────────────────┬────────────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         ▼                   ▼                   ▼
   ┌───────────┐       ┌───────────┐       ┌───────────┐
   │ Device A  │       │ Device B  │       │ Device C  │
   │ Process   │       │ Process   │       │ Process   │
   │           │       │           │       │           │
   │ scan loop │       │ scan loop │       │ scan loop │
   │  ↓        │       │  ↓        │       │  ↓        │
   │ detect_   │       │ detect_   │       │ detect_   │
   │ and_reply │       │ and_reply │       │ and_reply │
   │  ↓        │       │  ↓        │       │  ↓        │
   │ sleep     │       │ sleep     │       │ sleep     │
   │  ↓        │       │  ↓        │       │  ↓        │
   │ (repeat)  │       │ (repeat)  │       │ (repeat)  │
   └───────────┘       └───────────┘       └───────────┘
```

### 旧架构: BackgroundScheduler (已弃用)

```
┌─────────────────────────────────────────────────────────────┐
│                     Scan Loop (扫描循环)                     │
└─────────────────────────────────────────────────────────────┘
                        │
                        ▼
              ┌─────────────────┐
              │  检查系统状态    │
              │  - enabled?     │
              │  - paused?      │
              │  - 工作时间内?   │
              └────────┬────────┘
                       │
        ┌──────────────┴──────────────┐
        │                             │
        ▼                             ▼
┌───────────────────┐       ┌───────────────────┐
│     Phase 1       │       │     Phase 2       │
│  即时响应检测      │       │   补刀发送         │
│                   │       │                   │
│ enable_instant_   │       │    enabled        │
│ response = True   │       │    = True         │
└─────────┬─────────┘       └─────────┬─────────┘
          │                           │
          ▼                           ▼
  ResponseDetector            FollowUpScanner
  .detect_and_reply()         .scan_device_for_candidates()
          │                           │
          └───────────┬───────────────┘
                      │
                      ▼
           等待 scan_interval 秒
                      │
                      └──────── 循环 ────────┘
```

> **注意**: 旧架构 `BackgroundScheduler` 在单进程中协调所有设备，
> 新架构 `FollowUpDeviceManager` 为每个设备启动独立子进程。

---

## Phase 1: 即时响应检测 (ResponseDetector)

### 触发条件

- `enable_instant_response = True`

### 流程

```
1. 打开企业微信
2. 切换到"外部联系人"标签
3. 滚动到顶部
4. 检测第一页红点用户（不滚动）
5. 对每个红点用户：
   a. 点击进入聊天
   b. 提取消息并写入数据库
   c. 生成 AI 回复（如果启用）
   d. 通过 Sidecar 发送（如果启用）或直接发送
   e. 等待新消息（40秒超时）
   f. 返回列表
6. 重新检测红点，新红点优先处理
7. 循环直到没有红点
```

### 红点检测逻辑

```python
# 检测首页红点用户
priority_users = [u for u in current_users if u.is_priority()]

# is_priority() 条件:
#   1. unread_count > 0 (有红点)
#   2. 或 is_new_friend = True (新好友)
```

### 队列优先级

- 新发现的红点用户 → 加入队列**头部**（优先处理）
- 处理过但又出现红点的用户 → 重新加入队列头部

---

## Phase 2: 补刀发送 (FollowUpScanner)

### 触发条件

- `enabled = True`

### 候选人查询逻辑 (find_candidates)

```sql
-- 核心查询逻辑
WITH LastMessages AS (
    SELECT
        customer_id,
        MAX(CASE WHEN is_from_kefu = 1 THEN timestamp_parsed END) as last_kefu_time,
        MAX(CASE WHEN is_from_kefu = 0 THEN timestamp_parsed END) as last_customer_time
    FROM messages
    GROUP BY customer_id
)
SELECT ...
FROM customers c
JOIN LastMessages lm ON c.id = lm.customer_id
WHERE
    -- 有客服消息
    lm.last_kefu_time IS NOT NULL
    -- 且客服是最后发消息的人
    AND (lm.last_customer_time IS NULL OR lm.last_kefu_time > lm.last_customer_time)
```

### 就绪判断

```python
# 是否可以发送补刀
is_ready = (
    previous_attempts < max_followups  # 未达最大次数
    and seconds_since_last_kefu_message >= required_delay  # 冷却期已过
)
```

### 延迟计算

```python
def calculate_required_delay(attempt_number: int) -> int:
    if attempt_number == 1:
        return initial_delay  # 首次补刀使用 initial_delay

    if use_exponential_backoff:
        # 指数退避: subsequent_delay * multiplier^(n-2)
        return subsequent_delay * (backoff_multiplier ** (attempt_number - 2))
    else:
        return subsequent_delay

# 示例 (initial=120s, subsequent=120s, multiplier=2):
#   Attempt 1: 120s
#   Attempt 2: 120s (120 * 2^0)
#   Attempt 3: 240s (120 * 2^1)
#   Attempt 4: 480s (120 * 2^2)
```

### 发送流程

```
1. 获取所有连接的设备
2. 对每个设备：
   a. 查询该设备对应 kefu 的候选客户
   b. 过滤 is_ready=True 的客户
   c. 排除 Phase 1 已处理的用户
3. 对每个候选客户：
   a. 在列表中点击用户
   b. 检查最后一条消息是否是客服发的
   c. 如果是 → 发送补刀消息
   d. 如果不是（客户已回复）→ 标记为已响应
   e. 记录补刀尝试到 followup_attempts 表
   f. 返回列表
```

---

## 数据模型

### 数据库表

```sql
-- 客服表
CREATE TABLE kefus (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    serial TEXT UNIQUE,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP
);

-- 客户表
CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    channel TEXT,
    kefu_id INTEGER REFERENCES kefus(id),
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- 消息表
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    content TEXT,
    message_type TEXT DEFAULT 'text',
    is_from_kefu BOOLEAN DEFAULT 0,
    timestamp_raw TEXT,
    timestamp_parsed TIMESTAMP,
    message_hash TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP
);

-- 补刀尝试表
CREATE TABLE followup_attempts (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    attempt_number INTEGER NOT NULL,
    status TEXT NOT NULL,  -- 'pending', 'sent', 'failed'
    message_content TEXT,
    responded INTEGER DEFAULT 0,
    response_time_seconds INTEGER,
    created_at TIMESTAMP,
    sent_at TIMESTAMP,
    responded_at TIMESTAMP,
    error_message TEXT
);
```

### 状态流转

```
Customer Message Timeline:
─────────────────────────────────────────────────────────────►

  [客服消息]     [initial_delay]     [补刀1]     [subsequent_delay]     [补刀2]
      │              经过               │               经过                │
      ▼                                ▼                                  ▼
    ───●────────────────────────────────●────────────────────────────────●───

如果客户回复：
      │
      ▼
  [客户消息]  →  mark_responded()  →  重置补刀计数
```

---

## 与全量同步的协调

### 暂停/恢复机制

```python
# 全量同步开始时
await followup_service.pause_for_sync()
# - 设置 paused_for_sync = True
# - 请求取消当前扫描
# - 等待扫描结束

# 全量同步结束后
await followup_service.resume_after_sync()
# - 设置 paused_for_sync = False
# - 如果之前在运行则重新启动
```

### Phase 互斥

```python
# ResponseDetector 检查
if self._followup_scan_running:
    self._logger.info("Skipping response scan - follow-up scan is already in progress")
    return ...

# Scheduler 设置标志
self._detector.set_followup_scan_running(True)  # Phase 2 开始时
self._detector.set_followup_scan_running(False) # Phase 2 结束后
```

---

## Sidecar 集成

当 `send_via_sidecar = True` 时：

1. 生成的回复不会直接发送
2. 通过 SidecarQueueClient 推送到前端队列
3. 前端显示倒计时（默认 10 秒）
4. 用户可以：
   - 编辑回复内容
   - 立即发送
   - 取消发送
5. 倒计时结束自动发送（如果用户未干预）

---

## 工作时间限制

```python
def is_within_operating_hours() -> bool:
    if not enable_operating_hours:
        return True  # 24/7 运行

    current_hour = datetime.now().hour

    if start_hour <= end_hour:
        # 正常时段 (如 10:00 - 22:00)
        return start_hour <= current_hour < end_hour
    else:
        # 跨夜时段 (如 22:00 - 06:00)
        return current_hour >= start_hour or current_hour < end_hour
```

---

## API 接口

### 新架构 API (Multi-Device)

#### REST API 端点

```bash
# 启动单设备实时回复
POS../03-impl-and-arch/key-modules/realtime/device/{serial}/start
    ?scan_interval=60        # 扫描间隔（秒）
    &use_ai_reply=true       # 使用 AI 回复
    &send_via_sidecar=true   # 通过 Sidecar 发送

# 停止单设备实时回复
POS../03-impl-and-arch/key-modules/realtime/device/{serial}/stop

# 暂停单设备 (Windows: Job Objects, Unix: SIGSTOP)
POS../03-impl-and-arch/key-modules/realtime/device/{serial}/pause

# 恢复单设备 (Windows: Job Objects, Unix: SIGCONT)
POS../03-impl-and-arch/key-modules/realtime/device/{serial}/resume

# 获取单设备状态
GE../03-impl-and-arch/key-modules/realtime/device/{serial}/status

# 获取所有设备状态
GE../03-impl-and-arch/key-modules/realtime/devices/status
```

#### Python API

```python
from services.realtime_reply_manager import get_realtime_reply_manager

manager = get_realtime_reply_manager()

# 启动设备实时回复
await manager.start_realtime_reply(
    serial="DEVICE123",
    scan_interval=60,
    use_ai_reply=True,
    send_via_sidecar=True
)

# 停止设备实时回复
await manager.stop_realtime_reply("DEVICE123")

# 暂停/恢复
await manager.pause_realtime_reply("DEVICE123")
await manager.resume_realtime_reply("DEVICE123")

# 停止所有设备
await manager.stop_all()

# 状态查询
state = manager.get_state("DEVICE123")
all_states = manager.get_all_states()
is_running = manager.is_running("DEVICE123")
```

### 旧架构 API (单进程)

```python
# 启动/停止 (已弃用)
await followup_service.start_background_scanner()
await followup_service.stop_background_scanner()

# 状态查询
status = followup_service.get_scan_status()
# {
#   'running': True,
#   'enabled': True,
#   'paused_for_sync': False,
#   'last_scan': '2026-01-22T15:30:00',
#   'scan_interval': 60,
#   'in_operating_hours': True,
#   'scanner_running': False,
#   'followup_scan_running': False,
#   'response_scan_running': False,
#   'settings': {...}
# }

# 手动扫描
result = await followup_service.run_active_scan_for_device(serial)
result = await followup_service.scan_for_responses(serial)

# 候选人查询
candidates = followup_service.find_followup_candidates()
```

---

## WebSocket 实时日志

### 连接端点

```javascript
// 连接到设备的 follow-up 日志流
const ws = new WebSocket(`ws://localhost:8765/../03-impl-and-arch/${serial}/logs`)

ws.onmessage = (event) => {
  const log = JSON.parse(event.data)
  // {
  //   timestamp: "2026-01-22T15:30:00.123456",
  //   level: "INFO",
  //   message: "Found 2 unread users",
  //   source: "followup"
  // }
}
```

### 日志级别

| Level   | 含义                          |
| ------- | ----------------------------- |
| DEBUG   | 调试信息（默认不输出）        |
| INFO    | 正常流程日志                  |
| WARNING | 警告（如 Sidecar 初始化失败） |
| ERROR   | 错误（会记录到 state.errors） |

> **详细日志说明**：2026-02 起补刀执行器、队列管理器、响应检测器已增加详细日志（步骤、耗时、元素信息等）。参见 [补刀系统日志增强](followup-logging-enhancement.md)。

---

## 日志示例

### 新架构 (Multi-Device) 日志

```
============================================================
FOLLOW-UP PROCESS STARTED FOR DEVICE123
============================================================
Configuration:
   - Scan Interval: 60s
   - Use AI Reply: True
   - Send via Sidecar: True
============================================================
Database: D:\111\android_run_test-backup\wecom_conversations.db

[Scan #1] Checking for unread messages...

============================================================
PHASE 1: RESPONSE DETECTION (Red Dot Prioritized)
============================================================
Found 2 customers with SENT follow-ups awaiting response
Scanning 1 device(s): ['DEVICE123']

[DEVICE123] Starting response scan...
[DEVICE123] Step 1: Launching WeCom...
[DEVICE123] Step 2: Switching to External Chats...
[DEVICE123] Step 3: Scrolling to top...
[DEVICE123] Step 4: Detecting red dot users (first page only)...
[DEVICE123] 🔴 Found 2 priority users on first page (2 unread, 0 new friends)
[DEVICE123] 🔴 Found 2 red dot users, adding to queue

[DEVICE123] [1] 🔴 Processing: 张三 (queue: 1 remaining)
[DEVICE123] Processing: 张三
[DEVICE123]    - Unread count: 1
[DEVICE123] ✅ Reply sent to 张三
[DEVICE123] Checking for new red dots...

[DEVICE123] [2] 🔴 Processing: 李四 (queue: 0 remaining)
[DEVICE123] ✅ Reply sent to 李四

[DEVICE123] ✅ Queue empty, all red dot users processed

============================================================
PHASE 1 COMPLETE
============================================================
   Devices scanned: 1
   Users processed: 2
   Replies sent: 2
   Messages stored: 4
============================================================

[Scan #1] Processed 2 response(s)
Sleeping 60s until next scan...
```

### 旧架构 (BackgroundScheduler) 日志

```
============================================================
STARTING BACKGROUND FOLLOW-UP SCANNER
============================================================
Configuration:
   - Scan Interval: 60 seconds
   - Max Follow-ups: 3
   - Initial Delay: 120 seconds
   - Subsequent Delay: 120 seconds
   - Exponential Backoff: False
   - Operating Hours: 10:00 - 22:00
============================================================

Phase 1: Checking for customer responses (Instant Response ON)...
Phase 2: Finding customers who need follow-up from database...

Phase 2 Summary: candidates=2, sent=2, failed=0
Next scan cycle in 60 seconds...
```

---

## 常见问题

### Q: 新架构和旧架构的区别？

A:
| 旧架构 | 新架构 |
|--------|--------|
| `FollowUpService.start_background_scanner()` | `FollowUpDeviceManager.start_followup(serial)` |
| 单进程管理所有设备 | 每设备独立子进程 |
| 一个设备卡住影响所有 | 进程隔离互不影响 |
| 通过 `BackgroundScheduler` 调度 | 通过 `realtime_reply_process.py` 独立运行 |

### Q: 为什么客户一直收到补刀？

A: 检查：

1. 客户是否真的回复了（messages 表中 is_from_kefu=0 的记录）
2. mark_responded() 是否被正确调用
3. max_followups 设置是否合理

### Q: 为什么补刀没有发送？

A: 检查：

1. `enabled = True`？
2. 是否在工作时间内？
3. 冷却期是否已过？(`seconds_since_last_kefu_message >= required_delay`)
4. 是否已达 max_followups？
5. 设备是否在线？
6. 子进程是否正常运行？(`manager.is_running(serial)`)

### Q: 如何调试子进程？

A:

1. 查看 WebSocket 日志：`ws://localhost:8765/ws/realtime/{serial}/logs`
2. 直接运行脚本：`uv run realtime_reply_process.py --serial XXX --debug`
3. 检查 `RealtimeReplyState.errors` 数组

### Q: Phase 1 和 Phase 2 的区别？

A:

- Phase 1: 检测红点，处理客户的新消息，发送 AI 回复
- Phase 2: 根据数据库查询，对冷却期结束的客户发送补刀

> **注意**: 新架构中，`followup_process.py` 默认只运行 Phase 1（红点检测+回复）。
> Phase 2 补刀逻辑仍在 `ResponseDetector` 内，但需要数据库中有候选人。

### Q: 如何在 Windows 上暂停进程？

A: 使用 `Job Objects`，`RealtimeReplyManager` 会自动处理：

```python
job_manager.create_job(f"realtime_{serial}")
job_manager.add_process(f"realtime_{serial}", process.pid)
job_manager.suspend_job(f"realtime_{serial}")  # 暂停
job_manager.resume_job(f"realtime_{serial}")   # 恢复
```
