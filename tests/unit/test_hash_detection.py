"""
Tests for hash-based change detection.

TDD Step 3: Hash Detection
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock


class TestHashUITree:
    """Tests for hash_ui_tree() method."""

    def test_hash_ui_tree_returns_string(self):
        """hash_ui_tree() should return a string hash."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        tree = {"className": "FrameLayout", "children": []}
        result = service.hash_ui_tree(tree)

        assert isinstance(result, str)
        assert len(result) > 0

    def test_hash_ui_tree_deterministic(self):
        """Same tree should produce same hash."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        tree = {"className": "FrameLayout", "children": [{"text": "Hello"}]}
        hash1 = service.hash_ui_tree(tree)
        hash2 = service.hash_ui_tree(tree)

        assert hash1 == hash2

    def test_hash_ui_tree_different_trees_different_hash(self):
        """Different trees should produce different hashes."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        tree1 = {"className": "FrameLayout", "children": []}
        tree2 = {"className": "LinearLayout", "children": []}

        hash1 = service.hash_ui_tree(tree1)
        hash2 = service.hash_ui_tree(tree2)

        assert hash1 != hash2

    def test_hash_ui_tree_handles_none(self):
        """hash_ui_tree() should handle None gracefully."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        result = service.hash_ui_tree(None)

        assert isinstance(result, str)

    def test_hash_ui_tree_handles_empty_dict(self):
        """hash_ui_tree() should handle empty dict."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        result = service.hash_ui_tree({})

        assert isinstance(result, str)
        assert len(result) > 0

    def test_hash_ui_tree_handles_complex_tree(self):
        """hash_ui_tree() should handle complex nested trees."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        tree = {
            "className": "FrameLayout",
            "bounds": "[0,0][1080,2400]",
            "children": [
                {"className": "TextView", "text": "Hello", "children": []},
                {"className": "Button", "text": "Click me", "clickable": True},
            ],
        }

        result = service.hash_ui_tree(tree)

        assert isinstance(result, str)
        assert len(result) > 0


class TestIsTreeUnchanged:
    """Tests for is_tree_unchanged() method."""

    def test_is_tree_unchanged_returns_true_when_same(self):
        """is_tree_unchanged() should return True when tree hasn't changed."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        tree = {"className": "FrameLayout"}
        tree_hash = service.hash_ui_tree(tree)

        # Set cache hash
        service._cache.tree_hash = tree_hash
        service._last_tree_hash = tree_hash

        assert service.is_tree_unchanged() is True

    def test_is_tree_unchanged_returns_false_when_different(self):
        """is_tree_unchanged() should return False when tree changed."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        # Different hashes
        service._cache.tree_hash = "hash1"
        service._last_tree_hash = "hash2"

        assert service.is_tree_unchanged() is False

    def test_is_tree_unchanged_returns_false_when_no_previous(self):
        """is_tree_unchanged() should return False when no previous hash."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.tree_hash = "current_hash"
        # _last_tree_hash should be empty string by default

        assert service.is_tree_unchanged() is False


class TestHashUpdatedOnRefresh:
    """Tests for hash being updated during state refresh."""

    def test_refresh_updates_tree_hash(self):
        """_refresh_ui_state() should update tree_hash in cache."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {"className": "FrameLayout"}
        mock_adb.clickable_elements_cache = []
        service._adb = mock_adb

        # Initially empty
        assert service._cache.tree_hash == ""

        asyncio.run(service._refresh_ui_state())

        # Should have a hash now
        assert service._cache.tree_hash != ""
        assert len(service._cache.tree_hash) > 0

    def test_refresh_updates_last_tree_hash(self):
        """_refresh_ui_state() should update _last_tree_hash."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {"className": "FrameLayout"}
        mock_adb.clickable_elements_cache = []
        service._adb = mock_adb

        # First refresh
        asyncio.run(service._refresh_ui_state())
        first_hash = service._cache.tree_hash

        # Change tree
        mock_adb.raw_tree_cache = {"className": "LinearLayout"}

        # Second refresh
        asyncio.run(service._refresh_ui_state())

        # _last_tree_hash should be the first hash
        assert service._last_tree_hash == first_hash
        # Current hash should be different
        assert service._cache.tree_hash != first_hash

    def test_is_tree_unchanged_after_scroll(self):
        """Simulate scroll - tree unchanged should be detected."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {"className": "FrameLayout", "text": "Same"}
        mock_adb.clickable_elements_cache = []
        service._adb = mock_adb

        # First refresh
        asyncio.run(service._refresh_ui_state())

        # Second refresh with same tree (simulating scroll that didn't change content)
        asyncio.run(service._refresh_ui_state())

        # Tree should be detected as unchanged
        assert service.is_tree_unchanged() is True

    def test_is_tree_changed_after_navigation(self):
        """Simulate navigation - tree changed should be detected."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        mock_adb = MagicMock()
        mock_adb.get_state = AsyncMock()
        mock_adb.raw_tree_cache = {"className": "FrameLayout", "text": "Screen 1"}
        mock_adb.clickable_elements_cache = []
        service._adb = mock_adb

        # First refresh
        asyncio.run(service._refresh_ui_state())

        # Change tree (simulating navigation)
        mock_adb.raw_tree_cache = {"className": "FrameLayout", "text": "Screen 2"}

        # Second refresh
        asyncio.run(service._refresh_ui_state())

        # Tree should be detected as changed
        assert service.is_tree_unchanged() is False
