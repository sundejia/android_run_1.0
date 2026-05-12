"""Regression tests for the new-friend welcome keyword lists.

Both `UnreadUserExtractor` implementations (sync_service.py and unread_detector.py)
keep their own copy of `NEW_FRIEND_WELCOME_KEYWORDS`. They MUST stay in sync, and
they MUST NOT contain over-broad keywords that would match ordinary agent replies.

Background: a previously included keyword `"感谢您"` matched the agent's polite
phrase `"感谢您的考虑"` (and similar), causing replied-to old customers to be
flagged `is_new_friend=True`. On 2026-05-09 this trapped one customer in a
priority-queue / click-cooldown loop for 5.5 hours
(see docs/04-bugs-and-fixes/resolved/2026-05-12-new-friend-false-positive-click-loop.md).
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def _sync_service_extractor():
    from wecom_automation.services.sync_service import UnreadUserExtractor

    return UnreadUserExtractor


def _user_module_extractor():
    from wecom_automation.services.user.unread_detector import UnreadUserExtractor

    return UnreadUserExtractor


# ---------------------------------------------------------------------------
# Parity: the two class-level tuples must be identical
# ---------------------------------------------------------------------------


def test_new_friend_keyword_lists_match_between_sync_service_and_user_module():
    sync_kw = _sync_service_extractor().NEW_FRIEND_WELCOME_KEYWORDS
    user_kw = _user_module_extractor().NEW_FRIEND_WELCOME_KEYWORDS

    assert tuple(sync_kw) == tuple(user_kw), (
        "NEW_FRIEND_WELCOME_KEYWORDS drift between sync_service.py and "
        "user/unread_detector.py. Keep the two copies in lock-step (or move them "
        "to a shared module). Drift produced a 5h outage on 2026-05-09."
    )


# ---------------------------------------------------------------------------
# Forbidden over-broad keywords: must never appear in either list
# ---------------------------------------------------------------------------


_OVERLY_BROAD_KEYWORDS_THAT_MUST_NOT_BE_ADDED = (
    "感谢您",  # matches "感谢您的考虑/咨询/耐心等待…" - common agent reply
    "感谢",  # even broader; would match almost any agent reply
    "您好",  # generic greeting
    "你好",  # generic greeting
    "请问",  # generic question opener
)


def test_sync_service_keyword_list_has_no_over_broad_prefixes():
    forbidden = set(_OVERLY_BROAD_KEYWORDS_THAT_MUST_NOT_BE_ADDED)
    kws = set(_sync_service_extractor().NEW_FRIEND_WELCOME_KEYWORDS)
    intersect = forbidden & kws
    assert not intersect, (
        f"Forbidden over-broad keyword(s) present in sync_service.py: {intersect}. "
        "See docs/04-bugs-and-fixes/resolved/2026-05-12-new-friend-false-positive-click-loop.md"
    )


def test_user_module_keyword_list_has_no_over_broad_prefixes():
    forbidden = set(_OVERLY_BROAD_KEYWORDS_THAT_MUST_NOT_BE_ADDED)
    kws = set(_user_module_extractor().NEW_FRIEND_WELCOME_KEYWORDS)
    intersect = forbidden & kws
    assert not intersect, (
        f"Forbidden over-broad keyword(s) present in user/unread_detector.py: {intersect}. "
        "See docs/04-bugs-and-fixes/resolved/2026-05-12-new-friend-false-positive-click-loop.md"
    )


# ---------------------------------------------------------------------------
# Positive matches: genuine welcome messages must still be detected
# ---------------------------------------------------------------------------


_GENUINE_WELCOME_PREVIEWS = (
    "感谢您信任并选择WELIKE，未来我将会在该账号与您保持沟通。",
    "我已经添加了你，现在我们可以开始聊天了",
    "你已添加了张三，现在可以开始聊天了",
    "我通过了你的好友请求，现在我们可以开始聊天了",
    "You have added 乐迪^ as your WeCom contact. Start chatting!",
    "I've accepted your friend request. Now we can chat!",
)


def test_sync_service_detects_genuine_welcome_previews():
    extractor = _sync_service_extractor()
    for preview in _GENUINE_WELCOME_PREVIEWS:
        assert extractor._is_new_friend_welcome(preview), (
            f"Genuine welcome preview not detected by sync_service: {preview!r}"
        )


def test_user_module_detects_genuine_welcome_previews():
    extractor = _user_module_extractor()
    for preview in _GENUINE_WELCOME_PREVIEWS:
        assert extractor._is_new_friend_welcome(preview), (
            f"Genuine welcome preview not detected by user module: {preview!r}"
        )


# ---------------------------------------------------------------------------
# Negative matches: agent business replies must NOT be flagged as welcomes
# ---------------------------------------------------------------------------


_AGENT_BUSINESS_REPLIES_MUST_NOT_MATCH = (
    # The exact preview that broke 2026-05-09 (B2605080143-(保底正常)):
    "您好，感谢您的考虑。我们提供的待遇和直播形式都很灵活，"
    "旨在为您提供一个舒适的直播环境。不论您选择音频还是视频直播，"
    "我们都会提供相应的支持和指导。[海王老师]",
    # Common agent reply variants that would have matched the old "感谢您" keyword:
    "感谢您的咨询，请问您之前有直播经验吗？",
    "感谢您的耐心等待，资料已为您准备好。",
    "感谢您的支持，期待与您合作。",
    # Other common greetings that must not be treated as new-friend signals:
    "您好，请问需要什么帮助？",
    "你好呀，我是海王老师～",
    "请问您方便发一下半身照吗？",
    # Edge case: a customer message that just contains 选择 (no WELIKE):
    "我想选择视频直播",
)


def test_sync_service_rejects_agent_business_replies():
    extractor = _sync_service_extractor()
    for preview in _AGENT_BUSINESS_REPLIES_MUST_NOT_MATCH:
        assert not extractor._is_new_friend_welcome(preview), (
            f"Agent business reply was incorrectly flagged as new-friend welcome "
            f"by sync_service: {preview!r}"
        )


def test_user_module_rejects_agent_business_replies():
    extractor = _user_module_extractor()
    for preview in _AGENT_BUSINESS_REPLIES_MUST_NOT_MATCH:
        assert not extractor._is_new_friend_welcome(preview), (
            f"Agent business reply was incorrectly flagged as new-friend welcome "
            f"by user module: {preview!r}"
        )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_or_none_preview_is_not_a_welcome():
    sync_extractor = _sync_service_extractor()
    user_extractor = _user_module_extractor()

    for preview in ("", None):
        assert not sync_extractor._is_new_friend_welcome(preview)  # type: ignore[arg-type]
        assert not user_extractor._is_new_friend_welcome(preview)  # type: ignore[arg-type]
