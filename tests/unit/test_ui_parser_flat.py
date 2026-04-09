"""
Tests for UIParser flat-list optimization and index matching.

TDD Step 9: UI Parser
"""


class TestFindElementByTextFlatList:
    """Tests for find_element_by_text() with is_flat_list parameter."""

    def test_find_element_by_text_default_searches_children(self):
        """find_element_by_text() should search children by default."""
        from wecom_automation.services.ui_parser import UIParserService

        parser = UIParserService()

        elements = [{"text": "Parent", "children": [{"text": "Child Target"}]}]

        result = parser.find_element_by_text(elements, ("Child Target",))

        assert result is not None
        assert result["text"] == "Child Target"

    def test_find_element_by_text_flat_list_skips_children(self):
        """find_element_by_text(is_flat_list=True) should skip children."""
        from wecom_automation.services.ui_parser import UIParserService

        parser = UIParserService()

        elements = [{"text": "Parent", "children": [{"text": "Child Target"}]}]

        # With is_flat_list=True, should NOT find child
        result = parser.find_element_by_text(elements, ("Child Target",), is_flat_list=True)

        assert result is None

    def test_find_element_by_text_flat_list_finds_top_level(self):
        """find_element_by_text(is_flat_list=True) should find top-level."""
        from wecom_automation.services.ui_parser import UIParserService

        parser = UIParserService()

        elements = [
            {"text": "Button 1", "index": 0},
            {"text": "Button 2", "index": 1},
        ]

        result = parser.find_element_by_text(elements, ("Button 2",), is_flat_list=True)

        assert result is not None
        assert result["index"] == 1


class TestFindAllElementsByTextFlatList:
    """Tests for find_all_elements_by_text() with is_flat_list parameter."""

    def test_find_all_elements_by_text_default_searches_children(self):
        """find_all_elements_by_text() should search children by default."""
        from wecom_automation.services.ui_parser import UIParserService

        parser = UIParserService()

        elements = [{"text": "Target 1", "children": [{"text": "Target 2"}]}]

        results = parser.find_all_elements_by_text(elements, ("Target",))

        assert len(results) == 2

    def test_find_all_elements_by_text_flat_list_skips_children(self):
        """find_all_elements_by_text(is_flat_list=True) should skip children."""
        from wecom_automation.services.ui_parser import UIParserService

        parser = UIParserService()

        elements = [{"text": "Target 1", "children": [{"text": "Target 2"}]}]

        results = parser.find_all_elements_by_text(elements, ("Target",), is_flat_list=True)

        # Should only find top-level
        assert len(results) == 1
        assert results[0]["text"] == "Target 1"


class TestMatchUserToIndex:
    """Tests for match_user_to_index() method."""

    def test_match_user_to_index_finds_match(self):
        """match_user_to_index() should find matching element index."""
        from wecom_automation.core.models import UserDetail
        from wecom_automation.services.ui_parser import UIParserService

        parser = UIParserService()

        user = UserDetail(name="wgz")
        clickable_elements = [
            {"index": 0, "text": "Messages"},
            {"index": 1, "text": "wgz"},
            {"index": 2, "text": "sdj"},
        ]

        index = parser.match_user_to_index(user, clickable_elements)

        assert index == 1

    def test_match_user_to_index_returns_none_when_not_found(self):
        """match_user_to_index() should return None when no match."""
        from wecom_automation.core.models import UserDetail
        from wecom_automation.services.ui_parser import UIParserService

        parser = UIParserService()

        user = UserDetail(name="nonexistent")
        clickable_elements = [
            {"index": 0, "text": "wgz"},
        ]

        index = parser.match_user_to_index(user, clickable_elements)

        assert index is None

    def test_match_user_to_index_case_insensitive(self):
        """match_user_to_index() should be case insensitive."""
        from wecom_automation.core.models import UserDetail
        from wecom_automation.services.ui_parser import UIParserService

        parser = UIParserService()

        user = UserDetail(name="WGZ")
        clickable_elements = [
            {"index": 0, "text": "wgz"},
        ]

        index = parser.match_user_to_index(user, clickable_elements)

        assert index == 0

    def test_match_user_to_index_handles_empty_list(self):
        """match_user_to_index() should handle empty element list."""
        from wecom_automation.core.models import UserDetail
        from wecom_automation.services.ui_parser import UIParserService

        parser = UIParserService()

        user = UserDetail(name="wgz")
        clickable_elements = []

        index = parser.match_user_to_index(user, clickable_elements)

        assert index is None

    def test_match_user_to_index_handles_missing_text(self):
        """match_user_to_index() should handle elements without text."""
        from wecom_automation.core.models import UserDetail
        from wecom_automation.services.ui_parser import UIParserService

        parser = UIParserService()

        user = UserDetail(name="wgz")
        clickable_elements = [
            {"index": 0},  # No text
            {"index": 1, "text": "wgz"},
        ]

        index = parser.match_user_to_index(user, clickable_elements)

        assert index == 1

    def test_match_user_to_index_exact_match(self):
        """match_user_to_index() should do exact match on name."""
        from wecom_automation.core.models import UserDetail
        from wecom_automation.services.ui_parser import UIParserService

        parser = UIParserService()

        user = UserDetail(name="wgz")
        clickable_elements = [
            {"index": 0, "text": "wgz123"},  # Contains but not exact
            {"index": 1, "text": "wgz"},  # Exact match
        ]

        index = parser.match_user_to_index(user, clickable_elements)

        # Should find exact match
        assert index == 1
