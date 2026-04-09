import sqlite3
from pathlib import Path

from wecom_automation.services.blacklist_service import BlacklistChecker, BlacklistWriter


def _init_blacklist_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
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


def test_is_blacklisted_ignores_channel_when_name_matches(tmp_path, monkeypatch):
    db_path = tmp_path / "blacklist.db"
    _init_blacklist_db(db_path)
    monkeypatch.setattr("wecom_automation.services.blacklist_service.get_db_path", lambda *_: db_path)
    BlacklistChecker.invalidate_cache()

    writer = BlacklistWriter()
    assert writer.add_to_blacklist("D1", "Alice", "＠微信", reason="test")

    assert BlacklistChecker.is_blacklisted("D1", "Alice", "@微信") is True
    assert BlacklistChecker.is_blacklisted("D1", "Alice", "completely-different-channel") is True


def test_remove_from_blacklist_works_even_if_channel_differs(tmp_path, monkeypatch):
    db_path = tmp_path / "blacklist.db"
    _init_blacklist_db(db_path)
    monkeypatch.setattr("wecom_automation.services.blacklist_service.get_db_path", lambda *_: db_path)
    BlacklistChecker.invalidate_cache()

    writer = BlacklistWriter()
    assert writer.add_to_blacklist("D1", "Bob", None, reason="sidecar-no-channel")

    # Name-only matching: channel differences should not matter.
    assert BlacklistChecker.is_blacklisted("D1", "Bob", "@WeChat") is True

    # Unblock should also work when a different channel is provided.
    assert writer.remove_from_blacklist("D1", "Bob", "@WeChat") is True
    assert BlacklistChecker.is_blacklisted("D1", "Bob", "@WeChat") is False


def test_upsert_scanned_users_merges_channel_variants_by_name(tmp_path, monkeypatch):
    db_path = tmp_path / "blacklist.db"
    _init_blacklist_db(db_path)
    monkeypatch.setattr("wecom_automation.services.blacklist_service.get_db_path", lambda *_: db_path)
    BlacklistChecker.invalidate_cache()

    writer = BlacklistWriter()
    writer.upsert_scanned_users(
        "D1",
        [{"customer_name": "Alice", "customer_channel": "@WeChat", "avatar_url": None, "reason": "scan-1"}],
    )
    writer.upsert_scanned_users(
        "D1",
        [{"customer_name": "Alice", "customer_channel": "＠WeChat", "avatar_url": None, "reason": "scan-2"}],
    )

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT customer_name, customer_channel, is_blacklisted
            FROM blacklist
            WHERE device_serial = ?
            ORDER BY id
            """,
            ("D1",),
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 1
    assert rows[0]["customer_name"] == "Alice"
    assert rows[0]["customer_channel"] == "@WeChat"
    assert rows[0]["is_blacklisted"] == 0
    assert writer.get_whitelist_names("D1") == {"Alice"}


def test_update_status_syncs_all_rows_for_same_customer(tmp_path, monkeypatch):
    db_path = tmp_path / "blacklist.db"
    _init_blacklist_db(db_path)
    monkeypatch.setattr("wecom_automation.services.blacklist_service.get_db_path", lambda *_: db_path)
    BlacklistChecker.invalidate_cache()

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            INSERT INTO blacklist (device_serial, customer_name, customer_channel, reason, is_blacklisted)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("D1", "Alice", "@WeChat", "scan-1", 0),
        )
        conn.execute(
            """
            INSERT INTO blacklist (device_serial, customer_name, customer_channel, reason, is_blacklisted)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("D1", "Alice", "＠WeChat", "scan-2", 0),
        )
        conn.commit()
        first_id, second_id = [row[0] for row in conn.execute("SELECT id FROM blacklist ORDER BY id").fetchall()]
    finally:
        conn.close()

    writer = BlacklistWriter()
    assert writer.update_status(first_id, True) is True
    assert BlacklistChecker.is_blacklisted("D1", "Alice", "completely-different-channel") is True

    conn = sqlite3.connect(str(db_path))
    try:
        blocked_states = [row[0] for row in conn.execute("SELECT is_blacklisted FROM blacklist ORDER BY id").fetchall()]
    finally:
        conn.close()

    assert blocked_states == [1, 1]

    assert writer.update_status(second_id, False) is True
    assert BlacklistChecker.is_blacklisted("D1", "Alice", "@WeChat") is False

    conn = sqlite3.connect(str(db_path))
    try:
        allowed_states = [row[0] for row in conn.execute("SELECT is_blacklisted FROM blacklist ORDER BY id").fetchall()]
    finally:
        conn.close()

    assert allowed_states == [0, 0]
