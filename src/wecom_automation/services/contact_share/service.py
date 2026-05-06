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
            logger.debug("media_action_contact_shares table ready (db_path=%s)", self._db_path)
        except Exception as exc:
            logger.warning("Failed to ensure contact_shares table: %s", exc)

    # ── Public API ────────────────────────────────────────────────

    async def share_contact_card(self, request: ContactShareRequest) -> bool:
        logger.info(
            "Sharing contact card: device=%s, customer=%s, contact=%s, kefu=%s, "
            "send_pre_message=%s, pre_message_length=%d",
            request.device_serial,
            request.customer_name,
            request.contact_name,
            request.kefu_name,
            request.send_message_before_share,
            len(request.pre_share_message_text),
        )
        try:
            if self._wecom is None:
                logger.warning("No WeComService available; recording share intent only")
                self._record_share(request)
                return True

            success = await self._perform_ui_share(request)
            if success:
                self._record_share(request)
                logger.info(
                    "Contact card share completed and recorded "
                    "(device=%s, customer=%s, contact=%s)",
                    request.device_serial,
                    request.customer_name,
                    request.contact_name,
                )
            else:
                logger.error(
                    "Contact card share returned failure "
                    "(device=%s, customer=%s, contact=%s)",
                    request.device_serial,
                    request.customer_name,
                    request.contact_name,
                )
            return success
        except Exception:
            logger.exception(
                "Contact card sharing failed "
                "(device=%s, customer=%s, contact=%s)",
                request.device_serial,
                request.customer_name,
                request.contact_name,
            )
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
                already_shared = cur.fetchone() is not None
                logger.debug(
                    "Checked contact share history "
                    "(device=%s, customer=%s, contact=%s, already_shared=%s)",
                    device_serial,
                    customer_name,
                    contact_name,
                    already_shared,
                )
                return already_shared
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
        logger.info(
            "Contact share step: ensure target chat (device=%s, customer=%s, assume_current_chat=%s)",
            request.device_serial,
            request.customer_name,
            request.assume_current_chat,
        )
        if not await self._ensure_target_chat(request):
            logger.error("Could not navigate to chat for '%s'", request.customer_name)
            return False

        await asyncio.sleep(self._STEP_DELAY)

        # Step 1.5: Send pre-share message (if configured)
        if request.send_message_before_share and request.pre_share_message_text:
            try:
                logger.info(
                    "Contact share step: send pre-share message "
                    "(device=%s, customer=%s, text_length=%d)",
                    request.device_serial,
                    request.customer_name,
                    len(request.pre_share_message_text),
                )
                sent, _ = await self._wecom.send_message(request.pre_share_message_text)
                if not sent:
                    logger.warning("Pre-share message failed to send, continuing with card share")
                else:
                    logger.info(
                        "Pre-share message sent before contact card "
                        "(device=%s, customer=%s)",
                        request.device_serial,
                        request.customer_name,
                    )
            except Exception as exc:
                logger.warning("Pre-share message error (continuing): %s", exc)
            await asyncio.sleep(self._STEP_DELAY)

        # Step 2: Tap attachment button (i9u)
        logger.info(
            "Contact share step: tap attachment button (device=%s, customer=%s)",
            request.device_serial,
            request.customer_name,
        )
        if not await self._tap_attach_button():
            logger.error("Could not tap attachment button")
            return False

        await asyncio.sleep(self._STEP_DELAY)

        # Step 3: Open Contact Card — adaptive: try current page first, swipe if needed
        logger.info(
            "Contact share step: open Contact Card menu (device=%s, customer=%s)",
            request.device_serial,
            request.customer_name,
        )
        if not await self._open_contact_card_menu():
            logger.error("Could not find 'Contact Card' menu item")
            return False

        await asyncio.sleep(self._STEP_DELAY)

        # Step 4: Select the target contact from picker
        logger.info(
            "Contact share step: select contact from picker "
            "(device=%s, customer=%s, contact=%s)",
            request.device_serial,
            request.customer_name,
            request.contact_name,
        )
        if not await self._select_contact_from_picker(request.contact_name):
            logger.error("Could not select contact '%s' in picker", request.contact_name)
            return False

        await asyncio.sleep(self._STEP_DELAY)

        # Step 5: Tap "Send" in confirmation dialog
        logger.info(
            "Contact share step: confirm send (device=%s, customer=%s, contact=%s)",
            request.device_serial,
            request.customer_name,
            request.contact_name,
        )
        if not await self._confirm_send():
            logger.error("Could not confirm contact card send")
            return False

        logger.info("Contact card shared successfully to %s", request.customer_name)
        return True

    async def _ensure_target_chat(self, request: ContactShareRequest) -> bool:
        if request.assume_current_chat:
            try:
                screen = await self._wecom.get_current_screen()
            except Exception as exc:
                logger.warning(
                    "Could not inspect current screen before contact share; falling back to navigation "
                    "(device=%s, customer=%s): %s",
                    request.device_serial,
                    request.customer_name,
                    exc,
                )
            else:
                if screen == "chat":
                    logger.info(
                        "Contact share using current chat without re-navigation "
                        "(device=%s, customer=%s)",
                        request.device_serial,
                        request.customer_name,
                    )
                    return True
                logger.info(
                    "Current screen is %s, navigating before contact share "
                    "(device=%s, customer=%s)",
                    screen,
                    request.device_serial,
                    request.customer_name,
                )

        return await self._wecom.navigate_to_chat(request.device_serial, request.customer_name)

    async def _tap_attach_button(self) -> bool:
        """Tap the attachment button (rightmost bottom icon in chat input area).

        Tries in order:
          1. Known resource IDs (i9u, id8, ...) and descriptions ("更多功能").
          2. Position heuristic: the rightmost clickable element in the bottom
             ~25% of the screen, excluding the send button area.

        The position fallback exists because WeCom obfuscates resource IDs and
        they drift between minor versions — a single hardcoded ID is the most
        common reason this step silently fails on production devices.
        """
        if await self._find_and_tap(
            resource_patterns=S.ATTACH_RESOURCE_PATTERNS,
            desc_patterns=S.ATTACH_DESC_PATTERNS,
            step_name="attach button",
        ):
            return True

        logger.warning(
            "Attach button not found via resourceId/desc patterns "
            "(tried resource_ids=%s, descs=%s); falling back to position heuristic",
            S.ATTACH_RESOURCE_PATTERNS,
            S.ATTACH_DESC_PATTERNS,
        )
        return await self._tap_attach_button_by_position()

    async def _tap_attach_button_by_position(self) -> bool:
        """Heuristically tap the rightmost icon in the chat input row.

        The chat input bar always sits at the bottom of the screen with the
        attachment button as the rightmost icon (or second-to-rightmost when
        the keyboard / voice toggle is visible). We pick the clickable element
        whose center sits in the bottom ~20% of the screen and farthest right,
        then dump UI state on failure for diagnosis.
        """
        try:
            ui_tree, elements = await self._wecom.adb.get_ui_state(force=True)
        except Exception as exc:
            logger.warning("[attach button position fallback] get_ui_state failed: %s", exc)
            return False

        if not elements:
            logger.warning("[attach button position fallback] no UI elements returned")
            return False

        screen_height = self._infer_screen_height(elements)
        if screen_height <= 0:
            logger.warning("[attach button position fallback] could not infer screen height")
            self._dump_ui_for_attach_failure(elements)
            return False

        bottom_band_top = int(screen_height * 0.78)

        candidates: list[tuple[int, dict]] = []
        for elem in elements:
            if not isinstance(elem, dict):
                continue
            bounds = self._parse_bounds(elem)
            if not bounds:
                continue
            x1, y1, x2, y2 = bounds
            if y1 < bottom_band_top:
                continue

            cls_name = (elem.get("className") or "").lower()
            if "edittext" in cls_name:
                continue

            text = (elem.get("text") or "").strip()
            if any(token in text for token in ("Send", "发送", "SEND")):
                continue

            if elem.get("clickable") is False:
                continue

            cx = (x1 + x2) // 2
            candidates.append((cx, elem))

        if not candidates:
            logger.warning(
                "[attach button position fallback] no candidates in bottom band y>=%d (screen_height=%d)",
                bottom_band_top,
                screen_height,
            )
            self._dump_ui_for_attach_failure(elements)
            return False

        candidates.sort(key=lambda pair: pair[0], reverse=True)
        target_cx, target_elem = candidates[0]
        idx = target_elem.get("index")
        logger.info(
            "[attach button position fallback] picked rightmost bottom element "
            "(center_x=%d, %s)",
            target_cx,
            self._describe_element(target_elem),
        )

        if idx is None:
            logger.warning("[attach button position fallback] candidate has no index, cannot tap")
            return False

        try:
            await self._wecom.adb.tap(int(idx))
            return True
        except Exception as exc:
            logger.warning("[attach button position fallback] tap failed: %s", exc)
            return False

    @staticmethod
    def _parse_bounds(elem: dict) -> tuple[int, int, int, int] | None:
        """Parse an element's bounds into (x1, y1, x2, y2) or None."""
        import re

        bounds_value = elem.get("bounds") or elem.get("boundsInScreen")
        if isinstance(bounds_value, dict):
            try:
                return (
                    int(bounds_value.get("left", 0)),
                    int(bounds_value.get("top", 0)),
                    int(bounds_value.get("right", 0)),
                    int(bounds_value.get("bottom", 0)),
                )
            except (TypeError, ValueError):
                return None
        if isinstance(bounds_value, str):
            nums = re.findall(r"-?\d+", bounds_value)
            if len(nums) >= 4:
                return tuple(int(n) for n in nums[:4])  # type: ignore[return-value]
        return None

    @staticmethod
    def _infer_screen_height(elements: list[dict]) -> int:
        """Infer device screen height from the largest bottom bound seen."""
        max_bottom = 0
        for elem in elements:
            if not isinstance(elem, dict):
                continue
            bounds = ContactShareService._parse_bounds(elem)
            if bounds and bounds[3] > max_bottom:
                max_bottom = bounds[3]
        return max_bottom

    def _dump_ui_for_attach_failure(self, elements: list[dict]) -> None:
        """Log a compact UI snapshot to help debug attach-button selector drift.

        Only the bottom 30% of the screen is dumped — that's where the input
        bar lives, and dumping the whole tree would flood the log file.
        """
        try:
            screen_height = self._infer_screen_height(elements) or 1
            cutoff = int(screen_height * 0.7)
            lines = []
            for elem in elements:
                if not isinstance(elem, dict):
                    continue
                bounds = self._parse_bounds(elem)
                if not bounds or bounds[1] < cutoff:
                    continue
                lines.append(self._describe_element(elem))
            if lines:
                logger.warning(
                    "[attach button] bottom-of-screen UI snapshot for diagnosis "
                    "(screen_height=%d, cutoff=%d, count=%d):\n  - %s",
                    screen_height,
                    cutoff,
                    len(lines),
                    "\n  - ".join(lines),
                )
        except Exception as exc:
            logger.debug("UI dump for attach failure errored: %s", exc)

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
            logger.debug(
                "Selecting contact with configured finder "
                "(contact=%s, finder=%s)",
                contact_name,
                type(self._contact_finder).__name__,
            )
            return await self._contact_finder.find_and_select(contact_name, self._wecom.adb)

        from wecom_automation.services.ui_search.strategy import SearchContactFinder

        finder = SearchContactFinder()
        logger.debug(
            "Selecting contact with default finder (contact=%s, finder=%s)",
            contact_name,
            type(finder).__name__,
        )
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
                logger.debug("[%s] no UI elements returned (attempt %d)", step_name, attempt + 1)
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
                logger.debug(
                    "[%s] found %d candidate(s); first=%s (attempt %d)",
                    step_name,
                    len(matches),
                    self._describe_element(elem),
                    attempt + 1,
                )
                if idx is not None:
                    try:
                        await self._wecom.adb.tap(int(idx))
                        logger.debug("[%s] tapped (attempt %d)", step_name, attempt + 1)
                        return True
                    except Exception:
                        logger.warning("[%s] tap failed (attempt %d)", step_name, attempt + 1)
                else:
                    logger.warning(
                        "[%s] first candidate has no droidrun index: %s",
                        step_name,
                        self._describe_element(elem),
                    )
            else:
                logger.debug(
                    "[%s] no match among %d UI elements (attempt %d)",
                    step_name,
                    len(elements),
                    attempt + 1,
                )

            await asyncio.sleep(0.5)

        logger.warning("[%s] not found after %d attempts", step_name, self._MAX_RETRIES)
        return False

    @staticmethod
    def _describe_element(elem: dict) -> str:
        """Return compact UI element metadata for debug logs."""
        return (
            f"index={elem.get('index')}, text={elem.get('text')!r}, "
            f"desc={elem.get('contentDescription')!r}, resourceId={elem.get('resourceId')!r}, "
            f"bounds={elem.get('bounds')!r}"
        )

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
                logger.debug(
                    "Recorded contact share "
                    "(device=%s, customer=%s, contact=%s, kefu=%s)",
                    request.device_serial,
                    request.customer_name,
                    request.contact_name,
                    request.kefu_name,
                )
        except Exception as exc:
            logger.warning("Failed to record contact share: %s", exc)
