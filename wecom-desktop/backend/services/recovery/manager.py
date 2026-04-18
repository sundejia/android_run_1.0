"""
Recovery Manager - 无感恢复管理器

负责任务状态的持久化、检查点管理和恢复逻辑。
"""

import sqlite3
import logging
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager

from .models import RecoveryTask, TaskStatus, TaskType

# Use centralized database path config
from wecom_automation.core.config import get_default_db_path

logger = logging.getLogger("recovery.manager")


class RecoveryManager:
    """无感恢复管理器"""

    def __init__(self, db_path: str, logger: Optional[logging.Logger] = None):
        self._db_path = db_path
        self._logger = logger or logging.getLogger("recovery.manager")
        self._ensure_tables()

    @contextmanager
    def _connection(self):
        """获取数据库连接上下文（带 busy_timeout/WAL 容错）"""
        from services.conversation_storage import open_shared_sqlite

        conn = open_shared_sqlite(str(self._db_path), row_factory=True)
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_tables(self) -> None:
        """确保必要的表存在"""
        with self._connection() as conn:
            cursor = conn.cursor()

            # 创建 recovery_state 表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recovery_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    
                    -- 任务标识
                    task_type TEXT NOT NULL,
                    task_id TEXT UNIQUE NOT NULL,
                    
                    -- 状态信息
                    status TEXT NOT NULL DEFAULT 'running',
                    progress_percent INTEGER DEFAULT 0,
                    
                    -- 检查点数据 (JSON)
                    checkpoint_data TEXT,
                    
                    -- UI状态数据 (JSON) - 用于恢复界面状态
                    ui_state TEXT,
                    
                    -- 队列数据 (JSON)
                    pending_items TEXT,
                    completed_items TEXT,
                    failed_items TEXT,
                    
                    -- 设备信息
                    device_serial TEXT,
                    
                    -- 时间戳
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_checkpoint_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    
                    -- 错误信息
                    last_error TEXT,
                    retry_count INTEGER DEFAULT 0,
                    
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 尝试添加 ui_state 列（如果表已存在但没有该列）
            try:
                cursor.execute("ALTER TABLE recovery_state ADD COLUMN ui_state TEXT")
            except:
                pass  # 列已存在

            # 创建索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_recovery_state_status 
                ON recovery_state(status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_recovery_state_task_type 
                ON recovery_state(task_type)
            """)

            # 创建设备连接状态表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS device_connection_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_serial TEXT UNIQUE NOT NULL,
                    
                    is_connected INTEGER DEFAULT 0,
                    last_connected_at TIMESTAMP,
                    last_disconnected_at TIMESTAMP,
                    
                    pending_task_id TEXT,
                    
                    auto_reconnect INTEGER DEFAULT 1,
                    reconnect_attempts INTEGER DEFAULT 0,
                    max_reconnect_attempts INTEGER DEFAULT 5,
                    
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()
            self._logger.info("Recovery tables initialized")

    # =========================================================================
    # 任务状态管理
    # =========================================================================

    def create_task(
        self,
        task_type: str,
        device_serial: str,
        initial_checkpoint: Optional[Dict] = None,
        task_id: Optional[str] = None,
        total_items: int = 0,
    ) -> str:
        """
        创建新的恢复任务

        Args:
            task_type: 任务类型 (followup_scan, full_sync, phase2_scan)
            device_serial: 设备序列号
            initial_checkpoint: 初始检查点数据
            task_id: 可选的自定义任务ID（如果不提供则自动生成）
            total_items: 总项目数（用于进度计算，存储在 checkpoint 中）

        Returns:
            task_id: 任务唯一标识
        """
        if task_id is None:
            task_id = str(uuid.uuid4())[:8]  # 短 UUID

        # Include total_items in checkpoint if provided
        checkpoint_data = initial_checkpoint or {}
        if total_items > 0:
            checkpoint_data["total_items"] = total_items

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO recovery_state 
                (task_id, task_type, device_serial, status, checkpoint_data, started_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
                (
                    task_id,
                    task_type,
                    device_serial,
                    TaskStatus.RUNNING.value,
                    json.dumps(checkpoint_data) if checkpoint_data else None,
                ),
            )
            conn.commit()

        self._logger.info(f"Created recovery task: {task_id} ({task_type}) for device {device_serial}")
        return task_id

    def update_checkpoint(
        self, task_id: str, checkpoint: Dict[str, Any], progress_percent: Optional[int] = None
    ) -> None:
        """
        更新任务检查点

        Args:
            task_id: 任务ID
            checkpoint: 检查点数据
            progress_percent: 进度百分比
        """
        with self._connection() as conn:
            cursor = conn.cursor()

            if progress_percent is not None:
                cursor.execute(
                    """
                    UPDATE recovery_state 
                    SET checkpoint_data = ?, 
                        progress_percent = ?,
                        last_checkpoint_at = CURRENT_TIMESTAMP
                    WHERE task_id = ?
                """,
                    (json.dumps(checkpoint, ensure_ascii=False), progress_percent, task_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE recovery_state 
                    SET checkpoint_data = ?, 
                        last_checkpoint_at = CURRENT_TIMESTAMP
                    WHERE task_id = ?
                """,
                    (json.dumps(checkpoint, ensure_ascii=False), task_id),
                )

            conn.commit()

        self._logger.debug(f"Updated checkpoint for task {task_id}")

    def save_queue_state(
        self, task_id: str, pending: List[str], completed: List[str], failed: Optional[List[str]] = None
    ) -> None:
        """
        保存队列状态

        Args:
            task_id: 任务ID
            pending: 待处理项目列表
            completed: 已完成项目列表
            failed: 失败项目列表
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE recovery_state 
                SET pending_items = ?,
                    completed_items = ?,
                    failed_items = ?,
                    last_checkpoint_at = CURRENT_TIMESTAMP
                WHERE task_id = ?
            """,
                (
                    json.dumps(pending, ensure_ascii=False),
                    json.dumps(completed, ensure_ascii=False),
                    json.dumps(failed or [], ensure_ascii=False),
                    task_id,
                ),
            )
            conn.commit()

    def mark_completed(self, task_id: str) -> None:
        """标记任务完成"""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE recovery_state 
                SET status = ?,
                    progress_percent = 100,
                    completed_at = CURRENT_TIMESTAMP
                WHERE task_id = ?
            """,
                (TaskStatus.COMPLETED.value, task_id),
            )
            conn.commit()

        self._logger.info(f"Task {task_id} marked as completed")

    def mark_failed(self, task_id: str, error: str) -> None:
        """标记任务失败"""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE recovery_state 
                SET status = ?,
                    last_error = ?,
                    retry_count = retry_count + 1
                WHERE task_id = ?
            """,
                (TaskStatus.FAILED.value, error, task_id),
            )
            conn.commit()

        self._logger.warning(f"Task {task_id} marked as failed: {error}")

    def mark_paused(self, task_id: str) -> None:
        """标记任务暂停（用于优雅关闭）"""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE recovery_state 
                SET status = ?
                WHERE task_id = ?
            """,
                (TaskStatus.PAUSED.value, task_id),
            )
            conn.commit()

        self._logger.info(f"Task {task_id} marked as paused")

    def mark_pending_recovery(self, task_id: str) -> None:
        """标记任务等待恢复"""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE recovery_state 
                SET status = ?
                WHERE task_id = ?
            """,
                (TaskStatus.PENDING_RECOVERY.value, task_id),
            )
            conn.commit()

        self._logger.info(f"Task {task_id} marked as pending recovery")

    # =========================================================================
    # 恢复逻辑
    # =========================================================================

    def get_pending_tasks(self, task_type: Optional[str] = None) -> List[RecoveryTask]:
        """
        获取待恢复的任务

        Args:
            task_type: 可选，过滤特定类型的任务

        Returns:
            待恢复任务列表
        """
        with self._connection() as conn:
            cursor = conn.cursor()

            # 查找运行中、暂停或等待恢复的任务
            if task_type:
                cursor.execute(
                    """
                    SELECT * FROM recovery_state 
                    WHERE status IN (?, ?, ?)
                    AND task_type = ?
                    ORDER BY started_at DESC
                """,
                    (TaskStatus.RUNNING.value, TaskStatus.PAUSED.value, TaskStatus.PENDING_RECOVERY.value, task_type),
                )
            else:
                cursor.execute(
                    """
                    SELECT * FROM recovery_state 
                    WHERE status IN (?, ?, ?)
                    ORDER BY started_at DESC
                """,
                    (
                        TaskStatus.RUNNING.value,
                        TaskStatus.PAUSED.value,
                        TaskStatus.PENDING_RECOVERY.value,
                    ),
                )

            rows = cursor.fetchall()
            return [RecoveryTask.from_row(row) for row in rows]

    def get_task(self, task_id: str) -> Optional[RecoveryTask]:
        """获取特定任务"""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM recovery_state WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            return RecoveryTask.from_row(row) if row else None

    def get_task_checkpoint(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务检查点数据"""
        task = self.get_task(task_id)
        return task.checkpoint_data if task else None

    def load_queue_state(self, task_id: str) -> Tuple[List[str], List[str], List[str]]:
        """
        加载队列状态

        Returns:
            (pending, completed, failed) 元组
        """
        task = self.get_task(task_id)
        if not task:
            return [], [], []
        return task.pending_items, task.completed_items, task.failed_items

    def should_resume(self, task_type: str, device_serial: Optional[str] = None) -> bool:
        """
        检查是否应该恢复任务

        Args:
            task_type: 任务类型
            device_serial: 设备序列号（可选）

        Returns:
            是否有待恢复的任务
        """
        pending = self.get_pending_tasks(task_type)
        if not pending:
            return False

        if device_serial:
            return any(t.device_serial == device_serial for t in pending)

        return len(pending) > 0

    def get_resumable_task(self, task_type: str, device_serial: Optional[str] = None) -> Optional[RecoveryTask]:
        """
        获取可恢复的任务

        Args:
            task_type: 任务类型
            device_serial: 设备序列号（可选）

        Returns:
            可恢复的任务，如果没有返回 None
        """
        pending = self.get_pending_tasks(task_type)

        if device_serial:
            for task in pending:
                if task.device_serial == device_serial:
                    return task

        return pending[0] if pending else None

    # =========================================================================
    # 清理和管理
    # =========================================================================

    def clear_completed_tasks(self, days_old: int = 7) -> int:
        """清理已完成的旧任务"""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM recovery_state 
                WHERE status = ?
                AND completed_at < datetime('now', ?)
            """,
                (TaskStatus.COMPLETED.value, f"-{days_old} days"),
            )
            conn.commit()
            return cursor.rowcount

    def clear_all_tasks(self) -> int:
        """清除所有任务（慎用）"""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM recovery_state")
            conn.commit()
            return cursor.rowcount

    def discard_task(self, task_id: str) -> bool:
        """放弃特定任务"""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM recovery_state WHERE task_id = ?
            """,
                (task_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    # =========================================================================
    # 状态摘要
    # =========================================================================

    def get_status(self) -> Dict[str, Any]:
        """获取恢复系统状态摘要"""
        pending_tasks = self.get_pending_tasks()

        with self._connection() as conn:
            cursor = conn.cursor()

            # 统计各状态任务数
            cursor.execute("""
                SELECT status, COUNT(*) as count 
                FROM recovery_state 
                GROUP BY status
            """)
            status_counts = {row["status"]: row["count"] for row in cursor.fetchall()}

        return {
            "has_pending_tasks": len(pending_tasks) > 0,
            "pending_count": len(pending_tasks),
            "pending_tasks": [t.to_dict() for t in pending_tasks],
            "status_counts": status_counts,
            "can_resume": len(pending_tasks) > 0,
        }

    # =========================================================================
    # 设备连接状态
    # =========================================================================

    def update_device_connection(
        self, device_serial: str, is_connected: bool, pending_task_id: Optional[str] = None
    ) -> None:
        """更新设备连接状态"""
        with self._connection() as conn:
            cursor = conn.cursor()

            # 检查是否存在记录
            cursor.execute("SELECT id FROM device_connection_state WHERE device_serial = ?", (device_serial,))
            exists = cursor.fetchone()

            if exists:
                if is_connected:
                    cursor.execute(
                        """
                        UPDATE device_connection_state 
                        SET is_connected = 1,
                            last_connected_at = CURRENT_TIMESTAMP,
                            reconnect_attempts = 0,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE device_serial = ?
                    """,
                        (device_serial,),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE device_connection_state 
                        SET is_connected = 0,
                            last_disconnected_at = CURRENT_TIMESTAMP,
                            pending_task_id = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE device_serial = ?
                    """,
                        (pending_task_id, device_serial),
                    )
            else:
                cursor.execute(
                    """
                    INSERT INTO device_connection_state 
                    (device_serial, is_connected, pending_task_id)
                    VALUES (?, ?, ?)
                """,
                    (device_serial, 1 if is_connected else 0, pending_task_id),
                )

            conn.commit()

    def increment_reconnect_attempts(self, device_serial: str) -> int:
        """增加重连尝试次数，返回当前次数"""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE device_connection_state 
                SET reconnect_attempts = reconnect_attempts + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE device_serial = ?
            """,
                (device_serial,),
            )

            cursor.execute(
                "SELECT reconnect_attempts FROM device_connection_state WHERE device_serial = ?", (device_serial,)
            )
            row = cursor.fetchone()
            conn.commit()
            return row["reconnect_attempts"] if row else 0

    def get_device_pending_task(self, device_serial: str) -> Optional[str]:
        """获取设备的待恢复任务ID"""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT pending_task_id FROM device_connection_state WHERE device_serial = ?", (device_serial,)
            )
            row = cursor.fetchone()
            return row["pending_task_id"] if row else None

    # =========================================================================
    # 通用恢复功能 - UI 状态和应用状态管理
    # =========================================================================

    def save_ui_state(self, task_id: str, ui_state: Dict[str, Any]) -> None:
        """
        保存任务的 UI 状态

        用于在任意界面恢复时能够还原用户的界面状态

        Args:
            task_id: 任务ID
            ui_state: UI状态数据（包含路由、选中设备等）
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE recovery_state 
                SET ui_state = ?,
                    last_checkpoint_at = CURRENT_TIMESTAMP
                WHERE task_id = ?
            """,
                (json.dumps(ui_state, ensure_ascii=False), task_id),
            )
            conn.commit()
        self._logger.debug(f"Saved UI state for task {task_id}")

    def get_ui_state(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务的 UI 状态"""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT ui_state FROM recovery_state WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            if row and row["ui_state"]:
                try:
                    return json.loads(row["ui_state"])
                except:
                    return None
            return None

    def get_resumable_tasks_with_details(self) -> List[Dict[str, Any]]:
        """
        获取所有可恢复任务（包含详细信息）

        用于前端显示恢复对话框

        Returns:
            包含任务详情的列表
        """
        tasks = self.get_pending_tasks()
        result = []

        for task in tasks:
            # 解析检查点数据
            checkpoint = task.checkpoint_data or {}
            synced_customers = checkpoint.get("synced_customers", [])
            stats = checkpoint.get("stats", {})

            result.append(
                {
                    "task_id": task.task_id,
                    "task_type": task.task_type,
                    "device_serial": task.device_serial,
                    "status": task.status.value if hasattr(task.status, "value") else task.status,
                    "progress_percent": task.progress_percent,
                    "synced_count": len(synced_customers),
                    "total_count": stats.get("total_customers", 0),
                    "messages_added": stats.get("messages_added", 0),
                    "checkpoint_data": checkpoint,
                    "ui_state": self.get_ui_state(task.task_id),
                    "started_at": task.started_at.isoformat() if task.started_at else None,
                    "last_checkpoint_at": task.last_checkpoint_at.isoformat() if task.last_checkpoint_at else None,
                }
            )

        return result

    def mark_all_running_as_pending(self) -> int:
        """
        将所有运行中的任务标记为待恢复

        用于应用启动时检测到之前异常退出的任务

        Returns:
            更新的任务数量
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE recovery_state 
                SET status = ?
                WHERE status = ?
            """,
                (TaskStatus.PENDING_RECOVERY.value, TaskStatus.RUNNING.value),
            )
            count = cursor.rowcount
            conn.commit()

        if count > 0:
            self._logger.info(f"Marked {count} running tasks as pending recovery")
        return count

    def get_tasks_by_device(self, device_serial: str) -> List[Dict[str, Any]]:
        """
        获取指定设备的所有可恢复任务

        Args:
            device_serial: 设备序列号

        Returns:
            任务列表
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM recovery_state 
                WHERE device_serial = ?
                AND status IN (?, ?, ?)
                ORDER BY last_checkpoint_at DESC
            """,
                (
                    device_serial,
                    TaskStatus.RUNNING.value,
                    TaskStatus.PAUSED.value,
                    TaskStatus.PENDING_RECOVERY.value,
                ),
            )
            rows = cursor.fetchall()

            result = []
            for row in rows:
                task = RecoveryTask.from_row(row)
                checkpoint = task.checkpoint_data or {}
                synced_customers = checkpoint.get("synced_customers", [])

                result.append(
                    {
                        "task_id": task.task_id,
                        "task_type": task.task_type,
                        "device_serial": task.device_serial,
                        "status": task.status.value if hasattr(task.status, "value") else task.status,
                        "progress_percent": task.progress_percent,
                        "synced_count": len(synced_customers),
                        "checkpoint_data": checkpoint,
                        "last_checkpoint_at": task.last_checkpoint_at.isoformat() if task.last_checkpoint_at else None,
                    }
                )

            return result


# 单例
_recovery_manager: Optional[RecoveryManager] = None


def get_recovery_manager(db_path: Optional[str] = None) -> RecoveryManager:
    """获取 RecoveryManager 单例"""
    global _recovery_manager

    if _recovery_manager is None:
        if db_path is None:
            # Use centralized database path config
            db_path = str(get_default_db_path())
        _recovery_manager = RecoveryManager(db_path)

    return _recovery_manager
