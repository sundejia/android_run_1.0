import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from main import app


def _create_drifted_blacklist_db(db_path: Path) -> None:
    """Create a DB that reports the latest version but still has the old blacklist schema."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.executescript(
        """
        CREATE TABLE blacklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_serial TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            customer_channel TEXT,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(device_serial, customer_name, customer_channel)
        );

        CREATE TABLE schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        INSERT INTO schema_version (version) VALUES (8);
        """
    )
    conn.commit()
    conn.close()


def _create_duplicate_blacklist_db(db_path: Path) -> None:
    """Create a DB with duplicate blacklist identities but current schema_version."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.executescript(
        """
        CREATE TABLE blacklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_serial TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            customer_channel TEXT,
            reason TEXT,
            deleted_by_user INTEGER NOT NULL DEFAULT 0,
            is_blacklisted INTEGER NOT NULL DEFAULT 0,
            avatar_url TEXT,
            customer_db_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(device_serial, customer_name, customer_channel)
        );

        CREATE TABLE schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        INSERT INTO schema_version (version) VALUES (13);

        INSERT INTO blacklist (
            device_serial, customer_name, customer_channel, reason,
            deleted_by_user, is_blacklisted, avatar_url, customer_db_id,
            created_at, updated_at
        ) VALUES (
            'SERIAL-DUP', 'Alice', '@WeChat', 'older allow',
            0, 0, NULL, NULL,
            '2026-01-01 10:00:00', '2026-01-01 10:00:00'
        );

        INSERT INTO blacklist (
            device_serial, customer_name, customer_channel, reason,
            deleted_by_user, is_blacklisted, avatar_url, customer_db_id,
            created_at, updated_at
        ) VALUES (
            'SERIAL-DUP', 'Alice', '＠WeChat', 'latest block',
            1, 1, 'avatar.png', 42,
            '2026-01-02 10:00:00', '2026-01-02 10:00:00'
        );
        """
    )
    conn.commit()
    conn.close()


def test_toggle_blacklist_blocks_user_when_not_blacklisted():
    client = TestClient(app)
    mock_writer = Mock()
    mock_writer.add_to_blacklist.return_value = True

    with (
        patch("routers.blacklist.BlacklistWriter", return_value=mock_writer),
        patch("routers.blacklist.BlacklistChecker.is_blacklisted", return_value=False),
    ):
        response = client.post(
            "/api/blacklist/toggle",
            json={
                "device_serial": "SERIAL-1",
                "customer_name": "Alice",
                "customer_channel": "@WeChat",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "message": "User added to blacklist",
        "is_blacklisted": True,
    }
    mock_writer.add_to_blacklist.assert_called_once_with(
        device_serial="SERIAL-1",
        customer_name="Alice",
        customer_channel="@WeChat",
        reason="Toggled via Sidecar",
    )
    mock_writer.remove_from_blacklist.assert_not_called()


def test_toggle_blacklist_allows_user_when_currently_blacklisted():
    client = TestClient(app)
    mock_writer = Mock()
    mock_writer.remove_from_blacklist.return_value = True

    with (
        patch("routers.blacklist.BlacklistWriter", return_value=mock_writer),
        patch("routers.blacklist.BlacklistChecker.is_blacklisted", return_value=True),
    ):
        response = client.post(
            "/api/blacklist/toggle",
            json={
                "device_serial": "SERIAL-2",
                "customer_name": "Bob",
                "customer_channel": "@Queue",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "message": "User removed from blacklist",
        "is_blacklisted": False,
    }
    mock_writer.remove_from_blacklist.assert_called_once_with(
        device_serial="SERIAL-2",
        customer_name="Bob",
        customer_channel="@Queue",
    )
    mock_writer.add_to_blacklist.assert_not_called()


def test_toggle_blacklist_repairs_drifted_schema_on_startup(tmp_path):
    db_path = tmp_path / "blacklist-drift.db"
    _create_drifted_blacklist_db(db_path)

    with patch.dict(os.environ, {"WECOM_DB_PATH": str(db_path)}, clear=False):
        with TestClient(app) as client:
            response = client.post(
                "/api/blacklist/toggle",
                json={
                    "device_serial": "SERIAL-3",
                    "customer_name": "Carol",
                    "customer_channel": "@Queue",
                },
            )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "message": "User added to blacklist",
        "is_blacklisted": True,
    }

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(blacklist)")
    columns = {row["name"] for row in cursor.fetchall()}
    assert {"deleted_by_user", "is_blacklisted", "avatar_url", "customer_db_id"}.issubset(columns)

    cursor.execute(
        """
        SELECT is_blacklisted, deleted_by_user, avatar_url, customer_db_id, reason
        FROM blacklist
        WHERE device_serial = ? AND customer_name = ?
        """,
        ("SERIAL-3", "Carol"),
    )
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row["is_blacklisted"] == 1
    assert row["deleted_by_user"] == 0
    assert row["avatar_url"] is None
    assert row["customer_db_id"] is None
    assert row["reason"] == "Toggled via Sidecar"


def test_check_blacklist_returns_reason_even_when_channel_differs(tmp_path):
    db_path = tmp_path / "blacklist-check.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.executescript(
        """
        CREATE TABLE blacklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_serial TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            customer_channel TEXT,
            reason TEXT,
            deleted_by_user INTEGER NOT NULL DEFAULT 0,
            is_blacklisted INTEGER NOT NULL DEFAULT 0,
            avatar_url TEXT,
            customer_db_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        INSERT INTO schema_version (version) VALUES (13);
        INSERT INTO blacklist (
            device_serial, customer_name, customer_channel, reason, deleted_by_user, is_blacklisted
        ) VALUES ('SERIAL-4', 'Alice', '@WeChat', 'manual block', 0, 1);
        """
    )
    conn.commit()
    conn.close()

    with patch.dict(os.environ, {"WECOM_DB_PATH": str(db_path)}, clear=False):
        with TestClient(app) as client:
            response = client.get(
                "/api/blacklist/check",
                params={
                    "device_serial": "SERIAL-4",
                    "customer_name": "Alice",
                    "customer_channel": "＠WeChat",
                },
            )

    assert response.status_code == 200
    assert response.json() == {
        "is_blacklisted": True,
        "reason": "manual block",
    }


def test_startup_repair_merges_duplicate_blacklist_identities(tmp_path):
    db_path = tmp_path / "blacklist-duplicate.db"
    _create_duplicate_blacklist_db(db_path)

    with patch.dict(os.environ, {"WECOM_DB_PATH": str(db_path)}, clear=False):
        with TestClient(app) as client:
            response = client.get("/health")

    assert response.status_code == 200

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT customer_channel, reason, deleted_by_user, is_blacklisted, avatar_url, customer_db_id
        FROM blacklist
        WHERE device_serial = ? AND customer_name = ?
        """,
        ("SERIAL-DUP", "Alice"),
    )
    rows = cursor.fetchall()
    conn.close()

    assert len(rows) == 1
    row = rows[0]
    assert row["customer_channel"] == "＠WeChat"
    assert row["reason"] == "latest block"
    assert row["deleted_by_user"] == 1
    assert row["is_blacklisted"] == 1
    assert row["avatar_url"] == "avatar.png"
    assert row["customer_db_id"] == 42
