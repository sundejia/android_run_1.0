# 无感恢复功能实现计划

## 概述

### 功能目标

实现程序在异常退出、设备断连、网络中断等情况下的自动恢复能力，确保：

- 用户无需手动干预即可继续之前的任务
- 不会丢失已完成的进度
- 不会重复执行已完成的操作
- 系统状态在恢复后保持一致

### 适用场景

| 场景     | 描述               | 恢复需求                 |
| -------- | ------------------ | ------------------------ |
| 程序崩溃 | 后端服务异常退出   | 恢复扫描进度、待发送队列 |
| 设备断连 | ADB 连接中断       | 自动重连、继续未完成任务 |
| 网络中断 | AI 服务/API 不可用 | 重试机制、降级策略       |
| 系统重启 | 服务器/电脑重启    | 恢复全部状态             |
| 手动停止 | 用户主动停止后重启 | 从断点继续               |

---

## 架构设计

### 核心组件

```
┌─────────────────────────────────────────────────────────────┐
│                    Recovery Manager                          │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ State Store │  │ Task Queue  │  │ Checkpoint Manager  │  │
│  │  (SQLite)   │  │  (Memory +  │  │   (Persistence)     │  │
│  │             │  │   SQLite)   │  │                     │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ Device      │  │ Health      │  │ Graceful Shutdown   │  │
│  │ Reconnector │  │ Monitor     │  │ Handler             │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 数据流

```
启动时:
  1. 检查是否有未完成的任务（recovery_state 表）
  2. 加载上次的检查点
  3. 恢复任务队列
  4. 继续执行

运行时:
  1. 每完成一个任务 → 更新检查点
  2. 定期保存状态快照
  3. 监听系统信号（SIGTERM/SIGINT）

异常时:
  1. 捕获异常 → 保存当前状态
  2. 尝试自动恢复
  3. 失败则记录断点，等待下次启动恢复
```

---

## 数据库设计

### 新增表: `recovery_state`

```sql
CREATE TABLE IF NOT EXISTS recovery_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 任务标识
    task_type TEXT NOT NULL,           -- 'followup_scan', 'full_sync', 'phase2_scan'
    task_id TEXT UNIQUE NOT NULL,      -- 唯一任务ID (UUID)

    -- 状态信息
    status TEXT NOT NULL,              -- 'running', 'paused', 'failed', 'completed'
    progress_percent INTEGER DEFAULT 0,

    -- 检查点数据 (JSON)
    checkpoint_data TEXT,              -- 序列化的检查点信息

    -- 队列数据 (JSON)
    pending_items TEXT,                -- 待处理项目列表
    completed_items TEXT,              -- 已完成项目列表
    failed_items TEXT,                 -- 失败项目列表

    -- 设备信息
    device_serial TEXT,

    -- 时间戳
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_checkpoint_at TIMESTAMP,
    completed_at TIMESTAMP,

    -- 错误信息
    last_error TEXT,
    retry_count INTEGER DEFAULT 0,

    -- 索引优化
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_recovery_state_status ON recovery_state(status);
CREATE INDEX IF NOT EXISTS idx_recovery_state_task_type ON recovery_state(task_type);
```

### 新增表: `device_connection_state`

```sql
CREATE TABLE IF NOT EXISTS device_connection_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_serial TEXT UNIQUE NOT NULL,

    -- 连接状态
    is_connected INTEGER DEFAULT 0,
    last_connected_at TIMESTAMP,
    last_disconnected_at TIMESTAMP,

    -- 断连时的任务状态
    pending_task_id TEXT,              -- 关联 recovery_state.task_id

    -- 重连配置
    auto_reconnect INTEGER DEFAULT 1,
    reconnect_attempts INTEGER DEFAULT 0,
    max_reconnect_attempts INTEGER DEFAULT 5,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 实现计划

### Phase 1: 基础恢复框架 (预计 2-3 天)

#### 1.1 创建 RecoveryManager 类

```python
# wecom-desktop/backend/services/recovery/manager.py

class RecoveryManager:
    """无感恢复管理器"""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._ensure_tables()

    # 任务状态管理
    def create_task(self, task_type: str, device_serial: str) -> str: ...
    def update_checkpoint(self, task_id: str, checkpoint: dict): ...
    def mark_completed(self, task_id: str): ...
    def mark_failed(self, task_id: str, error: str): ...

    # 恢复逻辑
    def get_pending_tasks(self) -> List[RecoveryTask]: ...
    def get_task_checkpoint(self, task_id: str) -> Optional[dict]: ...
    def should_resume(self, task_type: str) -> bool: ...

    # 队列管理
    def save_queue_state(self, task_id: str, pending: List, completed: List): ...
    def load_queue_state(self, task_id: str) -> Tuple[List, List]: ...
```

#### 1.2 定义检查点数据结构

```python
# wecom-desktop/backend/services/recovery/models.py

@dataclass
class FollowupScanCheckpoint:
    """跟进扫描检查点"""
    scan_start_time: datetime
    current_user_index: int
    total_users: int
    processed_users: List[str]
    pending_users: List[str]
    current_phase: str  # 'phase1', 'phase2'

@dataclass
class RecoveryTask:
    """恢复任务"""
    task_id: str
    task_type: str
    status: str
    device_serial: str
    checkpoint: Optional[dict]
    started_at: datetime
    last_checkpoint_at: Optional[datetime]
```

#### 1.3 实现优雅关闭处理

```python
# wecom-desktop/backend/services/recovery/shutdown.py

class GracefulShutdownHandler:
    """优雅关闭处理器"""

    def __init__(self, recovery_manager: RecoveryManager):
        self._recovery = recovery_manager
        self._register_signals()

    def _register_signals(self):
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

    async def _handle_shutdown(self, signum, frame):
        """保存当前状态并优雅退出"""
        logger.info("Received shutdown signal, saving state...")
        await self._save_all_running_tasks()
        sys.exit(0)
```

### Phase 2: 集成到 FollowUp Scanner (预计 2-3 天)

#### 2.1 修改 FollowUpScanner

```python
# 在 scanner.py 中集成恢复逻辑

class FollowUpScanner:
    def __init__(self, ..., recovery_manager: RecoveryManager = None):
        self._recovery = recovery_manager or RecoveryManager(db_path)
        self._current_task_id: Optional[str] = None

    async def scan_device(self, device_serial: str, ...):
        # 检查是否有待恢复的任务
        pending = self._recovery.get_pending_tasks()
        if pending:
            return await self._resume_scan(pending[0])

        # 创建新任务
        self._current_task_id = self._recovery.create_task(
            'followup_scan', device_serial
        )

        try:
            # 执行扫描，定期保存检查点
            for idx, user in enumerate(user_queue):
                await self._process_user(user)

                # 每处理一个用户保存一次检查点
                self._recovery.update_checkpoint(self._current_task_id, {
                    'current_index': idx,
                    'processed': list(processed_names),
                    'pending': [u.name for u in user_queue],
                })

            self._recovery.mark_completed(self._current_task_id)

        except Exception as e:
            self._recovery.mark_failed(self._current_task_id, str(e))
            raise

    async def _resume_scan(self, task: RecoveryTask):
        """从检查点恢复扫描"""
        checkpoint = task.checkpoint
        logger.info(f"Resuming scan from checkpoint: {checkpoint}")

        # 恢复队列状态
        pending_users = checkpoint.get('pending', [])
        processed_users = set(checkpoint.get('processed', []))

        # 从断点继续
        ...
```

#### 2.2 添加定期检查点保存

```python
# 在长时间运行的任务中定期保存

CHECKPOINT_INTERVAL = 30  # 秒

async def _periodic_checkpoint_saver(self):
    """后台任务：定期保存检查点"""
    while self._running:
        await asyncio.sleep(CHECKPOINT_INTERVAL)
        if self._current_task_id:
            self._save_current_checkpoint()
```

### Phase 3: 设备断连恢复 (预计 2 天)

#### 3.1 创建 DeviceReconnector

```python
# wecom-desktop/backend/services/recovery/device_reconnector.py

class DeviceReconnector:
    """设备断连自动重连"""

    def __init__(self, recovery_manager: RecoveryManager):
        self._recovery = recovery_manager
        self._reconnect_tasks: Dict[str, asyncio.Task] = {}

    async def on_device_disconnected(self, device_serial: str):
        """设备断连回调"""
        logger.warning(f"Device {device_serial} disconnected")

        # 保存当前任务状态
        self._recovery.pause_device_tasks(device_serial)

        # 启动重连任务
        self._reconnect_tasks[device_serial] = asyncio.create_task(
            self._reconnect_loop(device_serial)
        )

    async def _reconnect_loop(self, device_serial: str):
        """重连循环"""
        for attempt in range(MAX_RECONNECT_ATTEMPTS):
            logger.info(f"Reconnect attempt {attempt + 1} for {device_serial}")

            if await self._try_reconnect(device_serial):
                logger.info(f"Device {device_serial} reconnected!")
                await self._resume_device_tasks(device_serial)
                return

            await asyncio.sleep(RECONNECT_INTERVAL * (2 ** attempt))  # 指数退避

        logger.error(f"Failed to reconnect {device_serial} after {MAX_RECONNECT_ATTEMPTS} attempts")
```

#### 3.2 集成到 DeviceManager

```python
# 在 device_manager.py 中添加断连检测

class DeviceManager:
    def __init__(self, ..., reconnector: DeviceReconnector = None):
        self._reconnector = reconnector

    async def _monitor_connections(self):
        """监控设备连接状态"""
        while True:
            for serial in self._active_devices:
                if not await self._is_device_connected(serial):
                    await self._reconnector.on_device_disconnected(serial)

            await asyncio.sleep(5)
```

### Phase 4: 健康监控与告警 (预计 1-2 天)

#### 4.1 创建 HealthMonitor

```python
# wecom-desktop/backend/services/recovery/health_monitor.py

class HealthMonitor:
    """系统健康监控"""

    def __init__(self, recovery_manager: RecoveryManager):
        self._recovery = recovery_manager
        self._health_checks = []

    def register_check(self, name: str, check_fn: Callable):
        self._health_checks.append((name, check_fn))

    async def run_health_checks(self) -> HealthReport:
        """运行所有健康检查"""
        results = {}
        for name, check_fn in self._health_checks:
            try:
                results[name] = await check_fn()
            except Exception as e:
                results[name] = HealthStatus.UNHEALTHY

        return HealthReport(results)

    async def get_recovery_status(self) -> dict:
        """获取恢复状态摘要"""
        pending = self._recovery.get_pending_tasks()
        return {
            'pending_tasks': len(pending),
            'tasks': [t.to_dict() for t in pending],
            'can_resume': len(pending) > 0,
        }
```

#### 4.2 添加 API 端点

```python
# wecom-desktop/backend/routers/recovery.py

router = APIRouter(prefix../03-impl-and-arch/key-modules/recovery", tags=["recovery"])

@router.get("/status")
async def get_recovery_status():
    """获取恢复状态"""
    manager = get_recovery_manager()
    return await manager.get_status()

@router.post("/resume")
async def resume_tasks():
    """手动触发恢复"""
    manager = get_recovery_manager()
    return await manager.resume_all_pending()

@router.post("/clear")
async def clear_recovery_state():
    """清除恢复状态（放弃恢复）"""
    manager = get_recovery_manager()
    return await manager.clear_all()
```

---

## 前端集成

### 恢复提示 UI

```vue
<!-- src/components/RecoveryPrompt.vue -->
<template>
  <div v-if="hasRecoverableTasks" class="recovery-prompt">
    <div class="recovery-icon">⚠️</div>
    <div class="recovery-content">
      <h4>检测到未完成的任务</h4>
      <p>上次运行被中断，发现 {{ pendingTasks.length }} 个未完成任务</p>
      <ul>
        <li v-for="task in pendingTasks" :key="task.id">
          {{ task.task_type }} - 进度 {{ task.progress_percent }}%
        </li>
      </ul>
    </div>
    <div class="recovery-actions">
      <button @click="resumeTasks" class="btn-primary">继续执行</button>
      <button @click="discardTasks" class="btn-secondary">放弃</button>
    </div>
  </div>
</template>
```

### 状态指示器

```vue
<!-- 在 FollowUpPanel 中添加恢复状态指示 -->
<div v-if="isRecovering" class="recovering-indicator">
  <span class="spinner"></span>
  正在从断点恢复... ({{ recoveryProgress }}%)
</div>
```

---

## 测试计划

### 单元测试

```python
# tests/unit/test_recovery_manager.py

class TestRecoveryManager:
    def test_create_task(self): ...
    def test_update_checkpoint(self): ...
    def test_resume_from_checkpoint(self): ...
    def test_handle_multiple_pending_tasks(self): ...
```

### 集成测试

```python
# tests/integration/test_seamless_recovery.py

class TestSeamlessRecovery:
    async def test_recover_after_crash(self):
        """模拟崩溃后恢复"""
        # 1. 启动扫描
        # 2. 中途强制停止
        # 3. 重新启动
        # 4. 验证从断点继续

    async def test_recover_after_device_disconnect(self):
        """模拟设备断连后恢复"""
        # 1. 启动扫描
        # 2. 断开设备
        # 3. 重连设备
        # 4. 验证自动继续
```

### 手动测试场景

| 场景     | 操作               | 预期结果                     |
| -------- | ------------------ | ---------------------------- |
| 正常中断 | Ctrl+C 停止程序    | 保存检查点，下次启动提示恢复 |
| 强制终止 | 任务管理器结束进程 | 使用上次检查点恢复           |
| 设备断连 | 拔掉 USB 线        | 自动重连并继续               |
| 网络中断 | 断开 AI 服务网络   | 降级到模板消息，稍后重试     |

---

## 实现优先级

| 优先级 | 功能                     | 预计工时 | 依赖                 |
| ------ | ------------------------ | -------- | -------------------- |
| P0     | RecoveryManager 基础框架 | 1 天     | -                    |
| P0     | 数据库表创建             | 0.5 天   | -                    |
| P0     | 优雅关闭处理             | 0.5 天   | RecoveryManager      |
| P1     | FollowUpScanner 集成     | 2 天     | RecoveryManager      |
| P1     | 检查点自动保存           | 0.5 天   | FollowUpScanner 集成 |
| P2     | 设备断连重连             | 2 天     | RecoveryManager      |
| P2     | 前端恢复提示             | 1 天     | API 端点             |
| P3     | 健康监控                 | 1 天     | RecoveryManager      |
| P3     | 完整测试覆盖             | 1-2 天   | 所有功能             |

**总计预估：8-10 天**

---

## 风险与缓解

| 风险             | 影响          | 缓解措施                 |
| ---------------- | ------------- | ------------------------ |
| 检查点数据损坏   | 无法恢复      | 多版本检查点、校验和验证 |
| 恢复后状态不一致 | 重复操作/遗漏 | 幂等性设计、去重机制     |
| 频繁保存影响性能 | 扫描变慢      | 异步保存、批量写入       |
| 设备重连失败     | 任务卡住      | 超时机制、人工干预入口   |

---

## 参考资料

- SQLite WAL 模式（提高并发写入性能）
- Python asyncio 信号处理
- 分布式系统检查点设计模式
