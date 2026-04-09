"""
Integration tests for the full WeCom automation workflow.

These tests require a connected Android device with WeCom installed.
Run with: pytest tests/integration/ -v -m integration

Note: These tests interact with a real device and may take time to complete.
"""

import asyncio
from pathlib import Path

import pytest

from wecom_automation.core.config import Config
from wecom_automation.services.wecom_service import WeComService

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


class TestWeComWorkflow:
    """
    Integration tests for the complete WeCom workflow.

    Prerequisites:
    - Android device connected via ADB
    - WeCom installed on the device
    - Device is unlocked
    """

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return Config(
            debug=True,
            capture_avatars=False,  # Skip avatars for faster tests
        )

    @pytest.fixture
    def service(self, config):
        """Create WeComService instance."""
        return WeComService(config)

    @pytest.mark.asyncio
    async def test_launch_wecom(self, service):
        """Test launching WeCom app."""
        await service.launch_wecom(wait_for_ready=True)
        # If we get here without exception, launch succeeded

    @pytest.mark.asyncio
    async def test_switch_to_private_chats(self, service):
        """Test switching to Private Chats filter."""
        # First launch the app
        await service.launch_wecom()

        # Then switch to private chats
        success = await service.switch_to_private_chats()
        assert success is True

    @pytest.mark.asyncio
    async def test_extract_users(self, service):
        """Test extracting user details."""
        # Launch and navigate
        await service.launch_wecom()
        await service.switch_to_private_chats()
        await asyncio.sleep(1.0)  # Wait for UI to stabilize

        # Extract users
        result = await service.extract_private_chat_users(max_scrolls=3)

        assert result.success is True
        # We should find at least some users if Private Chats has content
        # (This assertion may fail if the test account has no chats)
        print(f"\nExtracted {result.total_count} users:")
        print(result.format_table())

    @pytest.mark.asyncio
    async def test_full_workflow(self, service, tmp_path):
        """Test the complete workflow from start to finish."""
        result = await service.run_full_workflow(
            skip_launch=False,
            capture_avatars=False,
            output_dir=str(tmp_path),
        )

        assert result.success is True
        print("\nFull workflow completed:")
        print(f"  - Users found: {result.total_count}")
        print(f"  - Scrolls performed: {result.total_scrolls}")
        print(f"  - Duration: {result.duration_seconds:.1f}s")
        print(result.format_table())

    @pytest.mark.asyncio
    async def test_full_workflow_with_avatars(self, service, tmp_path):
        """Test workflow with avatar capture."""
        result = await service.run_full_workflow(
            skip_launch=False,
            capture_avatars=True,
            output_dir=str(tmp_path),
        )

        assert result.success is True

        # Check if avatars were captured
        avatar_dir = tmp_path / "avatars"
        if avatar_dir.exists():
            avatar_files = list(avatar_dir.glob("*.png"))
            print(f"\nCaptured {len(avatar_files)} avatar images")
            for f in avatar_files:
                print(f"  - {f.name}")


class TestWeComWorkflowSkipLaunch:
    """
    Integration tests that skip app launch.

    Use these when WeCom is already open on the device.
    """

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return Config(debug=True)

    @pytest.fixture
    def service(self, config):
        """Create WeComService instance."""
        return WeComService(config)

    @pytest.mark.asyncio
    async def test_extract_from_current_state(self, service):
        """
        Test extracting users from current state.

        Assumes WeCom is already open on Private Chats.
        """
        result = await service.extract_private_chat_users(max_scrolls=5)

        print(f"\nExtracted {result.total_count} users from current state:")
        print(result.format_table())

        # Export to dict for inspection
        data = result.to_dict()
        assert "users" in data
        assert "extraction_time" in data


class TestConversationSync:
    """
    Integration tests for the conversation sync workflow.

    These tests verify the full database sync functionality.
    """

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return Config(debug=True)

    @pytest.fixture
    def temp_db(self, tmp_path):
        """Create temporary database path."""
        return str(tmp_path / "test_sync.db")

    @pytest.fixture
    def temp_images(self, tmp_path):
        """Create temporary images directory."""
        images_dir = tmp_path / "images"
        images_dir.mkdir()
        return str(images_dir)

    @pytest.mark.asyncio
    async def test_sync_single_customer(self, config, temp_db, temp_images):
        """
        Test syncing a single customer's conversation.

        This test requires WeCom to be open with at least one private chat.
        """
        from wecom_automation.services.sync_service import (
            InitialSyncService,
            VoiceHandlerAction,
        )

        # Create sync service with auto-placeholder for voice messages
        sync = InitialSyncService(
            config=config,
            db_path=temp_db,
            images_dir=temp_images,
            timing_multiplier=0.5,  # Faster for testing
        )

        # Use placeholder for voice messages (non-interactive)
        sync.set_voice_handler_callback(lambda msg: (VoiceHandlerAction.PLACEHOLDER, None))

        # Run sync without test messages
        stats = await sync.run_initial_sync(
            send_test_messages=False,
            response_wait_seconds=2.0,
        )

        print("\nSync Results:")
        print(f"  Customers synced: {stats.get('customers_synced', 0)}")
        print(f"  Messages added: {stats.get('messages_added', 0)}")
        print(f"  Messages skipped: {stats.get('messages_skipped', 0)}")
        print(f"  Images saved: {stats.get('images_saved', 0)}")
        print(f"  Voice messages: {stats.get('voice_messages', 0)}")

        if stats.get("errors"):
            print(f"  Errors: {len(stats['errors'])}")
            for error in stats["errors"][:5]:
                print(f"    - {error}")

        # Verify database was created
        assert Path(temp_db).exists()

        # Verify statistics
        db_stats = sync.repository.get_statistics()
        print("\nDatabase Statistics:")
        print(f"  Devices: {db_stats['devices']}")
        print(f"  Kefus: {db_stats['kefus']}")
        print(f"  Customers: {db_stats['customers']}")
        print(f"  Messages: {db_stats['messages']}")

    @pytest.mark.asyncio
    async def test_sync_idempotent(self, config, temp_db, temp_images):
        """
        Test that running sync twice doesn't duplicate messages.
        """
        from wecom_automation.services.sync_service import (
            InitialSyncService,
            VoiceHandlerAction,
        )

        sync = InitialSyncService(
            config=config,
            db_path=temp_db,
            images_dir=temp_images,
            timing_multiplier=0.5,
        )

        sync.set_voice_handler_callback(lambda msg: (VoiceHandlerAction.PLACEHOLDER, None))

        # First sync
        stats1 = await sync.run_initial_sync(
            send_test_messages=False,
            response_wait_seconds=2.0,
        )

        messages_after_first = sync.repository.get_statistics()["messages"]

        # Second sync
        stats2 = await sync.run_initial_sync(
            send_test_messages=False,
            response_wait_seconds=2.0,
        )

        messages_after_second = sync.repository.get_statistics()["messages"]

        print(f"\nFirst sync: {stats1.get('messages_added', 0)} added")
        print(f"Second sync: {stats2.get('messages_added', 0)} added")
        print(f"Second sync skipped: {stats2.get('messages_skipped', 0)}")

        # Messages count should be the same (or slightly more if new messages arrived)
        # But not double
        assert messages_after_second <= messages_after_first * 1.1  # Allow 10% growth


class TestMessageExtraction:
    """
    Integration tests for message extraction from conversations.
    """

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return Config(debug=True)

    @pytest.fixture
    def service(self, config):
        """Create WeComService instance."""
        return WeComService(config)

    @pytest.mark.asyncio
    async def test_extract_conversation_messages(self, service):
        """
        Test extracting messages from current conversation.

        Requires WeCom to be open with a conversation visible.
        """
        result = await service.extract_conversation_messages(
            max_scrolls=5,
            download_images=False,
        )

        print(f"\n{result.format_summary()}")

        if result.messages:
            print("\nFirst 10 messages:")
            for i, msg in enumerate(result.messages[:10], 1):
                print(msg.format(i))

    @pytest.mark.asyncio
    async def test_get_kefu_name(self, service):
        """
        Test extracting kefu name from UI.

        Requires WeCom to be open.
        """
        kefu_info = await service.get_kefu_name(debug=True)

        if kefu_info:
            print(f"\nKefu Name: {kefu_info.name}")
            if kefu_info.department:
                print(f"Department: {kefu_info.department}")
            if kefu_info.verification_status:
                print(f"Status: {kefu_info.verification_status}")
        else:
            print("\nCould not extract kefu name")


# =============================================================================
# Skip integration tests by default (require device)
# =============================================================================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "integration: mark test as integration test (requires device)")


def pytest_collection_modifyitems(config, items):
    """Skip integration tests unless explicitly requested."""
    if not config.getoption("-m") or "integration" not in config.getoption("-m"):
        skip_integration = pytest.mark.skip(reason="Integration tests skipped. Run with: pytest -m integration")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)
