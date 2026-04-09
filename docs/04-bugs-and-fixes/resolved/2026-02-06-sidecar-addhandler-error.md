# Sidecar 初始化错误修复: 'Logger' object has no attribute 'addHandler'

**日期**: 2026-02-06  
**严重性**: 🔴 Critical  
**状态**: ✅ 已解决

---

## 📋 问题描述

在启动 Follow-up 进程时遇到以下错误：

```
[AN2FVB1706003302] Failed to init sidecar client: 'Logger' object has no attribute 'addHandler'
```

### 错误位置

- **触发点**: `wecom-desktop/backend/services/followup/service.py` 的 `__init__` 方法
- **错误原因**: 尝试对 `loguru.logger` 调用 `addHandler()` 方法
- **错误代码**:
  ```python
  logger.addHandler(self._log_handler)  # ❌ loguru 没有 addHandler()
  ```

---

## 🔍 根本原因

### 1. Loguru 迁移不完整

在之前的 loguru 迁移中，`service.py` 文件被更新为使用 `get_logger()`：

```python
from wecom_automation.core.logging import get_logger
logger = get_logger("followup_service")
```

但 `__init__` 方法中仍然保留了 `stdlib logging` 的 `addHandler()` 调用：

```python
# ❌ 错误：loguru.logger 没有 addHandler 方法
logger.addHandler(self._log_handler)
logger.setLevel(logging.INFO)
```

### 2. \_EnhancedLogHandler 设计冲突

`service.py` 使用了 `_EnhancedLogHandler` 类（继承自 `logging.Handler`）来实现：

1. 将日志写入文件 (`followup-service-legacy.log`)
2. 转发日志到前端 WebSocket

这个设计基于 `stdlib logging` 的 Handler 机制，与 loguru 的 sink 机制不兼容。

### 3. SidecarQueueClient 的 Logger 类型

`SidecarQueueClient.__init__` 接受 `logging.Logger` 类型提示：

```python
def __init__(self, ..., logger: logging.Logger | None = None):
    self._logger = logger or logging.getLogger(__name__)
```

当传入 loguru logger 时，类型不匹配导致后续调用失败。

---

## 🛠️ 解决方案

### 修改 1: 将 `_EnhancedLogHandler` 改为 Loguru Sinks

**文件**: `wecom-desktop/backend/services/followup/service.py`

#### 之前（stdlib logging）

```python
def __init__(self, db_path: str | None = None):
    # ...
    self._log_handler = self._EnhancedLogHandler(self)
    self._log_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(self._log_handler)  # ❌ loguru 不支持
    logger.setLevel(logging.INFO)

class _EnhancedLogHandler(logging.Handler):
    def __init__(self, service):
        super().__init__()
        self.service = service
        self._file_handler = None
        self._setup_file_handler()

    def emit(self, record):
        # 写入文件和转发到前端
        ...
```

#### 之后（loguru sinks）

```python
def __init__(self, db_path: str | None = None):
    # ...
    self._sink_ids: list[int] = []
    self._setup_loguru_sinks()

def _setup_loguru_sinks(self):
    """Setup loguru sinks for file logging and frontend forwarding."""
    from loguru import logger as _loguru_logger

    # 1. 文件 sink
    file_sink_id = _loguru_logger.add(
        log_dir / "followup-service-legacy.log",
        rotation="00:00",  # 每天午夜轮换
        retention="7 days",
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        filter=lambda record: record["extra"].get("module") == "followup_service",
    )
    self._sink_ids.append(file_sink_id)

    # 2. 前端转发 sink
    def frontend_sink(message):
        record = message.record
        log_entry = {
            "timestamp": record["time"].isoformat(),
            "level": record["level"].name,
            "message": record["message"],
            "source": "followup",
        }

        # 添加到历史
        self._log_history.append(log_entry)
        if len(self._log_history) > FollowUpService.MAX_LOG_HISTORY:
            self._log_history = self._log_history[-FollowUpService.MAX_LOG_HISTORY :]

        # 广播到回调
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(self._broadcast_log(log_entry), loop=loop)
        except RuntimeError:
            self._broadcast_log_sync(log_entry)

    frontend_sink_id = _loguru_logger.add(
        frontend_sink,
        format="{message}",
        filter=lambda record: record["extra"].get("module") == "followup_service",
    )
    self._sink_ids.append(frontend_sink_id)

def __del__(self):
    """Cleanup: Remove loguru sinks."""
    for sink_id in self._sink_ids:
        try:
            _loguru_logger.remove(sink_id)
        except Exception:
            pass
```

**关键改进**:

- ✅ 使用 `_loguru_logger.add()` 替代 `addHandler()`
- ✅ 文件轮换使用 loguru 内置的 `rotation` 参数
- ✅ 自定义 sink 函数替代 `Handler.emit()`
- ✅ 使用 `filter` 参数过滤特定模块的日志
- ✅ 清理时使用 `_loguru_logger.remove(sink_id)`

### 修改 2: 更新 `SidecarQueueClient` 支持 Loguru

**文件**: `src/wecom_automation/services/integration/sidecar.py`

#### 之前

```python
import logging

def __init__(self, serial: str, backend_url: str = "http://localhost:8765", logger: logging.Logger | None = None):
    self._logger = logger or logging.getLogger(__name__)
```

#### 之后

```python
from typing import Any

def __init__(self, serial: str, backend_url: str = "http://localhost:8765", logger: Any = None):
    """
    初始化边车队列客户端

    Args:
        serial: 设备序列号
        backend_url: 后端服务URL
        logger: 日志记录器（支持 loguru 或 stdlib logging）
    """
    self.serial = serial
    self.backend_url = backend_url.rstrip("/")
    self._session: aiohttp.ClientSession | None = None

    # Accept both loguru and stdlib logging loggers
    if logger is None:
        from wecom_automation.core.logging import get_logger
        self._logger = get_logger(__name__)
    else:
        self._logger = logger
```

**关键改进**:

- ✅ 类型提示改为 `Any` 支持 loguru 和 stdlib logging
- ✅ 默认使用 `get_logger()` 获取 loguru logger
- ✅ 接受任何 logger 对象（duck typing）

---

## 🔍 验证步骤

### 1. 语法验证

```bash
python -m py_compile "d:\111\android_run_test-backup\wecom-desktop\backend\services\followup\service.py"
python -m py_compile "d:\111\android_run_test-backup\src\wecom_automation\services\integration\sidecar.py"
```

**结果**: ✅ 所有文件语法正确

### 2. 导入测试

```bash
python -c "from wecom_automation.services.integration.sidecar import SidecarQueueClient; print('✅ OK')"
```

**结果**: ✅ 导入成功

### 3. 运行时测试

启动 Follow-up 进程，验证：

- ✅ 不再出现 `addHandler` 错误
- ✅ Sidecar 客户端正确初始化
- ✅ 日志正常输出到 `logs/followup-service-legacy.log`
- ✅ 日志正常转发到前端 WebSocket

---

## 📚 相关技术要点

### Loguru Sink 机制

Loguru 使用 **sink** 替代 stdlib logging 的 **handler**：

| stdlib logging                  | loguru                   |
| ------------------------------- | ------------------------ |
| `logger.addHandler(handler)`    | `logger.add(sink)`       |
| `Handler.emit(record)`          | `sink(message)`          |
| `logger.removeHandler(handler)` | `logger.remove(sink_id)` |
| `Handler.setLevel()`            | `level=` 参数            |
| `Handler.setFormatter()`        | `format=` 参数           |
| `Handler.addFilter()`           | `filter=` 参数           |

### 自定义 Sink 函数

```python
def custom_sink(message):
    """
    Args:
        message: loguru.Message 对象
            - message.record: 包含 time, level, message, extra 等字段的字典
    """
    record = message.record
    print(f"{record['time']} | {record['level'].name} | {record['message']}")

logger.add(custom_sink)
```

### Filter 按模块过滤

```python
logger.add(
    sink,
    filter=lambda record: record["extra"].get("module") == "followup_service"
)

# 使用时需要绑定 module
from wecom_automation.core.logging import get_logger
logger = get_logger("followup_service")  # 自动绑定 module="followup_service"
```

---

## 🎯 影响范围

### 修改的文件

1. ✅ `wecom-desktop/backend/services/followup/service.py` (重构 logging)
2. ✅ `src/wecom_automation/services/integration/sidecar.py` (类型提示)

### 不需要修改的文件

- `response_detector.py` - 已使用 loguru `get_logger()`
- `realtime_reply_process.py` - 已使用 loguru `init_logging()`
- `initial_sync.py` - 已使用 loguru `init_logging()`

---

## 📝 经验教训

### 1. 迁移时检查所有 Logger 使用方式

在从 stdlib logging 迁移到 loguru 时，需要全面检查：

- `logger.addHandler()` → `logger.add()`
- `logger.setLevel()` → `level=` 参数
- `Handler.emit()` → sink 函数
- `Handler.setFormatter()` → `format=` 参数

### 2. 类型提示要宽松

当一个类接受 logger 参数时，使用 `Any` 而不是 `logging.Logger`，以支持不同的日志库（loguru, stdlib logging, structlog 等）。

### 3. Legacy 代码需要特殊处理

标记为 LEGACY 的代码可能使用旧的 logging 机制，需要：

- 评估是否值得迁移（如果很快会被删除，可以最小化修改）
- 确保与新系统兼容（如本次修复）
- 在文档中明确标注 LEGACY 状态

---

## 🔗 相关文档

- `docs/05-changelog-and-upgrades/2026-02-06-loguru-migration-complete.md` - Loguru 迁移总结
- `docs/03-impl-and-arch/key-modules/logging-system-architecture.md` - 日志系统架构
- `docs/04-bugs-and-fixes/resolved/2026-02-06-sidecar-client-none-warning.md` - Sidecar 客户端优先级修复

---

**状态**: ✅ **已解决且已验证**  
**测试**: ✅ **通过**  
**生产就绪**: ✅ **是**
