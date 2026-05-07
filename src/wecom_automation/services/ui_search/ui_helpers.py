"""
Pure helper functions for UI element analysis.

Extracted from WeComService to enable reuse across strategy classes
without coupling to the full service. All functions are stateless.
"""

from __future__ import annotations

import re
from typing import Literal

MatchMode = Literal["substring", "exact", "prefix"]


def parse_element_bounds(element: dict | None) -> tuple[int, int, int, int] | None:
    """Parse bounds from an element dict.

    Supports string bounds ("[x1,y1][x2,y2]") and dict bounds
    (bounds/boundsInScreen keys).
    """
    if not element:
        return None

    bounds_value = element.get("bounds")
    if not bounds_value:
        bounds_value = element.get("boundsInScreen") or element.get("bounds_in_screen")

    if not bounds_value:
        return None

    if isinstance(bounds_value, dict):
        return (
            int(bounds_value.get("left", 0)),
            int(bounds_value.get("top", 0)),
            int(bounds_value.get("right", 0)),
            int(bounds_value.get("bottom", 0)),
        )

    if isinstance(bounds_value, str):
        nums = re.findall(r"-?\d+", bounds_value)
        if len(nums) >= 4:
            x1, y1, x2, y2 = (int(n) for n in nums[:4])
            return (x1, y1, x2, y2)

    return None


def _matches(value: str, patterns: tuple[str, ...], mode: MatchMode) -> bool:
    """Apply the requested match strategy to a single (value, patterns) pair.

    Why a single helper: keeping the per-mode rules co-located here means
    callers can flip from substring → exact at the call site without
    re-implementing the matching logic, and the contact_share flow can
    safely use exact match for short labels like "Send" / "Cancel" without
    forking the whole helper.
    """
    if not patterns:
        return False
    value_lc = value.lower()
    if mode == "exact":
        return any(value_lc == pattern.lower() for pattern in patterns)
    if mode == "prefix":
        return any(value_lc.startswith(pattern.lower()) for pattern in patterns)
    return any(pattern.lower() in value_lc for pattern in patterns)


def find_elements_by_keywords(
    elements: list[dict],
    *,
    text_patterns: tuple[str, ...] = (),
    desc_patterns: tuple[str, ...] = (),
    resource_patterns: tuple[str, ...] = (),
    is_flat_list: bool = True,
    text_match_mode: MatchMode = "substring",
    desc_match_mode: MatchMode = "substring",
    resource_match_mode: MatchMode = "substring",
) -> list[dict]:
    """Find elements whose text, contentDescription, or resourceId matches any pattern.

    The default ``substring`` mode is preserved for every existing caller.
    Pass ``text_match_mode="exact"`` for short, well-known labels like
    "Send" or "Cancel" so substrings ("Send to:") cannot false-match —
    this is what stops the contact-share confirm-dialog from "succeeding"
    when no dialog is even open.
    """
    matches: list[dict] = []

    def walk(items: list[dict]) -> None:
        for element in items:
            if not isinstance(element, dict):
                continue
            text = element.get("text") or ""
            desc = element.get("contentDescription") or ""
            rid = element.get("resourceId") or ""

            if (
                _matches(text, text_patterns, text_match_mode)
                or _matches(desc, desc_patterns, desc_match_mode)
                or _matches(rid, resource_patterns, resource_match_mode)
            ):
                matches.append(element)

            if not is_flat_list:
                walk(element.get("children", []))

    walk(elements)
    return matches


def layout_sort_key(element: dict) -> tuple[int, int]:
    """Sort key: vertical position first, then horizontal."""
    bounds = parse_element_bounds(element)
    if not bounds:
        return (10**9, 10**9)
    x1, y1, _, _ = bounds
    return (y1, x1)


def _layout_x2(element: dict) -> int:
    bounds = parse_element_bounds(element)
    return bounds[2] if bounds else -1


def _layout_y1(element: dict) -> int:
    bounds = parse_element_bounds(element)
    return bounds[1] if bounds else 10**9


def _layout_y2(element: dict) -> int:
    bounds = parse_element_bounds(element)
    return bounds[3] if bounds else -1


def pick_top_right_element(elements: list[dict]) -> dict | None:
    """Pick the element closest to the top-right corner."""
    if not elements:
        return None
    return max(elements, key=lambda e: (_layout_x2(e), -_layout_y1(e)))


def pick_bottom_right_element(elements: list[dict]) -> dict | None:
    """Pick the element closest to the bottom-right corner."""
    if not elements:
        return None
    return max(elements, key=lambda e: (_layout_y2(e), _layout_x2(e)))


def pick_first_by_layout(elements: list[dict]) -> dict | None:
    """Pick the topmost-leftmost element."""
    if not elements:
        return None
    return sorted(elements, key=layout_sort_key)[0]


def infer_screen_height_from_elements(elements: list[dict]) -> int:
    """Best-effort screen height from max bottom edge in the flat tree."""
    max_bottom = 0
    for element in elements or []:
        bounds = parse_element_bounds(element)
        if bounds and bounds[3] > max_bottom:
            max_bottom = bounds[3]
    return max_bottom


def find_search_input(elements: list[dict]) -> dict | None:
    """Find a search input field (EditText or search-keyword element).

    When multiple ``EditText`` nodes exist (chat composer under the sheet +
    picker search field), **prefer** the field in the upper portion of the
    screen and nodes whose hint/resource suggests search — otherwise the
    legacy ``pick_first_by_layout`` would still pick the mathematically
    topmost node, which can be wrong if the accessibility layer lists the
    chat bar before the overlay field.

    If the only ``EditText`` sits in the **lower half** of the screen, treat
    it as the chat input (not the picker field that appears only after
    tapping the magnifier) and return ``None`` so ``find_search_button``
    runs next.
    """
    screen_h = infer_screen_height_from_elements(elements)
    upper_cut = int(screen_h * 0.42) if screen_h else 0

    inputs: list[dict] = []
    for element in elements:
        class_name = (element.get("className") or "").lower()
        text = (element.get("text") or "").lower()
        rid = (element.get("resourceId") or "").lower()
        content_desc = (element.get("contentDescription") or "").lower()
        if "edittext" in class_name or "search" in text or "search" in rid or "search" in content_desc:
            inputs.append(element)
    if not inputs:
        return None

    def _looks_like_search_field(elem: dict) -> bool:
        t = (elem.get("text") or "").lower()
        d = (elem.get("contentDescription") or "").lower()
        r = (elem.get("resourceId") or "").lower()
        return "搜索" in t or "search" in t or "搜索" in d or "search" in d or "lba" in r or "search" in r

    hinted = [e for e in inputs if _looks_like_search_field(e)]
    if hinted:
        return pick_first_by_layout(hinted)

    if screen_h > 0 and len(inputs) > 1:
        upper_only = []
        for element in inputs:
            bounds = parse_element_bounds(element)
            if bounds and bounds[1] < upper_cut:
                upper_only.append(element)
        if upper_only:
            return pick_first_by_layout(upper_only)

    if len(inputs) == 1 and screen_h > 0:
        bounds = parse_element_bounds(inputs[0])
        if bounds and bounds[1] > int(screen_h * 0.55):
            return None

    return pick_first_by_layout(inputs)


def find_result_candidates(
    elements: list[dict],
    target_name: str,
    *,
    anchor: dict | None = None,
    is_flat_list: bool = True,
    screen_width: int = 1080,
) -> list[dict]:
    """Find elements matching target_name with bidirectional substring matching.

    Filters results to appear below the anchor element and beyond the left margin.
    """
    matches: list[dict] = []
    anchor_bounds = parse_element_bounds(anchor)
    min_y = anchor_bounds[3] if anchor_bounds else 0
    min_x = int(screen_width * 0.14)

    def append_matches(items: list[dict]) -> None:
        for element in items:
            text = (element.get("text") or "").strip()
            text_normalized = " ".join(text.split()).lower()
            target_normalized = " ".join(target_name.split()).lower()

            if (
                text_normalized != target_normalized
                and target_normalized not in text_normalized
                and text_normalized not in target_normalized
            ):
                if not is_flat_list:
                    append_matches(element.get("children", []))
                continue

            # Skip EditText elements (search input field itself)
            cls = (element.get("className") or "").lower()
            if "edittext" in cls:
                if not is_flat_list:
                    append_matches(element.get("children", []))
                continue

            bounds = parse_element_bounds(element)
            if bounds and bounds[1] < min_y:
                continue
            if bounds and bounds[0] < min_x:
                if not is_flat_list:
                    append_matches(element.get("children", []))
                continue
            matches.append(element)

            if not is_flat_list:
                append_matches(element.get("children", []))

    append_matches(elements)
    return sorted(matches, key=layout_sort_key)


def find_search_button(
    elements: list[dict],
    *,
    text_patterns: tuple[str, ...] = (),
    desc_patterns: tuple[str, ...] = (),
    resource_patterns: tuple[str, ...] = (),
    screen_width: int = 1080,
    screen_height: int = 2340,
    is_flat_list: bool = True,
) -> dict | None:
    """Find a search button with keyword matching + top-right position fallback.

    Excludes close/back buttons from BOTH the keyword match and the position
    heuristic so the rightmost top-right element does not silently win when
    the real magnifier id is missing from the keyword list. Known close ids:

      - ``nd7``: legacy close button.
      - ``nma``: 720x1612 build (2026-05-07) picker close button. Sits at the
        far right of the picker top bar (e.g. bounds=624,56,720,152 on a
        720-wide device); tapping it dismisses the picker and returns to
        chat_screen, breaking the contact-share flow with no recovery.
    """
    _EXCLUDE_RIDS = ("nd7", "nma")

    matches = find_elements_by_keywords(
        elements,
        text_patterns=text_patterns,
        desc_patterns=desc_patterns,
        resource_patterns=resource_patterns,
        is_flat_list=is_flat_list,
    )
    # Filter out excluded resource IDs from keyword matches
    matches = [m for m in matches if not any(ex in (m.get("resourceId") or "").lower() for ex in _EXCLUDE_RIDS)]
    if matches:
        return pick_top_right_element(matches)

    # Header band must include OEM status bars + thick toolbars. The old
    # 8% cutoff (~129px on a 1612-tall phone) dropped real search icons
    # when WeCom moved the picker header down (user saw Contact Card open
    # but automation never tapped the magnifier — keyword miss + empty
    # header_candidates). 22% matches practical toolbar stacks while
    # still excluding the chat list body.
    _header_bottom = max(int(screen_height * 0.22), 180)
    header_candidates = [
        element
        for element in elements
        if isinstance(element, dict)
        and any(token in (element.get("className") or "").lower() for token in ("image", "button", "textview"))
        and (bounds := parse_element_bounds(element))
        and bounds[1] <= _header_bottom
        and bounds[0] >= screen_width * 0.45
        and not any(ex in (element.get("resourceId") or "").lower() for ex in _EXCLUDE_RIDS)
    ]
    if header_candidates:
        return pick_top_right_element(header_candidates)
    return None
