"""
Pytest configuration and fixtures for WeCom Automation tests.
"""

# Add src to path for imports FIRST, before any other imports
import sys
from pathlib import Path
from typing import Any

# Configure sys.path before importing project modules
project_root = Path(__file__).parent.parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

import pytest

from wecom_automation.core.config import get_project_root


# =============================================================================
# Sample UI Tree Fixtures
# =============================================================================


@pytest.fixture
def sample_ui_element() -> dict[str, Any]:
    """A basic UI element dict."""
    return {
        "className": "android.widget.TextView",
        "resourceId": "com.tencent.wework:id/title",
        "text": "John Doe",
        "clickable": True,
        "index": 1,
        "bounds": "[36,200][540,280]",
    }


@pytest.fixture
def sample_avatar_element() -> dict[str, Any]:
    """A UI element representing an avatar image."""
    return {
        "className": "android.widget.ImageView",
        "resourceId": "com.tencent.wework:id/avatar",
        "contentDescription": "User avatar",
        "bounds": "[36,200][120,284]",
        "clickable": False,
    }


@pytest.fixture
def sample_message_row() -> dict[str, Any]:
    """A complete message row with all typical elements."""
    return {
        "className": "android.widget.RelativeLayout",
        "resourceId": "com.tencent.wework:id/conversation_item",
        "packageName": "com.tencent.wework",
        "bounds": "[0,200][1080,360]",
        "clickable": True,
        "children": [
            {
                "className": "android.widget.ImageView",
                "resourceId": "com.tencent.wework:id/avatar",
                "bounds": "[36,210][120,294]",
            },
            {
                "className": "android.widget.TextView",
                "resourceId": "com.tencent.wework:id/title",
                "text": "张三",
                "bounds": "[130,210][400,250]",
            },
            {
                "className": "android.widget.TextView",
                "resourceId": "com.tencent.wework:id/channel",
                "text": "@WeChat",
                "bounds": "[405,210][500,250]",
            },
            {
                "className": "android.widget.TextView",
                "resourceId": "com.tencent.wework:id/time",
                "text": "10:30",
                "bounds": "[950,210][1050,250]",
            },
            {
                "className": "android.widget.TextView",
                "resourceId": "com.tencent.wework:id/content",
                "text": "Hello, how are you?",
                "bounds": "[130,260][950,300]",
            },
        ],
    }


@pytest.fixture
def sample_message_list() -> dict[str, Any]:
    """A complete message list container with multiple rows."""
    return {
        "className": "androidx.recyclerview.widget.RecyclerView",
        "resourceId": "com.tencent.wework:id/conversation_list",
        "packageName": "com.tencent.wework",
        "bounds": "[0,150][1080,2000]",
        "children": [
            # Row 1: 张三
            {
                "className": "android.widget.RelativeLayout",
                "packageName": "com.tencent.wework",
                "bounds": "[0,150][1080,310]",
                "children": [
                    {
                        "className": "android.widget.ImageView",
                        "resourceId": "com.tencent.wework:id/avatar",
                        "bounds": "[36,160][120,244]",
                    },
                    {
                        "className": "android.widget.TextView",
                        "resourceId": "com.tencent.wework:id/title",
                        "text": "张三",
                        "bounds": "[130,160][400,200]",
                    },
                    {
                        "className": "android.widget.TextView",
                        "text": "@WeChat",
                        "bounds": "[405,160][500,200]",
                    },
                    {
                        "className": "android.widget.TextView",
                        "resourceId": "com.tencent.wework:id/time",
                        "text": "10:30",
                        "bounds": "[950,160][1050,200]",
                    },
                    {
                        "className": "android.widget.TextView",
                        "resourceId": "com.tencent.wework:id/content",
                        "text": "Hello, how are you?",
                        "bounds": "[130,210][950,250]",
                    },
                ],
            },
            # Row 2: 李四
            {
                "className": "android.widget.RelativeLayout",
                "packageName": "com.tencent.wework",
                "bounds": "[0,310][1080,470]",
                "children": [
                    {
                        "className": "android.widget.ImageView",
                        "bounds": "[36,320][120,404]",
                    },
                    {
                        "className": "android.widget.TextView",
                        "resourceId": "com.tencent.wework:id/title",
                        "text": "李四",
                        "bounds": "[130,320][400,360]",
                    },
                    {
                        "className": "android.widget.TextView",
                        "resourceId": "com.tencent.wework:id/time",
                        "text": "Yesterday",
                        "bounds": "[950,320][1050,360]",
                    },
                    {
                        "className": "android.widget.TextView",
                        "resourceId": "com.tencent.wework:id/content",
                        "text": "See you tomorrow!",
                        "bounds": "[130,370][950,410]",
                    },
                ],
            },
            # Row 3: John (English)
            {
                "className": "android.widget.RelativeLayout",
                "packageName": "com.tencent.wework",
                "bounds": "[0,470][1080,630]",
                "children": [
                    {
                        "className": "android.widget.ImageView",
                        "resourceId": "com.tencent.wework:id/avatar",
                        "bounds": "[36,480][120,564]",
                    },
                    {
                        "className": "android.widget.TextView",
                        "resourceId": "com.tencent.wework:id/title",
                        "text": "John",
                        "bounds": "[130,480][400,520]",
                    },
                    {
                        "className": "android.widget.TextView",
                        "text": "＠微信",
                        "bounds": "[405,480][500,520]",
                    },
                    {
                        "className": "android.widget.TextView",
                        "text": "6 mins ago",
                        "bounds": "[950,480][1050,520]",
                    },
                    {
                        "className": "android.widget.TextView",
                        "text": "Meeting at 3pm",
                        "bounds": "[130,530][950,570]",
                    },
                ],
            },
        ],
    }


@pytest.fixture
def sample_dropdown_elements() -> list[dict[str, Any]]:
    """UI elements including dropdown filter."""
    return [
        {
            "className": "android.widget.TextView",
            "text": "All",
            "clickable": True,
            "index": 5,
        },
        {
            "className": "android.widget.TextView",
            "text": "Messages",
            "clickable": False,
            "index": 6,
        },
    ]


@pytest.fixture
def sample_private_chats_menu() -> list[dict[str, Any]]:
    """UI elements for the dropdown menu with Private Chats option."""
    return [
        {
            "className": "android.widget.TextView",
            "text": "All",
            "clickable": True,
            "index": 1,
        },
        {
            "className": "android.widget.TextView",
            "text": "Private Chats",
            "clickable": True,
            "index": 2,
        },
        {
            "className": "android.widget.TextView",
            "text": "Group Chats",
            "clickable": True,
            "index": 3,
        },
        {
            "className": "android.widget.TextView",
            "text": "Unread",
            "clickable": True,
            "index": 4,
        },
    ]


# =============================================================================
# Mock Fixtures
# =============================================================================


@pytest.fixture
def mock_adb_tools(mocker):
    """Mock AdbTools for unit testing."""
    mock = mocker.MagicMock()
    mock.start_app = mocker.AsyncMock()
    mock.get_state = mocker.AsyncMock()
    mock.tap = mocker.AsyncMock(return_value="Tap successful")
    mock.swipe = mocker.AsyncMock()
    mock.take_screenshot = mocker.AsyncMock(return_value=("png", b"fake_image"))
    return mock
