"""
Recovery 数据模型

定义恢复相关的数据结构。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
import json


class TaskStatus(str, Enum):
    """任务状态"""

    RUNNING = "running"
    PAUSED = "paused"
    FAILED = "failed"
    COMPLETED = "completed"
    PENDING_RECOVERY = "pending_recovery"


class TaskType(str, Enum):
    """任务类型"""

    FOLLOWUP_SCAN = "followup_scan"
    FULL_SYNC = "full_sync"
    PHASE2_SCAN = "phase2_scan"


@dataclass
class FollowupScanCheckpoint:
    """跟进扫描检查点"""

    scan_start_time: datetime
    current_user_index: int
    total_users: int
    processed_users: List[str]
    pending_users: List[str]
    current_phase: str  # 'phase1', 'phase2'
    device_serial: str

    # 可选的额外状态
    last_processed_user: Optional[str] = None
    error_users: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "scan_start_time": self.scan_start_time.isoformat(),
            "current_user_index": self.current_user_index,
            "total_users": self.total_users,
            "processed_users": self.processed_users,
            "pending_users": self.pending_users,
            "current_phase": self.current_phase,
            "device_serial": self.device_serial,
            "last_processed_user": self.last_processed_user,
            "error_users": self.error_users,
        }

    def to_json(self) -> str:
        """序列化为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "FollowupScanCheckpoint":
        """从字典反序列化"""
        return cls(
            scan_start_time=datetime.fromisoformat(data["scan_start_time"]),
            current_user_index=data["current_user_index"],
            total_users=data["total_users"],
            processed_users=data.get("processed_users", []),
            pending_users=data.get("pending_users", []),
            current_phase=data["current_phase"],
            device_serial=data["device_serial"],
            last_processed_user=data.get("last_processed_user"),
            error_users=data.get("error_users", []),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "FollowupScanCheckpoint":
        """从 JSON 字符串反序列化"""
        return cls.from_dict(json.loads(json_str))


@dataclass
class RecoveryTask:
    """恢复任务"""

    task_id: str
    task_type: str
    status: TaskStatus
    device_serial: str

    # 进度信息
    progress_percent: int = 0

    # 检查点数据
    checkpoint_data: Optional[Dict[str, Any]] = None

    # 队列状态
    pending_items: List[str] = field(default_factory=list)
    completed_items: List[str] = field(default_factory=list)
    failed_items: List[str] = field(default_factory=list)

    # 时间戳
    started_at: Optional[datetime] = None
    last_checkpoint_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # 错误信息
    last_error: Optional[str] = None
    retry_count: int = 0

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status.value if isinstance(self.status, TaskStatus) else self.status,
            "device_serial": self.device_serial,
            "progress_percent": self.progress_percent,
            "checkpoint_data": self.checkpoint_data,
            "pending_items": self.pending_items,
            "completed_items": self.completed_items,
            "failed_items": self.failed_items,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_checkpoint_at": self.last_checkpoint_at.isoformat() if self.last_checkpoint_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "last_error": self.last_error,
            "retry_count": self.retry_count,
        }

    @classmethod
    def from_row(cls, row) -> "RecoveryTask":
        """从数据库行创建"""
        checkpoint_data = None
        if row["checkpoint_data"]:
            try:
                checkpoint_data = json.loads(row["checkpoint_data"])
            except:
                pass

        pending_items = []
        if row["pending_items"]:
            try:
                pending_items = json.loads(row["pending_items"])
            except:
                pass

        completed_items = []
        if row["completed_items"]:
            try:
                completed_items = json.loads(row["completed_items"])
            except:
                pass

        failed_items = []
        if row["failed_items"]:
            try:
                failed_items = json.loads(row["failed_items"])
            except:
                pass

        def parse_datetime(val):
            if not val:
                return None
            if isinstance(val, datetime):
                return val
            try:
                return datetime.fromisoformat(val.replace("Z", "+00:00"))
            except:
                return None

        return cls(
            task_id=row["task_id"],
            task_type=row["task_type"],
            status=TaskStatus(row["status"]),
            device_serial=row["device_serial"] or "",
            progress_percent=row["progress_percent"] or 0,
            checkpoint_data=checkpoint_data,
            pending_items=pending_items,
            completed_items=completed_items,
            failed_items=failed_items,
            started_at=parse_datetime(row["started_at"]),
            last_checkpoint_at=parse_datetime(row["last_checkpoint_at"]),
            completed_at=parse_datetime(row["completed_at"]),
            last_error=row["last_error"],
            retry_count=row["retry_count"] or 0,
        )


@dataclass
class DeviceConnectionState:
    """设备连接状态"""

    device_serial: str
    is_connected: bool = False
    last_connected_at: Optional[datetime] = None
    last_disconnected_at: Optional[datetime] = None
    pending_task_id: Optional[str] = None
    auto_reconnect: bool = True
    reconnect_attempts: int = 0
    max_reconnect_attempts: int = 5
