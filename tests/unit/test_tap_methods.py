"""
Tests for convenience tap methods.

TDD Step 6: Tap Methods
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from wecom_automation.core.exceptions import WeComAutomationError


class TestTapByIndex:
    """Tests for tap_by_index() method."""

    def test_tap_by_index_refreshes_and_taps(self):
        """tap_by_index() should refresh state then tap."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.tap = AsyncMock(return_value="Tapped element 5")
        mock_adb.raw_tree_cache = {}
        mock_adb.clickable_elements_cache = [{"index": i} for i in range(10)]
        service._adb = mock_adb

        asyncio.run(service.tap_by_index(5))

        # Should have called get_state and tap
        assert mock_adb.get_state.called
        assert mock_adb.tap.called
        mock_adb.tap.assert_called_with(5)

    def test_tap_by_index_refresh_first_false(self):
        """tap_by_index(refresh_first=False) should skip refresh."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.tap = AsyncMock(return_value="Tapped")
        service._adb = mock_adb

        # Pre-populate cache to avoid needing refresh
        service._cache.timestamp = time.time()
        service._cache.clickable_elements = [{"index": 0}]

        asyncio.run(service.tap_by_index(0, refresh_first=False))

        # Should NOT have called get_state
        assert not mock_adb.get_state.called
        # But should have called tap
        assert mock_adb.tap.called

    def test_tap_by_index_returns_tap_result(self):
        """tap_by_index() should return the tap result."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.tap = AsyncMock(return_value="Success!")
        mock_adb.raw_tree_cache = {}
        mock_adb.clickable_elements_cache = []
        service._adb = mock_adb

        result = asyncio.run(service.tap_by_index(0))

        assert result == "Success!"

    def test_tap_by_index_invalidates_cache(self):
        """tap_by_index() should invalidate cache after tap."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.tap = AsyncMock(return_value="Tapped")
        mock_adb.raw_tree_cache = {}
        mock_adb.clickable_elements_cache = []
        service._adb = mock_adb

        asyncio.run(service.tap_by_index(0))

        # Cache should be invalidated after tap
        assert service._cache.is_valid() is False


class TestTapElement:
    """Tests for tap_element() method."""

    def test_tap_element_uses_index(self):
        """tap_element() should tap using element's index."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.tap = AsyncMock(return_value="Tapped")
        service._adb = mock_adb

        element = {"index": 7, "text": "Button"}

        asyncio.run(service.tap_element(element))

        mock_adb.tap.assert_called_with(7)

    def test_tap_element_returns_result(self):
        """tap_element() should return tap result."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.tap = AsyncMock(return_value="Element tapped!")
        service._adb = mock_adb

        element = {"index": 3, "text": "Link"}

        result = asyncio.run(service.tap_element(element))

        assert result == "Element tapped!"

    def test_tap_element_invalidates_cache(self):
        """tap_element() should invalidate cache after tap."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.tap = AsyncMock(return_value="Tapped")
        service._adb = mock_adb

        # Set up valid cache
        service._cache.timestamp = time.time()

        element = {"index": 0}

        asyncio.run(service.tap_element(element))

        # Cache should be invalidated
        assert service._cache.is_valid() is False

    def test_tap_element_handles_missing_index(self):
        """tap_element() should handle element without index."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.tap = AsyncMock(return_value="Tapped")
        service._adb = mock_adb

        element = {"text": "No index"}  # Missing index

        # Should raise an error or handle gracefully
        with pytest.raises(WeComAutomationError):
            asyncio.run(service.tap_element(element))


class TestTapByIndexBestPractice:
    """Tests for DroidRun best practice compliance."""

    def test_tap_by_index_follows_droidrun_pattern(self):
        """tap_by_index() should follow DroidRun's refresh-then-tap pattern."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        call_order = []

        async def mock_get_state():
            call_order.append("get_state")

        async def mock_tap(index):
            call_order.append(f"tap_{index}")
            return "Tapped"

        mock_adb = MagicMock()
        mock_adb.get_state = mock_get_state
        mock_adb.tap = mock_tap
        mock_adb.raw_tree_cache = {}
        mock_adb.clickable_elements_cache = []
        service._adb = mock_adb

        asyncio.run(service.tap_by_index(5))

        # get_state should be called before tap
        assert call_order == ["get_state", "tap_5"]
