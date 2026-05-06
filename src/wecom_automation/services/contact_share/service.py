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
import json
import logging
import sqlite3
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from wecom_automation.core.metrics_logger import get_metrics_logger
from wecom_automation.database.schema import get_db_path
from wecom_automation.services.contact_share import selectors as S
from wecom_automation.services.contact_share.models import (
    ContactShareRequest,
)
from wecom_automation.services.contact_share.page_state import PageStateValidator
from wecom_automation.services.ui_search.ui_helpers import (
    MatchMode,
    find_elements_by_keywords,
)

logger = logging.getLogger(__name__)

# Stabilization window after a UI action before re-querying state. WeCom's
# attach panel slide-up animation is ~250ms; picker push is ~400ms; confirm
# dialog appears within ~200ms. 0.6s gives all three a comfortable margin
# without bloating per-share latency.
_STATE_STABILIZATION_DELAY = 0.6


def _emit_share_metric(device_serial: str, event: str, data: dict) -> None:
    """Best-effort metric emission — never raise from instrumentation."""
    try:
        get_metrics_logger(device_serial=device_serial or "default").log_event(event, data)
    except Exception:  # noqa: BLE001 — metrics must never break the share flow
        logger.debug("metrics_logger emit failed for event=%s", event, exc_info=True)

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
        """Execute the multi-step UI automation for contact card sharing.

        Transactional contract:
          - The pre-share message is sent FIRST (so the customer sees the lead-in
            text in the right order), but if any subsequent step fails, we send a
            recovery message so the customer is not left with a promise that
            never lands a card.
        """
        pre_message_sent = False
        failure_step: str | None = None

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
                    pre_message_sent = True
                    logger.info(
                        "Pre-share message sent before contact card "
                        "(device=%s, customer=%s)",
                        request.device_serial,
                        request.customer_name,
                    )
            except Exception as exc:
                logger.warning("Pre-share message error (continuing): %s", exc)
            await asyncio.sleep(self._STEP_DELAY)

        try:
            # Step 2: Tap attachment button (i9u/id8/igu) → attach panel
            logger.info(
                "Contact share step: tap attachment button (device=%s, customer=%s)",
                request.device_serial,
                request.customer_name,
            )
            if not await self._tap_attach_button(device_serial=request.device_serial):
                logger.error("Could not tap attachment button")
                failure_step = "attach_button"
                return False
            if not await self._assert_page_state(
                "attach_panel",
                step="attach_button",
                request=request,
            ):
                failure_step = "attach_button_state_check"
                return False

            # Step 3: Open Contact Card menu → contact picker
            logger.info(
                "Contact share step: open Contact Card menu (device=%s, customer=%s)",
                request.device_serial,
                request.customer_name,
            )
            if not await self._open_contact_card_menu(request=request):
                logger.error("Could not find 'Contact Card' menu item")
                failure_step = "contact_card_menu"
                return False
            if not await self._assert_page_state(
                "contact_picker",
                step="contact_card_menu",
                request=request,
            ):
                failure_step = "contact_card_menu_state_check"
                return False

            # Step 4: Select the target contact from picker → confirm dialog
            logger.info(
                "Contact share step: select contact from picker "
                "(device=%s, customer=%s, contact=%s)",
                request.device_serial,
                request.customer_name,
                request.contact_name,
            )
            if not await self._select_contact_from_picker(
                request.contact_name,
                device_serial=request.device_serial,
            ):
                logger.error("Could not select contact '%s' in picker", request.contact_name)
                failure_step = "contact_picker"
                return False
            if not await self._assert_page_state(
                "confirm_send_dialog",
                step="contact_picker",
                request=request,
            ):
                failure_step = "contact_picker_state_check"
                return False

            # Step 5: Tap "Send" in confirmation dialog → back to chat screen
            logger.info(
                "Contact share step: confirm send (device=%s, customer=%s, contact=%s)",
                request.device_serial,
                request.customer_name,
                request.contact_name,
            )
            if not await self._confirm_send():
                logger.error("Could not confirm contact card send")
                failure_step = "confirm_send"
                return False
            if not await self._assert_page_state(
                "chat_screen",
                step="confirm_send",
                request=request,
            ):
                failure_step = "confirm_send_state_check"
                return False

            logger.info("Contact card shared successfully to %s", request.customer_name)
            return True
        finally:
            _emit_share_metric(
                request.device_serial,
                "contact_share_attempt",
                {
                    "customer_name": request.customer_name,
                    "contact_name": request.contact_name,
                    "kefu_name": request.kefu_name,
                    "result": "success" if failure_step is None else f"fail_{failure_step}",
                    "pre_message_sent": pre_message_sent,
                    "recovery_triggered": failure_step is not None and pre_message_sent,
                },
            )
            if failure_step is not None and pre_message_sent:
                # Only send recovery when pre-message went out but the card never
                # arrived — otherwise customer thinks "card incoming" but nothing follows.
                await self._send_recovery_message_after_failure(request, failure_step)

    async def _send_recovery_message_after_failure(
        self,
        request: ContactShareRequest,
        failure_step: str,
    ) -> None:
        """Send a recovery message so the customer is not left expecting a card.

        Only invoked when:
          1. The pre-share message was already delivered (the customer was promised
             a card or supervisor handoff)
          2. A subsequent UI step failed (attach_button / contact_card_menu /
             contact_picker / confirm_send) so no card was actually sent.
        """
        text = (request.recovery_message_on_failure_text or "").strip()
        if not text:
            logger.warning(
                "Skipping recovery message: empty text "
                "(device=%s, customer=%s, failure_step=%s)",
                request.device_serial,
                request.customer_name,
                failure_step,
            )
            return

        try:
            logger.info(
                "Contact share recovery: sending fallback message "
                "(device=%s, customer=%s, failure_step=%s, text_length=%d)",
                request.device_serial,
                request.customer_name,
                failure_step,
                len(text),
            )
            sent, _ = await self._wecom.send_message(text)
            if sent:
                logger.info(
                    "Recovery message delivered after card share failure "
                    "(device=%s, customer=%s, failure_step=%s)",
                    request.device_serial,
                    request.customer_name,
                    failure_step,
                )
            else:
                logger.warning(
                    "Recovery message send returned False "
                    "(device=%s, customer=%s, failure_step=%s)",
                    request.device_serial,
                    request.customer_name,
                    failure_step,
                )
        except Exception as exc:
            logger.warning(
                "Recovery message send raised "
                "(device=%s, customer=%s, failure_step=%s): %s",
                request.device_serial,
                request.customer_name,
                failure_step,
                exc,
            )

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

    async def _tap_attach_button(self, device_serial: str | None = None) -> bool:
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
            _emit_share_metric(
                device_serial or "",
                "contact_share_attach_button",
                {"match": "resource_id"},
            )
            return True

        logger.warning(
            "Attach button not found via resourceId/desc patterns "
            "(tried resource_ids=%s, descs=%s); falling back to position heuristic",
            S.ATTACH_RESOURCE_PATTERNS,
            S.ATTACH_DESC_PATTERNS,
        )
        ok = await self._tap_attach_button_by_position()
        _emit_share_metric(
            device_serial or "",
            "contact_share_attach_button",
            {"match": "position_fallback" if ok else "miss"},
        )
        return ok

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
        # Always dump the bottom band when we resort to position fallback so we
        # can audit whether we picked the real attach button vs an emoji /
        # voice-toggle icon. This is deliberately verbose: any time the
        # resource-id selector misses, we want a full record for selector
        # drift analysis even when the tap "happened to work".
        self._dump_ui_for_attach_failure(elements)

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

    async def _open_contact_card_menu(
        self,
        request: ContactShareRequest | None = None,
    ) -> bool:
        """Find and tap 'Contact Card' — tries current page first, swipes if not found.

        WeCom promotes recently-used attachment items to page 1, so after the first
        use 'Contact Card' may appear without swiping. This method handles both cases.

        On total failure (both fast-path and slow-path miss) we dump the
        post-swipe attach panel to ``logs/contact_share_dump_*_contact_card_menu.json``
        AND log every visible element whose text/desc/resourceId contains a
        Contact-Card-shaped keyword. That second log is critical because the
        primary failure mode now is *resourceId/text drift* — without seeing
        the real strings we cannot extend ``CARD_TEXT_PATTERNS`` to match
        the new build (e.g. "Personal Card" vs "推荐联系人" vs ...).
        """
        if await self._tap_contact_card_menu():
            return True

        logger.info("Contact Card not on current page; swiping to page 2...")
        if not await self._swipe_attach_grid():
            await self._diagnose_contact_card_miss(request, after_swipe=False)
            return False

        await asyncio.sleep(1.0)
        if await self._tap_contact_card_menu():
            return True

        await self._diagnose_contact_card_miss(request, after_swipe=True)
        return False

    async def _diagnose_contact_card_miss(
        self,
        request: ContactShareRequest | None,
        *,
        after_swipe: bool,
    ) -> None:
        """Log Contact-Card candidates and dump the UI when the menu item
        cannot be tapped. No-op if anything in the path raises — diagnostics
        must never mask the underlying share failure.
        """
        try:
            ui_tree, elements = await self._wecom.adb.get_ui_state(force=True)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[contact-card miss] failed to read UI for diagnosis: %s", exc)
            return

        # Surface every candidate string an operator could plausibly need.
        keywords = ("card", "Card", "名片", "Contact", "Personal", "联系人", "Recommend", "推荐")
        candidates: list[str] = []
        for elem in (elements or []):
            text = (elem.get("text") or "").strip()
            desc = (elem.get("contentDescription") or "").strip()
            rid = (elem.get("resourceId") or "")
            if any(kw in text or kw in desc for kw in keywords):
                short_rid = rid.rsplit("/", 1)[-1] if rid else ""
                candidates.append(
                    f"text={text!r} desc={desc!r} rid={short_rid!r} bounds={elem.get('bounds')!r}"
                )

        if candidates:
            logger.warning(
                "[contact-card miss] %d candidate node(s) with Contact-Card-shaped text "
                "(after_swipe=%s) — review and extend CARD_TEXT_PATTERNS if real:\n  - %s",
                len(candidates),
                after_swipe,
                "\n  - ".join(candidates),
            )
        else:
            logger.warning(
                "[contact-card miss] zero Contact-Card-shaped candidates in tree "
                "(after_swipe=%s, total_elements=%d) — attach panel may have closed "
                "or layout changed entirely",
                after_swipe,
                len(elements or []),
            )

        if request is not None:
            self._dump_full_ui_for_diagnosis(
                request=request,
                step="contact_card_menu",
                expected_state="contact_card_visible",
                ui_tree=ui_tree,
                elements=elements or [],
                reason=(
                    "Contact Card menu item not found "
                    f"(after_swipe={after_swipe})"
                ),
            )

    async def _swipe_attach_grid(self) -> bool:
        """Swipe left on the attachment GridView to reveal the next page.

        Walks every known GridView resource id (ahe legacy / aij
        2026-05-06 build / ...) so a build-bumped resource id does not
        silently break the swipe. The original code hardcoded ``"ahe"``
        which is exactly why Contact Card on page 2 was unreachable on
        the 720x1612 device that triggered this whole investigation.
        """
        try:
            ui_tree, elements = await self._wecom.adb.get_ui_state(force=True)
        except Exception as exc:
            logger.warning("Failed to get UI state for swipe: %s", exc)
            return False

        import re

        for elem in elements:
            rid = (elem.get("resourceId") or "")
            if not any(grid_id in rid for grid_id in S.ATTACH_GRID_RESOURCE_PATTERNS):
                continue
            bounds = elem.get("bounds", "")
            nums = re.findall(r"\d+", bounds)
            if len(nums) >= 4:
                x1, y1, x2, y2 = int(nums[0]), int(nums[1]), int(nums[2]), int(nums[3])
                center_y = (y1 + y2) // 2
                await self._wecom.adb.swipe(x2 - 30, center_y, x1 + 30, center_y)
                logger.debug(
                    "Swiped attach grid (rid=%s, bounds=%s) to reveal next page",
                    rid,
                    bounds,
                )
                return True

        logger.warning(
            "Attachment GridView not found for swipe (tried %s)",
            S.ATTACH_GRID_RESOURCE_PATTERNS,
        )
        return False

    async def _tap_contact_card_menu(self) -> bool:
        """Tap 'Contact Card' item in the attachment menu.

        Uses *exact* text match. Substring matching previously caused
        false positives — any chat history label or attach-panel item
        text that contained "名片" / "Contact Card" as a substring (e.g.
        "我的名片夹") would be tapped instead of the real menu item, and
        the share flow would silently advance with no actual page change.
        """
        return await self._find_and_tap(
            text_patterns=S.CARD_TEXT_PATTERNS,
            resource_patterns=S.CARD_RESOURCE_PATTERNS,
            text_match_mode="exact",
            step_name="Contact Card menu item",
        )

    async def _select_contact_from_picker(
        self,
        contact_name: str,
        device_serial: str | None = None,
    ) -> bool:
        """Select a contact from the picker using the configured ContactFinderStrategy.

        Defaults to a composite of (SearchContactFinder, ScrollContactFinder).
        Search hits are precise but can miss when IME drops a keystroke or the
        WeCom search index is cold; ScrollContactFinder then walks the visible
        list as a safety net so we don't fail closed when the contact is
        actually right there.
        """
        if self._contact_finder is not None:
            logger.debug(
                "Selecting contact with configured finder "
                "(contact=%s, finder=%s)",
                contact_name,
                type(self._contact_finder).__name__,
            )
            ok = await self._contact_finder.find_and_select(contact_name, self._wecom.adb)
            _emit_share_metric(
                device_serial or "",
                "contact_share_picker",
                {
                    "contact_name": contact_name,
                    "finder": type(self._contact_finder).__name__,
                    "result": "hit" if ok else "miss",
                },
            )
            return ok

        from wecom_automation.services.ui_search.strategy import (
            CompositeContactFinder,
            ScrollContactFinder,
            SearchContactFinder,
        )

        finder = CompositeContactFinder([
            SearchContactFinder(),
            ScrollContactFinder(),
        ])
        logger.debug(
            "Selecting contact with default finder (contact=%s, finder=%s)",
            contact_name,
            type(finder).__name__,
        )
        ok = await finder.find_and_select(contact_name, self._wecom.adb)
        _emit_share_metric(
            device_serial or "",
            "contact_share_picker",
            {
                "contact_name": contact_name,
                "finder": "composite_search_then_scroll",
                "result": "hit" if ok else "miss",
            },
        )
        return ok

    async def _confirm_send(self) -> bool:
        """Tap the 'Send' button in the confirmation dialog.

        Resource ID first (dak/blz/i_2), then *exact* text match. Substring
        text matching is the original sin here: ``"Send"`` would gladly
        match ``"Send to:"`` (the picker title!) on a page where no real
        confirm dialog ever appeared, returning fake success. The page-
        state envelope around this call (`is_confirm_send_dialog_open`)
        already filters most wrong contexts, but exact match is a second
        line of defense if the validator ever drifts.
        """
        if await self._find_and_tap(
            resource_patterns=S.SEND_RESOURCE_PATTERNS,
            step_name="Send button (dak)",
        ):
            return True
        return await self._find_and_tap(
            text_patterns=S.SEND_TEXT_PATTERNS,
            text_match_mode="exact",
            step_name="Send button (text fallback)",
        )

    # ── Shared Helpers ────────────────────────────────────────────

    async def _find_and_tap(
        self,
        text_patterns: tuple[str, ...] = (),
        desc_patterns: tuple[str, ...] = (),
        resource_patterns: tuple[str, ...] = (),
        step_name: str = "element",
        text_match_mode: MatchMode = "substring",
        desc_match_mode: MatchMode = "substring",
        resource_match_mode: MatchMode = "substring",
    ) -> bool:
        """Generic find-and-tap with retry logic.

        Match modes default to ``substring`` to preserve every existing
        call site. Pass ``text_match_mode="exact"`` for short labels like
        "Send" / "Cancel" / "Contact Card" where substrings on unrelated
        UI nodes would otherwise be tapped — this is exactly how 22:58's
        fake-success was happening.
        """
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
                text_match_mode=text_match_mode,
                desc_match_mode=desc_match_mode,
                resource_match_mode=resource_match_mode,
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

    # ── Page State Assertion & Diagnostic Dump ────────────────────

    async def _assert_page_state(
        self,
        expected: str,
        *,
        step: str,
        request: ContactShareRequest,
    ) -> bool:
        """Re-read the UI tree and assert we landed on ``expected`` page.

        Why this exists: WeCom's obfuscated resource IDs + substring
        matching used to let any step "succeed" by tapping a wrong element,
        so the next step would happily run on the same stale page until the
        whole flow recorded a fake success. This helper closes that loop —
        every transition is verified against PageStateValidator and a full
        UI snapshot is dumped on mismatch so we can update selectors.

        Args:
            expected: one of "attach_panel" / "contact_picker" /
                "confirm_send_dialog" / "chat_screen".
            step: name of the UI action that *should* have produced
                ``expected`` (used for log lines and dump filename).
            request: the active share request, used for diagnostic context.
        """
        await asyncio.sleep(_STATE_STABILIZATION_DELAY)
        try:
            ui_tree, elements = await self._wecom.adb.get_ui_state(force=True)
        except Exception as exc:
            logger.error(
                "[state-check %s] get_ui_state failed (device=%s, customer=%s): %s",
                step,
                request.device_serial,
                request.customer_name,
                exc,
            )
            self._dump_full_ui_for_diagnosis(
                request=request,
                step=step,
                expected_state=expected,
                ui_tree=None,
                elements=[],
                reason=f"get_ui_state error: {exc!r}",
            )
            return False

        validator_summary = PageStateValidator.describe(elements or [])
        check_map = {
            "attach_panel": PageStateValidator.is_attach_panel_open,
            "contact_picker": PageStateValidator.is_contact_picker_open,
            "confirm_send_dialog": PageStateValidator.is_confirm_send_dialog_open,
            "chat_screen": PageStateValidator.is_chat_screen,
        }
        check = check_map.get(expected)
        if check is None:
            logger.error("[state-check %s] unknown expected state: %s", step, expected)
            return False

        ok = bool(check(elements or []))
        if ok:
            logger.info(
                "[state-check %s] OK — observed=%s (device=%s, customer=%s)",
                step,
                validator_summary,
                request.device_serial,
                request.customer_name,
            )
            return True

        logger.error(
            "[state-check %s] FAILED — expected=%s observed=%s "
            "(device=%s, customer=%s, contact=%s) — dumping UI for diagnosis",
            step,
            expected,
            validator_summary,
            request.device_serial,
            request.customer_name,
            request.contact_name,
        )
        self._dump_full_ui_for_diagnosis(
            request=request,
            step=step,
            expected_state=expected,
            ui_tree=ui_tree,
            elements=elements or [],
            reason=f"expected={expected} observed={validator_summary}",
        )
        return False

    def _dump_full_ui_for_diagnosis(
        self,
        *,
        request: ContactShareRequest,
        step: str,
        expected_state: str,
        ui_tree,
        elements: list[dict],
        reason: str,
    ) -> None:
        """Persist the full UI snapshot to ``logs/contact_share_dump_<ts>_<step>.json``.

        Captures BOTH the recursive ui_tree and the flat clickable list so
        we can reconstruct exactly what was on screen when the page-state
        check failed. The dump intentionally lives outside the rotated
        log file to preserve large payloads; selector drift work needs the
        whole tree, not the bottom 30%.
        """
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            dump_dir = Path("logs")
            dump_dir.mkdir(parents=True, exist_ok=True)
            dump_path = dump_dir / f"contact_share_dump_{timestamp}_{step}.json"

            payload = {
                "captured_at": datetime.now().isoformat(timespec="microseconds"),
                "device_serial": request.device_serial,
                "customer_name": request.customer_name,
                "contact_name": request.contact_name,
                "kefu_name": request.kefu_name,
                "step": step,
                "expected_state": expected_state,
                "reason": reason,
                "page_state_summary": PageStateValidator.describe(elements or []),
                "elements_count": len(elements or []),
                "elements": elements or [],
                "ui_tree": ui_tree,
            }
            dump_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            logger.warning(
                "[ui-dump] wrote contact-share diagnostic dump to %s "
                "(step=%s, reason=%s, elements=%d)",
                dump_path,
                step,
                reason,
                len(elements or []),
            )
            _emit_share_metric(
                request.device_serial,
                "contact_share_ui_dump",
                {
                    "step": step,
                    "expected_state": expected_state,
                    "reason": reason,
                    "dump_path": str(dump_path),
                },
            )
        except Exception as exc:  # noqa: BLE001 — diagnostics must never break the share flow
            logger.warning(
                "[ui-dump] failed to write diagnostic dump (step=%s): %s",
                step,
                exc,
                exc_info=True,
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
