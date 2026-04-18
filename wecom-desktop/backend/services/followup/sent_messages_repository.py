"""
Follow-up Sent Messages Repository

跟踪每个客户已发送的消息模板，用于补刀去重功能。
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Set

from services.conversation_storage import get_control_db_path, open_shared_sqlite

logger = logging.getLogger("followup.sent_messages_repository")


class FollowupSentMessagesRepository:
    """跟踪已发送消息模板的仓库"""

    def __init__(self, db_path: str | None = None):
        self._db_path = str(db_path or get_control_db_path())
        self._ensure_tables()

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接（带 busy_timeout/WAL 容错）"""
        return open_shared_sqlite(self._db_path, row_factory=True)

    def _ensure_tables(self):
        """确保表存在"""
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS followup_sent_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_serial TEXT NOT NULL,
                    customer_name TEXT NOT NULL,
                    message_template TEXT NOT NULL,
                    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(device_serial, customer_name, message_template)
                )
            """
            )

            # 创建索引：用于快速查询客户已发送的消息
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_followup_sent_messages_lookup
                ON followup_sent_messages(device_serial, customer_name)
            """
            )

            conn.commit()
            logger.debug("followup_sent_messages table ensured")

    def get_sent_templates(self, device_serial: str, customer_name: str) -> Set[str]:
        """
        获取已发送给客户的消息模板集合

        Args:
            device_serial: 设备序列号
            customer_name: 客户名称

        Returns:
            已发送的消息模板集合
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                """SELECT message_template FROM followup_sent_messages
                   WHERE device_serial = ? AND customer_name = ?""",
                (device_serial, customer_name),
            ).fetchall()

            return {row["message_template"] for row in rows}

    def record_sent_message(self, device_serial: str, customer_name: str, message_template: str) -> None:
        """
        记录已发送的消息模板

        Args:
            device_serial: 设备序列号
            customer_name: 客户名称
            message_template: 消息模板内容
        """
        with self._get_connection() as conn:
            try:
                conn.execute(
                    """INSERT INTO followup_sent_messages
                       (device_serial, customer_name, message_template)
                       VALUES (?, ?, ?)""",
                    (device_serial, customer_name, message_template),
                )
                conn.commit()
                logger.debug(
                    f"Recorded sent message for {customer_name} on {device_serial}: {message_template[:50]}..."
                )
            except sqlite3.IntegrityError:
                # UNIQUE约束违反，说明已经记录过了（幂等操作）
                logger.debug(
                    f"Message already recorded for {customer_name} on {device_serial}: {message_template[:50]}..."
                )

    def clear_all(self) -> int:
        """
        清空所有跟踪记录（模板修改时调用）

        Returns:
            删除的记录数
        """
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM followup_sent_messages")
            deleted_count = cursor.rowcount
            conn.commit()
            logger.info(f"Cleared {deleted_count} sent message tracking records")
            return deleted_count

    def get_statistics(self, device_serial: str | None = None) -> dict:
        """
        获取统计信息

        Args:
            device_serial: 可选的设备序列号，如果为None则统计所有设备

        Returns:
            统计信息字典
        """
        with self._get_connection() as conn:
            if device_serial:
                rows = conn.execute(
                    """SELECT customer_name, COUNT(*) as count
                       FROM followup_sent_messages
                       WHERE device_serial = ?
                       GROUP BY customer_name""",
                    (device_serial,),
                ).fetchall()
                total = conn.execute(
                    """SELECT COUNT(*) as total FROM followup_sent_messages
                       WHERE device_serial = ?""",
                    (device_serial,),
                ).fetchone()["total"]
            else:
                rows = conn.execute(
                    """SELECT customer_name, COUNT(*) as count
                       FROM followup_sent_messages
                       GROUP BY customer_name"""
                ).fetchall()
                total = conn.execute(
                    """SELECT COUNT(*) as total FROM followup_sent_messages"""
                ).fetchone()["total"]

            return {
                "total_records": total,
                "customers_tracked": len(rows),
                "device_serial": device_serial,
            }
