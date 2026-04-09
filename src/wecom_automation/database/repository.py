"""
Repository pattern implementation for database operations.

This module provides a clean interface for all CRUD operations,
including message deduplication and conversation management.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from wecom_automation.database.models import (
    CustomerRecord,
    DeviceRecord,
    ImageRecord,
    KefuRecord,
    MessageRecord,
    VideoRecord,
    VoiceRecord,
)
from wecom_automation.database.retry import retry_on_db_lock
from wecom_automation.database.schema import get_connection, init_database


class ConversationRepository:
    """
    Repository for managing conversation data in SQLite.

    This class provides a clean interface for all database operations,
    handling connection management and transactions automatically.

    Usage:
        repo = ConversationRepository("path/to/db.sqlite")

        # Create or get a device
        device = repo.get_or_create_device("device_serial", model="Pixel 6")

        # Create or get a kefu
        kefu = repo.get_or_create_kefu("张三", device.id)

        # Create or get a customer
        customer = repo.get_or_create_customer("客户A", kefu.id, channel="@WeChat")

        # Add messages (with automatic deduplication)
        msg = MessageRecord(customer_id=customer.id, content="Hello", ...)
        success = repo.add_message_if_not_exists(msg)
    """

    def __init__(self, db_path: str | None = None, auto_init: bool = True):
        """
        Initialize the repository.

        Args:
            db_path: Path to the SQLite database file.
            auto_init: If True, initialize database schema if needed.
        """
        self.db_path = db_path
        if auto_init:
            init_database(db_path)

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for database connections."""
        conn = get_connection(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _transaction(self) -> Generator[tuple[sqlite3.Connection, sqlite3.Cursor], None, None]:
        """Context manager for database transactions."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        try:
            yield conn, cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # =========================================================================
    # Device Operations
    # =========================================================================

    def get_device_by_serial(self, serial: str) -> DeviceRecord | None:
        """
        Get a device by serial number.

        Args:
            serial: Device serial number.

        Returns:
            DeviceRecord if found, None otherwise.
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM devices WHERE serial = ?", (serial,))
            row = cursor.fetchone()
            return DeviceRecord.from_row(row) if row else None

    def get_device_by_id(self, device_id: int) -> DeviceRecord | None:
        """Get a device by ID."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM devices WHERE id = ?", (device_id,))
            row = cursor.fetchone()
            return DeviceRecord.from_row(row) if row else None

    @retry_on_db_lock(max_retries=3)
    def create_device(self, device: DeviceRecord) -> DeviceRecord:
        """
        Create a new device record.

        Args:
            device: DeviceRecord to create.

        Returns:
            Created DeviceRecord with ID populated.
        """
        with self._transaction() as (conn, cursor):
            data = device.to_dict()
            cursor.execute(
                """
                INSERT INTO devices (serial, model, manufacturer, android_version)
                VALUES (:serial, :model, :manufacturer, :android_version)
                """,
                data,
            )
            device.id = cursor.lastrowid
            return device

    def get_or_create_device(
        self,
        serial: str,
        model: str | None = None,
        manufacturer: str | None = None,
        android_version: str | None = None,
    ) -> DeviceRecord:
        """
        Get existing device or create new one.

        Args:
            serial: Device serial number.
            model: Device model name.
            manufacturer: Device manufacturer.
            android_version: Android version.

        Returns:
            DeviceRecord (existing or newly created).
        """
        existing = self.get_device_by_serial(serial)
        if existing:
            return existing

        device = DeviceRecord(
            serial=serial,
            model=model,
            manufacturer=manufacturer,
            android_version=android_version,
        )
        return self.create_device(device)

    def list_devices(self) -> list[DeviceRecord]:
        """List all devices."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM devices ORDER BY created_at DESC")
            return [DeviceRecord.from_row(row) for row in cursor.fetchall()]

    # =========================================================================
    # Kefu Operations
    # =========================================================================

    def get_kefu_by_id(self, kefu_id: int) -> KefuRecord | None:
        """Get a kefu by ID."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM kefus WHERE id = ?", (kefu_id,))
            row = cursor.fetchone()
            return KefuRecord.from_row(row) if row else None

    def get_kefu_by_name_and_department(
        self,
        name: str,
        department: str | None = None,
    ) -> KefuRecord | None:
        """
        Get a kefu by name and department.

        Args:
            name: Kefu name.
            department: Department/organization name.

        Returns:
            KefuRecord if found, None otherwise.
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            if department:
                cursor.execute("SELECT * FROM kefus WHERE name = ? AND department = ?", (name, department))
            else:
                cursor.execute("SELECT * FROM kefus WHERE name = ? AND department IS NULL", (name,))
            row = cursor.fetchone()
            return KefuRecord.from_row(row) if row else None

    @retry_on_db_lock(max_retries=3)
    def create_kefu(self, kefu: KefuRecord) -> KefuRecord:
        """
        Create a new kefu record.

        Args:
            kefu: KefuRecord to create.

        Returns:
            Created KefuRecord with ID populated.
        """
        with self._transaction() as (conn, cursor):
            data = kefu.to_dict()
            cursor.execute(
                """
                INSERT INTO kefus (name, department, verification_status)
                VALUES (:name, :department, :verification_status)
                """,
                data,
            )
            kefu.id = cursor.lastrowid
            return kefu

    def link_kefu_to_device(self, kefu_id: int, device_id: int) -> None:
        """
        Link a kefu to a device (creates kefu_devices record if not exists).

        Args:
            kefu_id: Kefu ID.
            device_id: Device ID.
        """
        with self._transaction() as (conn, cursor):
            cursor.execute(
                """
                INSERT OR IGNORE INTO kefu_devices (kefu_id, device_id)
                VALUES (?, ?)
                """,
                (kefu_id, device_id),
            )

    def get_or_create_kefu(
        self,
        name: str,
        device_id: int,
        department: str | None = None,
        verification_status: str | None = None,
    ) -> KefuRecord:
        """
        Get existing kefu or create new one, and link to device.

        Kefus are identified by name + department (not device).
        The device is linked via the kefu_devices junction table.

        Args:
            name: Kefu name.
            device_id: Device ID to link.
            department: Department name.
            verification_status: Verification status.

        Returns:
            KefuRecord (existing or newly created).
        """
        existing = self.get_kefu_by_name_and_department(name, department)
        if existing:
            # Link to device if not already linked
            self.link_kefu_to_device(existing.id, device_id)
            return existing

        kefu = KefuRecord(
            name=name,
            department=department,
            verification_status=verification_status,
        )
        created = self.create_kefu(kefu)
        # Link to device
        self.link_kefu_to_device(created.id, device_id)
        return created

    def list_kefus_for_device(self, device_id: int) -> list[KefuRecord]:
        """List all kefus for a device."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT k.* FROM kefus k
                JOIN kefu_devices kd ON k.id = kd.kefu_id
                WHERE kd.device_id = ?
                ORDER BY k.created_at DESC
                """,
                (device_id,),
            )
            return [KefuRecord.from_row(row) for row in cursor.fetchall()]

    def get_devices_for_kefu(self, kefu_id: int) -> list[DeviceRecord]:
        """List all devices used by a kefu."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT d.* FROM devices d
                JOIN kefu_devices kd ON d.id = kd.device_id
                WHERE kd.kefu_id = ?
                ORDER BY kd.created_at DESC
                """,
                (kefu_id,),
            )
            return [DeviceRecord.from_row(row) for row in cursor.fetchall()]

    # =========================================================================
    # Customer Operations
    # =========================================================================

    def get_customer_by_id(self, customer_id: int) -> CustomerRecord | None:
        """Get a customer by ID."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
            row = cursor.fetchone()
            return CustomerRecord.from_row(row) if row else None

    @staticmethod
    def _normalize_timestamp(value: datetime | str | None) -> str:
        """Normalize timestamps for persisted customer facts."""
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, str) and value.strip():
            return value.strip()
        return datetime.now().isoformat()

    def get_customer(
        self,
        name: str,
        kefu_id: int,
        channel: str | None = None,
    ) -> CustomerRecord | None:
        """
        Get a customer by name, kefu, and channel.

        Args:
            name: Customer name.
            kefu_id: Kefu ID.
            channel: Message channel (e.g., @WeChat).

        Returns:
            CustomerRecord if found, None otherwise.
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            if channel:
                cursor.execute(
                    "SELECT * FROM customers WHERE name = ? AND kefu_id = ? AND channel = ?", (name, kefu_id, channel)
                )
            else:
                cursor.execute(
                    "SELECT * FROM customers WHERE name = ? AND kefu_id = ? AND channel IS NULL", (name, kefu_id)
                )
            row = cursor.fetchone()
            return CustomerRecord.from_row(row) if row else None

    @staticmethod
    def _normalize_timestamp(value: datetime | str | None) -> str:
        """Normalize timestamps for fact columns."""
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, str) and value.strip():
            return value.strip()
        return datetime.now().isoformat()

    @retry_on_db_lock(max_retries=3)
    def create_customer(self, customer: CustomerRecord) -> CustomerRecord:
        """
        Create a new customer record.

        Args:
            customer: CustomerRecord to create.

        Returns:
            Created CustomerRecord with ID populated.
        """
        with self._transaction() as (conn, cursor):
            data = customer.to_dict()
            cursor.execute(
                """
                INSERT INTO customers (
                    name, channel, kefu_id, last_message_preview, last_message_date,
                    friend_added_at, first_customer_media_at, has_customer_media
                )
                VALUES (
                    :name, :channel, :kefu_id, :last_message_preview, :last_message_date,
                    :friend_added_at, :first_customer_media_at, :has_customer_media
                )
                """,
                data,
            )
            customer.id = cursor.lastrowid
            return customer

    def get_or_create_customer(
        self,
        name: str,
        kefu_id: int,
        channel: str | None = None,
        last_message_preview: str | None = None,
        last_message_date: str | None = None,
    ) -> CustomerRecord:
        """
        Get existing customer or create new one.

        Args:
            name: Customer name.
            kefu_id: Kefu ID.
            channel: Message channel.
            last_message_preview: Preview of last message.
            last_message_date: Date of last message.

        Returns:
            CustomerRecord (existing or newly created).
        """
        existing = self.get_customer(name, kefu_id, channel)
        if existing:
            return existing

        customer = CustomerRecord(
            name=name,
            kefu_id=kefu_id,
            channel=channel,
            last_message_preview=last_message_preview,
            last_message_date=last_message_date,
        )
        return self.create_customer(customer)

    def update_customer_last_message(
        self,
        customer_id: int,
        preview: str,
        date: str,
    ) -> None:
        """Update customer's last message info."""
        with self._transaction() as (conn, cursor):
            cursor.execute(
                """
                UPDATE customers
                SET last_message_preview = ?, last_message_date = ?
                WHERE id = ?
                """,
                (preview, date, customer_id),
            )

    def mark_customer_friend_added(
        self,
        customer_id: int,
        detected_at: datetime | str | None = None,
    ) -> bool:
        """Persist the first true new-friend detection timestamp."""
        timestamp = self._normalize_timestamp(detected_at)
        with self._transaction() as (conn, cursor):
            cursor.execute(
                """
                UPDATE customers
                SET friend_added_at = COALESCE(friend_added_at, ?)
                WHERE id = ?
                """,
                (timestamp, customer_id),
            )
            return cursor.rowcount > 0

    def mark_customer_sent_media(
        self,
        customer_id: int,
        sent_at: datetime | str | None = None,
    ) -> bool:
        """Persist the first customer-side photo/video timestamp."""
        timestamp = self._normalize_timestamp(sent_at)
        with self._transaction() as (conn, cursor):
            cursor.execute(
                """
                UPDATE customers
                SET
                    first_customer_media_at = CASE
                        WHEN first_customer_media_at IS NULL THEN ?
                        WHEN first_customer_media_at > ? THEN ?
                        ELSE first_customer_media_at
                    END,
                    has_customer_media = 1
                WHERE id = ?
                """,
                (timestamp, timestamp, timestamp, customer_id),
            )
            return cursor.rowcount > 0

    def list_customers_for_kefu(self, kefu_id: int) -> list[CustomerRecord]:
        """List all customers for a kefu."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM customers WHERE kefu_id = ? ORDER BY updated_at DESC", (kefu_id,))
            return [CustomerRecord.from_row(row) for row in cursor.fetchall()]

    def count_customers_for_kefu(self, kefu_id: int) -> int:
        """Count customers for a kefu."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM customers WHERE kefu_id = ?", (kefu_id,))
            return cursor.fetchone()["count"]

    # =========================================================================
    # Message Operations
    # =========================================================================

    def get_message_by_hash(self, message_hash: str) -> MessageRecord | None:
        """
        Get a message by its hash (for deduplication).

        Args:
            message_hash: SHA256 hash of the message.

        Returns:
            MessageRecord if found, None otherwise.
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM messages WHERE message_hash = ?", (message_hash,))
            row = cursor.fetchone()
            return MessageRecord.from_row(row) if row else None

    def message_exists(self, message: MessageRecord) -> bool:
        """
        Check if a message already exists (by hash).

        Args:
            message: MessageRecord to check.

        Returns:
            True if message exists, False otherwise.
        """
        msg_hash = message.message_hash or message.compute_hash()
        existing = self.get_message_by_hash(msg_hash)
        return existing is not None

    def get_next_ui_position(self, customer_id: int) -> int:
        """
        Get the next ui_position for a customer's messages.

        Args:
            customer_id: Customer ID.

        Returns:
            Next ui_position value (max + 1, or 1 if no messages).
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(ui_position) as max_pos FROM messages WHERE customer_id = ?", (customer_id,))
            row = cursor.fetchone()
            max_pos = row["max_pos"] if row and row["max_pos"] is not None else 0
            return max_pos + 1

    @retry_on_db_lock(max_retries=3)
    def create_message(self, message: MessageRecord) -> MessageRecord:
        """
        Create a new message record.

        Args:
            message: MessageRecord to create.

        Returns:
            Created MessageRecord with ID populated.

        Raises:
            sqlite3.IntegrityError: If message hash already exists.
        """
        with self._transaction() as (conn, cursor):
            data = message.to_dict()

            # Auto-assign ui_position if not provided
            if data.get("ui_position") is None:
                cursor.execute(
                    "SELECT MAX(ui_position) as max_pos FROM messages WHERE customer_id = ?", (data["customer_id"],)
                )
                row = cursor.fetchone()
                max_pos = row["max_pos"] if row and row["max_pos"] is not None else 0
                data["ui_position"] = max_pos + 1
                message.ui_position = data["ui_position"]

            cursor.execute(
                """
                INSERT INTO messages (
                    customer_id, content, message_type, is_from_kefu,
                    timestamp_raw, timestamp_parsed, extra_info, message_hash, ui_position
                )
                VALUES (
                    :customer_id, :content, :message_type, :is_from_kefu,
                    :timestamp_raw, :timestamp_parsed, :extra_info, :message_hash, :ui_position
                )
                """,
                data,
            )
            message.id = cursor.lastrowid

            if not data["is_from_kefu"] and str(data["message_type"]).lower() in {"image", "photo", "video"}:
                logical_ts = data.get("timestamp_parsed") or datetime.now().isoformat()
                cursor.execute(
                    """
                    UPDATE customers
                    SET
                        first_customer_media_at = CASE
                            WHEN first_customer_media_at IS NULL THEN ?
                            WHEN first_customer_media_at > ? THEN ?
                            ELSE first_customer_media_at
                        END,
                        has_customer_media = 1
                    WHERE id = ?
                    """,
                    (logical_ts, logical_ts, logical_ts, data["customer_id"]),
                )

            return message

    @retry_on_db_lock(max_retries=3)
    @retry_on_db_lock(max_retries=3)
    def add_message_if_not_exists(self, message: MessageRecord) -> tuple[bool, MessageRecord]:
        """
        Add a message only if it doesn't already exist.

        This is the primary method for adding messages with deduplication.

        Args:
            message: MessageRecord to add.

        Returns:
            Tuple of (was_added, message_record).
            was_added is True if new, False if duplicate.
        """
        msg_hash = message.message_hash or message.compute_hash()
        message.message_hash = msg_hash

        existing = self.get_message_by_hash(msg_hash)
        if existing:
            return False, existing

        try:
            created = self.create_message(message)
            return True, created
        except sqlite3.IntegrityError:
            # Race condition: message was added between check and insert
            existing = self.get_message_by_hash(msg_hash)
            return False, existing

    def update_message_extra_info(self, message_id: int, updates: dict) -> bool:
        """
        Update the extra_info field of a message by merging with existing data.

        This is used to add voice/image/video file paths after they're downloaded.

        Args:
            message_id: Database ID of the message
            updates: Dictionary of fields to add/update in extra_info

        Returns:
            True if updated successfully, False otherwise
        """
        import json

        with self._connection() as conn:
            cursor = conn.cursor()

            # Get current extra_info
            cursor.execute("SELECT extra_info FROM messages WHERE id = ?", (message_id,))
            row = cursor.fetchone()
            if not row:
                return False

            # Parse existing extra_info
            current_extra = {}
            if row["extra_info"]:
                try:
                    current_extra = json.loads(row["extra_info"])
                except json.JSONDecodeError:
                    pass

            # Merge updates
            current_extra.update(updates)

            # Update in database
            cursor.execute("UPDATE messages SET extra_info = ? WHERE id = ?", (json.dumps(current_extra), message_id))
            conn.commit()

            return cursor.rowcount > 0

    def get_messages_for_customer(
        self,
        customer_id: int,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[MessageRecord]:
        """
        Get messages for a customer.

        Args:
            customer_id: Customer ID.
            limit: Maximum number of messages to return.
            offset: Number of messages to skip.

        Returns:
            List of MessageRecord ordered by ui_position (accurate conversation order).
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            # Order by ui_position for accurate context, fallback to id for older data
            query = """
                SELECT * FROM messages
                WHERE customer_id = ?
                ORDER BY COALESCE(ui_position, id) ASC
            """
            if limit:
                query += f" LIMIT {limit} OFFSET {offset}"

            cursor.execute(query, (customer_id,))
            return [MessageRecord.from_row(row) for row in cursor.fetchall()]

    def get_last_message_for_customer(
        self,
        customer_id: int,
    ) -> MessageRecord | None:
        """Get the most recent message for a customer."""
        with self._connection() as conn:
            cursor = conn.cursor()
            # Order by ui_position for accurate ordering, fallback to id
            cursor.execute(
                """
                SELECT * FROM messages
                WHERE customer_id = ?
                ORDER BY COALESCE(ui_position, id) DESC
                LIMIT 1
                """,
                (customer_id,),
            )
            row = cursor.fetchone()
            return MessageRecord.from_row(row) if row else None

    def check_kefu_message_exists(
        self,
        customer_id: int,
        content: str,
        message_type: str = "text",
    ) -> bool:
        """
        检查是否已存在相同内容的客服消息。

        用于解决重复同步时，客服消息被重复写入的问题。
        只检查 is_from_kefu=1 的消息。

        Args:
            customer_id: 客户ID
            content: 消息内容
            message_type: 消息类型，默认 "text"

        Returns:
            True 如果已存在相同内容的客服消息
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT 1 FROM messages
                WHERE customer_id = ?
                    AND content = ?
                    AND is_from_kefu = 1
                    AND message_type = ?
                LIMIT 1
                """,
                (customer_id, content, message_type),
            )
            return cursor.fetchone() is not None

    def count_messages_for_customer(self, customer_id: int) -> int:
        """Count messages for a customer."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM messages WHERE customer_id = ?", (customer_id,))
            return cursor.fetchone()["count"]

    def count_messages_by_type(
        self,
        customer_id: int,
    ) -> dict[str, int]:
        """Get message count by type for a customer."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT message_type, COUNT(*) as count
                FROM messages
                WHERE customer_id = ?
                GROUP BY message_type
                """,
                (customer_id,),
            )
            return {row["message_type"]: row["count"] for row in cursor.fetchall()}

    def get_recent_messages_for_customer(
        self,
        customer_id: int,
        limit: int = 10,
    ) -> list[MessageRecord]:
        """
        Get the most recent N messages for a customer (for AI context).

        Messages are ordered by time (oldest first) to maintain conversation flow.

        Args:
            customer_id: Customer ID.
            limit: Maximum number of messages to return.

        Returns:
            List of MessageRecord ordered by time (oldest first for chat context).
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            # Get recent N messages in reverse, then reorder to ascending
            # This maintains conversation order (oldest first)
            query = """
                SELECT * FROM (
                    SELECT * FROM messages
                    WHERE customer_id = ?
                    ORDER BY COALESCE(ui_position, id) DESC
                    LIMIT ?
                ) subquery
                ORDER BY COALESCE(ui_position, id) ASC
            """
            cursor.execute(query, (customer_id, limit))
            return [MessageRecord.from_row(row) for row in cursor.fetchall()]

    # =========================================================================
    # Image Operations
    # =========================================================================

    def create_image(self, image: ImageRecord) -> ImageRecord:
        """
        Create or update the image record for a message.

        Args:
            image: ImageRecord to create.

        Returns:
            Stored ImageRecord with ID populated.
        """
        with self._transaction() as (conn, cursor):
            cursor.execute(
                "SELECT id FROM images WHERE message_id = ? ORDER BY id DESC LIMIT 1",
                (image.message_id,),
            )
            existing = cursor.fetchone()
            data = image.to_dict()

            if existing:
                cursor.execute(
                    """
                    UPDATE images
                    SET
                        file_path = :file_path,
                        file_name = :file_name,
                        original_bounds = :original_bounds,
                        width = :width,
                        height = :height,
                        file_size = :file_size
                    WHERE id = :id
                    """,
                    {
                        **data,
                        "id": existing["id"],
                    },
                )
                image.id = existing["id"]
            else:
                cursor.execute(
                    """
                    INSERT INTO images (
                        message_id, file_path, file_name, original_bounds,
                        width, height, file_size
                    )
                    VALUES (
                        :message_id, :file_path, :file_name, :original_bounds,
                        :width, :height, :file_size
                    )
                    """,
                    data,
                )
                image.id = cursor.lastrowid

            cursor.execute(
                """
                UPDATE customers
                SET
                    first_customer_media_at = CASE
                        WHEN first_customer_media_at IS NULL THEN (
                            SELECT COALESCE(m.timestamp_parsed, m.created_at)
                            FROM messages m
                            WHERE m.id = ?
                              AND m.is_from_kefu = 0
                            LIMIT 1
                        )
                        WHEN first_customer_media_at > (
                            SELECT COALESCE(m.timestamp_parsed, m.created_at)
                            FROM messages m
                            WHERE m.id = ?
                              AND m.is_from_kefu = 0
                            LIMIT 1
                        ) THEN (
                            SELECT COALESCE(m.timestamp_parsed, m.created_at)
                            FROM messages m
                            WHERE m.id = ?
                              AND m.is_from_kefu = 0
                            LIMIT 1
                        )
                        ELSE first_customer_media_at
                    END,
                    has_customer_media = CASE
                        WHEN EXISTS(
                            SELECT 1 FROM messages m
                            WHERE m.id = ?
                              AND m.is_from_kefu = 0
                        ) THEN 1
                        ELSE has_customer_media
                    END
                WHERE id = (
                    SELECT m.customer_id FROM messages m WHERE m.id = ? LIMIT 1
                )
                """,
                (image.message_id, image.message_id, image.message_id, image.message_id, image.message_id),
            )

            return image

    def update_image_review_by_message_id(
        self,
        message_id: int,
        *,
        review_external_id: str | None = None,
        ai_review_score: float | None = None,
        ai_review_model: str | None = None,
        ai_review_decision: str | None = None,
        ai_review_details_json: str | None = None,
        ai_review_at: str | None = None,
        ai_review_status: str | None = None,
        ai_review_error: str | None = None,
        ai_review_requested_at: str | None = None,
    ) -> bool:
        """
        Persist AI review fields for the image row linked to a message.

        Only non-None keyword arguments are written. Returns True if a row was updated.
        """
        fields: list[str] = []
        values: list[Any] = []
        if review_external_id is not None:
            fields.append("review_external_id = ?")
            values.append(review_external_id)
        if ai_review_score is not None:
            fields.append("ai_review_score = ?")
            values.append(ai_review_score)
        if ai_review_model is not None:
            fields.append("ai_review_model = ?")
            values.append(ai_review_model)
        if ai_review_decision is not None:
            fields.append("ai_review_decision = ?")
            values.append(ai_review_decision)
        if ai_review_details_json is not None:
            fields.append("ai_review_details_json = ?")
            values.append(ai_review_details_json)
        if ai_review_at is not None:
            fields.append("ai_review_at = ?")
            values.append(ai_review_at)
        if ai_review_status is not None:
            fields.append("ai_review_status = ?")
            values.append(ai_review_status)
        if ai_review_error is not None:
            fields.append("ai_review_error = ?")
            values.append(ai_review_error)
        if ai_review_requested_at is not None:
            fields.append("ai_review_requested_at = ?")
            values.append(ai_review_requested_at)
        if not fields:
            return False
        values.append(message_id)
        with self._transaction() as (conn, cursor):
            cursor.execute(
                f"UPDATE images SET {', '.join(fields)} WHERE message_id = ?",
                values,
            )
            return cursor.rowcount > 0

    def get_message_review_context(self, message_id: int) -> dict[str, Any] | None:
        """Return customer context for a stored message review update."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    c.id AS customer_id,
                    c.name AS customer_name,
                    c.channel AS channel,
                    d.serial AS device_serial
                FROM messages m
                JOIN customers c ON c.id = m.customer_id
                JOIN kefus k ON k.id = c.kefu_id
                JOIN kefu_devices kd ON kd.kefu_id = k.id
                JOIN devices d ON d.id = kd.device_id
                WHERE m.id = ?
                LIMIT 1
                """,
                (message_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "customer_id": row["customer_id"],
                "customer_name": row["customer_name"],
                "channel": row["channel"],
                "device_serial": row["device_serial"],
            }

    def get_image_for_message(self, message_id: int) -> ImageRecord | None:
        """Get image record for a message."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM images WHERE message_id = ?", (message_id,))
            row = cursor.fetchone()
            return ImageRecord.from_row(row) if row else None

    def list_images_for_customer(self, customer_id: int) -> list[ImageRecord]:
        """List all images for a customer's conversation."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT i.* FROM images i
                JOIN messages m ON i.message_id = m.id
                WHERE m.customer_id = ?
                ORDER BY i.created_at ASC
                """,
                (customer_id,),
            )
            return [ImageRecord.from_row(row) for row in cursor.fetchall()]

    # =========================================================================
    # Video Operations
    # =========================================================================

    def create_video(self, video: VideoRecord) -> VideoRecord:
        """
        Create a new video record.

        Args:
            video: VideoRecord to create.

        Returns:
            Created VideoRecord with ID populated.
        """
        with self._transaction() as (conn, cursor):
            data = video.to_dict()
            cursor.execute(
                """
                INSERT INTO videos (
                    message_id, file_path, file_name, duration,
                    duration_seconds, thumbnail_path, width, height, file_size
                )
                VALUES (
                    :message_id, :file_path, :file_name, :duration,
                    :duration_seconds, :thumbnail_path, :width, :height, :file_size
                )
                """,
                data,
            )
            video.id = cursor.lastrowid

            cursor.execute(
                """
                UPDATE customers
                SET
                    first_customer_media_at = CASE
                        WHEN first_customer_media_at IS NULL THEN (
                            SELECT COALESCE(m.timestamp_parsed, m.created_at)
                            FROM messages m
                            WHERE m.id = ?
                              AND m.is_from_kefu = 0
                            LIMIT 1
                        )
                        WHEN first_customer_media_at > (
                            SELECT COALESCE(m.timestamp_parsed, m.created_at)
                            FROM messages m
                            WHERE m.id = ?
                              AND m.is_from_kefu = 0
                            LIMIT 1
                        ) THEN (
                            SELECT COALESCE(m.timestamp_parsed, m.created_at)
                            FROM messages m
                            WHERE m.id = ?
                              AND m.is_from_kefu = 0
                            LIMIT 1
                        )
                        ELSE first_customer_media_at
                    END,
                    has_customer_media = CASE
                        WHEN EXISTS(
                            SELECT 1 FROM messages m
                            WHERE m.id = ?
                              AND m.is_from_kefu = 0
                        ) THEN 1
                        ELSE has_customer_media
                    END
                WHERE id = (
                    SELECT m.customer_id FROM messages m WHERE m.id = ? LIMIT 1
                )
                """,
                (video.message_id, video.message_id, video.message_id, video.message_id, video.message_id),
            )
            return video

    def get_video_for_message(self, message_id: int) -> VideoRecord | None:
        """Get video record for a message."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM videos WHERE message_id = ?", (message_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return VideoRecord.from_row(row)

    def update_video_review_by_message_id(
        self,
        message_id: int,
        *,
        ai_review_score: float | None = None,
        ai_review_frames_json: str | None = None,
        ai_review_at: str | None = None,
        ai_review_status: str | None = None,
        ai_review_error: str | None = None,
        ai_review_requested_at: str | None = None,
    ) -> bool:
        """
        Persist AI review fields on the video row linked to a message.

        Only non-None keyword arguments are written. Returns True if a row was updated.
        """
        fields: list[str] = []
        values: list[Any] = []
        if ai_review_score is not None:
            fields.append("ai_review_score = ?")
            values.append(ai_review_score)
        if ai_review_frames_json is not None:
            fields.append("ai_review_frames_json = ?")
            values.append(ai_review_frames_json)
        if ai_review_at is not None:
            fields.append("ai_review_at = ?")
            values.append(ai_review_at)
        if ai_review_status is not None:
            fields.append("ai_review_status = ?")
            values.append(ai_review_status)
        if ai_review_error is not None:
            fields.append("ai_review_error = ?")
            values.append(ai_review_error)
        if ai_review_requested_at is not None:
            fields.append("ai_review_requested_at = ?")
            values.append(ai_review_requested_at)
        if not fields:
            return False
        values.append(message_id)
        with self._transaction() as (conn, cursor):
            cursor.execute(
                f"UPDATE videos SET {', '.join(fields)} WHERE message_id = ?",
                values,
            )
            return cursor.rowcount > 0

    def list_videos_for_customer(self, customer_id: int) -> list[VideoRecord]:
        """List all videos for a customer's conversation."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT v.* FROM videos v
                JOIN messages m ON v.message_id = m.id
                WHERE m.customer_id = ?
                ORDER BY v.created_at ASC
                """,
                (customer_id,),
            )
            return [VideoRecord.from_row(row) for row in cursor.fetchall()]

    # =========================================================================
    # Voice Operations
    # =========================================================================

    def create_voice(self, voice: VoiceRecord) -> VoiceRecord:
        """
        Create a new voice record.

        Args:
            voice: VoiceRecord to create.

        Returns:
            Created VoiceRecord with ID populated.
        """
        with self._transaction() as (conn, cursor):
            data = voice.to_dict()
            cursor.execute(
                """
                INSERT INTO voices (
                    message_id, file_path, file_name, duration,
                    duration_seconds, file_size
                )
                VALUES (
                    :message_id, :file_path, :file_name, :duration,
                    :duration_seconds, :file_size
                )
                """,
                data,
            )
            voice.id = cursor.lastrowid
            return voice

    def get_voice_for_message(self, message_id: int) -> VoiceRecord | None:
        """Get voice record for a message."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM voices WHERE message_id = ?", (message_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return VoiceRecord.from_row(row)

    def list_voices_for_customer(self, customer_id: int) -> list[VoiceRecord]:
        """List all voice files for a customer's conversation."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT v.* FROM voices v
                JOIN messages m ON v.message_id = m.id
                WHERE m.customer_id = ?
                ORDER BY v.created_at ASC
                """,
                (customer_id,),
            )
            return [VoiceRecord.from_row(row) for row in cursor.fetchall()]

    # =========================================================================
    # Bulk Operations
    # =========================================================================

    def add_messages_batch(
        self,
        messages: list[MessageRecord],
    ) -> tuple[int, int]:
        """
        Add multiple messages with deduplication.

        Args:
            messages: List of MessageRecord to add.

        Returns:
            Tuple of (added_count, skipped_count).
        """
        added = 0
        skipped = 0

        for message in messages:
            was_added, _ = self.add_message_if_not_exists(message)
            if was_added:
                added += 1
            else:
                skipped += 1

        return added, skipped

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_statistics(self) -> dict:
        """Get overall database statistics."""
        with self._connection() as conn:
            cursor = conn.cursor()

            stats = {}

            cursor.execute("SELECT COUNT(*) as count FROM devices")
            stats["devices"] = cursor.fetchone()["count"]

            cursor.execute("SELECT COUNT(*) as count FROM kefus")
            stats["kefus"] = cursor.fetchone()["count"]

            cursor.execute("SELECT COUNT(*) as count FROM customers")
            stats["customers"] = cursor.fetchone()["count"]

            cursor.execute("SELECT COUNT(*) as count FROM messages")
            stats["messages"] = cursor.fetchone()["count"]

            cursor.execute("SELECT COUNT(*) as count FROM images")
            stats["images"] = cursor.fetchone()["count"]

            # Check if videos table exists and count videos
            try:
                cursor.execute("SELECT COUNT(*) as count FROM videos")
                stats["videos"] = cursor.fetchone()["count"]
            except Exception:
                stats["videos"] = 0

            try:
                cursor.execute("SELECT COUNT(*) as count FROM voices")
                stats["voices"] = cursor.fetchone()["count"]
            except Exception:
                stats["voices"] = 0

            # Messages by type
            cursor.execute(
                """
                SELECT message_type, COUNT(*) as count
                FROM messages
                GROUP BY message_type
                """
            )
            stats["messages_by_type"] = {row["message_type"]: row["count"] for row in cursor.fetchall()}

            return stats
