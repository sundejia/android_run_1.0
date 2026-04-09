import sqlite3
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
sys.path.insert(0, str(backend_dir.parent.parent / "src"))

from services.conversation_storage import ConversationDbTarget
from services.media_action_state_migration import migrate_media_action_state_to_control


def _create_source_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
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
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE media_action_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_serial TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                group_name TEXT NOT NULL,
                group_members TEXT,
                status TEXT DEFAULT 'created',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.execute(
            """
            INSERT INTO blacklist (
                device_serial, customer_name, customer_channel, reason,
                deleted_by_user, is_blacklisted, avatar_url, customer_db_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("DEVICE-1", "Alice", "@WeChat", "older allow", 0, 0, None, None, "2026-01-01 10:00:00", "2026-01-01 10:00:00"),
        )
        conn.execute(
            """
            INSERT INTO blacklist (
                device_serial, customer_name, customer_channel, reason,
                deleted_by_user, is_blacklisted, avatar_url, customer_db_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("DEVICE-1", "Alice", "＠WeChat", "latest block", 1, 1, "avatar.png", 42, "2026-01-02 10:00:00", "2026-01-02 10:00:00"),
        )
        conn.execute(
            """
            INSERT INTO media_action_groups (
                device_serial, customer_name, group_name, group_members, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("DEVICE-1", "Alice", "Alice-服务群", '["经理A"]', "created", "2026-01-02 11:00:00", "2026-01-02 11:00:00"),
        )
        conn.commit()
    finally:
        conn.close()


def test_migrate_media_action_state_to_control_is_idempotent(tmp_path, monkeypatch):
    control_db = tmp_path / "control.db"
    source_db = tmp_path / "device.db"
    control_db.touch()
    _create_source_db(source_db)

    target = ConversationDbTarget(device_serial="DEVICE-1", db_path=source_db)
    monkeypatch.setattr(
        "services.media_action_state_migration.list_device_conversation_targets",
        lambda: [target],
    )

    first_stats = migrate_media_action_state_to_control(str(control_db))
    second_stats = migrate_media_action_state_to_control(str(control_db))

    assert first_stats["source_dbs_scanned"] == 1
    assert second_stats["source_dbs_scanned"] == 1

    conn = sqlite3.connect(str(control_db))
    conn.row_factory = sqlite3.Row
    try:
        blacklist_rows = conn.execute(
            """
            SELECT device_serial, customer_name, customer_channel, reason, deleted_by_user, is_blacklisted, avatar_url, customer_db_id
            FROM blacklist
            """
        ).fetchall()
        group_rows = conn.execute(
            """
            SELECT device_serial, customer_name, group_name, group_members, status
            FROM media_action_groups
            """
        ).fetchall()
    finally:
        conn.close()

    assert len(blacklist_rows) == 1
    assert blacklist_rows[0]["device_serial"] == "DEVICE-1"
    assert blacklist_rows[0]["customer_name"] == "Alice"
    assert blacklist_rows[0]["reason"] == "latest block"
    assert blacklist_rows[0]["deleted_by_user"] == 1
    assert blacklist_rows[0]["is_blacklisted"] == 1
    assert blacklist_rows[0]["avatar_url"] == "avatar.png"
    assert blacklist_rows[0]["customer_db_id"] == 42

    assert len(group_rows) == 1
    assert group_rows[0]["group_name"] == "Alice-服务群"
    assert group_rows[0]["group_members"] == '["经理A"]'
    assert group_rows[0]["status"] == "created"
