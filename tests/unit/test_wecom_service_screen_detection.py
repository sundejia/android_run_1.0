"""Unit tests for WeComService screen-state heuristics (no device)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from wecom_automation.core.config import Config
from wecom_automation.services.wecom_service import WeComService


def test_is_chat_screen_external_style_group_title_zh() -> None:
    svc = WeComService(Config())
    elements = [
        {
            "text": "群聊(3)",
            "contentDescription": "",
            "className": "android.widget.TextView",
            "resourceId": "",
            "index": 2,
        },
        {
            "className": "android.widget.EditText",
            "text": "",
            "contentDescription": "",
            "resourceId": "com.tencent.wework:id/input",
            "bounds": "[0,900][1080,1000]",
        },
        {
            "className": "android.widget.ListView",
            "resourceId": "com.tencent.wework:id/iru",
            "text": "",
            "contentDescription": "",
        },
    ]
    assert svc._is_chat_screen({}, elements) is True


def test_is_chat_screen_listview_and_bottom_edittext_from_tree() -> None:
    svc = WeComService(Config())
    elements = [
        {
            "className": "android.widget.EditText",
            "text": "",
            "resourceId": "",
            "bounds": "[0,850][1080,950]",
        },
    ]
    tree = {
        "className": "android.widget.FrameLayout",
        "children": [
            {
                "className": "android.widget.ListView",
                "resourceId": "com.tencent.wework:id/iru",
                "children": [],
            }
        ],
    }
    assert svc._is_chat_screen(tree, elements) is True


def test_is_chat_screen_external_customer_group_title_zh() -> None:
    svc = WeComService(Config())
    elements = [
        {
            "text": "外部客户群(3)",
            "contentDescription": "",
            "className": "android.widget.TextView",
            "resourceId": "",
            "index": 2,
        },
        {
            "className": "android.widget.EditText",
            "text": "",
            "contentDescription": "",
            "resourceId": "com.tencent.wework:id/input",
            "bounds": "[0,760][1080,860]",
        },
        {
            "className": "android.widget.ListView",
            "resourceId": "com.tencent.wework:id/iru",
            "text": "",
            "contentDescription": "",
        },
    ]
    assert svc._is_chat_screen({}, elements) is True


def test_is_chat_screen_uses_content_description_for_group_hint() -> None:
    svc = WeComService(Config())
    elements = [
        {
            "text": "",
            "contentDescription": "外部客户群(3)",
            "className": "android.widget.TextView",
            "resourceId": "",
            "index": 2,
        },
        {
            "className": "android.widget.ImageButton",
            "text": "",
            "contentDescription": "返回",
            "resourceId": "",
            "index": 0,
        },
        {
            "className": "android.widget.EditText",
            "text": "",
            "contentDescription": "",
            "resourceId": "",
            "bounds": "[0,650][1080,760]",
        },
    ]
    assert svc._is_chat_screen({}, elements) is True


def test_is_chat_screen_short_viewport_bottom_input_threshold() -> None:
    svc = WeComService(Config())
    elements = [
        {
            "className": "android.widget.ImageButton",
            "text": "",
            "contentDescription": "返回",
            "resourceId": "",
            "index": 0,
            "bounds": "[0,80][80,160]",
        },
        {
            "className": "android.widget.EditText",
            "text": "",
            "contentDescription": "",
            "resourceId": "",
            "bounds": "[0,620][1080,720]",
        },
    ]
    assert svc._is_chat_screen({}, elements) is True


@pytest.mark.asyncio
async def test_confirm_group_creation_waits_for_slow_chat_transition() -> None:
    svc = WeComService(Config(device_serial="device001"))
    svc.adb.get_ui_state = AsyncMock(return_value=({}, [{"index": 1}]))
    svc.adb.wait = AsyncMock()
    svc._find_group_confirm_button = lambda elements, is_flat_list=True: {"index": 1}
    svc._tap_element = AsyncMock(return_value=True)
    svc.get_current_screen = AsyncMock(side_effect=["other", "other", "chat"])

    assert await svc.confirm_group_creation("device001", post_confirm_wait_seconds=1.0) is True
