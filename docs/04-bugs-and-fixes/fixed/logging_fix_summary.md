# 日志系统修复总结

## 问题描述

1. `lo../03-impl-and-arch/response_detector.log` 一直为空
2. `lo../03-impl-and-arch/scanner.log` 一直为空
3. `lo../03-impl-and-arch/followup.log` 一直为空
4. Backend 没有正确记录前端显示的所有日志内容

## 问题根源

### 1. followup_process.py (scanner)

- 只配置了 stdout 输出（由父进程捕获）
- 没有文件日志处理器
- → `scanner.log` 为空

### 2. response_detector.py

- 有文件日志配置
- 但未设置 `propagate=True`，日志不传播到根 logger
- → `response_detector.log` 为空

### 3. FollowUpService (service.py)

- `_LogHandler` 只转发到 WebSocket（前端显示）
- 不写入文件
- → `followup.log` 为空，且 backend 没有完整日志

## 解决方案

### 1. 修复 followup_process.py

**变更**: `setup_logging()` 函数

```python
def setup_logging(serial: str, debug: bool = False):
    """设置日志 - 同时输出到文件和 stdout（由父进程捕获）"""
    # 创建日志目录
    log_dir = PROJECT_ROOT / "logs" / "followup"
    log_dir.mkdir(parents=True, exist_ok=True)

    # 配置根 logger（确保所有日志都被捕获）
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 1. 文件日志处理器 (scanner.log)
    file_handler = TimedRotatingFileHandler(
        log_dir / "scanner.log",
        when="midnight",
        backupCount=0,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d"
    root_logger.addHandler(file_handler)

    # 2. 控制台输出处理器（由父进程捕获并通过 WebSocket 转发到前端）
    console_handler = logging.StreamHandler(sys.stdout)
    root_logger.addHandler(console_handler)

    # 配置 wecom_automation 相关 logger 确保传播
    for logger_name in ["wecom_automation", "followup", ...]:
        logger = logging.getLogger(logger_name)
        logger.propagate = True

    return logging.getLogger("followup.scanner")
```

**效果**:

- ✅ 写入 `scanner.log`
- ✅ 输出到 stdout（由父进程捕获并转发到前端）

### 2. 修复 response_detector.py

**变更**: `_setup_response_detector_logging()` 函数

```python
def _setup_response_detector_logging():
    """配置 ResponseDetector 服务日志 - 同时写入文件和传播到父进程"""
    # 获取 logger 并配置
    detector_logger = logging.getLogger("followup.response_detector")

    # 添加文件处理器（只添加一次，避免重复）
    if not any(isinstance(h, TimedRotatingFileHandler) for h in detector_logger.handlers):
        detector_logger.addHandler(file_handler)

    # 确保日志传播到根 logger（这样父进程的 stdout 也能捕获）
    detector_logger.propagate = True
```

**效果**:

- ✅ 写入 `response_detector.log`
- ✅ 传播到根 logger（由父进程捕获）

### 3. 修复 FollowUpService (service.py)

**变更**: 创建 `_EnhancedLogHandler` 类

```python
class _EnhancedLogHandler(logging.Handler):
    """
    Enhanced log handler that writes to file AND forwards to frontend.

    This handler performs two functions:
    1. Writes all logs to backend log file (followup.log)
    2. Forwards logs to frontend via WebSocket callbacks
    """
    def _setup_file_handler(self):
        """Setup file handler for persistent logging."""
        # 使用项目统一的项目根目录获取方法
        from wecom_automation.core.config import get_project_root
        project_root = get_project_root()

        log_dir = project_root / "logs" / "followup"
        self._file_handler = TimedRotatingFileHandler(
            log_dir / "followup.log",
            when="midnight",
            backupCount=0,
            encoding="utf-8",
        )

    def emit(self, record):
        # 1. Write to file
        if self._file_handler:
            self._file_handler.emit(record)

        # 2. Forward to frontend
        log_entry = {...}
        self.service._log_history.append(log_entry)
        await self.service._broadcast_log(log_entry)
```

**效果**:

- ✅ 写入 `followup.log`
- ✅ 转发到前端（WebSocket）
- ✅ Backend 现在有完整的日志记录

### 4. 使用统一的项目根目录获取方法

**变更**: 使用 `get_project_root()` 而不是手动计算路径

```python
from wecom_automation.core.config import get_project_root

project_root = get_project_root()  # 支持环境变量 WECOM_PROJECT_ROOT
log_dir = project_root / "logs" / "followup"
```

**优势**:

- 统一的路径管理
- 支持环境变量覆盖
- 避免硬编码路径计算

## 验证结果

所有测试通过：

```
=== 测试 followup_process.py 日志 ===
[OK] scanner.log 已创建
[OK] scanner.log 包含测试日志

=== 测试 response_detector.py 日志 ===
[OK] response_detector.log 已创建
[OK] response_detector.log 包含测试日志

=== 测试 FollowUpService 日志 ===
[OK] followup.log 已创建
[OK] followup.log 包含测试日志
[OK] 日志历史记录数: 3
```

## 日志文件结构

```
logs/
└── followup/
    ├── scanner.log              # followup_process.py 的日志
    ├── response_detector.log    # response_detector.py 的日志
    └── followup.log             # FollowUpService 的日志
```

## 日志格式

所有日志文件使用统一格式：

```
YYYY-MM-DD HH:MM:SS | LEVEL     | Message
```

示例：

```
2026-01-23 17:56:43 | INFO     | Starting response scan...
2026-01-23 17:56:43 | WARNING  | Could not click on user
2026-01-23 17:56:43 | ERROR    | Failed to extract messages
```

## 额外改进

1. **日志轮转**: 使用 `TimedRotatingFileHandler` 每天午夜自动轮转
2. **永久保留**: `backupCount=0` 保留所有历史日志
3. **UTF-8 编码**: 支持中文等非 ASCII 字符
4. **Windows 兼容**: 测试脚本添加了 UTF-8 编码设置

## 相关文件

| 文件                                                                   | 变更 | 说明                      |
| ---------------------------------------------------------------------- | ---- | ------------------------- |
| `followup_process.py`                                                  | 修改 | 添加文件日志处理器        |
| `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py` | 修改 | 设置 propagate=True       |
| `wecom-desktop/backend/servic../03-impl-and-arch/service.py`           | 修改 | 创建 \_EnhancedLogHandler |
| `test_logging.py`                                                      | 新增 | 日志系统测试脚本          |

## 测试方法

运行测试脚本验证日志功能：

```bash
uv run test_logging.py
```

预期输出：

- 所有日志文件已创建
- 所有日志文件包含测试日志
- 日志历史记录正常（用于前端显示）
