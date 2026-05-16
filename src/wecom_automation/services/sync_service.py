"""
Sync Service - Orchestrates the full conversation synchronization workflow.

This service handles:
- Initial database sync of all conversations
- Voice message handling with user interaction
- Image message storage
- Anti-detection measures with human-like delays
- Priority syncing for users with unread messages
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from wecom_automation.core.config import Config, get_project_root
from wecom_automation.core.logging import get_logger, log_operation
from wecom_automation.core.models import ConversationMessage, UserDetail
from wecom_automation.database.models import (
    CustomerRecord,
    DeviceRecord,
    KefuRecord,
    MessageRecord,
    MessageType,
    VideoRecord,
)
from wecom_automation.database.repository import ConversationRepository
from wecom_automation.services.blacklist_service import BlacklistChecker
from wecom_automation.services.timestamp_parser import TimestampContext, TimestampParser
from wecom_automation.services.wecom_service import WeComService


class VoiceHandlerAction(str, Enum):
    """Actions for handling voice messages without captions."""

    CAPTION = "caption"  # User will reveal caption on screen
    INPUT = "input"  # User will type the spoken text
    PLACEHOLDER = "placeholder"  # Use placeholder text
    SKIP = "skip"  # Skip this message


class HumanTiming:
    """
    Provides randomized delays to simulate human behavior.

    This helps avoid detection as automated behavior.
    """

    def __init__(self, multiplier: float = 1.0):
        """
        Initialize timing with optional multiplier.

        Args:
            multiplier: Factor to multiply all delays (>1 for slower, <1 for faster)
        """
        self.multiplier = multiplier

    def get_tap_delay(self) -> float:
        """Get delay after a tap action (0.5-2.0s)."""
        return random.uniform(0.5, 2.0) * self.multiplier

    def get_scroll_delay(self) -> float:
        """Get delay after scrolling (1.0-3.0s)."""
        return random.uniform(1.0, 3.0) * self.multiplier

    def get_type_delay(self) -> float:
        """Get delay after typing (0.3-1.0s)."""
        return random.uniform(0.3, 1.0) * self.multiplier

    def get_user_switch_delay(self) -> float:
        """Get delay when switching between users (3.0-5.0s)."""
        return random.uniform(3.0, 5.0) * self.multiplier

    def get_read_delay(self) -> float:
        """Get delay to simulate reading messages (1.0-2.0s)."""
        return random.uniform(1.0, 2.0) * self.multiplier

    def get_scroll_distance(self) -> int:
        """Get randomized scroll distance (500-700 pixels)."""
        return random.randint(500, 700)


# =============================================================================
# UNREAD USER DETECTION
# =============================================================================


@dataclass
class UnreadUserInfo:
    """
    Information about a user with potential unread messages.

    Attributes:
        name: 用户名称
        unread_count: 未读消息数
        channel: 渠道标识 (如 @WeChat)
        last_message_date: 最后消息日期
        message_preview: 消息预览
        avatar_bounds: 头像边界坐标
        is_new_friend: 是否为新好友（消息预览包含欢迎语）
    """

    name: str
    unread_count: int = 0
    channel: str | None = None
    last_message_date: str | None = None
    message_preview: str | None = None
    avatar_bounds: str | None = None
    is_new_friend: bool = False  # 新好友标记

    def unique_key(self) -> str:
        """Generate a unique key for deduplication."""
        return f"{self.name}|{self.channel or ''}"

    def has_unread(self) -> bool:
        """是否有未读消息"""
        return self.unread_count > 0

    def is_priority(self) -> bool:
        """
        判断是否为高优先级用户

        高优先级条件：
        1. 有未读消息（红点）
        2. 或者是新好友（消息预览包含欢迎语）

        Returns:
            True 如果是高优先级用户
        """
        return self.unread_count > 0 or self.is_new_friend


class UnreadUserExtractor:
    """
    Utility class for extracting users with unread message badges from UI tree.

    This reuses logic from extract_unread_users.py but is integrated into the sync service.
    """

    # Badge detection hints
    BADGE_CLASS_HINTS = ("textview", "text", "badge", "unread", "count", "number")
    BADGE_RESOURCE_ID_HINTS = ("badge", "unread", "count", "num", "dot", "red")
    NAME_RESOURCE_ID_HINTS = ("title", "name", "nickname", "username", "contact", "mid1txt")
    PREVIEW_RESOURCE_ID_HINTS = (
        "content",
        "summary",
        "desc",
        "preview",
        "snippet",
        "message",
        "msg",
        "body",
        "mid2txt",
        "idk",
        "icx",
        "ig6",
        "igj",
    )
    CHANNEL_TEXT_PATTERNS = ("@WeChat", "@微信", "@wechat", "＠WeChat", "＠微信", "＠wechat")

    # Container detection hints
    MESSAGE_LIST_CLASS_HINTS = ("recyclerview", "listview", "viewpager", "listlayout", "viewgroup")
    MESSAGE_LIST_ID_HINTS = ("conversation", "session", "message", "msg", "chat", "recent", "list", "inbox")

    # Elements to exclude
    DROPDOWN_FILTER_PATTERNS = (
        "private",
        "私聊",
        "单聊",
        "all",
        "全部",
        "group",
        "群聊",
        "unread",
        "未读",
        "mention",
        "@我",
        "cal",
        "日历",
        "calendar",
        "meeting",
        "会议",
    )
    GENERIC_MESSAGE_NAMES = {"你好", "您好", "好", "嗯", "嗯呐", "哈喽", "hello", "hi", "？", "?"}
    MESSAGE_TEXT_HINTS = (
        "怎么",
        "什么",
        "哪些",
        "平台",
        "日结",
        "月结",
        "回复",
        "主管",
        "老师",
        "吗",
        "呢",
        "呀",
        "啊",
        "请问",
        "可以",
        "是不是",
        "有没有",
    )

    # 新好友欢迎语关键词 - 用于识别刚添加的好友
    #
    # 必须与 wecom_automation.services.user.unread_detector.UnreadUserExtractor.NEW_FRIEND_WELCOME_KEYWORDS
    # 保持一致；两份清单的 parity 由 tests/unit/test_new_friend_welcome_keywords.py 锁定。
    #
    # 注意：禁止加入泛化前缀（例如裸的 "感谢您"），否则会命中客服自己的业务话术
    # （"感谢您的考虑"、"感谢您的咨询"等），把已应答的老客户错误标成新好友、
    # 反复推进 priority 队列触发 click 失败 + cooldown 死循环
    # （详见 docs/04-bugs-and-fixes/resolved/2026-05-12-new-friend-false-positive-click-loop.md）。
    NEW_FRIEND_WELCOME_KEYWORDS = (
        # 英文关键词 - 添加新好友系统消息
        "You have added",
        "as your WeCom",
        "I've accepted your",
        "Now we can chat",
        # 中文关键词 - WELIKE 欢迎语（业务文案，足够特异）
        "感谢您信任并选择WELIKE",
        "感谢您信任",
        "选择WELIKE",
        "未来我将会",
        # 中文关键词 - WeCom 系统通知（添加/通过好友请求）
        "我通过了你的",
        "你已添加了",  # "你已添加了XXX，现在可以开始聊天了"
        "现在我们可以开始聊天了",
        "现在可以开始聊天了",  # 不带"我们"的变体
    )

    @staticmethod
    def _get_node_bounds(node: dict[str, Any]) -> str | None:
        """Get bounds from a node."""
        bounds_keys = ["bounds", "visibleBounds", "boundsInScreen", "boundsInParent", "rect"]
        for key in bounds_keys:
            bounds = node.get(key)
            if bounds:
                if isinstance(bounds, str) and "[" in bounds:
                    return bounds
                if isinstance(bounds, dict):
                    x1 = bounds.get("left", bounds.get("x", bounds.get("x1", 0)))
                    y1 = bounds.get("top", bounds.get("y", bounds.get("y1", 0)))
                    x2 = bounds.get("right", bounds.get("x2", x1 + bounds.get("width", 0)))
                    y2 = bounds.get("bottom", bounds.get("y2", y1 + bounds.get("height", 0)))
                    return f"[{x1},{y1}][{x2},{y2}]"
                if isinstance(bounds, (list, tuple)) and len(bounds) >= 4:
                    return f"[{bounds[0]},{bounds[1]}][{bounds[2]},{bounds[3]}]"
        return None

    @staticmethod
    def _parse_bounds(bounds: str) -> tuple[int, int, int, int] | None:
        """Parse bounds string into (x1, y1, x2, y2) tuple."""
        if not bounds:
            return None
        try:
            match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
            if match:
                return tuple(map(int, match.groups()))
        except (ValueError, AttributeError):
            pass
        return None

    @staticmethod
    def _collect_all_nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
        """Flatten the tree into a list of all nodes."""
        results = [node]
        children = node.get("children") or []
        for child in children:
            if isinstance(child, dict):
                results.extend(UnreadUserExtractor._collect_all_nodes(child))
        return results

    @staticmethod
    def _is_badge_text(text: str) -> bool:
        """Check if text looks like an unread badge number."""
        if not text:
            return False
        text = text.strip()
        if text.isdigit():
            return True
        if re.match(r"^\d+\+?$", text):
            return True
        return False

    @staticmethod
    def _looks_like_timestamp(value: str) -> bool:
        """Check whether the string looks like a time or date."""
        if not value:
            return False
        value_lower = value.lower().strip()

        if re.search(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", value):
            return True
        if re.search(r"\b\d{1,2}/\d{1,2}\b", value):
            return True
        if re.search(r"\b\d+\s*(?:min|mins|minute|minutes|hr|hrs|hour|hours|day|days)\s*ago\b", value, re.IGNORECASE):
            return True
        if re.search(r"\d+\s*(?:分钟|小时|天|秒)前", value):
            return True

        day_names = (
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
            "星期一",
            "星期二",
            "星期三",
            "星期四",
            "星期五",
            "星期六",
            "星期日",
            "周一",
            "周二",
            "周三",
            "周四",
            "周五",
            "周六",
            "周日",
            "yesterday",
            "昨天",
            "today",
            "今天",
            "just now",
            "刚刚",
        )
        for day in day_names:
            if day.lower() in value_lower:
                return True
        return False

    @staticmethod
    def _looks_like_channel(value: str) -> bool:
        """Check whether the string looks like a channel indicator."""
        if not value:
            return False
        value_lower = value.lower().strip()
        for pattern in UnreadUserExtractor.CHANNEL_TEXT_PATTERNS:
            if pattern.lower() in value_lower:
                return True
        if (value.startswith("@") or value.startswith("＠")) and len(value) < 20:
            return True
        return False

    @staticmethod
    def _looks_like_dropdown_filter(name: str) -> bool:
        """Check whether the name looks like a dropdown/filter UI element."""
        if not name:
            return False
        name_lower = name.lower().strip()
        for pattern in UnreadUserExtractor.DROPDOWN_FILTER_PATTERNS:
            if pattern.lower() in name_lower:
                return True
        return False

    @classmethod
    def _is_new_friend_welcome(cls, message_preview: str) -> bool:
        """
        检查消息预览是否包含新好友欢迎语

        Args:
            message_preview: 消息预览文本

        Returns:
            True 如果包含欢迎语关键词
        """
        if not message_preview:
            return False
        for keyword in cls.NEW_FRIEND_WELCOME_KEYWORDS:
            if keyword in message_preview:
                return True
        return False

    @classmethod
    def _looks_like_message_text(cls, value: str) -> bool:
        """Return True when a fallback name candidate looks like chat preview text."""
        if not value:
            return True

        text = value.strip()
        if len(text) <= 1:
            return True

        lowered = text.lower()
        if lowered in cls.GENERIC_MESSAGE_NAMES:
            return True

        if re.match(r"^B\d{8,}", text):
            return False

        if any(mark in text for mark in ("，", "。", "！", "？", ",", "!", "?")):
            return True

        if len(text) >= 4 and any(hint in text for hint in cls.MESSAGE_TEXT_HINTS):
            return True

        # Long fallback strings without a name resource are much more likely to
        # be snippets than contact names. Strong resource-ID matches are handled
        # before this fallback check.
        if len(text) > 18:
            return True

        return False

    @classmethod
    def _looks_like_customer_name(cls, value: str) -> bool:
        """Check if text looks like a customer name (as opposed to a message preview)."""
        if not value:
            return False
        text = value.strip()
        if len(text) <= 1:
            return False
        # B-prefixed IDs: B2605132089-(保底正常)
        if re.match(r"^B\d{8,}", text):
            return True
        # bili-prefixed IDs: bili_82076709740-1787652898(重复[保底正常])
        if re.match(r"^bili_\d+", text):
            return True
        # Numeric IDs with optional tags: 1766909895-[重复(保底正常)]
        if re.match(r"^\d{4,}", text):
            return True
        # Alphanumeric ID patterns with brackets/parentheses (system-generated names)
        if re.match(r"^[\w]+_\d+-\d+", text):
            return True
        # Short Chinese names: 2-4 chars, no punctuation/message particles
        if 2 <= len(text) <= 4:
            if not any(mark in text for mark in ("，", "。", "！", "？", ",", "!", "?")):
                if not any(hint in text for hint in cls.MESSAGE_TEXT_HINTS):
                    return True
        # Names with emoji (common in WeChat display names)
        if re.search(r"[\U0001F300-\U0001F9FF]", text):
            return True
        return False

    @classmethod
    def _is_strong_customer_id(cls, value: str) -> bool:
        """Check if text is a strong (system-generated) customer identifier.

        Matches B-prefixed IDs, bili-prefixed IDs, and numeric IDs with brackets.
        These are unambiguous — they can never be message text.
        """
        if not value:
            return False
        text = value.strip()
        if re.match(r"^B\d{8,}", text):
            return True
        if re.match(r"^bili_\d+", text):
            return True
        if re.match(r"^\d{4,}", text):
            return True
        if re.match(r"^[\w]+_\d+-\d+", text):
            return True
        return False

    @classmethod
    def _check_and_fix_name_preview_swap(
        cls, name: str | None, message_preview: str | None
    ) -> tuple[str | None, str | None]:
        """Detect and correct name/preview swaps after extraction."""
        if not name or not message_preview:
            return name, message_preview
        # Strong ID in preview + current name is NOT a strong ID → swap
        if cls._is_strong_customer_id(message_preview) and not cls._is_strong_customer_id(name):
            return message_preview, name
        # Generic: preview clearly looks like a name but name clearly does not
        name_is_name = cls._looks_like_customer_name(name)
        preview_is_name = cls._looks_like_customer_name(message_preview)
        if preview_is_name and not name_is_name:
            return message_preview, name
        return name, message_preview

    @classmethod
    def _is_name_position_candidate(
        cls,
        node: dict[str, Any],
        avatar_bounds: tuple[int, int, int, int] | None,
    ) -> bool:
        """Check whether a text node sits where a conversation title normally appears."""
        bounds = cls._get_node_bounds(node)
        if not bounds:
            return False

        parsed = cls._parse_bounds(bounds)
        if not parsed:
            return False

        x1, y1, _x2, y2 = parsed
        if not avatar_bounds:
            return x1 >= 90

        av_x1, av_y1, av_x2, av_y2 = avatar_bounds
        avatar_height = max(av_y2 - av_y1, 1)
        text_center_y = (y1 + y2) // 2

        return x1 >= av_x2 - 10 and av_x1 < x1 and text_center_y <= av_y1 + int(avatar_height * 0.75)

    @classmethod
    def _is_plausible_fallback_name(
        cls,
        text: str,
        node: dict[str, Any],
        avatar_bounds: tuple[int, int, int, int] | None,
    ) -> bool:
        """Validate heuristic name candidates before they enter the click queue."""
        if not text:
            return False
        if cls._is_badge_text(text) or cls._looks_like_timestamp(text) or cls._looks_like_channel(text):
            return False
        if cls._looks_like_dropdown_filter(text):
            return False
        if cls._looks_like_message_text(text):
            return False
        return cls._is_name_position_candidate(node, avatar_bounds)

    @classmethod
    def _find_avatar_bounds_in_row(cls, all_nodes: list[dict[str, Any]]) -> tuple[int, int, int, int] | None:
        """Find the avatar bounds in a row."""
        avatar_class_hints = ("imageview", "image", "avatar", "icon", "photo")
        avatar_resource_id_hints = ("avatar", "photo", "icon", "head", "portrait", "profile")

        for node in all_nodes:
            bounds = cls._get_node_bounds(node)
            if not bounds:
                continue
            parsed = cls._parse_bounds(bounds)
            if not parsed:
                continue

            x1, y1, x2, y2 = parsed
            width = x2 - x1
            height = y2 - y1

            class_name = (node.get("className") or "").lower()
            resource_id = (node.get("resourceId") or "").lower()

            if "textview" in class_name or "text" in class_name:
                continue
            if width > 300:
                continue

            is_avatar_rid = any(hint in resource_id for hint in avatar_resource_id_hints)
            is_avatar_class = any(hint in class_name for hint in avatar_class_hints)
            is_left_side = x1 < 200
            is_avatar_size = 40 <= width <= 150 and 40 <= height <= 150
            aspect_ratio = width / height if height > 0 else 0
            is_square = 0.7 <= aspect_ratio <= 1.3

            if is_avatar_rid or (is_avatar_class and is_left_side and is_avatar_size and is_square):
                return parsed
        return None

    @classmethod
    def _find_badge_in_row(
        cls, all_nodes: list[dict[str, Any]], avatar_bounds: tuple[int, int, int, int] | None
    ) -> tuple[int, str] | None:
        """Find the unread badge number in a row."""
        badge_candidates: list[tuple[int, int, str]] = []  # (count, score, bounds)

        for node in all_nodes:
            text = (node.get("text") or "").strip()
            if not text or not cls._is_badge_text(text):
                continue

            bounds = cls._get_node_bounds(node)
            if not bounds:
                continue

            parsed = cls._parse_bounds(bounds)
            if not parsed:
                continue

            x1, y1, x2, y2 = parsed
            width = x2 - x1
            height = y2 - y1

            class_name = (node.get("className") or "").lower()
            resource_id = (node.get("resourceId") or "").lower()

            score = 0

            for hint in cls.BADGE_RESOURCE_ID_HINTS:
                if hint in resource_id:
                    score += 20
                    break

            for hint in cls.BADGE_CLASS_HINTS:
                if hint in class_name:
                    score += 5
                    break

            if 15 <= width <= 60 and 15 <= height <= 60:
                score += 15
            elif 10 <= width <= 80 and 10 <= height <= 80:
                score += 8

            if avatar_bounds:
                av_x1, av_y1, av_x2, av_y2 = avatar_bounds
                badge_center_x = (x1 + x2) // 2
                badge_center_y = (y1 + y2) // 2

                if av_x2 - 20 <= badge_center_x <= av_x2 + 30:
                    score += 15
                elif av_x2 - 40 <= badge_center_x <= av_x2 + 50:
                    score += 8

                if av_y1 - 20 <= badge_center_y <= av_y1 + 40:
                    score += 15
                elif av_y1 - 30 <= badge_center_y <= av_y1 + 60:
                    score += 8
            else:
                if x1 < 200:
                    score += 10

            if len(text) <= 3:
                score += 5

            try:
                if text.endswith("+"):
                    count = int(text[:-1])
                else:
                    count = int(text)
            except ValueError:
                continue

            if score >= 20:
                badge_candidates.append((count, score, bounds))

        if badge_candidates:
            badge_candidates.sort(key=lambda x: x[1], reverse=True)
            count, _, bounds = badge_candidates[0]
            return (count, bounds)
        return None

    @classmethod
    def _find_message_containers(cls, nodes: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        """Locate probable conversation list containers."""
        candidates: list[dict[str, Any]] = []
        stack: list[dict[str, Any]] = list(nodes)

        # 获取屏幕宽度和高度（从根节点）
        screen_width = 1080  # 默认值
        screen_height = 2400  # 默认值
        if nodes:
            root = nodes[0] if isinstance(nodes, (list, tuple)) else nodes
            bounds = root.get("boundsInScreen", {})
            if isinstance(bounds, dict):
                screen_width = bounds.get("right", 1080) - bounds.get("left", 0)
                screen_height = bounds.get("bottom", 2400) - bounds.get("top", 0)

        while stack:
            node = stack.pop()
            children = node.get("children") or []
            stack.extend(child for child in children if isinstance(child, dict))

            if not children:
                continue

            class_name = (node.get("className") or "").lower()
            resource_id = (node.get("resourceId") or "").lower()
            package_name = (node.get("packageName") or "").lower()

            if package_name and "wework" not in package_name:
                continue

            is_list_class = any(hint in class_name for hint in cls.MESSAGE_LIST_CLASS_HINTS)
            is_list_id = any(hint in resource_id for hint in cls.MESSAGE_LIST_ID_HINTS)

            if is_list_class or is_list_id:
                candidates.append(node)

        def get_container_score(node: dict[str, Any]) -> tuple:
            """
            计算容器得分，用于排序。

            优先级（从高到低）：
            1. 不是全屏根容器（has_margin）- 排除覆盖整个屏幕的根节点
            2. 有 resourceId（has_resource_id）- 优先选择有明确标识的容器
            3. 是具体的列表类型（is_specific_list）- RecyclerView/ListView 优于 ViewGroup
            4. 全宽容器（is_full_width）
            5. 子节点数（child_count）
            """
            bounds = node.get("boundsInScreen", {})
            if isinstance(bounds, dict):
                left = bounds.get("left", 0)
                top = bounds.get("top", 0)
                right = bounds.get("right", 0)
                bottom = bounds.get("bottom", 0)
                width = right - left
                height = bottom - top
            else:
                left = top = width = height = 0

            # 1. 检查是否为全屏根容器（top 很小且高度接近屏幕高度）
            # 排除这种容器，因为它们通常包含导航栏等非对话列表元素
            is_likely_root = (top <= 50) and (height >= screen_height * 0.95)
            has_margin = not is_likely_root

            # 2. 是否有 resourceId
            resource_id = (node.get("resourceId") or "").strip()
            has_resource_id = bool(resource_id)

            # 3. 是否为具体的列表类型（RecyclerView/ListView 优于泛型 ViewGroup）
            class_name = (node.get("className") or "").lower()
            is_specific_list = "recyclerview" in class_name or "listview" in class_name

            # 4. 是否为全宽容器
            is_full_width = width >= screen_width * 0.95

            # 5. 子节点数
            child_count = len(node.get("children") or [])

            # 返回元组用于排序（从高到低优先级）
            return (has_margin, has_resource_id, is_specific_list, is_full_width, child_count)

        candidates.sort(key=get_container_score, reverse=True)
        return candidates

    @classmethod
    def _extract_entry_from_row(cls, row_node: dict[str, Any]) -> UnreadUserInfo | None:
        """Extract an UnreadUserInfo from a single row node."""
        all_nodes = cls._collect_all_nodes(row_node)

        avatar_bounds = cls._find_avatar_bounds_in_row(all_nodes)
        badge_result = cls._find_badge_in_row(all_nodes, avatar_bounds)
        unread_count = badge_result[0] if badge_result else 0

        text_nodes = []
        for n in all_nodes:
            # Check both text and contentDescription
            text = (n.get("text") or "").strip()
            if not text:
                text = (n.get("contentDescription") or "").strip()

            if text:
                # Add a temporary field to the node to store the resolved text for this session
                n["_resolved_text"] = text
                text_nodes.append(n)

        if not text_nodes:
            return None

        name: str | None = None
        channel: str | None = None
        last_message_date: str | None = None
        message_preview: str | None = None

        # First pass: identify by resource ID hints
        for tn in text_nodes:
            text = tn.get("_resolved_text", "")
            rid = (tn.get("resourceId") or "").lower()

            if not text:
                continue
            if cls._is_badge_text(text) and len(text) <= 3:
                continue

            matches_preview = any(hint in rid for hint in cls.PREVIEW_RESOURCE_ID_HINTS)
            matches_name = any(hint in rid for hint in cls.NAME_RESOURCE_ID_HINTS)

            if not message_preview and matches_preview:
                message_preview = text
                continue

            if not name and matches_name and not matches_preview:
                name = text
                continue

        # Second pass: identify by content patterns
        used_texts = {name, channel, last_message_date, message_preview}

        for tn in text_nodes:
            text = tn.get("_resolved_text", "")
            if not text or text in used_texts:
                continue
            if cls._is_badge_text(text) and len(text) <= 3:
                continue

            if not channel and cls._looks_like_channel(text):
                channel = text
                used_texts.add(text)
                continue

            if not last_message_date and cls._looks_like_timestamp(text):
                last_message_date = text
                used_texts.add(text)
                continue

        # Third pass: heuristic assignment
        remaining_nodes = []
        for tn in text_nodes:
            text = tn.get("_resolved_text", "")
            if text and text not in used_texts:
                if cls._is_badge_text(text) and len(text) <= 3:
                    continue
                remaining_nodes.append(tn)

        if not name and remaining_nodes:
            for idx, tn in enumerate(remaining_nodes):
                candidate = tn.get("_resolved_text", "")
                if cls._is_plausible_fallback_name(candidate, tn, avatar_bounds):
                    name = candidate
                    used_texts.add(name)
                    remaining_nodes = remaining_nodes[:idx] + remaining_nodes[idx + 1 :]
                    break

        remaining_texts = [tn.get("_resolved_text", "") for tn in remaining_nodes if tn.get("_resolved_text", "")]

        if not message_preview and remaining_texts:
            preview_candidates = [
                text
                for text in remaining_texts
                if not cls._looks_like_timestamp(text) and not cls._looks_like_channel(text)
            ]
            if preview_candidates:
                preview_candidates.sort(key=len, reverse=True)
                message_preview = preview_candidates[0]

        # Skip dropdown/filter elements
        if name and cls._looks_like_dropdown_filter(name):
            return None

        # Swap detection: validate name/preview consistency
        name, message_preview = cls._check_and_fix_name_preview_swap(name, message_preview)

        # 检测是否为新好友（消息预览包含欢迎语）
        is_new_friend = cls._is_new_friend_welcome(message_preview)

        if name:
            return UnreadUserInfo(
                name=name,
                unread_count=unread_count,
                channel=channel,
                last_message_date=last_message_date,
                message_preview=message_preview,
                avatar_bounds=f"[{avatar_bounds[0]},{avatar_bounds[1]}][{avatar_bounds[2]},{avatar_bounds[3]}]"
                if avatar_bounds
                else None,
                is_new_friend=is_new_friend,
            )
        return None

    @classmethod
    def extract_from_tree(cls, tree: Any) -> list[UnreadUserInfo]:
        """
        Extract users with unread counts from the UI tree.

        Returns ALL users (with or without unread messages).

        注意：只使用第一个有效容器（全宽优先），避免从隐藏/缓存的UI元素中提取错误数据。
        """
        roots = []
        if isinstance(tree, dict):
            roots = [tree]
        elif isinstance(tree, Sequence) and not isinstance(tree, str):
            roots = [node for node in tree if isinstance(node, dict)]

        containers = cls._find_message_containers(roots)
        if not containers:
            return []

        # 只使用第一个容器（已按全宽优先 + 子节点数排序）
        # 避免从非全宽的隐藏/缓存元素中提取错误数据
        all_entries: list[UnreadUserInfo] = []
        seen_keys = set()

        for container in containers:
            children = container.get("children", [])
            for child in children:
                if isinstance(child, dict):
                    entry = cls._extract_entry_from_row(child)
                    if entry:
                        key = entry.unique_key()
                        if key not in seen_keys:
                            all_entries.append(entry)
                            seen_keys.add(key)

            # 如果从第一个容器提取到了有效条目，则停止
            # 避免从其他非全宽容器中提取错误数据
            if all_entries:
                break

        return all_entries


# =============================================================================
# KEYBOARD MODE DETECTION AND SWITCHING
# =============================================================================


class KeyboardModeHelper:
    """
    Helper class for detecting and switching between voice and keyboard input modes.

    Integrates functionality from change-to-keyboard.py into the sync service.
    """

    # Voice mode indicators - text patterns that indicate voice input is active
    VOICE_MODE_PATTERNS = [
        "Hold\xa0to Talk",
        "按住 说话",
        "hold to talk",
        "按住说话",
    ]

    # Known resource IDs for the voice/keyboard toggle button
    TOGGLE_BUTTON_RESOURCE_IDS = [
        "com.tencent.wework:id/gdx",  # Known toggle button ID
    ]

    # Voice/keyboard toggle button resource ID hints (fallback)
    TOGGLE_RESOURCE_ID_HINTS = [
        "voice",
        "audio",
        "keyboard",
        "input_switch",
        "switch",
        "btn_voice",
        "btn_keyboard",
        "input_mode",
        "gdx",
    ]

    @staticmethod
    def _get_node_bounds(node: dict[str, Any]) -> str | None:
        """Get bounds from a node."""
        bounds_keys = ["boundsInScreen", "bounds", "visibleBounds", "boundsInParent", "rect"]
        for key in bounds_keys:
            bounds = node.get(key)
            if bounds:
                if isinstance(bounds, str) and "[" in bounds:
                    return bounds
                if isinstance(bounds, dict):
                    x1 = bounds.get("left", bounds.get("x", bounds.get("x1", 0)))
                    y1 = bounds.get("top", bounds.get("y", bounds.get("y1", 0)))
                    x2 = bounds.get("right", bounds.get("x2", x1 + bounds.get("width", 0)))
                    y2 = bounds.get("bottom", bounds.get("y2", y1 + bounds.get("height", 0)))
                    return f"[{x1},{y1}][{x2},{y2}]"
                if isinstance(bounds, (list, tuple)) and len(bounds) >= 4:
                    return f"[{bounds[0]},{bounds[1]}][{bounds[2]},{bounds[3]}]"
        return None

    @staticmethod
    def _parse_bounds(bounds: str) -> tuple[int, int, int, int] | None:
        """Parse bounds string into (x1, y1, x2, y2) tuple."""
        if not bounds:
            return None
        try:
            match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
            if match:
                return tuple(map(int, match.groups()))
        except (ValueError, AttributeError):
            pass
        return None

    @staticmethod
    def _get_center(bounds: str) -> tuple[int, int] | None:
        """Get center coordinates from bounds string."""
        parsed = KeyboardModeHelper._parse_bounds(bounds)
        if parsed:
            x1, y1, x2, y2 = parsed
            return ((x1 + x2) // 2, (y1 + y2) // 2)
        return None

    @staticmethod
    def _collect_all_nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
        """Flatten the tree into a list of all nodes."""
        results = [node]
        children = node.get("children") or []
        for child in children:
            if isinstance(child, dict):
                results.extend(KeyboardModeHelper._collect_all_nodes(child))
        return results

    @classmethod
    def find_voice_mode_button(cls, nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Find the 'hold to talk' button indicating voice mode is active."""
        for node in nodes:
            text = (node.get("text") or "").strip().lower()
            content_desc = (node.get("contentDescription") or "").strip().lower()

            for pattern in cls.VOICE_MODE_PATTERNS:
                if pattern.lower() in text or pattern.lower() in content_desc:
                    return node
        return None

    @classmethod
    def find_toggle_button(cls, nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Find the voice/keyboard toggle button."""
        # First, try to find by exact known resource ID
        for node in nodes:
            resource_id = node.get("resourceId") or ""
            for known_id in cls.TOGGLE_BUTTON_RESOURCE_IDS:
                if resource_id == known_id:
                    return node

        # Fallback: score-based detection
        candidates: list[tuple[dict[str, Any], int]] = []

        for node in nodes:
            class_name = (node.get("className") or "").lower()
            resource_id = (node.get("resourceId") or "").lower()
            content_desc = (node.get("contentDescription") or "").strip().lower()
            package_name = node.get("packageName") or ""

            if package_name and "wework" not in package_name.lower():
                continue

            bounds = cls._get_node_bounds(node)
            if not bounds:
                continue

            parsed = cls._parse_bounds(bounds)
            if not parsed:
                continue

            x1, y1, x2, y2 = parsed
            width = x2 - x1
            height = y2 - y1

            score = 0

            # Check resource ID for toggle hints
            for hint in cls.TOGGLE_RESOURCE_ID_HINTS:
                if hint in resource_id:
                    score += 30
                    break

            # Check content description
            voice_keywords = ["voice", "语音", "键盘", "keyboard", "audio", "录音"]
            for keyword in voice_keywords:
                if keyword.lower() in content_desc:
                    score += 25
                    break

            # Check if it's an ImageView
            if "android.widget.imageview" in class_name or class_name == "imageview":
                score += 20
            elif "imagebutton" in class_name:
                score += 15
            elif "button" in class_name:
                score += 10

            # Check size
            if 80 <= width <= 180 and 60 <= height <= 120:
                score += 15
            elif 30 <= width <= 200 and 30 <= height <= 150:
                score += 8

            # Check if clickable
            is_clickable = node.get("clickable") or node.get("isClickable")
            if is_clickable:
                score += 15

            # Check position (bottom-left of screen)
            if x1 == 0 and y1 > 2000:
                score += 30
            elif x1 < 150 and y1 > 2000:
                score += 25
            elif x1 < 200 and y1 > 1800:
                score += 15
            elif y1 > 1500:
                score += 5

            # Check if enabled
            is_enabled = node.get("enabled") or node.get("isEnabled")
            if is_enabled:
                score += 5

            if score >= 40:
                candidates.append((node, score))

        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            return candidates[0][0]

        return None

    @classmethod
    def is_voice_mode_active(cls, tree: Any) -> bool:
        """Check if voice mode is currently active."""
        roots = []
        if isinstance(tree, dict):
            roots = [tree]
        elif isinstance(tree, list):
            roots = [node for node in tree if isinstance(node, dict)]

        all_nodes = []
        for root in roots:
            all_nodes.extend(cls._collect_all_nodes(root))

        return cls.find_voice_mode_button(all_nodes) is not None

    @classmethod
    def get_toggle_button_position(cls, tree: Any) -> tuple[int, int] | None:
        """Get the center position of the toggle button."""
        roots = []
        if isinstance(tree, dict):
            roots = [tree]
        elif isinstance(tree, list):
            roots = [node for node in tree if isinstance(node, dict)]

        all_nodes = []
        for root in roots:
            all_nodes.extend(cls._collect_all_nodes(root))

        toggle_button = cls.find_toggle_button(all_nodes)
        if toggle_button:
            bounds = cls._get_node_bounds(toggle_button)
            return cls._get_center(bounds)

        return None


class InitialSyncService:
    """
    Service for performing initial conversation database synchronization.

    This service orchestrates the full workflow of:
    1. Opening WeCom
    2. Getting kefu information
    3. Navigating to private chats
    4. Extracting all customers
    5. Syncing each customer's conversation
    6. Handling special message types (voice, image)
    7. Sending test messages and waiting for responses

    Usage:
        sync = InitialSyncService(config, repository)
        await sync.run_initial_sync()
    """

    def __init__(
        self,
        config: Config | None = None,
        repository: ConversationRepository | None = None,
        db_path: str | None = None,
        images_dir: str | None = None,
        videos_dir: str | None = None,
        timing_multiplier: float = 1.0,
        blacklist_file: str | None = None,
    ):
        """
        Initialize the sync service.

        Args:
            config: Application configuration
            repository: Database repository (created if not provided)
            db_path: Path to SQLite database
            images_dir: Directory to store image messages
            videos_dir: Directory to store video messages
            timing_multiplier: Factor for timing delays (>1 = slower)
            blacklist_file: Path to user blacklist JSON file
        """
        self.config = config or Config()
        self.logger = get_logger("wecom_automation.sync")

        # Initialize repository
        self.db_path = db_path
        self.repository = repository or ConversationRepository(db_path)

        # Initialize WeComService
        self.wecom = WeComService(self.config)

        # Blacklist file for skipping users who requested human agent
        self.blacklist_file = Path(blacklist_file) if blacklist_file else None

        # Setup image storage
        self.images_dir = Path(images_dir or "conversation_images")
        self.images_dir.mkdir(parents=True, exist_ok=True)

        # Setup video storage
        self.videos_dir = Path(videos_dir or "conversation_videos")
        self.videos_dir.mkdir(parents=True, exist_ok=True)

        # Setup voice storage
        self.voices_dir = Path(images_dir or "conversation_images").parent / "conversation_voices"
        self.voices_dir.mkdir(parents=True, exist_ok=True)

        # Setup avatar storage (use project root avatars/ directory)
        # This ensures avatars are available to frontend via Vite's syncAvatarsPlugin
        self.avatars_dir = get_project_root() / "avatars"
        self.avatars_dir.mkdir(parents=True, exist_ok=True)

        # Human-like timing
        self.timing = HumanTiming(timing_multiplier)

        # Callback for voice message handling
        self._voice_handler_callback: Callable | None = None

        # Callback when customer sends voice message (for notifications)
        self._on_customer_voice_callback: Callable[[str, str | None, str], None] | None = None

        # Track current context
        self._current_device: DeviceRecord | None = None
        self._current_kefu: KefuRecord | None = None

        # Initialize timestamp parser with configured timezone
        self.timestamp_parser = TimestampParser(timezone=self.config.timezone)
        self._timestamp_context: TimestampContext | None = None

        # Checkpoint file for resume functionality
        db_dir = Path(db_path).parent if db_path else Path(".")
        self._checkpoint_file = db_dir / f"sync_checkpoint_{self.config.device_serial}.json"

    # =========================================================================
    # Blacklist Management
    # =========================================================================

    def _load_blacklist(self) -> dict:
        """Load blacklist from file."""
        if not self.blacklist_file or not self.blacklist_file.exists():
            return {"users": [], "updated_at": None}

        try:
            with open(self.blacklist_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self.logger.warning(f"Failed to load blacklist: {e}")
            return {"users": [], "updated_at": None}

    def is_user_blacklisted(self, customer_name: str, channel: str | None = None) -> bool:
        """
        Check if a user is in the blacklist.

        Checks both the file-based blacklist (legacy) and the database blacklist.

        Args:
            customer_name: Name of the customer
            channel: Optional channel/platform info

        Returns:
            True if user is blacklisted
        """
        # Check database blacklist first (preferred method)
        device_serial = self._current_device.serial if self._current_device else None
        if device_serial:
            if BlacklistChecker.is_blacklisted(device_serial, customer_name, channel):
                self.logger.info(f"⛔ User {customer_name} is blacklisted (database)")
                return True

        # Check file-based blacklist (legacy support)
        blacklist = self._load_blacklist()
        for user in blacklist.get("users", []):
            if user.get("name") == customer_name:
                # If channel is not specified, match any channel
                if channel is None or user.get("channel") == channel:
                    self.logger.info(
                        f"⛔ User {customer_name} is blacklisted (reason: {user.get('reason', 'unknown')})"
                    )
                    return True
        return False

    # =========================================================================
    # Checkpoint Management (Resume Functionality)
    # =========================================================================

    def _get_checkpoint(self) -> dict[str, Any] | None:
        """
        Load checkpoint data if exists.

        Returns:
            Checkpoint dict with 'synced_customers', 'stats', etc. or None
        """
        if not self._checkpoint_file.exists():
            return None

        try:
            with open(self._checkpoint_file, encoding="utf-8") as f:
                checkpoint = json.load(f)
            self.logger.info(
                f"Loaded checkpoint: {len(checkpoint.get('synced_customers', []))} customers already synced"
            )
            return checkpoint
        except Exception as e:
            self.logger.warning(f"Failed to load checkpoint: {e}")
            return None

    def _save_checkpoint(
        self,
        synced_customers: list[str],
        stats: dict[str, Any],
        total_customers: int,
        current_state: dict[str, Any] | None = None,
        all_customers: list[UserDetail] | None = None,
    ) -> None:
        """
        Save checkpoint data for resume.

        Args:
            synced_customers: List of customer names that have been synced
            stats: Current sync statistics
            total_customers: Total number of customers to sync
            current_state: P1 改进 - 当前界面状态，用于断连恢复
            all_customers: Optional list of all UserDetail objects to avoid re-extraction
        """
        checkpoint = {
            "device_serial": self.config.device_serial,
            "synced_customers": synced_customers,
            "stats": stats,
            "total_customers": total_customers,
            "last_updated": datetime.now().isoformat(),
            # P1 改进: 添加当前界面状态
            "current_state": current_state or {"phase": "list"},
        }

        if all_customers:
            checkpoint["all_customers"] = [u.to_dict() for u in all_customers]

        try:
            with open(self._checkpoint_file, "w", encoding="utf-8") as f:
                json.dump(checkpoint, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.warning(f"Failed to save checkpoint: {e}")

    def _clear_checkpoint(self) -> None:
        """Clear checkpoint file after successful completion."""
        try:
            if self._checkpoint_file.exists():
                self._checkpoint_file.unlink()
                self.logger.info("Checkpoint cleared")
        except Exception as e:
            self.logger.warning(f"Failed to clear checkpoint: {e}")

    def has_checkpoint(self) -> bool:
        """Check if a checkpoint exists for resume."""
        return self._checkpoint_file.exists()

    def get_checkpoint_info(self) -> dict[str, Any] | None:
        """
        Get checkpoint info for display.

        Returns:
            Dict with checkpoint summary or None
        """
        checkpoint = self._get_checkpoint()
        if not checkpoint:
            return None

        synced = len(checkpoint.get("synced_customers", []))
        total = checkpoint.get("total_customers", 0)

        return {
            "synced_customers": synced,
            "total_customers": total,
            "progress_percent": int(synced / total * 100) if total > 0 else 0,
            "last_updated": checkpoint.get("last_updated"),
        }

    async def _restore_ui_state(self) -> bool:
        """
        P1 改进: 根据 checkpoint 中的 current_state 恢复界面位置。

        当断连恢复时，如果之前在聊天界面内，自动导航回该客户的对话。

        Returns:
            True if UI was restored to a specific chat, False otherwise
        """
        if not hasattr(self, "_resume_state") or not self._resume_state:
            return False

        state = self._resume_state
        phase = state.get("phase", "list")

        if phase == "in_chat" or phase == "sending":
            customer = state.get("current_customer")
            channel = state.get("current_customer_channel")

            if customer:
                self.logger.info(f"🔄 恢复界面: 正在返回 {customer} 的对话...")

                # 先确保在主界面
                await self.wecom.go_back()
                await self.wecom.adb.wait(0.5)
                await self.wecom.switch_to_private_chats()
                await self.wecom.adb.wait(0.5)

                # 尝试点击进入该客户的对话
                success = await self.wecom.click_user_in_list(customer, channel)
                if success:
                    self.logger.info(f"✅ 已恢复到 {customer} 的对话界面")
                    return True
                else:
                    self.logger.warning(f"⚠️ 无法找到 {customer}，从列表界面继续")

        return False

    def set_voice_handler_callback(
        self,
        callback: Callable[[ConversationMessage], tuple[VoiceHandlerAction, str | None]],
    ) -> None:
        """
        Set callback for handling voice messages without captions.

        The callback receives a ConversationMessage and should return:
        - (VoiceHandlerAction.CAPTION, None) - Wait for user to reveal caption
        - (VoiceHandlerAction.INPUT, "transcribed text") - Use provided text
        - (VoiceHandlerAction.PLACEHOLDER, None) - Use "[Voice Message]"
        - (VoiceHandlerAction.SKIP, None) - Skip this message

        Args:
            callback: Function to handle voice messages
        """
        self._voice_handler_callback = callback

    def set_customer_voice_callback(
        self,
        callback: Callable[[str, str | None, str], None],
    ) -> None:
        """
        Set callback for when a customer sends a voice message.

        This callback is triggered when a voice message from a customer
        (not kefu) is detected during sync. This can be used to send
        notifications and add the user to blacklist.

        Args:
            callback: Function that takes (customer_name, channel, serial)
                      and handles the voice message notification
        """
        self._on_customer_voice_callback = callback

    # =========================================================================
    # Main Sync Workflow
    # =========================================================================

    async def _extract_unread_users(
        self,
        max_scrolls: int = 20,
        scroll_delay: float = 1.0,
        stable_threshold: int = 2,
    ) -> list[UnreadUserInfo]:
        """
        Extract all users with their unread message counts by scrolling through the list.

        Args:
            max_scrolls: Maximum scroll iterations
            scroll_delay: Delay between scrolls
            stable_threshold: Stop after N scrolls with no new entries

        Returns:
            List of UnreadUserInfo objects
        """
        self.logger.info("Extracting users with unread message counts...")

        all_entries: dict[str, UnreadUserInfo] = {}
        stable_count = 0

        for scroll_num in range(max_scrolls + 1):
            self.logger.debug(f"Scroll iteration {scroll_num}/{max_scrolls}")

            # Get current UI tree
            tree = await self.wecom.adb.get_ui_tree()
            if not tree:
                self.logger.warning("Failed to get UI tree, retrying...")
                await asyncio.sleep(1.0)
                continue

            # Extract users from current view
            current_entries = UnreadUserExtractor.extract_from_tree(tree)

            new_count = 0
            for entry in current_entries:
                key = entry.unique_key()
                if key not in all_entries:
                    all_entries[key] = entry
                    new_count += 1
                    # 高优先级: 有未读消息(红点) 或 是新好友(欢迎语)
                    if entry.is_priority():
                        priority_reason = []
                        if entry.unread_count > 0:
                            priority_reason.append(f"{entry.unread_count} unread")
                        if entry.is_new_friend:
                            priority_reason.append("new friend")
                        self.logger.info(f"  🔴 Found priority user: '{entry.name}' - {', '.join(priority_reason)}")
                else:
                    # Update unread count if higher
                    existing = all_entries[key]
                    if entry.unread_count > existing.unread_count:
                        existing.unread_count = entry.unread_count

            # 统计高优先级用户 (包括未读消息和新好友)
            priority_count_so_far = sum(1 for e in all_entries.values() if e.is_priority())
            self.logger.debug(
                f"Found {len(current_entries)} entries in view, "
                f"{new_count} new, {len(all_entries)} total, "
                f"{priority_count_so_far} priority (unread/new friends)"
            )

            if new_count == 0:
                stable_count += 1
                if stable_count >= stable_threshold:
                    self.logger.info("Reached stability threshold, all users collected")
                    break
            else:
                stable_count = 0

            if scroll_num < max_scrolls:
                await self.wecom.adb.scroll_down()
                await asyncio.sleep(scroll_delay)

        result = list(all_entries.values())
        # 包括未读消息和新好友在内的高优先级用户
        priority_users = [e for e in result if e.is_priority()]
        new_friend_count = sum(1 for e in result if e.is_new_friend)

        self.logger.info(
            f"Extracted {len(result)} users, {len(priority_users)} priority "
            f"({sum(1 for e in result if e.unread_count > 0)} unread, {new_friend_count} new friends)"
        )

        return result

    def _match_user_to_unread_info(
        self,
        user: UserDetail,
        unread_infos: list[UnreadUserInfo],
    ) -> UnreadUserInfo | None:
        """Match a UserDetail to its corresponding UnreadUserInfo."""
        for info in unread_infos:
            if info.name == user.name:
                # Check channel match if available
                if info.channel and user.channel:
                    if info.channel == user.channel:
                        return info
                else:
                    return info
        return None

    async def _detect_first_page_unread(self) -> list[UnreadUserInfo]:
        """
        Detect unread users on the first page only (no scrolling).

        This is used for dynamic unread detection after processing each customer.
        When exiting a conversation, new messages may have arrived from other users,
        and they typically appear at the top of the list with red badges.

        Returns:
            List of UnreadUserInfo for users with unread messages on first page
        """
        self.logger.debug("Checking first page for new unread messages...")

        # Get current UI tree (should already be on private chat list)
        tree = await self.wecom.adb.get_ui_tree()
        if not tree:
            self.logger.warning("Could not get UI tree for first page unread detection")
            return []

        # Extract unread info from current screen
        current_users = UnreadUserExtractor.extract_from_tree(tree)

        # 使用 is_priority() 过滤: 包括未读消息和新好友
        priority_users = [u for u in current_users if u.is_priority()]

        if priority_users:
            unread_count = sum(1 for u in priority_users if u.unread_count > 0)
            new_friend_count = sum(1 for u in priority_users if u.is_new_friend)
            self.logger.info(
                f"🔴 Found {len(priority_users)} priority users on first page "
                f"({unread_count} unread, {new_friend_count} new friends)"
            )
            for u in priority_users:
                reason = []
                if u.unread_count > 0:
                    reason.append(f"{u.unread_count} unread")
                if u.is_new_friend:
                    reason.append("new friend")
                self.logger.debug(f"  - {u.name}: {', '.join(reason)}")

        return priority_users

    async def run_initial_sync(
        self,
        send_test_messages: bool = True,
        response_wait_seconds: float = 5.0,
        prioritize_unread: bool = True,
        unread_only: bool = False,
        resume: bool = False,
        interactive_wait_timeout: float = 40.0,
        max_interaction_rounds: int = 10,
    ) -> dict:
        """
        Run the full initial sync workflow with interactive waiting and dynamic unread detection.

        New features (v2):
        - Interactive waiting: After sending a message, wait up to interactive_wait_timeout
          for new messages. If customer responds, reply and continue waiting.
        - Dynamic unread detection: After exiting each conversation, check first page
          for new unread users and prioritize them.

        Args:
            send_test_messages: If True, send test messages after syncing each user
            response_wait_seconds: (Legacy) Time to wait for responses after test message
            prioritize_unread: If True, sync users with unread messages first
            unread_only: If True, only sync users with unread messages (implies prioritize_unread)
            resume: If True, resume from last checkpoint (skip already synced customers)
            interactive_wait_timeout: Time to wait for new messages before exiting (default 40s)
            max_interaction_rounds: Max conversation rounds to prevent infinite loop (default 10)

        Returns:
            Statistics about the sync operation
        """
        if unread_only:
            prioritize_unread = True

        # Check for checkpoint if resuming
        synced_customers_set: set = set()
        checkpoint_stats: dict[str, Any] | None = None

        if resume:
            checkpoint = self._get_checkpoint()
            if checkpoint:
                synced_customers_set = set(checkpoint.get("synced_customers", []))
                checkpoint_stats = checkpoint.get("stats", {})
                # P1 改进: 读取当前界面状态
                self._resume_state = checkpoint.get("current_state", {"phase": "list"})
                self.logger.info(f"📌 Resuming sync: {len(synced_customers_set)} customers already synced")
                self.logger.info(
                    f"📌 Resume state: phase={self._resume_state.get('phase')}, customer={self._resume_state.get('current_customer', 'N/A')}"
                )
            else:
                self.logger.info("No checkpoint found, starting fresh sync")
                self._resume_state = None
        else:
            self._resume_state = None

        # Try to load customer list from checkpoint if resuming
        all_customers_from_checkpoint = []
        if resume and checkpoint:
            raw_customers = checkpoint.get("all_customers", [])
            if raw_customers:
                try:
                    all_customers_from_checkpoint = [UserDetail.from_dict(c) for c in raw_customers]
                    self.logger.info(
                        f"📌 Resuming with {len(all_customers_from_checkpoint)} customers from checkpoint list"
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to parse customers from checkpoint: {e}")

        # Initialize stats (restore from checkpoint if resuming)
        if checkpoint_stats:
            stats = {
                "start_time": checkpoint_stats.get("start_time", datetime.now().isoformat()),
                "customers_synced": checkpoint_stats.get("customers_synced", 0),
                "messages_added": checkpoint_stats.get("messages_added", 0),
                "messages_skipped": checkpoint_stats.get("messages_skipped", 0),
                "images_saved": checkpoint_stats.get("images_saved", 0),
                "videos_saved": checkpoint_stats.get("videos_saved", 0),
                "voice_messages": checkpoint_stats.get("voice_messages", 0),
                "unread_users_found": checkpoint_stats.get("unread_users_found", 0),
                "unread_users_synced": checkpoint_stats.get("unread_users_synced", 0),
                "errors": checkpoint_stats.get("errors", []),
                "resumed": True,
            }
        else:
            stats = {
                "start_time": datetime.now().isoformat(),
                "customers_synced": 0,
                "messages_added": 0,
                "messages_skipped": 0,
                "images_saved": 0,
                "videos_saved": 0,
                "voice_messages": 0,
                "unread_users_found": 0,
                "unread_users_synced": 0,
                "errors": [],
            }

        # Track synced customers for checkpoint
        synced_customers_list = list(synced_customers_set)

        with log_operation(self.logger, "initial_sync"):
            blacklisted_count = 0
            try:
                # Step 1: Ensure WeCom is open
                self.logger.info("Step 1: Ensuring WeCom is open...")
                await self._ensure_wecom_open()
                await self._human_delay("read")

                # Step 2: Get kefu information
                self.logger.info("Step 2: Getting kefu information...")
                kefu_info = await self.wecom.get_kefu_name()
                if not kefu_info:
                    raise RuntimeError("Could not get kefu information")

                self.logger.info(f"Current kefu: {kefu_info.name}")
                await self._human_delay("read")

                # Step 3: Setup device and kefu in database
                self.logger.info("Step 3: Setting up database records...")
                await self._setup_device_and_kefu(kefu_info)

                # Step 4: Navigate to private chats
                self.logger.info("Step 4: Navigating to private chats...")
                await self.wecom.switch_to_private_chats()
                await self._human_delay("scroll")
                prioritize_unread = True
                # Step 5: Extract users with unread info if prioritizing
                unread_infos: list[UnreadUserInfo] = []
                if prioritize_unread:
                    self.logger.info("Step 5: Extracting users with unread message counts...")
                    # First scroll to top
                    await self.wecom.adb.scroll_to_top()
                    await self._human_delay("scroll")

                    unread_infos = await self._extract_unread_users()
                    # 统计高优先级用户 (未读 + 新好友)
                    priority_users_count = sum(1 for u in unread_infos if u.is_priority())
                    unread_only_count = sum(1 for u in unread_infos if u.unread_count > 0)
                    new_friend_only_count = sum(1 for u in unread_infos if u.is_new_friend)
                    stats["unread_users_found"] = priority_users_count

                    self.logger.info(
                        f"Found {priority_users_count} priority users "
                        f"({unread_only_count} unread, {new_friend_only_count} new friends)"
                    )

                    # Scroll back to top for extraction
                    await self.wecom.adb.scroll_to_top()
                    await self._human_delay("scroll")

                # Step 6: Get customer list
                customers = []
                if resume and all_customers_from_checkpoint:
                    self.logger.info(
                        f"Skipping extraction, using {len(all_customers_from_checkpoint)} customers loaded from checkpoint"
                    )
                    customers = all_customers_from_checkpoint
                else:
                    step_num = 6 if prioritize_unread else 5
                    self.logger.info(f"Step {step_num}: Extracting customer list...")
                    extraction_result = await self.wecom.extract_private_chat_users()
                    customers = extraction_result.users

                    # IMPORTANT: Save the full list immediately so we have it for resume
                    # We pass empty stats equivalent for now if this is a fresh start
                    self._save_checkpoint(
                        synced_customers_list, stats, len(customers), {"phase": "list"}, all_customers=customers
                    )

                self.logger.info(f"Found {len(customers)} customers")
                await self._human_delay("read")

                # Step 7: Sort/filter customers based on unread priority
                if prioritize_unread and unread_infos:
                    # Create a map of priority info (unread count + new friend status)
                    priority_map: dict[str, tuple] = {}
                    for info in unread_infos:
                        # 存储 (unread_count, is_new_friend) 元组
                        priority_map[info.name] = (info.unread_count, info.is_new_friend)

                    # Separate into priority and non-priority users
                    priority_customers = []
                    regular_customers = []

                    for user in customers:
                        priority_info = priority_map.get(user.name, (0, False))
                        unread_count, is_new_friend = priority_info
                        # 高优先级: 有未读消息 或 是新好友
                        if unread_count > 0 or is_new_friend:
                            priority_customers.append((user, unread_count, is_new_friend))
                        else:
                            regular_customers.append(user)

                    # 排序: 未读数多的优先, 其次是新好友
                    priority_customers.sort(key=lambda x: (x[1], x[2]), reverse=True)

                    if unread_only:
                        # Only sync priority users (unread or new friends)
                        customers = [u for u, _, _ in priority_customers]
                        self.logger.info(f"Priority-only mode: will sync {len(customers)} priority users")
                    else:
                        # Prioritize priority users, then process others
                        customers = [u for u, _, _ in priority_customers] + regular_customers
                        self.logger.info(
                            f"Priority mode: {len(priority_customers)} priority users first, "
                            f"then {len(regular_customers)} regular users"
                        )

                # Step 8: Sync each customer's conversation (with dynamic unread detection)
                step_num = 8 if prioritize_unread else 6
                total_customers = len(customers)
                skipped_count = 0

                if resume and synced_customers_set:
                    self.logger.info(f"Step {step_num}: Syncing customer conversations (resuming from checkpoint)...")
                    self.logger.info(f"📌 Will skip {len(synced_customers_set)} already synced customers")
                else:
                    self.logger.info(f"Step {step_num}: Syncing customer conversations...")

                # Use a queue for dynamic unread priority insertion
                pending_customers = list(customers)  # Copy to mutable list
                processed_customer_keys = set(synced_customers_set)  # Track all processed
                idx = 0  # Manual counter for logging

                while pending_customers:
                    user = pending_customers.pop(0)

                    # Create a unique key for the customer (name + channel)
                    customer_key = f"{user.name}|{user.channel or ''}"

                    # Skip if already processed in this session
                    if customer_key in processed_customer_keys:
                        self.logger.debug(f"⏭️ Skipping {user.name} (already processed)")
                        continue

                    # Skip if user is blacklisted (requested human agent)
                    if self.is_user_blacklisted(user.name, user.channel):
                        blacklisted_count += 1
                        processed_customer_keys.add(customer_key)
                        self.logger.info(f"⛔ Skipping customer: {user.name} (blacklisted - requested human agent)")
                        continue

                    idx += 1

                    # Check if this user is a priority user (unread or new friend)
                    is_priority_user = False
                    priority_reason = []
                    if prioritize_unread and unread_infos:
                        matched_info = self._match_user_to_unread_info(user, unread_infos)
                        if matched_info and matched_info.is_priority():
                            is_priority_user = True
                            if matched_info.unread_count > 0:
                                priority_reason.append(f"{matched_info.unread_count} unread")
                            if matched_info.is_new_friend:
                                priority_reason.append("new friend")
                            self.logger.info(
                                f"Processing customer {idx}/{total_customers}: "
                                f"{user.name} 🔴 ({', '.join(priority_reason)})"
                            )
                        else:
                            self.logger.info(f"Processing customer {idx}/{total_customers}: {user.name}")
                    else:
                        self.logger.info(f"Processing customer {idx}/{total_customers}: {user.name}")

                    try:
                        customer_stats = await self._sync_customer_conversation(
                            user,
                            send_test_messages=send_test_messages,
                            response_wait_seconds=response_wait_seconds,
                            interactive_wait_timeout=interactive_wait_timeout,
                            max_interaction_rounds=max_interaction_rounds,
                        )

                        stats["customers_synced"] += 1
                        stats["messages_added"] += customer_stats.get("messages_added", 0)
                        stats["messages_skipped"] += customer_stats.get("messages_skipped", 0)
                        stats["images_saved"] += customer_stats.get("images_saved", 0)
                        stats["videos_saved"] += customer_stats.get("videos_saved", 0)
                        stats["voice_messages"] += customer_stats.get("voice_messages", 0)

                        # Track priority users synced
                        if is_priority_user:
                            stats["unread_users_synced"] += 1

                        # Mark as processed
                        processed_customer_keys.add(customer_key)
                        synced_customers_list.append(customer_key)
                        self._save_checkpoint(synced_customers_list, stats, total_customers, all_customers=customers)

                        # =========================================================
                        # Dynamic unread detection: Check first page for new unread
                        # =========================================================
                        new_unread_users = await self._detect_first_page_unread()

                        if new_unread_users:
                            # Filter out already processed users
                            truly_new = []
                            for unread_info in new_unread_users:
                                unread_key = f"{unread_info.name}|{unread_info.channel or ''}"
                                if unread_key not in processed_customer_keys:
                                    # Create UserDetail from UnreadUserInfo
                                    new_user = UserDetail(
                                        name=unread_info.name,
                                        channel=unread_info.channel,
                                    )
                                    truly_new.append(new_user)

                            if truly_new:
                                self.logger.info(
                                    f"🔴 Found {len(truly_new)} NEW unread user(s), inserting at front of queue"
                                )
                                for u in truly_new:
                                    self.logger.info(f"  → {u.name}")

                                # Insert at front of pending queue (priority processing)
                                pending_customers = truly_new + pending_customers

                                # Update unread_infos for accurate logging
                                for unread_info in new_unread_users:
                                    if unread_info not in unread_infos:
                                        unread_infos.append(unread_info)

                    except Exception as e:
                        error_str = str(e)
                        is_device_not_found = "not found" in error_str.lower() and "device" in error_str.lower()

                        error_msg = f"Error syncing {user.name}: {error_str}"
                        self.logger.error(error_msg)
                        stats["errors"].append(error_msg)

                        # Mark as processed even on error to avoid retry loop
                        processed_customer_keys.add(customer_key)

                        if is_device_not_found:
                            self.logger.critical(
                                "🛑 FATAL ERROR: Device not found. Stopping sync immediately to preserve state."
                            )
                            break

                        # Try to recover by going back to private chats
                        try:
                            self.logger.info("Attempting to recover - navigating back to private chats...")
                            await self._recover_to_private_chats()
                        except Exception as recover_error:
                            self.logger.error(f"Recovery failed: {recover_error}")
                            # If recovery also fails with device not found, we should probably abort too
                            if "not found" in str(recover_error).lower() and "device" in str(recover_error).lower():
                                self.logger.critical("🛑 FATAL ERROR during recovery: Device not found. Stopping sync.")
                                break

                    # Human delay between customers
                    if pending_customers:
                        await self._human_delay("user_switch")

            except Exception as e:
                self.logger.error(f"Initial sync failed: {e}")
                stats["errors"].append(str(e))

            stats["end_time"] = datetime.now().isoformat()

            # Clear checkpoint on successful completion
            if not stats["errors"]:
                self._clear_checkpoint()
                self.logger.info("✅ Sync completed successfully, checkpoint cleared")
            else:
                self.logger.warning(
                    f"⚠️ Sync completed with {len(stats['errors'])} errors, checkpoint preserved for potential retry"
                )

            # Log summary
            self.logger.info("=" * 60)
            self.logger.info("SYNC COMPLETE")
            self.logger.info("=" * 60)
            self.logger.info(f"Customers synced: {stats['customers_synced']}")
            self.logger.info(f"Messages added: {stats['messages_added']}")
            self.logger.info(f"Messages skipped (duplicates): {stats['messages_skipped']}")
            self.logger.info(f"Images saved: {stats['images_saved']}")
            self.logger.info(f"Videos saved: {stats['videos_saved']}")
            self.logger.info(f"Voice messages: {stats['voice_messages']}")
            if prioritize_unread:
                self.logger.info(f"Unread users found: {stats['unread_users_found']}")
                self.logger.info(f"Unread users synced: {stats['unread_users_synced']}")
            if resume and skipped_count > 0:
                self.logger.info(f"Customers skipped (already synced): {skipped_count}")
            if blacklisted_count > 0:
                self.logger.info(f"Customers skipped (blacklisted): {blacklisted_count}")
            if stats["errors"]:
                self.logger.warning(f"Errors: {len(stats['errors'])}")

            return stats

    # =========================================================================
    # Setup and Navigation
    # =========================================================================

    async def _ensure_wecom_open(self) -> None:
        """Launch WeCom if not already open."""
        await self.wecom.launch_wecom(wait_for_ready=True)

    async def _ensure_keyboard_mode(self) -> bool:
        """
        Ensure the chat input is in keyboard mode (not voice mode).

        If "hold to talk" is detected, clicks the toggle button to switch to keyboard mode.

        Returns:
            True if successfully switched or already in keyboard mode, False otherwise.
        """
        self.logger.debug("Checking if input is in keyboard mode...")

        # Get current UI tree
        tree = await self.wecom.adb.get_ui_tree()
        if not tree:
            self.logger.warning("Could not get UI tree for keyboard mode check")
            return True  # Assume keyboard mode if we can't check

        # Check if voice mode is active
        if KeyboardModeHelper.is_voice_mode_active(tree):
            self.logger.info("🔊 Voice mode detected, switching to keyboard mode...")

            # Find and click the toggle button
            toggle_pos = KeyboardModeHelper.get_toggle_button_position(tree)

            if toggle_pos:
                x, y = toggle_pos
                self.logger.debug(f"Clicking toggle button at ({x}, {y})")
                await self.wecom.adb.tap_coordinates(x, y)
                await asyncio.sleep(0.5)

                # Verify the switch
                tree = await self.wecom.adb.get_ui_tree()
                if tree and not KeyboardModeHelper.is_voice_mode_active(tree):
                    self.logger.info("✓ Switched to keyboard mode")
                    return True
                else:
                    self.logger.warning("Voice mode still active after toggle click")
                    return False
            else:
                self.logger.warning("Could not find toggle button")
                return False
        else:
            self.logger.debug("Already in keyboard mode")
            return True

    async def _recover_to_private_chats(self) -> None:
        """
        Recover navigation by going back to private chats.

        This is called after an error to ensure we're in the right view
        for continuing with the next customer.
        """
        # Press back a few times to ensure we're out of any conversation
        for _ in range(3):
            try:
                await self.wecom.go_back()
                await asyncio.sleep(0.5)
            except Exception:
                pass

        # Wait for UI to stabilize
        await self.wecom.adb.wait(1.0)

        # Try to switch to private chats (this will handle the navigation)
        try:
            await self.wecom.switch_to_private_chats()
        except Exception:
            # If that fails, at least scroll to top
            await self.wecom.adb.scroll_to_top()

    async def _setup_device_and_kefu(self, kefu_info) -> None:
        """Setup device and kefu records in database."""
        # Get device info
        device_serial = self.config.device_serial or "unknown"

        # Create or get device
        self._current_device = self.repository.get_or_create_device(
            serial=device_serial,
        )

        # Create or get kefu
        self._current_kefu = self.repository.get_or_create_kefu(
            name=kefu_info.name,
            device_id=self._current_device.id,
            department=kefu_info.department,
            verification_status=kefu_info.verification_status,
        )

        self.logger.info(f"Device ID: {self._current_device.id}, Kefu ID: {self._current_kefu.id}")

    # =========================================================================
    # Avatar Caching
    # =========================================================================

    def _is_avatar_cached(self, name: str) -> bool:
        """
        Check if an avatar is already cached for the given user name.

        Looks for files matching pattern: avatar_*_{name}.png

        Args:
            name: User name to check

        Returns:
            True if avatar exists, False otherwise
        """
        # Normalize name for file matching
        safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)

        # Check for any existing avatar file with this name
        pattern = f"avatar_*_{safe_name}.png"
        matches = list(self.avatars_dir.glob(pattern))

        if matches:
            self.logger.debug(f"Avatar already cached for {name}: {matches[0]}")
            return True

        return False

    async def _try_capture_avatar_once(self, user_name: str) -> str | None:
        """
        Try to capture avatar from current screen once.

        This is a single attempt - the caller should retry during scrolling.

        Args:
            user_name: Name of the user (for filename)

        Returns:
            Path to saved avatar file, or None if capture failed
        """
        try:
            from io import BytesIO

            from PIL import Image
        except ImportError:
            self.logger.warning("PIL not installed - skipping avatar capture")
            return None

        # Get current UI tree to find avatar bounds
        tree = await self.wecom.adb.get_ui_tree()
        if not tree:
            self.logger.debug("Could not get UI tree for avatar capture")
            return None

        # Find avatar next to left-side messages
        avatar_bounds = self._find_avatar_in_header(tree)
        if not avatar_bounds:
            self.logger.debug(f"No avatar found on current screen for {user_name}")
            return None

        # Take screenshot
        try:
            _, image_bytes = await self.wecom.adb.take_screenshot()
            full_image = Image.open(BytesIO(image_bytes))
        except Exception as e:
            self.logger.error(f"Screenshot failed for avatar capture: {e}")
            return None

        # Parse avatar bounds
        x1, y1, x2, y2 = avatar_bounds
        img_width, img_height = full_image.size

        # Validate bounds
        if x1 < 0 or y1 < 0 or x2 > img_width or y2 > img_height:
            self.logger.debug(f"Avatar bounds out of image range: [{x1},{y1}][{x2},{y2}]")
            return None

        width, height = x2 - x1, y2 - y1
        if width < 30 or height < 30 or width > 200 or height > 200:
            self.logger.debug(f"Invalid avatar size: {width}x{height}")
            return None

        # Crop avatar
        try:
            avatar_crop = full_image.crop((x1, y1, x2, y2))

            # Generate filename
            safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in user_name)

            # Find next available index
            existing = list(self.avatars_dir.glob("avatar_*.png"))
            next_idx = len(existing) + 1

            filename = f"avatar_{next_idx:02d}_{safe_name}.png"
            avatar_path = self.avatars_dir / filename

            # Save avatar
            avatar_crop.save(avatar_path)
            self.logger.info(f"✓ Captured avatar: {filename}")

            return str(avatar_path)

        except Exception as e:
            self.logger.error(f"Failed to save avatar for {user_name}: {e}")
            return None

    async def _capture_avatar_with_scroll(self, user_name: str, max_scroll_attempts: int = 10) -> str | None:
        """
        Capture avatar from conversation, scrolling up if needed.

        The avatar appears next to messages from the other party (on the left side).
        If the current screen only shows our own messages (right side), we need to
        scroll up to find messages from the other party.

        Args:
            user_name: Name of the user (for filename)
            max_scroll_attempts: Maximum number of scroll attempts before giving up

        Returns:
            Path to saved avatar file, or None if not found after scrolling to top
        """
        self.logger.debug(f"Attempting to capture avatar for {user_name}")

        # First try on current screen
        avatar_path = await self._try_capture_avatar_once(user_name)
        if avatar_path:
            return avatar_path

        # Keep track of previous screen content to detect when we've reached the top
        previous_tree_hash = None
        consecutive_same_screen = 0

        for attempt in range(max_scroll_attempts):
            self.logger.debug(f"Avatar capture: scroll attempt {attempt + 1}/{max_scroll_attempts}")

            # Scroll up to see more messages
            await self.wecom.adb.scroll_up()
            await self._human_delay("scroll")

            # Try to capture avatar
            avatar_path = await self._try_capture_avatar_once(user_name)
            if avatar_path:
                return avatar_path

            # Check if we've reached the top of the conversation
            # (screen content stops changing)
            tree = await self.wecom.adb.get_ui_tree()
            if tree:
                # Create a simple hash of the tree structure
                tree_str = str(tree)[:1000]  # Use first 1000 chars as hash
                current_hash = hash(tree_str)

                if current_hash == previous_tree_hash:
                    consecutive_same_screen += 1
                    if consecutive_same_screen >= 2:
                        self.logger.debug("Reached top of conversation - screen stopped changing")
                        break
                else:
                    consecutive_same_screen = 0
                    previous_tree_hash = current_hash

        self.logger.debug(f"Could not capture avatar for {user_name} after {max_scroll_attempts} scroll attempts")
        return None

    def _use_default_avatar(self, user_name: str) -> str | None:
        """
        Use default avatar for a user when avatar cannot be parsed.

        Copies avatar_default.png to create a user-specific avatar file.

        Args:
            user_name: Name of the user

        Returns:
            Path to created avatar file, or None if default not found
        """
        import shutil

        default_avatar = self.avatars_dir / "avatar_default.png"
        if not default_avatar.exists():
            self.logger.warning(f"Default avatar not found: {default_avatar}")
            return None

        # Generate filename
        safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in user_name)

        # Find next available index
        existing = list(self.avatars_dir.glob("avatar_*.png"))
        next_idx = len(existing) + 1

        filename = f"avatar_{next_idx:02d}_{safe_name}.png"
        avatar_path = self.avatars_dir / filename

        try:
            shutil.copy2(default_avatar, avatar_path)
            self.logger.info(f"  Using default avatar for {user_name}: {filename}")
            return str(avatar_path)
        except Exception as e:
            self.logger.error(f"Failed to copy default avatar: {e}")
            return None

    def _find_avatar_in_header(self, tree: Any) -> tuple[int, int, int, int] | None:
        """
        Find avatar bounds by locating messages from the other party (left side).

        In a chat conversation:
        - Messages from the other party appear on the LEFT side with avatar
        - Messages from self appear on the RIGHT side without avatar

        We look for left-side message bubbles and find the avatar beside them.

        IMPORTANT: We must exclude the bottom toolbar area which contains icons like:
        - "Company business card" (公司名片)
        - "Initiation of Receipt" (发起收款)
        These icons are also on the left side but are NOT avatars.

        Args:
            tree: UI accessibility tree

        Returns:
            Tuple of (x1, y1, x2, y2) bounds, or None if not found
        """
        avatar_class_hints = ("imageview", "image", "avatar", "icon", "photo")
        avatar_resource_id_hints = ("avatar", "photo", "icon", "head", "portrait", "profile", "im4")
        message_class_hints = ("textview", "text", "message", "bubble", "chat")
        # Text content that indicates bottom toolbar buttons (should be excluded)
        bottom_toolbar_hints = (
            "Company",
            "business",
            "card",
            "receipt",
            "收款",
            "名片",
            "发起",
            "transfer",
            "转账",
            "红包",
            "envelope",
            "location",
            "位置",
            "file",
            "文件",
            "photo",
            "相册",
            "camera",
            "拍摄",
            "voice",
            "语音",
        )

        roots = []
        if isinstance(tree, dict):
            roots = [tree]
        elif isinstance(tree, list):
            roots = [node for node in tree if isinstance(node, dict)]

        all_nodes = []
        for root in roots:
            all_nodes.extend(self._collect_all_nodes_flat(root))

        # Step 0: Find bottom toolbar Y position by looking for toolbar indicators
        # The bottom toolbar typically contains buttons like "Company business card"
        bottom_toolbar_y = 2000  # Default high value

        for node in all_nodes:
            text = (node.get("text") or "").lower().strip()
            content_desc = (node.get("contentDescription") or node.get("content-desc") or "").lower()

            # Check if this node is part of bottom toolbar
            is_toolbar_element = any(hint in text or hint in content_desc for hint in bottom_toolbar_hints)

            if is_toolbar_element:
                bounds_str = self._get_node_bounds_str(node)
                if bounds_str:
                    match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
                    if match:
                        _, y1, _, _ = map(int, match.groups())
                        # Set bottom toolbar boundary (above toolbar buttons)
                        if y1 < bottom_toolbar_y:
                            bottom_toolbar_y = y1 - 50  # Add margin

        self.logger.debug(f"Bottom toolbar boundary detected at Y={bottom_toolbar_y}")

        # Step 1: Find left-side message bubbles (from other party)
        # These are text elements on the left side of screen with message content
        left_messages = []
        screen_center_x = 540  # Approximate center for 1080p screen

        for node in all_nodes:
            bounds_str = self._get_node_bounds_str(node)
            if not bounds_str:
                continue

            match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
            if not match:
                continue

            x1, y1, x2, y2 = map(int, match.groups())

            # Message should be on the left side (center of element < screen center)
            center_x = (x1 + x2) // 2
            if center_x > screen_center_x:
                continue

            # Skip elements too high (header area) or too low (input area / bottom toolbar)
            # CRITICAL: Use bottom_toolbar_y to exclude toolbar icons
            if y1 < 200 or y2 > bottom_toolbar_y:
                continue

            # Check if it looks like a message
            class_name = (node.get("className") or "").lower()
            text = (node.get("text") or "").strip()

            is_message_class = any(hint in class_name for hint in message_class_hints)
            has_content = len(text) > 0

            # Message bubbles typically have some width
            width = x2 - x1
            if width < 50 or width > 800:
                continue

            if is_message_class and has_content:
                left_messages.append((x1, y1, x2, y2))

        if not left_messages:
            self.logger.debug("No left-side messages found")
            return None

        # Step 2: Find avatar adjacent to one of the left-side messages
        # Avatar is typically to the LEFT of the message bubble, at similar Y position
        best_avatar = None
        best_score = 0

        for node in all_nodes:
            bounds_str = self._get_node_bounds_str(node)
            if not bounds_str:
                continue

            match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
            if not match:
                continue

            x1, y1, x2, y2 = map(int, match.groups())
            width = x2 - x1
            height = y2 - y1

            # Avatar is typically square, 40-120px
            if width < 30 or width > 150 or height < 30 or height > 150:
                continue

            aspect_ratio = width / height if height > 0 else 0
            if aspect_ratio < 0.7 or aspect_ratio > 1.3:
                continue

            # Avatar must be on the far left (margin area)
            if x1 > 120:
                continue

            # CRITICAL: Exclude top navigation bar area (contains back button)
            # The back button is typically at Y < 200 in the header area
            if y1 < 250:
                self.logger.debug(f"Skipping element at Y={y1} (in header/nav area, likely back button)")
                continue

            # CRITICAL: Exclude elements in the bottom toolbar area
            if y1 > bottom_toolbar_y:
                self.logger.debug(f"Skipping element at Y={y1} (below toolbar boundary {bottom_toolbar_y})")
                continue

            resource_id = (node.get("resourceId") or "").lower()
            class_name = (node.get("className") or "").lower()

            score = 0

            # Check for avatar hints in resource ID
            for hint in avatar_resource_id_hints:
                if hint in resource_id:
                    score += 30
                    break

            # Check for ImageView class
            for hint in avatar_class_hints:
                if hint in class_name:
                    score += 20
                    break

            # CRITICAL: Check if avatar is vertically aligned with any left-side message
            # This is the most important check - avatar MUST be next to a message
            avatar_center_y = (y1 + y2) // 2
            is_aligned_with_message = False
            for _msg_x1, msg_y1, _msg_x2, msg_y2 in left_messages:
                msg_center_y = (msg_y1 + msg_y2) // 2
                y_distance = abs(avatar_center_y - msg_center_y)

                # Avatar should be within ~80px vertically of message
                if y_distance < 80:
                    score += 50  # Strong score for close alignment
                    is_aligned_with_message = True
                    break
                elif y_distance < 150:
                    score += 25
                    is_aligned_with_message = True

            # Skip if not aligned with any message - this filters out
            # stray icons like back button, toolbar icons, etc.
            if not is_aligned_with_message:
                self.logger.debug(f"Skipping element at Y={y1} (not aligned with any message)")
                continue

            # Prefer avatars on the very left edge
            if x1 < 30:
                score += 15
            elif x1 < 60:
                score += 10

            # Prefer square avatars
            if 0.9 <= aspect_ratio <= 1.1:
                score += 5

            if score > best_score:
                best_score = score
                best_avatar = (x1, y1, x2, y2)

        # Require minimum score to be confident this is actually an avatar
        # Score breakdown:
        # - Resource ID hint: +30
        # - ImageView class: +20
        # - Close alignment with message: +50
        # - Left edge position: +10-15
        # - Square aspect ratio: +5
        # Minimum 40 means at least message alignment is required
        MIN_AVATAR_SCORE = 40

        if best_avatar and best_score >= MIN_AVATAR_SCORE:
            self.logger.debug(f"Found avatar at {best_avatar} with score {best_score}")
            return best_avatar
        else:
            if best_avatar:
                self.logger.debug(
                    f"Best candidate at {best_avatar} has score {best_score} < {MIN_AVATAR_SCORE}, rejected"
                )
            else:
                self.logger.debug("No avatar candidates found next to left-side messages")
            return None

    def _collect_all_nodes_flat(self, node: dict[str, Any]) -> list[dict[str, Any]]:
        """Flatten the tree into a list of all nodes."""
        results = [node]
        children = node.get("children") or []
        for child in children:
            if isinstance(child, dict):
                results.extend(self._collect_all_nodes_flat(child))
        return results

    def _get_node_bounds_str(self, node: dict[str, Any]) -> str | None:
        """Get bounds string from a node."""
        bounds_keys = ["bounds", "visibleBounds", "boundsInScreen", "boundsInParent", "rect"]
        for key in bounds_keys:
            bounds = node.get(key)
            if bounds:
                if isinstance(bounds, str) and "[" in bounds:
                    return bounds
                if isinstance(bounds, dict):
                    x1 = bounds.get("left", bounds.get("x", bounds.get("x1", 0)))
                    y1 = bounds.get("top", bounds.get("y", bounds.get("y1", 0)))
                    x2 = bounds.get("right", bounds.get("x2", x1 + bounds.get("width", 0)))
                    y2 = bounds.get("bottom", bounds.get("y2", y1 + bounds.get("height", 0)))
                    return f"[{x1},{y1}][{x2},{y2}]"
                if isinstance(bounds, (list, tuple)) and len(bounds) >= 4:
                    return f"[{bounds[0]},{bounds[1]}][{bounds[2]},{bounds[3]}]"
        return None

    # =========================================================================
    # Customer Conversation Sync
    # =========================================================================

    async def _sync_customer_conversation(
        self,
        user: UserDetail,
        send_test_messages: bool = True,
        response_wait_seconds: float = 5.0,
        interactive_wait_timeout: float = 40.0,
        max_interaction_rounds: int = 10,
    ) -> dict:
        """
        Sync all messages for a single customer with interactive waiting.

        New flow (v2):
        1. Enter conversation, extract history, store messages
        2. Send initial reply if last message is from customer
        3. Wait up to interactive_wait_timeout for new messages
        4. If new message arrives, process it and reply, continue waiting
        5. If timeout, exit conversation

        Args:
            user: UserDetail of the customer
            send_test_messages: Whether to send test messages
            response_wait_seconds: (Legacy) Time to wait for responses
            interactive_wait_timeout: Time to wait for new messages before exiting (default 40s)
            max_interaction_rounds: Max conversation rounds to prevent infinite loop (default 10)

        Returns:
            Statistics for this customer
        """
        stats = {
            "messages_added": 0,
            "messages_skipped": 0,
            "images_saved": 0,
            "videos_saved": 0,
            "voices_saved": 0,
            "voice_messages": 0,
            "interaction_rounds": 0,
            "exit_reason": None,
        }

        # Initialize timestamp context for this conversation
        self._init_timestamp_context()

        # Create or get customer record
        customer = self.repository.get_or_create_customer(
            name=user.name,
            kefu_id=self._current_kefu.id,
            channel=user.channel,
            last_message_preview=user.message_preview,
            last_message_date=user.last_message_date,
        )
        if getattr(user, "is_new_friend", False):
            self.repository.mark_customer_friend_added(customer.id)
            refreshed_customer = self.repository.get_customer_by_id(customer.id)
            if refreshed_customer is not None:
                customer = refreshed_customer

        # Click on user to open conversation
        success = await self.wecom.click_user_in_list(user.name, user.channel)
        if not success:
            self.logger.warning(f"Could not find user {user.name} in list")
            stats["exit_reason"] = "user_not_found"
            return stats

        await self._human_delay("tap")

        # Capture avatar from conversation if not already cached
        if not self._is_avatar_cached(user.name):
            avatar_path = await self._capture_avatar_with_scroll(user.name, max_scroll_attempts=10)
            if avatar_path:
                stats["avatar_captured"] = True
            else:
                self.logger.info("  Could not capture avatar after scrolling, using default")
                self._use_default_avatar(user.name)
        else:
            self.logger.debug(f"Avatar already cached for {user.name}")

        # Ensure keyboard mode is active (not voice mode)
        await self._ensure_keyboard_mode()

        # =====================================================================
        # Step 1: Extract and store all history messages
        # =====================================================================
        result = await self.wecom.extract_conversation_messages(
            download_images=True,
            download_videos=True,
            download_voices=True,
            output_dir=str(self.images_dir),
        )

        self.logger.info(f"Extracted {result.total_count} messages for {user.name}")

        # Process and store messages
        for msg in result.messages:
            try:
                processed = await self._process_and_store_message(msg, customer)
                if processed["added"]:
                    stats["messages_added"] += 1
                else:
                    stats["messages_skipped"] += 1

                if processed.get("image_saved"):
                    stats["images_saved"] += 1
                if processed.get("video_saved"):
                    stats["videos_saved"] += 1
                if processed.get("voice_saved"):
                    stats["voices_saved"] += 1
                if processed.get("is_voice"):
                    stats["voice_messages"] += 1

            except Exception as e:
                self.logger.error(f"Error processing message: {e}")

        # Track the last seen message for new message detection
        last_seen_msg_signature = self._get_message_signature(result.messages[-1]) if result.messages else None

        # =====================================================================
        # Step 2: Send initial reply if needed
        # =====================================================================
        if send_test_messages and result.messages:
            last_msg = result.messages[-1]
            # Only send if last message is from customer (not self/kefu)
            if not last_msg.is_self:
                self.logger.info(f"📤 Sending initial reply to {user.name}...")
                await self._send_reply_to_customer(last_msg, customer)
                stats["interaction_rounds"] += 1

        # =====================================================================
        # Step 3: Interactive waiting loop
        # =====================================================================
        if send_test_messages:
            self.logger.info(
                f"⏳ Entering interactive wait mode (timeout={interactive_wait_timeout}s, max_rounds={max_interaction_rounds})"
            )

            # After sending initial reply, update last_seen to include our own message
            # Get current state to update signature
            await asyncio.sleep(1.0)  # Brief wait for UI to update after sending
            tree = await self.wecom.adb.get_ui_tree()
            if tree:
                current_msgs = self.wecom.ui_parser.extract_conversation_messages(tree)
                if current_msgs:
                    last_seen_msg_signature = self._get_message_signature(current_msgs[-1])
                    self.logger.debug(f"Updated last_seen after initial reply: {last_seen_msg_signature[:50]}...")

            interaction_round = 0
            while interaction_round < max_interaction_rounds:
                # Wait for new CUSTOMER messages (ignores our own messages)
                has_new_customer_msg, new_messages = await self._wait_for_new_customer_messages(
                    last_seen_signature=last_seen_msg_signature,
                    timeout=interactive_wait_timeout,
                    poll_interval=3.0,
                )

                if not has_new_customer_msg:
                    # Timeout - no new customer messages
                    self.logger.info(
                        f"⏰ No new customer messages after {interactive_wait_timeout}s, exiting conversation"
                    )
                    stats["exit_reason"] = "timeout"
                    break

                # Process new messages
                customer_messages = [m for m in new_messages if not m.is_self]
                self.logger.info(f"📨 Received {len(customer_messages)} new message(s) from customer {user.name}")

                for msg in new_messages:
                    try:
                        processed = await self._process_and_store_message(msg, customer)
                        if processed["added"]:
                            stats["messages_added"] += 1
                        else:
                            stats["messages_skipped"] += 1

                        if processed.get("image_saved"):
                            stats["images_saved"] += 1
                        if processed.get("video_saved"):
                            stats["videos_saved"] += 1
                        if processed.get("voice_saved"):
                            stats["voices_saved"] += 1
                        if processed.get("is_voice"):
                            stats["voice_messages"] += 1
                    except Exception as e:
                        self.logger.error(f"Error processing new message: {e}")

                # Update last seen message signature
                if new_messages:
                    last_seen_msg_signature = self._get_message_signature(new_messages[-1])

                # Send reply to customer
                last_customer_msg = customer_messages[-1]
                self.logger.info(f"📤 Sending reply (round {interaction_round + 1})...")
                await self._send_reply_to_customer(last_customer_msg, customer)
                interaction_round += 1
                stats["interaction_rounds"] = interaction_round

                # After sending reply, update last_seen to include our reply
                await asyncio.sleep(1.0)  # Brief wait for UI to update
                tree = await self.wecom.adb.get_ui_tree()
                if tree:
                    current_msgs = self.wecom.ui_parser.extract_conversation_messages(tree)
                    if current_msgs:
                        last_seen_msg_signature = self._get_message_signature(current_msgs[-1])
                        self.logger.debug(f"Updated last_seen after reply: {last_seen_msg_signature[:50]}...")

                if interaction_round >= max_interaction_rounds:
                    self.logger.info(f"🔄 Max interaction rounds ({max_interaction_rounds}) reached")
                    stats["exit_reason"] = "max_rounds"
                    break
        else:
            stats["exit_reason"] = "no_test_messages"

        # =====================================================================
        # Step 4: Exit conversation
        # =====================================================================
        await self.wecom.go_back()
        await self._human_delay("tap")

        self.logger.info(
            f"✅ Finished conversation with {user.name}: {stats['messages_added']} new msgs, {stats['interaction_rounds']} rounds"
        )

        return stats

    def _get_message_signature(self, msg: ConversationMessage) -> str:
        """
        Generate a unique signature for a message to track new messages.

        Args:
            msg: The message to generate signature for

        Returns:
            A string signature for comparison
        """
        content_preview = (msg.content or "")[:50]
        return f"{msg.is_self}|{msg.message_type}|{content_preview}|{msg.timestamp or ''}"

    async def _wait_for_new_customer_messages(
        self,
        last_seen_signature: str | None,
        timeout: float = 40.0,
        poll_interval: float = 3.0,
    ) -> tuple[bool, list[ConversationMessage]]:
        """
        Wait for new messages FROM CUSTOMER in the current conversation.

        Only detects messages from customer (is_self=False), ignores kefu's own messages.
        Polls the UI tree at regular intervals.

        Args:
            last_seen_signature: Signature of the last seen message (any message)
            timeout: Maximum time to wait (seconds)
            poll_interval: Time between polls (seconds)

        Returns:
            Tuple of (has_new_customer_messages, list_of_all_new_messages)
        """
        import time

        start_time = time.time()

        self.logger.debug(
            f"Waiting for customer messages (timeout={timeout}s, last_sig={last_seen_signature[:30] if last_seen_signature else 'None'}...)"
        )

        while (time.time() - start_time) < timeout:
            elapsed = time.time() - start_time

            # Get current UI tree
            tree = await self.wecom.adb.get_ui_tree()
            if not tree:
                await asyncio.sleep(poll_interval)
                continue

            # Extract visible messages from UI
            current_messages = self.wecom.ui_parser.extract_conversation_messages(tree)

            if not current_messages:
                await asyncio.sleep(poll_interval)
                continue

            # Find all messages after last_seen_signature
            new_messages = []
            found_last_seen = False

            if last_seen_signature is None:
                # First time - check all messages
                new_messages = current_messages
                found_last_seen = True
            else:
                for msg in current_messages:
                    msg_sig = self._get_message_signature(msg)
                    if found_last_seen:
                        new_messages.append(msg)
                    elif msg_sig == last_seen_signature:
                        found_last_seen = True

                # If we didn't find the last_seen message, check the last message
                if not found_last_seen:
                    last_current_sig = self._get_message_signature(current_messages[-1])
                    if last_current_sig != last_seen_signature:
                        # Conversation changed, get last few messages
                        new_messages = current_messages[-3:]

            # KEY FIX: Only consider customer messages (is_self=False)
            customer_messages = [m for m in new_messages if not m.is_self]

            if customer_messages:
                self.logger.debug(f"Found {len(customer_messages)} new customer message(s) after {elapsed:.1f}s")
                return True, new_messages  # Return all new messages for processing

            # Log progress every 10 seconds
            if int(elapsed) % 10 == 0 and int(elapsed) > 0:
                self.logger.debug(f"Still waiting... {int(timeout - elapsed)}s remaining")

            # Wait before next poll
            await asyncio.sleep(poll_interval)

        # Timeout - no new customer messages
        self.logger.debug(f"Timeout after {timeout}s - no new customer messages")
        return False, []

    async def _send_reply_to_customer(
        self,
        customer_msg: ConversationMessage,
        customer: CustomerRecord,
    ) -> bool:
        """
        Send a reply to the customer's message.

        Args:
            customer_msg: The customer's message to reply to
            customer: Customer record

        Returns:
            True if reply was sent successfully
        """
        content = customer_msg.content or "[media]"
        # Generate reply message (will be replaced by AI if enabled via monkey-patch)
        reply_message = f"测试信息: [...{content[:30]}...]"

        # Send the message (returns actual message sent, may differ if AI reply used)
        success, actual_message = await self.wecom.send_message(reply_message)

        if success:
            # Store the ACTUAL message sent (could be AI reply, not mock message)
            now = self.timestamp_parser.get_now()
            reply_record = MessageRecord(
                customer_id=customer.id,
                content=actual_message,
                message_type=MessageType.TEXT,
                is_from_kefu=True,
                timestamp_raw=now.strftime("%H:%M"),
                timestamp_parsed=now,
            )
            self.repository.add_message_if_not_exists(reply_record)
            return True

        return False

    # =========================================================================
    # Message Processing
    # =========================================================================

    def _init_timestamp_context(self) -> None:
        """Initialize a new timestamp context for a conversation."""
        self.timestamp_parser.set_reference_time()  # Reset reference to current time
        self._timestamp_context = TimestampContext(self.timestamp_parser)

    def _get_parsed_timestamp(self, timestamp_raw: str | None) -> tuple[str | None, datetime | None]:
        """
        Get parsed timestamp for a message.

        Uses the timestamp context to propagate timestamps from separators
        to subsequent messages.

        Args:
            timestamp_raw: Raw timestamp string from the message

        Returns:
            Tuple of (raw_timestamp, parsed_datetime)
        """
        if self._timestamp_context is None:
            self._init_timestamp_context()

        return self._timestamp_context.get_timestamp_for_message(timestamp_raw)

    async def _process_and_store_message(
        self,
        msg: ConversationMessage,
        customer: CustomerRecord,
    ) -> dict:
        """
        Process a message and store it in the database.

        Handles special cases for voice and image messages.
        Parses relative timestamps to absolute datetime values.

        Args:
            msg: ConversationMessage to process
            customer: CustomerRecord for this conversation

        Returns:
            Dict with processing results
        """
        result = {"added": False, "image_saved": False, "is_voice": False}

        # Determine message type
        msg_type = MessageType.from_string(msg.message_type)
        content = msg.content
        extra_info = {}

        # Handle voice messages
        if msg_type == MessageType.VOICE:
            result["is_voice"] = True
            content, extra_info = await self._handle_voice_message(msg)

            # Trigger callback if customer (not kefu) sent a voice message
            if not msg.is_self and self._on_customer_voice_callback:
                result["customer_voice_detected"] = True
                try:
                    self._on_customer_voice_callback(
                        customer.name,
                        customer.channel,
                        self.config.device_serial,
                    )
                except Exception as e:
                    self.logger.error(f"Error in customer voice callback: {e}")

            if content is None:
                # Voice message was skipped
                return result

        # Handle image messages - include bounds/dimensions for unique identification
        # This is CRITICAL because image messages have no text content, so two different
        # images from the same sender at the same time would otherwise have the same hash
        if msg_type == MessageType.IMAGE and msg.image:
            if msg.image.bounds:
                extra_info["image_bounds"] = msg.image.bounds
            # Also include dimensions as a secondary identifier
            if msg.image.parse_bounds():
                width = msg.image.x2 - msg.image.x1
                height = msg.image.y2 - msg.image.y1
                extra_info["image_dimensions"] = f"{width}x{height}"

        # Handle video messages - include duration for unique identification
        if msg_type == MessageType.VIDEO and msg.video_duration:
            extra_info["video_duration"] = msg.video_duration

        # Parse timestamp using context
        timestamp_raw, timestamp_parsed = self._get_parsed_timestamp(msg.timestamp)

        # Include sequence number in extra_info for database deduplication
        # This allows multiple identical messages at the same timestamp to be distinct
        # Always include sequence (even if 0) to ensure uniqueness
        extra_info["sequence"] = msg._sequence

        # Include ui_position (raw index in UI tree) for improved deduplication
        # This helps distinguish messages with same content but different positions
        if hasattr(msg, "_raw_index") and msg._raw_index >= 0:
            extra_info["ui_position"] = msg._raw_index

        # Create message record with parsed timestamp
        message_record = MessageRecord(
            customer_id=customer.id,
            content=content,
            message_type=msg_type,
            is_from_kefu=msg.is_self,
            timestamp_raw=timestamp_raw,
            timestamp_parsed=timestamp_parsed,
            extra_info=json.dumps(extra_info) if extra_info else None,
        )

        # Try to add message (with deduplication)
        was_added, stored_msg = self.repository.add_message_if_not_exists(message_record)
        result["added"] = was_added

        # Handle image messages
        # IMPORTANT: Save images even for duplicate messages if:
        # 1. We have an inline-captured image (local_path exists)
        # 2. The DB record doesn't already have an associated image
        # This handles the case where a message was added in a previous sync
        # but its image wasn't captured (e.g., was cut off at screen edge)
        if msg_type == MessageType.IMAGE and msg.image and msg.image.local_path:
            # Check if this message already has an image in the DB
            existing_image = self.repository.get_image_for_message(stored_msg.id)
            if not existing_image:
                image_path = await self._save_message_image(msg, customer, stored_msg.id)
                if image_path:
                    result["image_saved"] = True
                    self.logger.debug(f"Saved image for {'new' if was_added else 'existing'} message {stored_msg.id}")
            else:
                self.logger.debug(f"Image already exists for message {stored_msg.id}, skipping")

        # Handle video messages
        if was_added and msg_type == MessageType.VIDEO:
            result["is_video"] = True
            video_path = await self._save_message_video(msg, customer, stored_msg.id)
            if video_path:
                result["video_saved"] = True

        # Handle voice messages - save audio file if available
        if msg_type == MessageType.VOICE and msg.voice_local_path:
            voice_path = await self._save_message_voice(msg, customer, stored_msg.id)
            if voice_path:
                result["voice_saved"] = True

        return result

    async def _handle_voice_message(
        self,
        msg: ConversationMessage,
    ) -> tuple[str | None, dict]:
        """
        Handle a voice message, potentially with user interaction.

        Args:
            msg: Voice message to handle

        Returns:
            Tuple of (content, extra_info)
        """
        extra_info = {}

        if msg.voice_duration:
            extra_info["voice_duration"] = msg.voice_duration

        # If message already has transcription content, use it
        if msg.content:
            extra_info["source"] = "transcription"
            return msg.content, extra_info

        # No caption available - need user interaction
        if self._voice_handler_callback:
            action, text = self._voice_handler_callback(msg)

            if action == VoiceHandlerAction.CAPTION:
                # Wait for user to reveal caption on screen
                self.logger.info("Waiting for user to reveal voice caption...")
                await asyncio.sleep(3.0)  # Give user time to interact

                # Re-extract to get caption
                tree = await self.wecom.adb.get_ui_tree()
                messages = self.wecom.ui_parser.extract_conversation_messages(tree)

                # Try to find the updated message with caption
                for updated_msg in messages:
                    if (
                        updated_msg.message_type == "voice"
                        and updated_msg.voice_duration == msg.voice_duration
                        and updated_msg.content
                    ):
                        extra_info["source"] = "user_revealed_caption"
                        return updated_msg.content, extra_info

                # Caption not found, fall back to placeholder
                extra_info["source"] = "placeholder_caption_not_found"
                return "[Voice Message]", extra_info

            elif action == VoiceHandlerAction.INPUT:
                extra_info["source"] = "user_input"
                return text, extra_info

            elif action == VoiceHandlerAction.PLACEHOLDER:
                extra_info["source"] = "placeholder"
                return "[Voice Message]", extra_info

            elif action == VoiceHandlerAction.SKIP:
                return None, {}

        # No callback set, use placeholder
        extra_info["source"] = "placeholder_no_callback"
        return "[Voice Message]", extra_info

    async def _save_message_image(
        self,
        msg: ConversationMessage,
        customer: CustomerRecord,
        message_id: int,
    ) -> str | None:
        """
        Save an image message record to database.

        Images are captured INLINE during extraction (when download_images=True).
        This method directly uses the inline captured path without copying:
        1. Checks if the image was already captured inline (has local_path)
        2. If yes: creates DB record pointing to the existing file
        3. If no: logs warning (image was not captured, likely due to being cut off)

        NOTE: No file copying is performed. The inline captured file is the
        final storage location.

        Args:
            msg: Image message (should have image.local_path if captured inline)
            customer: Customer record
            message_id: Database ID of the message

        Returns:
            Path to saved image, or None if not captured
        """
        if not msg.image:
            return None

        # Check if image was captured inline during extraction
        if msg.image.local_path:
            # Image was captured inline - use the existing file directly
            image_path = Path(msg.image.local_path)

            if not image_path.exists():
                self.logger.warning(f"Inline captured image missing: {image_path}")
                return None

            # Get image dimensions
            width, height = 0, 0
            try:
                from PIL import Image

                with Image.open(image_path) as img:
                    width, height = img.size
            except Exception:
                pass

            # Create database record directly (no file copying)
            from wecom_automation.database.models import ImageRecord

            image_record = ImageRecord(
                message_id=message_id,
                file_path=str(image_path),
                file_name=image_path.name,
                width=width,
                height=height,
                original_bounds=msg.image.bounds,
            )
            self.repository.create_image(image_record)

            self.logger.info(
                f"[SyncService] 图片记录已保存: {image_path.name} ({width}x{height}), "
                f"message_id={message_id}, customer={customer.name}"
            )

            # Upload to image review platform (fire-and-forget; errors only logged)
            try:
                import asyncio

                from services.image_review_client import upload_image_for_review

                self.logger.info(
                    f"[SyncService] 触发异步上传到审核平台: file={image_path.name}, message_id={message_id}"
                )
                asyncio.ensure_future(
                    upload_image_for_review(
                        image_path,
                        auto_analyze=True,
                        local_message_id=message_id,
                    )
                )
            except Exception as _upload_exc:
                self.logger.warning(f"[SyncService] 无法触发图片上传（image_review_client 不可用）: {_upload_exc}")

            return str(image_path)
        else:
            # Image was NOT captured inline
            # This happens when the image was partially cut off (near screen edges)
            # or if download_images=False was used during extraction
            self.logger.warning(
                f"Image for message {message_id} was not captured inline. "
                "This usually means the image was partially cut off during scroll."
            )
            return None

    async def _save_message_video(
        self,
        msg: ConversationMessage,
        customer: CustomerRecord,
        message_id: int,
    ) -> str | None:
        """
        Save a video message record to the database.

        If the video was already downloaded inline during extraction (video_local_path set),
        it will be used directly or moved to the customer directory. Otherwise, this records metadata only.

        Args:
            msg: Video message
            customer: Customer record
            message_id: Database ID of the message

        Returns:
            Path to saved video, or None if failed
        """
        try:
            # Create customer-specific directory
            customer_dir = self.videos_dir / f"customer_{customer.id}"
            customer_dir.mkdir(parents=True, exist_ok=True)

            # Parse duration to seconds if available
            duration_seconds = None
            if msg.video_duration:
                duration_seconds = VideoRecord.parse_duration_to_seconds(msg.video_duration)

            # Check if video was already downloaded inline during extraction
            video_local_path = getattr(msg, "video_local_path", None)
            actual_file_path = None
            file_size = None
            filename = None

            if video_local_path:
                source_path = Path(video_local_path)
                if source_path.exists():
                    # Check if the video is already in the customer directory
                    if str(source_path.parent) == str(customer_dir):
                        # Video is already in the right place - use it directly
                        actual_file_path = str(source_path)
                        filename = source_path.name
                        file_size = source_path.stat().st_size
                        self.logger.info(f"Using inline-downloaded video: {filename}")
                    else:
                        # Video is in a different directory - copy to customer directory
                        # Preserve the original filename to maintain consistency
                        filename = source_path.name
                        dest_path = customer_dir / filename

                        # If a file with the same name already exists, generate a new name
                        if dest_path.exists():
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            filename = f"video_{message_id}_{timestamp}.mp4"
                            dest_path = customer_dir / filename

                        import shutil

                        shutil.copy2(source_path, dest_path)
                        actual_file_path = str(dest_path)
                        file_size = dest_path.stat().st_size
                        self.logger.info(f"Copied inline-downloaded video to customer dir: {filename}")
                else:
                    self.logger.warning(f"Inline video path not found: {video_local_path}")

            # Generate a placeholder filename if we don't have one
            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"video_{message_id}_{timestamp}.mp4"

            # Create video record with the actual path (relative for portability)
            # Convert absolute path to relative if it's within the videos_dir
            if actual_file_path:
                actual_path_obj = Path(actual_file_path)
                try:
                    relative_path = actual_path_obj.relative_to(Path.cwd())
                    db_file_path = str(relative_path)
                except ValueError:
                    # Path is not relative to cwd, use as-is
                    db_file_path = actual_file_path
            else:
                db_file_path = f"[not downloaded] {filename}"

            video_record = VideoRecord(
                message_id=message_id,
                file_path=db_file_path,
                file_name=filename,
                duration=msg.video_duration,
                duration_seconds=duration_seconds,
                thumbnail_path=None,  # Could be captured from screenshot if needed
                file_size=file_size,
            )
            self.repository.create_video(video_record)

            if actual_file_path:
                self.logger.info(f"Saved video record: {db_file_path}")
                try:
                    from services.video_review_service import schedule_video_review_for_message

                    schedule_video_review_for_message(message_id, None)
                except Exception as _vr_exc:
                    self.logger.warning(f"[SyncService] 无法触发视频审核（video_review_service 不可用）: {_vr_exc}")
                return actual_file_path
            else:
                self.logger.info(f"Recorded video message (file not downloaded): {msg.video_duration}")
                return None

        except Exception as e:
            self.logger.error(f"Failed to save message video: {e}")

        return None

    async def _save_message_voice(
        self,
        msg: ConversationMessage,
        customer: CustomerRecord,
        message_id: int,
    ) -> str | None:
        """
        Save a voice message audio file to database and customer directory.

        Voice files are downloaded inline during extraction as WAV files
        (converted from WeCom's SILK format).

        Args:
            msg: Voice message with voice_local_path set
            customer: Customer record
            message_id: Database ID of the message

        Returns:
            Path to saved voice file, or None if failed
        """
        if not msg.voice_local_path:
            return None

        try:
            source_path = Path(msg.voice_local_path)
            if not source_path.exists():
                self.logger.warning(f"Voice file not found: {source_path}")
                return None

            # Create customer-specific directory for voices
            customer_dir = self.voices_dir / f"customer_{customer.id}"
            customer_dir.mkdir(parents=True, exist_ok=True)

            # Generate filename with message ID
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            extension = source_path.suffix or ".wav"
            filename = f"voice_{message_id}_{timestamp}{extension}"
            dest_path = customer_dir / filename

            # Copy to customer directory
            import shutil

            shutil.copy2(source_path, dest_path)

            file_size = dest_path.stat().st_size

            # Parse duration from voice_duration string (e.g., "2\"" -> 2 seconds)
            duration_seconds = None
            if msg.voice_duration:
                try:
                    duration_str = msg.voice_duration.replace('"', "").replace("'", "").strip()
                    duration_seconds = int(duration_str)
                except (ValueError, AttributeError):
                    pass

            # Create voice record in database
            # Note: Using a generic record structure, adjust based on your VoiceRecord model
            {
                "message_id": message_id,
                "file_path": str(dest_path),
                "file_name": filename,
                "duration": msg.voice_duration,
                "duration_seconds": duration_seconds,
                "file_size": file_size,
            }

            # Store in database (if you have a VoiceRecord model and repository method)
            # For now, we'll update the message's extra_info with the voice path
            try:
                self.repository.update_message_extra_info(
                    message_id, {"voice_file_path": str(dest_path), "voice_file_size": file_size}
                )
            except Exception as e:
                self.logger.warning(f"Could not update message extra_info: {e}")

            # Update the message's voice_local_path to the customer directory location
            msg.voice_local_path = str(dest_path)

            self.logger.info(f"Saved voice file: {filename} ({file_size} bytes)")
            return str(dest_path)

        except Exception as e:
            self.logger.error(f"Failed to save voice file: {e}")
            import traceback

            self.logger.debug(traceback.format_exc())
            return None

    # =========================================================================
    # Test Messages and Response Handling
    # =========================================================================

    async def _send_test_message_and_wait(
        self,
        last_msg: ConversationMessage,
        customer: CustomerRecord,
        wait_seconds: float,
    ) -> None:
        """
        Send a test message and wait for responses.

        Args:
            last_msg: The last message in the conversation
            customer: Customer record
            wait_seconds: How long to wait for responses
        """
        # Determine test message based on who sent the last message
        if last_msg.is_self:
            # Kefu sent last message - send a follow-up
            test_message = "测试信息: 想的怎么样了?"
        else:
            # Customer sent last message - echo it back
            content = last_msg.content or "[media]"
            test_message = f"测试信息: [...{content[:30]}...]"

        self.logger.info(f"Sending test message: {test_message[:50]}...")

        # Send the test message (returns actual message sent, may differ if AI reply used)
        success, actual_message = await self.wecom.send_message(test_message)

        if success:
            # Store the ACTUAL message sent (could be AI reply, not mock message)
            # Use current time with configured timezone
            now = self.timestamp_parser.get_now()
            test_record = MessageRecord(
                customer_id=customer.id,
                content=actual_message,
                message_type=MessageType.TEXT,
                is_from_kefu=True,
                timestamp_raw=now.strftime("%H:%M"),
                timestamp_parsed=now,
            )
            self.repository.add_message_if_not_exists(test_record)

            # Wait for and process responses
            await self._wait_and_process_responses(customer, wait_seconds)

    async def _wait_and_process_responses(
        self,
        customer: CustomerRecord,
        wait_seconds: float,
    ) -> None:
        """
        Wait for new messages and store them.

        Continues checking until no new messages for wait_seconds.

        Args:
            customer: Customer record
            wait_seconds: Time to wait for each response cycle
        """
        max_cycles = 5  # Prevent infinite loops
        cycles = 0

        while cycles < max_cycles:
            new_messages = await self.wecom.wait_for_new_messages(
                timeout_seconds=wait_seconds,
                check_interval=1.0,
            )

            if not new_messages:
                self.logger.info("No new messages, ending response wait")
                break

            # Store new messages
            for msg in new_messages:
                msg_type = MessageType.from_string(msg.message_type)
                # Parse timestamp using context
                timestamp_raw, timestamp_parsed = self._get_parsed_timestamp(msg.timestamp)
                record = MessageRecord(
                    customer_id=customer.id,
                    content=msg.content,
                    message_type=msg_type,
                    is_from_kefu=msg.is_self,
                    timestamp_raw=timestamp_raw,
                    timestamp_parsed=timestamp_parsed,
                )
                was_added, _ = self.repository.add_message_if_not_exists(record)

                if was_added:
                    self.logger.info(f"Stored response: {msg.content[:50] if msg.content else '[media]'}...")

            # If customer responded, send another test message and continue
            customer_responded = any(not m.is_self for m in new_messages)
            if customer_responded:
                self.logger.info("Customer responded, sending follow-up...")
                last_customer_msg = [m for m in new_messages if not m.is_self][-1]
                content = last_customer_msg.content or "[media]"
                follow_up = f"测试信息: [...{content[:30]}...]"

                # Send follow-up (returns actual message sent, may differ if AI reply used)
                success, actual_follow_up = await self.wecom.send_message(follow_up)

                if success:
                    # Store ACTUAL follow-up message sent (could be AI reply)
                    now = self.timestamp_parser.get_now()
                    follow_record = MessageRecord(
                        customer_id=customer.id,
                        content=actual_follow_up,
                        message_type=MessageType.TEXT,
                        is_from_kefu=True,
                        timestamp_raw=now.strftime("%H:%M"),
                        timestamp_parsed=now,
                    )
                    self.repository.add_message_if_not_exists(follow_record)

            cycles += 1

    # =========================================================================
    # Human-like Delays
    # =========================================================================

    async def _human_delay(self, delay_type: str) -> None:
        """
        Wait for a human-like delay.

        Args:
            delay_type: Type of delay ("tap", "scroll", "type", "user_switch", "read")
        """
        delay_methods = {
            "tap": self.timing.get_tap_delay,
            "scroll": self.timing.get_scroll_delay,
            "type": self.timing.get_type_delay,
            "user_switch": self.timing.get_user_switch_delay,
            "read": self.timing.get_read_delay,
        }

        delay_func = delay_methods.get(delay_type, self.timing.get_tap_delay)
        delay = delay_func()

        self.logger.debug(f"Human delay ({delay_type}): {delay:.2f}s")
        await asyncio.sleep(delay)
