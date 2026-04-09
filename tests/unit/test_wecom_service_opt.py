"""
Tests for WeComService optimizations.

TDD Step 10: WeComService Optimization
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_wecom_service():
    """Create a mock WeComService for testing helper methods."""
    from wecom_automation.core.config import Config
    from wecom_automation.services.wecom_service import WeComService

    config = Config()

    # Create service without full initialization
    service = object.__new__(WeComService)
    service.config = config
    service.logger = MagicMock()
    service.adb = MagicMock()
    service.ui_parser = MagicMock()

    return service


class TestFindInputFieldOptimized:
    """Tests for _find_input_field() with is_flat_list parameter."""

    def test_find_input_field_flat_list_skips_recursion(self, mock_wecom_service):
        """_find_input_field(is_flat_list=True) should skip recursion."""
        # Element with child containing EditText
        elements = [{"className": "FrameLayout", "children": [{"className": "android.widget.EditText", "index": 1}]}]

        # With is_flat_list=True, should NOT find child
        result = mock_wecom_service._find_input_field(elements, is_flat_list=True)

        assert result is None

    def test_find_input_field_flat_list_finds_top_level(self, mock_wecom_service):
        """_find_input_field(is_flat_list=True) should find top-level."""
        elements = [
            {"className": "Button", "index": 0},
            {"className": "android.widget.EditText", "index": 1},
        ]

        result = mock_wecom_service._find_input_field(elements, is_flat_list=True)

        assert result is not None
        assert result["index"] == 1


class TestFindSendButtonOptimized:
    """Tests for _find_send_button() with is_flat_list parameter."""

    def test_find_send_button_flat_list_skips_recursion(self, mock_wecom_service):
        """_find_send_button(is_flat_list=True) should skip recursion."""
        elements = [{"text": "Parent", "children": [{"text": "发送", "index": 1}]}]

        result = mock_wecom_service._find_send_button(elements, is_flat_list=True)

        assert result is None

    def test_find_send_button_flat_list_finds_top_level(self, mock_wecom_service):
        """_find_send_button(is_flat_list=True) should find top-level."""
        elements = [
            {"text": "Button", "index": 0},
            {"text": "发送", "index": 1},
        ]

        result = mock_wecom_service._find_send_button(elements, is_flat_list=True)

        assert result is not None
        assert result["index"] == 1


class TestFindUserElementOptimized:
    """Tests for _find_user_element() with is_flat_list parameter."""

    def test_find_user_element_flat_list_skips_recursion(self, mock_wecom_service):
        """_find_user_element(is_flat_list=True) should skip recursion."""
        elements = [{"text": "Parent", "children": [{"text": "wgz", "index": 1}]}]

        result = mock_wecom_service._find_user_element(elements, "wgz", None, is_flat_list=True)

        assert result is None

    def test_find_user_element_flat_list_finds_top_level(self, mock_wecom_service):
        """_find_user_element(is_flat_list=True) should find top-level."""
        elements = [
            {"text": "Messages", "index": 0},
            {"text": "wgz", "index": 1},
        ]

        result = mock_wecom_service._find_user_element(elements, "wgz", None, is_flat_list=True)

        assert result is not None
        assert result["index"] == 1


class TestGoBackOptimized:
    """Tests for go_back() using get_ui_state()."""

    def test_go_back_uses_get_ui_state(self, mock_wecom_service):
        """go_back() should use get_ui_state() for single call."""
        mock_wecom_service.adb.get_ui_state = AsyncMock(
            return_value=({"tree": True}, [{"text": "返回", "index": 0, "contentDescription": "返回"}])
        )
        mock_wecom_service.adb.tap = AsyncMock()
        mock_wecom_service.adb.wait = AsyncMock()

        asyncio.run(mock_wecom_service.go_back())

        # Should have called get_ui_state (not separate get_ui_tree and get_clickable_elements)
        assert mock_wecom_service.adb.get_ui_state.called


class TestSendMessageOptimized:
    """Tests for send_message() using get_ui_state()."""

    def test_send_message_uses_get_ui_state(self, mock_wecom_service):
        """send_message() should use get_ui_state() for single call."""
        mock_wecom_service.adb.get_ui_state = AsyncMock(
            return_value=(
                {"tree": True},
                [{"className": "android.widget.EditText", "index": 0}, {"text": "发送", "index": 1}],
            )
        )
        mock_wecom_service.adb.tap = AsyncMock()
        mock_wecom_service.adb.input_text = AsyncMock()
        mock_wecom_service.adb.wait = AsyncMock()

        asyncio.run(mock_wecom_service.send_message("Hello"))

        # Should have called get_ui_state
        assert mock_wecom_service.adb.get_ui_state.called


class TestGroupInviteMenuDetection:
    """Tests for group invite header menu detection heuristics."""

    def test_find_group_invite_menu_button_recurses_tree_fallback(self, mock_wecom_service):
        """Tree fallback should detect top-right clickable menu descendants."""
        elements = [
            {
                "className": "android.widget.FrameLayout",
                "children": [
                    {
                        "resourceId": "com.tencent.wework:id/nml",
                        "className": "android.widget.TextView",
                        "text": "",
                        "contentDescription": "",
                        "isClickable": True,
                        "boundsInScreen": {"left": 528, "top": 56, "right": 624, "bottom": 152},
                        "children": [],
                    },
                    {
                        "resourceId": "com.tencent.wework:id/nma",
                        "className": "android.widget.TextView",
                        "text": "",
                        "contentDescription": "",
                        "isClickable": True,
                        "boundsInScreen": {"left": 624, "top": 56, "right": 720, "bottom": 152},
                        "children": [],
                    },
                ],
            }
        ]

        result = mock_wecom_service._find_group_invite_menu_button(elements, is_flat_list=False)

        assert result is not None
        assert result["resourceId"] == "com.tencent.wework:id/nma"

    def test_find_group_invite_menu_button_accepts_clickable_layout_container(self, mock_wecom_service):
        """Clickable layout containers in the top-right header should be eligible."""
        elements = [
            {
                "resourceId": "com.tencent.wework:id/kjg",
                "className": "android.widget.RelativeLayout",
                "text": "",
                "contentDescription": "",
                "isClickable": True,
                "boundsInScreen": {"left": 543, "top": 112, "right": 615, "bottom": 184},
                "children": [],
            }
        ]

        result = mock_wecom_service._find_group_invite_menu_button(elements)

        assert result is not None
        assert result["resourceId"] == "com.tencent.wework:id/kjg"
