import sqlite3
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from services import conversation_storage
from services.federated_reads import federated_reads


def _seed_device_db(db_path: Path, serial: str, customer_name: str, message_content: str, include_image: bool = False):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                serial TEXT,
                model TEXT,
                manufacturer TEXT,
                android_version TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE kefus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                department TEXT,
                verification_status TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE kefu_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kefu_id INTEGER,
                device_id INTEGER
            );
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                channel TEXT,
                kefu_id INTEGER,
                last_message_preview TEXT,
                last_message_date TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER,
                content TEXT,
                message_type TEXT,
                is_from_kefu INTEGER,
                timestamp_raw TEXT,
                timestamp_parsed TEXT,
                extra_info TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                file_path TEXT,
                file_name TEXT,
                original_bounds TEXT,
                width INTEGER,
                height INTEGER,
                file_size INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                file_path TEXT,
                file_name TEXT,
                duration TEXT,
                duration_seconds INTEGER,
                file_size INTEGER,
                thumbnail_path TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.execute(
            "INSERT INTO devices (serial, model, manufacturer, android_version) VALUES (?, ?, ?, ?)",
            (serial, f"model-{serial}", "test", "14"),
        )
        conn.execute(
            "INSERT INTO kefus (name, department, verification_status) VALUES (?, ?, ?)",
            (f"Agent-{serial}", "Sales", "verified"),
        )
        conn.execute("INSERT INTO kefu_devices (kefu_id, device_id) VALUES (1, 1)")
        conn.execute(
            """
            INSERT INTO customers (name, channel, kefu_id, last_message_preview, last_message_date)
            VALUES (?, ?, 1, ?, '2026-04-02 10:00:00')
            """,
            (customer_name, "wechat", message_content),
        )
        conn.execute(
            """
            INSERT INTO messages (
                customer_id, content, message_type, is_from_kefu, timestamp_raw, timestamp_parsed, extra_info
            ) VALUES (1, ?, 'text', 0, '2026-04-02 10:00:00', '2026-04-02 10:00:00', NULL)
            """,
            (message_content,),
        )
        if include_image:
            conn.execute(
                """
                INSERT INTO images (message_id, file_path, file_name, width, height, file_size)
                VALUES (1, 'conversation_images/sample.jpg', 'sample.jpg', 200, 100, 1234)
                """
            )
        conn.commit()
    finally:
        conn.close()


def test_list_federated_targets_and_global_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation_storage, "DEVICE_STORAGE_ROOT", tmp_path / "device_storage")

    db_a = conversation_storage.get_device_conversation_db_path("SERIAL-A")
    db_b = conversation_storage.get_device_conversation_db_path("SERIAL-B")
    _seed_device_db(db_a, "SERIAL-A", "Alice", "hello a")
    _seed_device_db(db_b, "SERIAL-B", "Bob", "hello b")

    targets = conversation_storage.list_federated_conversation_targets()
    assert [target.device_serial for target in targets] == ["SERIAL-A", "SERIAL-B"]

    global_id = conversation_storage.compose_global_id(db_a, 7)
    token, local_id = conversation_storage.decode_global_id(global_id)
    assert token == targets[0].source_token
    assert local_id == 7


def test_federated_reads_aggregate_customers_and_dashboard(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation_storage, "DEVICE_STORAGE_ROOT", tmp_path / "device_storage")

    db_a = conversation_storage.get_device_conversation_db_path("SERIAL-A")
    db_b = conversation_storage.get_device_conversation_db_path("SERIAL-B")
    _seed_device_db(db_a, "SERIAL-A", "Alice", "hello from alice", include_image=True)
    _seed_device_db(db_b, "SERIAL-B", "Bob", "hello from bob")

    customers = federated_reads.list_customers(limit=10)
    assert customers["total"] == 2
    assert {item["device_serial"] for item in customers["items"]} == {"SERIAL-A", "SERIAL-B"}

    first_customer = customers["items"][0]
    target, local_id = federated_reads.resolve_customer(first_customer["id"])
    assert target.device_serial in {"SERIAL-A", "SERIAL-B"}
    assert local_id == 1

    overview = federated_reads.get_dashboard_overview(limit=10)
    assert overview["stats"]["customers"] == 2
    assert overview["stats"]["messages"] == 2
    assert overview["stats"]["images"] == 1


def test_federated_reads_aggregate_resource_filters(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation_storage, "DEVICE_STORAGE_ROOT", tmp_path / "device_storage")

    db_a = conversation_storage.get_device_conversation_db_path("SERIAL-A")
    db_b = conversation_storage.get_device_conversation_db_path("SERIAL-B")
    _seed_device_db(db_a, "SERIAL-A", "Alice", "hello from alice", include_image=True)
    _seed_device_db(db_b, "SERIAL-B", "Bob", "hello from bob")

    options = federated_reads.get_resource_filter_options()
    assert options["counts"]["images"] == 1
    assert options["streamers"] == ["Alice"]
    assert {device["serial"] for device in options["devices"]} == {"SERIAL-A", "SERIAL-B"}
