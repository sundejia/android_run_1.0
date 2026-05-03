"""
Regression tests for new-device deployment scenarios.

These tests cover:
- Copying blacklist rows from an old Android device serial to a new one
- Resolving sidecar history when a placeholder Kefu-* record coexists with a real kefu
- Aggregating fragmented history across placeholder and real kefu customer rows
"""

import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# Add backend directory to import path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Mock droidrun before importing the app
mock_droidrun = MagicMock()
mock_droidrun.tools = MagicMock()
mock_droidrun.tools.adb = MagicMock()
mock_droidrun.tools.adb.AdbTools = MagicMock()
sys.modules["droidrun"] = mock_droidrun
sys.modules["droidrun.tools"] = mock_droidrun.tools
sys.modules["droidrun.tools.adb"] = mock_droidrun.tools.adb

from main import app


@pytest.fixture
def deployment_db():
    """Create a temporary database that exercises new-device deployment flows."""
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "deployment.db"
    conn = sqlite3.connect(str(db_path))

    try:
        cursor = conn.cursor()
        cursor.executescript(
            """
            CREATE TABLE devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                serial TEXT UNIQUE NOT NULL,
                model TEXT,
                manufacturer TEXT,
                android_version TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE kefus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                department TEXT,
                verification_status TEXT,
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
                message_type TEXT NOT NULL,
                is_from_kefu INTEGER NOT NULL,
                timestamp_raw TEXT,
                timestamp_parsed TEXT,
                extra_info TEXT,
                message_hash TEXT,
                ui_position INTEGER,
                created_at TEXT
            );

            CREATE TABLE images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                file_path TEXT,
                width INTEGER,
                height INTEGER,
                ai_review_score REAL,
                ai_review_decision TEXT,
                ai_review_details_json TEXT,
                ai_review_at TEXT,
                ai_review_status TEXT,
                ai_review_error TEXT,
                ai_review_requested_at TEXT
            );

            CREATE TABLE videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                duration TEXT,
                ai_review_score REAL,
                ai_review_status TEXT,
                ai_review_error TEXT,
                ai_review_requested_at TEXT,
                ai_review_at TEXT,
                ai_review_frames_json TEXT
            );

            CREATE TABLE blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_serial TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                customer_channel TEXT,
                reason TEXT,
                deleted_by_user INTEGER DEFAULT 0,
                is_blacklisted INTEGER DEFAULT 0,
                avatar_url TEXT,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(device_serial, customer_name, customer_channel)
            );
            """
        )

        # Devices used for blacklist-copy tests.
        cursor.execute(
            "INSERT INTO devices (serial, created_at, updated_at) VALUES (?, ?, ?)",
            ("OLD-DEVICE", "2026-01-01T08:00:00", "2026-01-01T08:00:00"),
        )
        cursor.execute(
            "INSERT INTO devices (serial, created_at, updated_at) VALUES (?, ?, ?)",
            ("NEW-DEVICE", "2026-01-01T08:05:00", "2026-01-01T08:05:00"),
        )

        # Device used for sidecar-history tests.
        cursor.execute(
            "INSERT INTO devices (serial, created_at, updated_at) VALUES (?, ?, ?)",
            ("SER123", "2026-01-01T08:10:00", "2026-01-01T08:10:00"),
        )
        history_device_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO kefus (name, department, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("RealAgent", "Support", "2026-01-01T08:00:00", "2026-01-01T08:00:00"),
        )
        real_kefu_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO kefus (name, department, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("Kefu-SER123", None, "2026-01-01T09:00:00", "2026-01-01T12:00:00"),
        )
        placeholder_kefu_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO kefu_devices (kefu_id, device_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (real_kefu_id, history_device_id, "2026-01-01T08:00:00", "2026-01-01T08:00:00"),
        )
        cursor.execute(
            "INSERT INTO kefu_devices (kefu_id, device_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (placeholder_kefu_id, history_device_id, "2026-01-01T09:00:00", "2026-01-01T12:00:00"),
        )

        # Customer that only exists under the real kefu.
        cursor.execute(
            """
            INSERT INTO customers (kefu_id, name, channel, last_message_preview, last_message_date, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                real_kefu_id,
                "CustomerOnlyReal",
                "@WeChat",
                "real only message",
                "2026-01-01T10:00:00",
                "2026-01-01T10:00:00",
                "2026-01-01T10:00:00",
            ),
        )
        customer_only_real_id = cursor.lastrowid

        # Customer split between placeholder and real kefu rows.
        cursor.execute(
            """
            INSERT INTO customers (kefu_id, name, channel, last_message_preview, last_message_date, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                placeholder_kefu_id,
                "CustomerFragmented",
                "@WeChat",
                "placeholder intro",
                "2026-01-01T09:00:00",
                "2026-01-01T09:00:00",
                "2026-01-01T09:00:00",
            ),
        )
        placeholder_customer_id = cursor.lastrowid
        cursor.execute(
            """
            INSERT INTO customers (kefu_id, name, channel, last_message_preview, last_message_date, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                real_kefu_id,
                "CustomerFragmented",
                "@WeChat",
                "real synced followup",
                "2026-01-01T10:00:00",
                "2026-01-01T10:00:00",
                "2026-01-01T10:00:00",
            ),
        )
        real_customer_id = cursor.lastrowid

        cursor.execute(
            """
            INSERT INTO messages
                (customer_id, content, message_type, is_from_kefu, timestamp_raw, timestamp_parsed, extra_info, message_hash, ui_position, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                customer_only_real_id,
                "real only message",
                "text",
                0,
                "10:00",
                "2026-01-01T10:00:00",
                None,
                "hash-real-only",
                1,
                "2026-01-01T10:00:00",
            ),
        )
        cursor.execute(
            """
            INSERT INTO messages
                (customer_id, content, message_type, is_from_kefu, timestamp_raw, timestamp_parsed, extra_info, message_hash, ui_position, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                placeholder_customer_id,
                "placeholder intro",
                "text",
                1,
                "09:00",
                "2026-01-01T09:00:00",
                None,
                "hash-placeholder-fragment",
                1,
                "2026-01-01T09:00:00",
            ),
        )
        cursor.execute(
            """
            INSERT INTO messages
                (customer_id, content, message_type, is_from_kefu, timestamp_raw, timestamp_parsed, extra_info, message_hash, ui_position, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                real_customer_id,
                "real synced followup",
                "text",
                0,
                "10:00",
                "2026-01-01T10:00:00",
                None,
                "hash-real-fragment",
                1,
                "2026-01-01T10:00:00",
            ),
        )

        cursor.executemany(
            """
            INSERT INTO blacklist
                (device_serial, customer_name, customer_channel, reason, deleted_by_user, is_blacklisted, avatar_url, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "OLD-DEVICE",
                    "Alice",
                    "@WeChat",
                    "legacy block",
                    0,
                    1,
                    "alice.png",
                    "2026-01-01T08:00:00",
                    "2026-01-01T08:00:00",
                ),
                (
                    "OLD-DEVICE",
                    "Bob",
                    "@WeChat",
                    "legacy allow",
                    0,
                    0,
                    "bob.png",
                    "2026-01-01T08:10:00",
                    "2026-01-01T08:10:00",
                ),
                (
                    "NEW-DEVICE",
                    "Alice",
                    "@WeChat",
                    "stale target status",
                    0,
                    0,
                    None,
                    "2026-01-01T08:20:00",
                    "2026-01-01T08:20:00",
                ),
            ],
        )

        conn.commit()
    finally:
        conn.close()

    yield db_path
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def client(monkeypatch, deployment_db):
    """Create a TestClient that uses the temporary deployment database."""
    from routers import sidecar

    monkeypatch.setattr(sidecar, "get_db_path", lambda *_: deployment_db)
    monkeypatch.setattr("wecom_automation.services.blacklist_service.get_db_path", lambda *_: deployment_db)

    with TestClient(app) as test_client:
        yield test_client


def test_copy_blacklist_between_devices_updates_target_rows(client, deployment_db):
    response = client.post(
        "/api/blacklist/copy-device",
        json={
            "source_device_serial": "OLD-DEVICE",
            "target_device_serial": "NEW-DEVICE",
            "include_allowed": True,
            "overwrite_existing": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["copied_count"] == 1
    assert payload["updated_count"] == 1
    assert payload["skipped_count"] == 0
    assert payload["total_source_entries"] == 2

    conn = sqlite3.connect(str(deployment_db))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT customer_name, is_blacklisted, reason, avatar_url
            FROM blacklist
            WHERE device_serial = ?
            ORDER BY customer_name ASC
            """,
            ("NEW-DEVICE",),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    assert [row["customer_name"] for row in rows] == ["Alice", "Bob"]
    assert rows[0]["is_blacklisted"] == 1
    assert rows[0]["reason"] == "legacy block"
    assert rows[0]["avatar_url"] == "alice.png"
    assert rows[1]["is_blacklisted"] == 0
    assert rows[1]["reason"] == "legacy allow"


def test_conversation_history_prefers_real_kefu_over_placeholder(client):
    response = client.get(
        "/sidecar/SER123/conversation-history",
        params={"contact_name": "CustomerOnlyReal", "channel": "@WeChat"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["kefu_name"] == "RealAgent"
    assert payload["customer_name"] == "CustomerOnlyReal"
    assert payload["total_messages"] == 1
    assert [msg["content"] for msg in payload["messages"]] == ["real only message"]


def test_conversation_history_defaults_to_device_scoped_db(monkeypatch, deployment_db):
    from routers import sidecar

    empty_control = deployment_db.parent / "empty-control.db"
    conn = sqlite3.connect(str(empty_control))
    conn.close()

    monkeypatch.setattr(sidecar, "get_db_path", lambda *_: empty_control)
    monkeypatch.setattr(sidecar, "get_device_conversation_db_path", lambda serial: deployment_db)

    with TestClient(app) as test_client:
        response = test_client.get(
            "/sidecar/SER123/conversation-history",
            params={"contact_name": "CustomerOnlyReal", "channel": "@WeChat"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["db_path"] == str(deployment_db)
    assert payload["kefu_name"] == "RealAgent"
    assert [msg["content"] for msg in payload["messages"]] == ["real only message"]


def test_conversation_history_aggregates_fragmented_rows(client):
    response = client.get(
        "/sidecar/SER123/conversation-history",
        params={
            "contact_name": "CustomerFragmented",
            "channel": "@WeChat",
            "kefu_name": "RealAgent",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["kefu_name"] == "RealAgent"
    assert payload["customer_name"] == "CustomerFragmented"
    assert payload["total_messages"] == 2
    assert [msg["content"] for msg in payload["messages"]] == [
        "placeholder intro",
        "real synced followup",
    ]
