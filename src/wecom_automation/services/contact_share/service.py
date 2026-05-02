"""
ContactShareService - WeCom UI automation for sharing contact cards (名片).

Provides an abstraction layer over WeComService for sharing a supervisor's
contact card with a customer. Follows the same architecture as GroupChatService:
  - ABC interface for testability
  - SQLite-backed idempotency table
  - Multi-step UI automation with retry logic
  - Navigation restoration in finally blocks

Validated UI flow (WeCom Android):
  1. navigate_to_chat(customer)
  2. tap i9u (rightmost bottom icon) → opens attachment panel
  3. swipe LEFT on GridView (ahe) → reveals page 2
  4. tap "Contact Card" (aha) → opens contact picker (nca/cth)
  5. tap target contact in list → opens confirmation dialog
  6. tap "Send" (dak) → sends card, returns to chat
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from abc import ABC, abstractmethod
from contextlib import contextmanager

from wecom_automation.database.schema import get_db_path
from wecom_automation.services.contact_share import selectors as S
from wecom_automation.services.contact_share.models import (
    ContactShareRequest,
)
from wecom_automation.services.ui_search.ui_helpers import find_elements_by_keywords

logger = logging.getLogger(__name__)

CONTACT_SHARES_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS media_action_contact_shares (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_serial TEXT NOT NULL,
        customer_name TEXT NOT NULL,
        contact_name TEXT NOT NULL,
        kefu_name TEXT DEFAULT '',
        status TEXT DEFAULT 'shared',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""

CONTACT_SHARES_INDEX_SQL = """
    CREATE INDEX IF NOT EXISTS idx_contact_shares_lookup
        ON media_action_contact_shares (device_serial, customer_name, contact_name)
"""


def ensure_contact_shares_table(db_path: str | None = None) -> str:
    """Ensure the media_action_contact_shares tracking table exists."""
    resolved = str(get_db_path(db_path))
    conn = sqlite3.connect(resolved)
    try:
        conn.execute(CONTACT_SHARES_TABLE_SQL)
        conn.execute(CONTACT_SHARES_INDEX_SQL)
        conn.commit()
    finally:
        conn.close()
    return resolved


class IContactShareService(ABC):
    """Interface for contact card sharing operations."""

    @abstractmethod
    async def share_contact_card(self, request: ContactShareRequest) -> bool:
        """Share a contact card with a customer via WeCom UI."""
        ...

    @abstractmethod
    async def contact_already_shared(
        self,
        device_serial: str,
        customer_name: str,
        contact_name: str,
    ) -> bool:
        """Check if we already shared this contact to this customer."""
        ...

    @abstractmethod
    async def restore_navigation(self) -> bool:
        """Navigate back to the private chats list."""
        ...


class ContactShareService(IContactShareService):
    """
    Concrete implementation using WeComService for ADB-based UI automation.

    UI flow (validated on real device):
    1. Navigate to customer chat
    2. Tap attachment button (i9u, rightmost bottom)
    3. Find "Contact Card" — try current page, swipe left if not found
    4. Select target contact from picker via ContactFinderStrategy
    5. Tap "Send" in confirmation dialog
    """

    _MAX_RETRIES = 3
    _STEP_DELAY = 1.0

    def __init__(
        self,
        wecom_service=None,
        db_path: str | None = None,
        contact_finder=None,
    ) -> None:
        self._wecom = wecom_service
        self._db_path = db_path
        self._contact_finder = contact_finder
        self._ensure_table()

    @contextmanager
    def _connection(self):
        if not self._db_path:
            self._db_path = str(get_db_path())
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_table(self) -> None:
        try:
            self._db_path = ensure_contact_shares_table(self._db_path)
        except Exception as exc:
            logger.warning("Failed to ensure contact_shares table: %s", exc)

    # ── Public API ────────────────────────────────────────────────

    async def share_contact_card(self, request: ContactShareRequest) -> bool:
        logger.info(
            "Sharing contact card: device=%s, customer=%s, contact=%s",
            request.device_serial,
            request.customer_name,
            request.contact_name,
        )
        try:
            if self._wecom is None:
                logger.warning("No WeComService available; recording share intent only")
                self._record_share(request)
                return True

            success = await self._perform_ui_share(request)
            if success:
                self._record_share(request)
            return success
        except Exception as exc:
            logger.error("Contact card sharing failed: %s", exc)
            return False

    async def contact_already_shared(
        self,
        device_serial: str,
        customer_name: str,
        contact_name: str,
    ) -> bool:
        try:
            with self._connection() as conn:
                cur = conn.execute(
                    """
                    SELECT 1 FROM media_action_contact_shares
                    WHERE device_serial = ?
                      AND customer_name = ?
                      AND contact_name = ?
                      AND status = 'shared'
                    LIMIT 1
                    """,
                    (device_serial, customer_name, contact_name),
                )
                return cur.fetchone() is not None
        except Exception as exc:
            logger.warning("Failed to check contact share history: %s", exc)
            return False

    async def restore_navigation(self) -> bool:
        if self._wecom is None:
            return False
        try:
            return await self._wecom.ensure_on_private_chats()
        except Exception as exc:
            logger.warning("Failed to restore navigation: %s", exc)
            return False

    # ── UI Automation Steps ───────────────────────────────────────

    async def _perform_ui_share(self, request: ContactShareRequest) -> bool:
        """Execute the multi-step UI automation for contact card sharing."""

        # Step 1: Navigate to customer chat
        if not await self._wecom.navigate_to_chat(request.device_serial, request.customer_name):
            logger.error("Could not navigate to chat for '%s'", request.customer_name)
            return False

        await asyncio.sleep(self._STEP_DELAY)

        # Step 2: Tap attachment button (i9u)
        if not await self._tap_attach_button():
            logger.error("Could not tap attachment button")
            return False

        await asyncio.sleep(self._STEP_DELAY)

        # Step 3: Open Contact Card — adaptive: try current page first, swipe if needed
        if not await self._open_contact_card_menu():
            logger.error("Could not find 'Contact Card' menu item")
            return False

        await asyncio.sleep(self._STEP_DELAY)

        # Step 4: Select the target contact from picker
        if not await self._select_contact_from_picker(request.contact_name):
            logger.error("Could not select contact '%s' in picker", request.contact_name)
            return False

        await asyncio.sleep(self._STEP_DELAY)

        # Step 5: Tap "Send" in confirmation dialog
        if not await self._confirm_send():
            logger.error("Could not confirm contact card send")
            return False

        logger.info("Contact card shared successfully to %s", request.customer_name)
        return True

    async def _tap_attach_button(self) -> bool:
        """Tap the attachment button (i9u, rightmost bottom icon)."""
        return await self._find_and_tap(
            resource_patterns=S.ATTACH_RESOURCE_PATTERNS,
            step_name="attach button (i9u)",
        )

    async def _open_contact_card_menu(self) -> bool:
        """Find and tap 'Contact Card' — tries current page first, swipes if not found.

        WeCom promotes recently-used attachment items to page 1, so after the first
        use 'Contact Card' may appear without swiping.  This method handles both cases.
        """
        # Fast path: try to find Contact Card on the current page
        if await self._tap_contact_card_menu():
            return True

        # Slow path: swipe left on GridView, then try again
        logger.info("Contact Card not on current page; swiping to page 2...")
        if not await self._swipe_attach_grid():
            return False

        await asyncio.sleep(1.0)
        return await self._tap_contact_card_menu()

    async def _swipe_attach_grid(self) -> bool:
        """Swipe left on the GridView (ahe) to reveal the next page."""
        try:
            ui_tree, elements = await self._wecom.adb.get_ui_state(force=True)
        except Exception as exc:
            logger.warning("Failed to get UI state for swipe: %s", exc)
            return False

        import re

        for elem in elements:
            if "ahe" in (elem.get("resourceId") or ""):
                bounds = elem.get("bounds", "")
                nums = re.findall(r"\d+", bounds)
                if len(nums) >= 4:
                    x1, y1, x2, y2 = int(nums[0]), int(nums[1]), int(nums[2]), int(nums[3])
                    center_y = (y1 + y2) // 2
                    await self._wecom.adb.swipe(x2 - 30, center_y, x1 + 30, center_y)
                    logger.debug("Swiped attach grid to reveal next page")
                    return True

        logger.warning("Attachment GridView (ahe) not found for swipe")
        return False

    async def _tap_contact_card_menu(self) -> bool:
        """Tap 'Contact Card' item in the attachment menu."""
        return await self._find_and_tap(
            text_patterns=S.CARD_TEXT_PATTERNS,
            resource_patterns=S.CARD_RESOURCE_PATTERNS,
            step_name="Contact Card menu item",
        )

    async def _select_contact_from_picker(self, contact_name: str) -> bool:
        """Select a contact from the picker using the configured ContactFinderStrategy.

        Defaults to SearchContactFinder (search button → input → result matching).
        Falls back to ScrollContactFinder when explicitly configured.
        """
        if self._contact_finder is not None:
            return await self._contact_finder.find_and_select(contact_name, self._wecom.adb)

        from wecom_automation.services.ui_search.strategy import SearchContactFinder

        finder = SearchContactFinder()
        return await finder.find_and_select(contact_name, self._wecom.adb)

    async def _confirm_send(self) -> bool:
        """Tap the 'Send' button in the confirmation dialog.

        Uses resource_patterns first to avoid false matches like 'Send to:'.
        Falls back to text matching only if resource matching yields nothing.
        """
        # Prefer resource-based matching to avoid "Send to:" false positives
        if await self._find_and_tap(
            resource_patterns=S.SEND_RESOURCE_PATTERNS,
            step_name="Send button (dak)",
        ):
            return True
        # Fallback: text matching
        return await self._find_and_tap(
            text_patterns=S.SEND_TEXT_PATTERNS,
            step_name="Send button (text fallback)",
        )

    # ── Shared Helpers ────────────────────────────────────────────

    async def _find_and_tap(
        self,
        text_patterns: tuple[str, ...] = (),
        desc_patterns: tuple[str, ...] = (),
        resource_patterns: tuple[str, ...] = (),
        step_name: str = "element",
    ) -> bool:
        """Generic find-and-tap with retry logic."""
        for attempt in range(self._MAX_RETRIES):
            try:
                ui_tree, elements = await self._wecom.adb.get_ui_state(force=True)
            except Exception:
                logger.warning("[%s] get_ui_state failed (attempt %d)", step_name, attempt + 1)
                await asyncio.sleep(0.5)
                continue

            if not elements:
                await asyncio.sleep(0.5)
                continue

            matches = find_elements_by_keywords(
                elements,
                text_patterns=text_patterns,
                desc_patterns=desc_patterns,
                resource_patterns=resource_patterns,
            )

            if matches:
                elem = matches[0]
                idx = elem.get("index")
                if idx is not None:
                    try:
                        await self._wecom.adb.tap(int(idx))
                        logger.debug("[%s] tapped (attempt %d)", step_name, attempt + 1)
                        return True
                    except Exception:
                        logger.warning("[%s] tap failed (attempt %d)", step_name, attempt + 1)

            await asyncio.sleep(0.5)

        logger.warning("[%s] not found after %d attempts", step_name, self._MAX_RETRIES)
        return False

    # ── Database Recording ────────────────────────────────────────

    def _record_share(self, request: ContactShareRequest) -> None:
        try:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO media_action_contact_shares
                        (device_serial, customer_name, contact_name, kefu_name, status)
                    VALUES (?, ?, ?, ?, 'shared')
                    """,
                    (request.device_serial, request.customer_name, request.contact_name, request.kefu_name),
                )
        except Exception as exc:
            logger.warning("Failed to record contact share: %s", exc)
