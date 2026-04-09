"""
Tests for text indexing for O(1) lookups.

TDD Step 4: Text Index
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock


class TestBuildTextIndex:
    """Tests for _build_text_index() method."""

    def test_build_text_index_creates_dict(self):
        """_build_text_index() should create a dictionary."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.clickable_elements = [
            {"index": 0, "text": "Button 1"},
            {"index": 1, "text": "Button 2"},
        ]

        index = service._build_text_index()

        assert isinstance(index, dict)

    def test_build_text_index_maps_lowercase_text_to_element(self):
        """_build_text_index() should map lowercase text to element."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.clickable_elements = [
            {"index": 0, "text": "Hello World"},
            {"index": 1, "text": "Click Me"},
        ]

        index = service._build_text_index()

        assert "hello world" in index
        assert index["hello world"]["index"] == 0
        assert "click me" in index
        assert index["click me"]["index"] == 1

    def test_build_text_index_handles_empty_text(self):
        """_build_text_index() should skip elements with empty text."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.clickable_elements = [
            {"index": 0, "text": ""},
            {"index": 1, "text": "Valid"},
            {"index": 2, "text": None},
        ]

        index = service._build_text_index()

        assert "" not in index
        assert "valid" in index
        assert len(index) == 1

    def test_build_text_index_handles_whitespace(self):
        """_build_text_index() should strip whitespace from text."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.clickable_elements = [
            {"index": 0, "text": "  Padded  "},
        ]

        index = service._build_text_index()

        assert "padded" in index

    def test_build_text_index_first_wins(self):
        """_build_text_index() should keep first element for duplicate text."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.clickable_elements = [
            {"index": 0, "text": "Duplicate"},
            {"index": 1, "text": "Duplicate"},
        ]

        index = service._build_text_index()

        # First element wins
        assert index["duplicate"]["index"] == 0

    def test_build_text_index_handles_empty_list(self):
        """_build_text_index() should handle empty element list."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.clickable_elements = []

        index = service._build_text_index()

        assert index == {}


class TestFindByTextIndexed:
    """Tests for find_by_text_indexed() method."""

    def test_find_by_text_indexed_returns_element(self):
        """find_by_text_indexed() should return matching element."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.text_index = {
            "hello": {"index": 0, "text": "Hello"},
            "world": {"index": 1, "text": "World"},
        }

        result = service.find_by_text_indexed("Hello")

        assert result is not None
        assert result["index"] == 0

    def test_find_by_text_indexed_case_insensitive(self):
        """find_by_text_indexed() should be case insensitive."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.text_index = {
            "hello world": {"index": 0, "text": "Hello World"},
        }

        # Different cases should all work
        assert service.find_by_text_indexed("Hello World") is not None
        assert service.find_by_text_indexed("hello world") is not None
        assert service.find_by_text_indexed("HELLO WORLD") is not None

    def test_find_by_text_indexed_returns_none_when_not_found(self):
        """find_by_text_indexed() should return None when not found."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.text_index = {
            "hello": {"index": 0, "text": "Hello"},
        }

        result = service.find_by_text_indexed("Goodbye")

        assert result is None

    def test_find_by_text_indexed_handles_empty_index(self):
        """find_by_text_indexed() should handle empty index."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.text_index = {}

        result = service.find_by_text_indexed("Anything")

        assert result is None


class TestTextIndexUpdatedOnRefresh:
    """Tests for text index being updated during state refresh."""

    def test_refresh_updates_text_index(self):
        """_refresh_ui_state() should update text_index in cache."""
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

        # Initially empty
        assert service._cache.text_index == {}

        asyncio.run(service._refresh_ui_state())

        # Should have text index now
        assert "button" in service._cache.text_index
        assert "link" in service._cache.text_index

    def test_find_by_text_indexed_after_refresh(self):
        """find_by_text_indexed() should work after refresh."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {}
        mock_adb.clickable_elements_cache = [
            {"index": 5, "text": "Private Chats"},
        ]
        service._adb = mock_adb

        asyncio.run(service._refresh_ui_state())

        result = service.find_by_text_indexed("Private Chats")

        assert result is not None
        assert result["index"] == 5


class TestTextIndexPerformance:
    """Tests for O(1) lookup performance."""

    def test_find_by_text_indexed_is_constant_time(self):
        """find_by_text_indexed() should be O(1) not O(n)."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        # Create large index
        large_index = {}
        for i in range(10000):
            large_index[f"element_{i}"] = {"index": i, "text": f"Element_{i}"}
        service._cache.text_index = large_index

        # First lookup
        start = time.time()
        service.find_by_text_indexed("element_9999")
        first_time = time.time() - start

        # Second lookup (should be similar time)
        start = time.time()
        service.find_by_text_indexed("element_0")
        second_time = time.time() - start

        # Both should be very fast (< 1ms typically)
        # The key is they should be similar, not that first is slower
        assert first_time < 0.01  # Less than 10ms
        assert second_time < 0.01
