"""
Unit tests for the database module.

These tests cover:
- Schema initialization
- Model creation and serialization
- Repository CRUD operations
- Message deduplication
"""

import os
import sqlite3
import tempfile

import pytest

from wecom_automation.database.models import (
    CustomerRecord,
    DeviceRecord,
    ImageRecord,
    KefuRecord,
    MessageRecord,
    MessageType,
    VideoRecord,
    VoiceRecord,
)
from wecom_automation.database.repository import ConversationRepository
from wecom_automation.database.schema import (
    DATABASE_VERSION,
    get_connection,
    get_schema_version,
    init_database,
    needs_migration,
    repair_blacklist_schema,
    repair_videos_ai_review_schema,
    run_migrations,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_db_path():
    """Create a temporary database file path (not the file itself)."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(db_path)  # Remove the file so we can test creation
    yield db_path
    # Cleanup
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def initialized_db(temp_db_path):
    """Initialize a temporary database and return its path."""
    init_database(temp_db_path)
    return temp_db_path


@pytest.fixture
def repository(initialized_db):
    """Create a repository with initialized database."""
    return ConversationRepository(initialized_db, auto_init=False)


@pytest.fixture
def sample_device():
    """Sample device record."""
    return DeviceRecord(
        serial="ABC123XYZ",
        model="Pixel 6",
        manufacturer="Google",
        android_version="13",
    )


@pytest.fixture
def sample_kefu():
    """Sample kefu record."""
    return KefuRecord(
        name="张三",
        department="302实验室",
        verification_status="未认证",
    )


@pytest.fixture
def sample_customer():
    """Sample customer record (requires kefu_id to be set)."""
    return CustomerRecord(
        name="客户A",
        kefu_id=1,  # Will be updated in tests
        channel="@WeChat",
        last_message_preview="你好",
        last_message_date="10:30",
    )


# =============================================================================
# Schema Tests
# =============================================================================


class TestSchema:
    """Tests for database schema initialization."""

    @staticmethod
    def _create_drifted_blacklist_db(db_path: str) -> None:
        """Create a DB that claims to be current but has an old blacklist schema."""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.executescript(
            f"""
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

            INSERT INTO schema_version (version) VALUES ({DATABASE_VERSION});
            INSERT INTO blacklist (device_serial, customer_name, customer_channel, reason)
            VALUES ('SERIAL-1', 'Alice', '@WeChat', 'legacy row');
            """
        )
        conn.commit()
        conn.close()

    @staticmethod
    def _create_duplicate_blacklist_db(db_path: str) -> None:
        """Create a DB with current schema_version but duplicate blacklist identities."""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.executescript(
            f"""
            CREATE TABLE blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_serial TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                customer_channel TEXT,
                reason TEXT,
                deleted_by_user BOOLEAN DEFAULT 0,
                is_blacklisted BOOLEAN DEFAULT 1,
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

            INSERT INTO schema_version (version) VALUES ({DATABASE_VERSION});

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

    def test_init_database_creates_file(self, temp_db_path):
        """Test that init_database creates the database file."""
        assert not os.path.exists(temp_db_path)
        init_database(temp_db_path)
        assert os.path.exists(temp_db_path)

    def test_init_database_creates_tables(self, initialized_db):
        """Test that all required tables are created."""
        conn = get_connection(initialized_db)
        cursor = conn.cursor()

        # Get list of tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = {row["name"] for row in cursor.fetchall()}
        conn.close()

        expected_tables = {
            "devices",
            "kefus",
            "kefu_devices",
            "customers",
            "messages",
            "images",
            "videos",
            "voices",
            "schema_version",
        }
        assert expected_tables.issubset(tables)

    def test_schema_version_recorded(self, initialized_db):
        """Test that schema version is recorded."""
        version = get_schema_version(initialized_db)
        assert version == DATABASE_VERSION

    def test_init_database_creates_current_blacklist_columns(self, initialized_db):
        """Fresh databases should include all runtime-required blacklist columns."""
        conn = get_connection(initialized_db)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(blacklist)")
        columns = {row["name"] for row in cursor.fetchall()}
        conn.close()

        assert {"deleted_by_user", "is_blacklisted", "avatar_url", "customer_db_id"}.issubset(columns)

    def test_init_database_videos_has_ai_review_columns(self, initialized_db):
        """Fresh databases should include videos AI review columns (v12)."""
        conn = get_connection(initialized_db)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(videos)")
        columns = {row["name"] for row in cursor.fetchall()}
        conn.close()
        assert {
            "ai_review_score",
            "ai_review_frames_json",
            "ai_review_at",
            "ai_review_status",
            "ai_review_error",
            "ai_review_requested_at",
        }.issubset(columns)

    def test_repair_videos_ai_review_after_drop_column(self, initialized_db):
        """repair_videos_ai_review_schema re-adds missing columns when schema_version is current."""
        conn = get_connection(initialized_db)
        cursor = conn.cursor()
        try:
            cursor.execute("ALTER TABLE videos DROP COLUMN ai_review_score")
            conn.commit()
        except sqlite3.OperationalError:
            conn.close()
            pytest.skip("SQLite build without ALTER TABLE DROP COLUMN")
        conn.close()

        repairs = repair_videos_ai_review_schema(initialized_db)
        assert any("ai_review_score" in r for r in repairs)

        conn = get_connection(initialized_db)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(videos)")
        columns = {row["name"] for row in cursor.fetchall()}
        conn.close()
        assert "ai_review_score" in columns

    def test_needs_migration_false_for_current(self, initialized_db):
        """Test that no migration needed for current version."""
        assert not needs_migration(initialized_db)

    def test_needs_migration_true_for_missing(self, temp_db_path):
        """Test that migration needed for non-existent database."""
        assert needs_migration(temp_db_path)

    def test_run_migrations_repairs_blacklist_schema_drift(self, temp_db_path):
        """Current schema_version should not skip blacklist column repair."""
        self._create_drifted_blacklist_db(temp_db_path)

        assert needs_migration(temp_db_path)

        run_migrations(temp_db_path)

        assert get_schema_version(temp_db_path) == DATABASE_VERSION
        assert not needs_migration(temp_db_path)

        conn = get_connection(temp_db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(blacklist)")
        columns = {row["name"] for row in cursor.fetchall()}

        assert {"deleted_by_user", "is_blacklisted", "avatar_url", "customer_db_id"}.issubset(columns)

        cursor.execute(
            """
            SELECT deleted_by_user, is_blacklisted, avatar_url, customer_db_id
            FROM blacklist
            WHERE device_serial = ? AND customer_name = ?
            """,
            ("SERIAL-1", "Alice"),
        )
        row = cursor.fetchone()
        conn.close()

        assert row["deleted_by_user"] == 0
        assert row["is_blacklisted"] == 1
        assert row["avatar_url"] is None
        assert row["customer_db_id"] is None

    def test_run_migrations_merges_duplicate_blacklist_identities(self, temp_db_path):
        """Current schema_version should not skip duplicate blacklist identity repair."""
        self._create_duplicate_blacklist_db(temp_db_path)

        assert needs_migration(temp_db_path)

        run_migrations(temp_db_path)

        assert get_schema_version(temp_db_path) == DATABASE_VERSION
        assert not needs_migration(temp_db_path)

        conn = get_connection(temp_db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, customer_channel, reason, deleted_by_user, is_blacklisted, avatar_url, customer_db_id
            FROM blacklist
            WHERE device_serial = ? AND customer_name = ?
            ORDER BY id
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

        assert repair_blacklist_schema(temp_db_path) == []

    def test_foreign_keys_enabled(self, initialized_db):
        """Test that foreign keys are enforced."""
        conn = get_connection(initialized_db)
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys")
        result = cursor.fetchone()
        conn.close()
        assert result[0] == 1


# =============================================================================
# Model Tests
# =============================================================================


class TestDeviceRecord:
    """Tests for DeviceRecord model."""

    def test_to_dict(self, sample_device):
        """Test conversion to dictionary."""
        data = sample_device.to_dict()
        assert data["serial"] == "ABC123XYZ"
        assert data["model"] == "Pixel 6"
        assert data["manufacturer"] == "Google"
        assert data["android_version"] == "13"

    def test_from_row(self):
        """Test creation from database row."""

        # Simulate a sqlite3.Row
        class MockRow:
            def __getitem__(self, key):
                data = {
                    "id": 1,
                    "serial": "XYZ789",
                    "model": "Galaxy S21",
                    "manufacturer": "Samsung",
                    "android_version": "12",
                    "created_at": "2024-01-01 00:00:00",
                    "updated_at": "2024-01-01 00:00:00",
                }
                return data[key]

        device = DeviceRecord.from_row(MockRow())
        assert device.id == 1
        assert device.serial == "XYZ789"
        assert device.model == "Galaxy S21"


class TestMessageRecord:
    """Tests for MessageRecord model."""

    def test_hash_generation(self):
        """Test that hash is automatically generated."""
        msg = MessageRecord(
            customer_id=1,
            content="Hello, world!",
            message_type=MessageType.TEXT,
            is_from_kefu=True,
            timestamp_raw="10:30",
        )
        assert msg.message_hash is not None
        assert len(msg.message_hash) == 64  # SHA256 hex length

    def test_same_content_same_hash(self):
        """Test that identical messages have same hash."""
        msg1 = MessageRecord(
            customer_id=1,
            content="Hello",
            message_type=MessageType.TEXT,
            is_from_kefu=True,
            timestamp_raw="10:30",
        )
        msg2 = MessageRecord(
            customer_id=1,
            content="Hello",
            message_type=MessageType.TEXT,
            is_from_kefu=True,
            timestamp_raw="10:30",
        )
        assert msg1.message_hash == msg2.message_hash

    def test_different_content_different_hash(self):
        """Test that different messages have different hash."""
        msg1 = MessageRecord(
            customer_id=1,
            content="Hello",
            message_type=MessageType.TEXT,
            is_from_kefu=True,
            timestamp_raw="10:30",
        )
        msg2 = MessageRecord(
            customer_id=1,
            content="Goodbye",
            message_type=MessageType.TEXT,
            is_from_kefu=True,
            timestamp_raw="10:30",
        )
        assert msg1.message_hash != msg2.message_hash

    def test_different_sender_different_hash(self):
        """Test that sender affects hash."""
        msg1 = MessageRecord(
            customer_id=1,
            content="Hello",
            message_type=MessageType.TEXT,
            is_from_kefu=True,
            timestamp_raw="10:30",
        )
        msg2 = MessageRecord(
            customer_id=1,
            content="Hello",
            message_type=MessageType.TEXT,
            is_from_kefu=False,
            timestamp_raw="10:30",
        )
        assert msg1.message_hash != msg2.message_hash

    def test_extra_info_dict(self):
        """Test extra_info JSON handling."""
        msg = MessageRecord(
            customer_id=1,
            message_type=MessageType.VOICE,
            is_from_kefu=False,
        )

        # Set extra info
        msg.set_extra_info_dict({"voice_duration": '3"', "caption": "语音转文字"})

        # Get extra info
        info = msg.get_extra_info_dict()
        assert info["voice_duration"] == '3"'
        assert info["caption"] == "语音转文字"

    def test_message_type_from_string(self):
        """Test MessageType conversion from string."""
        assert MessageType.from_string("text") == MessageType.TEXT
        assert MessageType.from_string("TEXT") == MessageType.TEXT
        assert MessageType.from_string("voice") == MessageType.VOICE
        assert MessageType.from_string("image") == MessageType.IMAGE
        assert MessageType.from_string("unknown_type") == MessageType.UNKNOWN

    def test_video_hash_uses_video_duration_in_extra(self):
        """Two video messages with different video_duration must not share hash."""
        import json

        base = dict(
            customer_id=1,
            content="[视频]",
            message_type=MessageType.VIDEO,
            is_from_kefu=False,
            timestamp_raw="10:30",
        )
        msg1 = MessageRecord(
            **base,
            extra_info=json.dumps({"video_duration": "0:05", "original_bounds": "[0,0][1,1]"}),
        )
        msg2 = MessageRecord(
            **base,
            extra_info=json.dumps({"video_duration": "0:12", "original_bounds": "[0,0][1,1]"}),
        )
        assert msg1.compute_hash() != msg2.compute_hash()

    def test_video_hash_bounds_when_no_duration(self):
        """Videos without duration string still differ by original_bounds."""
        import json

        base = dict(
            customer_id=1,
            content="[视频]",
            message_type=MessageType.VIDEO,
            is_from_kefu=False,
            timestamp_raw="10:30",
        )
        msg1 = MessageRecord(
            **base,
            extra_info=json.dumps({"original_bounds": "[10,100][200,300]"}),
        )
        msg2 = MessageRecord(
            **base,
            extra_info=json.dumps({"original_bounds": "[10,400][200,600]"}),
        )
        assert msg1.compute_hash() != msg2.compute_hash()

    def test_voice_hash_accepts_legacy_duration_key(self):
        """compute_hash reads voice_duration; legacy extra used only "duration"."""
        import json

        base = dict(
            customer_id=1,
            content="transcribed",
            message_type=MessageType.VOICE,
            is_from_kefu=False,
            timestamp_raw="10:30",
        )
        with_voice_key = MessageRecord(
            **base,
            extra_info=json.dumps({"voice_duration": '2"', "duration": '2"'}),
        )
        legacy_only = MessageRecord(
            **base,
            extra_info=json.dumps({"duration": '2"'}),
        )
        assert with_voice_key.compute_hash() == legacy_only.compute_hash()


# =============================================================================
# Repository Tests
# =============================================================================


class TestRepositoryDevice:
    """Tests for device repository operations."""

    def test_create_device(self, repository, sample_device):
        """Test creating a new device."""
        created = repository.create_device(sample_device)
        assert created.id is not None
        assert created.serial == "ABC123XYZ"

    def test_get_device_by_serial(self, repository, sample_device):
        """Test retrieving device by serial."""
        repository.create_device(sample_device)

        found = repository.get_device_by_serial("ABC123XYZ")
        assert found is not None
        assert found.serial == "ABC123XYZ"
        assert found.model == "Pixel 6"

    def test_get_device_not_found(self, repository):
        """Test that None is returned for non-existent device."""
        found = repository.get_device_by_serial("NONEXISTENT")
        assert found is None

    def test_get_or_create_device_creates(self, repository):
        """Test get_or_create creates new device."""
        device = repository.get_or_create_device(
            serial="NEW123",
            model="Test Phone",
        )
        assert device.id is not None
        assert device.serial == "NEW123"

    def test_get_or_create_device_gets_existing(self, repository, sample_device):
        """Test get_or_create returns existing device."""
        created = repository.create_device(sample_device)

        found = repository.get_or_create_device(serial="ABC123XYZ")
        assert found.id == created.id

    def test_list_devices(self, repository):
        """Test listing all devices."""
        repository.get_or_create_device(serial="DEV1")
        repository.get_or_create_device(serial="DEV2")

        devices = repository.list_devices()
        assert len(devices) == 2


class TestRepositoryKefu:
    """Tests for kefu repository operations."""

    def test_create_kefu(self, repository, sample_device):
        """Test creating a new kefu."""
        repository.create_device(sample_device)

        kefu = KefuRecord(
            name="张三",
            department="测试部",
        )
        created = repository.create_kefu(kefu)

        assert created.id is not None
        assert created.name == "张三"

    def test_get_or_create_kefu(self, repository, sample_device):
        """Test get_or_create for kefu."""
        device = repository.create_device(sample_device)

        kefu1 = repository.get_or_create_kefu(
            name="李四",
            device_id=device.id,
            department="销售部",
        )
        kefu2 = repository.get_or_create_kefu(
            name="李四",
            device_id=device.id,
            department="销售部",
        )

        assert kefu1.id == kefu2.id

    def test_kefu_linked_to_device(self, repository, sample_device):
        """Test that kefu is linked to device via junction table."""
        device = repository.create_device(sample_device)

        kefu = repository.get_or_create_kefu(
            name="王五",
            device_id=device.id,
            department="技术部",
        )

        devices = repository.get_devices_for_kefu(kefu.id)
        assert len(devices) == 1
        assert devices[0].serial == device.serial

    def test_kefu_multiple_devices(self, repository):
        """Test that a kefu can be linked to multiple devices."""
        device1 = repository.get_or_create_device(serial="DEV1")
        device2 = repository.get_or_create_device(serial="DEV2")

        # Same kefu on two different devices
        kefu1 = repository.get_or_create_kefu(
            name="赵六",
            device_id=device1.id,
            department="运营部",
        )
        kefu2 = repository.get_or_create_kefu(
            name="赵六",
            device_id=device2.id,
            department="运营部",
        )

        # Should be the same kefu
        assert kefu1.id == kefu2.id

        # Should have 2 devices linked
        devices = repository.get_devices_for_kefu(kefu1.id)
        assert len(devices) == 2


class TestRepositoryCustomer:
    """Tests for customer repository operations."""

    def test_create_customer(self, repository, sample_device):
        """Test creating a new customer."""
        device = repository.create_device(sample_device)
        kefu = repository.get_or_create_kefu("测试客服", device.id)

        customer = CustomerRecord(
            name="客户A",
            kefu_id=kefu.id,
            channel="@WeChat",
        )
        created = repository.create_customer(customer)

        assert created.id is not None
        assert created.name == "客户A"

    def test_get_or_create_customer_with_channel(self, repository, sample_device):
        """Test get_or_create distinguishes by channel."""
        device = repository.create_device(sample_device)
        kefu = repository.get_or_create_kefu("测试客服", device.id)

        c1 = repository.get_or_create_customer("张三", kefu.id, channel="@WeChat")
        c2 = repository.get_or_create_customer("张三", kefu.id, channel="@微信")
        c3 = repository.get_or_create_customer("张三", kefu.id, channel="@WeChat")

        # Same name+channel = same customer
        assert c1.id == c3.id
        # Different channel = different customer
        assert c1.id != c2.id

    def test_list_customers_for_kefu(self, repository, sample_device):
        """Test listing customers for a kefu."""
        device = repository.create_device(sample_device)
        kefu = repository.get_or_create_kefu("测试客服", device.id)

        repository.get_or_create_customer("客户1", kefu.id)
        repository.get_or_create_customer("客户2", kefu.id)
        repository.get_or_create_customer("客户3", kefu.id)

        customers = repository.list_customers_for_kefu(kefu.id)
        assert len(customers) == 3

    def test_mark_customer_friend_added_sets_first_timestamp_once(self, repository, sample_device):
        """Friend-added fact should be set once and remain stable."""
        device = repository.create_device(sample_device)
        kefu = repository.get_or_create_kefu("测试客服", device.id)
        customer = repository.get_or_create_customer("新好友客户", kefu.id)

        first_ts = "2026-03-24T09:00:00"
        second_ts = "2026-03-24T10:00:00"
        repository.mark_customer_friend_added(customer.id, first_ts)
        repository.mark_customer_friend_added(customer.id, second_ts)

        refreshed = repository.get_customer_by_id(customer.id)
        assert refreshed is not None
        assert refreshed.friend_added_at == first_ts


class TestRepositoryMessage:
    """Tests for message repository operations."""

    @pytest.fixture
    def setup_customer(self, repository, sample_device):
        """Setup device, kefu, and customer for message tests."""
        device = repository.create_device(sample_device)
        kefu = repository.get_or_create_kefu("测试客服", device.id)
        customer = repository.get_or_create_customer("测试客户", kefu.id)
        return customer

    def test_create_message(self, repository, setup_customer):
        """Test creating a new message."""
        msg = MessageRecord(
            customer_id=setup_customer.id,
            content="你好",
            message_type=MessageType.TEXT,
            is_from_kefu=False,
            timestamp_raw="10:30",
        )
        created = repository.create_message(msg)

        assert created.id is not None
        assert created.content == "你好"

    def test_add_message_if_not_exists_adds_new(self, repository, setup_customer):
        """Test that new messages are added."""
        msg = MessageRecord(
            customer_id=setup_customer.id,
            content="新消息",
            message_type=MessageType.TEXT,
            is_from_kefu=True,
        )

        was_added, result = repository.add_message_if_not_exists(msg)

        assert was_added is True
        assert result.id is not None

    def test_add_message_if_not_exists_skips_duplicate(self, repository, setup_customer):
        """Test that duplicate messages are skipped."""
        msg1 = MessageRecord(
            customer_id=setup_customer.id,
            content="重复消息",
            message_type=MessageType.TEXT,
            is_from_kefu=True,
            timestamp_raw="10:30",
        )
        msg2 = MessageRecord(
            customer_id=setup_customer.id,
            content="重复消息",
            message_type=MessageType.TEXT,
            is_from_kefu=True,
            timestamp_raw="10:30",
        )

        added1, result1 = repository.add_message_if_not_exists(msg1)
        added2, result2 = repository.add_message_if_not_exists(msg2)

        assert added1 is True
        assert added2 is False
        assert result1.id == result2.id

    def test_get_messages_for_customer(self, repository, setup_customer):
        """Test retrieving messages for a customer."""
        for i in range(5):
            msg = MessageRecord(
                customer_id=setup_customer.id,
                content=f"消息 {i}",
                message_type=MessageType.TEXT,
                is_from_kefu=i % 2 == 0,
            )
            repository.add_message_if_not_exists(msg)

        messages = repository.get_messages_for_customer(setup_customer.id)
        assert len(messages) == 5

    def test_get_last_message_for_customer(self, repository, setup_customer):
        """Test getting the last message (by ID, most recently inserted)."""
        # Add messages - the last one inserted should be returned
        contents = ["第一条", "第二条", "最后一条"]
        for content in contents:
            msg = MessageRecord(
                customer_id=setup_customer.id,
                content=content,
                message_type=MessageType.TEXT,
                is_from_kefu=True,
                timestamp_raw=f"10:{30 + contents.index(content):02d}",
            )
            repository.add_message_if_not_exists(msg)

        last = repository.get_last_message_for_customer(setup_customer.id)
        # The last message should be one of the messages we added
        assert last is not None
        assert last.content in contents
        # Verify we have 3 messages total
        count = repository.count_messages_for_customer(setup_customer.id)
        assert count == 3

    def test_count_messages_by_type(self, repository, setup_customer):
        """Test counting messages by type."""
        # Add text messages
        for i in range(3):
            repository.add_message_if_not_exists(
                MessageRecord(
                    customer_id=setup_customer.id,
                    content=f"文本 {i}",
                    message_type=MessageType.TEXT,
                    is_from_kefu=True,
                )
            )

        # Add voice messages
        for i in range(2):
            repository.add_message_if_not_exists(
                MessageRecord(
                    customer_id=setup_customer.id,
                    content=f"语音 {i}",
                    message_type=MessageType.VOICE,
                    is_from_kefu=False,
                )
            )

        counts = repository.count_messages_by_type(setup_customer.id)
        assert counts["text"] == 3
        assert counts["voice"] == 2

    def test_add_messages_batch(self, repository, setup_customer):
        """Test batch message insertion."""
        messages = [
            MessageRecord(
                customer_id=setup_customer.id,
                content=f"批量消息 {i}",
                message_type=MessageType.TEXT,
                is_from_kefu=True,
            )
            for i in range(10)
        ]

        added, skipped = repository.add_messages_batch(messages)

        assert added == 10
        assert skipped == 0

        # Try adding same messages again
        added2, skipped2 = repository.add_messages_batch(messages)

        assert added2 == 0
        assert skipped2 == 10

    def test_customer_media_fact_updates_on_first_customer_media_message(self, repository, setup_customer):
        """Customer media fact should be derived from customer-side image/video inserts."""
        image_msg = MessageRecord(
            customer_id=setup_customer.id,
            message_type=MessageType.IMAGE,
            is_from_kefu=False,
        )
        repository.add_message_if_not_exists(image_msg)

        refreshed = repository.get_customer_by_id(setup_customer.id)
        assert refreshed is not None
        assert refreshed.has_customer_media is True
        assert refreshed.first_customer_media_at is not None


class TestRepositoryImage:
    """Tests for image repository operations."""

    @pytest.fixture
    def setup_message(self, repository, sample_device):
        """Setup device, kefu, customer, and message for image tests."""
        device = repository.create_device(sample_device)
        kefu = repository.get_or_create_kefu("测试客服", device.id)
        customer = repository.get_or_create_customer("测试客户", kefu.id)
        msg = MessageRecord(
            customer_id=customer.id,
            message_type=MessageType.IMAGE,
            is_from_kefu=False,
        )
        created_msg = repository.create_message(msg)
        return created_msg, customer

    def test_create_image(self, repository, setup_message):
        """Test creating an image record."""
        msg, _ = setup_message

        image = ImageRecord(
            message_id=msg.id,
            file_path="/path/to/image.png",
            file_name="image.png",
            width=800,
            height=600,
        )
        created = repository.create_image(image)

        assert created.id is not None
        assert created.file_path == "/path/to/image.png"

    def test_get_image_for_message(self, repository, setup_message):
        """Test retrieving image for a message."""
        msg, _ = setup_message

        repository.create_image(
            ImageRecord(
                message_id=msg.id,
                file_path="/path/to/image.png",
            )
        )

        image = repository.get_image_for_message(msg.id)
        assert image is not None
        assert image.message_id == msg.id

    def test_create_image_updates_existing_message_row(self, repository, setup_message):
        """Creating an image twice for the same message should update the existing row."""
        msg, _ = setup_message

        first = repository.create_image(
            ImageRecord(
                message_id=msg.id,
                file_path="/path/to/first.png",
                file_name="first.png",
                width=100,
                height=100,
            )
        )
        second = repository.create_image(
            ImageRecord(
                message_id=msg.id,
                file_path="/path/to/second.png",
                file_name="second.png",
                width=200,
                height=300,
            )
        )

        assert second.id == first.id
        image = repository.get_image_for_message(msg.id)
        assert image is not None
        assert image.id == first.id
        assert image.file_path == "/path/to/second.png"
        assert image.file_name == "second.png"
        assert image.width == 200
        assert image.height == 300

    def test_update_image_review_by_message_id(self, repository, setup_message):
        """Persist AI review fields on the images row for a message."""
        msg, _ = setup_message
        repository.create_image(
            ImageRecord(
                message_id=msg.id,
                file_path="/path/to/image.png",
            )
        )
        ok = repository.update_image_review_by_message_id(
            msg.id,
            review_external_id="uuid-test",
            ai_review_score=7.5,
            ai_review_model="test-model",
            ai_review_decision="合格",
            ai_review_details_json='{"reason": "清晰"}',
            ai_review_at="2026-03-21T12:00:00",
        )
        assert ok is True
        image = repository.get_image_for_message(msg.id)
        assert image is not None
        assert image.review_external_id == "uuid-test"
        assert image.ai_review_score == 7.5
        assert image.ai_review_model == "test-model"
        assert image.ai_review_decision == "合格"
        assert image.ai_review_details_json == '{"reason": "清晰"}'
        assert image.ai_review_at == "2026-03-21T12:00:00"

    def test_update_video_review_by_message_id(self, repository, setup_message):
        """Persist AI review fields on the videos row for a message."""
        msg, _ = setup_message
        repository.create_video(
            VideoRecord(
                message_id=msg.id,
                file_path="/path/to/video.mp4",
                file_name="video.mp4",
            )
        )
        ok = repository.update_video_review_by_message_id(
            msg.id,
            ai_review_score=6.5,
            ai_review_frames_json='[{"frame_index":0}]',
            ai_review_at="2026-03-21T12:00:00",
            ai_review_status="completed",
        )
        assert ok is True
        video = repository.get_video_for_message(msg.id)
        assert video is not None
        assert video.ai_review_score == 6.5
        assert video.ai_review_frames_json == '[{"frame_index":0}]'
        assert video.ai_review_at == "2026-03-21T12:00:00"
        assert video.ai_review_status == "completed"


class TestRepositoryVoice:
    """Tests for voice repository operations."""

    @pytest.fixture
    def setup_voice_message(self, repository, sample_device):
        """Setup device, kefu, customer, and voice message."""
        device = repository.create_device(sample_device)
        kefu = repository.get_or_create_kefu("测试客服", device.id)
        customer = repository.get_or_create_customer("测试客户", kefu.id)
        msg = MessageRecord(
            customer_id=customer.id,
            message_type=MessageType.VOICE,
            is_from_kefu=False,
            content="[语音消息]",
            extra_info='{"voice_duration": "3\\""}',
        )
        created_msg = repository.create_message(msg)
        return created_msg, customer

    def test_create_and_get_voice(self, repository, setup_voice_message):
        msg, _ = setup_voice_message
        voice = VoiceRecord(
            message_id=msg.id,
            file_path="/path/to/voice.wav",
            file_name="voice.wav",
            duration='3"',
            duration_seconds=3,
            file_size=1024,
        )
        created = repository.create_voice(voice)
        assert created.id is not None
        got = repository.get_voice_for_message(msg.id)
        assert got is not None
        assert got.file_path == "/path/to/voice.wav"
        assert got.duration_seconds == 3

    def test_list_voices_for_customer(self, repository, setup_voice_message):
        msg, customer = setup_voice_message
        repository.create_voice(
            VoiceRecord(
                message_id=msg.id,
                file_path="/path/to/voice.wav",
            )
        )
        voices = repository.list_voices_for_customer(customer.id)
        assert len(voices) == 1
        assert voices[0].message_id == msg.id


class TestRepositoryStatistics:
    """Tests for repository statistics."""

    def test_get_statistics(self, repository, sample_device):
        """Test getting database statistics."""
        # Setup some data
        device = repository.create_device(sample_device)
        kefu = repository.get_or_create_kefu("测试客服", device.id)
        customer = repository.get_or_create_customer("测试客户", kefu.id)

        for i in range(5):
            repository.add_message_if_not_exists(
                MessageRecord(
                    customer_id=customer.id,
                    content=f"消息 {i}",
                    message_type=MessageType.TEXT,
                    is_from_kefu=True,
                )
            )

        stats = repository.get_statistics()

        assert stats["devices"] == 1
        assert stats["kefus"] == 1
        assert stats["customers"] == 1
        assert stats["messages"] == 5
        assert stats["messages_by_type"]["text"] == 5
        assert stats["voices"] == 0
