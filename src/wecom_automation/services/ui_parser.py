"""
UI Parser Service - Parse and extract data from UI accessibility trees.

This service provides:
- UI tree traversal
- Element identification by patterns
- Data extraction (text, bounds, etc.)
- User detail parsing
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from wecom_automation.core.config import Config
from wecom_automation.core.logging import get_logger
from wecom_automation.core.models import AvatarInfo, ConversationMessage, ImageInfo, KefuInfo, UserDetail
from wecom_automation.utils.kefu_profile_parser import parse_kefu_profile

# Compiled regex patterns for timestamp detection
TIME_PATTERN = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b")
DATE_PATTERN = re.compile(r"\b\d{1,2}/\d{1,2}\b")
RELATIVE_TIME_PATTERN = re.compile(
    r"\b\d+\s*(?:min|mins|minute|minutes|hr|hrs|hour|hours|day|days|sec|secs|second|seconds)\s*ago\b", re.IGNORECASE
)
RELATIVE_TIME_PATTERN_CN = re.compile(r"\d+\s*(?:分钟|小时|天|秒)前")


def message_image_thumbnail_min_ok(width: int, height: int) -> bool:
    """
    True if an ImageView is plausibly an in-chat image thumbnail (not avatar).

    Avatars are ~76px. Portrait thumbnails can be narrower than 150px (e.g. 124x270);
    the old rule width>150 and height>150 dropped those.
    """
    min_side = min(width, height)
    max_side = max(width, height)
    return min_side >= 100 and max_side >= 150


DAY_NAMES = (
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


class UIParserService:
    """
    Service for parsing UI accessibility trees and extracting structured data.

    This service encapsulates all UI parsing logic, making it:
    - Testable in isolation with mock UI trees
    - Configurable via UIParserConfig
    - Reusable across different automation tasks
    """

    def __init__(self, config: Config | None = None):
        """
        Initialize the UI parser service.

        Args:
            config: Optional configuration (uses defaults if not provided)
        """
        self.config = config or Config()
        self.ui_config = self.config.ui_parser
        self.logger = get_logger("wecom_automation.ui_parser")

    # =========================================================================
    # Public API
    # =========================================================================

    def find_element_by_text(
        self,
        elements: list[dict[str, Any]],
        text_patterns: tuple[str, ...],
        exact_match: bool = False,
        is_flat_list: bool = False,
    ) -> dict[str, Any] | None:
        """
        Find the first element containing any of the specified text patterns.

        Args:
            elements: List of UI elements to search
            text_patterns: Text patterns to match
            exact_match: If True, require exact match
            is_flat_list: If True, skip recursive child search (optimized for
                         flat lists like clickable_elements_cache)

        Returns:
            Matching element dict, or None if not found
        """
        for element in elements:
            text = element.get("text", "")
            if text and self._matches_text(text, text_patterns, exact_match):
                return element

            # Only recursively check children if not a flat list
            if not is_flat_list:
                children = element.get("children", [])
                if children:
                    result = self.find_element_by_text(children, text_patterns, exact_match, is_flat_list=False)
                    if result:
                        return result

        return None

    def find_all_elements_by_text(
        self,
        elements: list[dict[str, Any]],
        text_patterns: tuple[str, ...],
        exact_match: bool = False,
        is_flat_list: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Find all elements containing any of the specified text patterns.

        Args:
            elements: List of UI elements to search
            text_patterns: Text patterns to match
            exact_match: If True, require exact match
            is_flat_list: If True, skip recursive child search (optimized for
                         flat lists like clickable_elements_cache)

        Returns:
            List of matching element dicts
        """
        results = []

        for element in elements:
            text = element.get("text", "")
            if text and self._matches_text(text, text_patterns, exact_match):
                results.append(element)

            # Only recursively check children if not a flat list
            if not is_flat_list:
                children = element.get("children", [])
                if children:
                    results.extend(
                        self.find_all_elements_by_text(children, text_patterns, exact_match, is_flat_list=False)
                    )

        return results

    def match_user_to_index(
        self,
        user: UserDetail,
        clickable_elements: list[dict[str, Any]],
    ) -> int | None:
        """
        Find the DroidRun index for a user by matching text.

        This maps extracted user data back to DroidRun's clickable_elements_cache,
        allowing reliable automation via tap(index) instead of coordinates.

        Args:
            user: UserDetail object with name to match
            clickable_elements: List of clickable elements from DroidRun

        Returns:
            Element index if found, None otherwise
        """
        user_name_lower = user.name.lower().strip()

        for element in clickable_elements:
            text = (element.get("text") or "").strip().lower()
            if text == user_name_lower:
                index = element.get("index")
                if index is not None:
                    self.logger.debug(f"Matched '{user.name}' to index {index}")
                    return index

        return None

    def find_message_containers(
        self,
        tree: Any,
    ) -> list[dict[str, Any]]:
        """
        Find probable conversation list containers in the UI tree.

        Args:
            tree: The accessibility tree (dict or list)

        Returns:
            List of candidate container nodes, sorted by full-width priority then child count
        """
        roots = self._normalize_tree(tree)
        candidates: list[dict[str, Any]] = []
        stack: list[dict[str, Any]] = list(roots)

        # 获取屏幕宽度和高度（从根节点）
        screen_width = 1080  # 默认值
        screen_height = 2400  # 默认值
        if roots:
            root = roots[0]
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

            # Skip if not from WeCom
            if package_name and "wework" not in package_name:
                continue

            # Check if this looks like a list container
            is_list = self._looks_like_list_container(class_name, resource_id)
            if is_list:
                candidates.append(node)
                self.logger.debug(
                    f"Found container: class='{class_name}', id='{resource_id}', children={len(children)}"
                )

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
        self.logger.debug(f"Found {len(candidates)} candidate containers")

        return candidates

    def extract_users_from_tree(
        self,
        tree: Any,
    ) -> list[UserDetail]:
        """
        Extract user details from the UI tree.

        This is the main entry point for extracting user information
        from the conversation list.

        注意：只使用第一个有效容器（全宽优先），避免从隐藏/缓存的UI元素中提取错误数据。

        Args:
            tree: The accessibility tree

        Returns:
            List of extracted UserDetail objects
        """
        self.logger.info("Extracting users from UI tree...")

        containers = self.find_message_containers(tree)
        if not containers:
            self.logger.warning("No message list containers found")
            return []

        # 只使用第一个容器（已按全宽优先 + 子节点数排序）
        # 避免从非全宽的隐藏/缓存元素中提取错误数据
        for container_idx, container in enumerate(containers):
            self.logger.debug(f"Processing container {container_idx}...")
            children = container.get("children", [])
            entries: list[UserDetail] = []

            for row_idx, child in enumerate(children):
                if isinstance(child, dict):
                    entry = self._extract_user_from_row(child, row_idx)
                    if entry:
                        entries.append(entry)

            self.logger.debug(f"Container {container_idx} yielded {len(entries)} entries")

            # 如果从第一个容器提取到了有效条目，则返回
            if entries:
                self.logger.info(f"Extracted {len(entries)} users from tree")
                return entries

        self.logger.info("No users extracted from tree")
        return []

    def get_current_filter_text(
        self,
        elements: list[dict[str, Any]],
    ) -> str | None:
        """
        Determine the currently selected filter ('All', 'Private Chats', etc.).

        The filter label in WeCom is not always marked as clickable, so we
        inspect all elements near the header region and match against the
        configured filter text patterns.
        """
        original_patterns = self.config.app.all_text_patterns + self.config.app.private_chats_patterns
        pattern_lookup = {pattern.lower(): pattern for pattern in original_patterns}
        lowercase_patterns = tuple(pattern_lookup.keys())

        def matches_pattern(value: str) -> bool:
            value_lower = value.lower()
            return any(pattern in value_lower for pattern in lowercase_patterns)

        def is_header_element(element: dict[str, Any]) -> bool:
            bounds = self._get_node_bounds(element)
            if not bounds:
                return True  # fall back when bounds missing
            match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
            if not match:
                return True
            _, top, _, _ = map(int, match.groups())
            return top < 600  # header area near top of screen

        def search(nodes: Sequence[dict[str, Any]]) -> str | None:
            for element in nodes:
                if not isinstance(element, dict):
                    continue

                text = (element.get("text") or "").strip()
                if text and matches_pattern(text) and is_header_element(element):
                    return text

                resource_id = (element.get("resourceId") or "").lower()
                if resource_id and any(pattern in resource_id for pattern in lowercase_patterns):
                    if text:
                        return text
                    # Provide best-effort fallback using matched pattern
                    for pattern_lower, original in pattern_lookup.items():
                        if pattern_lower in resource_id:
                            return original

                children = element.get("children") or []
                if children:
                    result = search(children)
                    if result:
                        return result

            return None

        return search(elements)

    # =========================================================================
    # Text Pattern Matching
    # =========================================================================

    def _matches_text(
        self,
        text: str,
        patterns: tuple[str, ...],
        exact_match: bool,
    ) -> bool:
        """Check if text matches any of the patterns."""
        for pattern in patterns:
            if exact_match:
                if text == pattern:
                    return True
            else:
                if pattern.lower() in text.lower() or text.lower() in pattern.lower():
                    return True
        return False

    def looks_like_timestamp(self, value: str) -> bool:
        """
        Check if a string looks like a timestamp.

        Args:
            value: String to check

        Returns:
            True if value looks like a timestamp
        """
        if not value:
            return False

        value_lower = value.lower().strip()

        # Check regex patterns
        if TIME_PATTERN.search(value):
            return True
        if DATE_PATTERN.search(value):
            return True
        if RELATIVE_TIME_PATTERN.search(value):
            return True
        if RELATIVE_TIME_PATTERN_CN.search(value):
            return True

        # Check day names
        for day in DAY_NAMES:
            if day.lower() in value_lower or value_lower == day.lower():
                return True

        return False

    def looks_like_channel(self, value: str) -> bool:
        """
        Check if a string looks like a channel indicator.

        Args:
            value: String to check

        Returns:
            True if value looks like a channel (e.g., @WeChat)
        """
        if not value:
            return False

        value_lower = value.lower().strip()

        for pattern in self.config.app.channel_text_patterns:
            if pattern.lower() in value_lower:
                return True

        # Check if starts with @ (half-width or full-width)
        if (value.startswith("@") or value.startswith("＠")) and len(value) < 20:
            return True

        return False

    def looks_like_dropdown_filter(self, name: str) -> bool:
        """
        Check if a name looks like a dropdown/filter UI element.

        Args:
            name: The extracted name to check

        Returns:
            True if this looks like a dropdown filter element
        """
        if not name:
            return False

        name_lower = name.lower().strip()

        for pattern in self.ui_config.dropdown_filter_patterns:
            if pattern.lower() in name_lower:
                return True
            # Also check when stripping ellipsis
            name_clean = name_lower.replace("...", "").replace("…", "").strip()
            if pattern.lower() in name_clean or name_clean in pattern.lower():
                return True

        return False

    def looks_like_unread_badge(self, value: str) -> bool:
        """
        Check if a string looks like an unread count badge.

        Unread badges are typically:
        - Pure numbers (1-99)
        - "99+" or similar overflow patterns
        - "new" or "新" indicators

        Args:
            value: String to check

        Returns:
            True if value looks like an unread count badge
        """
        if not value:
            return False

        value = value.strip()

        # Pure number (1-999)
        if value.isdigit() and len(value) <= 3:
            return True

        # Overflow patterns: "99+", "999+", etc.
        if re.match(r"^\d+\+$", value):
            return True

        # "new" or "新" indicators
        if value.lower() in ("new", "新", "新消息"):
            return True

        return False

    def looks_like_filter_header(self, value: str) -> bool:
        """
        Check if a string looks like a filter/category header.

        These are UI elements like "Internal chats", "Private chats",
        "私聊", "群聊" that appear as list section headers.

        Args:
            value: String to check

        Returns:
            True if value looks like a filter header
        """
        if not value:
            return False

        value_lower = value.lower().strip()

        # Common filter headers
        filter_headers = (
            "internal chats",
            "private chats",
            "内部聊天",
            "外部聊天",
            "私聊",
            "群聊",
            "单聊",
            "private chats",
            "group chats",
        )

        for pattern in filter_headers:
            if pattern in value_lower or value_lower in pattern:
                return True

        return False

    # =========================================================================
    # Tree Traversal Helpers
    # =========================================================================

    def _normalize_tree(self, tree: Any) -> list[dict[str, Any]]:
        """Normalize tree to a list of root nodes."""
        if isinstance(tree, dict):
            return [tree]
        elif isinstance(tree, Sequence) and not isinstance(tree, str):
            return [node for node in tree if isinstance(node, dict)]
        return []

    def _looks_like_list_container(self, class_name: str, resource_id: str) -> bool:
        """Check if a node looks like a list container."""
        is_list_class = any(hint in class_name for hint in self.ui_config.message_list_class_hints)
        is_list_id = any(hint in resource_id for hint in self.ui_config.message_list_id_hints)
        return is_list_class or is_list_id

    def _collect_all_nodes(self, node: dict[str, Any]) -> list[dict[str, Any]]:
        """Flatten the tree into a list of all nodes."""
        results = [node]
        children = node.get("children") or []
        for child in children:
            if isinstance(child, dict):
                results.extend(self._collect_all_nodes(child))
        return results

    def _collect_text_nodes(self, node: dict[str, Any]) -> list[dict[str, Any]]:
        """Collect all nodes that have text."""
        results = []
        all_nodes = self._collect_all_nodes(node)
        for n in all_nodes:
            text = (n.get("text") or "").strip()
            if text:
                results.append(n)
        return results

    # =========================================================================
    # User Extraction from Row
    # =========================================================================

    def _extract_user_from_row(
        self,
        row_node: dict[str, Any],
        row_index: int,
    ) -> UserDetail | None:
        """
        Extract a UserDetail from a single row node.

        Args:
            row_node: The row node to analyze
            row_index: Index of the row

        Returns:
            UserDetail if extraction successful, None otherwise
        """
        self.logger.debug(f"Analyzing row {row_index}...")

        text_nodes = self._collect_text_nodes(row_node)
        all_nodes = self._collect_all_nodes(row_node)

        if not text_nodes:
            self.logger.debug(f"Row {row_index}: No text nodes, skipping")
            return None

        # Initialize fields
        name: str | None = None
        channel: str | None = None
        last_message_date: str | None = None
        message_preview: str | None = None

        # First pass: identify by resource ID hints
        for tn in text_nodes:
            text = (tn.get("text") or "").strip()
            rid = (tn.get("resourceId") or "").lower()

            if not text:
                continue

            if not name and any(h in rid for h in self.ui_config.name_resource_id_hints):
                name = text
                continue

            if not last_message_date and any(h in rid for h in self.ui_config.date_resource_id_hints):
                last_message_date = text
                continue

            if not message_preview and any(h in rid for h in self.ui_config.snippet_resource_id_hints):
                message_preview = text
                continue

            if not channel and any(h in rid for h in self.ui_config.channel_resource_id_hints):
                channel = text
                continue

        # Second pass: identify by content patterns
        used_texts = {name, channel, last_message_date, message_preview}

        for tn in text_nodes:
            text = (tn.get("text") or "").strip()
            if not text or text in used_texts:
                continue

            if not channel and self.looks_like_channel(text):
                channel = text
                used_texts.add(text)
                continue

            if not last_message_date and self.looks_like_timestamp(text):
                last_message_date = text
                used_texts.add(text)
                continue

        # Third pass: heuristic assignment
        remaining_texts = [
            (tn.get("text") or "").strip() for tn in text_nodes if (tn.get("text") or "").strip() not in used_texts
        ]

        if not name and remaining_texts:
            # Find first text that looks like a valid name
            # Skip unread badges (numbers), timestamps, and channel indicators
            for text in remaining_texts:
                if (
                    not self.looks_like_unread_badge(text)
                    and not self.looks_like_timestamp(text)
                    and not self.looks_like_channel(text)
                    and not self.looks_like_filter_header(text)
                ):
                    name = text
                    used_texts.add(name)
                    break

            # Update remaining_texts to exclude the chosen name
            remaining_texts = [t for t in remaining_texts if t not in used_texts]

        if not message_preview and remaining_texts:
            # Pick longest non-timestamp, non-channel, non-badge text
            candidates = [
                t
                for t in remaining_texts
                if (
                    not self.looks_like_timestamp(t)
                    and not self.looks_like_channel(t)
                    and not self.looks_like_unread_badge(t)
                )
            ]
            if candidates:
                candidates.sort(key=len, reverse=True)
                message_preview = candidates[0]

        # Find avatar
        avatar = self._find_avatar_in_row(all_nodes)

        # Skip dropdown/filter elements and filter headers
        if name and (self.looks_like_dropdown_filter(name) or self.looks_like_filter_header(name)):
            self.logger.debug(f"Row {row_index}: Skipping '{name}' - looks like dropdown/filter")
            return None

        if name:
            return UserDetail(
                name=name,
                channel=channel,
                last_message_date=last_message_date,
                message_preview=message_preview,
                avatar=avatar,
                _raw_index=row_index,
            )

        self.logger.debug(f"Row {row_index}: Could not determine name")
        return None

    # =========================================================================
    # Avatar Detection
    # =========================================================================

    def _find_avatar_in_row(
        self,
        all_nodes: list[dict[str, Any]],
    ) -> AvatarInfo | None:
        """
        Find the avatar image in a row.

        Uses multiple strategies:
        1. Look for elements with avatar hints in resource ID
        2. Look for ImageView elements on the left side
        3. Infer avatar bounds from row layout

        Args:
            all_nodes: All nodes in the row

        Returns:
            AvatarInfo if found, None otherwise
        """
        avatar_candidates: list[tuple[dict[str, Any], int, str]] = []
        row_bounds = None
        leftmost_text_x = 9999

        # Analyze all nodes
        for node in all_nodes:
            bounds = self._get_node_bounds(node)
            if bounds:
                class_name = (node.get("className") or "").lower()

                # Parse bounds
                bounds_match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                if bounds_match:
                    x1, y1, x2, y2 = map(int, bounds_match.groups())
                    width = x2 - x1

                    # Track row bounds
                    if width > 500 and (row_bounds is None or width > row_bounds[2] - row_bounds[0]):
                        row_bounds = (x1, y1, x2, y2)

                    # Track leftmost text position
                    if "textview" in class_name or "text" in class_name:
                        if x1 < leftmost_text_x:
                            leftmost_text_x = x1

        # Look for avatar elements
        for node in all_nodes:
            bounds = self._get_node_bounds(node)
            if not bounds:
                continue

            class_name = (node.get("className") or "").lower()
            resource_id = (node.get("resourceId") or "").lower()

            # Skip text views
            if "textview" in class_name or "text" in class_name:
                continue

            bounds_match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
            if not bounds_match:
                continue

            x1, y1, x2, y2 = map(int, bounds_match.groups())
            width = x2 - x1
            height = y2 - y1

            # Skip full-row elements
            if width > 300:
                continue

            # Calculate score
            score = 0

            # Resource ID hints (strong)
            for hint in self.ui_config.avatar_resource_id_hints:
                if hint in resource_id:
                    score += 20
                    break

            # Class hints
            for hint in self.ui_config.avatar_class_hints:
                if hint in class_name:
                    score += 15
                    break

            # Position (left side)
            if x1 < 50:
                score += 15
            elif x1 < 100:
                score += 10
            elif x1 < 150:
                score += 5

            # Aspect ratio (square-ish)
            aspect_ratio = width / height if height > 0 else 0
            if 0.85 <= aspect_ratio <= 1.15:
                score += 10
            elif 0.7 <= aspect_ratio <= 1.3:
                score += 5

            # Size
            if 40 <= width <= 150 and 40 <= height <= 150:
                score += 8

            if score >= 20:
                avatar_candidates.append((node, score, bounds))

        # Return best candidate
        if avatar_candidates:
            avatar_candidates.sort(key=lambda x: x[1], reverse=True)
            best_node, _, best_bounds = avatar_candidates[0]
            return AvatarInfo(
                bounds=best_bounds,
                resource_id=best_node.get("resourceId"),
                content_description=best_node.get("contentDescription"),
            )

        # Infer avatar from layout
        if row_bounds and leftmost_text_x < 9999 and leftmost_text_x > 100:
            return self._infer_avatar_bounds(row_bounds, leftmost_text_x)

        return None

    def _infer_avatar_bounds(
        self,
        row_bounds: tuple[int, int, int, int],
        leftmost_text_x: int,
    ) -> AvatarInfo | None:
        """Infer avatar bounds from row layout."""
        row_x1, row_y1, row_x2, row_y2 = row_bounds
        row_height = row_y2 - row_y1

        # Estimate avatar size
        estimated_size = int(row_height * 0.7)
        estimated_size = max(60, min(estimated_size, 150))

        # Position
        avatar_left = row_x1 + 36
        avatar_right = min(avatar_left + estimated_size, leftmost_text_x - 20)

        if avatar_right - avatar_left < 50:
            avatar_right = leftmost_text_x - 10

        actual_width = avatar_right - avatar_left
        vertical_padding = (row_height - actual_width) // 2
        avatar_top = row_y1 + vertical_padding
        avatar_bottom = avatar_top + actual_width

        inferred_bounds = f"[{avatar_left},{avatar_top}][{avatar_right},{avatar_bottom}]"

        return AvatarInfo(
            bounds=inferred_bounds,
            content_description="inferred",
        )

    def _get_node_bounds(self, node: dict[str, Any]) -> str | None:
        """Get bounds from a node, checking multiple possible property names."""
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
    # Conversation Message Extraction
    # =========================================================================

    def _detect_screen_width(self, nodes: list[dict[str, Any]]) -> int:
        """
        Auto-detect screen width from UI tree by finding the maximum x2 coordinate.

        Args:
            nodes: Flattened list of all UI nodes

        Returns:
            Detected screen width (720, 1080, or 1440)
        """
        max_x2 = 0
        for node in nodes:
            bounds_str = self._get_node_bounds(node)
            if bounds_str:
                match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
                if match:
                    x2 = int(match.group(3))
                    if x2 > max_x2:
                        max_x2 = x2

        # Common screen widths: 720, 1080, 1440
        if max_x2 <= 800:
            return 720
        elif max_x2 <= 1200:
            return 1080
        else:
            return 1440

    def extract_conversation_messages(
        self,
        tree: Any,
        screen_width: int | None = None,
    ) -> list[ConversationMessage]:
        """
        Extract messages from a conversation view UI tree.

        This method parses the conversation window to extract individual messages,
        including text, images, voice messages, and system messages.

        Args:
            tree: The accessibility tree
            screen_width: Screen width in pixels for determining message alignment.
                         If not provided, auto-detects from UI tree.

        Returns:
            List of extracted ConversationMessage objects
        """
        # Normalize tree first to get all nodes for detection
        roots = self._normalize_tree(tree)
        all_nodes = []
        for root in roots:
            all_nodes.extend(self._collect_all_nodes(root))

        # Auto-detect screen width if not provided
        if screen_width is None:
            screen_width = self._detect_screen_width(all_nodes)
            self.logger.info(f"Auto-detected screen width: {screen_width}px")

        self.logger.info(f"Extracting conversation messages (screen_width={screen_width})...")

        messages: list[ConversationMessage] = []

        # Find the message ListView (WeCom uses ListView with id containing 'iop')
        listview = self._find_message_listview(roots)

        if listview:
            messages = self._extract_messages_from_listview(listview, screen_width)
        else:
            # Fallback to container-based extraction
            message_containers = self._find_conversation_containers(roots)
            for container in message_containers:
                container_messages = self._extract_messages_from_container(container, screen_width)
                if len(container_messages) > len(messages):
                    messages = container_messages

        self.logger.info(f"Extracted {len(messages)} messages from conversation")
        return messages

    def _find_message_listview(
        self,
        nodes: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """
        Find the message ListView in WeCom (id contains 'iop').

        Args:
            nodes: Root nodes to search

        Returns:
            ListView node if found, None otherwise
        """
        stack = list(nodes)

        while stack:
            node = stack.pop()
            resource_id = node.get("resourceId") or ""
            class_name = (node.get("className") or "").lower()

            # Check using configured hints
            is_list_id = any(hint in resource_id for hint in self.ui_config.message_list_id_hints)

            if is_list_id or ("listview" in class_name and len(node.get("children", [])) > 0):
                children = node.get("children", [])
                # Verify it looks like a message list (children have known row ids)
                if children:
                    first_child_rid = children[0].get("resourceId") or ""
                    if (
                        any(hint in first_child_rid for hint in self.ui_config.message_row_id_hints)
                        or len(children) >= 3
                    ):
                        return node

            for child in node.get("children", []):
                if isinstance(child, dict):
                    stack.append(child)

        return None

    def _extract_messages_from_listview(
        self,
        listview: dict[str, Any],
        screen_width: int,
    ) -> list[ConversationMessage]:
        """
        Extract messages from WeCom's message ListView.

        Each child of the ListView is a message row (RelativeLayout with id 'cmn').

        WeChat shows timestamps as separators, with multiple messages sharing
        a timestamp. This method tracks the current timestamp context and
        propagates it to messages that don't have their own timestamp.

        Args:
            listview: The ListView node
            screen_width: Screen width for alignment detection

        Returns:
            List of ConversationMessage objects with propagated timestamps
        """
        messages: list[ConversationMessage] = []
        children = listview.get("children", [])

        # Track current timestamp context for propagation
        current_timestamp: str | None = None

        # Track sequence numbers for identical messages (key: base_key, value: count)
        # This allows distinguishing multiple identical messages at the same timestamp
        sequence_counters: dict[str, int] = defaultdict(int)

        for idx, child in enumerate(children):
            if not isinstance(child, dict):
                continue

            # First, check if this row is a timestamp separator
            separator_timestamp = self._extract_timestamp_separator(child)
            if separator_timestamp:
                current_timestamp = separator_timestamp
                self.logger.debug(f"Timestamp separator found: {current_timestamp}")
                continue

            message = self._extract_message_from_row(child, idx, screen_width)
            if message:
                # Propagate timestamp if message doesn't have its own
                if not message.timestamp and current_timestamp:
                    message.timestamp = current_timestamp
                # Update context if message has its own timestamp
                elif message.timestamp:
                    current_timestamp = message.timestamp

                # Assign sequence number for identical messages at same timestamp
                base_key = self._get_message_base_key(message)
                message._sequence = sequence_counters[base_key]
                sequence_counters[base_key] += 1

                messages.append(message)

        return messages

    def _get_message_base_key(self, msg: ConversationMessage) -> str:
        """
        Generate base key for sequence tracking.

        This key identifies messages that would otherwise be identical
        (same sender, type, content). We intentionally DO NOT include
        timestamp because:
        1. unique_key() doesn't include timestamp
        2. The same message content sent at different times should get
           different sequence numbers so they have different unique_keys

        Example: "测试信息" sent at 9:50 and again at 10:16 should be:
        - First: sequence 0, unique_key = "self|text|测试信息|"
        - Second: sequence 1, unique_key = "self|text|测试信息|1"
        """
        dir_part = "self" if msg.is_self else "other"
        type_part = msg.message_type

        if msg.message_type == "voice":
            content_part = f"{msg.voice_duration or ''}/{msg.content or ''}"[:80]
        elif msg.message_type == "image" and msg.image and msg.image.bounds:
            match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", msg.image.bounds)
            if match:
                x1, y1, x2, y2 = map(int, match.groups())
                content_part = f"{x2 - x1}x{y2 - y1}"
            else:
                content_part = "img"
        else:
            content_part = (msg.content or "")[:80]

        return f"{dir_part}|{type_part}|{content_part}"

    def _extract_timestamp_separator(self, row: dict[str, Any]) -> str | None:
        """
        Check if a row is a timestamp separator and extract the timestamp.

        Timestamp separators are rows that contain only a timestamp text
        (like "Thursday PM 7:37", "Yesterday PM 8:41", "PM 8:29").

        Args:
            row: Row node to check

        Returns:
            Timestamp string if this is a separator, None otherwise
        """
        all_nodes = self._collect_all_nodes(row)
        row_bounds = self._get_node_bounds(row)

        # Parse row bounds to get Y position
        row_y = 0
        if row_bounds:
            match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", row_bounds)
            if match:
                row_y = int(match.group(2))

        # Skip rows in header area (reduced threshold to capture messages near top)
        if row_y < 150:
            return None

        timestamp: str | None = None
        has_content = False
        has_avatar = False

        for node in all_nodes:
            rid = (node.get("resourceId") or "").lower()
            text = (node.get("text") or "").strip()

            # Check for timestamp (ief in old WeCom, ih1 in newer WeCom)
            if ("ief" in rid or "ih1" in rid) and text:
                # Verify this looks like a timestamp, not a system message
                if not self._is_system_message_text(text):
                    timestamp = text
                continue

            # Check for avatar - indicates actual message row
            if any(hint in rid for hint in self.ui_config.avatar_resource_id_hints):
                has_avatar = True
                continue

            # Check for message content
            if any(hint in rid for hint in self.ui_config.snippet_resource_id_hints) and text:
                has_content = True
                continue

            # Check for voice duration:
            # - ies in old WeCom
            # - ie5 in mid WeCom
            # - ihf in newer WeCom
            # - iht on currently observed devices
            if ("ies" in rid or "ie5" in rid or "ihf" in rid or "iht" in rid) and text:
                has_content = True
                continue

        # It's a timestamp separator if it has timestamp but no content/avatar
        if timestamp and not has_content and not has_avatar:
            return timestamp

        return None

    def _extract_message_from_row(
        self,
        row: dict[str, Any],
        index: int,
        screen_width: int,
    ) -> ConversationMessage | None:
        """
        Extract a message from a single row in the ListView.

        WeCom message structure:
        - RelativeLayout [cmn] - message row container
          - ImageView [im4] - avatar (left for others, right for self)
          - TextView [ief] - timestamp (optional, centered)
          - LinearLayout [hwl] or [ih3] - message bubble
            - TextView [idk] - text message content
            - TextView [ies] - voice duration (e.g., "2\"")
            - TextView [p05] - voice transcription text

        Args:
            row: Row node (RelativeLayout)
            index: Index in the list
            screen_width: Screen width for alignment detection

        Returns:
            ConversationMessage if extraction successful, None otherwise
        """
        all_nodes = self._collect_all_nodes(row)
        row_bounds = self._get_node_bounds(row)

        # Parse row bounds to get Y position
        row_y = 0
        if row_bounds:
            match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", row_bounds)
            if match:
                row_y = int(match.group(2))

        # Skip rows in header area (reduced threshold to capture messages near top)
        # Header is typically around 150px, lowered from 250 to avoid missing top messages
        if row_y < 150:
            return None

        # Find key elements by resource ID
        timestamp: str | None = None
        content: str | None = None
        voice_duration: str | None = None
        voice_transcription: str | None = None
        video_duration: str | None = None  # For video messages (e.g., "00:45")
        is_self = False
        message_type = "text"
        image_info: ImageInfo | None = None
        avatar_x: int | None = None
        content_x: int | None = None
        has_video_thumbnail = False  # Video thumbnail has resource ID k2j
        has_play_button = False  # Play button overlay has resource ID jqb
        # Sticker detection variables
        has_sticker = False
        sticker_bounds: str | None = None

        for node in all_nodes:
            rid = (node.get("resourceId") or "").lower()
            text = (node.get("text") or "").strip()
            node_bounds = self._get_node_bounds(node)

            # Get X position for alignment detection
            # Use CENTER X instead of left edge (x1) for accurate alignment detection
            # This fixes the issue where kefu messages were misidentified as customer messages
            # because text left edge can be on left side even for right-aligned bubbles
            node_x = 0
            node_center_x = 0
            if node_bounds:
                match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node_bounds)
                if match:
                    x1, _, x2, _ = map(int, match.groups())
                    node_x = x1  # Left edge (for avatar detection)
                    node_center_x = (x1 + x2) // 2  # Center (for content alignment)

            # Timestamp (ief in old WeCom, ih1 in newer WeCom) - but can also be system messages!
            if ("ief" in rid or "ih1" in rid) and text:
                # Check if this is actually a system message
                if self._is_system_message_text(text):
                    # This is a system message, not a timestamp
                    return ConversationMessage(
                        content=text,
                        timestamp=None,
                        is_self=False,
                        message_type="system",
                        raw_bounds=row_bounds,
                        _raw_index=index,
                    )
                else:
                    timestamp = text
                continue

            # Avatar - used to determine self vs other
            if any(hint in rid for hint in self.ui_config.avatar_resource_id_hints):
                avatar_x = node_x  # Use left edge for avatar (small square element)
                continue

            # Voice duration:
            # - ies in old WeCom
            # - ie5 in mid WeCom
            # - ihf in newer WeCom
            # - iht on currently observed devices
            if ("ies" in rid or "ie5" in rid or "ihf" in rid or "iht" in rid) and text:
                voice_duration = text
                message_type = "voice"
                continue

            # Voice transcription:
            # - p05 in old WeCom
            # - oyl in mid WeCom
            # - p47 in newer WeCom
            # - p4w on currently observed devices
            if ("p05" in rid or "oyl" in rid or "p47" in rid or "p4w" in rid) and text:
                voice_transcription = text
                continue

            # Text message content
            if any(hint in rid for hint in self.ui_config.snippet_resource_id_hints) and text:
                content = text
                # Use CENTER X for content alignment detection
                # This is critical: right-aligned bubbles have text starting from left
                # but the bubble center is on the right side
                content_x = node_center_x
                continue

            # Video duration:
            # - e5v in old WeCom
            # - e5l in newer WeCom
            # - e8l on currently observed devices
            # This appears in video messages, distinct from voice duration
            if ("e5v" in rid or "e5l" in rid or "e8l" in rid) and text:
                # Video duration format is typically "MM:SS" or "H:MM:SS"
                if re.match(r"^\d{1,2}:\d{2}(:\d{2})?$", text):
                    video_duration = text
                continue

            # Video thumbnail (k2j in old WeCom, k1r/k1s in new WeCom)
            if "k2j" in rid or "k1r" in rid or "k1s" in rid:
                has_video_thumbnail = True
                continue

            # Play button overlay (jqb in old WeCom, jpn in new WeCom) - indicates video
            if "jqb" in rid or "jpn" in rid:
                has_play_button = True
                continue

            # Sticker detection (igf in old WeCom, ijr in newer WeCom + RelativeLayout + childCount=0)
            # Stickers have: className="RelativeLayout", childCount=0, large bounds (not a button)
            if "igf" in rid or "ijr" in rid:
                class_name = (node.get("className") or "").lower()
                child_count = node.get("childCount", len(node.get("children", [])))
                if "relativelayout" in class_name and child_count == 0:
                    has_sticker = True
                    sticker_bounds = node_bounds
                    continue

        # Determine if self message based on avatar position and message bubble position
        # WeCom chat layout:
        # - KEFU (self) messages: RIGHT side, typically NO avatar shown
        # - CUSTOMER messages: LEFT side, avatar on LEFT
        #
        # Detection strategy (following followup_service.py pattern):
        # 1. If avatar found on LEFT (x < 200) -> CUSTOMER message
        # 2. If avatar found on RIGHT (x > screen_width - 200) -> KEFU message
        # 3. If NO avatar found, check message bubble/content position:
        #    - Content on RIGHT side -> KEFU message (self messages don't show avatar)
        #    - Content on LEFT side -> CUSTOMER message

        # First check avatar position
        avatar_on_left = avatar_x is not None and avatar_x < 200
        avatar_on_right = avatar_x is not None and avatar_x > screen_width - 200

        if avatar_on_left:
            # Avatar on left = customer message
            is_self = False
        elif avatar_on_right:
            # Avatar on right = kefu message
            is_self = True
        elif content_x is not None:
            # No avatar found - use content position
            # KEY: KEFU messages typically don't show avatar in WeCom
            # So if content is on right side -> KEFU (is_self=True)
            # If content is on left side -> CUSTOMER (is_self=False)
            is_self = content_x > screen_width // 2
        else:
            # Fallback: try to find any clickable/bubble element position
            # Look for message bubble containers
            for node in all_nodes:
                node_bounds = self._get_node_bounds(node)
                rid = (node.get("resourceId") or "").lower()
                class_name = (node.get("className") or "").lower()

                # Look for bubble-like containers
                is_bubble = any(hint in rid for hint in ("bubble", "msg", "message", "content", "idk"))
                is_clickable = node.get("clickable") or "relativelayout" in class_name

                if (is_bubble or is_clickable) and node_bounds:
                    match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node_bounds)
                    if match:
                        x1, _, x2, _ = map(int, match.groups())
                        width = x2 - x1
                        # Skip full-width containers
                        if width < screen_width * 0.8:
                            center_x = (x1 + x2) // 2
                            is_self = center_x > screen_width // 2
                            break

        # Check for video messages first
        # Video detection requires STRONG evidence:
        # - video_duration (e5v with time format like "00:45") is the most reliable indicator
        # - OR both video thumbnail (k2j) AND play button (jqb) together
        # Single indicators like just k2j or just jqb are NOT enough (could be in image views)
        if not content and not voice_duration:
            is_video = video_duration is not None or (has_video_thumbnail and has_play_button)

            if is_video:
                message_type = "video"
                # Store video duration as content for display
                if video_duration:
                    content = f"[Video {video_duration}]"
                else:
                    content = "[Video]"
                # Still try to get image info for the thumbnail
                image_info = self._find_message_image(all_nodes, screen_width)
            elif has_sticker:
                # Sticker message - detected by igf resource id + RelativeLayout
                message_type = "sticker"
                content = "[表情包]"
                # Use sticker bounds to create ImageInfo for screenshot
                if sticker_bounds:
                    image_info = ImageInfo(bounds=sticker_bounds)
            else:
                # Check for image-only messages (no text content but has image)
                image_info = self._find_message_image(all_nodes, screen_width)
                if image_info:
                    message_type = "image"
                    if not content:
                        content = "[图片]"

        # Check for system messages (timestamp-only rows or centered text)
        if not content and not voice_duration and not image_info:
            # This might be a timestamp-only row or system message
            # Check for system message patterns
            for node in all_nodes:
                text = (node.get("text") or "").strip()
                rid = (node.get("resourceId") or "").lower()

                # Skip timestamp which we already captured (ief in old, ih1 in newer WeCom)
                if "ief" in rid or "ih1" in rid:
                    continue

                if text and self._is_system_message_text(text):
                    return ConversationMessage(
                        content=text,
                        timestamp=timestamp,
                        is_self=False,
                        message_type="system",
                        raw_bounds=row_bounds,
                        _raw_index=index,
                    )

            # If only timestamp, skip this row (it's just a date separator)
            if timestamp and not content:
                return None

            return None

        # For voice messages, use transcription as content if available
        if message_type == "voice" and voice_transcription:
            content = voice_transcription

        return ConversationMessage(
            content=content,
            timestamp=timestamp,
            is_self=is_self,
            message_type=message_type,
            image=image_info,
            voice_duration=voice_duration,
            video_duration=video_duration,
            raw_bounds=row_bounds,
            _raw_index=index,
        )

    def _find_message_image(
        self,
        all_nodes: list[dict[str, Any]],
        screen_width: int,
    ) -> ImageInfo | None:
        """
        Find a message image (not avatar) in the nodes.

        Avatars have id 'im4' and are small (~114px).
        Message images are larger and don't have avatar id.
        """
        for node in all_nodes:
            rid = (node.get("resourceId") or "").lower()
            class_name = (node.get("className") or "").lower()
            bounds = self._get_node_bounds(node)

            # Skip avatars (im4/ilg in old WeCom, iov in newer WeCom)
            if any(hint in rid for hint in self.ui_config.avatar_resource_id_hints):
                continue

            # Check if this is an ImageView
            if "imageview" not in class_name and "image" not in class_name:
                continue

            if not bounds:
                continue

            match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
            if not match:
                continue

            x1, y1, x2, y2 = map(int, match.groups())
            width = x2 - x1
            height = y2 - y1

            if message_image_thumbnail_min_ok(width, height):
                return ImageInfo(
                    bounds=bounds,
                    resource_id=node.get("resourceId"),
                    content_description=node.get("contentDescription"),
                )

        return None

    def _is_system_message_text(self, text: str) -> bool:
        """Check if text looks like a system message."""
        system_patterns = (
            "added",
            "removed",
            "joined",
            "left",
            "created",
            "recalled a message",
            "已添加",
            "已移除",
            "加入",
            "离开",
            "创建",
            "以上是打招呼内容",
            "开始聊天",
            "撤回了一条消息",
            "你已添加",
            "现在可以开始聊天",
            # User deletion/blocked patterns
            "has enabled verification for contacts",
            "Send a verification request",
            "You're not his/her contact",
            "开启了联系人验证",
            "发起验证请求",
            "你还不是他的企业联系人",
            "你还不是她的企业联系人",
        )
        text_lower = text.lower()
        return any(p.lower() in text_lower for p in system_patterns)

    def is_user_deleted_message(self, text: str) -> bool:
        """Check if text indicates the user has deleted/blocked us."""
        deletion_patterns = (
            "has enabled verification for contacts",
            "Send a verification request",
            "You're not his/her contact",
            "开启了联系人验证",
            "发起验证请求",
            "你还不是他的企业联系人",
            "你还不是她的企业联系人",
        )
        text_lower = text.lower()
        return any(p.lower() in text_lower for p in deletion_patterns)

    def _find_conversation_containers(
        self,
        nodes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Find conversation message list containers in the UI tree.

        Args:
            nodes: Root nodes to search

        Returns:
            List of candidate container nodes
        """
        candidates: list[dict[str, Any]] = []
        stack: list[dict[str, Any]] = list(nodes)

        # Hints for conversation containers
        conv_class_hints = ("recyclerview", "listview", "scrollview", "viewgroup")
        conv_id_hints = ("message", "chat", "conversation", "msg", "bubble", "list")

        while stack:
            node = stack.pop()
            children = node.get("children") or []
            stack.extend(child for child in children if isinstance(child, dict))

            if not children:
                continue

            class_name = (node.get("className") or "").lower()
            resource_id = (node.get("resourceId") or "").lower()
            package_name = (node.get("packageName") or "").lower()

            # Skip if not from WeCom
            if package_name and "wework" not in package_name:
                continue

            # Check if this looks like a message container
            is_list_class = any(hint in class_name for hint in conv_class_hints)
            is_list_id = any(hint in resource_id for hint in conv_id_hints)

            if is_list_class or is_list_id:
                candidates.append(node)
                self.logger.debug(
                    f"Found conversation container: class='{class_name}', id='{resource_id}', children={len(children)}"
                )

        # Sort by number of children (most children first)
        candidates.sort(key=lambda n: len(n.get("children") or []), reverse=True)
        return candidates

    def _extract_messages_from_container(
        self,
        container: dict[str, Any],
        screen_width: int,
    ) -> list[ConversationMessage]:
        """
        Extract messages from a conversation container (fallback method).

        Args:
            container: Container node
            screen_width: Screen width for alignment detection

        Returns:
            List of ConversationMessage objects
        """
        messages: list[ConversationMessage] = []
        children = container.get("children", [])

        for idx, child in enumerate(children):
            if not isinstance(child, dict):
                continue

            message = self._extract_message_from_row(child, idx, screen_width)
            if message:
                messages.append(message)

        return messages

    def get_conversation_header_info(
        self,
        tree: Any,
    ) -> tuple[str | None, str | None]:
        """
        Extract contact name and channel from conversation header.

        Args:
            tree: The accessibility tree

        Returns:
            Tuple of (contact_name, channel)
        """
        roots = self._normalize_tree(tree)
        contact_name: str | None = None
        channel: str | None = None

        # Look for header elements at the top of the screen
        for root in roots:
            all_nodes = self._collect_all_nodes(root)

            for node in all_nodes:
                bounds = self._get_node_bounds(node)
                if not bounds:
                    continue

                # Parse bounds to check position
                match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                if not match:
                    continue

                x1, y1, x2, y2 = map(int, match.groups())

                # Header is typically in top 200 pixels
                if y1 > 250:
                    continue

                text = (node.get("text") or "").strip()
                if not text:
                    continue

                # Check for channel pattern
                if self.looks_like_channel(text):
                    channel = text
                    continue

                # Check for contact name (not a button or common UI text)
                resource_id = (node.get("resourceId") or "").lower()
                class_name = (node.get("className") or "").lower()

                # Skip navigation buttons and common UI elements
                skip_patterns = ("back", "more", "menu", "icon", "button")
                if any(p in resource_id or p in class_name for p in skip_patterns):
                    continue

                # Skip very short text (likely icons)
                if len(text) < 2:
                    continue

                # This is likely the contact name
                if not contact_name and "textview" in class_name:
                    contact_name = text

        return contact_name, channel

    # =========================================================================
    # Kefu (Customer Service Rep) Extraction
    # =========================================================================

    def extract_kefu_info_from_tree(
        self,
        tree: Any,
        max_x: int = 700,
        min_y: int = 80,
        max_y: int = 900,
    ) -> KefuInfo | None:
        self.logger.info("Extracting kefu info from main-page profile block...")

        parsed = parse_kefu_profile(tree, max_x=max_x, min_y=min_y, max_y=max_y)
        if not parsed:
            self.logger.warning("Could not determine kefu info from profile block")
            return None

        self.logger.info(f"Found kefu name: {parsed.name}")
        return KefuInfo(
            name=parsed.name,
            department=parsed.department,
            verification_status=parsed.verification_status,
        )
        """
        Extract the 客服 (Customer Service Rep) name from the UI tree.

        The 客服 name is typically found in the upper-left area of the screen,
        on the app's main page, in the profile/sidebar region showing:
        - User avatar
        - User name (the 客服 name we want)
        - Department/organization
        - Verification status (e.g., "未认证")

        Args:
            tree: The accessibility tree
            max_x: Maximum X coordinate for the profile area
            min_y: Minimum Y coordinate for the profile area (inclusive)
            max_y: Maximum Y coordinate for the profile area (inclusive)

        Returns:
            KefuInfo with extracted name, or None if not found
        """
        self.logger.info("Extracting 客服 info from UI tree...")

        roots = self._normalize_tree(tree)
        if not roots:
            self.logger.warning("Empty UI tree")
            return None

        # Collect all text nodes with their positions
        text_elements: list[dict[str, Any]] = []

        for root in roots:
            all_nodes = self._collect_all_nodes(root)

            for node in all_nodes:
                text = (node.get("text") or "").strip()
                if not text:
                    continue

                bounds = self._get_node_bounds(node)
                if not bounds:
                    continue

                match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                if not match:
                    continue

                x1, y1, x2, y2 = map(int, match.groups())

                # Only consider elements in the left panel area
                if x1 > max_x:
                    continue

                text_elements.append(
                    {
                        "text": text,
                        "x1": x1,
                        "y1": y1,
                        "x2": x2,
                        "y2": y2,
                        "height": y2 - y1,
                        "node": node,
                    }
                )

        if not text_elements:
            self.logger.warning("No text elements found in profile panel area")
            return None

        # Sort by Y position (top to bottom)
        text_elements.sort(key=lambda e: e["y1"])

        # Patterns to exclude from name candidates
        exclude_patterns = (
            "消息",
            "messages",
            "全部",
            "all",
            "私聊",
            "private",
            "日程",
            "schedule",
            "calendar",
            "会议",
            "meeting",
            "未认证",
            "已认证",
            "认证",
            "@",
            "＠",
        )

        # Patterns that indicate verification status
        verification_patterns = ("未认证", "已认证")

        # Patterns that indicate department
        department_patterns = ("实验室", "部门", "部", "组", "team", "dept")

        name_candidates: list[dict[str, Any]] = []
        department: str | None = None
        verification: str | None = None

        for elem in text_elements:
            text = elem["text"]
            text_lower = text.lower()
            y1 = elem["y1"]

            # Skip elements outside the configured vertical band
            if y1 < min_y or y1 > max_y:
                continue

            # Check for verification status
            for vp in verification_patterns:
                if vp in text:
                    verification = text
                    break

            # Check for department
            for dp in department_patterns:
                if dp.lower() in text_lower:
                    department = text
                    break

            # Check if this should be excluded
            is_excluded = any(ep.lower() in text_lower or text_lower in ep.lower() for ep in exclude_patterns)

            if is_excluded:
                continue

            # Name length check (2-30 characters)
            if len(text) < 2 or len(text) > 30:
                continue

            name_candidates.append(elem)

        # Score name candidates
        best_name: str | None = None
        best_score = -1

        for candidate in name_candidates:
            text = candidate["text"]
            y1 = candidate["y1"]
            height = candidate["height"]

            score = 0

            # Prefer elements in the profile area (around y=200-400)
            if 150 <= y1 <= 400:
                score += 20
            elif y1 < 150:
                score += 5
            else:
                score += 10

            # Prefer typical name text height
            if 30 <= height <= 80:
                score += 15

            # Prefer reasonable name length
            if 2 <= len(text) <= 15:
                score += 10

            # Clean up trailing arrows
            clean_text = text.rstrip(">》 ")
            if clean_text != text:
                score += 5  # Clickable name with arrow

            if score > best_score:
                best_score = score
                best_name = clean_text

        if best_name:
            self.logger.info(f"Found 客服 name: {best_name}")
            return KefuInfo(
                name=best_name,
                department=department,
                verification_status=verification,
            )

        self.logger.warning("Could not determine 客服 name")
        return None
