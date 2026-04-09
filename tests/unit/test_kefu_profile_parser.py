"""
Unit tests for the shared kefu profile parser.
"""

import sys

from wecom_automation.core.config import get_project_root

project_root = get_project_root()
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

from wecom_automation.utils.kefu_profile_parser import extract_kefu_from_tree, parse_kefu_profile  # noqa: E402


def test_extract_kefu_from_structured_profile_block():
    """The parser should choose the profile block and keep role text out of the name."""
    tree = {
        "className": "android.widget.FrameLayout",
        "packageName": "com.tencent.wework",
        "children": [
            {
                "className": "android.widget.TextView",
                "resourceId": "com.tencent.wework:id/name",
                "text": "\u6c88\u5b50\u6db5",
                "bounds": "[208,112][316,154]",
            },
            {
                "className": "android.widget.TextView",
                "resourceId": "com.tencent.wework:id/role",
                "text": "\u7ecf\u7eaa\u4eba",
                "bounds": "[208,154][292,187]",
            },
            {
                "className": "android.widget.TextView",
                "resourceId": "com.tencent.wework:id/department",
                "text": "\u6167\u83b1\u6587\u5316",
                "bounds": "[208,187][320,225]",
            },
            {
                "className": "android.widget.TextView",
                "resourceId": "com.tencent.wework:id/file_desc",
                "text": "Full Image (255K)",
                "bounds": "[208,330][430,368]",
            },
            {
                "className": "android.widget.TextView",
                "resourceId": "com.tencent.wework:id/other_department",
                "text": "302\u5b9e\u9a8c\u5ba4",
                "bounds": "[160,440][328,512]",
            },
        ],
    }

    kefu = extract_kefu_from_tree(tree)
    parsed = parse_kefu_profile(tree)

    assert parsed is not None
    assert parsed.name_raw == "\u6c88\u5b50\u6db5"
    assert parsed.role == "\u7ecf\u7eaa\u4eba"
    assert parsed.department == "\u6167\u83b1\u6587\u5316"

    assert kefu is not None
    assert kefu.name == "\u6c88\u5b50\u6db5"
    assert kefu.department == "\u6167\u83b1\u6587\u5316"


def test_extract_kefu_normalizes_small_account_suffix():
    """The parser should normalize small-account suffixes to the main kefu name."""
    tree = {
        "className": "android.widget.FrameLayout",
        "packageName": "com.tencent.wework",
        "children": [
            {
                "className": "android.widget.TextView",
                "resourceId": "com.tencent.wework:id/name",
                "text": "\u6c88\u5b50\u6db5\u5c0f\u53f7",
                "bounds": "[312,168][543,231]",
            },
            {
                "className": "android.widget.TextView",
                "resourceId": "com.tencent.wework:id/role",
                "text": "\u7ecf\u7eaa\u4eba",
                "bounds": "[312,231][438,280]",
            },
            {
                "className": "android.widget.TextView",
                "resourceId": "com.tencent.wework:id/department",
                "text": "\u6167\u83b1\u6587\u5316",
                "bounds": "[312,280][456,322]",
            },
        ],
    }

    kefu = extract_kefu_from_tree(tree)
    parsed = parse_kefu_profile(tree)

    assert parsed is not None
    assert parsed.name_raw == "\u6c88\u5b50\u6db5\u5c0f\u53f7"
    assert parsed.name == "\u6c88\u5b50\u6db5"

    assert kefu is not None
    assert kefu.name == "\u6c88\u5b50\u6db5"
    assert kefu.department == "\u6167\u83b1\u6587\u5316"
