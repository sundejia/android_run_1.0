import sqlite3
import importlib.util
import shutil
import sys
import types
import uuid
from pathlib import Path


backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

services_pkg = types.ModuleType("services")
services_pkg.__path__ = [str(backend_dir / "services")]
sys.modules.setdefault("services", services_pkg)

followup_pkg = types.ModuleType("services.followup")
followup_pkg.__path__ = [str(backend_dir / "services" / "followup")]
sys.modules.setdefault("services.followup", followup_pkg)

settings_path = backend_dir / "services" / "followup" / "settings.py"
settings_spec = importlib.util.spec_from_file_location("services.followup.settings", settings_path)
settings_module = importlib.util.module_from_spec(settings_spec)
assert settings_spec and settings_spec.loader
sys.modules["services.followup.settings"] = settings_module
settings_spec.loader.exec_module(settings_module)

repository_path = backend_dir / "services" / "followup" / "repository.py"
repository_spec = importlib.util.spec_from_file_location("services.followup.repository", repository_path)
repository_module = importlib.util.module_from_spec(repository_spec)
assert repository_spec and repository_spec.loader
sys.modules["services.followup.repository"] = repository_module
repository_spec.loader.exec_module(repository_module)
ConversationRepository = repository_module.ConversationRepository


def _create_db() -> tuple[Path, Path]:
    temp_root = backend_dir / "tests_tmp"
    temp_root.mkdir(exist_ok=True)
    temp_dir = temp_root / f"realtime_customer_{uuid.uuid4().hex}"
    temp_dir.mkdir()
    db_path = temp_dir / "realtime_customer.db"

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.executescript(
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
                kefu_id INTEGER,
                name TEXT NOT NULL,
                channel TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                content TEXT,
                message_type TEXT NOT NULL DEFAULT 'text',
                is_from_kefu BOOLEAN NOT NULL DEFAULT 0,
                timestamp_raw TEXT,
                timestamp_parsed TEXT,
                extra_info TEXT,
                message_hash TEXT UNIQUE NOT NULL,
                ui_position INTEGER,
                created_at TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    return temp_dir, db_path


def test_find_or_create_customer_creates_row_for_current_kefu():
    temp_dir, db_path = _create_db()
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO devices (serial, created_at, updated_at) VALUES (?, ?, ?)",
                ("SER123", "2026-03-22T09:00:00", "2026-03-22T09:00:00"),
            )
            device_id = cursor.lastrowid

            cursor.execute(
                "INSERT INTO kefus (name, created_at, updated_at) VALUES (?, ?, ?)",
                ("OldAgent", "2026-03-22T09:00:00", "2026-03-22T09:00:00"),
            )
            old_kefu_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO kefus (name, created_at, updated_at) VALUES (?, ?, ?)",
                ("CurrentAgent", "2026-03-22T10:00:00", "2026-03-22T10:00:00"),
            )
            current_kefu_id = cursor.lastrowid

            cursor.execute(
                "INSERT INTO kefu_devices (kefu_id, device_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (old_kefu_id, device_id, "2026-03-22T09:00:00", "2026-03-22T09:00:00"),
            )
            cursor.execute(
                "INSERT INTO kefu_devices (kefu_id, device_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (current_kefu_id, device_id, "2026-03-22T10:00:00", "2026-03-22T10:00:00"),
            )

            cursor.execute(
                "INSERT INTO customers (kefu_id, name, channel, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (old_kefu_id, "Alice", "@WeChat", "2026-03-22T09:05:00", "2026-03-22T09:05:00"),
            )
            old_customer_id = cursor.lastrowid
            conn.commit()
        finally:
            conn.close()

        repo = ConversationRepository(str(db_path))
        customer_id = repo.find_or_create_customer("Alice", "@WeChat", "SER123")

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT id, kefu_id, name, channel FROM customers WHERE name = ? ORDER BY id",
                ("Alice",),
            ).fetchall()
        finally:
            conn.close()

        assert customer_id != old_customer_id
        assert len(rows) == 2
        assert rows[-1]["id"] == customer_id
        assert rows[-1]["kefu_id"] == current_kefu_id
        assert rows[-1]["channel"] == "@WeChat"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
