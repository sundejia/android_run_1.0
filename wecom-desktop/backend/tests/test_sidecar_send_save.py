"""
Tests for the send-and-save sidecar endpoint.

This tests the API that allows sending a message and immediately saving it
to the database, useful when sync is running and we want to ensure the
message is recorded without waiting for sync to capture it.
"""

import sys
import pytest
import sqlite3
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock droidrun before importing anything else
mock_droidrun = MagicMock()
mock_droidrun.tools = MagicMock()
mock_droidrun.tools.adb = MagicMock()
mock_droidrun.tools.adb.AdbTools = MagicMock()
sys.modules["droidrun"] = mock_droidrun
sys.modules["droidrun.tools"] = mock_droidrun.tools
sys.modules["droidrun.tools.adb"] = mock_droidrun.tools.adb

from fastapi.testclient import TestClient


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test.db"

    # Create schema
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Create tables
    cursor.executescript("""
        CREATE TABLE devices (
            id INTEGER PRIMARY KEY,
            serial TEXT UNIQUE NOT NULL,
            model TEXT,
            manufacturer TEXT,
            android_version TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        
        CREATE TABLE kefus (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            department TEXT,
            verification_status TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        
        CREATE TABLE kefu_devices (
            id INTEGER PRIMARY KEY,
            kefu_id INTEGER NOT NULL,
            device_id INTEGER NOT NULL,
            FOREIGN KEY (kefu_id) REFERENCES kefus(id),
            FOREIGN KEY (device_id) REFERENCES devices(id)
        );
        
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            kefu_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            channel TEXT,
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (kefu_id) REFERENCES kefus(id)
        );
        
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            content TEXT,
            message_type TEXT NOT NULL,
            is_from_kefu INTEGER NOT NULL,
            timestamp_raw TEXT,
            timestamp_parsed TEXT,
            extra_info TEXT,
            message_hash TEXT,
            created_at TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );
    """)

    # Insert test data
    now = datetime.now().isoformat()
    cursor.execute(
        "INSERT INTO devices (serial, model, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("test-serial", "TestPhone", now, now),
    )
    device_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO kefus (name, department, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("TestKefu", "Support", now, now),
    )
    kefu_id = cursor.lastrowid

    cursor.execute("INSERT INTO kefu_devices (kefu_id, device_id) VALUES (?, ?)", (kefu_id, device_id))

    cursor.execute(
        "INSERT INTO customers (kefu_id, name, channel, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (kefu_id, "TestCustomer", "WeChat", now, now),
    )
    customer_id = cursor.lastrowid

    conn.commit()
    conn.close()

    yield db_path

    # Cleanup
    shutil.rmtree(temp_dir)


@pytest.fixture
def mock_session():
    """Create a mock SidecarSession."""
    session = MagicMock()
    session.send_message = AsyncMock(return_value=True)

    # Mock snapshot to return conversation info
    mock_state = MagicMock()
    mock_state.conversation = MagicMock()
    mock_state.conversation.contact_name = "TestCustomer"
    mock_state.conversation.channel = "WeChat"
    session.snapshot = AsyncMock(return_value=mock_state)

    return session


class TestSendAndSave:
    """Tests for the send-and-save endpoint."""

    def test_send_and_save_success(self, temp_db, mock_session):
        """Test successful send and save."""
        # Import after droidrun mock is set up
        from main import app
        from routers import sidecar

        # Patch get_session to return mock
        with patch.object(sidecar, "get_session", return_value=mock_session):
            # Patch database path
            with patch.object(sidecar, "get_db_path", return_value=temp_db):
                client = TestClient(app)

                response = client.post(
                    "/sidecar/test-serial/send-and-save",
                    json={"message": "Test message", "contact_name": "TestCustomer", "channel": "WeChat"},
                )

                assert response.status_code == 200
                data = response.json()
                assert data["success"] is True
                assert data["message_saved"] is True

                # Verify message was saved
                conn = sqlite3.connect(str(temp_db))
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM messages WHERE content = ?", ("Test message",))
                row = cursor.fetchone()
                conn.close()

                assert row is not None
                assert row["is_from_kefu"] == 1
                assert row["message_type"] == "text"

    def test_send_and_save_empty_message(self, mock_session):
        """Test that empty messages are rejected."""
        from main import app
        from routers import sidecar

        with patch.object(sidecar, "get_session", return_value=mock_session):
            client = TestClient(app)

            response = client.post("/sidecar/test-serial/send-and-save", json={"message": "   "})

            assert response.status_code == 400

    def test_send_and_save_send_fails(self, temp_db, mock_session):
        """Test handling when send fails."""
        mock_session.send_message = AsyncMock(return_value=False)

        from main import app
        from routers import sidecar

        with patch.object(sidecar, "get_session", return_value=mock_session):
            with patch.object(sidecar, "get_db_path", return_value=temp_db):
                client = TestClient(app)

                response = client.post("/sidecar/test-serial/send-and-save", json={"message": "Test message"})

                assert response.status_code == 200
                data = response.json()
                assert data["success"] is False
                assert data["message_saved"] is False

    def test_send_and_save_uses_session_state(self, temp_db, mock_session):
        """Test that session state is used when contact info not provided."""
        from main import app
        from routers import sidecar

        with patch.object(sidecar, "get_session", return_value=mock_session):
            with patch.object(sidecar, "get_db_path", return_value=temp_db):
                client = TestClient(app)

                # Send without contact_name/channel - should use session state
                response = client.post("/sidecar/test-serial/send-and-save", json={"message": "Test from session"})

                assert response.status_code == 200
                data = response.json()
                assert data["success"] is True
                # Note: message_saved depends on finding customer in DB

    def test_send_and_save_no_customer_found(self, temp_db, mock_session):
        """Test handling when customer is not found in database."""
        from main import app
        from routers import sidecar

        with patch.object(sidecar, "get_session", return_value=mock_session):
            with patch.object(sidecar, "get_db_path", return_value=temp_db):
                client = TestClient(app)

                response = client.post(
                    "/sidecar/test-serial/send-and-save",
                    json={"message": "Test message", "contact_name": "NonExistentCustomer"},
                )

                assert response.status_code == 200
                data = response.json()
                assert data["success"] is True  # Send succeeded
                assert data["message_saved"] is False  # Save failed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
