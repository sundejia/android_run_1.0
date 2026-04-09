"""
Unit tests for UI Parser service.
"""

import sys
from pathlib import Path

import pytest

# Add src to path
from wecom_automation.core.config import get_project_root

project_root = get_project_root()
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

# Import only what we need without triggering droidrun import

# We need to import UIParserService directly to avoid the services __init__
# which imports ADBService and triggers droidrun import
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("ui_parser", src_path / "wecom_automation" / "services" / "ui_parser.py")
ui_parser_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui_parser_module)
UIParserService = ui_parser_module.UIParserService


class TestUIParserTimestampDetection:
    """Tests for timestamp detection."""

    @pytest.fixture
    def parser(self):
        return UIParserService()

    @pytest.mark.parametrize(
        "value,expected",
        [
            # Time formats
            ("10:30", True),
            ("9:00", True),
            ("23:59", True),
            ("00:00", True),
            # Date formats
            ("11/25", True),
            ("1/5", True),
            ("12/31", True),
            # Relative time (English)
            ("6 mins ago", True),
            ("2 hours ago", True),
            ("1 day ago", True),
            ("30 seconds ago", True),
            # Relative time (Chinese)
            ("3分钟前", True),
            ("2小时前", True),
            ("1天前", True),
            # Day names
            ("Monday", True),
            ("sunday", True),
            ("星期一", True),
            ("周五", True),
            ("Yesterday", True),
            ("昨天", True),
            ("Today", True),
            ("今天", True),
            ("Just now", True),
            ("刚刚", True),
            # Non-timestamps
            ("Hello", False),
            ("John Doe", False),
            ("@WeChat", False),
            ("", False),
        ],
    )
    def test_looks_like_timestamp(self, parser, value, expected):
        """Test various timestamp patterns."""
        assert parser.looks_like_timestamp(value) == expected


class TestUIParserChannelDetection:
    """Tests for channel detection."""

    @pytest.fixture
    def parser(self):
        return UIParserService()

    @pytest.mark.parametrize(
        "value,expected",
        [
            # Valid channels
            ("@WeChat", True),
            ("@微信", True),
            ("＠WeChat", True),  # Full-width @
            ("＠微信", True),
            ("@wechat", True),
            # Invalid
            ("WeChat", False),
            ("Hello @friend", False),  # @ in middle
            ("John Doe", False),
            ("10:30", False),
            ("", False),
        ],
    )
    def test_looks_like_channel(self, parser, value, expected):
        """Test various channel patterns."""
        assert parser.looks_like_channel(value) == expected


class TestUIParserDropdownDetection:
    """Tests for dropdown/filter element detection."""

    @pytest.fixture
    def parser(self):
        return UIParserService()

    @pytest.mark.parametrize(
        "name,expected",
        [
            # Dropdown/filter patterns
            ("Private Chats", True),
            ("私聊", True),
            ("All", True),
            ("全部", True),
            ("Group Chats", True),
            ("群聊", True),
            ("Unread", True),
            ("未读", True),
            # Regular names (should not match)
            ("John Doe", False),
            ("张三", False),
            ("Project Team", False),
            ("Hello World", False),
        ],
    )
    def test_looks_like_dropdown_filter(self, parser, name, expected):
        """Test dropdown filter detection."""
        assert parser.looks_like_dropdown_filter(name) == expected


class TestUIParserUnreadBadgeDetection:
    """Tests for unread badge detection."""

    @pytest.fixture
    def parser(self):
        return UIParserService()

    @pytest.mark.parametrize(
        "value,expected",
        [
            # Pure numbers (unread counts)
            ("1", True),
            ("4", True),
            ("10", True),
            ("99", True),
            ("100", True),
            ("999", True),
            # Overflow patterns
            ("99+", True),
            ("999+", True),
            # New message indicators
            ("new", True),
            ("New", True),
            ("NEW", True),
            ("新", True),
            ("新消息", True),
            # Regular text (should not match)
            ("John Doe", False),
            ("zxy", False),
            ("wgz(302)", False),
            ("Hello", False),
            ("10:30", False),  # Time format
            ("11/25", False),  # Date format
            ("@WeChat", False),
            ("1234", False),  # 4-digit number (not unread badge)
            ("", False),
            (" ", False),
        ],
    )
    def test_looks_like_unread_badge(self, parser, value, expected):
        """Test unread badge detection."""
        assert parser.looks_like_unread_badge(value) == expected


class TestUIParserFilterHeaderDetection:
    """Tests for filter header detection."""

    @pytest.fixture
    def parser(self):
        return UIParserService()

    @pytest.mark.parametrize(
        "value,expected",
        [
            # Filter headers that should be detected
            ("Internal chats", True),
            ("内部聊天", True),
            ("外部聊天", True),
            ("私聊", True),
            ("群聊", True),
            ("单聊", True),
            ("Private chats", True),
            ("Group chats", True),
            # Case insensitive (only patterns in all_text_patterns + private_chats_patterns)
            ("INTERNAL CHATS", True),
            # Not in current filter patterns (no external_chats_patterns)
            ("External chats", False),
            ("external CHATS", False),
            # Regular names (should not match)
            ("John Doe", False),
            ("zxy", False),
            ("wgz(302)", False),
            ("Hello World", False),
            ("Project Team", False),
            ("10:30", False),
            ("@WeChat", False),
            ("", False),
        ],
    )
    def test_looks_like_filter_header(self, parser, value, expected):
        """Test filter header detection."""
        assert parser.looks_like_filter_header(value) == expected


class TestUIParserElementSearch:
    """Tests for element searching."""

    @pytest.fixture
    def parser(self):
        return UIParserService()

    def test_find_element_by_text_exact(self, parser):
        """Test finding element by exact text match."""
        elements = [
            {"text": "All", "clickable": True},
            {"text": "Messages", "clickable": False},
        ]
        result = parser.find_element_by_text(elements, ("All",), exact_match=True)
        assert result is not None
        assert result["text"] == "All"

    def test_find_element_by_text_partial(self, parser):
        """Test finding element by partial text match."""
        elements = [
            {"text": "Private Chats", "clickable": True},
            {"text": "Messages", "clickable": False},
        ]
        result = parser.find_element_by_text(elements, ("Private",), exact_match=False)
        assert result is not None
        assert result["text"] == "Private Chats"

    def test_find_element_by_text_not_found(self, parser):
        """Test when element is not found."""
        elements = [
            {"text": "Messages", "clickable": False},
        ]
        result = parser.find_element_by_text(elements, ("Settings",))
        assert result is None

    def test_find_element_in_nested(self, parser):
        """Test finding element in nested structure."""
        elements = [
            {
                "text": "",
                "children": [
                    {"text": "Nested Text", "clickable": True},
                ],
            },
        ]
        result = parser.find_element_by_text(elements, ("Nested Text",))
        assert result is not None
        assert result["text"] == "Nested Text"

    def test_find_all_elements_by_text(self, parser):
        """Test finding all matching elements."""
        elements = [
            {"text": "Private", "index": 1},
            {"text": "Private Chats", "index": 2},
            {"text": "Other", "index": 3},
        ]
        results = parser.find_all_elements_by_text(elements, ("Private",))
        assert len(results) == 2

    def test_get_current_filter_text(self, parser, sample_dropdown_elements):
        """Test getting current filter text."""
        result = parser.get_current_filter_text(sample_dropdown_elements)
        assert result == "All"

    def test_get_current_filter_text_non_clickable(self, parser):
        """Filter text should be detected even if not marked clickable."""
        elements = [
            {
                "className": "android.widget.TextView",
                "text": "All",
                "clickable": False,
                "bounds": "[150,200][250,250]",
            },
        ]
        assert parser.get_current_filter_text(elements) == "All"

    def test_get_current_filter_text_not_found(self, parser):
        """Test when no filter text is found."""
        elements = [
            {"text": "Random", "clickable": False},
        ]
        result = parser.get_current_filter_text(elements)
        assert result is None


class TestUIParserContainerDetection:
    """Tests for message container detection."""

    @pytest.fixture
    def parser(self):
        return UIParserService()

    def test_find_message_containers(self, parser, sample_message_list):
        """Test finding message list containers."""
        containers = parser.find_message_containers(sample_message_list)
        assert len(containers) >= 1

    def test_find_message_containers_empty_tree(self, parser):
        """Test with empty tree."""
        containers = parser.find_message_containers({})
        assert containers == []

    def test_find_message_containers_list_input(self, parser, sample_message_list):
        """Test with list input."""
        containers = parser.find_message_containers([sample_message_list])
        assert len(containers) >= 1


class TestUIParserUserExtraction:
    """Tests for user extraction from UI tree."""

    @pytest.fixture
    def parser(self):
        return UIParserService()

    def test_extract_users_from_tree(self, parser, sample_message_list):
        """Test extracting users from a complete message list."""
        users = parser.extract_users_from_tree(sample_message_list)
        assert len(users) == 3

        # Check first user
        zhang_san = next((u for u in users if "张三" in u.name), None)
        assert zhang_san is not None
        assert zhang_san.channel == "@WeChat"
        assert zhang_san.last_message_date == "10:30"
        assert zhang_san.message_preview == "Hello, how are you?"

    def test_extract_users_from_single_row(self, parser, sample_message_row):
        """Test extracting user from a single row."""
        # Wrap in a container
        container = {
            "className": "androidx.recyclerview.widget.RecyclerView",
            "resourceId": "com.tencent.wework:id/list",
            "packageName": "com.tencent.wework",
            "children": [sample_message_row],
        }
        users = parser.extract_users_from_tree(container)
        assert len(users) == 1
        assert users[0].name == "张三"

    def test_extract_users_empty_tree(self, parser):
        """Test with empty tree."""
        users = parser.extract_users_from_tree({})
        assert users == []

    def test_extract_users_skips_dropdowns(self, parser):
        """Test that dropdown elements are skipped."""
        tree = {
            "className": "androidx.recyclerview.widget.RecyclerView",
            "resourceId": "com.tencent.wework:id/list",
            "packageName": "com.tencent.wework",
            "children": [
                {
                    "className": "android.widget.TextView",
                    "children": [
                        {"className": "android.widget.TextView", "text": "Private Chats"},
                    ],
                },
                {
                    "className": "android.widget.RelativeLayout",
                    "children": [
                        {"className": "android.widget.TextView", "text": "John Doe"},
                        {"className": "android.widget.TextView", "text": "Hello!"},
                    ],
                },
            ],
        }
        users = parser.extract_users_from_tree(tree)
        # Should only get John Doe, not "Private Chats"
        assert len(users) == 1
        assert users[0].name == "John Doe"


class TestUIParserAvatarDetection:
    """Tests for avatar detection."""

    @pytest.fixture
    def parser(self):
        return UIParserService()

    def test_avatar_detection_by_resource_id(self, parser, sample_avatar_element):
        """Test avatar detection by resource ID."""
        # The parser should find avatar in a row containing this element
        row = {
            "className": "android.widget.RelativeLayout",
            "children": [
                sample_avatar_element,
                {"className": "android.widget.TextView", "text": "User Name"},
            ],
        }
        users = parser.extract_users_from_tree(
            {
                "className": "RecyclerView",
                "resourceId": "list",
                "packageName": "com.tencent.wework",
                "children": [row],
            }
        )

        if users:
            assert users[0].avatar is not None
            assert "[36,200][120,284]" in users[0].avatar.bounds

    def test_avatar_bounds_parsing(self, parser):
        """Test that avatar bounds are correctly stored."""
        row = {
            "className": "android.widget.RelativeLayout",
            "packageName": "com.tencent.wework",
            "bounds": "[0,100][1080,200]",
            "children": [
                {
                    "className": "android.widget.ImageView",
                    "resourceId": "avatar",
                    "bounds": "[20,110][90,180]",
                },
                {
                    "className": "android.widget.TextView",
                    "text": "Test User",
                    "bounds": "[100,110][500,150]",
                },
            ],
        }

        tree = {
            "className": "RecyclerView",
            "resourceId": "conversation_list",
            "packageName": "com.tencent.wework",
            "children": [row],
        }

        users = parser.extract_users_from_tree(tree)
        if users and users[0].avatar:
            avatar = users[0].avatar
            assert avatar.bounds is not None
