"""
Tests for direct index access methods.

TDD Step 5: Index Access
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock


class TestGetElementByIndex:
    """Tests for get_element_by_index() method."""

    def test_get_element_by_index_returns_element(self):
        """get_element_by_index() should return element at given index."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.clickable_elements = [
            {"index": 0, "text": "First"},
            {"index": 1, "text": "Second"},
            {"index": 2, "text": "Third"},
        ]

        result = service.get_element_by_index(1)

        assert result is not None
        assert result["text"] == "Second"

    def test_get_element_by_index_returns_none_when_out_of_range(self):
        """get_element_by_index() should return None for invalid index."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.clickable_elements = [
            {"index": 0, "text": "Only"},
        ]

        assert service.get_element_by_index(5) is None
        assert service.get_element_by_index(-1) is None

    def test_get_element_by_index_handles_empty_list(self):
        """get_element_by_index() should return None for empty list."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.clickable_elements = []

        assert service.get_element_by_index(0) is None

    def test_get_element_by_index_first_element(self):
        """get_element_by_index(0) should return first element."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.clickable_elements = [
            {"index": 0, "text": "First"},
        ]

        result = service.get_element_by_index(0)

        assert result is not None
        assert result["text"] == "First"


class TestFindClickableByText:
    """Tests for find_clickable_by_text() method."""

    def test_find_clickable_by_text_returns_element(self):
        """find_clickable_by_text() should return matching element."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {}
        mock_adb.clickable_elements_cache = [
            {"index": 0, "text": "Button"},
            {"index": 1, "text": "Link"},
        ]
        service._adb = mock_adb

        result = asyncio.run(service.find_clickable_by_text(("Button",)))

        assert result is not None
        assert result["index"] == 0

    def test_find_clickable_by_text_multiple_patterns(self):
        """find_clickable_by_text() should match any of multiple patterns."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {}
        mock_adb.clickable_elements_cache = [
            {"index": 0, "text": "私聊"},
        ]
        service._adb = mock_adb

        result = asyncio.run(service.find_clickable_by_text(("Private Chats", "私聊")))

        assert result is not None
        assert result["index"] == 0

    def test_find_clickable_by_text_exact_match(self):
        """find_clickable_by_text(exact=True) should require exact match."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {}
        mock_adb.clickable_elements_cache = [
            {"index": 0, "text": "Button Text"},
        ]
        service._adb = mock_adb

        # Partial match should fail with exact=True
        result = asyncio.run(service.find_clickable_by_text(("Button",), exact=True))
        assert result is None

        # Exact match should succeed
        result = asyncio.run(
            service.find_clickable_by_text(("Button Text",), exact=True)
        )
        assert result is not None

    def test_find_clickable_by_text_partial_match(self):
        """find_clickable_by_text() should do partial match by default."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {}
        mock_adb.clickable_elements_cache = [
            {"index": 0, "text": "Send Message"},
        ]
        service._adb = mock_adb

        result = asyncio.run(service.find_clickable_by_text(("Send",)))

        assert result is not None
        assert result["index"] == 0

    def test_find_clickable_by_text_returns_none_when_not_found(self):
        """find_clickable_by_text() should return None when not found."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {}
        mock_adb.clickable_elements_cache = [
            {"index": 0, "text": "Button"},
        ]
        service._adb = mock_adb

        result = asyncio.run(service.find_clickable_by_text(("NonExistent",)))

        assert result is None


class TestFindClickableByResourceId:
    """Tests for find_clickable_by_resource_id() method."""

    def test_find_clickable_by_resource_id_returns_element(self):
        """find_clickable_by_resource_id() should return matching element."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {}
        mock_adb.clickable_elements_cache = [
            {"index": 0, "resourceId": "com.app:id/button"},
            {"index": 1, "resourceId": "com.app:id/link"},
        ]
        service._adb = mock_adb

        result = asyncio.run(service.find_clickable_by_resource_id(("button",)))

        assert result is not None
        assert result["index"] == 0

    def test_find_clickable_by_resource_id_multiple_patterns(self):
        """find_clickable_by_resource_id() should match any pattern."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {}
        mock_adb.clickable_elements_cache = [
            {"index": 0, "resourceId": "com.app:id/send_btn"},
        ]
        service._adb = mock_adb

        result = asyncio.run(service.find_clickable_by_resource_id(("button", "btn")))

        assert result is not None
        assert result["index"] == 0

    def test_find_clickable_by_resource_id_case_insensitive(self):
        """find_clickable_by_resource_id() should be case insensitive."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {}
        mock_adb.clickable_elements_cache = [
            {"index": 0, "resourceId": "com.app:id/SendButton"},
        ]
        service._adb = mock_adb

        result = asyncio.run(service.find_clickable_by_resource_id(("sendbutton",)))

        assert result is not None

    def test_find_clickable_by_resource_id_returns_none_when_not_found(self):
        """find_clickable_by_resource_id() should return None when not found."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {}
        mock_adb.clickable_elements_cache = [
            {"index": 0, "resourceId": "com.app:id/button"},
        ]
        service._adb = mock_adb

        result = asyncio.run(service.find_clickable_by_resource_id(("nonexistent",)))

        assert result is None

    def test_find_clickable_by_resource_id_handles_missing_resource_id(self):
        """find_clickable_by_resource_id() should handle elements without resourceId."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {}
        mock_adb.clickable_elements_cache = [
            {"index": 0, "text": "No resource ID"},
            {"index": 1, "resourceId": "com.app:id/target"},
        ]
        service._adb = mock_adb

        result = asyncio.run(service.find_clickable_by_resource_id(("target",)))

        assert result is not None
        assert result["index"] == 1


class TestMatchesText:
    """Tests for _matches_text() helper method."""

    def test_matches_text_partial_match(self):
        """_matches_text() should do partial match by default."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        assert service._matches_text("Hello World", ("Hello",), exact=False) is True
        assert service._matches_text("Hello World", ("World",), exact=False) is True
        assert service._matches_text("Hello World", ("Goodbye",), exact=False) is False

    def test_matches_text_exact_match(self):
        """_matches_text() should require exact match when exact=True."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        assert service._matches_text("Hello", ("Hello",), exact=True) is True
        assert service._matches_text("Hello World", ("Hello",), exact=True) is False

    def test_matches_text_case_insensitive(self):
        """_matches_text() should be case insensitive."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        assert service._matches_text("Hello", ("hello",), exact=False) is True
        assert service._matches_text("HELLO", ("hello",), exact=True) is True
