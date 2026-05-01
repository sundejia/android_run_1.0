"""
Pure helper functions for UI element analysis.

Extracted from WeComService to enable reuse across strategy classes
without coupling to the full service. All functions are stateless.
"""

from __future__ import annotations

import re


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


def find_elements_by_keywords(
    elements: list[dict],
    *,
    text_patterns: tuple[str, ...] = (),
    desc_patterns: tuple[str, ...] = (),
    resource_patterns: tuple[str, ...] = (),
    is_flat_list: bool = True,
) -> list[dict]:
    """Find elements whose text, contentDescription, or resourceId matches any pattern."""
    matches: list[dict] = []

    def walk(items: list[dict]) -> None:
        for element in items:
            if not isinstance(element, dict):
                continue
            text = (element.get("text") or "").lower()
            desc = (element.get("contentDescription") or "").lower()
            rid = (element.get("resourceId") or "").lower()

            if (
                any(pattern.lower() in text for pattern in text_patterns)
                or any(pattern.lower() in desc for pattern in desc_patterns)
                or any(pattern.lower() in rid for pattern in resource_patterns)
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


def find_search_input(elements: list[dict]) -> dict | None:
    """Find a search input field (EditText or search-keyword element)."""
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
    """Find a search button with keyword matching + top-right position fallback."""
    matches = find_elements_by_keywords(
        elements,
        text_patterns=text_patterns,
        desc_patterns=desc_patterns,
        resource_patterns=resource_patterns,
        is_flat_list=is_flat_list,
    )
    if matches:
        return pick_top_right_element(matches)

    header_candidates = [
        element
        for element in elements
        if isinstance(element, dict)
        and any(token in (element.get("className") or "").lower() for token in ("image", "button", "textview"))
        and (bounds := parse_element_bounds(element))
        and bounds[1] <= screen_height * 0.08
        and bounds[0] >= screen_width * 0.52
    ]
    if header_candidates:
        return pick_top_right_element(header_candidates)
    return None
