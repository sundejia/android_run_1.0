"""
Kefu (Customer Service Representative) Information Extraction.

This module provides utilities to extract 客服 information from WeCom UI trees.
Extracted from the original get_kefu_name.py standalone script.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from wecom_automation.core.models import KefuInfo
    from wecom_automation.utils.kefu_profile_parser import extract_kefu_from_tree as _shared_extract_kefu_from_tree
except ImportError:
    from dataclasses import dataclass

    @dataclass
    class KefuInfo:
        """Information about the 客服 (Customer Service Representative)."""

        name: str
        department: Optional[str] = None
        verification_status: Optional[str] = None

    _shared_extract_kefu_from_tree = None


def _collect_all_nodes(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Flatten the UI tree into a list of all nodes.

    Args:
        node: Root node of the tree

    Returns:
        List of all nodes including the root and all descendants
    """
    results = [node]
    children = node.get("children") or []
    for child in children:
        if isinstance(child, dict):
            results.extend(_collect_all_nodes(child))
    return results


def _get_node_bounds(node: Dict[str, Any]) -> Optional[Tuple[int, int, int, int]]:
    """
    Get bounds from a node as (x1, y1, x2, y2) tuple.

    Args:
        node: UI tree node

    Returns:
        Tuple of (x1, y1, x2, y2) or None if bounds not found/parseable
    """
    bounds_keys = ["bounds", "visibleBounds", "boundsInScreen", "boundsInParent", "rect"]

    for key in bounds_keys:
        bounds = node.get(key)
        if bounds:
            if isinstance(bounds, str) and "[" in bounds:
                match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                if match:
                    return tuple(map(int, match.groups()))
            if isinstance(bounds, dict):
                x1 = bounds.get("left", bounds.get("x", bounds.get("x1", 0)))
                y1 = bounds.get("top", bounds.get("y", bounds.get("y1", 0)))
                x2 = bounds.get("right", bounds.get("x2", x1 + bounds.get("width", 0)))
                y2 = bounds.get("bottom", bounds.get("y2", y1 + bounds.get("height", 0)))
                return (x1, y1, x2, y2)
            if isinstance(bounds, (list, tuple)) and len(bounds) >= 4:
                return tuple(bounds[:4])

    return None


def extract_kefu_from_tree(tree: Any, debug: bool = False) -> Optional[KefuInfo]:
    """
    Extract the 客服 name from the UI tree.

    The 客服 name is typically found in the upper-left area of the screen,
    typically on WeCom's main page in the profile/sidebar region.

    Args:
        tree: Raw UI accessibility tree
        debug: Print debug information (default: False)

    Returns:
        KefuInfo with extracted name, department, and verification status,
        or None if not found
    """
    if _shared_extract_kefu_from_tree is not None:
        return _shared_extract_kefu_from_tree(tree, max_x=700, min_y=80, max_y=900)

    if not tree:
        return None

    roots = [tree] if isinstance(tree, dict) else list(tree) if isinstance(tree, (list, tuple)) else []

    text_elements = []

    for root in roots:
        all_nodes = _collect_all_nodes(root)

        for node in all_nodes:
            text = (node.get("text") or "").strip()
            if not text:
                continue

            bounds = _get_node_bounds(node)
            if not bounds:
                continue

            x1, y1, x2, y2 = bounds

            # Only consider elements in the left area (profile panel region)
            if x1 > 500:
                continue

            text_elements.append(
                {
                    "text": text,
                    "bounds": bounds,
                    "y": y1,
                    "x": x1,
                    "height": y2 - y1,
                }
            )

    if not text_elements:
        return None

    # Sort by Y position (top to bottom)
    text_elements.sort(key=lambda e: e["y"])

    if debug:
        print("\nText elements found in profile area:")
        for elem in text_elements:
            print(f"  y={elem['y']:4d}, x={elem['x']:4d}, h={elem['height']:3d}: '{elem['text']}'")

    # Patterns to exclude from name candidates
    exclude_patterns = (
        "消息",
        "messages",
        "全部",
        "all",
        "私聊",
        "private",
        "日程",
        "schedule",
        "calendar",
        "会议",
        "meeting",
        "未认证",
        "已认证",
        "认证",
        "@",
        "＠",
    )

    # Patterns that indicate department
    department_patterns = ("实验室", "部门", "部", "组", "team", "dept")

    # Patterns that indicate verification status
    verification_patterns = ("未认证", "已认证")

    name_candidates = []
    department = None
    verification = None

    for elem in text_elements:
        text = elem["text"]
        text_lower = text.lower()
        y = elem["y"]

        # Skip elements too high (status bar) or too low
        if y < 100 or y > 600:
            continue

        # Check for verification status
        for vp in verification_patterns:
            if vp in text:
                verification = text
                break

        # Check for department
        for dp in department_patterns:
            if dp.lower() in text_lower:
                department = text
                break

        # Check if this should be excluded
        is_excluded = any(ep.lower() in text_lower or text_lower in ep.lower() for ep in exclude_patterns)

        if is_excluded:
            continue

        # Name length check (2-30 characters)
        if len(text) < 2 or len(text) > 30:
            continue

        name_candidates.append(elem)

    if debug:
        print(f"\nName candidates: {[c['text'] for c in name_candidates]}")
        print(f"Department: {department}")
        print(f"Verification: {verification}")

    # Score name candidates
    best_name = None
    best_score = -1

    for candidate in name_candidates:
        text = candidate["text"]
        y = candidate["y"]
        height = candidate["height"]

        score = 0

        # Prefer elements in the profile area (around y=150-400)
        if 150 <= y <= 400:
            score += 20
        elif y < 150:
            score += 5
        else:
            score += 10

        # Prefer typical name text height
        if 30 <= height <= 80:
            score += 15

        # Prefer reasonable name length
        if 2 <= len(text) <= 15:
            score += 10

        # Clean up trailing arrows (clickable name indicator)
        clean_text = text.rstrip(">》 ")
        if clean_text != text:
            score += 5

        if score > best_score:
            best_score = score
            best_name = clean_text

    if best_name:
        return KefuInfo(
            name=best_name,
            department=department,
            verification_status=verification,
        )

    return None
