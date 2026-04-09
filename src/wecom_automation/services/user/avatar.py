"""
头像管理器

处理用户头像的捕获、缓存和管理。
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Any


class AvatarManager:
    """
    头像管理器

    职责:
    - 检查头像缓存
    - 捕获用户头像
    - 使用默认头像作为后备

    Usage:
        manager = AvatarManager(wecom_service, avatars_dir)

        # 如果需要则捕获头像
        path = await manager.capture_if_needed("张三")

        # 检查是否已缓存
        if manager.is_cached("张三"):
            path = manager.get_path("张三")
    """

    # 头像检测提示
    AVATAR_CLASS_HINTS = ("imageview", "image", "avatar", "icon", "photo")
    AVATAR_RESOURCE_ID_HINTS = ("avatar", "photo", "icon", "head", "portrait", "profile")

    def __init__(
        self,
        wecom_service,
        avatars_dir: Path,
        default_avatar: Path | None = None,
        logger: logging.Logger | None = None,
        log_callback: callable | None = None,
    ):
        """
        初始化头像管理器

        Args:
            wecom_service: WeComService实例
            avatars_dir: 头像保存目录
            default_avatar: 默认头像路径
            logger: 日志记录器
            log_callback: 可选的异步回调函数，用于发送日志到前端
                          格式: async def log_callback(level: str, message: str)
        """
        self._wecom = wecom_service
        self._avatars_dir = Path(avatars_dir)
        self._default_avatar = Path(default_avatar) if default_avatar else None
        self._logger = logger or logging.getLogger(__name__)
        self._log_callback = log_callback  # Store callback for sending logs to frontend

        # 确保目录存在
        self._avatars_dir.mkdir(parents=True, exist_ok=True)

    async def _log(self, level: str, message: str, to_console: bool = True):
        """
        发送日志到前端和控制台

        Args:
            level: 日志级别 (DEBUG, INFO, WARNING, ERROR)
            message: 日志消息
            to_console: 是否同时输出到控制台（默认True，因为日志通过stdout被发送到前端）
        """
        # 发送到前端（如果有回调）
        if self._log_callback:
            try:
                await self._log_callback(level, f"[AVATAR] {message}")
            except Exception:
                pass  # Callback failed, will use console below

        # 输出到控制台（被 DeviceManager._read_output 捕获并发送到前端）
        if to_console:
            getattr(self._logger, level.lower(), self._logger.info)(f"[AVATAR] {message}")

    def is_cached(self, name: str) -> bool:
        """
        检查头像是否已缓存

        Args:
            name: 用户名称

        Returns:
            True如果已缓存
        """
        for suffix in [".png", ".jpg", ".jpeg"]:
            # 尝试多种命名格式
            patterns = [
                f"avatar_{name}{suffix}",
                f"avatar_*_{name}{suffix}",
            ]
            for pattern in patterns:
                if pattern.startswith("avatar_*"):
                    # 模糊匹配
                    for _f in self._avatars_dir.glob(f"avatar_*{name}{suffix}"):
                        return True
                else:
                    if (self._avatars_dir / pattern).exists():
                        return True
        return False

    def get_path(self, name: str) -> Path | None:
        """
        获取已缓存的头像路径

        Args:
            name: 用户名称

        Returns:
            头像文件路径，不存在返回None
        """
        for suffix in [".png", ".jpg", ".jpeg"]:
            # 精确匹配
            path = self._avatars_dir / f"avatar_{name}{suffix}"
            if path.exists():
                return path

            # 带索引的匹配
            for f in self._avatars_dir.glob(f"avatar_*_{name}{suffix}"):
                return f

        return None

    async def capture_if_needed(self, name: str) -> Path | None:
        """
        如果头像未缓存则捕获

        Args:
            name: 用户名称

        Returns:
            头像文件路径
        """
        if self.is_cached(name):
            cached_path = self.get_path(name)
            await self._log(
                "INFO", f"[avatar] ✓ Already cached: {name} -> {cached_path.name if cached_path else 'None'}"
            )
            return cached_path

        await self._log("INFO", f"[avatar] Not cached, starting capture for: {name}")
        return await self.capture(name)

    async def capture(self, name: str, max_scroll_attempts: int = 3) -> Path | None:
        """
        捕获用户头像

        Args:
            name: 用户名称
            max_scroll_attempts: 最大滚动尝试次数

        Returns:
            保存的头像路径，失败返回None
        """
        await self._log("INFO", f"[avatar] 📷 Starting capture for: {name}")

        try:
            # 尝试在当前界面捕获
            result = await self._try_capture_once(name)
            if result:
                await self._log("INFO", f"[avatar] ✓ Captured: {name}")
                return result

            # 如果失败，尝试滚动后再捕获
            for attempt in range(max_scroll_attempts):
                await self._log("INFO", f"[avatar] Scroll attempt {attempt + 1}/{max_scroll_attempts}")

                # 滚动
                if hasattr(self._wecom, "scroll_up"):
                    await self._wecom.scroll_up()
                else:
                    await self._log("WARNING", "[avatar] scroll_up not available")

                result = await self._try_capture_once(name)
                if result:
                    await self._log("INFO", f"[avatar] ✓ Captured after scroll: {name}")
                    return result

            await self._log("WARNING", f"[avatar] ✗ All attempts failed for: {name}")
            # 使用默认头像
            return await self._use_default(name)

        except Exception as e:
            await self._log("ERROR", f"[avatar] Exception: {e}")
            return await self._use_default(name)

    async def _try_capture_once(self, name: str) -> Path | None:
        """
        尝试捕获一次头像

        Args:
            name: 用户名称

        Returns:
            头像路径，失败返回None
        """
        try:
            # 获取UI树
            tree = None

            if hasattr(self._wecom, "get_ui_tree"):
                tree = await self._wecom.get_ui_tree()
            elif hasattr(self._wecom, "adb") and hasattr(self._wecom.adb, "get_ui_tree"):
                tree = await self._wecom.adb.get_ui_tree()
            else:
                await self._log("ERROR", "[avatar] No get_ui_tree method found")
                return None

            if not tree:
                await self._log("ERROR", "[avatar] get_ui_tree returned None")
                return None

            # 查找头像位置
            avatar_bounds = await self._find_avatar_in_tree(tree, name)

            if not avatar_bounds:
                return None

            # 截图保存
            filepath = self._avatars_dir / f"avatar_{name}.png"

            if hasattr(self._wecom, "screenshot_element"):
                bounds_str = f"[{avatar_bounds[0]},{avatar_bounds[1]}][{avatar_bounds[2]},{avatar_bounds[3]}]"

                await self._wecom.screenshot_element(bounds_str, str(filepath))

                if filepath.exists():
                    await self._log("INFO", f"[avatar] 💾 Saved: {filepath.name}")
                    return filepath
                else:
                    await self._log("ERROR", f"[avatar] File not created: {filepath}")
            else:
                await self._log("ERROR", "[avatar] screenshot_element method not found")

        except Exception as e:
            await self._log("ERROR", f"[avatar] Exception: {e}")

        return None

    async def _use_default(self, name: str) -> Path | None:
        """
        使用默认头像

        Args:
            name: 用户名称

        Returns:
            复制后的头像路径
        """
        if not self._default_avatar or not self._default_avatar.exists():
            # 尝试查找默认头像
            default_path = self._avatars_dir / "avatar_default.png"
            if not default_path.exists():
                await self._log("WARNING", "[avatar] No default avatar found")
                return None
            self._default_avatar = default_path

        dest = self._avatars_dir / f"avatar_{name}.png"

        try:
            shutil.copy(self._default_avatar, dest)
            await self._log("INFO", f"[avatar] 📋 Using default for: {name}")
            return dest
        except Exception as e:
            await self._log("ERROR", f"[avatar] Failed to copy default: {e}")
            return None

    async def _find_avatar_in_tree(self, tree: Any, name: str) -> tuple[int, int, int, int] | None:
        """
        在UI树中查找指定用户的头像位置

        使用基于用户名位置的推断方法

        Args:
            tree: UI树
            name: 用户名称

        Returns:
            (x1, y1, x2, y2) 坐标元组
        """
        await self._log("INFO", f"[avatar] Searching for avatar: {name}")

        nodes = self._collect_all_nodes(tree)
        await self._log("INFO", f"[avatar] Collected {len(nodes)} UI nodes")

        if not nodes:
            await self._log("ERROR", "No nodes found in UI tree!")
            return None

        # =============================================================
        # 基于位置推断的方法
        # =============================================================
        await self._log("INFO", "[avatar] Using position-based inference")

        # UI elements to skip (not user names)
        SKIP_TEXTS = {
            "微信",
            "企业微信",
            "私聊",
            "Private Chats",
            "消息",
            "Messages",
            "Cal",
            "Calendar",
            "日历",
            "Meeting",
            "会议",
            "Private...",
            "@WeChat",
            "@微信",
            "@企微",
            "100%",
            "AM",
            "PM",
            "Search",
            "搜索",
        }

        # Find list container to exclude sidebar
        list_container = None
        for node in nodes:
            class_name = (node.get("className") or "").lower()
            if "recyclerview" in class_name or "listview" in class_name:
                bounds = self._get_node_bounds(node)
                parsed = self._parse_bounds(bounds)
                if parsed:
                    x1, y1, x2, y2 = parsed
                    # The chat list should be prominent and below the header
                    if y1 > 200 and (x2 - x1) > 500:
                        list_container = node
                        await self._log("INFO", "[avatar] Found chat list container")
                        break

        if list_container:
            # Re-collect nodes only from the list container to ignore sidebar
            nodes = self._collect_all_nodes(list_container)
            await self._log("INFO", f"[avatar] Restricted to list: {len(nodes)} nodes")
        else:
            await self._log("WARNING", "[avatar] No list container found, using heuristic")

        # Find potential row containers and user names
        row_containers = []
        user_name_candidates = []

        for node in nodes:
            class_name = (node.get("className") or "").lower()
            text = (node.get("text") or "").strip()
            bounds = self._get_node_bounds(node)
            if not bounds:
                continue
            parsed = self._parse_bounds(bounds)
            if not parsed:
                continue

            x1, y1, x2, y2 = parsed

            # Identify row containers (RelativeLayout)
            if "relativelayout" in class_name or "linearlayout" in class_name:
                # Row containers should be wide and moderate height
                if (x2 - x1) > 600 and 100 < (y2 - y1) < 300:
                    row_containers.append({"node": node, "bounds": parsed, "y1": y1, "y2": y2})

            # Identify user name candidates
            if text and len(text) > 1 and text not in SKIP_TEXTS:
                # Basic timestamp and date filtering
                if not any(ts in text for ts in [":", "AM", "PM", "202", "Yesterday"]) and (x2 - x1) < 500:
                    if x1 > 150:  # Leave room for avatar
                        user_name_candidates.append({"text": text, "bounds": parsed, "y1": y1, "x1": x1})

        # Sort by Y position
        user_name_candidates.sort(key=lambda x: x["y1"])

        # Find the target user
        target_user = None
        for user in user_name_candidates:
            user_text = user["text"].split("@")[0].split("[")[0].strip()
            # Try exact match first, then partial match
            if user_text == name or name in user_text or user_text in name:
                target_user = user
                await self._log("INFO", f"[avatar] Found user: '{user_text}'")
                break

        if target_user:
            text_x1, text_y1, text_x2, text_y2 = target_user["bounds"]

            # Find the row container for this user
            container = None
            for row in row_containers:
                ry1, ry2 = row["y1"], row["y2"]
                if ry1 <= text_y1 <= ry2:
                    container = row
                    break

            if container:
                cx1, cy1, cx2, cy2 = container["bounds"]
                row_h = cy2 - cy1

                # Fine-tuned parameters (from test code)
                avatar_size = int(row_h * 0.58)
                avatar_x1 = cx1 + 56  # Offset from left edge
                avatar_y1 = cy1 + (row_h - avatar_size) // 2  # Center vertically
            else:
                # Fallback based on text position
                avatar_size = 100
                avatar_x1 = max(text_x1 - avatar_size - 40, 56)
                avatar_y1 = text_y1 - 5

            avatar_x2 = avatar_x1 + avatar_size
            avatar_y2 = avatar_y1 + avatar_size

            await self._log("INFO", f"[avatar] ✓ Inferred position: [{avatar_x1},{avatar_y1}][{avatar_x2},{avatar_y2}]")
            await self._log("INFO", f"[avatar]   Size: {avatar_size}x{avatar_size}, Name at: [{text_x1},{text_y1}]")

            return (avatar_x1, avatar_y1, avatar_x2, avatar_y2)

        # =============================================================
        # 位置推断策略失败
        # =============================================================
        await self._log("WARNING", f"[avatar] ✗ Position inference failed for: '{name}'")
        candidates = [u["text"] for u in user_name_candidates[:5]]
        await self._log("INFO", f"[avatar]   Candidates found: {candidates}")
        return None

    def _collect_all_nodes(self, tree: Any) -> list[dict[str, Any]]:
        """收集所有节点"""
        if isinstance(tree, dict):
            results = [tree]
            children = tree.get("children") or []
            for child in children:
                if isinstance(child, dict):
                    results.extend(self._collect_all_nodes(child))
            return results
        elif isinstance(tree, (list, tuple)):
            results = []
            for item in tree:
                if isinstance(item, dict):
                    results.extend(self._collect_all_nodes(item))
            return results
        return []

    @staticmethod
    def _get_node_bounds(node: dict[str, Any]) -> str | None:
        """获取节点边界"""
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
        return None

    @staticmethod
    def _parse_bounds(bounds: str) -> tuple[int, int, int, int] | None:
        """解析边界字符串"""
        if not bounds:
            return None
        match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if match:
            return tuple(map(int, match.groups()))
        return None

    def list_cached(self) -> list[str]:
        """
        列出所有已缓存头像的用户名

        Returns:
            用户名列表
        """
        names = set()
        for f in self._avatars_dir.glob("avatar_*.png"):
            # 解析文件名提取用户名
            name = f.stem.replace("avatar_", "")
            # 移除索引前缀（如 "02_张三" -> "张三"）
            if "_" in name and name.split("_")[0].isdigit():
                name = "_".join(name.split("_")[1:])
            if name and name != "default":
                names.add(name)
        return list(names)

    def clear_cache(self) -> int:
        """
        清空头像缓存

        Returns:
            删除的文件数
        """
        count = 0
        for f in self._avatars_dir.glob("avatar_*.png"):
            if f.name != "avatar_default.png":
                try:
                    f.unlink()
                    count += 1
                except Exception:
                    pass
        return count
