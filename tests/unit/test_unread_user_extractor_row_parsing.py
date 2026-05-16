"""Regression tests for conversation-list row parsing.

The 2026-05-10 click loop showed rows like ``User: 你好 | Preview: None``.
That shape means the list parser likely treated a message preview as a contact
name, then the click path searched for a non-existent target all day.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def _sync_service_extractor():
    from wecom_automation.services.sync_service import UnreadUserExtractor

    return UnreadUserExtractor


def _user_module_extractor():
    from wecom_automation.services.user.unread_detector import UnreadUserExtractor

    return UnreadUserExtractor()


@pytest.fixture(params=[_sync_service_extractor, _user_module_extractor])
def extractor(request):
    return request.param()


def _text(text: str, *, rid: str = "", bounds: tuple[int, int, int, int]) -> dict:
    left, top, right, bottom = bounds
    return {
        "className": "android.widget.TextView",
        "packageName": "com.tencent.wework",
        "resourceId": rid,
        "text": text,
        "boundsInScreen": {"left": left, "top": top, "right": right, "bottom": bottom},
    }


def _row(*children: dict, top: int = 100, bottom: int = 210) -> dict:
    return {
        "className": "android.view.ViewGroup",
        "packageName": "com.tencent.wework",
        "boundsInScreen": {"left": 0, "top": top, "right": 1080, "bottom": bottom},
        "children": [
            {
                "className": "android.widget.ImageView",
                "packageName": "com.tencent.wework",
                "resourceId": "com.tencent.wework:id/avatar",
                "boundsInScreen": {"left": 24, "top": top + 20, "right": 104, "bottom": top + 100},
            },
            *children,
        ],
    }


def _tree(*rows: dict) -> dict:
    return {
        "className": "android.widget.FrameLayout",
        "packageName": "com.tencent.wework",
        "boundsInScreen": {"left": 0, "top": 0, "right": 1080, "bottom": 2400},
        "children": [
            {
                "className": "androidx.recyclerview.widget.RecyclerView",
                "packageName": "com.tencent.wework",
                "resourceId": "com.tencent.wework:id/conversation_list",
                "boundsInScreen": {"left": 0, "top": 80, "right": 1080, "bottom": 2200},
                "children": list(rows),
            }
        ],
    }


def test_title_resource_id_keeps_real_name_when_preview_is_generic_greeting(extractor):
    row = _row(
        _text("李乖乖🍓", rid="com.tencent.wework:id/title", bounds=(128, 112, 420, 146)),
        _text("你好", rid="com.tencent.wework:id/snippet", bounds=(128, 156, 520, 188)),
        _text("2", rid="com.tencent.wework:id/unread_count", bounds=(86, 96, 120, 130)),
    )

    users = extractor.extract_from_tree(_tree(row))

    assert len(users) == 1
    assert users[0].name == "李乖乖🍓"
    assert users[0].message_preview == "你好"
    assert users[0].unread_count == 2


@pytest.mark.parametrize(
    "message_like_text",
    [
        "你好",
        "好",
        "日结的有哪些平台啊",
        "你好，你们那个主管老师怎么不回话了呀",
    ],
)
def test_message_like_text_without_name_evidence_is_not_extracted_as_user(extractor, message_like_text):
    row = _row(
        _text(message_like_text, bounds=(128, 112, 700, 146)),
        _text("2", rid="com.tencent.wework:id/unread_count", bounds=(86, 96, 120, 130)),
    )

    users = extractor.extract_from_tree(_tree(row))

    assert users == []


def test_b_number_customer_can_still_be_used_as_fallback_name(extractor):
    row = _row(
        _text("B2605100011-(保底正常)", bounds=(128, 112, 620, 146)),
        _text("您好", bounds=(128, 156, 520, 188)),
        _text("3", rid="com.tencent.wework:id/unread_count", bounds=(86, 96, 120, 130)),
    )

    users = extractor.extract_from_tree(_tree(row))

    assert len(users) == 1
    assert users[0].name == "B2605100011-(保底正常)"
    assert users[0].message_preview == "您好"
    assert users[0].unread_count == 3


def test_plain_nickname_with_position_evidence_can_still_be_fallback_name(extractor):
    row = _row(
        _text("牛奶奥利奥", bounds=(128, 112, 420, 146)),
        _text("[Voice Call]Call has been canceled", bounds=(128, 156, 720, 188)),
        _text("4", rid="com.tencent.wework:id/unread_count", bounds=(86, 96, 120, 130)),
    )

    users = extractor.extract_from_tree(_tree(row))

    assert len(users) == 1
    assert users[0].name == "牛奶奥利奥"
    assert users[0].message_preview == "[Voice Call]Call has been canceled"
    assert users[0].unread_count == 4


# ---------------------------------------------------------------------------
# Swap-bug regression tests (2026-05-14)
# ---------------------------------------------------------------------------


def test_swap_corrected_when_preview_node_has_name_resourceId(extractor):
    """Production bug: preview node resourceId contained 'title', causing name/preview swap.

    Log evidence: User: 我想做哔哩哔哩 | Preview: '1766909895-[重复(保底正常)]'
    """
    row = _row(
        _text(
            "我想做哔哩哔哩",
            rid="com.tencent.wework:id/titleTv",
            bounds=(128, 156, 700, 188),
        ),
        _text(
            "1766909895-[重复(保底正常)]",
            rid="com.tencent.wework:id/mid2Txt",
            bounds=(128, 112, 620, 146),
        ),
        _text("1", rid="com.tencent.wework:id/unread_count", bounds=(86, 96, 120, 130)),
    )

    users = extractor.extract_from_tree(_tree(row))

    assert len(users) == 1
    assert users[0].name == "1766909895-[重复(保底正常)]"
    assert users[0].message_preview == "我想做哔哩哔哩"


def test_swap_corrected_with_bili_prefix_real_name_in_preview(extractor):
    """Production bug: short message as name, bili-prefixed ID as preview.

    Log evidence: User: 有过几次 | Preview: 'bili_82076709740-1787652898(重复[保底正常])'
    """
    row = _row(
        _text("有过几次", rid="com.tencent.wework:id/titleTv", bounds=(128, 156, 700, 188)),
        _text(
            "bili_82076709740-1787652898(重复[保底正常])",
            bounds=(128, 112, 620, 146),
        ),
        _text("1", rid="com.tencent.wework:id/unread_count", bounds=(86, 96, 120, 130)),
    )

    users = extractor.extract_from_tree(_tree(row))

    assert len(users) == 1
    assert users[0].name == "bili_82076709740-1787652898(重复[保底正常])"
    assert users[0].message_preview == "有过几次"


def test_preview_hint_takes_priority_over_name_hint(extractor):
    """When a node matches BOTH name and preview hints, preview wins."""
    row = _row(
        _text(
            "B2605132089-(保底正常)",
            rid="com.tencent.wework:id/mid1Txt",
            bounds=(128, 112, 420, 146),
        ),
        _text(
            "你好呀",
            rid="com.tencent.wework:id/mid2Txt",
            bounds=(128, 156, 520, 188),
        ),
        _text("2", rid="com.tencent.wework:id/unread_count", bounds=(86, 96, 120, 130)),
    )

    users = extractor.extract_from_tree(_tree(row))

    assert len(users) == 1
    assert users[0].name == "B2605132089-(保底正常)"
    assert users[0].message_preview == "你好呀"


def test_no_false_swap_on_correct_data(extractor):
    """Correct extraction should NOT be swapped."""
    row = _row(
        _text("李乖乖🍓", rid="com.tencent.wework:id/title", bounds=(128, 112, 420, 146)),
        _text("你好", rid="com.tencent.wework:id/snippet", bounds=(128, 156, 520, 188)),
        _text("2", rid="com.tencent.wework:id/unread_count", bounds=(86, 96, 120, 130)),
    )

    users = extractor.extract_from_tree(_tree(row))

    assert len(users) == 1
    assert users[0].name == "李乖乖🍓"
    assert users[0].message_preview == "你好"


def test_no_swap_when_both_look_ambiguous(extractor):
    """If both name and preview are ambiguous, no swap should happen."""
    row = _row(
        _text("好的", rid="com.tencent.wework:id/title", bounds=(128, 112, 420, 146)),
        _text("可以", bounds=(128, 156, 520, 188)),
        _text("1", rid="com.tencent.wework:id/unread_count", bounds=(86, 96, 120, 130)),
    )

    users = extractor.extract_from_tree(_tree(row))

    # "好的" was assigned by resourceId (title) and should stay as name
    # because "可以" is not clearly a customer name either
    assert len(users) == 1
    assert users[0].name == "好的"
