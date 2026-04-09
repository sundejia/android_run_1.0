"""
未读消息检测器

从UI树中提取有未读消息的用户列表。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass
class UnreadUserInfo:
    """
    未读用户信息

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
        """生成唯一键用于去重"""
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
    未读用户提取器

    从WeCom的UI树中提取用户列表，包括未读消息数。

    Usage:
        extractor = UnreadUserExtractor()
        users = extractor.extract_from_tree(ui_tree)
        unread_users = [u for u in users if u.has_unread()]
    """

    # Badge检测提示
    BADGE_CLASS_HINTS = ("textview", "text", "badge", "unread", "count", "number")
    BADGE_RESOURCE_ID_HINTS = ("badge", "unread", "count", "num", "dot", "red")
    NAME_RESOURCE_ID_HINTS = ("title", "name", "nickname", "username", "contact")
    CHANNEL_TEXT_PATTERNS = ("@WeChat", "@微信", "@wechat", "＠WeChat", "＠微信", "＠wechat")

    # 容器检测提示
    MESSAGE_LIST_CLASS_HINTS = ("recyclerview", "listview", "viewpager", "listlayout", "viewgroup")
    MESSAGE_LIST_ID_HINTS = ("conversation", "session", "message", "msg", "chat", "recent", "list", "inbox")

    # 需要排除的元素
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

    # 新好友欢迎语关键词 - 用于识别刚添加的好友
    NEW_FRIEND_WELCOME_KEYWORDS = (
        # 英文关键词 - 添加新好友系统消息
        "You have added",
        "as your WeCom",
        # 中文关键词 - 欢迎语
        "感谢您信任并选择WELIKE",
        "未来我将会",
        "感谢您信任",
        "选择WELIKE",
    )

    def __init__(self, logger: logging.Logger | None = None):
        """
        初始化提取器

        Args:
            logger: 日志记录器
        """
        self._logger = logger or logging.getLogger(__name__)

    @staticmethod
    def _get_node_bounds(node: dict[str, Any]) -> str | None:
        """从节点获取边界坐标字符串"""
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
        """解析边界字符串为坐标元组"""
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
        """将树扁平化为节点列表"""
        results = [node]
        children = node.get("children") or []
        for child in children:
            if isinstance(child, dict):
                results.extend(UnreadUserExtractor._collect_all_nodes(child))
        return results

    @staticmethod
    def _is_badge_text(text: str) -> bool:
        """检查文本是否像未读徽章数字"""
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
        """检查字符串是否像时间戳"""
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

    @classmethod
    def _looks_like_channel(cls, value: str) -> bool:
        """检查字符串是否像渠道标识"""
        if not value:
            return False
        value_lower = value.lower().strip()
        for pattern in cls.CHANNEL_TEXT_PATTERNS:
            if pattern.lower() in value_lower:
                return True
        if (value.startswith("@") or value.startswith("＠")) and len(value) < 20:
            return True
        return False

    @classmethod
    def _looks_like_dropdown_filter(cls, name: str) -> bool:
        """检查名称是否像下拉筛选UI元素"""
        if not name:
            return False
        name_lower = name.lower().strip()
        for pattern in cls.DROPDOWN_FILTER_PATTERNS:
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
    def _find_avatar_bounds_in_row(cls, all_nodes: list[dict[str, Any]]) -> tuple[int, int, int, int] | None:
        """在行中查找头像边界"""
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
        """在行中查找未读徽章"""
        badge_candidates: list[tuple[int, int, str]] = []

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
        """定位可能的会话列表容器"""
        candidates: list[dict[str, Any]] = []
        stack: list[dict[str, Any]] = list(nodes)

        # 获取屏幕宽度（从根节点）
        screen_width = 1080  # 默认值
        if nodes:
            root = nodes[0] if isinstance(nodes, (list, tuple)) else nodes
            bounds = root.get("boundsInScreen", {})
            if isinstance(bounds, dict):
                screen_width = bounds.get("right", 1080) - bounds.get("left", 0)

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

            优先级：
            1. 全宽容器优先（宽度 >= 屏幕宽度的 95%）
            2. 然后按子节点数排序
            """
            bounds = node.get("boundsInScreen", {})
            if isinstance(bounds, dict):
                width = bounds.get("right", 0) - bounds.get("left", 0)
            else:
                width = 0

            # 是否为全宽容器
            is_full_width = width >= screen_width * 0.95
            child_count = len(node.get("children") or [])

            # 返回元组，优先按全宽排序，然后按子节点数
            return (is_full_width, child_count)

        candidates.sort(key=get_container_score, reverse=True)
        return candidates

    @classmethod
    def _extract_entry_from_row(cls, row_node: dict[str, Any]) -> UnreadUserInfo | None:
        """从单行节点提取用户信息"""
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

        # 第一遍：通过资源ID识别
        for tn in text_nodes:
            text = tn.get("_resolved_text", "")
            rid = (tn.get("resourceId") or "").lower()

            if not text:
                continue
            if cls._is_badge_text(text) and len(text) <= 3:
                continue

            if not name and any(hint in rid for hint in cls.NAME_RESOURCE_ID_HINTS):
                name = text
                continue

        # 第二遍：通过内容模式识别
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

        # 第三遍：启发式分配
        remaining_texts = []
        for tn in text_nodes:
            text = tn.get("_resolved_text", "")
            if text and text not in used_texts:
                if cls._is_badge_text(text) and len(text) <= 3:
                    continue
                remaining_texts.append(text)

        if not name and remaining_texts:
            name = remaining_texts[0]
            used_texts.add(name)
            remaining_texts = remaining_texts[1:]

        if not message_preview and remaining_texts:
            preview_candidates = [
                text
                for text in remaining_texts
                if not cls._looks_like_timestamp(text) and not cls._looks_like_channel(text)
            ]
            if preview_candidates:
                preview_candidates.sort(key=len, reverse=True)
                message_preview = preview_candidates[0]

        # 跳过下拉筛选元素
        if name and cls._looks_like_dropdown_filter(name):
            return None

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

    def extract_from_tree(self, tree: Any) -> list[UnreadUserInfo]:
        """
        从UI树中提取用户列表

        返回所有用户（包括没有未读消息的）。
        使用 has_unread() 方法过滤出有未读消息的用户。

        注意：只使用第一个有效容器（全宽优先），避免从隐藏/缓存的UI元素中提取错误数据。

        Args:
            tree: UI树 (字典或字典列表)

        Returns:
            用户信息列表
        """
        roots = []
        if isinstance(tree, dict):
            roots = [tree]
        elif isinstance(tree, Sequence) and not isinstance(tree, str):
            roots = [node for node in tree if isinstance(node, dict)]

        containers = self._find_message_containers(roots)
        if not containers:
            self._logger.debug("No message containers found in UI tree")
            return []

        # 只使用第一个容器（已按全宽优先 + 子节点数排序）
        # 避免从非全宽的隐藏/缓存元素中提取错误数据
        for container in containers:
            children = container.get("children", [])
            entries: list[UnreadUserInfo] = []

            for child in children:
                if isinstance(child, dict):
                    entry = self._extract_entry_from_row(child)
                    if entry:
                        entries.append(entry)

            # 如果从第一个容器提取到了有效条目，则返回
            if entries:
                self._logger.debug(f"Extracted {len(entries)} users from UI tree")
                return entries

        self._logger.debug("No users extracted from UI tree")
        return []

    def extract_unread_only(self, tree: Any) -> list[UnreadUserInfo]:
        """
        从UI树中提取有未读消息的用户

        Args:
            tree: UI树

        Returns:
            有未读消息的用户列表
        """
        all_users = self.extract_from_tree(tree)
        return [u for u in all_users if u.has_unread()]
