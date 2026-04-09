import sqlite3
from pathlib import Path

from wecom_automation.services.blacklist_service import BlacklistWriter


def _init_control_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """
            CREATE TABLE blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_serial TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                customer_channel TEXT,
                reason TEXT,
                is_blacklisted INTEGER NOT NULL DEFAULT 0,
                deleted_by_user INTEGER NOT NULL DEFAULT 0,
                customer_db_id INTEGER,
                avatar_url TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _init_device_customer_db(path: Path, serial: str) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            CREATE TABLE devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                serial TEXT UNIQUE NOT NULL,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE kefus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE kefu_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kefu_id INTEGER NOT NULL,
                device_id INTEGER NOT NULL,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kefu_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                channel TEXT,
                last_message_preview TEXT,
                last_message_date TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                content TEXT,
                message_type TEXT NOT NULL DEFAULT 'text',
                is_from_kefu INTEGER NOT NULL DEFAULT 0,
                timestamp_raw TEXT,
                timestamp_parsed TEXT,
                message_hash TEXT UNIQUE NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cursor = conn.cursor()
        cursor.execute("INSERT INTO devices (serial, created_at, updated_at) VALUES (?, '2026-01-01', '2026-01-01')", (serial,))
        device_id = cursor.lastrowid
        cursor.execute("INSERT INTO kefus (name, created_at, updated_at) VALUES ('Kefu', '2026-01-01', '2026-01-01')")
        kefu_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO kefu_devices (kefu_id, device_id, created_at, updated_at) VALUES (?, ?, '2026-01-01', '2026-01-01')",
            (kefu_id, device_id),
        )
        cursor.execute(
            """
            INSERT INTO customers (kefu_id, name, channel, last_message_preview, last_message_date, created_at, updated_at)
            VALUES (?, 'Alice', '@WeChat', 'hi', '2026-01-02T09:00:00', '2026-01-02T09:00:00', '2026-01-02T09:00:00')
            """,
            (kefu_id,),
        )
        alice_id = cursor.lastrowid
        cursor.execute(
            """
            INSERT INTO customers (kefu_id, name, channel, last_message_preview, last_message_date, created_at, updated_at)
            VALUES (?, 'Bob', '@WeChat', 'hello', '2026-01-03T09:00:00', '2026-01-03T09:00:00', '2026-01-03T09:00:00')
            """,
            (kefu_id,),
        )
        bob_id = cursor.lastrowid
        cursor.execute(
            """
            INSERT INTO messages (customer_id, content, message_type, is_from_kefu, timestamp_raw, timestamp_parsed, message_hash, created_at)
            VALUES (?, 'hello', 'text', 0, '2026-01-02T09:00:00', '2026-01-02T09:00:00', 'hash-alice', '2026-01-02T09:00:00')
            """,
            (alice_id,),
        )
        cursor.execute(
            """
            INSERT INTO messages (customer_id, content, message_type, is_from_kefu, timestamp_raw, timestamp_parsed, message_hash, created_at)
            VALUES (?, 'world', 'text', 0, '2026-01-03T09:00:00', '2026-01-03T09:00:00', 'hash-bob', '2026-01-03T09:00:00')
            """,
            (bob_id,),
        )
        conn.commit()
    finally:
        conn.close()


def test_list_customers_with_status_reads_blacklist_from_control_db_and_customers_from_device_db(
    tmp_path,
    monkeypatch,
):
    control_db = tmp_path / "control.db"
    device_db = tmp_path / "device.db"
    _init_control_db(control_db)
    _init_device_customer_db(device_db, "SERIAL-1")

    conn = sqlite3.connect(str(control_db))
    try:
        conn.execute(
            """
            INSERT INTO blacklist (
                device_serial, customer_name, customer_channel, reason, is_blacklisted, deleted_by_user
            ) VALUES (?, ?, ?, ?, 1, 1)
            """,
            ("SERIAL-1", "Alice", "@WeChat", "manual block"),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(
        "wecom_automation.services.blacklist_service._resolve_device_customer_db_path",
        lambda *_args: str(device_db),
    )

    writer = BlacklistWriter(str(control_db))
    customers = writer.list_customers_with_status("SERIAL-1")
    blacklisted_only = writer.list_customers_with_status("SERIAL-1", filter_status="blacklisted")

    assert [customer["customer_name"] for customer in customers] == ["Bob", "Alice"]
    assert customers[0]["is_blacklisted"] is False
    assert customers[1]["is_blacklisted"] is True
    assert customers[1]["blacklist_reason"] == "manual block"
    assert customers[1]["deleted_by_user"] is True
    assert customers[1]["message_count"] == 1
    assert [customer["customer_name"] for customer in blacklisted_only] == ["Alice"]
