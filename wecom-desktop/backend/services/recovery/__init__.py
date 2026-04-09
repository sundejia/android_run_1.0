"""
Recovery 模块 - 无感恢复功能

提供程序异常退出、设备断连后的自动恢复能力。
"""

from .models import RecoveryTask, FollowupScanCheckpoint, TaskStatus
from .manager import RecoveryManager
from .shutdown import GracefulShutdownHandler

__all__ = [
    "RecoveryTask",
    "FollowupScanCheckpoint",
    "TaskStatus",
    "RecoveryManager",
    "GracefulShutdownHandler",
]
