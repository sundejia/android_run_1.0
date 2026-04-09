"""
Database schema definitions and initialization for WeCom Automation.

This module handles:
- SQLite database creation
- Schema migrations
- Connection management
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Import centralized config for PROJECT_ROOT and DB_PATH
from wecom_automation.core.config import (
    PROJECT_ROOT,
    get_default_db_path,
)
from wecom_automation.core.performance import InstrumentedConnection

# Database version for migrations
DATABASE_VERSION = 13

# Re-export for backward compatibility
# Note: DEFAULT_DB_PATH is now a Path object, not string
DEFAULT_DB_PATH = "wecom_conversations.db"  # Keep as string for legacy code

BLACKLIST_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS blacklist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_serial TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    customer_channel TEXT,
    reason TEXT,
    deleted_by_user BOOLEAN DEFAULT 0,  -- True if user deleted/blocked us
    is_blacklisted BOOLEAN DEFAULT 1,   -- 1 = blocked, 0 = allowed
    avatar_url TEXT,
    customer_db_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(device_serial, customer_name, customer_channel)
);
"""

BLACKLIST_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_blacklist_device ON blacklist(device_serial);
CREATE INDEX IF NOT EXISTS idx_blacklist_name ON blacklist(customer_name);
"""

BLACKLIST_TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS update_blacklist_timestamp
AFTER UPDATE ON blacklist
BEGIN
    UPDATE blacklist SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
"""

BLACKLIST_COLUMN_REPAIRS: tuple[tuple[str, str], ...] = (
    ("deleted_by_user", "ALTER TABLE blacklist ADD COLUMN deleted_by_user BOOLEAN DEFAULT 0"),
    ("is_blacklisted", "ALTER TABLE blacklist ADD COLUMN is_blacklisted BOOLEAN DEFAULT 1"),
    ("avatar_url", "ALTER TABLE blacklist ADD COLUMN avatar_url TEXT"),
    ("customer_db_id", "ALTER TABLE blacklist ADD COLUMN customer_db_id INTEGER"),
)

CUSTOMER_FACT_COLUMN_REPAIRS: tuple[tuple[str, str], ...] = (
    ("friend_added_at", "ALTER TABLE customers ADD COLUMN friend_added_at TEXT"),
    ("first_customer_media_at", "ALTER TABLE customers ADD COLUMN first_customer_media_at TEXT"),
    ("has_customer_media", "ALTER TABLE customers ADD COLUMN has_customer_media BOOLEAN DEFAULT 0"),
)

# Runtime-required columns on videos for multi-frame AI review (v12+)
VIDEOS_AI_REVIEW_COLUMN_REPAIRS: tuple[tuple[str, str], ...] = (
    ("ai_review_score", "ALTER TABLE videos ADD COLUMN ai_review_score REAL"),
    ("ai_review_frames_json", "ALTER TABLE videos ADD COLUMN ai_review_frames_json TEXT"),
    ("ai_review_at", "ALTER TABLE videos ADD COLUMN ai_review_at TEXT"),
    ("ai_review_status", "ALTER TABLE videos ADD COLUMN ai_review_status TEXT"),
    ("ai_review_error", "ALTER TABLE videos ADD COLUMN ai_review_error TEXT"),
    ("ai_review_requested_at", "ALTER TABLE videos ADD COLUMN ai_review_requested_at TEXT"),
)

# SQL schema definition
SCHEMA_SQL = f"""
-- Enable foreign keys
PRAGMA foreign_keys = ON;

-- Devices table: tracks connected Android devices
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    serial TEXT UNIQUE NOT NULL,
    model TEXT,
    manufacturer TEXT,
    android_version TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Kefus table: customer service representatives (identified by name + department)
CREATE TABLE IF NOT EXISTS kefus (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    department TEXT,
    verification_status TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, department)
);

-- Kefu-Device junction table: tracks which devices a kefu has used
CREATE TABLE IF NOT EXISTS kefu_devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kefu_id INTEGER NOT NULL REFERENCES kefus(id) ON DELETE CASCADE,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(kefu_id, device_id)
);

-- Customers table: contacts in private chats
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    channel TEXT,  -- e.g., @WeChat, @微信
    kefu_id INTEGER NOT NULL REFERENCES kefus(id) ON DELETE CASCADE,
    last_message_preview TEXT,
    last_message_date TEXT,
    friend_added_at TEXT,  -- First detected true new-friend time
    first_customer_media_at TEXT,  -- First customer-side image/video time
    has_customer_media BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, channel, kefu_id)
);

-- Messages table: all conversation messages
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    content TEXT,
    message_type TEXT NOT NULL DEFAULT 'text',  -- text, voice, image, file, system, video, link, etc.
    is_from_kefu BOOLEAN NOT NULL DEFAULT 0,
    timestamp_raw TEXT,  -- Original timestamp from UI (e.g., "10:30", "Yesterday")
    timestamp_parsed TIMESTAMP,  -- Parsed timestamp if available
    extra_info TEXT,  -- JSON for additional metadata (voice captions, duration, etc.)
    message_hash TEXT UNIQUE NOT NULL,  -- SHA256 hash for deduplication
    ui_position INTEGER,  -- Position in UI extraction order (for accurate context ordering)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Images table: stores image message files
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    file_name TEXT,
    original_bounds TEXT,  -- UI bounds when captured
    width INTEGER,
    height INTEGER,
    file_size INTEGER,
    review_external_id TEXT,
    ai_review_score REAL,
    ai_review_model TEXT,
    ai_review_decision TEXT,
    ai_review_details_json TEXT,
    ai_review_at TEXT,
    ai_review_status TEXT,
    ai_review_error TEXT,
    ai_review_requested_at TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Videos table: stores video message files
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    file_name TEXT,
    duration TEXT,  -- Duration string (e.g., "00:45", "1:23")
    duration_seconds INTEGER,  -- Duration in seconds for sorting/filtering
    thumbnail_path TEXT,  -- Path to video thumbnail image
    width INTEGER,
    height INTEGER,
    file_size INTEGER,
    ai_review_score REAL,
    ai_review_frames_json TEXT,
    ai_review_at TEXT,
    ai_review_status TEXT,
    ai_review_error TEXT,
    ai_review_requested_at TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Voices table: stores voice message audio files
CREATE TABLE IF NOT EXISTS voices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    file_name TEXT,
    duration TEXT,
    duration_seconds INTEGER,
    file_size INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Blacklist table: users to skip during sync/followup
{BLACKLIST_TABLE_SQL}

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_messages_customer_id ON messages(customer_id);
CREATE INDEX IF NOT EXISTS idx_messages_hash ON messages(message_hash);
CREATE INDEX IF NOT EXISTS idx_messages_type ON messages(message_type);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp_parsed);
CREATE INDEX IF NOT EXISTS idx_messages_ui_position ON messages(customer_id, ui_position);
CREATE INDEX IF NOT EXISTS idx_customers_kefu_id ON customers(kefu_id);
CREATE INDEX IF NOT EXISTS idx_customers_friend_added_at ON customers(friend_added_at);
CREATE INDEX IF NOT EXISTS idx_customers_first_customer_media_at ON customers(first_customer_media_at);
CREATE INDEX IF NOT EXISTS idx_customers_has_customer_media ON customers(has_customer_media);
CREATE INDEX IF NOT EXISTS idx_kefu_devices_kefu_id ON kefu_devices(kefu_id);
CREATE INDEX IF NOT EXISTS idx_kefu_devices_device_id ON kefu_devices(device_id);
CREATE INDEX IF NOT EXISTS idx_images_message_id ON images(message_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_images_message_id_unique ON images(message_id);
CREATE INDEX IF NOT EXISTS idx_videos_message_id ON videos(message_id);
CREATE INDEX IF NOT EXISTS idx_voices_message_id ON voices(message_id);
{BLACKLIST_INDEXES_SQL}
"""

# Triggers for updated_at timestamps
TRIGGERS_SQL = f"""
-- Trigger for devices updated_at
CREATE TRIGGER IF NOT EXISTS update_devices_timestamp
AFTER UPDATE ON devices
BEGIN
    UPDATE devices SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

-- Trigger for kefus updated_at
CREATE TRIGGER IF NOT EXISTS update_kefus_timestamp
AFTER UPDATE ON kefus
BEGIN
    UPDATE kefus SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

-- Trigger for customers updated_at
CREATE TRIGGER IF NOT EXISTS update_customers_timestamp
AFTER UPDATE ON customers
BEGIN
    UPDATE customers SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

-- Trigger for kefu_devices updated_at
CREATE TRIGGER IF NOT EXISTS update_kefu_devices_timestamp
AFTER UPDATE ON kefu_devices
BEGIN
    UPDATE kefu_devices SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

-- Trigger for blacklist updated_at
{BLACKLIST_TRIGGER_SQL}
"""

# Migration from v1 to v2: consolidate kefus by name+department
MIGRATION_V1_TO_V2 = """
-- Step 1: Create the new kefu_devices junction table
CREATE TABLE IF NOT EXISTS kefu_devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kefu_id INTEGER NOT NULL REFERENCES kefus(id) ON DELETE CASCADE,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(kefu_id, device_id)
);

-- Step 2: Create indexes for kefu_devices
CREATE INDEX IF NOT EXISTS idx_kefu_devices_kefu_id ON kefu_devices(kefu_id);
CREATE INDEX IF NOT EXISTS idx_kefu_devices_device_id ON kefu_devices(device_id);
"""


def get_db_path(db_path: str | None = None) -> Path:
    """
    Get the database file path with sensible fallbacks.

    Resolution order:
    1) Explicit db_path argument
    2) WECOM_DB_PATH environment variable (via get_default_db_path)
    3) Project root / wecom_conversations.db

    Note: This function uses the centralized config from core.config
    """
    if db_path:
        return Path(db_path).expanduser().resolve()

    # Use centralized config which handles env vars
    return get_default_db_path()


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """
    Get a database connection with proper settings.

    Args:
        db_path: Optional custom database path.

    Returns:
        SQLite connection with WAL mode, busy_timeout, and foreign keys enabled.
    """
    path = get_db_path(db_path)
    conn = sqlite3.connect(str(path), factory=InstrumentedConnection)
    conn.row_factory = sqlite3.Row

    # Enable foreign key constraints
    conn.execute("PRAGMA foreign_keys = ON")

    # Enable WAL mode for better concurrent read/write performance
    # This allows multiple readers and one writer to work simultaneously
    conn.execute("PRAGMA journal_mode = WAL")

    # Set busy_timeout to 30 seconds - wait instead of failing immediately
    # when database is locked by another process
    conn.execute("PRAGMA busy_timeout = 30000")

    # Use NORMAL synchronous mode for balance between performance and safety
    conn.execute("PRAGMA synchronous = NORMAL")

    return conn


def init_database(db_path: str | None = None, force_recreate: bool = False) -> Path:
    """
    Initialize the database with schema.

    Args:
        db_path: Optional custom database path.
        force_recreate: If True, drop and recreate all tables.

    Returns:
        Path to the initialized database.
    """
    path = get_db_path(db_path)

    # Create parent directories if needed
    path.parent.mkdir(parents=True, exist_ok=True)

    if force_recreate and path.exists():
        path.unlink()

    conn = get_connection(str(path))
    cursor = conn.cursor()

    try:
        # Execute schema creation
        cursor.executescript(SCHEMA_SQL)

        # Execute triggers
        cursor.executescript(TRIGGERS_SQL)

        # Record schema version
        cursor.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (DATABASE_VERSION,))

        conn.commit()

    finally:
        conn.close()

    return path


def _table_exists(cursor: sqlite3.Cursor, table_name: str) -> bool:
    """Return True when the given table exists."""
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    )
    return cursor.fetchone() is not None


def _get_table_columns(cursor: sqlite3.Cursor, table_name: str) -> set[str]:
    """Return the set of column names for a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row["name"] for row in cursor.fetchall()}


def _has_blacklist_duplicate_identities_with_cursor(cursor: sqlite3.Cursor) -> bool:
    """Return True when blacklist has duplicate rows for the same logical customer."""
    if not _table_exists(cursor, "blacklist"):
        return False

    cursor.execute(
        """
        SELECT 1
        FROM blacklist
        GROUP BY device_serial, customer_name
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    )
    return cursor.fetchone() is not None


def _merge_blacklist_duplicate_identities_with_cursor(cursor: sqlite3.Cursor) -> int:
    """
    Merge duplicate blacklist rows by logical identity.

    Blacklist business identity is `device_serial + customer_name`. Historical
    rows may still exist per channel variant; this repair converges them to a
    single row while preserving the most recent non-empty metadata.
    """
    if not _table_exists(cursor, "blacklist"):
        return 0

    cursor.execute(
        """
        SELECT device_serial, customer_name
        FROM blacklist
        GROUP BY device_serial, customer_name
        HAVING COUNT(*) > 1
        """
    )
    duplicate_groups = cursor.fetchall()

    merged_groups = 0
    for group in duplicate_groups:
        cursor.execute(
            """
            SELECT *
            FROM blacklist
            WHERE device_serial = ? AND customer_name = ?
            ORDER BY COALESCE(updated_at, created_at) DESC,
                     COALESCE(created_at, updated_at) DESC,
                     id DESC
            """,
            (group["device_serial"], group["customer_name"]),
        )
        rows = cursor.fetchall()
        if len(rows) <= 1:
            continue

        canonical_row = rows[0]
        duplicate_ids = [(row["id"],) for row in rows[1:]]

        def _latest_non_empty(column_name: str):
            for row in rows:
                value = row[column_name]
                if value not in (None, ""):
                    return value
            return None

        merged_channel = _latest_non_empty("customer_channel")
        merged_reason = _latest_non_empty("reason")
        merged_avatar_url = _latest_non_empty("avatar_url")
        merged_customer_db_id = _latest_non_empty("customer_db_id")
        merged_is_blacklisted = 1 if any(bool(row["is_blacklisted"]) for row in rows) else 0
        merged_deleted_by_user = 1 if any(bool(row["deleted_by_user"]) for row in rows) else 0

        cursor.execute(
            """
            UPDATE blacklist
            SET customer_channel = ?,
                reason = ?,
                deleted_by_user = ?,
                is_blacklisted = ?,
                avatar_url = ?,
                customer_db_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                merged_channel,
                merged_reason,
                merged_deleted_by_user,
                merged_is_blacklisted,
                merged_avatar_url,
                merged_customer_db_id,
                canonical_row["id"],
            ),
        )

        cursor.executemany("DELETE FROM blacklist WHERE id = ?", duplicate_ids)
        merged_groups += 1

    return merged_groups


def _repair_blacklist_schema_with_cursor(cursor: sqlite3.Cursor) -> list[str]:
    """Repair blacklist schema drift without relying on schema_version."""
    repairs: list[str] = []

    if not _table_exists(cursor, "blacklist"):
        cursor.executescript(BLACKLIST_TABLE_SQL)
        repairs.append("created blacklist table")

    columns = _get_table_columns(cursor, "blacklist")
    for column_name, alter_sql in BLACKLIST_COLUMN_REPAIRS:
        if column_name not in columns:
            cursor.execute(alter_sql)
            columns.add(column_name)
            repairs.append(f"added blacklist.{column_name}")

    cursor.executescript(BLACKLIST_INDEXES_SQL)
    cursor.executescript(BLACKLIST_TRIGGER_SQL)

    if "deleted_by_user" in columns:
        cursor.execute("UPDATE blacklist SET deleted_by_user = 0 WHERE deleted_by_user IS NULL")
        if cursor.rowcount > 0:
            repairs.append("backfilled blacklist.deleted_by_user")

    if "is_blacklisted" in columns:
        cursor.execute("UPDATE blacklist SET is_blacklisted = 1 WHERE is_blacklisted IS NULL")
        if cursor.rowcount > 0:
            repairs.append("backfilled blacklist.is_blacklisted")

    merged_duplicate_groups = _merge_blacklist_duplicate_identities_with_cursor(cursor)
    if merged_duplicate_groups > 0:
        repairs.append(f"merged blacklist duplicate identities ({merged_duplicate_groups} groups)")

    return repairs


def _repair_customer_fact_schema_with_cursor(cursor: sqlite3.Cursor) -> list[str]:
    """Repair customer fact columns and backfill media facts when possible."""
    repairs: list[str] = []

    if not _table_exists(cursor, "customers"):
        return repairs

    columns = _get_table_columns(cursor, "customers")
    for column_name, alter_sql in CUSTOMER_FACT_COLUMN_REPAIRS:
        if column_name not in columns:
            cursor.execute(alter_sql)
            columns.add(column_name)
            repairs.append(f"added customers.{column_name}")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_customers_friend_added_at ON customers(friend_added_at)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_customers_first_customer_media_at ON customers(first_customer_media_at)"
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_customers_has_customer_media ON customers(has_customer_media)")

    if "first_customer_media_at" in columns and _table_exists(cursor, "messages"):
        message_columns = _get_table_columns(cursor, "messages")
        timestamp_expr = "m.created_at"
        if "timestamp_parsed" in message_columns:
            timestamp_expr = "COALESCE(m.timestamp_parsed, m.created_at)"

        joins: list[str] = []
        media_parts = ["LOWER(COALESCE(m.message_type, '')) IN ('image', 'photo', 'video')"]
        if _table_exists(cursor, "images"):
            joins.append("LEFT JOIN images i ON i.message_id = m.id")
            media_parts.append("i.id IS NOT NULL")
        if _table_exists(cursor, "videos"):
            joins.append("LEFT JOIN videos v ON v.message_id = m.id")
            media_parts.append("v.id IS NOT NULL")

        join_sql = "\n                ".join(joins)
        media_predicate = " OR ".join(media_parts)
        cursor.execute(
            f"""
            UPDATE customers
            SET first_customer_media_at = (
                SELECT MIN({timestamp_expr})
                FROM messages m
                {join_sql}
                WHERE m.customer_id = customers.id
                  AND m.is_from_kefu = 0
                  AND ({media_predicate})
            )
            WHERE first_customer_media_at IS NULL
            """
        )
        if cursor.rowcount > 0:
            repairs.append("backfilled customers.first_customer_media_at")

    if "has_customer_media" in columns:
        cursor.execute(
            """
            UPDATE customers
            SET has_customer_media = CASE
                WHEN first_customer_media_at IS NOT NULL THEN 1
                ELSE 0
            END
            WHERE has_customer_media IS NULL
               OR has_customer_media != CASE
                    WHEN first_customer_media_at IS NOT NULL THEN 1
                    ELSE 0
               END
            """
        )
        if cursor.rowcount > 0:
            repairs.append("backfilled customers.has_customer_media")

    return repairs


def needs_blacklist_schema_repair(db_path: str | None = None) -> bool:
    """Return True when blacklist has schema drift or duplicate logical identities."""
    path = get_db_path(db_path)
    if not path.exists():
        return False

    conn = get_connection(str(path))
    cursor = conn.cursor()

    try:
        if not _table_exists(cursor, "blacklist"):
            return True

        columns = _get_table_columns(cursor, "blacklist")
        if any(column_name not in columns for column_name, _ in BLACKLIST_COLUMN_REPAIRS):
            return True

        cursor.execute(
            """
            SELECT 1
            FROM blacklist
            WHERE is_blacklisted IS NULL OR deleted_by_user IS NULL
            LIMIT 1
            """
        )
        if cursor.fetchone() is not None:
            return True

        return _has_blacklist_duplicate_identities_with_cursor(cursor)
    finally:
        conn.close()


def needs_customer_fact_schema_repair(db_path: str | None = None) -> bool:
    """Return True when customer fact columns are missing or stale."""
    path = get_db_path(db_path)
    if not path.exists():
        return False

    conn = get_connection(str(path))
    cursor = conn.cursor()

    try:
        if not _table_exists(cursor, "customers"):
            return False

        columns = _get_table_columns(cursor, "customers")
        if any(column_name not in columns for column_name, _ in CUSTOMER_FACT_COLUMN_REPAIRS):
            return True

        if "has_customer_media" in columns and "first_customer_media_at" in columns:
            cursor.execute(
                """
                SELECT 1
                FROM customers
                WHERE has_customer_media IS NULL
                   OR has_customer_media != CASE
                        WHEN first_customer_media_at IS NOT NULL THEN 1
                        ELSE 0
                   END
                LIMIT 1
                """
            )
            return cursor.fetchone() is not None

        return False
    finally:
        conn.close()


def repair_customer_fact_schema(db_path: str | None = None) -> list[str]:
    """Repair customer fact schema drift for existing databases."""
    path = get_db_path(db_path)
    if not path.exists():
        return []

    conn = get_connection(str(path))
    cursor = conn.cursor()
    try:
        repairs = _repair_customer_fact_schema_with_cursor(cursor)
        conn.commit()
        return repairs
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def repair_blacklist_schema(db_path: str | None = None) -> list[str]:
    """Repair blacklist schema drift for existing databases."""
    path = get_db_path(db_path)
    if not path.exists():
        return []

    conn = get_connection(str(path))
    cursor = conn.cursor()

    try:
        repairs = _repair_blacklist_schema_with_cursor(cursor)
        conn.commit()
        return repairs
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _repair_videos_ai_review_schema_with_cursor(cursor: sqlite3.Cursor) -> list[str]:
    """Add missing videos AI review columns (idempotent)."""
    repairs: list[str] = []
    if not _table_exists(cursor, "videos"):
        return repairs
    columns = _get_table_columns(cursor, "videos")
    for column_name, alter_sql in VIDEOS_AI_REVIEW_COLUMN_REPAIRS:
        if column_name not in columns:
            cursor.execute(alter_sql)
            columns.add(column_name)
            repairs.append(f"added videos.{column_name}")
    return repairs


def repair_videos_ai_review_schema(db_path: str | None = None) -> list[str]:
    """Repair videos table when schema_version is current but AI review columns are missing."""
    path = get_db_path(db_path)
    if not path.exists():
        return []
    conn = get_connection(str(path))
    cursor = conn.cursor()
    try:
        repairs = _repair_videos_ai_review_schema_with_cursor(cursor)
        conn.commit()
        return repairs
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_schema_version(db_path: str | None = None) -> int | None:
    """
    Get the current schema version from the database.

    Args:
        db_path: Optional custom database path.

    Returns:
        Schema version number, or None if not initialized.
    """
    path = get_db_path(db_path)

    if not path.exists():
        return None

    conn = get_connection(str(path))
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        row = cursor.fetchone()
        return row["version"] if row else None
    except sqlite3.OperationalError:
        # Table doesn't exist
        return None
    finally:
        conn.close()


def needs_migration(db_path: str | None = None) -> bool:
    """
    Check if the database needs migration.

    Args:
        db_path: Optional custom database path.

    Returns:
        True if migration is needed.
    """
    current_version = get_schema_version(db_path)
    if current_version is None:
        return True
    return (
        current_version < DATABASE_VERSION
        or needs_blacklist_schema_repair(db_path)
        or needs_customer_fact_schema_repair(db_path)
    )


def migrate_v1_to_v2(db_path: str | None = None) -> None:
    """
    Migrate database from v1 to v2.

    This migration consolidates kefus that have the same name+department
    but different devices into a single kefu record, using a junction table
    to track the many-to-many relationship between kefus and devices.

    It also merges customers that have the same name+channel but were under
    different kefu records (now being merged), and merges their messages.

    Args:
        db_path: Optional custom database path.
    """
    path = get_db_path(db_path)
    conn = sqlite3.connect(str(path), factory=InstrumentedConnection)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # Disable foreign keys during migration
        cursor.execute("PRAGMA foreign_keys = OFF")

        # Step 1: Create kefu_devices junction table
        cursor.executescript(MIGRATION_V1_TO_V2)

        # Step 2: Find all unique (name, department) combinations and their kefu records
        cursor.execute("""
            SELECT name, department, GROUP_CONCAT(id) as kefu_ids, GROUP_CONCAT(device_id) as device_ids
            FROM kefus
            GROUP BY name, department
            HAVING COUNT(*) >= 1
        """)
        kefu_groups = cursor.fetchall()

        for group in kefu_groups:
            group["name"]
            group["department"]
            kefu_ids = [int(x) for x in group["kefu_ids"].split(",")]
            device_ids = [int(x) for x in group["device_ids"].split(",")]

            # Use the first kefu_id as the canonical one
            canonical_kefu_id = kefu_ids[0]

            # Insert kefu-device relationships
            for device_id in device_ids:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO kefu_devices (kefu_id, device_id)
                    VALUES (?, ?)
                """,
                    (canonical_kefu_id, device_id),
                )

            # Merge customers when consolidating kefus
            if len(kefu_ids) > 1:
                for old_kefu_id in kefu_ids[1:]:
                    # Find customers that would conflict (same name+channel)
                    cursor.execute(
                        """
                        SELECT c_old.id as old_id, c_old.name, c_old.channel, c_new.id as new_id
                        FROM customers c_old
                        JOIN customers c_new ON c_old.name = c_new.name
                            AND COALESCE(c_old.channel, '') = COALESCE(c_new.channel, '')
                        WHERE c_old.kefu_id = ? AND c_new.kefu_id = ?
                    """,
                        (old_kefu_id, canonical_kefu_id),
                    )

                    conflicting_customers = cursor.fetchall()

                    for conflict in conflicting_customers:
                        old_customer_id = conflict["old_id"]
                        new_customer_id = conflict["new_id"]

                        # Move messages from old customer to new customer
                        # Update the message hash to avoid conflicts
                        cursor.execute(
                            """
                            UPDATE messages
                            SET customer_id = ?,
                                message_hash = message_hash || '_migrated_' || ?
                            WHERE customer_id = ?
                        """,
                            (new_customer_id, old_customer_id, old_customer_id),
                        )

                        # Delete the old customer (messages already moved)
                        cursor.execute("DELETE FROM customers WHERE id = ?", (old_customer_id,))

                    # Update remaining customers (non-conflicting) to point to canonical kefu
                    cursor.execute(
                        """
                        UPDATE customers SET kefu_id = ? WHERE kefu_id = ?
                    """,
                        (canonical_kefu_id, old_kefu_id),
                    )

        # Step 3: Delete duplicate kefu records (keep only canonical ones)
        cursor.execute("""
            DELETE FROM kefus WHERE id NOT IN (
                SELECT MIN(id) FROM kefus GROUP BY name, department
            )
        """)

        # Step 4: Create new kefus table without device_id
        cursor.execute("""
            CREATE TABLE kefus_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                department TEXT,
                verification_status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, department)
            )
        """)

        # Step 5: Copy data to new table
        cursor.execute("""
            INSERT INTO kefus_new (id, name, department, verification_status, created_at, updated_at)
            SELECT id, name, department, verification_status, created_at, updated_at FROM kefus
        """)

        # Step 6: Drop old table and rename new one
        cursor.execute("DROP TABLE kefus")
        cursor.execute("ALTER TABLE kefus_new RENAME TO kefus")

        # Step 7: Recreate triggers
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS update_kefus_timestamp
            AFTER UPDATE ON kefus
            BEGIN
                UPDATE kefus SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS update_kefu_devices_timestamp
            AFTER UPDATE ON kefu_devices
            BEGIN
                UPDATE kefu_devices SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END
        """)

        # Step 8: Update schema version
        cursor.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (2,))

        conn.commit()

        # Re-enable foreign keys
        cursor.execute("PRAGMA foreign_keys = ON")

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def run_migrations(db_path: str | None = None) -> None:
    """
    Run all pending migrations.

    Args:
        db_path: Optional custom database path.
    """
    current_version = get_schema_version(db_path)

    if current_version is None:
        # Fresh database, just init
        init_database(db_path)
        return

    if current_version < 2:
        migrate_v1_to_v2(db_path)

    if current_version < 3:
        migrate_v2_to_v3(db_path)

    if current_version < 4:
        migrate_v3_to_v4(db_path)

    if current_version < 5:
        migrate_v4_to_v5(db_path)

    if current_version < 6:
        migrate_v5_to_v6(db_path)

    if current_version < 7:
        migrate_v6_to_v7(db_path)

    if current_version < 8:
        migrate_v7_to_v8(db_path)

    if current_version < 9:
        migrate_v8_to_v9(db_path)

    if current_version < 10:
        migrate_v9_to_v10(db_path)

    if current_version < 11:
        migrate_v10_to_v11(db_path)

    if current_version < 12:
        migrate_v11_to_v12(db_path)

    if current_version < 13:
        migrate_v12_to_v13(db_path)

    repairs = repair_blacklist_schema(db_path)
    if repairs:
        print(f"[schema] Repaired blacklist schema drift: {', '.join(repairs)}")

    customer_fact_repairs = repair_customer_fact_schema(db_path)
    if customer_fact_repairs:
        print(f"[schema] Repaired customer fact schema drift: {', '.join(customer_fact_repairs)}")

    video_repairs = repair_videos_ai_review_schema(db_path)
    if video_repairs:
        print(f"[schema] Repaired videos AI review schema drift: {', '.join(video_repairs)}")


# Migration from v2 to v3: add videos table
MIGRATION_V2_TO_V3 = """
-- Videos table: stores video message files
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    file_name TEXT,
    duration TEXT,  -- Duration string (e.g., "00:45", "1:23")
    duration_seconds INTEGER,  -- Duration in seconds for sorting/filtering
    thumbnail_path TEXT,  -- Path to video thumbnail image
    width INTEGER,
    height INTEGER,
    file_size INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_videos_message_id ON videos(message_id);
"""


def migrate_v2_to_v3(db_path: str | None = None) -> None:
    """
    Migrate database from v2 to v3.

    This migration adds the videos table for storing video message files.

    Args:
        db_path: Optional custom database path.
    """
    path = get_db_path(db_path)
    conn = sqlite3.connect(str(path), factory=InstrumentedConnection)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # Create videos table
        cursor.executescript(MIGRATION_V2_TO_V3)

        # Update schema version
        cursor.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (3,))

        conn.commit()

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


# Migration from v3 to v4: add ui_position for accurate message ordering
MIGRATION_V3_TO_V4 = """
-- Add ui_position column to messages table for accurate context ordering
ALTER TABLE messages ADD COLUMN ui_position INTEGER;

-- Create index for efficient ordering queries
CREATE INDEX IF NOT EXISTS idx_messages_ui_position ON messages(customer_id, ui_position);

-- Backfill ui_position for existing messages based on created_at order
-- This ensures existing data has reasonable ordering
UPDATE messages
SET ui_position = (
    SELECT COUNT(*)
    FROM messages m2
    WHERE m2.customer_id = messages.customer_id
    AND m2.id <= messages.id
);
"""


def migrate_v3_to_v4(db_path: str | None = None) -> None:
    """
    Migrate database from v3 to v4.

    This migration adds the ui_position column to messages table for accurate
    message ordering when constructing conversation context.

    Args:
        db_path: Optional custom database path.
    """
    path = get_db_path(db_path)
    conn = sqlite3.connect(str(path), factory=InstrumentedConnection)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(messages)")
        columns = [row["name"] for row in cursor.fetchall()]

        if "ui_position" not in columns:
            # Add the column
            cursor.execute("ALTER TABLE messages ADD COLUMN ui_position INTEGER")

            # Create index
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_ui_position ON messages(customer_id, ui_position)")

            # Backfill existing messages with ui_position based on id order
            # This gives reasonable ordering for existing data
            cursor.execute("""
                UPDATE messages
                SET ui_position = (
                    SELECT COUNT(*)
                    FROM messages m2
                    WHERE m2.customer_id = messages.customer_id
                    AND m2.id <= messages.id
                )
            """)

        # Update schema version
        cursor.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (4,))

        conn.commit()

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


# Migration from v4 to v5: add blacklist table
MIGRATION_V4_TO_V5 = """
-- Blacklist table: users to skip during sync/followup
CREATE TABLE IF NOT EXISTS blacklist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_serial TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    customer_channel TEXT,
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(device_serial, customer_name, customer_channel)
);

-- Indexes for blacklist
CREATE INDEX IF NOT EXISTS idx_blacklist_device ON blacklist(device_serial);
CREATE INDEX IF NOT EXISTS idx_blacklist_name ON blacklist(customer_name);

-- Trigger for blacklist updated_at
CREATE TRIGGER IF NOT EXISTS update_blacklist_timestamp
AFTER UPDATE ON blacklist
BEGIN
    UPDATE blacklist SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
"""


def migrate_v4_to_v5(db_path: str | None = None) -> None:
    """
    Migrate database from v4 to v5.

    This migration adds the blacklist table for managing users to skip
    during sync and followup operations.

    Args:
        db_path: Optional custom database path.
    """
    path = get_db_path(db_path)
    conn = sqlite3.connect(str(path), factory=InstrumentedConnection)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # Create blacklist table and related objects
        cursor.executescript(MIGRATION_V4_TO_V5)

        # Update schema version
        cursor.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (5,))

        conn.commit()

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


# Migration from v5 to v6: add deleted_by_user column to blacklist
MIGRATION_V5_TO_V6 = """
-- Add deleted_by_user column to blacklist table
ALTER TABLE blacklist ADD COLUMN deleted_by_user BOOLEAN DEFAULT 0;
"""


def migrate_v5_to_v6(db_path: str | None = None) -> None:
    """
    Migrate database from v5 to v6.

    This migration adds the deleted_by_user column to the blacklist table
    to track users who have deleted/blocked us.

    Args:
        db_path: Optional custom database path.
    """
    path = get_db_path(db_path)
    conn = sqlite3.connect(str(path), factory=InstrumentedConnection)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(blacklist)")
        columns = [row["name"] for row in cursor.fetchall()]

        if "deleted_by_user" not in columns:
            cursor.execute("ALTER TABLE blacklist ADD COLUMN deleted_by_user BOOLEAN DEFAULT 0")

        # Update schema version
        cursor.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (6,))

        conn.commit()

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


# Migration from v6 to v7: extend blacklist table for full user management
MIGRATION_V6_TO_V7 = """
-- Add avatar_url column to blacklist table for storing scanned avatars
ALTER TABLE blacklist ADD COLUMN avatar_url TEXT;

-- Add is_blacklisted column to control blacklist status (core switch)
-- Default 1: default all entries in this table are blacklisted (including newly scanned ones)
-- 0: whitelist (user manually allowed)
ALTER TABLE blacklist ADD COLUMN is_blacklisted BOOLEAN DEFAULT 1;
"""


def migrate_v6_to_v7(db_path: str | None = None) -> None:
    """
    Migrate database from v6 to v7.

    This migration extends the blacklist table to support full user management:
    - Adds avatar_url for storing scanned user avatars
    - Adds is_blacklisted as a core switch to distinguish blacklisted (1) from whitelisted (0) users
    - Updates all existing records to is_blacklisted=1 (historical data was explicitly blacklisted)

    This transforms the blacklist table from a simple "blocked users" list into
    a comprehensive "all scanned users" registry with status control.

    Args:
        db_path: Optional custom database path.
    """
    path = get_db_path(db_path)
    conn = sqlite3.connect(str(path), factory=InstrumentedConnection)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        _repair_blacklist_schema_with_cursor(cursor)

        # Update schema version
        cursor.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (7,))

        conn.commit()

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


# Migration from v7 to v8: add system_settings table and migrate from wecom_data.db
MIGRATION_V7_TO_V8 = """
-- System settings table: stores application configuration
CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def migrate_v7_to_v8(db_path: str | None = None) -> None:
    """
    Migrate database from v7 to v8.

    This migration adds the system_settings table and migrates data from
    the legacy wecom_data.db if it exists.

    Args:
        db_path: Optional custom database path.
    """
    path = get_db_path(db_path)
    conn = sqlite3.connect(str(path), factory=InstrumentedConnection)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # Create system_settings table
        cursor.executescript(MIGRATION_V7_TO_V8)

        # Migrate data from legacy wecom_data.db
        legacy_db_path = PROJECT_ROOT / "wecom_data.db"

        if legacy_db_path.exists():
            print(f"Found legacy database at {legacy_db_path}, migrating settings...")
            try:
                # Attach legacy database
                cursor.execute("ATTACH DATABASE ? AS legacy_db", (str(legacy_db_path),))

                # Check if system_settings exists in legacy db
                cursor.execute("SELECT name FROM legacy_db.sqlite_master WHERE type='table' AND name='system_settings'")
                if cursor.fetchone():
                    # Copy data
                    cursor.execute("""
                        INSERT OR REPLACE INTO system_settings (key, value, updated_at)
                        SELECT key, value, updated_at FROM legacy_db.system_settings
                    """)
                    print("Settings migrated successfully.")
                else:
                    print("Legacy database found but system_settings table is missing.")

                # Detach legacy database
                cursor.execute("DETACH DATABASE legacy_db")

                # Rename legacy database to verify successful migration (and backup)
                legacy_backup_path = PROJECT_ROOT / "wecom_data.db.migrated"
                if legacy_backup_path.exists():
                    legacy_backup_path.unlink()

                # We don't delete it automatically, just renaming/backing up could be safer,
                # but for now let's leave it as is or maybe print a message.
                # Actually, renaming it is a good way to "deprecate" it.
                try:
                    legacy_db_path.rename(legacy_backup_path)
                    print(f"Legacy database renamed to {legacy_backup_path}")
                except OSError as e:
                    print(f"Warning: Could not rename legacy database: {e}")

            except sqlite3.Error as e:
                print(f"Warning: Failed to migrate legacy settings: {e}")
                # Ensure we detach if error occurred during attached state
                try:
                    cursor.execute("DETACH DATABASE legacy_db")
                except Exception:
                    pass

        # Update schema version
        cursor.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (8,))

        conn.commit()

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


# Migration from v8 to v9: AI image review fields on images table
MIGRATION_V8_TO_V9 = """
ALTER TABLE images ADD COLUMN review_external_id TEXT;
ALTER TABLE images ADD COLUMN ai_review_score REAL;
ALTER TABLE images ADD COLUMN ai_review_model TEXT;
ALTER TABLE images ADD COLUMN ai_review_decision TEXT;
ALTER TABLE images ADD COLUMN ai_review_details_json TEXT;
ALTER TABLE images ADD COLUMN ai_review_at TEXT;
"""


def migrate_v8_to_v9(db_path: str | None = None) -> None:
    """
    Migrate database from v8 to v9.

    Adds columns on images for image-rating-server AI review results.
    """
    path = get_db_path(db_path)
    conn = sqlite3.connect(str(path), factory=InstrumentedConnection)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.executescript(MIGRATION_V8_TO_V9)
        cursor.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (9,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


# Migration from v9 to v10: image review workflow state fields on images table
MIGRATION_V9_TO_V10 = """
ALTER TABLE images ADD COLUMN ai_review_status TEXT;
ALTER TABLE images ADD COLUMN ai_review_error TEXT;
ALTER TABLE images ADD COLUMN ai_review_requested_at TEXT;
"""


def migrate_v9_to_v10(db_path: str | None = None) -> None:
    """
    Migrate database from v9 to v10.

    Adds workflow state fields for Sidecar image review status display.
    """
    path = get_db_path(db_path)
    conn = sqlite3.connect(str(path), factory=InstrumentedConnection)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.executescript(MIGRATION_V9_TO_V10)
        cursor.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (10,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


# Migration from v10 to v11: enforce one image row per message
MIGRATION_V10_TO_V11 = """
DELETE FROM images
WHERE id NOT IN (
    SELECT MAX(id)
    FROM images
    GROUP BY message_id
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_images_message_id_unique ON images(message_id);
"""


def migrate_v10_to_v11(db_path: str | None = None) -> None:
    """
    Migrate database from v10 to v11.

    Ensures images(message_id) stays one-to-one so message history joins are stable.
    """
    path = get_db_path(db_path)
    conn = sqlite3.connect(str(path), factory=InstrumentedConnection)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.executescript(MIGRATION_V10_TO_V11)
        cursor.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (11,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def migrate_v11_to_v12(db_path: str | None = None) -> None:
    """
    Migrate database from v11 to v12.

    Adds AI review aggregate and per-frame JSON on videos.
    """
    path = get_db_path(db_path)
    conn = sqlite3.connect(str(path), factory=InstrumentedConnection)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        columns = _get_table_columns(cursor, "videos")
        for column_name, alter_sql in VIDEOS_AI_REVIEW_COLUMN_REPAIRS:
            if column_name not in columns:
                cursor.execute(alter_sql)
                columns.add(column_name)
        cursor.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (12,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


MIGRATION_V12_TO_V13 = """
-- Voices table: stores voice message audio files
CREATE TABLE IF NOT EXISTS voices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    file_name TEXT,
    duration TEXT,
    duration_seconds INTEGER,
    file_size INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_voices_message_id ON voices(message_id);
"""
def migrate_v12_to_v13(db_path: str | None = None) -> None:
    """
    Migrate database from v12 to v13.

    Adds the voices table for storing voice message audio files.
    """
    path = get_db_path(db_path)
    conn = sqlite3.connect(str(path), factory=InstrumentedConnection)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.executescript(MIGRATION_V12_TO_V13)
        cursor.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (13,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()
