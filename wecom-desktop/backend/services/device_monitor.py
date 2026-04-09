"""
Device Monitor - 设备连接状态监控

监控 ADB 设备的连接状态，当设备断开或重新连接时触发事件。
用于支持断连后的无感恢复功能。
"""

import asyncio
import subprocess
import logging
from typing import Callable, Set, List, Optional, Awaitable
from datetime import datetime
from wecom_automation.core.performance import runtime_metrics

from services.recovery.manager import get_recovery_manager

logger = logging.getLogger("device_monitor")


class DeviceMonitor:
    """
    设备连接状态监控器

    功能:
    - 定期检查 ADB 设备连接状态
    - 检测新连接的设备
    - 检测断开的设备
    - 当设备断开时，标记相关任务为待恢复
    - 当设备重连时，通知前端有可恢复任务
    """

    def __init__(
        self,
        check_interval: float = 2.0,
        on_connect: Optional[Callable[[str], Awaitable[None]]] = None,
        on_disconnect: Optional[Callable[[str], Awaitable[None]]] = None,
    ):
        """
        初始化设备监控器

        Args:
            check_interval: 检查间隔（秒）
            on_connect: 设备连接回调
            on_disconnect: 设备断开回调
        """
        self._check_interval = check_interval
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect

        self._known_devices: Set[str] = set()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._callbacks: List[Callable[[str, str], Awaitable[None]]] = []

    def on_device_change(self, callback: Callable[[str, str], Awaitable[None]]):
        """
        注册设备变化回调

        Args:
            callback: 回调函数，参数为 (event_type, device_serial)
                      event_type: 'connected' 或 'disconnected'
        """
        self._callbacks.append(callback)

    def get_known_devices(self) -> Set[str]:
        """获取当前已知的设备列表"""
        return self._known_devices.copy()

    async def start(self):
        """开始监控"""
        if self._running:
            logger.warning("Device monitor is already running")
            return

        self._running = True

        # 初始化已知设备列表
        self._known_devices = await self._get_connected_devices()
        logger.info(f"Device monitor started. Initial devices: {self._known_devices}")

        # 启动监控任务
        self._task = asyncio.create_task(self._monitor_loop())

    async def stop(self):
        """停止监控"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Device monitor stopped")

    async def _monitor_loop(self):
        """监控循环"""
        idle_cycles = 0
        while self._running:
            try:
                effective_interval = self._get_effective_interval(idle_cycles)
                runtime_metrics.record_poll("backend.device_monitor", effective_interval * 1000)
                current_devices = await self._get_connected_devices()

                # 检测新连接的设备
                new_devices = current_devices - self._known_devices
                # 检测断开的设备
                disconnected = self._known_devices - current_devices

                # 处理新连接的设备
                for serial in new_devices:
                    await self._handle_device_connected(serial)

                # 处理断开的设备
                for serial in disconnected:
                    await self._handle_device_disconnected(serial)

                self._known_devices = current_devices
                if new_devices or disconnected:
                    idle_cycles = 0
                else:
                    idle_cycles = min(idle_cycles + 1, 6)

            except Exception as e:
                logger.error(f"Error in device monitor loop: {e}")
                idle_cycles = min(idle_cycles + 1, 6)

            await asyncio.sleep(self._get_effective_interval(idle_cycles))

    def _get_effective_interval(self, idle_cycles: int) -> float:
        """Increase poll interval on quiet/low-spec runs to reduce ADB churn."""
        interval = self._check_interval
        try:
            from services.settings import get_settings_service

            settings = get_settings_service()
            if settings.is_low_spec_mode():
                interval = max(interval, 5.0)
        except Exception:
            pass
        return min(interval * (1 + idle_cycles), 30.0)

    async def _get_connected_devices(self) -> Set[str]:
        """获取当前连接的设备列表"""
        try:
            # 在线程池中运行 adb 命令
            result = await asyncio.to_thread(
                subprocess.run, ["adb", "devices"], capture_output=True, text=True, timeout=5
            )

            devices = set()
            for line in result.stdout.strip().split("\n")[1:]:
                if "\tdevice" in line:
                    serial = line.split("\t")[0]
                    devices.add(serial)

            return devices

        except subprocess.TimeoutExpired:
            logger.warning("ADB command timed out")
            return self._known_devices  # 超时时返回上次的状态
        except FileNotFoundError:
            logger.error("ADB not found in PATH")
            return set()
        except Exception as e:
            logger.error(f"Error getting connected devices: {e}")
            return self._known_devices

    async def _handle_device_connected(self, serial: str):
        """处理设备连接事件"""
        logger.info(f"Device connected: {serial}")

        try:
            # 更新数据库中的连接状态
            recovery_manager = get_recovery_manager()
            recovery_manager.update_device_connection(serial, is_connected=True)

            # 检查该设备是否有待恢复任务
            tasks = recovery_manager.get_tasks_by_device(serial)
            resumable_tasks = [t for t in tasks if t.get("status") in ["running", "paused", "pending_recovery"]]

            if resumable_tasks:
                logger.info(f"Device {serial} has {len(resumable_tasks)} resumable tasks")

            # 广播到 WebSocket 客户端
            try:
                from routers.recovery import broadcast_recovery_event

                await broadcast_recovery_event(
                    "device_connected",
                    {
                        "device_serial": serial,
                        "has_resumable_tasks": len(resumable_tasks) > 0,
                        "resumable_tasks": resumable_tasks,
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to broadcast device connect event: {e}")

            # 调用回调
            if self._on_connect:
                await self._on_connect(serial)

            for callback in self._callbacks:
                try:
                    await callback("connected", serial)
                except Exception as e:
                    logger.error(f"Error in device connect callback: {e}")

        except Exception as e:
            logger.error(f"Error handling device connect: {e}")

    async def _handle_device_disconnected(self, serial: str):
        """处理设备断开事件"""
        logger.info(f"Device disconnected: {serial}")

        try:
            recovery_manager = get_recovery_manager()

            # 获取该设备正在运行的任务
            tasks = recovery_manager.get_tasks_by_device(serial)
            running_tasks = [t for t in tasks if t.get("status") == "running"]

            # 标记运行中的任务为待恢复
            marked_tasks = []
            for task in running_tasks:
                task_id = task.get("task_id")
                recovery_manager.mark_pending_recovery(task_id)
                marked_tasks.append(task)
                logger.info(f"Marked task {task_id} as pending recovery due to device disconnect")

            # 更新数据库中的连接状态，记录待恢复的任务
            pending_task_id = running_tasks[0]["task_id"] if running_tasks else None
            recovery_manager.update_device_connection(serial, is_connected=False, pending_task_id=pending_task_id)

            # 广播到 WebSocket 客户端
            try:
                from routers.recovery import broadcast_recovery_event

                await broadcast_recovery_event(
                    "device_disconnected",
                    {
                        "device_serial": serial,
                        "marked_tasks": marked_tasks,
                        "tasks_marked_count": len(marked_tasks),
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to broadcast device disconnect event: {e}")

            # 调用回调
            if self._on_disconnect:
                await self._on_disconnect(serial)

            for callback in self._callbacks:
                try:
                    await callback("disconnected", serial)
                except Exception as e:
                    logger.error(f"Error in device disconnect callback: {e}")

        except Exception as e:
            logger.error(f"Error handling device disconnect: {e}")


# 全局监控器实例
_device_monitor: Optional[DeviceMonitor] = None


def get_device_monitor() -> DeviceMonitor:
    """获取设备监控器单例"""
    global _device_monitor
    if _device_monitor is None:
        _device_monitor = DeviceMonitor()
    return _device_monitor


async def start_device_monitor():
    """启动设备监控器"""
    monitor = get_device_monitor()
    await monitor.start()


async def stop_device_monitor():
    """停止设备监控器"""
    global _device_monitor
    if _device_monitor:
        await _device_monitor.stop()
