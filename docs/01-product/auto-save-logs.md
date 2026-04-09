# 日志自动保存本地文件功能方案

## 概述

实现日志自动保存到本地文件功能，支持按日期轮转，方便调试和问题追踪。

## 当前日志系统分析

### 现有实现

1. **核心日志模块**: `src/wecom_automation/core/logging.py`
   - 提供 `setup_logger()` 函数，支持可选的文件日志
   - 支持自定义格式化器 `StructuredFormatter`
   - 包含 `SwipeLogFilter` 过滤冗余日志

2. **后端服务**: `wecom-desktop/backend/main.py`
   - 使用 uvicorn 内置日志
   - **没有配置文件日志**

3. **独立脚本** (如 `initial_sync.py`, `extract_conversation.py`)
   - 各自独立配置 FileHandler
   - 日志文件名硬编码

### 当前问题

| 问题           | 描述                                    |
| -------------- | --------------------------------------- |
| 后端无文件日志 | FastAPI 后端服务的日志只输出到控制台    |
| 日志不持久化   | 关闭终端后日志丢失，无法追溯问题        |
| 无日志轮转     | 没有按日期/大小轮转，日志文件会无限增长 |
| 日志分散       | 各模块日志配置不统一                    |

## 目标

1. **自动保存**: 所有日志自动保存到本地文件
2. **按日期轮转**: 每天生成新日志文件，保留历史
3. **统一配置**: 提供中央化日志配置
4. **易于查看**: 日志文件易于定位和查看

## 设计方案

### 1. 日志目录结构

```
项目根目录/
├── logs/
│   ├── backend/           # 后端服务日志
│   │   ├── backend_2026-01-21.log
│   │   ├── backend_2026-01-20.log
│   │   └── ...
│   ├── sync/              # 同步服务日志
│   │   ├── sync_2026-01-21.log
│   │   └── ...
│   ├── followup/          # FollowUp服务日志
│   │   ├── followup_2026-01-21.log
│   │   └── ...
│   └── all.log            # 合并日志（最近）
```

### 2. 日志配置类

```python
# src/wecom_automation/core/log_config.py

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
import logging
from logging.handlers import TimedRotatingFileHandler

@dataclass
class LogConfig:
    """日志配置"""
    log_dir: Path                     # 日志目录
    log_name: str = "app"             # 日志名称前缀
    level: int = logging.INFO         # 日志级别
    keep_forever: bool = True         # 永久保留日志
    console_output: bool = True       # 是否输出到控制台

    @property
    def log_file(self) -> Path:
        """获取当天的日志文件路径"""
        date_str = datetime.now().strftime("%Y-%m-%d")
        return self.log_dir / f"{self.log_name}_{date_str}.log"


def setup_file_logging(
    name: str = "wecom",
    log_dir: Optional[Path] = None,
    console: bool = True,
    level: int = logging.INFO,
) -> logging.Logger:
    """
    配置日志自动保存到文件

    Args:
        name: 日志名称（用作文件名前缀）
        log_dir: 日志目录，默认为 项目根目录/logs/
        console: 是否同时输出到控制台
        level: 日志级别
        # 日志永久保留，不自动删除

    Returns:
        配置好的 Logger 实例
    """
    # 确定日志目录
    if log_dir is None:
        project_root = Path(__file__).resolve().parents[3]
        log_dir = project_root / "logs" / name

    log_dir.mkdir(parents=True, exist_ok=True)

    # 创建 Logger
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()

    # 日志格式
    file_format = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_format = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S"
    )

    # 文件Handler（按日期轮转）
    log_file = log_dir / f"{name}.log"
    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",        # 每天午夜轮转
        interval=1,
        backupCount=0,          # 0 = 永久保留，不删除历史日志
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d"  # 文件后缀格式
    file_handler.setLevel(level)
    file_handler.setFormatter(file_format)
    logger.addHandler(file_handler)

    # 控制台Handler（可选）
    if console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(console_format)
        logger.addHandler(console_handler)

    return logger
```

### 3. 后端集成

修改 `wecom-desktop/backend/main.py`:

```python
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

def setup_backend_logging():
    """配置后端服务日志"""
    project_root = Path(__file__).parent.parent.parent
    log_dir = project_root / "logs" / "backend"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "backend.log"

    # 配置根Logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # 文件Handler
    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=0,  # 永久保留
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d"
    file_format = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_format)
    root_logger.addHandler(file_handler)

    print(f"[startup] Logging to file: {log_file}")

# 在 lifespan 函数中调用
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 设置日志
    setup_backend_logging()
    print("[startup] Backend logging configured")

    # ... 其余启动逻辑
```

### 4. FollowUp 服务集成

修改 `wecom-desktop/backend/services/followup_service.py`:

```python
from logging.handlers import TimedRotatingFileHandler

def _setup_followup_logging(self):
    """配置 FollowUp 服务日志"""
    log_dir = self._project_root / "logs" / "followup"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "followup.log"

    handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        backupCount=0,  # 永久保留
        encoding="utf-8",
    )
    handler.suffix = "%Y-%m-%d"
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))

    self._logger.addHandler(handler)
```

## 任务清单

### Task 1: 创建日志配置模块

- **文件**: `src/wecom_automation/core/log_config.py`
- **内容**: 实现 `setup_file_logging()` 函数
- **复杂度**: 中

### Task 2: 修改后端 main.py

- **文件**: `wecom-desktop/backend/main.py`
- **内容**: 添加 `setup_backend_logging()` 并在启动时调用
- **复杂度**: 低

### Task 3: 修改 FollowUp 服务

- **文件**: `wecom-desktop/backend/services/followup_service.py`
- **内容**: 添加文件日志配置
- **复杂度**: 低

### Task 4: 修改 response_detector.py

- **文件**: `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`
- **内容**: 添加文件日志配置
- **复杂度**: 低

### Task 5: 修改 scanner.py

- **文件**: `wecom-desktop/backend/servic../03-impl-and-arch/scanner.py`
- **内容**: 添加文件日志配置
- **复杂度**: 低

### Task 6: 确保 logs 目录创建

- **文件**: `wecom-desktop/backend/main.py`
- **内容**: 在 `ensure_directories()` 添加 logs 目录
- **复杂度**: 低

## 日志文件示例

### 文件名格式

```
backend.log              # 当天日志
backend.log.2026-01-20   # 历史日志
backend.log.2026-01-19
```

### 日志内容格式

```
2026-01-21 16:23:54 | INFO     | followup.scanner | [AN2FVB1706003302] Step 1: Launching WeCom...
2026-01-21 16:23:55 | INFO     | followup.scanner | [AN2FVB1706003302] Step 2: Switching to External Chats...
2026-01-21 16:23:56 | ERROR    | followup.scanner | [AN2FVB1706003302] Response scan error: ...
```

## 配置选项

| 配置项        | 默认值             | 说明                         |
| ------------- | ------------------ | ---------------------------- |
| `log_dir`     | `项目根目录/logs/` | 日志存储目录                 |
| `backupCount` | `0`                | 保留历史日志数量，0=永久保留 |
| `level`       | `INFO`             | 日志级别                     |
| `console`     | `True`             | 是否同时输出到控制台         |

## 注意事项

1. **编码问题**: Windows 需要指定 `encoding="utf-8"` 避免中文乱码
2. **权限问题**: 确保日志目录有写入权限
3. **磁盘空间**: 日志永久保留，建议定期手动清理过旧的日志文件
4. **日志轮转时机**: `when="midnight"` 在午夜轮转，跨天运行的任务日志会分散到两个文件

---

**创建时间**: 2026-01-21
**状态**: 待实现
