"""
补刀功能执行器模块

通过搜索框查找联系人并发送补刀消息。
独立模块，可被外部调用。

核心流程：
1. 点击右上角搜索图标
2. 输入联系人名称
3. 点击搜索结果进入聊天
4. 发送补刀消息
5. 返回消息列表
"""

import asyncio
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from droidrun import AdbTools

logger = logging.getLogger("followup.executor")


class SearchTargetNotFoundError(Exception):
    """Raised when no matching search result is found for target contact."""


class FollowupStatus(str, Enum):
    """补刀状态"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class FollowupResult:
    """单次补刀结果"""

    target_name: str
    status: FollowupStatus
    message_sent: str | None = None
    error: str | None = None
    duration_ms: int = 0


@dataclass
class BatchFollowupResult:
    """批量补刀结果"""

    total: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[FollowupResult] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total == 0:
            return 0.0
        return self.success / self.total


class FollowupExecutor:
    """
    补刀执行器

    负责通过搜索框查找联系人并发送补刀消息。

    使用方式:
        executor = FollowupExecutor(device_serial)
        await executor.connect()

        # 单个补刀
        result = await executor.execute("联系人名称", "补刀消息")

        # 批量补刀
        targets = [
            {"name": "用户1", "message": "消息1"},
            {"name": "用户2", "message": "消息2"},
        ]
        batch_result = await executor.execute_batch(targets)

        await executor.disconnect()
    """

    # 屏幕坐标常量（基于1080x2400分辨率，会根据实际屏幕动态调整）
    SEARCH_ICON_X_RATIO = 0.82  # 搜索图标在屏幕宽度的 82% 位置
    SEARCH_ICON_Y_RATIO = 0.055  # 搜索图标在屏幕高度的 5.5% 位置
    # 搜索按钮 resourceId（来自 UI tree：com.tencent.wework:id/ngq）
    SEARCH_ICON_RESOURCE_ID = "com.tencent.wework:id/ngq"

    # ==================== 图片触发关键词 ====================
    # 当 AI 回复包含这些关键词时，发送消息后自动追加发送收藏中的图片
    IMAGE_TRIGGER_KEYWORDS: list[str] = [
        "收入构成图",
    ]
    # 收藏项索引 - 发送 Favorites 中第几个图片（0 = 第一个）
    IMAGE_FAVORITE_INDEX: int = 0

    def __init__(
        self,
        device_serial: str,
        adb: AdbTools | None = None,
        log_callback: Callable[[str, str], None] | None = None,
    ):
        """
        初始化补刀执行器

        Args:
            device_serial: 设备序列号
            adb: 可选的 AdbTools 实例（如果不传入会自动创建）
            log_callback: 日志回调函数 (message, level) -> None
        """
        self.device_serial = device_serial
        self._adb = adb
        self._owns_adb = adb is None  # 是否自己创建的 adb 实例
        self._log_callback = log_callback
        self._connected = False

        # 屏幕尺寸
        self.screen_width = 1080
        self.screen_height = 2400

    def _log(self, msg: str, level: str = "INFO"):
        """记录日志"""
        timestamp = time.strftime("%H:%M:%S")
        full_msg = f"[{timestamp}] [{level}] [Followup] [{self.device_serial}] {msg}"

        if level == "ERROR":
            logger.error(f"[{self.device_serial}] {msg}")
        elif level == "WARN":
            logger.warning(f"[{self.device_serial}] {msg}")
        elif level == "DEBUG":
            logger.debug(f"[{self.device_serial}] {msg}")
        else:
            logger.info(f"[{self.device_serial}] {msg}")

        if self._log_callback:
            try:
                self._log_callback(msg, level)
            except Exception:
                pass

    @property
    def adb(self) -> AdbTools:
        """获取 AdbTools 实例"""
        if self._adb is None:
            raise RuntimeError("FollowupExecutor not connected. Call connect() first.")
        return self._adb

    async def connect(self) -> bool:
        """
        连接设备

        Returns:
            是否连接成功
        """
        try:
            self._log("=" * 50)
            self._log("补刀执行器: 开始连接设备")
            self._log("=" * 50)
            self._log(f"  设备序列号: {self.device_serial}")
            self._log(f"  ADB 实例: {'已提供' if self._adb else '需要创建'}")

            if self._adb is None:
                self._log("  创建新的 AdbTools 实例...")
                self._adb = AdbTools(self.device_serial)

            # 获取一次状态来验证连接
            self._log("  验证设备连接状态...")
            await self._adb.get_state()
            self._connected = True
            self._log("✅ 设备连接成功")
            self._log("=" * 50)
            return True

        except Exception as e:
            self._log(f"❌ 连接失败: {e}", "ERROR")
            import traceback

            self._log(f"  错误详情: {traceback.format_exc()}", "DEBUG")
            return False

    async def disconnect(self):
        """断开设备连接"""
        if self._owns_adb and self._adb is not None:
            self._adb = None
        self._connected = False
        self._log("设备已断开")

    # ==================== 基础操作 ====================

    async def _get_screen_size(self) -> tuple[int, int]:
        """获取屏幕尺寸"""
        try:
            tree = getattr(self.adb, "raw_tree_cache", {})
            # 兼容 bounds 和 boundsInScreen 两种格式
            bounds = tree.get("boundsInScreen") or tree.get("bounds") or {}
            if bounds:
                width = bounds.get("right", 0) - bounds.get("left", 0)
                height = bounds.get("bottom", 0) - bounds.get("top", 0)
                if width > 0 and height > 0:
                    self.screen_width = width
                    self.screen_height = height
                    return (width, height)
        except Exception as e:
            self._log(f"获取屏幕尺寸失败: {e}", "WARN")

        return (self.screen_width, self.screen_height)

    async def _tap(self, x: int, y: int, desc: str = ""):
        """点击坐标"""
        self._log(f"点击 ({x}, {y}) {desc}")
        await self.adb.tap_by_coordinates(x, y)
        await asyncio.sleep(0.5)

    async def _tap_by_index(self, index: int, desc: str = ""):
        """通过索引点击元素"""
        self._log(f"点击元素 index={index} {desc}")
        await self.adb.tap(index)
        await asyncio.sleep(0.5)

    async def _input_text(self, text: str):
        """输入文本"""
        self._log(f"输入: {text}")
        await self.adb.input_text(text)
        await asyncio.sleep(0.3)

    async def _press_back(self):
        """按返回键"""
        await self.adb.press_key(4)  # KEYCODE_BACK = 4
        await asyncio.sleep(0.5)

    async def _press_enter(self):
        """按回车键"""
        await self.adb.press_key(66)  # KEYCODE_ENTER = 66
        await asyncio.sleep(0.5)

    async def _refresh_ui(self) -> dict:
        """刷新 UI 树"""
        await self.adb.get_state()
        return getattr(self.adb, "raw_tree_cache", {})

    def _get_clickable_elements(self) -> list[dict]:
        """获取可点击元素列表"""
        return getattr(self.adb, "clickable_elements_cache", [])

    # ==================== UI 元素查找 ====================

    def _find_elements_by_text(self, tree: dict, keywords: list[str]) -> list[dict]:
        """在 UI 树中查找包含关键词的元素"""
        results = []

        def traverse(node: dict, depth: int = 0):
            if depth > 30:
                return

            text = str(node.get("text", "")).lower()
            desc = str(node.get("contentDescription", "")).lower()
            res_id = str(node.get("resourceId", "")).lower()

            for kw in keywords:
                kw_lower = kw.lower()
                if kw_lower in text or kw_lower in desc or kw_lower in res_id:
                    bounds = node.get("bounds", {})
                    if bounds and bounds.get("right", 0) > bounds.get("left", 0):
                        results.append(node)
                        return  # 找到就不再遍历子节点

            for child in node.get("children", []):
                traverse(child, depth + 1)

        traverse(tree)
        return results

    def _find_input_field(self, tree: dict) -> dict | None:
        """查找输入框
        
        查找策略（与 test_search_followup.py 一致）：
        1. className 包含 EditText
        2. text/resourceId 包含输入框关键词
        """
        input_hints = ("edittext", "input", "输入", "type", "compose", "说点什么")

        def traverse(node: dict, depth: int = 0) -> dict | None:
            if depth > 30:
                return None

            class_name = str(node.get("class", "") or node.get("className", "")).lower()
            text = str(node.get("text", "")).lower()
            rid = str(node.get("resourceId", "")).lower()

            # 方法1: 检查 className 是否包含 EditText
            if "edittext" in class_name or "edit" in class_name:
                return node

            # 方法2: 检查 text/resourceId 中的关键词
            for hint in input_hints:
                if hint in text or hint in rid:
                    return node

            for child in node.get("children", []):
                result = traverse(child, depth + 1)
                if result:
                    return result
            return None

        return traverse(tree)

    def _find_input_in_clickable(self, elements: list[dict]) -> dict | None:
        """在可点击元素中查找输入框"""
        input_hints = ("edittext", "input", "输入", "type", "compose", "说点什么")

        for element in elements:
            class_name = str(element.get("className", "")).lower()
            text = str(element.get("text", "")).lower()
            rid = str(element.get("resourceId", "")).lower()

            if "edittext" in class_name or "edit" in class_name:
                return element

            for hint in input_hints:
                if hint in text or hint in rid:
                    return element
        return None

    def _find_send_in_clickable(self, elements: list[dict]) -> dict | None:
        """在可点击元素中查找发送按钮"""
        # 优先查找 Button 类型且 text 为 SEND 的元素
        for element in elements:
            cls = str(element.get("className", "")).lower()
            text = str(element.get("text", "")).lower()
            rid = str(element.get("resourceId", "")).lower()

            # 精确匹配：Button + SEND text 或 idf resourceId
            if "button" in cls and ("send" in text or "idf" in rid):
                return element

        # 回退：查找包含发送关键词的元素
        send_hints = ("send", "发送", "idf")
        for element in elements:
            text = str(element.get("text", "")).lower()
            rid = str(element.get("resourceId", "")).lower()
            content_desc = str(element.get("contentDescription", "")).lower()

            for hint in send_hints:
                if hint in text or hint in rid or hint in content_desc:
                    return element
        return None

    def _get_element_center(self, element: dict) -> tuple[int, int]:
        """获取元素中心坐标"""
        # clickable_elements_cache 通常是 bounds；部分 tree dump 可能是 boundsInScreen
        bounds = element.get("bounds") or element.get("boundsInScreen") or {}

        # DroidRun 的 clickable_elements_cache 里 bounds 有时是 "l,t,r,b" 字符串
        if isinstance(bounds, str):
            try:
                l, t, r, b = [int(x.strip()) for x in bounds.split(",")]
                bounds = {"left": l, "top": t, "right": r, "bottom": b}
            except Exception:
                bounds = {}

        x = (bounds.get("left", 0) + bounds.get("right", 0)) // 2
        y = (bounds.get("top", 0) + bounds.get("bottom", 0)) // 2
        return (x, y)

    def _normalize_class_name(self, class_name: str) -> str:
        """把 className 归一化为末段（兼容 'TextView' vs 'android.widget.TextView'）。"""
        value = (class_name or "").strip()
        if "." in value:
            return value.split(".")[-1]
        return value

    def _normalize_match_text(self, value: object) -> str:
        """
        归一化文本用于模糊匹配：
        - 小写
        - 去空格、连字符、下划线
        """
        text = str(value or "").strip().lower()
        return text.replace(" ", "").replace("-", "").replace("_", "")

    def _iter_tree_nodes(self, node: object):
        """递归遍历 UI 树，产出所有 dict 节点。"""
        if isinstance(node, dict):
            yield node
            for child in node.get("children", []) or []:
                yield from self._iter_tree_nodes(child)
        elif isinstance(node, list):
            for item in node:
                yield from self._iter_tree_nodes(item)

    def _score_search_candidate(self, keyword: str, text: str, desc: str, rid: str) -> int:
        """为搜索候选项打分（越高越可能是目标联系人）。"""
        k = self._normalize_match_text(keyword)
        t = self._normalize_match_text(text)
        d = self._normalize_match_text(desc)
        r = self._normalize_match_text(rid)

        score = 0
        if t == k:
            score += 120
        if d == k:
            score += 110
        if k and k in t:
            score += 80
        if k and k in d:
            score += 70
        if k and k in r:
            score += 30
        if t and t in k:
            score += 20
        return score

    def _is_in_search_input_area(self, element: dict, keyword: str) -> bool:
        """
        判断元素是否属于搜索输入框区域（应排除，不作为搜索结果候选）。

        搜索输入框的特征：
        1. 位于屏幕顶部（y < 15% 屏幕高度）
        2. 文本通常是搜索关键词本身（用户刚输入的）
        3. 可能是 EditText 或可编辑元素
        """
        x, y = self._get_element_center(element)

        # 条件1: 不在顶部区域就不是搜索框
        top_threshold = int(self.screen_height * 0.15)
        if not y or y >= top_threshold:
            return False

        # 条件2: 检查是否是可编辑输入框
        is_editable = element.get("isEditable") or element.get("editable")
        class_name = (element.get("className") or "").lower()
        if is_editable or "edittext" in class_name:
            return True

        # 条件3: 顶部区域且文本精确匹配关键词 → 几乎确定是搜索框中回显的文字
        text = self._normalize_match_text(element.get("text", ""))
        kw = self._normalize_match_text(keyword)
        if text and kw and text == kw:
            return True

        return False

    def _collect_search_result_candidates(self, tree: dict, clickables: list[dict], keyword: str) -> list[dict]:
        """
        从 UI 树 + clickable_elements 采集搜索候选并打分。
        返回: [{"source": "tree|clickable", "element": dict, "score": int}, ...]
        """
        candidates: list[dict] = []

        # 1) UI 树候选
        for node in self._iter_tree_nodes(tree):
            text = str(node.get("text", "") or "")
            desc = str(node.get("contentDescription", "") or "")
            rid = str(node.get("resourceId", "") or "")
            score = self._score_search_candidate(keyword, text, desc, rid)
            if score <= 0:
                continue

            # 排除搜索输入框本身（顶部区域 + 精确匹配关键词 = 搜索框回显文字）
            if self._is_in_search_input_area(node, keyword):
                continue

            candidates.append({"source": "tree", "element": node, "score": score})

        # 2) clickable 候选（可直接点击，优先级更高）
        for el in clickables:
            text = str(el.get("text", "") or "")
            desc = str(el.get("contentDescription", "") or "")
            rid = str(el.get("resourceId", "") or "")
            score = self._score_search_candidate(keyword, text, desc, rid)
            if score <= 0:
                continue

            # 排除搜索输入框本身
            if self._is_in_search_input_area(el, keyword):
                continue

            # 可点击元素加权
            score += 10

            candidates.append({"source": "clickable", "element": el, "score": score})

        candidates.sort(key=lambda item: item["score"], reverse=True)
        return candidates

    def _normalize_search_query(self, name: str) -> str:
        """
        规范化“搜索框输入”的关键词。

        需求场景：
        - 补刀目标名可能带后缀：`B2601300118-(保底正常)` 或 `B2601300118-[正常]`
        - 但搜索框需要输入缩减后的主键：`B2601300118`
        - 名称后跟 `-数字(备注)` 形式：`总是睡不饱呢-1774683390(重复[保底正常])`

        规则：
        1. 若命中 `-(`, `-（`, `-[`, `-【` 形式，取其前半段
        2. 若命中 `name-数字(备注)` 或 `name-数字[备注]` 形式，取 `-数字` 之前的部分
        3. Bxxxxxx-(...) 正则兜底
        4. 否则返回原字符串（strip 后）
        """
        raw = (name or "").strip()
        if not raw:
            return raw

        # 支持半角/全角括号和方括号
        for sep in ("-(", "-（", "-[", "-【"):
            if sep in raw:
                base = raw.split(sep, 1)[0].strip()
                return base or raw

        # name-数字(备注) 或 name-数字[备注] 形式
        # 例如：总是睡不饱呢-1774683390(重复[保底正常])
        m = re.match(r"^(.+?)-\d+\s*[\(（\[【].*$", raw)
        if m:
            base = m.group(1).strip()
            return base or raw

        # 再兜底：Bxxxxxx-(...) 或 Bxxxxxx-[...] 形式（更严格的正则）
        m = re.match(r"^(B\d+)-\s*[\(（\[【].*$", raw)
        if m:
            return m.group(1)

        return raw

    def _find_clickable_by_resource_id(
        self,
        elements: list[dict],
        resource_id: str,
        class_name: str | None = None,
    ) -> dict | None:
        """
        从 clickable_elements_cache 中按 resourceId 精确匹配元素。

        优先用于搜索按钮：这种 icon 在 UI tree 里经常没有 text/desc，
        但 clickable cache 里通常能稳定拿到 resourceId + index。
        """
        expected_cls = self._normalize_class_name(class_name or "") if class_name else ""

        for el in elements:
            rid = str(el.get("resourceId", "") or "")
            cls = str(el.get("className", "") or "")
            # clickable_elements_cache 本身就是“可点击元素集合”，很多情况下不会再提供 clickability 字段
            clickable = el.get("clickable", el.get("isClickable"))
            if clickable is not None and not bool(clickable):
                continue

            if rid != resource_id:
                continue

            if expected_cls:
                actual_cls = self._normalize_class_name(cls)
                if actual_cls != expected_cls:
                    continue

            # 优先用 index 点击；如果有 index，就不强制要求 bounds
            if el.get("index") is not None:
                return el

            # 没 index 时才依赖 bounds 做坐标兜底
            bounds = el.get("bounds") or el.get("boundsInScreen") or {}
            if isinstance(bounds, str):
                try:
                    l, t, r, b = [int(x.strip()) for x in bounds.split(",")]
                    bounds = {"left": l, "top": t, "right": r, "bottom": b}
                except Exception:
                    bounds = {}
            if not isinstance(bounds, dict) or bounds.get("right", 0) <= bounds.get("left", 0):
                continue
            return el

        # className 可能在不同版本不一致，允许只按 rid 回退一次
        if expected_cls:
            for el in elements:
                rid = str(el.get("resourceId", "") or "")
                clickable = el.get("clickable", el.get("isClickable"))
                if clickable is not None and not bool(clickable):
                    continue
                if rid != resource_id:
                    continue

                if el.get("index") is not None:
                    return el

                bounds = el.get("bounds") or el.get("boundsInScreen") or {}
                if isinstance(bounds, str):
                    try:
                        l, t, r, b = [int(x.strip()) for x in bounds.split(",")]
                        bounds = {"left": l, "top": t, "right": r, "bottom": b}
                    except Exception:
                        bounds = {}
                if not isinstance(bounds, dict) or bounds.get("right", 0) <= bounds.get("left", 0):
                    continue
                return el

        return None

    async def _find_search_button_method0(self, refresh_ui: bool = True) -> dict | None:
        """
        方法0：通过 resourceId 在 clickable_elements_cache 中定位搜索按钮。

        这是目前最稳定的方式：搜索按钮在 UI tree 里经常没有 text/desc，
        但 clickable_elements_cache 里通常能稳定提供 resourceId + index。

        Args:
            refresh_ui: 是否先调用 get_state 刷新缓存（建议 True）

        Returns:
            匹配到的元素 dict；未找到返回 None
        """
        if refresh_ui:
            await self._refresh_ui()

        elements = self._get_clickable_elements()
        return self._find_clickable_by_resource_id(
            elements,
            self.SEARCH_ICON_RESOURCE_ID,
            # NOTE: clickable_elements_cache 的 className 在不同版本里可能是 "TextView"
            # 或 "android.widget.TextView"，这里让匹配逻辑做归一化处理。
            class_name="android.widget.TextView",
        )

    # ==================== 核心步骤 ====================

    async def _step1_click_search(self) -> bool:
        """步骤1: 点击搜索图标"""
        self._log("")
        self._log("┌" + "─" * 48 + "┐")
        self._log("│ 步骤1: 点击搜索图标                              │")
        self._log("└" + "─" * 48 + "┘")

        # 先刷新 UI，保证 raw_tree_cache/clickable_elements_cache 是最新的
        tree = await self._refresh_ui()
        await self._get_screen_size()
        self._log(f"  屏幕尺寸: {self.screen_width}x{self.screen_height}")

        # 方法0（新增/优先）：按 resourceId 在 clickable cache 里找搜索按钮（最稳定）
        self._log(f"  方法0: 按 resourceId 查找搜索按钮: {self.SEARCH_ICON_RESOURCE_ID}")
        el = await self._find_search_button_method0(refresh_ui=False)
        if el:
            idx = el.get("index")
            bounds = el.get("bounds") or el.get("boundsInScreen") or {}
            x, y = self._get_element_center(el)
            self._log("  ✅ 找到搜索按钮(resourceId):")
            self._log(f"     - index: {idx}")
            self._log(f"     - bounds: {bounds}")
            self._log(f"     - center: ({x}, {y})")
            if idx is not None:
                await self._tap_by_index(int(idx), "搜索按钮(resourceId/index)")
            else:
                await self._tap(int(x), int(y), "搜索按钮(resourceId/bounds)")
            await asyncio.sleep(1)
            return True

        # 方法1: 尝试通过 UI 树找搜索图标
        self._log("  方法1: 尝试通过 UI 树查找搜索图标...")
        search_elements = self._find_elements_by_text(tree, ["search", "搜索", "Search"])

        if search_elements:
            element = search_elements[0]
            x, y = self._get_element_center(element)
            bounds = element.get("bounds", {})
            self._log("  ✅ 找到搜索元素:")
            self._log(f"     - 位置: ({x}, {y})")
            self._log(f"     - bounds: {bounds}")
            self._log(f"     - text: {element.get('text', '')}")
            self._log(f"     - resourceId: {element.get('resourceId', '')}")
            await self._tap(x, y, "搜索元素")
            await asyncio.sleep(1)
            return True

        # 方法2: 使用坐标点击右上角搜索图标
        self._log("  方法2: 未找到搜索元素，使用坐标点击...")
        x = int(self.screen_width * self.SEARCH_ICON_X_RATIO)
        y = int(self.screen_height * self.SEARCH_ICON_Y_RATIO)
        self._log(f"  计算坐标: ({x}, {y})")
        self._log(f"     - X比例: {self.SEARCH_ICON_X_RATIO} × {self.screen_width} = {x}")
        self._log(f"     - Y比例: {self.SEARCH_ICON_Y_RATIO} × {self.screen_height} = {y}")
        await self._tap(x, y, "右上角搜索图标区域")
        await asyncio.sleep(1)
        return True

    async def _step2_input_search(self, query: str) -> bool:
        """步骤2: 输入搜索关键词
        
        关键改进：即使找不到输入框也会尝试直接输入，
        因为搜索页面通常自动聚焦到搜索框
        """
        self._log("")
        self._log("┌" + "─" * 48 + "┐")
        self._log("│ 步骤2: 输入搜索关键词                            │")
        self._log("└" + "─" * 48 + "┘")
        normalized = self._normalize_search_query(query)
        if normalized != (query or "").strip():
            self._log(f"  搜索关键词: [{query}] -> 规范化为 [{normalized}]")
        else:
            self._log(f"  搜索关键词: [{normalized}]")

        tree = await self._refresh_ui()

        # 查找输入框
        self._log("  查找输入框...")
        input_field = self._find_input_field(tree)
        if input_field:
            x, y = self._get_element_center(input_field)
            bounds = input_field.get("bounds", {})
            class_name = input_field.get("class", input_field.get("className", ""))
            is_editable = input_field.get("isEditable", input_field.get("editable", False))
            self._log("  ✅ 找到输入框:")
            self._log(f"     - 位置: ({x}, {y})")
            self._log(f"     - bounds: {bounds}")
            self._log(f"     - className: {class_name}")
            self._log(f"     - isEditable: {is_editable}")
            await self._tap(x, y, "输入框")
            await asyncio.sleep(0.5)
        else:
            # 即使找不到输入框，搜索页面通常已自动聚焦，直接输入即可
            self._log("  ⚠️ 未找到输入框UI元素，但搜索页面通常自动聚焦，继续输入...")

        # 输入文本（无论是否找到输入框都尝试输入）
        self._log(f"  输入文本: {normalized}")
        await self._input_text(normalized)
        await asyncio.sleep(1)
        self._log("  ✅ 搜索关键词输入完成")
        return True

    async def _step3_click_result(self, target_name: str) -> bool:
        """步骤3: 点击搜索结果"""
        self._log("")
        self._log("┌" + "─" * 48 + "┐")
        self._log("│ 步骤3: 点击搜索结果                              │")
        self._log("└" + "─" * 48 + "┘")
        normalized = self._normalize_search_query(target_name)
        if normalized != (target_name or "").strip():
            self._log(f"  目标联系人: [{target_name}] -> 规范化为 [{normalized}]")
        else:
            self._log(f"  目标联系人: [{normalized}]")

        # 等待搜索结果加载
        self._log("  等待搜索结果加载 (1.5s)...")
        await asyncio.sleep(1.5)
        tree = await self._refresh_ui()
        clickables = self._get_clickable_elements()

        self._log(f"  在 UI 树 + clickable 中查找 [{normalized}]...")
        self._log(f"  诊断: clickable 元素数量 = {len(clickables)}", "DEBUG")
        candidates = self._collect_search_result_candidates(tree, clickables, normalized)
        self._log(f"  诊断: 候选结果数量 = {len(candidates)}", "DEBUG")

        # 打印前几个候选，便于线上定位“明明存在却匹配不到”的问题
        for i, item in enumerate(candidates[:8], 1):
            el = item["element"]
            self._log(
                f"    [{i}] src={item['source']} score={item['score']} "
                f"text={str(el.get('text', ''))[:40]!r} "
                f"desc={str(el.get('contentDescription', ''))[:30]!r} "
                f"rid={str(el.get('resourceId', ''))[-40:]!r}",
                "DEBUG",
            )

        if candidates:
            best = candidates[0]
            element = best["element"]
            source = best["source"]
            index = element.get("index")
            x, y = self._get_element_center(element)

            self._log("  ✅ 选择最佳候选:")
            self._log(f"     - source: {source}")
            self._log(f"     - score: {best['score']}")
            self._log(f"     - index: {index}")
            self._log(f"     - center: ({x}, {y})")
            self._log(f"     - text: {element.get('text', '')}")
            self._log(f"     - contentDescription: {element.get('contentDescription', '')}")

            if source == "clickable" and index is not None:
                await self._tap_by_index(int(index), f"搜索结果: {normalized}")
            else:
                await self._tap(x, y, f"搜索结果: {normalized}")
            await asyncio.sleep(1.5)
            return True

        self._log(f"  ⚠️ 未找到匹配联系人 [{normalized}]，判定为搜索无结果", "WARN")
        raise SearchTargetNotFoundError(f"搜索无结果: {normalized}")

    async def _step4_send_message(self, message: str) -> bool:
        """步骤4: 发送消息"""
        self._log("")
        self._log("┌" + "─" * 48 + "┐")
        self._log("│ 步骤4: 发送消息                                  │")
        self._log("└" + "─" * 48 + "┘")
        self._log(f"  消息内容: [{message[:50]}{'...' if len(message) > 50 else ''}]")
        self._log(f"  消息长度: {len(message)} 字符")

        # 刷新 UI 并获取可点击元素
        self._log("  刷新 UI 并获取可点击元素...")
        await self._refresh_ui()
        elements = self._get_clickable_elements()
        self._log(f"  找到 {len(elements)} 个可点击元素")

        # 在可点击元素中查找输入框
        self._log("  查找聊天输入框...")
        input_field = self._find_input_in_clickable(elements)
        if input_field:
            index = input_field.get("index")
            bounds = input_field.get("bounds", {})
            class_name = input_field.get("className", "")
            text = input_field.get("text", "")
            self._log("  ✅ 找到输入框:")
            self._log(f"     - index: {index}")
            self._log(f"     - className: {class_name}")
            self._log(f"     - text: {text[:30] if text else '(空)'}")
            self._log(f"     - bounds: {bounds}")

            if index is not None:
                self._log(f"  使用 index={index} 点击输入框")
                await self._tap_by_index(index, "输入框")
            else:
                x, y = self._get_element_center(input_field)
                self._log(f"  使用坐标 ({x}, {y}) 点击输入框")
                await self._tap(x, y, "输入框(bounds)")
        else:
            self._log("  ⚠️ 未找到输入框，尝试坐标点击", "WARN")
            y = int(self.screen_height * 0.965)
            x = int(self.screen_width * 0.30)
            self._log(f"  回退坐标: ({x}, {y})")
            self._log(f"     - Y = 屏幕高度 96.5% = {self.screen_height} × 0.965 = {y}")
            self._log(f"     - X = 屏幕宽度 30% = {self.screen_width} × 0.30 = {x}")
            await self._tap(x, y, "底部输入框区域")

        await asyncio.sleep(0.5)

        # 输入消息
        self._log("  输入消息文本...")
        await self._input_text(message)
        self._log("  ✅ 消息文本已输入")
        await asyncio.sleep(0.5)

        # 刷新 UI 查找发送按钮
        self._log("  刷新 UI 并查找发送按钮...")
        await self._refresh_ui()
        elements = self._get_clickable_elements()
        self._log(f"  当前 {len(elements)} 个可点击元素")

        send_button = self._find_send_in_clickable(elements)

        if send_button:
            index = send_button.get("index")
            bounds = send_button.get("bounds", {})
            text = send_button.get("text", "")
            rid = send_button.get("resourceId", "")
            class_name = send_button.get("className", "")
            self._log("  ✅ 找到发送按钮:")
            self._log(f"     - index: {index}")
            self._log(f"     - text: {text}")
            self._log(f"     - resourceId: {rid}")
            self._log(f"     - className: {class_name}")
            self._log(f"     - bounds: {bounds}")

            if index is not None:
                self._log(f"  使用 index={index} 点击发送按钮")
                await self._tap_by_index(index, "发送按钮")
            else:
                x, y = self._get_element_center(send_button)
                self._log(f"  使用坐标 ({x}, {y}) 点击发送按钮")
                await self._tap(x, y, "发送按钮(bounds)")
        else:
            # 回退方案：按回车键发送
            self._log("  ⚠️ 未找到发送按钮，使用回车键发送", "WARN")
            self._log("  按下 KEYCODE_ENTER (66)...")
            await self._press_enter()

        await asyncio.sleep(1)
        self._log("  ✅ 消息发送步骤完成")
        return True

    def _should_trigger_image(self, message: str) -> bool:
        """检查消息是否包含图片触发关键词"""
        if not self.IMAGE_TRIGGER_KEYWORDS or not message:
            return False
        for keyword in self.IMAGE_TRIGGER_KEYWORDS:
            if keyword and keyword in message:
                self._log(f"  🖼️ 检测到图片触发关键词: '{keyword}'")
                return True
        return False

    async def _step4b_send_image(self) -> bool:
        """步骤4b: 发送收藏图片（在消息发送后、返回前执行）"""
        self._log("")
        self._log("┌" + "─" * 48 + "┐")
        self._log("│ 步骤4b: 追加发送收藏图片                        │")
        self._log("└" + "─" * 48 + "┘")

        try:
            from wecom_automation.services.message.image_sender import ImageSender

            # 创建轻量级适配器，让 ImageSender 可以工作
            class _WeComAdapter:
                def __init__(adapter_self, adb, stabilization_delay=1.0):
                    adapter_self.adb = adb
                    adapter_self.config = type(
                        "Config", (), {
                            "timing": type("Timing", (), {
                                "ui_stabilization_delay": stabilization_delay,
                            })(),
                        }
                    )()

            adapter = _WeComAdapter(self.adb)
            sender = ImageSender(adapter)

            # 等待上一条文本消息发送完成
            self._log(f"  等待文本消息发送完成 (1.5s)...")
            await asyncio.sleep(1.5)

            self._log(f"  发送收藏图片 (index={self.IMAGE_FAVORITE_INDEX})...")
            success = await sender.send_via_favorites(
                favorite_index=self.IMAGE_FAVORITE_INDEX
            )

            if success:
                self._log("  ✅ 收藏图片发送成功")
            else:
                self._log("  ⚠️ 收藏图片发送失败（不影响补刀结果）", "WARN")

            return success

        except Exception as e:
            self._log(f"  ⚠️ 发送收藏图片异常: {e}（不影响补刀结果）", "WARN")
            return False

    async def _step5_go_back(self) -> bool:
        """步骤5: 返回消息列表"""
        self._log("")
        self._log("┌" + "─" * 48 + "┐")
        self._log("│ 步骤5: 返回消息列表                              │")
        self._log("└" + "─" * 48 + "┘")

        # 第1次返回 - 取消输入状态（关闭键盘）
        self._log("  第1次返回: 关闭键盘/取消输入状态")
        await self._press_back()
        await asyncio.sleep(0.5)

        # 第2次返回 - 从聊天页面退回到搜索页
        self._log("  第2次返回: 从聊天页面退回到搜索页")
        await self._press_back()
        await asyncio.sleep(0.5)

        # 第3次返回 - 从搜索页回到主菜单
        self._log("  第3次返回: 从搜索页回到主菜单")
        await self._press_back()
        await asyncio.sleep(0.5)

        self._log("  ✅ 已返回消息列表")
        return True

    # ==================== 公开 API ====================

    async def execute(
        self,
        target_name: str,
        message: str,
        skip_check: Callable[[], bool] | None = None,
    ) -> FollowupResult:
        """
        对单个用户执行补刀

        Args:
            target_name: 目标联系人名称
            message: 补刀消息
            skip_check: 可选的中断检查函数，返回 True 则跳过

        Returns:
            FollowupResult 执行结果
        """
        start_time = time.time()

        try:
            self._log("")
            self._log("╔" + "═" * 58 + "╗")
            self._log("║                    补刀任务开始                          ║")
            self._log("╠" + "═" * 58 + "╣")
            self._log(f"║  目标联系人: {target_name[:40]:<44}║")
            self._log(f"║  消息内容: {message[:42]:<46}║")
            self._log(f"║  消息长度: {len(message):<47}║")
            self._log("╚" + "═" * 58 + "╝")

            # 检查是否需要跳过
            if skip_check and skip_check():
                self._log(f"⏭️ 收到跳过信号，跳过 {target_name}")
                return FollowupResult(
                    target_name=target_name,
                    status=FollowupStatus.SKIPPED,
                    error="Skip requested",
                    duration_ms=int((time.time() - start_time) * 1000),
                )

            # 步骤1: 点击搜索
            step1_start = time.time()
            if not await self._step1_click_search():
                raise Exception("步骤1失败: 点击搜索")
            self._log(f"  步骤1耗时: {(time.time() - step1_start) * 1000:.0f}ms")

            if skip_check and skip_check():
                self._log("⏭️ 步骤1后收到跳过信号")
                await self._safe_go_back()
                return FollowupResult(
                    target_name=target_name,
                    status=FollowupStatus.SKIPPED,
                    duration_ms=int((time.time() - start_time) * 1000),
                )

            # 步骤2: 输入搜索
            step2_start = time.time()
            if not await self._step2_input_search(target_name):
                raise Exception("步骤2失败: 输入搜索")
            self._log(f"  步骤2耗时: {(time.time() - step2_start) * 1000:.0f}ms")

            # 步骤3: 点击结果
            step3_start = time.time()
            if not await self._step3_click_result(target_name):
                raise Exception("步骤3失败: 点击结果")
            self._log(f"  步骤3耗时: {(time.time() - step3_start) * 1000:.0f}ms")

            if skip_check and skip_check():
                self._log("⏭️ 步骤3后收到跳过信号")
                await self._safe_go_back()
                return FollowupResult(
                    target_name=target_name,
                    status=FollowupStatus.SKIPPED,
                    duration_ms=int((time.time() - start_time) * 1000),
                )

            # 步骤4: 发送消息
            step4_start = time.time()
            if not await self._step4_send_message(message):
                raise Exception("步骤4失败: 发送消息")
            self._log(f"  步骤4耗时: {(time.time() - step4_start) * 1000:.0f}ms")

            # 步骤4b: 检测是否需要追加发送图片
            if self._should_trigger_image(message):
                step4b_start = time.time()
                await self._step4b_send_image()
                self._log(f"  步骤4b耗时: {(time.time() - step4b_start) * 1000:.0f}ms")

            # 步骤5: 返回
            step5_start = time.time()
            if not await self._step5_go_back():
                raise Exception("步骤5失败: 返回")
            self._log(f"  步骤5耗时: {(time.time() - step5_start) * 1000:.0f}ms")

            duration_ms = int((time.time() - start_time) * 1000)
            self._log("")
            self._log("╔" + "═" * 58 + "╗")
            self._log("║                  ✅ 补刀任务完成                         ║")
            self._log("╠" + "═" * 58 + "╣")
            self._log(f"║  目标: {target_name[:48]:<50}║")
            self._log(f"║  总耗时: {duration_ms}ms{' ' * (47 - len(str(duration_ms)))}║")
            self._log("╚" + "═" * 58 + "╝")

            return FollowupResult(
                target_name=target_name,
                status=FollowupStatus.SUCCESS,
                message_sent=message,
                duration_ms=duration_ms,
            )

        except SearchTargetNotFoundError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            self._log("")
            self._log("╔" + "═" * 58 + "╗")
            self._log("║                ⚠️ 搜索无结果，已安全返回                 ║")
            self._log("╠" + "═" * 58 + "╣")
            self._log(f"║  目标: {target_name[:48]:<50}║")
            self._log(f"║  原因: {str(e)[:48]:<50}║")
            self._log(f"║  耗时: {duration_ms}ms{' ' * (49 - len(str(duration_ms)))}║")
            self._log("╚" + "═" * 58 + "╝")

            # 搜索无结果时只返回一次，避免多次返回导致退出应用
            self._log("搜索无结果，执行单次返回以退出搜索页...")
            await self._safe_go_back(max_presses=1)

            return FollowupResult(
                target_name=target_name,
                status=FollowupStatus.FAILED,
                error=str(e),
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            self._log("")
            self._log("╔" + "═" * 58 + "╗")
            self._log("║                  ❌ 补刀任务失败                         ║")
            self._log("╠" + "═" * 58 + "╣")
            self._log(f"║  目标: {target_name[:48]:<50}║")
            self._log(f"║  错误: {str(e)[:48]:<50}║")
            self._log(f"║  耗时: {duration_ms}ms{' ' * (49 - len(str(duration_ms)))}║")
            self._log("╚" + "═" * 58 + "╝")

            import traceback

            self._log(f"错误详情: {traceback.format_exc()}", "DEBUG")

            # 尝试返回主界面
            self._log("尝试安全返回主界面...")
            await self._safe_go_back()

            return FollowupResult(
                target_name=target_name,
                status=FollowupStatus.FAILED,
                error=str(e),
                duration_ms=duration_ms,
            )

    async def _safe_go_back(self, max_presses: int = 3):
        """安全返回主界面"""
        try:
            presses = max(1, max_presses)
            for _ in range(presses):
                await self._press_back()
                await asyncio.sleep(0.3)

                # 兜底：部分 ROM 下 KEYCODE_BACK 不生效，尝试点击左上角返回按钮
                tree = await self._refresh_ui()
                clickables = self._get_clickable_elements()
                top_left_back_candidates: list[dict] = []
                x_limit = max(220, int(self.screen_width * 0.25))
                y_limit = max(360, int(self.screen_height * 0.2))

                for el in clickables:
                    text = str(el.get("text", "")).lower()
                    desc = str(el.get("contentDescription", "")).lower()
                    rid = str(el.get("resourceId", "")).lower()
                    cls = str(el.get("className", "")).lower()
                    x, y = self._get_element_center(el)

                    if x > x_limit or y > y_limit:
                        continue

                    if (
                        "返回" in text
                        or "返回" in desc
                        or "back" in text
                        or "back" in desc
                        or "navigate" in rid
                        or "back" in rid
                        or "imagebutton" in cls
                        or "imageview" in cls
                    ):
                        top_left_back_candidates.append(el)

                if top_left_back_candidates:
                    cand = top_left_back_candidates[0]
                    idx = cand.get("index")
                    x, y = self._get_element_center(cand)
                    self._log(
                        f"  BACK兜底: 点击顶部返回候选 index={idx}, center=({x}, {y})",
                        "DEBUG",
                    )
                    if idx is not None:
                        await self._tap_by_index(int(idx), "返回按钮兜底")
                    else:
                        await self._tap(int(x), int(y), "返回按钮兜底")
                await asyncio.sleep(0.3)
        except Exception:
            pass

    async def execute_batch(
        self,
        targets: list[dict[str, str]],
        skip_check: Callable[[], bool] | None = None,
        delay_between: float = 1.0,
    ) -> BatchFollowupResult:
        """
        批量补刀多个用户

        Args:
            targets: 目标用户列表，每个元素为 {"name": "用户名", "message": "消息内容"}
            skip_check: 可选的中断检查函数
            delay_between: 每个用户之间的延迟（秒）

        Returns:
            BatchFollowupResult 批量执行结果
        """
        result = BatchFollowupResult(total=len(targets))
        batch_start_time = time.time()

        self._log("")
        self._log("█" * 60)
        self._log("█                   批量补刀任务开始                       █")
        self._log("█" * 60)
        self._log(f"  目标用户数: {len(targets)}")
        self._log(f"  用户间延迟: {delay_between}s")
        self._log("  目标列表:")
        for i, target in enumerate(targets, 1):
            name = target.get("name", "(无名)")
            msg = target.get("message", "")[:30]
            self._log(f"    {i}. {name} - {msg}...")
        self._log("─" * 60)

        for i, target in enumerate(targets, 1):
            name = target.get("name", "")
            message = target.get("message", "你好，请问考虑得怎么样了？")

            if not name:
                self._log(f"  [{i}/{len(targets)}] ⚠️ 跳过: 用户名为空")
                continue

            self._log("")
            self._log("  ┌───────────────────────────────────────────────────────┐")
            self._log(f"  │ [{i}/{len(targets)}] 处理: {name[:40]:<41}│")
            self._log("  └───────────────────────────────────────────────────────┘")

            # 检查是否需要中断整个批次
            if skip_check and skip_check():
                self._log("  ⛔ 收到中断信号，停止批量补刀")
                remaining_count = len(targets) - i + 1
                self._log(f"  标记剩余 {remaining_count} 个用户为跳过状态")
                # 标记剩余用户为跳过
                for remaining in targets[i - 1 :]:
                    result.skipped += 1
                    result.results.append(
                        FollowupResult(
                            target_name=remaining.get("name", ""),
                            status=FollowupStatus.SKIPPED,
                        )
                    )
                break

            followup_result = await self.execute(name, message, skip_check)
            result.results.append(followup_result)

            if followup_result.status == FollowupStatus.SUCCESS:
                result.success += 1
                self._log(f"  ✅ [{i}/{len(targets)}] {name} - 成功 ({followup_result.duration_ms}ms)")
            elif followup_result.status == FollowupStatus.FAILED:
                result.failed += 1
                self._log(f"  ❌ [{i}/{len(targets)}] {name} - 失败: {followup_result.error}")
            elif followup_result.status == FollowupStatus.SKIPPED:
                result.skipped += 1
                self._log(f"  ⏭️ [{i}/{len(targets)}] {name} - 跳过")

            # 用户之间的延迟
            if i < len(targets):
                self._log(f"  等待 {delay_between}s 后处理下一个用户...")
                await asyncio.sleep(delay_between)

        batch_duration = time.time() - batch_start_time
        self._log("")
        self._log("█" * 60)
        self._log("█                   批量补刀任务完成                       █")
        self._log("█" * 60)
        self._log(f"  总计: {result.total} | 成功: {result.success} | 失败: {result.failed} | 跳过: {result.skipped}")
        self._log(f"  成功率: {result.success_rate * 100:.1f}%")
        self._log(f"  总耗时: {batch_duration:.1f}s")
        self._log("█" * 60)

        return result

