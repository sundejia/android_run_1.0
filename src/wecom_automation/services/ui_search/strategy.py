"""
ContactFinderStrategy — strategy pattern for finding contacts in WeCom pickers.

Two implementations:
- ScrollContactFinder: scroll through list, match by text prefix (legacy)
- SearchContactFinder: use search button/input for precise lookup (new)

Both share the same interface: `find_and_select(contact_name, adb_service) -> bool`.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod

from wecom_automation.services.ui_search import selectors as S
from wecom_automation.services.ui_search.ui_helpers import (
    find_result_candidates,
    find_search_button,
    find_search_input,
    parse_element_bounds,
)

logger = logging.getLogger(__name__)

_REF_WIDTH = 1080
_REF_HEIGHT = 2340


_MIN_PLAUSIBLE_SCREEN_WIDTH = 400
_MIN_PLAUSIBLE_SCREEN_HEIGHT = 800


def _infer_screen_size_from_elements(elements: list[dict]) -> tuple[int, int]:
    """Infer (width, height) from the largest right/bottom bound seen.

    Returns (0, 0) when the observed bounds are too small to plausibly
    represent a real device screen (caller should keep its current default).
    Plausibility gates exist so a UI snapshot containing only one tiny
    icon doesn't collapse our screen-size estimate to that icon's box.
    """
    max_right = 0
    max_bottom = 0
    for elem in elements or []:
        bounds = parse_element_bounds(elem)
        if not bounds:
            continue
        if bounds[2] > max_right:
            max_right = bounds[2]
        if bounds[3] > max_bottom:
            max_bottom = bounds[3]
    width = max_right if max_right >= _MIN_PLAUSIBLE_SCREEN_WIDTH else 0
    height = max_bottom if max_bottom >= _MIN_PLAUSIBLE_SCREEN_HEIGHT else 0
    return (width, height)


class ContactFinderStrategy(ABC):
    """Abstract base for contact finding in a WeCom picker/list."""

    @abstractmethod
    async def find_and_select(self, contact_name: str, adb_service) -> bool:
        """Find and tap the target contact. Return True if selected."""
        ...


class ScrollContactFinder(ContactFinderStrategy):
    """Scroll through the visible list and match by text prefix.

    This is the legacy behavior from ContactShareService._select_contact_from_picker.
    """

    def __init__(self, max_retries: int = 3) -> None:
        self._max_retries = max_retries

    async def find_and_select(self, contact_name: str, adb_service) -> bool:
        for attempt in range(self._max_retries):
            try:
                _, elements = await adb_service.get_ui_state(force=True)
            except Exception:
                logger.debug("get_ui_state failed (attempt %d)", attempt + 1)
                await asyncio.sleep(0.5)
                continue

            if not elements:
                await asyncio.sleep(0.5)
                continue

            for elem in elements:
                text = (elem.get("text") or "").strip()
                if text and text.startswith(contact_name):
                    idx = elem.get("index")
                    if idx is not None:
                        try:
                            await adb_service.tap(int(idx))
                            logger.debug("Selected contact '%s' via scroll (attempt %d)", contact_name, attempt + 1)
                            return True
                        except Exception:
                            continue

            await asyncio.sleep(0.5)

        logger.warning("ScrollContactFinder: could not find contact '%s'", contact_name)
        return False


class SearchContactFinder(ContactFinderStrategy):
    """Use the search button/input to find a contact by name.

    Adaptive search flow:
    1. Look for an already-visible search input field
    2. If not found, look for a search button and tap it
    3. Fall back to top-right position heuristic
    4. Clear and type the contact name
    5. Wait for results, match by flexible text matching
    6. Select the best match
    """

    def __init__(
        self,
        *,
        search_text_patterns: tuple[str, ...] = (),
        search_desc_patterns: tuple[str, ...] = (),
        search_resource_patterns: tuple[str, ...] = (),
        max_retries: int = 3,
        stabilization_delay: float = 0.5,
        screen_width: int | None = None,
        screen_height: int | None = None,
    ) -> None:
        self._search_text_patterns = search_text_patterns or S.PICKER_SEARCH_TEXT_PATTERNS
        self._search_desc_patterns = search_desc_patterns or S.PICKER_SEARCH_DESC_PATTERNS
        self._search_resource_patterns = search_resource_patterns or S.PICKER_SEARCH_RESOURCE_PATTERNS
        self._max_retries = max_retries
        self._stabilization_delay = stabilization_delay
        self._screen_width = screen_width or _REF_WIDTH
        self._screen_height = screen_height or _REF_HEIGHT

    async def find_and_select(self, contact_name: str, adb_service) -> bool:
        # Step 1: Ensure search input is ready (also auto-detects screen size
        # from the first get_ui_state result so left-margin / top-band
        # heuristics aren't off by 1.5x on a 720-wide device).
        try:
            search_ready = await self._ensure_search_input_ready(adb_service)
        except Exception as exc:
            logger.warning("SearchContactFinder: failed to prepare search input: %s", exc)
            return False

        if not search_ready:
            logger.warning("SearchContactFinder: could not open search input for '%s'", contact_name)
            return False

        # Step 2: Clear and type
        try:
            await adb_service.clear_text_field()
            await adb_service.input_text(contact_name)
            await adb_service.wait(self._stabilization_delay)
        except Exception as exc:
            logger.warning("SearchContactFinder: failed to input search text: %s", exc)
            return False

        # Step 3: Find matching results with retry
        for attempt in range(self._max_retries):
            try:
                _, elements = await adb_service.get_ui_state(force=True)
            except Exception:
                logger.debug("get_ui_state failed during result search (attempt %d)", attempt + 1)
                await asyncio.sleep(0.5)
                continue

            search_input = find_search_input(elements)
            matches = find_result_candidates(
                elements,
                contact_name,
                anchor=search_input,
                screen_width=self._screen_width,
            )

            if matches:
                elem = matches[0]
                index = elem.get("index")
                if index is not None:
                    try:
                        await adb_service.tap(int(index))
                        logger.debug("SearchContactFinder: selected '%s' (attempt %d)", contact_name, attempt + 1)
                        return True
                    except Exception:
                        logger.debug("Tap failed on result (attempt %d)", attempt + 1)

            if attempt < self._max_retries - 1:
                await asyncio.sleep(1.0)

        logger.warning("SearchContactFinder: no matching results for '%s'", contact_name)
        return False

    async def _ensure_search_input_ready(self, adb_service) -> bool:
        """Tap search button or focus search input field."""
        try:
            ui_tree, elements = await adb_service.get_ui_state(force=True)
        except Exception:
            return False

        # Auto-detect actual screen size from this first batch — keeps the
        # left-margin / top-band heuristics correct on 720-wide devices.
        detected_w, detected_h = _infer_screen_size_from_elements(elements or [])
        if detected_w:
            self._screen_width = detected_w
        if detected_h:
            self._screen_height = detected_h

        # Try to find existing input field first
        input_field = find_search_input(elements)
        if input_field:
            index = input_field.get("index")
            if index is not None:
                try:
                    await adb_service.tap(int(index))
                    await adb_service.wait(self._stabilization_delay)
                    return True
                except Exception:
                    pass

        # Try to find search button
        search_btn = find_search_button(
            elements,
            text_patterns=self._search_text_patterns,
            desc_patterns=self._search_desc_patterns,
            resource_patterns=self._search_resource_patterns,
            screen_width=self._screen_width,
            screen_height=self._screen_height,
        )

        # Fallback: search in tree
        if not search_btn and ui_tree:
            search_btn = find_search_button(
                [ui_tree],
                text_patterns=self._search_text_patterns,
                desc_patterns=self._search_desc_patterns,
                resource_patterns=self._search_resource_patterns,
                screen_width=self._screen_width,
                screen_height=self._screen_height,
                is_flat_list=False,
            )

        if not search_btn:
            return False

        # Tap search button
        index = search_btn.get("index")
        try:
            if index is not None:
                await adb_service.tap(int(index))
            else:
                bounds = parse_element_bounds(search_btn)
                if bounds:
                    x = (bounds[0] + bounds[2]) // 2
                    y = (bounds[1] + bounds[3]) // 2
                    await adb_service.tap_coordinates(x, y)
                else:
                    return False
        except Exception:
            return False

        await adb_service.wait(self._stabilization_delay)

        # Now look for input field
        try:
            _, elements = await adb_service.get_ui_state(force=True)
        except Exception:
            return False

        input_field = find_search_input(elements)
        if not input_field:
            return False

        index = input_field.get("index")
        if index is not None:
            try:
                await adb_service.tap(int(index))
                await adb_service.wait(self._stabilization_delay)
            except Exception:
                return False

        return True


class CompositeContactFinder(ContactFinderStrategy):
    """Try strategies in order, returning on first success.

    Used to give SearchContactFinder a ScrollContactFinder safety net so a
    miss in the search box does not silently abort the whole share flow when
    the contact is actually visible in the picker list.
    """

    def __init__(self, finders: list[ContactFinderStrategy]) -> None:
        if not finders:
            raise ValueError("CompositeContactFinder requires at least one finder")
        self._finders = finders

    async def find_and_select(self, contact_name: str, adb_service) -> bool:
        for finder in self._finders:
            name = type(finder).__name__
            try:
                ok = await finder.find_and_select(contact_name, adb_service)
            except Exception as exc:
                logger.warning(
                    "CompositeContactFinder: %s raised for '%s': %s",
                    name,
                    contact_name,
                    exc,
                )
                continue
            if ok:
                logger.debug(
                    "CompositeContactFinder: %s selected '%s'",
                    name,
                    contact_name,
                )
                return True
            logger.info(
                "CompositeContactFinder: %s missed '%s', trying next strategy",
                name,
                contact_name,
            )
        logger.warning(
            "CompositeContactFinder: all %d strategies missed '%s'",
            len(self._finders),
            contact_name,
        )
        return False
