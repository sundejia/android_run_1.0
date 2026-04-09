"""
Graceful Shutdown Handler - 优雅关闭处理器

捕获系统信号，在程序退出前保存状态。
"""

import asyncio
import signal
import logging
import sys
from typing import Optional, List, Callable, Awaitable

from .manager import RecoveryManager, get_recovery_manager

logger = logging.getLogger("recovery.shutdown")


class GracefulShutdownHandler:
    """优雅关闭处理器"""

    def __init__(self, recovery_manager: Optional[RecoveryManager] = None, logger: Optional[logging.Logger] = None):
        self._recovery = recovery_manager or get_recovery_manager()
        self._logger = logger or logging.getLogger("recovery.shutdown")
        self._shutdown_callbacks: List[Callable[[], Awaitable[None]]] = []
        self._is_shutting_down = False
        self._registered = False

    def register_signals(self) -> None:
        """注册系统信号处理"""
        if self._registered:
            return

        # Windows 兼容性处理
        if sys.platform == "win32":
            # Windows 上使用 signal.signal
            signal.signal(signal.SIGINT, self._sync_signal_handler)
            signal.signal(signal.SIGTERM, self._sync_signal_handler)
        else:
            # Unix 系统可以使用 asyncio 的信号处理
            try:
                loop = asyncio.get_running_loop()
                for sig in (signal.SIGTERM, signal.SIGINT):
                    loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(self._handle_shutdown(s)))
            except RuntimeError:
                # 没有运行中的事件循环，使用同步方式
                signal.signal(signal.SIGINT, self._sync_signal_handler)
                signal.signal(signal.SIGTERM, self._sync_signal_handler)

        self._registered = True
        self._logger.info("Graceful shutdown handler registered")

    def _sync_signal_handler(self, signum, frame):
        """同步信号处理器（用于 Windows）"""
        self._logger.info(f"Received signal {signum}, initiating graceful shutdown...")

        # 尝试在事件循环中运行异步关闭
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._handle_shutdown(signum))
            else:
                loop.run_until_complete(self._handle_shutdown(signum))
        except RuntimeError:
            # 没有事件循环，直接同步保存
            self._sync_save_state()
            sys.exit(0)

    def _sync_save_state(self):
        """同步保存状态"""
        self._logger.info("Saving state synchronously...")

        # 获取所有运行中的任务并标记为暂停
        pending_tasks = self._recovery.get_pending_tasks()
        for task in pending_tasks:
            if task.status.value == "running":
                self._recovery.mark_paused(task.task_id)
                self._logger.info(f"Task {task.task_id} marked as paused")

        self._logger.info("State saved successfully")

    async def _handle_shutdown(self, signum) -> None:
        """异步处理关闭信号"""
        if self._is_shutting_down:
            self._logger.warning("Shutdown already in progress, ignoring signal")
            return

        self._is_shutting_down = True
        self._logger.info(f"Received signal {signum}, initiating graceful shutdown...")

        try:
            # 1. 执行所有注册的回调
            for callback in self._shutdown_callbacks:
                try:
                    self._logger.debug(f"Executing shutdown callback: {callback.__name__}")
                    await callback()
                except Exception as e:
                    self._logger.error(f"Error in shutdown callback: {e}")

            # 2. 保存所有运行中任务的状态
            await self._save_all_running_tasks()

            self._logger.info("Graceful shutdown completed")

        except Exception as e:
            self._logger.error(f"Error during graceful shutdown: {e}")

        finally:
            # 退出程序
            sys.exit(0)

    async def _save_all_running_tasks(self) -> None:
        """保存所有运行中任务的状态"""
        pending_tasks = self._recovery.get_pending_tasks()

        for task in pending_tasks:
            if task.status.value == "running":
                self._recovery.mark_paused(task.task_id)
                self._logger.info(f"Task {task.task_id} marked as paused for recovery")

    def register_callback(self, callback: Callable[[], Awaitable[None]]) -> None:
        """
        注册关闭时的回调函数

        Args:
            callback: 异步回调函数，在关闭前执行
        """
        self._shutdown_callbacks.append(callback)
        self._logger.debug(f"Registered shutdown callback: {callback.__name__}")

    def unregister_callback(self, callback: Callable[[], Awaitable[None]]) -> None:
        """取消注册回调函数"""
        if callback in self._shutdown_callbacks:
            self._shutdown_callbacks.remove(callback)


# 全局处理器
_shutdown_handler: Optional[GracefulShutdownHandler] = None


def get_shutdown_handler() -> GracefulShutdownHandler:
    """获取全局关闭处理器"""
    global _shutdown_handler

    if _shutdown_handler is None:
        _shutdown_handler = GracefulShutdownHandler()

    return _shutdown_handler


def init_graceful_shutdown(recovery_manager: Optional[RecoveryManager] = None) -> GracefulShutdownHandler:
    """
    初始化优雅关闭处理

    应在程序启动时调用。

    Args:
        recovery_manager: 可选的 RecoveryManager 实例

    Returns:
        GracefulShutdownHandler 实例
    """
    global _shutdown_handler

    _shutdown_handler = GracefulShutdownHandler(recovery_manager)
    _shutdown_handler.register_signals()

    return _shutdown_handler
