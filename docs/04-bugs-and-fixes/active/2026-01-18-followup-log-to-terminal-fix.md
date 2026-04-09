# Follow-up System 日志输出重定向方案

**创建日期**: 2026-01-18  
**状态**: 待实施

## 目标

**将当前输出到终端的 Follow-up 相关日志，重定向到前端 Logs 页面的 "Follow-up" 日志项中显示。**

## 问题描述

当前 Follow-up System 运行时，部分日志输出到了后端终端（控制台），而没有传递到前端 Logs 页面的 Follow-up 日志区域。用户无法在前端界面看到这些重要的操作日志。

### 当前行为

- 这些日志输出到**终端**（后端控制台）
- 用户需要查看终端才能看到这些日志
- 前端 Logs 页面的 Follow-up 日志项**看不到**这些信息

### 期望行为

- 这些日志应该显示在**前端 Logs 页面的 Follow-up 日志项**中
- 与其他 Follow-up 日志（如 "Phase 1", "Phase 2" 等）一起显示
- 用户无需查看终端即可获得完整的日志信息

### 涉及的日志内容

以下是当前输出到终端的日志示例（需要重定向到 Logs 页面）：

```
Scrolling to top (max_attempts=1000, stable_threshold=3)...
UI stable after consecutive scrolls - assuming top reached
[Swipe Stats] Scroll to top: 4 scroll-to-top operations (540, 400 -> 540, 1000, 300ms each)
Scrolled to top
Getting UI state...
Current filter: Private Chats
Already showing 'Private Chats' - no action needed
```

这些日志来自 `wecom_automation.services.wecom_service.WeComService` 和 `wecom_automation.services.adb_service.ADBService`。

## 问题根因分析

### 日志系统架构

当前系统有两套独立的日志配置：

1. **Follow-up Service 日志** (`followup_service`)
   - 位置: `wecom-desktop/backend/servic../03-impl-and-arch/service.py`
   - 有自定义 `_LogHandler`，会将日志广播到 WebSocket 客户端
   - 日志通过 `_log_callbacks` 传递给前端

2. **wecom_automation 日志** (`wecom_automation.*`)
   - 位置: `src/wecom_automation/core/logging.py`
   - 使用 `logging.StreamHandler` 输出到控制台
   - **没有** 连接到 Follow-up Service 的日志流

### 问题来源

当 Follow-up System 调用 `WeComService` 时：

```python
# scheduler.py 或 scanner.py
wecom = WeComService(config)
await wecom.launch_wecom(wait_for_ready=True)  # ← 这里的日志输出到控制台
await wecom.switch_to_private_chats()           # ← 这里的日志输出到控制台
```

`WeComService` 内部使用的 logger 是：

```python
# wecom_service.py
self.logger = get_logger("wecom_automation.wecom")
```

这个 logger 通过 `setup_logger()` 初始化时添加了 `StreamHandler`：

```python
# logging.py
console_handler = logging.StreamHandler()  # ← 输出到 sys.stdout
logger.addHandler(console_handler)
```

## 解决方案

### 方案 1: 统一 Logger Handler（推荐）

将 `wecom_automation` 模块的日志也连接到 Follow-up Service 的日志流。

#### 实现步骤

**Step 1: 在 FollowUpService 中注册 wecom_automation 的 logger**

修改 `wecom-desktop/backend/servic../03-impl-and-arch/service.py`:

```python
class FollowUpService:
    def __init__(self, db_path: Optional[str] = None):
        # ... existing code ...

        # Setup logging handler for followup logger
        self._log_handler = self._LogHandler(self)
        self._log_handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(self._log_handler)
        logger.setLevel(logging.INFO)

        # ===== NEW: 同时连接 wecom_automation 相关的 logger =====
        self._wecom_loggers = [
            "wecom_automation",
            "wecom_automation.wecom",
            "wecom_automation.adb",
            "wecom_automation.ui_parser",
        ]
        for logger_name in self._wecom_loggers:
            wecom_logger = logging.getLogger(logger_name)
            wecom_logger.addHandler(self._log_handler)
            # 可选：移除 StreamHandler 以避免重复输出到终端
            for handler in wecom_logger.handlers[:]:
                if isinstance(handler, logging.StreamHandler):
                    wecom_logger.removeHandler(handler)
```

**Step 2: 确保 logger 在销毁时移除 handler（可选，防止内存泄漏）**

```python
def __del__(self):
    # 清理 wecom_automation 的 logger handlers
    for logger_name in self._wecom_loggers:
        wecom_logger = logging.getLogger(logger_name)
        if self._log_handler in wecom_logger.handlers:
            wecom_logger.removeHandler(self._log_handler)
```

### 方案 2: 传递自定义 Logger

在创建 `WeComService` 时传入自定义 logger。

#### 实现步骤

**Step 1: 修改 WeComService 以支持自定义 logger**

修改 `src/wecom_automation/services/wecom_service.py`:

```python
class WeComService:
    def __init__(self, config: Optional[Config] = None, logger: Optional[logging.Logger] = None):
        self.config = config or Config()
        self.logger = logger or get_logger("wecom_automation.wecom")  # 使用传入的 logger
        # ...
```

**Step 2: 在 Follow-up Scanner 中传入 logger**

修改 `wecom-desktop/backend/servic../03-impl-and-arch/scanner.py`:

```python
async def scan_device(...):
    # ...
    config = Config(scroll=custom_scroll, device_serial=serial)
    wecom = WeComService(config, logger=self._logger)  # ← 传入 followup 的 logger
    # ...
```

### 方案 3: 使用日志过滤器（最小修改）

只输出 followup 相关的日志，过滤掉 wecom_automation 的日志。

**不推荐**：这会丢失有用的调试信息。

## 推荐方案

**推荐方案 1**，理由：

1. **一次性修改**：只需修改 `service.py`，所有 wecom_automation 的日志都会自动转发
2. **向后兼容**：不需要修改 `WeComService` 的接口
3. **灵活性**：可以选择性地移除 StreamHandler，避免终端输出

## 受影响的文件

| 文件                                                         | 修改内容                                |
| ------------------------------------------------------------ | --------------------------------------- |
| `wecom-desktop/backend/servic../03-impl-and-arch/service.py` | 添加 wecom_automation logger 的 handler |

## 测试验证

修复后，以下日志应该出现在**前端 Logs 页面的 Follow-up 日志项**中，而不是后端终端：

1. `Scrolling to top (max_attempts=1000, stable_threshold=3)...`
2. `UI stable after consecutive scrolls - assuming top reached`
3. `[Swipe Stats] Scroll to top: ...`
4. `Getting UI state...`
5. `Current filter: Private Chats`
6. `Already showing 'Private Chats' - no action needed`

### 验证步骤

1. 启动 Follow-up System（在前端开启）
2. 等待 Follow-up 执行扫描周期
3. 打开前端 **Logs 页面**，选择 **Follow-up** 日志项
4. 确认上述日志出现在 Follow-up 日志列表中
5. 确认后端终端不再输出这些日志（或只输出到日志文件）

## 附录

### 相关文件

**Follow-up 日志配置**:

- `wecom-desktop/backend/servic../03-impl-and-arch/service.py:103-131` - `_LogHandler` 类

**wecom_automation 日志配置**:

- `src/wecom_automation/core/logging.py:49-94` - `setup_logger()` 函数
- `src/wecom_automation/core/logging.py:97-109` - `get_logger()` 函数

**日志输出来源**:

- `src/wecom_automation/services/wecom_service.py` - WeComService 日志
- `src/wecom_automation/services/adb_service.py` - ADBService 日志 (Swipe Stats 等)

### Logger 层级结构

```
logging.root
├── followup_service          → 已连接到 WebSocket
├── followup.scheduler        → 已连接到 WebSocket (通过 followup_service logger)
├── followup.scanner          → 已连接到 WebSocket
├── followup.response_detector → 已连接到 WebSocket
├── followup.repository       → 未连接
├── followup.settings         → 未连接
├── wecom_automation          → 输出到终端 (需要修复)
│   ├── wecom_automation.wecom → 输出到终端 (需要修复)
│   ├── wecom_automation.adb   → 输出到终端 (需要修复)
│   └── wecom_automation.ui_parser → 输出到终端 (需要修复)
```
