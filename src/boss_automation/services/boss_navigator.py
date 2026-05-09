"""BOSS Zhipin page navigation helper.

Wraps an ``AdbPort`` with tab-aware navigation for the BOSS app's
four-tab bottom bar (牛人 / 搜索 / 消息 / 我的).  Used by
``BossAppService``, ``ReplyDispatcher``, and ``GreetExecutor`` to
guarantee the device is on the right page before interacting with it,
and to navigate back afterward.

Mirrors the ``ensure_on_private_chats`` / ``go_back`` pattern from the
WeCom ``wecom_service.py`` but specialised for the BOSS app layout.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final

from boss_automation.services.adb_port import AdbPort

_LOGGER = logging.getLogger("boss_automation.navigator")

TAB_CANDIDATES: Final[str] = "牛人"
TAB_SEARCH: Final[str] = "搜索"
TAB_MESSAGES: Final[str] = "消息"
TAB_ME_CANDIDATES: Final[tuple[str, ...]] = ("我的", "我")

_MAX_NAVIGATION_RETRIES: Final[int] = 2
_RETRY_SLEEP: Final[float] = 1.5


class BossNavigator:
    """Page-level navigation for the BOSS Zhipin Android app."""

    def __init__(
        self,
        adb: AdbPort,
        *,
        sleep: float = _RETRY_SLEEP,
        logger: logging.Logger | None = None,
    ) -> None:
        self._adb = adb
        self._sleep = sleep
        self._log = logger or _LOGGER

    async def press_back(self) -> None:
        await self._adb.press_back()

    async def navigate_to_tab(self, tab_text: str) -> bool:
        """Tap a bottom tab.  If the tap fails (because the device is
        on a detail page that hides the tab bar), press BACK first then
        retry.  Returns ``True`` if the tap was attempted successfully.
        """
        for attempt in range(_MAX_NAVIGATION_RETRIES):
            tapped = await self._adb.tap_by_text(tab_text)
            if tapped:
                self._log.debug("navigate_to_tab(%r): ok on attempt %d", tab_text, attempt + 1)
                return True
            self._log.debug("navigate_to_tab(%r): tap failed, pressing BACK (attempt %d)", tab_text, attempt + 1)
            await self._adb.press_back()
            await asyncio.sleep(self._sleep)
        self._log.warning("navigate_to_tab(%r): failed after %d attempts", tab_text, _MAX_NAVIGATION_RETRIES)
        return False

    async def navigate_to_me_tab(self) -> bool:
        """Navigate to the Me tab, trying both '我的' and '我'."""
        for candidate in TAB_ME_CANDIDATES:
            if await self.navigate_to_tab(candidate):
                return True
        return False

    async def ensure_on_messages(self) -> bool:
        """Ensure device is on the 消息 (chat list) page."""
        return await self.navigate_to_tab(TAB_MESSAGES)

    async def ensure_on_candidates(self) -> bool:
        """Ensure device is on the 牛人 (candidate recommendation feed)."""
        return await self.navigate_to_tab(TAB_CANDIDATES)
