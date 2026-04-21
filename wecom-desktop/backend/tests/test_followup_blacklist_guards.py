import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
sys.path.insert(0, str(backend_dir.parent.parent / "src"))

# Mock droidrun before importing followup modules.
mock_droidrun = MagicMock()
mock_droidrun.AdbTools = MagicMock()
mock_droidrun.tools = MagicMock()
mock_droidrun.tools.adb = MagicMock()
mock_droidrun.tools.adb.AdbTools = MagicMock()
sys.modules["droidrun"] = mock_droidrun
sys.modules["droidrun.tools"] = mock_droidrun.tools
sys.modules["droidrun.tools.adb"] = mock_droidrun.tools.adb

from main import app
from routers import sidecar
from services.followup.attempts_repository import AttemptStatus, FollowupAttemptsRepository
from services.followup.queue_manager import ConversationInfo, FollowupQueueManager
from services.followup.settings import FollowUpSettings


def _create_test_db(path: Path) -> None:
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
                extra_info TEXT,
                message_hash TEXT UNIQUE NOT NULL,
                ui_position INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
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
                customer_db_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _seed_customer(path: Path, *, serial: str, name: str, channel: str = "@WeChat") -> int:
    now = datetime.now().isoformat()
    conn = sqlite3.connect(str(path))
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO devices (serial, created_at, updated_at) VALUES (?, ?, ?)",
            (serial, now, now),
        )
        device_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO kefus (name, created_at, updated_at) VALUES (?, ?, ?)",
            ("TestKefu", now, now),
        )
        kefu_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO kefu_devices (kefu_id, device_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (kefu_id, device_id, now, now),
        )
        cursor.execute(
            "INSERT INTO customers (kefu_id, name, channel, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (kefu_id, name, channel, now, now),
        )
        customer_id = cursor.lastrowid
        conn.commit()
        return customer_id
    finally:
        conn.close()


def _insert_message(
    path: Path,
    *,
    customer_id: int,
    content: str,
    is_from_kefu: bool,
    minutes_ago: int = 0,
) -> int:
    conn = sqlite3.connect(str(path))
    try:
        cursor = conn.cursor()
        timestamp = (datetime.now() - timedelta(minutes=minutes_ago)).isoformat()
        cursor.execute(
            """
            INSERT INTO messages (
                customer_id, content, message_type, is_from_kefu,
                timestamp_raw, timestamp_parsed, message_hash, created_at
            ) VALUES (?, ?, 'text', ?, ?, ?, ?, ?)
            """,
            (
                customer_id,
                content,
                1 if is_from_kefu else 0,
                timestamp,
                timestamp,
                f"hash-{customer_id}-{content}-{is_from_kefu}-{timestamp}",
                timestamp,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def _blacklist_customer(path: Path, *, serial: str, name: str, channel: str = "@WeChat") -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """
            INSERT INTO blacklist (
                device_serial, customer_name, customer_channel, reason, is_blacklisted
            ) VALUES (?, ?, ?, ?, 1)
            """,
            (serial, name, channel, "test"),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def temp_db(monkeypatch):
    temp_dir = Path(tempfile.mkdtemp())
    db_path = temp_dir / "followup_blacklist.db"
    _create_test_db(db_path)
    monkeypatch.setenv("WECOM_DB_PATH", str(db_path))
    yield db_path
    sidecar._queues.clear()
    sidecar._sync_states.clear()
    sidecar._waiting_events.clear()
    sidecar._skip_flags.clear()
    shutil.rmtree(temp_dir, ignore_errors=True)


def _build_manager(db_path: Path, *, serial: str = "test-serial") -> tuple[FollowupQueueManager, FollowupAttemptsRepository]:
    manager = FollowupQueueManager(device_serial=serial, db_path=str(db_path))
    manager._settings_cache = FollowUpSettings(
        followup_enabled=True,
        max_followups=5,
        use_ai_reply=False,
        enable_operating_hours=False,
        idle_threshold_minutes=0,
        attempt_intervals=[0, 0, 0],
        message_templates=["hello"],
    )
    manager._settings_cache_time = time.time()
    repo = FollowupAttemptsRepository(str(db_path))
    manager._repository = repo
    manager._executor = MagicMock()
    manager._executor.connect = AsyncMock(return_value=True)
    manager._executor.disconnect = AsyncMock(return_value=None)
    manager._executor.execute = AsyncMock()
    manager._wecom = MagicMock()
    manager._wecom.get_current_screen = AsyncMock(return_value="private_chats")
    manager._wecom.go_back = AsyncMock(return_value=None)
    return manager, repo


@pytest.mark.asyncio
async def test_execute_pending_followups_skips_blacklisted_customer(temp_db):
    customer_id = _seed_customer(temp_db, serial="test-serial", name="BlockedUser")
    last_message_id = _insert_message(
        temp_db,
        customer_id=customer_id,
        content="客服最后一条消息",
        is_from_kefu=True,
        minutes_ago=10,
    )
    _blacklist_customer(temp_db, serial="test-serial", name="BlockedUser")

    manager, repo = _build_manager(temp_db)
    repo.add_or_update(
        device_serial="test-serial",
        customer_name="BlockedUser",
        customer_channel="@WeChat",
        last_kefu_message_id=str(last_message_id),
        last_kefu_message_time=datetime.now() - timedelta(minutes=10),
    )

    result = await manager.execute_pending_followups()
    attempt = repo.get_by_customer("test-serial", "BlockedUser")

    assert result["skipped"] == 1
    assert result["skipped_blacklisted"] == 1
    assert attempt is not None
    assert attempt.status == AttemptStatus.CANCELLED
    manager._executor.execute.assert_not_called()


@pytest.mark.asyncio
async def test_execute_pending_followups_marks_customer_replied_before_send(temp_db):
    customer_id = _seed_customer(temp_db, serial="test-serial", name="RepliedUser")
    last_kefu_message_id = _insert_message(
        temp_db,
        customer_id=customer_id,
        content="客服最后一条消息",
        is_from_kefu=True,
        minutes_ago=20,
    )
    _insert_message(
        temp_db,
        customer_id=customer_id,
        content="客户刚刚回复了",
        is_from_kefu=False,
        minutes_ago=1,
    )

    manager, repo = _build_manager(temp_db)
    repo.add_or_update(
        device_serial="test-serial",
        customer_name="RepliedUser",
        customer_channel="@WeChat",
        last_kefu_message_id=str(last_kefu_message_id),
        last_kefu_message_time=datetime.now() - timedelta(minutes=20),
    )

    result = await manager.execute_pending_followups()
    attempt = repo.get_by_customer("test-serial", "RepliedUser")

    assert result["skipped"] == 1
    assert attempt is not None
    assert attempt.status == AttemptStatus.COMPLETED
    manager._executor.execute.assert_not_called()


def test_process_conversations_fails_closed_when_blacklist_check_errors(temp_db):
    _seed_customer(temp_db, serial="test-serial", name="RiskyUser")
    manager, repo = _build_manager(temp_db)
    conversation = ConversationInfo(
        customer_name="RiskyUser",
        customer_channel="@WeChat",
        customer_id="1",
        last_message_id="m-1",
        last_message_time=datetime.now() - timedelta(minutes=60),
        last_message_sender="kefu",
    )

    with patch(
        "wecom_automation.services.blacklist_service.BlacklistChecker.is_blacklisted",
        side_effect=RuntimeError("db unavailable"),
    ):
        result = manager.process_conversations([conversation])

    assert result["added"] == 0
    assert repo.get_by_customer("test-serial", "RiskyUser") is None


def test_sidecar_send_rejects_blacklisted_contact(temp_db):
    mock_session = MagicMock()
    mock_session.send_message = AsyncMock(return_value=True)
    mock_state = MagicMock()
    mock_state.conversation = MagicMock(contact_name="BlockedUser", channel="@WeChat")
    mock_session.snapshot = AsyncMock(return_value=mock_state)

    with patch.object(sidecar, "get_session", return_value=mock_session), patch(
        "routers.sidecar.BlacklistChecker.is_blacklisted",
        return_value=True,
    ):
        client = TestClient(app)
        response = client.post(
            "/sidecar/test-serial/send",
            json={"message": "hello", "contact_name": "BlockedUser", "channel": "@WeChat"},
        )

    assert response.status_code == 409
    mock_session.send_message.assert_not_called()


def test_sidecar_send_and_save_rejects_blacklisted_contact(temp_db):
    mock_session = MagicMock()
    mock_session.send_message = AsyncMock(return_value=True)
    mock_state = MagicMock()
    mock_state.conversation = MagicMock(contact_name="BlockedUser", channel="@WeChat")
    mock_session.snapshot = AsyncMock(return_value=mock_state)

    with patch.object(sidecar, "get_session", return_value=mock_session), patch(
        "routers.sidecar.BlacklistChecker.is_blacklisted",
        return_value=True,
    ):
        client = TestClient(app)
        response = client.post(
            "/sidecar/test-serial/send-and-save",
            json={"message": "hello", "contact_name": "BlockedUser", "channel": "@WeChat"},
        )

    assert response.status_code == 409
    mock_session.send_message.assert_not_called()


def test_sidecar_queue_send_cancels_blacklisted_message(temp_db):
    mock_session = MagicMock()
    mock_session.send_message = AsyncMock(return_value=True)
    mock_state = MagicMock()
    mock_state.conversation = MagicMock(contact_name="BlockedUser", channel="@WeChat")
    mock_session.snapshot = AsyncMock(return_value=mock_state)

    with patch.object(sidecar, "get_session", return_value=mock_session), patch(
        "routers.sidecar.BlacklistChecker.is_blacklisted",
        return_value=True,
    ):
        client = TestClient(app)
        add_response = client.post(
            "/sidecar/test-serial/queue/add",
            json={"customerName": "BlockedUser", "channel": "@WeChat", "message": "hello"},
        )
        message_id = add_response.json()["id"]
        send_response = client.post(f"/sidecar/test-serial/queue/send/{message_id}")

    assert send_response.status_code == 409
    queue_item = next(item for item in sidecar._queues["test-serial"] if item.id == message_id)
    assert queue_item.status == sidecar.MessageStatus.CANCELLED
    mock_session.send_message.assert_not_called()


def test_sidecar_blacklist_gate_runs_off_event_loop(temp_db):
    """Regression for B1: ``_ensure_contact_not_blacklisted`` must dispatch the
    blocking ``BlacklistChecker.is_blacklisted`` SQLite query off the event
    loop via ``asyncio.to_thread`` so concurrent device sends are not
    serialized.

    A simple structural assertion: the call site must be ``await
    asyncio.to_thread(BlacklistChecker.is_blacklisted, ...)``. If anyone
    reverts the wrap, this test will fail because the mock will be called
    on the same thread as the test (i.e. the event loop thread).
    """
    import asyncio
    import threading

    main_thread_id = threading.get_ident()
    captured: dict[str, object] = {"thread_ids": []}

    def recording_check(*_args, **_kwargs) -> bool:
        captured["thread_ids"].append(threading.get_ident())
        return False

    mock_session = MagicMock()
    mock_session.snapshot = AsyncMock(return_value=MagicMock(conversation=None))

    with patch(
        "routers.sidecar.BlacklistChecker.is_blacklisted",
        side_effect=recording_check,
    ):
        asyncio.run(
            sidecar._ensure_contact_not_blacklisted(
                "test-serial",
                contact_name="SomeUser",
                channel="@WeChat",
                session=mock_session,
            )
        )

    assert captured["thread_ids"], "is_blacklisted was never called"
    # The blocking lookup must run on a worker thread, NOT the event loop
    # thread. This pins the asyncio.to_thread wrap in place.
    assert captured["thread_ids"][0] != main_thread_id, (
        "BlacklistChecker.is_blacklisted ran on the event loop thread. "
        "Regression: did someone remove the asyncio.to_thread wrap in "
        "routers/sidecar.py:_ensure_contact_not_blacklisted? See: docs "
        "handoff '不同设备不能同时运行' bug B1."
    )


def test_process_conversations_persists_attempts_to_control_db(temp_db):
    device_db = temp_db.parent / "device_followup.db"
    device_db.touch()

    manager = FollowupQueueManager(device_serial="test-serial", db_path=str(device_db))
    manager._settings_cache = FollowUpSettings(
        followup_enabled=True,
        max_followups=5,
        use_ai_reply=False,
        enable_operating_hours=False,
        idle_threshold_minutes=0,
        attempt_intervals=[0, 0, 0],
        message_templates=["hello"],
    )
    manager._settings_cache_time = time.time()

    conversation = ConversationInfo(
        customer_name="ControlDbUser",
        customer_channel="@WeChat",
        customer_id="42",
        last_message_id="m-42",
        last_message_time=datetime.now() - timedelta(minutes=30),
        last_message_sender="kefu",
    )

    result = manager.process_conversations([conversation])
    control_repo = FollowupAttemptsRepository(str(temp_db))
    device_repo = FollowupAttemptsRepository(str(device_db))

    assert result["added"] == 1
    assert control_repo.get_by_customer("test-serial", "ControlDbUser") is not None
    assert device_repo.get_by_customer("test-serial", "ControlDbUser") is None


def test_update_blacklist_status_cancels_pending_followups(temp_db):
    conn = sqlite3.connect(str(temp_db))
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO blacklist (
                device_serial, customer_name, customer_channel, reason, is_blacklisted
            ) VALUES (?, ?, ?, ?, 0)
            """,
            ("test-serial", "ManualBlacklistUser", "@WeChat", "seed"),
        )
        entry_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()

    repo = FollowupAttemptsRepository(str(temp_db))
    repo.add_or_update(
        device_serial="test-serial",
        customer_name="ManualBlacklistUser",
        customer_channel="@WeChat",
        last_kefu_message_id="msg-1",
        last_kefu_message_time=datetime.now() - timedelta(minutes=10),
    )

    client = TestClient(app)
    response = client.post(
        "/api/blacklist/update-status",
        json={"id": entry_id, "is_blacklisted": True},
    )

    attempt = repo.get_by_customer("test-serial", "ManualBlacklistUser")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert attempt is not None
    assert attempt.status == AttemptStatus.CANCELLED
