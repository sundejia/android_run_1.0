"""
Tests for UIStateCache - TTL-based caching for DroidRun UI state.

TDD Step 1: Cache Layer
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock


class TestUIStateCache:
    """Tests for UIStateCache dataclass with TTL-based invalidation."""

    def test_cache_is_valid_when_fresh(self):
        """Cache should be valid immediately after creation with timestamp."""
        from wecom_automation.services.adb_service import UIStateCache

        cache = UIStateCache()
        cache.timestamp = time.time()

        assert cache.is_valid(ttl_seconds=0.5) is True

    def test_cache_is_invalid_when_expired(self):
        """Cache should be invalid after TTL expires."""
        from wecom_automation.services.adb_service import UIStateCache

        cache = UIStateCache()
        cache.timestamp = time.time() - 1.0  # 1 second ago

        assert cache.is_valid(ttl_seconds=0.5) is False

    def test_cache_is_invalid_when_never_set(self):
        """Cache should be invalid when timestamp is 0 (never set)."""
        from wecom_automation.services.adb_service import UIStateCache

        cache = UIStateCache()
        # timestamp defaults to 0.0

        assert cache.is_valid(ttl_seconds=0.5) is False

    def test_cache_invalidate_resets_timestamp(self):
        """invalidate() should reset timestamp to 0."""
        from wecom_automation.services.adb_service import UIStateCache

        cache = UIStateCache()
        cache.timestamp = time.time()

        cache.invalidate()

        assert cache.timestamp == 0.0
        assert cache.is_valid() is False

    def test_cache_stores_formatted_text(self):
        """Cache should store formatted_text from DroidRun."""
        from wecom_automation.services.adb_service import UIStateCache

        cache = UIStateCache()
        cache.formatted_text = "Messages\nPrivate Chats\nwgz @WeChat"

        assert "Messages" in cache.formatted_text
        assert "wgz" in cache.formatted_text

    def test_cache_stores_focused_text(self):
        """Cache should store focused element text."""
        from wecom_automation.services.adb_service import UIStateCache

        cache = UIStateCache()
        cache.focused_text = "Input field"

        assert cache.focused_text == "Input field"

    def test_cache_stores_raw_tree(self):
        """Cache should store raw UI tree."""
        from wecom_automation.services.adb_service import UIStateCache

        tree = {"className": "FrameLayout", "children": []}
        cache = UIStateCache()
        cache.raw_tree = tree

        assert cache.raw_tree == tree

    def test_cache_stores_clickable_elements(self):
        """Cache should store clickable elements list."""
        from wecom_automation.services.adb_service import UIStateCache

        elements = [
            {"index": 0, "text": "Button 1"},
            {"index": 1, "text": "Button 2"},
        ]
        cache = UIStateCache()
        cache.clickable_elements = elements

        assert len(cache.clickable_elements) == 2
        assert cache.clickable_elements[0]["text"] == "Button 1"

    def test_cache_stores_tree_hash(self):
        """Cache should store tree hash for change detection."""
        from wecom_automation.services.adb_service import UIStateCache

        cache = UIStateCache()
        cache.tree_hash = "abc123def456"

        assert cache.tree_hash == "abc123def456"

    def test_cache_stores_text_index(self):
        """Cache should store text index for O(1) lookups."""
        from wecom_automation.services.adb_service import UIStateCache

        text_index = {
            "button 1": {"index": 0, "text": "Button 1"},
            "button 2": {"index": 1, "text": "Button 2"},
        }
        cache = UIStateCache()
        cache.text_index = text_index

        assert cache.text_index["button 1"]["index"] == 0

    def test_cache_default_values(self):
        """Cache should have sensible defaults."""
        from wecom_automation.services.adb_service import UIStateCache

        cache = UIStateCache()

        assert cache.formatted_text == ""
        assert cache.focused_text == ""
        assert cache.raw_tree is None
        assert cache.clickable_elements == []
        assert cache.tree_hash == ""
        assert cache.text_index == {}
        assert cache.timestamp == 0.0

    def test_cache_custom_ttl(self):
        """Cache should respect custom TTL values."""
        from wecom_automation.services.adb_service import UIStateCache

        cache = UIStateCache()
        cache.timestamp = time.time() - 0.3  # 300ms ago

        # Should be valid with 0.5s TTL
        assert cache.is_valid(ttl_seconds=0.5) is True
        # Should be invalid with 0.2s TTL
        assert cache.is_valid(ttl_seconds=0.2) is False


class TestADBServiceCacheInvalidation:
    """Tests for automatic cache invalidation after UI-modifying operations."""

    def test_tap_invalidates_cache(self):
        """tap() should invalidate cache after execution."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        # Mock the underlying adb
        mock_adb = MagicMock()
        mock_adb.tap = AsyncMock(return_value="Tapped")
        service._adb = mock_adb

        # Set up cache with valid timestamp
        service._cache.timestamp = time.time()
        assert service._cache.is_valid() is True

        # Run tap
        asyncio.run(service.tap(5))

        # Cache should be invalidated
        assert service._cache.is_valid() is False

    def test_swipe_invalidates_cache(self):
        """swipe() should invalidate cache after execution."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.swipe = AsyncMock()
        service._adb = mock_adb

        service._cache.timestamp = time.time()

        asyncio.run(service.swipe(100, 500, 100, 200))

        assert service._cache.is_valid() is False

    def test_input_text_invalidates_cache(self):
        """input_text() should invalidate cache after execution."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.input_text = AsyncMock()
        service._adb = mock_adb

        service._cache.timestamp = time.time()

        asyncio.run(service.input_text("Hello"))

        assert service._cache.is_valid() is False

    def test_press_enter_invalidates_cache(self):
        """press_enter() should invalidate cache after execution."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.press_key = AsyncMock()
        service._adb = mock_adb

        service._cache.timestamp = time.time()

        asyncio.run(service.press_enter())

        assert service._cache.is_valid() is False

    def test_press_back_invalidates_cache(self):
        """press_back() should invalidate cache after execution."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.back = AsyncMock()
        service._adb = mock_adb

        service._cache.timestamp = time.time()

        asyncio.run(service.press_back())

        assert service._cache.is_valid() is False

    def test_start_app_invalidates_cache(self):
        """start_app() should invalidate cache after execution."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.start_app = AsyncMock()
        service._adb = mock_adb

        service._cache.timestamp = time.time()

        asyncio.run(service.start_app("com.example.app"))

        assert service._cache.is_valid() is False

    def test_clear_text_field_invalidates_cache(self):
        """clear_text_field() should invalidate cache after execution."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.press_key = AsyncMock()
        service._adb = mock_adb

        service._cache.timestamp = time.time()

        asyncio.run(service.clear_text_field())

        assert service._cache.is_valid() is False

    def test_tap_coordinates_invalidates_cache(self):
        """tap_coordinates() should invalidate cache after execution."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.tap_by_coordinates = AsyncMock()
        service._adb = mock_adb

        service._cache.timestamp = time.time()

        asyncio.run(service.tap_coordinates(500, 500))

        assert service._cache.is_valid() is False
