"""
Tests for get_ui_state() and refresh parameter on getters.

TDD Step 2: Unified State Fetching
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock


class TestGetUIState:
    """Tests for get_ui_state() method that fetches both tree and elements."""

    def test_get_ui_state_returns_tuple(self):
        """get_ui_state() should return (ui_tree, clickable_elements) tuple."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        # Mock the underlying adb
        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {"className": "FrameLayout"}
        mock_adb.clickable_elements_cache = [{"index": 0, "text": "Button"}]
        service._adb = mock_adb

        # Run get_ui_state
        tree, elements = asyncio.run(service.get_ui_state())

        assert tree == {"className": "FrameLayout"}
        assert elements == [{"index": 0, "text": "Button"}]

    def test_get_ui_state_calls_get_state_once(self):
        """get_ui_state() should only call get_state() once."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {}
        mock_adb.clickable_elements_cache = []
        service._adb = mock_adb

        asyncio.run(service.get_ui_state())

        # Should only call get_state once
        assert mock_adb.get_state.call_count == 1

    def test_get_ui_state_uses_cache_when_valid(self):
        """get_ui_state() should use cache when still valid."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {"new": "tree"}
        mock_adb.clickable_elements_cache = [{"new": "element"}]
        service._adb = mock_adb

        # Pre-populate cache with valid timestamp
        service._cache.raw_tree = {"cached": "tree"}
        service._cache.clickable_elements = [{"cached": "element"}]
        service._cache.timestamp = time.time()

        tree, elements = asyncio.run(service.get_ui_state())

        # Should return cached values, not call get_state
        assert tree == {"cached": "tree"}
        assert elements == [{"cached": "element"}]
        assert mock_adb.get_state.call_count == 0

    def test_get_ui_state_force_refresh(self):
        """get_ui_state(force=True) should bypass cache."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {"fresh": "tree"}
        mock_adb.clickable_elements_cache = [{"fresh": "element"}]
        service._adb = mock_adb

        # Pre-populate cache with valid timestamp
        service._cache.raw_tree = {"cached": "tree"}
        service._cache.clickable_elements = [{"cached": "element"}]
        service._cache.timestamp = time.time()

        tree, elements = asyncio.run(service.get_ui_state(force=True))

        # Should return fresh values, call get_state
        assert tree == {"fresh": "tree"}
        assert elements == [{"fresh": "element"}]
        assert mock_adb.get_state.call_count == 1

    def test_get_ui_state_updates_cache(self):
        """get_ui_state() should update cache after fetching."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {"className": "FrameLayout"}
        mock_adb.clickable_elements_cache = [{"index": 0}]
        service._adb = mock_adb

        # Cache should be invalid initially
        assert service._cache.is_valid() is False

        asyncio.run(service.get_ui_state())

        # Cache should be valid and contain new data
        assert service._cache.is_valid() is True
        assert service._cache.raw_tree == {"className": "FrameLayout"}
        assert service._cache.clickable_elements == [{"index": 0}]


class TestGetUITreeRefresh:
    """Tests for get_ui_tree() with refresh parameter."""

    def test_get_ui_tree_default_refreshes(self):
        """get_ui_tree() should refresh by default."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {"className": "FrameLayout"}
        mock_adb.clickable_elements_cache = []
        service._adb = mock_adb

        tree = asyncio.run(service.get_ui_tree())

        assert tree == {"className": "FrameLayout"}
        assert mock_adb.get_state.call_count == 1

    def test_get_ui_tree_refresh_false_uses_cache(self):
        """get_ui_tree(refresh=False) should use cache when valid."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {"fresh": "tree"}
        service._adb = mock_adb

        # Pre-populate cache
        service._cache.raw_tree = {"cached": "tree"}
        service._cache.timestamp = time.time()

        tree = asyncio.run(service.get_ui_tree(refresh=False))

        assert tree == {"cached": "tree"}
        assert mock_adb.get_state.call_count == 0

    def test_get_ui_tree_refresh_false_fetches_when_cache_invalid(self):
        """get_ui_tree(refresh=False) should fetch when cache is invalid."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {"fresh": "tree"}
        mock_adb.clickable_elements_cache = []
        service._adb = mock_adb

        # Cache is invalid (timestamp = 0)
        tree = asyncio.run(service.get_ui_tree(refresh=False))

        assert tree == {"fresh": "tree"}
        assert mock_adb.get_state.call_count == 1


class TestGetClickableElementsRefresh:
    """Tests for get_clickable_elements() with refresh parameter."""

    def test_get_clickable_elements_default_refreshes(self):
        """get_clickable_elements() should refresh by default."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = None
        mock_adb.clickable_elements_cache = [{"index": 0}]
        service._adb = mock_adb

        elements = asyncio.run(service.get_clickable_elements())

        assert elements == [{"index": 0}]
        assert mock_adb.get_state.call_count == 1

    def test_get_clickable_elements_refresh_false_uses_cache(self):
        """get_clickable_elements(refresh=False) should use cache when valid."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.clickable_elements_cache = [{"fresh": "element"}]
        service._adb = mock_adb

        # Pre-populate cache
        service._cache.clickable_elements = [{"cached": "element"}]
        service._cache.timestamp = time.time()

        elements = asyncio.run(service.get_clickable_elements(refresh=False))

        assert elements == [{"cached": "element"}]
        assert mock_adb.get_state.call_count == 0

    def test_get_clickable_elements_refresh_false_fetches_when_cache_invalid(self):
        """get_clickable_elements(refresh=False) should fetch when cache invalid."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = None
        mock_adb.clickable_elements_cache = [{"fresh": "element"}]
        service._adb = mock_adb

        # Cache is invalid (timestamp = 0)
        elements = asyncio.run(service.get_clickable_elements(refresh=False))

        assert elements == [{"fresh": "element"}]
        assert mock_adb.get_state.call_count == 1


class TestRefreshState:
    """Tests for refresh_state() method."""

    def test_refresh_state_returns_cache(self):
        """refresh_state() should return the cache object."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService, UIStateCache

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {"tree": True}
        mock_adb.clickable_elements_cache = [{"index": 0}]
        service._adb = mock_adb

        cache = asyncio.run(service.refresh_state())

        assert isinstance(cache, UIStateCache)
        assert cache.raw_tree == {"tree": True}
        assert cache.clickable_elements == [{"index": 0}]

    def test_refresh_state_force_bypasses_cache(self):
        """refresh_state(force=True) should bypass valid cache."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {"fresh": "tree"}
        mock_adb.clickable_elements_cache = []
        service._adb = mock_adb

        # Pre-populate cache
        service._cache.raw_tree = {"cached": "tree"}
        service._cache.timestamp = time.time()

        cache = asyncio.run(service.refresh_state(force=True))

        assert cache.raw_tree == {"fresh": "tree"}
        assert mock_adb.get_state.call_count == 1

    def test_refresh_state_uses_cache_when_valid(self):
        """refresh_state() should use cache when valid."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        service._adb = mock_adb

        # Pre-populate cache
        service._cache.raw_tree = {"cached": "tree"}
        service._cache.timestamp = time.time()

        cache = asyncio.run(service.refresh_state())

        assert cache.raw_tree == {"cached": "tree"}
        assert mock_adb.get_state.call_count == 0
