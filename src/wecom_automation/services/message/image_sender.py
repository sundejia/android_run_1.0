"""
图片发送服务 - 通过 Favorites 发送图片

这是一个通用的图片发送模块，支持通过企业微信的 Favorites 功能发送收藏的图片。

特性:
- 动态查找 UI 元素，不依赖硬编码坐标
- 支持不同屏幕分辨率
- 支持不同 WeCom 版本
- 完整的错误处理
- 支持选择不同的收藏项索引

使用方法:
    from wecom_automation.services.message.image_sender import ImageSender

    # 在已有的 WeComService 实例中使用
    sender = ImageSender(wecom_service)
    success = await sender.send_via_favorites(favorite_index=0)

作者: Claude Sonnet 4.5
日期: 2026-02-06
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from wecom_automation.core.exceptions import WeComAutomationError
from wecom_automation.core.logging import get_logger, log_operation


@dataclass
class UIElement:
    """UI 元素封装"""

    index: int | None
    resource_id: str
    text: str
    bounds: str
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, elem: dict[str, Any]) -> UIElement:
        """从字典创建 UIElement"""
        return cls(
            index=elem.get("index"),
            resource_id=elem.get("resourceId", ""),
            text=elem.get("text", ""),
            bounds=elem.get("bounds", ""),
            raw=elem,
        )

    def get_center(self) -> tuple[int, int] | None:
        """获取元素中心点坐标"""
        if not self.bounds:
            return None

        try:
            parts = self.bounds.split(",")
            x1, y1, x2, y2 = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
            center_x = (x1 + x2) // 2
            center_y = (y1 + y2) // 2
            return (center_x, center_y)
        except (ValueError, IndexError):
            return None


class ElementNotFoundError(WeComAutomationError):
    """元素未找到异常"""

    pass


class ImageSender:
    """
    通用图片发送服务

    通过 Favorites 功能发送图片，支持不同设备

    使用方法:
        sender = ImageSender(wecom_service)
        success = await sender.send_via_favorites(favorite_index=0)

    注意:
        - 调用前必须确保已进入对话界面
        - 确保 Favorites 中已有收藏的图片
        - favorite_index 从 0 开始计数
    """

    def __init__(self, wecom_service):
        """
        初始化图片发送器

        Args:
            wecom_service: WeComService 实例
        """
        self.wecom = wecom_service
        self.adb = wecom_service.adb
        self.logger = get_logger("wecom_automation.image_sender")
        self._element_cache: dict[str, UIElement] = {}

    async def send_via_favorites(self, favorite_index: int = 0) -> bool:
        """
        通过 Favorites 发送图片

        Args:
            favorite_index: 要选择的收藏项索引（默认 0，即第一个）

        Returns:
            是否发送成功

        Raises:
            ElementNotFoundError: 未找到必要的 UI 元素
            Exception: 其他异常
        """
        with log_operation(self.logger, "send_via_favorites"):
            try:
                # 步骤 1: 打开附件菜单
                self.logger.info("Opening attach menu...")
                attach_button = await self._find_attach_button()
                await self._tap_element(attach_button)
                await self.adb.wait(self.wecom.config.timing.ui_stabilization_delay)

                # 步骤 2: 点击 Favorites
                self.logger.info("Opening Favorites...")
                favorites_button = await self._find_favorites_button()
                await self._tap_element(favorites_button)
                await self.adb.wait(2.0)

                # 步骤 3: 选择收藏项
                self.logger.info(f"Selecting favorite item at index {favorite_index}...")
                favorite_item = await self._find_favorite_item(favorite_index)
                await self._tap_element(favorite_item)
                await self.adb.wait(2.0)

                # 步骤 4: 点击发送
                self.logger.info("Sending image...")
                send_button = await self._find_send_button()
                await self._tap_element(send_button)
                await self.adb.wait(2.0)

                self.logger.info("✅ Image sent successfully")
                return True

            except ElementNotFoundError as e:
                self.logger.error(f"❌ Element not found: {e}")
                return False
            except Exception as e:
                self.logger.error(f"❌ Failed to send image: {e}")
                return False

    async def list_favorites(self) -> list[dict[str, Any]]:
        """
        列出所有收藏项（调试用）

        Returns:
            收藏项列表，每项包含 index, resource_id, text, bounds
        """
        try:
            # 打开附件菜单
            attach_button = await self._find_attach_button()
            await self._tap_element(attach_button)
            await self.adb.wait(self.wecom.config.timing.ui_stabilization_delay)

            # 点击 Favorites
            favorites_button = await self._find_favorites_button()
            await self._tap_element(favorites_button)
            await self.adb.wait(2.0)

            # 获取所有收藏项
            _, elements = await self.adb.get_ui_state()
            favorites = []
            for elem in elements:
                rid = elem.get("resourceId", "")
                if "ls1" in rid:
                    favorites.append(
                        {
                            "index": elem.get("index"),
                            "resource_id": rid,
                            "text": elem.get("text", ""),
                            "bounds": elem.get("bounds", ""),
                        }
                    )

            # 关闭菜单
            await self.adb.press_back()
            await self.adb.wait(1.0)

            return favorites

        except Exception as e:
            self.logger.error(f"Failed to list favorites: {e}")
            return []

    # ==================== Private Methods ====================

    async def _find_attach_button(self) -> UIElement:
        """
        查找附件按钮

        策略:
        1. 通过 resource_id 查找（id8，右侧附件按钮）
        2. 通过位置筛选（屏幕右下角，y > 2000）
        """
        _, elements = await self.adb.get_ui_state()

        candidates = []
        for elem in elements:
            rid = elem.get("resourceId", "")
            # 查找 id8（右侧附件按钮）
            if "id8" in rid:
                ui_elem = UIElement.from_dict(elem)
                # 验证位置：应该在底部
                bounds = elem.get("bounds", "")
                if bounds:
                    parts = bounds.split(",")
                    if len(parts) == 4:
                        y = int(parts[1])
                        if y > 2000:  # 在屏幕底部
                            candidates.append(ui_elem)

        if not candidates:
            raise ElementNotFoundError("Attach button (id8) not found. Make sure you're in a chat conversation.")

        self.logger.debug(f"Found attach button at index {candidates[0].index}")
        return candidates[0]

    async def _find_favorites_button(self) -> UIElement:
        """
        查找 Favorites 按钮

        策略:
        1. 通过文本查找 "Favorites"
        2. 通过 resource_id 查找（agb，附件菜单项通用 ID）
        3. 通过位置筛选（屏幕中间偏右，400 < x < 1000, 1200 < y < 2200）
        """
        _, elements = await self.adb.get_ui_state()

        # 方式 1: 通过文本查找
        for elem in elements:
            text = elem.get("text", "").strip()
            if "Favorites" in text or "favorites" in text.lower():
                self.logger.debug(f"Found Favorites by text at index {elem.get('index')}")
                return UIElement.from_dict(elem)

        # 方式 2: 通过位置和 resource_id 查找
        candidates = []
        for elem in elements:
            rid = elem.get("resourceId", "")
            text = elem.get("text", "")

            # agb 是附件菜单项的通用 resource_id
            if "agb" in rid and text:
                ui_elem = UIElement.from_dict(elem)
                # 计算中心点
                center = ui_elem.get_center()
                if center:
                    x, y = center
                    # Favorites 应该在中间偏右位置，相对宽松的范围
                    if 400 < x < 1000 and 1200 < y < 2200:
                        candidates.append((ui_elem, abs(x - 666)))  # 666 是参考位置

        # 选择最接近参考位置的元素
        if candidates:
            candidates.sort(key=lambda x: x[1])
            selected = candidates[0][0]
            self.logger.debug(f"Found Favorites by position at index {selected.index}, text='{selected.text}'")
            return selected

        raise ElementNotFoundError("Favorites button not found. Make sure the attach menu is open.")

    async def _find_favorite_item(self, index: int = 0) -> UIElement:
        """
        查找指定索引的收藏项

        策略:
        1. 查找所有收藏项（resource_id 包含 ls1）
        2. 返回指定索引的项

        Args:
            index: 收藏项索引（0-based）

        Returns:
            UIElement
        """
        _, elements = await self.adb.get_ui_state()

        # 查找所有收藏项
        favorites = []
        for elem in elements:
            rid = elem.get("resourceId", "")
            # ls1 是收藏项的 resource_id
            if "ls1" in rid:
                favorites.append(UIElement.from_dict(elem))

        if not favorites:
            raise ElementNotFoundError("No favorite items found. Please make sure you have favorited some images.")

        if index >= len(favorites):
            self.logger.warning(f"Favorite index {index} out of range (total: {len(favorites)}). Using last item.")
            index = len(favorites) - 1

        self.logger.debug(f"Found favorite item at index {favorites[index].index}")
        return favorites[index]

    async def _find_send_button(self) -> UIElement:
        """
        查找发送按钮

        策略:
        1. 通过文本查找 "Send"（精确匹配）
        2. 通过 resource_id 查找（dbf）
        """
        _, elements = await self.adb.get_ui_state()

        # 方式 1: 通过文本查找（精确匹配）
        for elem in elements:
            text = elem.get("text", "").strip()
            if text == "Send":
                self.logger.debug(f"Found Send button by text at index {elem.get('index')}")
                return UIElement.from_dict(elem)

        # 方式 2: 通过 resource_id 查找
        for elem in elements:
            rid = elem.get("resourceId", "")
            if "dbf" in rid:  # dbf 是 Send 按钮的 resource_id
                self.logger.debug(f"Found Send button by resource_id at index {elem.get('index')}")
                return UIElement.from_dict(elem)

        raise ElementNotFoundError("Send button not found. Make sure the share dialog is open.")

    async def _tap_element(self, elem: UIElement) -> None:
        """
        点击 UI 元素

        优先使用 overlay index，回退到坐标点击

        Args:
            elem: UI 元素
        """
        # 优先使用 overlay index（更可靠）
        if elem.index is not None:
            self.logger.debug(f"Tapping by index: {elem.index}")
            await self.adb.tap(elem.index)
            return

        # 回退到坐标点击
        center = elem.get_center()
        if center:
            x, y = center
            self.logger.debug(f"Tapping by coordinates: ({x}, {y})")
            await self.adb.tap_coordinates(x, y)
            return

        raise ElementNotFoundError(
            f"Cannot tap element: no index or bounds available. Element: {elem.resource_id}, {elem.text}"
        )
