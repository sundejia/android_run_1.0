"""
Recovery-based Checkpoint Manager

使用 RecoveryManager 替代 JSON 文件的断点管理器。
支持无感恢复功能，与新开发的 RecoveryManager 集成。
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from typing import Any

# Add backend path for imports
from wecom_automation.core.config import get_project_root
from wecom_automation.core.interfaces import ICheckpointManager

BACKEND_PATH = get_project_root() / "wecom-desktop" / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))


class RecoveryCheckpointManager(ICheckpointManager):
    """
    基于 RecoveryManager 的断点管理器

    使用 SQLite 数据库存储同步进度，替代 JSON 文件方案。
    支持无感恢复功能。

    Usage:
        manager = RecoveryCheckpointManager(db_path, device_serial, logger)

        # 检查是否有断点
        if manager.exists():
            data = manager.load()
            synced = data["synced_customers"]

        # 保存断点
        manager.save(
            synced_customers=["客户1", "客户2"],
            stats={"messages_added": 100},
            kefu_name="张三",
            device_serial="ABC123"
        )
    """

    TASK_TYPE = "full_sync"
    VERSION = 1

    def __init__(self, db_path: str, device_serial: str, logger: logging.Logger | None = None):
        """
        初始化断点管理器

        Args:
            db_path: 数据库文件路径
            device_serial: 设备序列号
            logger: 日志记录器
        """
        self._db_path = db_path
        self._device_serial = device_serial
        self._logger = logger or logging.getLogger(__name__)
        self._task_id = f"full_sync_{device_serial}"

        # Lazy import RecoveryManager to avoid circular imports
        self._recovery_manager = None

    def _get_recovery_manager(self):
        """Lazy load RecoveryManager"""
        if self._recovery_manager is None:
            try:
                from services.recovery.manager import get_recovery_manager

                self._recovery_manager = get_recovery_manager(self._db_path)
            except ImportError as e:
                self._logger.warning(f"RecoveryManager not available: {e}")
                return None
        return self._recovery_manager

    def load(self) -> dict[str, Any] | None:
        """
        加载检查点

        Returns:
            检查点数据字典，不存在或失败返回None
        """
        manager = self._get_recovery_manager()
        if not manager:
            return None

        try:
            task = manager.get_task(self._task_id)
            if not task:
                return None

            # Only return checkpoint for non-completed tasks
            from services.recovery.models import TaskStatus

            if task.status == TaskStatus.COMPLETED:
                self._logger.debug("Task completed, no checkpoint to restore")
                return None
            if task.status == TaskStatus.FAILED:
                self._logger.debug("Task failed, no checkpoint to restore")
                return None

            if not task.checkpoint_data:
                return None

            # checkpoint_data is already a dict from RecoveryTask.from_row()
            checkpoint = task.checkpoint_data

            self._logger.info(
                f"Loaded checkpoint: {len(checkpoint.get('synced_customers', []))} customers already synced"
            )

            return checkpoint

        except Exception as e:
            self._logger.warning(f"Failed to load checkpoint: {e}")
            return None

    def save(
        self,
        synced_customers: list[str],
        stats: dict[str, int],
        kefu_name: str,
        device_serial: str,
    ) -> bool:
        """
        保存检查点

        Args:
            synced_customers: 已同步的客户名称列表
            stats: 统计数据 (messages_added, messages_skipped等)
            kefu_name: 客服名称
            device_serial: 设备序列号

        Returns:
            True如果保存成功
        """
        manager = self._get_recovery_manager()
        if not manager:
            self._logger.warning("RecoveryManager not available, skipping checkpoint save")
            return False

        checkpoint_data = {
            "synced_customers": synced_customers,
            "stats": stats,
            "kefu_name": kefu_name,
            "device_serial": device_serial,
            "timestamp": datetime.now().isoformat(),
            "version": self.VERSION,
        }

        try:
            # Get or create task
            task = manager.get_task(self._task_id)
            if not task:
                manager.create_task(
                    task_type=self.TASK_TYPE,
                    device_serial=device_serial,
                    task_id=self._task_id,
                    total_items=stats.get("total_customers", 0),
                )

            # Calculate progress percent
            total = stats.get("total_customers", 0)
            progress_percent = int(len(synced_customers) * 100 / total) if total > 0 else 0

            # Update checkpoint
            manager.update_checkpoint(
                task_id=self._task_id, checkpoint=checkpoint_data, progress_percent=progress_percent
            )

            self._logger.debug(f"Checkpoint saved: {len(synced_customers)} customers")
            return True

        except Exception as e:
            self._logger.error(f"Failed to save checkpoint: {e}")
            return False

    def clear(self) -> bool:
        """
        清除检查点（标记任务为已完成）

        Returns:
            True如果清除成功
        """
        manager = self._get_recovery_manager()
        if not manager:
            return True

        try:
            task = manager.get_task(self._task_id)
            if task:
                manager.complete_task(self._task_id)
                self._logger.info("Checkpoint cleared (task completed)")
            return True
        except Exception as e:
            self._logger.error(f"Failed to clear checkpoint: {e}")
            return False

    def exists(self) -> bool:
        """
        检查点是否存在（有未完成的恢复任务）

        Returns:
            True如果有检查点存在
        """
        manager = self._get_recovery_manager()
        if not manager:
            return False

        try:
            task = manager.get_task(self._task_id)
            if not task:
                return False

            from services.recovery.models import TaskStatus

            # Has checkpoint if task is running/paused/pending_recovery and has checkpoint data
            return (
                task.status in [TaskStatus.RUNNING, TaskStatus.PAUSED, TaskStatus.PENDING_RECOVERY]
                and task.checkpoint_data is not None
            )
        except Exception as e:
            self._logger.warning(f"Failed to check checkpoint: {e}")
            return False

    def get_synced_customers(self) -> list[str]:
        """
        获取已同步的客户列表

        Returns:
            已同步客户名称列表，无检查点返回空列表
        """
        checkpoint = self.load()
        if checkpoint:
            return checkpoint.get("synced_customers", [])
        return []

    def get_stats(self) -> dict[str, int]:
        """
        获取统计数据

        Returns:
            统计数据字典，无检查点返回空字典
        """
        checkpoint = self.load()
        if checkpoint:
            return checkpoint.get("stats", {})
        return {}

    def get_info(self) -> dict[str, Any] | None:
        """
        获取检查点摘要信息

        Returns:
            摘要信息字典
        """
        checkpoint = self.load()
        if not checkpoint:
            return None

        return {
            "synced_count": len(checkpoint.get("synced_customers", [])),
            "timestamp": checkpoint.get("timestamp"),
            "kefu_name": checkpoint.get("kefu_name"),
            "device_serial": checkpoint.get("device_serial"),
            "stats": checkpoint.get("stats", {}),
        }

    def is_customer_synced(self, customer_name: str) -> bool:
        """
        检查客户是否已同步

        Args:
            customer_name: 客户名称

        Returns:
            True如果客户已在检查点中
        """
        synced = self.get_synced_customers()
        return customer_name in synced

    def add_synced_customer(
        self,
        customer_name: str,
        stats: dict[str, int],
        kefu_name: str,
        device_serial: str,
    ) -> bool:
        """
        添加一个已同步的客户到检查点

        Args:
            customer_name: 客户名称
            stats: 统计数据
            kefu_name: 客服名称
            device_serial: 设备序列号

        Returns:
            True如果保存成功
        """
        checkpoint = self.load() or {
            "synced_customers": [],
            "stats": {},
        }

        synced = checkpoint.get("synced_customers", [])
        if customer_name not in synced:
            synced.append(customer_name)

        existing_stats = checkpoint.get("stats", {})
        for key, value in stats.items():
            if key in existing_stats:
                existing_stats[key] = existing_stats[key] + value
            else:
                existing_stats[key] = value

        return self.save(
            synced_customers=synced,
            stats=existing_stats,
            kefu_name=kefu_name,
            device_serial=device_serial,
        )

    def discard(self) -> bool:
        """
        丢弃检查点（放弃恢复）

        Returns:
            True如果丢弃成功
        """
        manager = self._get_recovery_manager()
        if not manager:
            return True

        try:
            task = manager.get_task(self._task_id)
            if task:
                manager.discard_task(self._task_id)
                self._logger.info("Checkpoint discarded")
            return True
        except Exception as e:
            self._logger.error(f"Failed to discard checkpoint: {e}")
            return False
