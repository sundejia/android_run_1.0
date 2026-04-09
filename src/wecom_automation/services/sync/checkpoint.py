"""
断点管理器

管理同步断点，支持断点续传功能。
当同步过程中断时，可以从上次的位置继续同步。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from wecom_automation.core.interfaces import ICheckpointManager


class CheckpointManager(ICheckpointManager):
    """
    断点管理器

    职责:
    - 保存同步进度检查点
    - 加载检查点恢复同步
    - 清理检查点

    检查点文件格式:
    {
        "synced_customers": ["客户1", "客户2", ...],
        "stats": {
            "messages_added": 100,
            "messages_skipped": 10,
            ...
        },
        "kefu_name": "客服名称",
        "device_serial": "设备序列号",
        "timestamp": "2024-01-01T12:00:00",
        "version": 1
    }

    Usage:
        manager = CheckpointManager(Path("checkpoint.json"))

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

        # 清除断点
        manager.clear()
    """

    # 检查点文件版本
    VERSION = 1

    def __init__(self, checkpoint_file: Path, logger: logging.Logger | None = None):
        """
        初始化断点管理器

        Args:
            checkpoint_file: 检查点文件路径
            logger: 日志记录器
        """
        self._file = Path(checkpoint_file)
        self._logger = logger or logging.getLogger(__name__)

    def load(self) -> dict[str, Any] | None:
        """
        加载检查点

        Returns:
            检查点数据字典，不存在或失败返回None
        """
        if not self._file.exists():
            return None

        try:
            with open(self._file, encoding="utf-8") as f:
                data = json.load(f)

            self._logger.info(f"Loaded checkpoint: {len(data.get('synced_customers', []))} customers already synced")

            return data

        except json.JSONDecodeError as e:
            self._logger.warning(f"Failed to parse checkpoint file: {e}")
            return None
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
        data = {
            "synced_customers": synced_customers,
            "stats": stats,
            "kefu_name": kefu_name,
            "device_serial": device_serial,
            "timestamp": datetime.now().isoformat(),
            "version": self.VERSION,
        }

        try:
            # 确保目录存在
            self._file.parent.mkdir(parents=True, exist_ok=True)

            # 写入文件
            with open(self._file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            self._logger.debug(f"Checkpoint saved: {len(synced_customers)} customers")

            return True

        except Exception as e:
            self._logger.error(f"Failed to save checkpoint: {e}")
            return False

    def clear(self) -> bool:
        """
        清除检查点

        Returns:
            True如果清除成功或文件不存在
        """
        try:
            if self._file.exists():
                self._file.unlink()
                self._logger.info("Checkpoint cleared")
            return True
        except Exception as e:
            self._logger.error(f"Failed to clear checkpoint: {e}")
            return False

    def exists(self) -> bool:
        """
        检查点是否存在

        Returns:
            True如果检查点文件存在
        """
        return self._file.exists()

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
            摘要信息字典，包含:
            - synced_count: 已同步客户数
            - timestamp: 保存时间
            - kefu_name: 客服名称
            - device_serial: 设备序列号
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
        # 加载现有数据
        checkpoint = self.load() or {
            "synced_customers": [],
            "stats": {},
        }

        # 添加客户
        synced = checkpoint.get("synced_customers", [])
        if customer_name not in synced:
            synced.append(customer_name)

        # 合并统计数据
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
