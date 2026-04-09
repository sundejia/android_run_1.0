"""
会话数据仓库（Conversation Repository）

负责客户、消息等会话相关数据库操作，供实时回复（Realtime Reply）使用。
后续可在此模块外单独实现「补刀跟进」专用处理类。
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from .settings import SettingsManager

logger = logging.getLogger("followup.repository")


class ConversationRepository:
    """会话数据仓库：客户、消息等，供实时回复使用"""

    def __init__(self, db_path: str, settings_manager: SettingsManager | None = None):
        self._db_path = db_path
        self._settings_manager = settings_manager or SettingsManager(db_path)
        self._ensure_tables()

    @contextmanager
    def _connection(self):
        """获取数据库连接上下文"""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_tables(self) -> None:
        """确保必要的表存在"""
        with self._connection() as conn:
            cursor = conn.cursor()

            # Create kefus table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS kefus (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    serial TEXT UNIQUE,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create customers table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    channel TEXT,
                    kefu_id INTEGER,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (kefu_id) REFERENCES kefus(id)
                )
            """)

            # Create messages table if not exists (needed for find_candidates query)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL,
                    content TEXT,
                    message_type TEXT NOT NULL DEFAULT 'text',
                    is_from_kefu BOOLEAN NOT NULL DEFAULT 0,
                    timestamp_raw TEXT,
                    timestamp_parsed TIMESTAMP,
                    extra_info TEXT,
                    message_hash TEXT UNIQUE NOT NULL,
                    ui_position INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
                )
            """)

            # Note: followup_attempts table removed - managed by followup_manage.py router

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_customer_id 
                ON messages(customer_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_timestamp 
                ON messages(timestamp_parsed)
            """)

            conn.commit()

    def save_message(
        self,
        customer_id: int,
        content: str,
        message_type: str = "text",
        is_from_kefu: bool = True,
        timestamp_raw: str | None = None,
        timestamp_parsed: datetime | None = None,
    ) -> int | None:
        """
        保存消息到 messages 表

        Args:
            customer_id: 客户ID
            content: 消息内容
            message_type: 消息类型 (text, image, voice, video)
            is_from_kefu: 是否来自客服
            timestamp_raw: 原始时间戳字符串
            timestamp_parsed: 解析后的时间戳

        Returns:
            消息ID，如果重复则返回 None
        """
        import hashlib

        with self._connection() as conn:
            cursor = conn.cursor()

            # 生成消息哈希（用于去重）
            hash_content = f"{customer_id}:{content}:{is_from_kefu}:{timestamp_raw or ''}"
            message_hash = hashlib.md5(hash_content.encode()).hexdigest()

            try:
                cursor.execute(
                    """
                    INSERT INTO messages 
                    (customer_id, content, message_type, is_from_kefu, 
                     timestamp_raw, timestamp_parsed, message_hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                    (
                        customer_id,
                        content,
                        message_type,
                        1 if is_from_kefu else 0,
                        timestamp_raw,
                        timestamp_parsed.isoformat() if timestamp_parsed else None,
                        message_hash,
                    ),
                )
                conn.commit()
                logger.debug(f"Saved message for customer {customer_id}: {content[:30]}...")
                return cursor.lastrowid
            except Exception as e:
                if "UNIQUE constraint failed" in str(e):
                    logger.debug(f"Message already exists (duplicate hash): {content[:30]}...")
                    return None
                raise

    # ==================== Follow-up Attempts Methods Removed ====================
    # The following methods have been removed (now managed by followup_manage.py router):
    # - record_attempt(): Record follow-up attempt to followup_attempts table
    # - mark_responded(): Mark customer as responded in followup_attempts table
    # - get_attempt_count(): Get pending follow-up attempt count for customer
    #
    # These were Phase 2 (follow-up management) features.
    # Follow-up management now uses its own table management in followup_manage.py.

    def find_or_create_customer(
        self, name: str, channel: str | None = None, device_serial: str | None = None
    ) -> int:
        """查找或创建客户，返回 customer_id"""
        with self._connection() as conn:
            cursor = conn.cursor()
            normalized_channel = channel.strip() if isinstance(channel, str) and channel.strip() else None

            kefu_id = None
            if device_serial:
                # 通过 devices + kefu_devices 关联查找 kefu
                cursor.execute(
                    """
                    SELECT k.id FROM kefus k
                    JOIN kefu_devices kd ON k.id = kd.kefu_id
                    JOIN devices d ON kd.device_id = d.id
                    WHERE d.serial = ?
                    ORDER BY
                        CASE WHEN k.name LIKE 'Kefu-%' THEN 1 ELSE 0 END ASC,
                        COALESCE(k.updated_at, k.created_at) DESC,
                        k.id DESC
                    LIMIT 1
                """,
                    (device_serial,),
                )
                kefu_row = cursor.fetchone()
                if kefu_row:
                    kefu_id = kefu_row[0]
                else:
                    # 创建设备记录（如果不存在）
                    cursor.execute("SELECT id FROM devices WHERE serial = ?", (device_serial,))
                    device_row = cursor.fetchone()
                    if device_row:
                        device_id = device_row[0]
                    else:
                        cursor.execute(
                            """
                            INSERT INTO devices (serial, created_at, updated_at)
                            VALUES (?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """,
                            (device_serial,),
                        )
                        device_id = cursor.lastrowid

                    # 创建 kefu 记录
                    kefu_name = f"Kefu-{device_serial[:8]}"
                    cursor.execute(
                        """
                        INSERT INTO kefus (name, created_at, updated_at)
                        VALUES (?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                        (kefu_name,),
                    )
                    kefu_id = cursor.lastrowid

                    # 创建关联
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO kefu_devices (kefu_id, device_id, created_at, updated_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                        (kefu_id, device_id),
                    )

            row = None
            if kefu_id is not None:
                # Resolve customers within the selected kefu first.
                # Reusing any same-name customer on the device would attach
                # the conversation to the wrong kefu when multiple agents
                # have talked to the same user on the same device.
                cursor.execute(
                    """
                    SELECT id
                    FROM customers
                    WHERE name = ?
                      AND kefu_id = ?
                      AND ((channel IS NULL AND ? IS NULL) OR channel = ?)
                    ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
                    LIMIT 1
                    """,
                    (name, kefu_id, normalized_channel, normalized_channel),
                )
                row = cursor.fetchone()
            else:
                # Fallback for older flows that do not provide device context.
                cursor.execute(
                    """
                    SELECT id
                    FROM customers
                    WHERE name = ?
                      AND ((channel IS NULL AND ? IS NULL) OR channel = ?)
                    ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
                    LIMIT 1
                    """,
                    (name, normalized_channel, normalized_channel),
                )
                row = cursor.fetchone()

            if row:
                return row[0]

            # Create new customer
            cursor.execute(
                """
                INSERT INTO customers (name, channel, kefu_id, created_at, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
                (name, normalized_channel, kefu_id),
            )
            conn.commit()
            return cursor.lastrowid

    # ==================== Phase 2 Methods Removed ====================
    # The following Phase 2 (follow-up sending) methods have been removed:
    # - find_candidates(): Query customers needing follow-up reminders
    # - get_pending_customers(): Get customers with pending follow-ups
    # - save_followup_message(): Save follow-up message to messages table
    #
    # These will be reimplemented in the new follow-up management system.
    # Phase 1 (instant response) continues to work with the remaining methods.

    def get_customer_by_name(self, name: str) -> dict[str, Any] | None:
        """通过名称获取客户信息"""
        with self._connection() as conn:
            cursor = conn.cursor()
            # 通过 kefu_devices 关联表获取设备信息
            cursor.execute(
                """
                SELECT c.*, d.serial as device_serial
                FROM customers c
                LEFT JOIN kefus k ON c.kefu_id = k.id
                LEFT JOIN kefu_devices kd ON k.id = kd.kefu_id
                LEFT JOIN devices d ON kd.device_id = d.id
                WHERE c.name = ?
            """,
                (name,),
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def _parse_datetime(self, ts_str: str | None) -> datetime | None:
        """解析时间戳字符串"""
        if not ts_str:
            return None
        try:
            ts = ts_str
            if "+" in ts:
                ts = ts.split("+")[0]
            if "Z" in ts:
                ts = ts.replace("Z", "")
            if "T" in ts:
                return datetime.fromisoformat(ts)
            return datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None
