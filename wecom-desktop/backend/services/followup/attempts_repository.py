"""
补刀尝试记录仓库

管理 followup_attempts 表，跟踪需要补刀的客户状态。
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from services.conversation_storage import get_control_db_path

logger = logging.getLogger("followup.attempts_repository")


class AttemptStatus(str, Enum):
    """补刀尝试状态"""

    PENDING = "pending"  # 待补刀
    IN_PROGRESS = "in_progress"  # 补刀中
    COMPLETED = "completed"  # 已完成（达到上限或客户回复）
    CANCELLED = "cancelled"  # 已取消


@dataclass
class FollowupAttempt:
    """补刀尝试记录"""

    id: int | None = None
    device_serial: str = ""
    customer_name: str = ""
    customer_id: str | None = None
    customer_channel: str | None = None  # 客户渠道（用于黑名单检查）

    # 消息追踪
    last_kefu_message_id: str = ""  # 进入队列时 kefu 最后一条消息 ID
    last_kefu_message_time: datetime | None = None  # kefu 最后一条消息时间
    last_checked_message_id: str | None = None  # 最近一次检查时的最后消息 ID

    # 补刀状态
    max_attempts: int = 3  # 最大补刀次数
    current_attempt: int = 0  # 已补刀次数
    status: AttemptStatus = AttemptStatus.PENDING

    # 时间戳
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_followup_at: datetime | None = None  # 最后补刀时间


class FollowupAttemptsRepository:
    """补刀尝试记录仓库"""

    def __init__(self, db_path: str | None = None):
        self._db_path = str(db_path or get_control_db_path())
        self._ensure_tables()

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self):
        """确保表存在"""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS followup_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_serial TEXT NOT NULL,
                    customer_name TEXT NOT NULL,
                    customer_id TEXT,
                    customer_channel TEXT,
                    
                    last_kefu_message_id TEXT NOT NULL,
                    last_kefu_message_time DATETIME,
                    last_checked_message_id TEXT,
                    
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    current_attempt INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_followup_at DATETIME,
                    
                    UNIQUE(device_serial, customer_name)
                )
            """)

            # 创建索引
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_followup_attempts_device_status 
                ON followup_attempts(device_serial, status)
            """)

            # 迁移: 添加 customer_channel 列（兼容已有数据库）
            try:
                conn.execute("ALTER TABLE followup_attempts ADD COLUMN customer_channel TEXT")
                logger.info("Migrated followup_attempts: added customer_channel column")
            except sqlite3.OperationalError:
                pass  # 列已存在，忽略

            # 确保 followup_sent_messages 表存在（补刀去重用）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS followup_sent_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_serial TEXT NOT NULL,
                    customer_name TEXT NOT NULL,
                    message_template TEXT NOT NULL,
                    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(device_serial, customer_name, message_template)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_followup_sent_messages_lookup
                ON followup_sent_messages(device_serial, customer_name)
            """)

            conn.commit()

    def _row_to_attempt(self, row: sqlite3.Row) -> FollowupAttempt:
        """将数据库行转换为 FollowupAttempt 对象"""
        # 兼容旧数据库（可能没有 customer_channel 列）
        try:
            customer_channel = row["customer_channel"]
        except (IndexError, KeyError):
            customer_channel = None

        return FollowupAttempt(
            id=row["id"],
            device_serial=row["device_serial"],
            customer_name=row["customer_name"],
            customer_id=row["customer_id"],
            customer_channel=customer_channel,
            last_kefu_message_id=row["last_kefu_message_id"],
            last_kefu_message_time=datetime.fromisoformat(row["last_kefu_message_time"])
            if row["last_kefu_message_time"]
            else None,
            last_checked_message_id=row["last_checked_message_id"],
            max_attempts=row["max_attempts"],
            current_attempt=row["current_attempt"],
            status=AttemptStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
            last_followup_at=datetime.fromisoformat(row["last_followup_at"]) if row["last_followup_at"] else None,
        )

    # ==================== CRUD 操作 ====================

    def add_or_update(
        self,
        device_serial: str,
        customer_name: str,
        last_kefu_message_id: str,
        last_kefu_message_time: datetime | None = None,
        max_attempts: int = 3,
        customer_id: str | None = None,
        customer_channel: str | None = None,
    ) -> FollowupAttempt:
        """
        添加或更新补刀记录

        如果客户已存在且状态为 pending，则更新消息 ID
        如果不存在或已完成，则创建新记录
        """
        with self._get_connection() as conn:
            now = datetime.now().isoformat()

            # 检查是否已存在
            existing = conn.execute(
                """SELECT * FROM followup_attempts 
                   WHERE device_serial = ? AND customer_name = ?""",
                (device_serial, customer_name),
            ).fetchone()

            if existing:
                # 如果已存在且未完成，更新消息 ID 和 channel
                if existing["status"] == AttemptStatus.PENDING.value:
                    conn.execute(
                        """UPDATE followup_attempts 
                           SET last_kefu_message_id = ?,
                               last_kefu_message_time = ?,
                               customer_channel = COALESCE(?, customer_channel),
                               updated_at = ?
                           WHERE id = ?""",
                        (
                            last_kefu_message_id,
                            last_kefu_message_time.isoformat() if last_kefu_message_time else None,
                            customer_channel,
                            now,
                            existing["id"],
                        ),
                    )
                    conn.commit()
                    return self.get_by_id(existing["id"])
                else:
                    # 已完成/取消的，重置为 pending
                    conn.execute(
                        """UPDATE followup_attempts 
                           SET last_kefu_message_id = ?,
                               last_kefu_message_time = ?,
                               last_checked_message_id = NULL,
                               current_attempt = 0,
                               max_attempts = ?,
                               customer_channel = COALESCE(?, customer_channel),
                               status = 'pending',
                               updated_at = ?
                           WHERE id = ?""",
                        (
                            last_kefu_message_id,
                            last_kefu_message_time.isoformat() if last_kefu_message_time else None,
                            max_attempts,
                            customer_channel,
                            now,
                            existing["id"],
                        ),
                    )
                    conn.commit()
                    return self.get_by_id(existing["id"])
            else:
                # 新建记录
                cursor = conn.execute(
                    """INSERT INTO followup_attempts 
                       (device_serial, customer_name, customer_id, customer_channel,
                        last_kefu_message_id, last_kefu_message_time, max_attempts,
                        status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                    (
                        device_serial,
                        customer_name,
                        customer_id,
                        customer_channel,
                        last_kefu_message_id,
                        last_kefu_message_time.isoformat() if last_kefu_message_time else None,
                        max_attempts,
                        now,
                        now,
                    ),
                )
                conn.commit()
                return self.get_by_id(cursor.lastrowid)

    def get_by_id(self, attempt_id: int) -> FollowupAttempt | None:
        """根据 ID 获取记录"""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM followup_attempts WHERE id = ?", (attempt_id,)).fetchone()
            return self._row_to_attempt(row) if row else None

    def get_by_customer(self, device_serial: str, customer_name: str) -> FollowupAttempt | None:
        """根据设备和客户名获取记录"""
        with self._get_connection() as conn:
            row = conn.execute(
                """SELECT * FROM followup_attempts 
                   WHERE device_serial = ? AND customer_name = ?""",
                (device_serial, customer_name),
            ).fetchone()
            return self._row_to_attempt(row) if row else None

    def get_pending_attempts(
        self,
        device_serial: str,
        limit: int = 10,
        attempt_intervals: list[int] | None = None,
    ) -> list[FollowupAttempt]:
        """
        获取待补刀的记录

        条件：
        - status = pending
        - current_attempt < max_attempts
        - 间隔时间检查：
          * current_attempt = 0: 首次补刀，无需检查间隔
          * current_attempt > 0: 必须满足间隔时间要求

        Args:
            device_serial: 设备序列号
            limit: 返回记录数限制
            attempt_intervals: 补刀间隔时间列表（分钟），如 [60, 120, 180]
                              第1次补刀后等待 60 分钟，第2次等待 120 分钟...

        按创建时间排序
        """
        if attempt_intervals is None or len(attempt_intervals) == 0:
            attempt_intervals = [60, 120, 180]  # 默认值

        with self._get_connection() as conn:
            # 获取所有符合基本条件的记录
            rows = conn.execute(
                """SELECT * FROM followup_attempts 
                   WHERE device_serial = ? 
                     AND status = 'pending'
                     AND current_attempt < max_attempts
                   ORDER BY created_at ASC""",
                (device_serial,),
            ).fetchall()

            # 过滤：检查间隔时间
            filtered_attempts = []
            now = datetime.now()

            for row in rows:
                attempt = self._row_to_attempt(row)

                # 首次补刀 (current_attempt = 0)，无需检查间隔
                if attempt.current_attempt == 0:
                    filtered_attempts.append(attempt)
                    continue

                # 后续补刀，检查距离上次补刀的时间
                if attempt.last_followup_at:
                    # 获取对应的间隔时间（分钟）
                    # attempt_intervals[0] = 第1次补刀后等待时间
                    # attempt_intervals[1] = 第2次补刀后等待时间
                    # ...
                    interval_index = attempt.current_attempt - 1
                    if interval_index < len(attempt_intervals):
                        required_interval_minutes = attempt_intervals[interval_index]
                    else:
                        # 超出索引，使用最后一个间隔
                        required_interval_minutes = attempt_intervals[-1] if attempt_intervals else 60

                    # 计算距离上次补刀的时间
                    time_since_last = now - attempt.last_followup_at
                    minutes_since_last = time_since_last.total_seconds() / 60

                    # 检查是否满足间隔要求
                    if minutes_since_last >= required_interval_minutes:
                        filtered_attempts.append(attempt)
                    # else: 未到间隔时间，跳过
                else:
                    # 理论上 current_attempt > 0 必须有 last_followup_at
                    # 如果没有，可能是数据问题，允许补刀
                    filtered_attempts.append(attempt)

                # 达到限制，停止
                if len(filtered_attempts) >= limit:
                    break

            return filtered_attempts[:limit]

    def get_all_by_device(
        self,
        device_serial: str,
        status: AttemptStatus | None = None,
    ) -> list[FollowupAttempt]:
        """获取设备的所有补刀记录"""
        with self._get_connection() as conn:
            if status:
                rows = conn.execute(
                    """SELECT * FROM followup_attempts 
                       WHERE device_serial = ? AND status = ?
                       ORDER BY updated_at DESC""",
                    (device_serial, status.value),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM followup_attempts 
                       WHERE device_serial = ?
                       ORDER BY updated_at DESC""",
                    (device_serial,),
                ).fetchall()
            return [self._row_to_attempt(row) for row in rows]

    # ==================== 状态更新 ====================

    def mark_customer_replied(
        self,
        device_serial: str,
        customer_name: str,
    ) -> bool:
        """
        标记客户已回复（移出补刀队列）
        """
        with self._get_connection() as conn:
            now = datetime.now().isoformat()
            cursor = conn.execute(
                """UPDATE followup_attempts 
                   SET status = 'completed', updated_at = ?
                   WHERE device_serial = ? AND customer_name = ? AND status = 'pending'""",
                (now, device_serial, customer_name),
            )
            conn.commit()
            return cursor.rowcount > 0

    def record_followup_sent(
        self,
        attempt_id: int,
        new_message_id: str,
    ) -> FollowupAttempt | None:
        """
        记录补刀已发送

        - current_attempt += 1
        - last_checked_message_id = new_message_id
        - last_followup_at = now
        - 如果达到上限，status = completed
        """
        with self._get_connection() as conn:
            now = datetime.now().isoformat()

            # 先获取当前记录
            row = conn.execute("SELECT * FROM followup_attempts WHERE id = ?", (attempt_id,)).fetchone()

            if not row:
                return None

            new_attempt = row["current_attempt"] + 1
            new_status = (
                AttemptStatus.COMPLETED.value if new_attempt >= row["max_attempts"] else AttemptStatus.PENDING.value
            )

            conn.execute(
                """UPDATE followup_attempts 
                   SET current_attempt = ?,
                       last_checked_message_id = ?,
                       last_followup_at = ?,
                       status = ?,
                       updated_at = ?
                   WHERE id = ?""",
                (new_attempt, new_message_id, now, new_status, now, attempt_id),
            )
            conn.commit()
            return self.get_by_id(attempt_id)

    def update_status(
        self,
        attempt_id: int,
        status: AttemptStatus,
    ) -> bool:
        """更新状态"""
        with self._get_connection() as conn:
            now = datetime.now().isoformat()
            cursor = conn.execute(
                """UPDATE followup_attempts 
                   SET status = ?, updated_at = ?
                   WHERE id = ?""",
                (status.value, now, attempt_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete(self, attempt_id: int) -> bool:
        """删除记录"""
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM followup_attempts WHERE id = ?", (attempt_id,))
            conn.commit()
            return cursor.rowcount > 0

    def delete_by_customer(
        self,
        device_serial: str,
        customer_name: str,
    ) -> bool:
        """删除指定客户的记录"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """DELETE FROM followup_attempts 
                   WHERE device_serial = ? AND customer_name = ?""",
                (device_serial, customer_name),
            )
            conn.commit()
            return cursor.rowcount > 0

    def cancel_attempts_by_customer(
        self,
        device_serial: str,
        customer_name: str,
        reason: str | None = None,
    ) -> int:
        """
        取消指定用户的所有待补刀记录
        
        Args:
            device_serial: 设备序列号
            customer_name: 用户名
            reason: 取消原因
            
        Returns:
            被取消的记录数量
        """
        with self._get_connection() as conn:
            now = datetime.now().isoformat()
            cursor = conn.execute(
                """UPDATE followup_attempts 
                   SET status = ?, updated_at = ?
                   WHERE device_serial = ? 
                     AND customer_name = ? 
                     AND status = ?""",
                (AttemptStatus.CANCELLED.value, now, device_serial, customer_name, AttemptStatus.PENDING.value),
            )
            conn.commit()
            cancelled_count = cursor.rowcount
            
            if cancelled_count > 0:
                logger.info(
                    f"Cancelled {cancelled_count} pending attempts for {customer_name} "
                    f"on {device_serial}. Reason: {reason or 'N/A'}"
                )
            
            return cancelled_count

    # ==================== 统计 ====================

    def get_statistics(self, device_serial: str) -> dict[str, Any]:
        """获取设备的补刀统计"""
        with self._get_connection() as conn:
            rows = conn.execute(
                """SELECT status, COUNT(*) as count 
                   FROM followup_attempts 
                   WHERE device_serial = ?
                   GROUP BY status""",
                (device_serial,),
            ).fetchall()

            stats = {
                "total": 0,
                "pending": 0,
                "in_progress": 0,
                "completed": 0,
                "cancelled": 0,
            }

            for row in rows:
                stats[row["status"]] = row["count"]
                stats["total"] += row["count"]

            return stats

    def cleanup_old_records(self, days: int = 30) -> int:
        """清理旧记录"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """DELETE FROM followup_attempts 
                   WHERE status IN ('completed', 'cancelled')
                     AND updated_at < datetime('now', ?)""",
                (f"-{days} days",),
            )
            conn.commit()
            return cursor.rowcount
