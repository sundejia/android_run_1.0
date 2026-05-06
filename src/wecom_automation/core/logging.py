"""
统一日志模块 - 基于 loguru

提供全项目统一的日志配置，支持：
- 多设备日志隔离（每设备独立文件）
- 统一命名规范（{hostname}-{device}-{module}.log）
- 自动轮转与清理（默认 30 天）
- 多进程安全
"""

from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from loguru import logger as _loguru_logger

from wecom_automation.core.config import get_project_root

# 全局状态
_initialized = False
_device_sinks: dict[str, int] = {}  # device_serial -> sink_id
_hostname = "default"
_log_dir: Path | None = None


# 格式定义
# 使用自定义函数安全地访问 extra[module]，避免 KeyError
def _format_module(record):
    """安全获取模块名，避免 KeyError"""
    return record["extra"].get("module", record.get("name", "unknown"))


LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level:<8}</level> | "
    "<cyan>{extra[module]}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)

# 安全的日志格式（兼容没有 module 字段的日志）
SAFE_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level:<8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)

CONSOLE_FORMAT = "<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | <level>{message}</level>"


def _swipe_filter(record: dict) -> bool:
    """过滤 droidrun 的滑动日志"""
    message = record.get("message", "")
    if "Swiped from" in message and "milliseconds" in message:
        return False
    return True


class _LoguruInterceptHandler(logging.Handler):
    """Forward stdlib ``logging`` records into loguru.

    A non-trivial portion of the codebase (e.g. ``services/media_actions/*``,
    ``services/contact_share/*``) was written with ``logging.getLogger(__name__)``.
    Without this bridge those records are discarded silently because we tear
    down the stdlib root handlers in ``init_logging`` and never attach a sink
    to them.

    Mapping rules:
    - levels are translated by ``logging.getLevelName`` (loguru accepts the
      same names: DEBUG/INFO/WARNING/ERROR/CRITICAL).
    - the originating module name is preserved as ``extra[module]`` so the
      file format stays consistent across stdlib and loguru-native callers.
    - ``record.exc_info`` is preserved so tracebacks show up in the file sink.
    """

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - thin shim
        try:
            level = _loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame = logging.currentframe()
        depth = 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        bound = _loguru_logger.bind(module=record.name)
        bound.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _install_stdlib_intercept(level: str) -> None:
    """Reroute stdlib ``logging`` through loguru.

    Idempotent: subsequent calls keep the existing intercept handler in place
    and refresh its level threshold. Any pre-existing handlers on the root
    logger are replaced so we get a single source of truth for log output.
    """
    handler = _LoguruInterceptHandler()
    handler.setLevel(level)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for name in list(logging.Logger.manager.loggerDict.keys()):
        existing = logging.getLogger(name)
        existing.handlers = []
        existing.propagate = True


def _get_hostname() -> str:
    """从设置中获取主机名"""
    try:
        # 延迟导入避免循环依赖
        import sys

        from wecom_automation.core.config import get_default_db_path

        backend_path = get_project_root() / "wecom-desktop" / "backend"
        if str(backend_path) not in sys.path:
            sys.path.insert(0, str(backend_path))

        from services.settings.service import SettingsService

        db_path = str(get_default_db_path())
        settings_service = SettingsService(db_path)
        hostname = settings_service.get("general", "hostname", "default")

        # 确保主机名是有效的文件名
        if not hostname or not hostname.strip():
            return "default"

        # 移除可能造成文件名问题的字符
        hostname = hostname.strip().replace("/", "-").replace("\\", "-").replace(" ", "_")
        return hostname
    except Exception:
        return "default"


def init_logging(
    hostname: str | None = None,
    level: str = "INFO",
    log_dir: Path | None = None,
    console: bool = True,
    serial: str | None = None,  # 新增：设备序列号，用于多进程日志隔离
) -> None:
    """
    初始化日志配置（支持主进程和子进程）

    Args:
        hostname: 主机名标识，None 则从设置读取
        level: 日志级别（DEBUG/INFO/WARNING/ERROR）
        log_dir: 日志目录，None 则使用 {project_root}/logs/
        console: 是否输出到控制台
        serial: 设备序列号（可选），用于子进程隔离
            - 如果提供 serial（子进程）：只写设备专属日志 {hostname}-{serial}.log
            - 如果不提供 serial（主进程）：不落盘，仅控制台（及 add_device_sink 另行挂载的文件）

    多进程日志隔离策略:
        - 主进程: 无文件 sink（避免 {hostname}-global.log）；子进程写 {hostname}-{serial}.log
    """
    global _initialized, _hostname, _log_dir

    if hostname is None:
        hostname = _get_hostname()

    _hostname = hostname
    _log_dir = log_dir or get_project_root() / "logs"
    _log_dir.mkdir(parents=True, exist_ok=True)

    # 移除默认 handler
    _loguru_logger.remove()

    # 控制台 handler（所有进程都输出到控制台）
    if console:
        _loguru_logger.add(
            sys.stderr,
            format=CONSOLE_FORMAT,
            level=level,
            colorize=True,
            filter=_swipe_filter,
        )

    # 转发 stdlib logging 到 loguru（让 services/media_actions/* 等使用
    # logging.getLogger(__name__) 的旧模块也能写入设备日志，否则它们的
    # warning/error 在生产环境完全不可见，调试名片分享之类的链路时无从下手）
    _install_stdlib_intercept(level)

    # 日志文件写入策略：根据是否提供 serial 决定
    if serial:
        # 子进程：只写设备专属日志，避免多进程争用同一文件
        device_log_file = _log_dir / f"{hostname}-{serial}.log"
        _loguru_logger.add(
            device_log_file,
            format=SAFE_LOG_FORMAT,
            rotation="00:00",  # 午夜轮转
            retention="30 days",  # 保留 30 天
            encoding="utf-8",
            enqueue=True,  # 进程内安全
            level=level,
            colorize=False,
        )
        print(f"[logging] Subprocess mode: logging to {device_log_file}")
    else:
        print(
            f"[logging] Main process: console only; per-device files are "
            f"logs/{hostname}-<serial>.log when subprocesses run"
        )

    _initialized = True


def add_device_sink(
    serial: str,
    hostname: str | None = None,
    log_dir: Path | None = None,
    level: str = "INFO",
) -> int:
    """
    为指定设备添加独立日志文件 sink

    Args:
        serial: 设备序列号
        hostname: 主机名，None 则使用全局配置
        log_dir: 日志目录，None 则使用全局配置
        level: 日志级别

    Returns:
        sink ID（用于后续 remove）
    """
    global _device_sinks

    if hostname is None:
        hostname = _hostname
    if log_dir is None:
        log_dir = _log_dir or get_project_root() / "logs"

    log_dir.mkdir(parents=True, exist_ok=True)

    # 如果已存在，先移除旧的
    if serial in _device_sinks:
        _loguru_logger.remove(_device_sinks[serial])

    # 添加设备专属 sink
    # 使用 SAFE_LOG_FORMAT 以兼容 stdlib logging
    sink_id = _loguru_logger.add(
        log_dir / f"{hostname}-{serial}.log",
        format=SAFE_LOG_FORMAT,
        rotation="00:00",
        retention="30 days",
        encoding="utf-8",
        enqueue=True,
        filter=lambda r, s=serial: r["extra"].get("device") == s,
        level=level,
        colorize=False,
    )

    _device_sinks[serial] = sink_id
    return sink_id


def remove_device_sink(serial: str) -> None:
    """移除设备日志 sink"""
    if serial in _device_sinks:
        _loguru_logger.remove(_device_sinks[serial])
        del _device_sinks[serial]


def get_logger(name: str = "wecom_automation", device: str | None = None):
    """
    获取带模块名和可选设备上下文的 logger

    Args:
        name: 模块名（用于日志中的 module 字段）
        device: 设备序列号（可选），指定后日志路由到该设备的文件

    Returns:
        Loguru logger 实例（支持 .info(), .debug(), .error() 等方法）

    Example:
        logger = get_logger("sync", device="R58M35XXXX")
        logger.info("开始同步")  # 写入 logs/host01-R58M35XXXX.log
    """
    if not _initialized:
        init_logging()

    bound = _loguru_logger.bind(module=name)
    if device:
        bound = bound.bind(device=device)
    return bound


def setup_logger(
    name: str = "wecom_automation",
    level: int = logging.INFO,
    log_file: str | None = None,
    debug: bool = False,
):
    """
    向后兼容的 logger 设置函数

    Args:
        name: Logger 名称
        level: 日志级别（logging.INFO 等）
        log_file: 日志文件路径（已弃用，使用统一配置）
        debug: 调试模式

    Returns:
        Loguru logger 实例
    """
    if not _initialized:
        # 转换 logging level 到字符串
        level_str = "DEBUG" if debug else logging.getLevelName(level)
        init_logging(level=level_str)

    # log_file 参数已弃用，使用统一的设备 sink 机制
    if log_file:
        import warnings

        warnings.warn(
            "log_file parameter is deprecated, use add_device_sink() instead",
            DeprecationWarning,
            stacklevel=2,
        )

    return get_logger(name)


@contextmanager
def log_operation(
    logger_obj,  # Loguru logger 或 stdlib logger
    operation_name: str,
    level: int = logging.INFO,
    **context: Any,
):
    """
    上下文管理器：记录操作开始/结束及耗时

    Usage:
        with log_operation(logger, "extract_users", user_count=10):
            # do work
            pass

    Args:
        logger_obj: Logger 实例
        operation_name: 操作名称
        level: 日志级别
        **context: 附加上下文信息

    Yields:
        None
    """
    start_time = time.perf_counter()

    # 构建上下文字符串
    ctx_str = " | ".join(f"{k}={v}" for k, v in context.items()) if context else ""
    start_msg = f"Starting: {operation_name}"
    if ctx_str:
        start_msg += f" [{ctx_str}]"

    # 转换 logging level 到 loguru level
    level_name = logging.getLevelName(level)
    logger_obj.log(level_name, start_msg)

    try:
        yield
        duration = time.perf_counter() - start_time
        complete_msg = f"Completed: {operation_name} | duration_ms={duration * 1000:.1f}"
        if ctx_str:
            complete_msg += f" [{ctx_str}]"
        logger_obj.log(level_name, complete_msg)
    except Exception as e:
        duration = time.perf_counter() - start_time

        # 检查是否为 SkipUserException（用 INFO 而非 ERROR）
        from wecom_automation.core.exceptions import SkipUserException

        if isinstance(e, SkipUserException):
            skip_msg = f"Skipped: {operation_name} | duration_ms={duration * 1000:.1f} | reason={str(e)}"
            if ctx_str:
                skip_msg += f" [{ctx_str}]"
            logger_obj.log("INFO", skip_msg)
        else:
            error_msg = f"Failed: {operation_name} | duration_ms={duration * 1000:.1f} | error={str(e)}"
            if ctx_str:
                error_msg += f" [{ctx_str}]"
            logger_obj.log("ERROR", error_msg)
        raise


# 向后兼容：导出这些符号供外部使用
# 但底层已替换为 loguru
__all__ = [
    "init_logging",
    "add_device_sink",
    "remove_device_sink",
    "get_logger",
    "setup_logger",
    "log_operation",
    "install_stdlib_intercept",
]


def install_stdlib_intercept(level: str = "INFO") -> None:
    """Public wrapper for the internal stdlib→loguru bridge installer.

    Useful for ad-hoc scripts and tests that initialize loguru manually but
    still want third-party / legacy modules using ``logging.getLogger`` to
    funnel into the same sinks.
    """
    _install_stdlib_intercept(level)
