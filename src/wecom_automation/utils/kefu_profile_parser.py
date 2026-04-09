"""
Shared kefu profile parsing utilities.

This module extracts the kefu identity block from the current WeCom main-page
profile area and classifies the block into:
- name
- role
- department
- verification status
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from wecom_automation.core.models import KefuInfo

BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
FILE_SIZE_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:k|m|g)b\b", re.IGNORECASE)

ROLE_PATTERNS = (
    "\u7ecf\u7eaa\u4eba",
    "\u5ba2\u670d",
    "\u987e\u95ee",
    "\u9500\u552e",
    "\u52a9\u7406",
    "\u8fd0\u8425",
    "\u5546\u52a1",
    "\u4e3b\u64ad",
)

DEPARTMENT_PATTERNS = (
    "\u5b9e\u9a8c\u5ba4",
    "\u5de5\u4f5c\u5ba4",
    "\u516c\u53f8",
    "\u6587\u5316",
    "\u4f20\u5a92",
    "\u56e2\u961f",
    "\u4e2d\u5fc3",
    "\u96c6\u56e2",
    "\u79d1\u6280",
    "\u90e8\u95e8",
    "\u59d4\u5458\u4f1a",
    "\u6709\u9650",
    "\u4ff1\u4e50\u90e8",
)

VERIFICATION_PATTERNS = (
    "\u672a\u8ba4\u8bc1",
    "\u5df2\u8ba4\u8bc1",
    "\u4f01\u4e1a\u8ba4\u8bc1",
    "\u5b9e\u540d\u8ba4\u8bc1",
)

NOISE_PATTERNS = (
    "messages",
    "\u6d88\u606f",
    "all",
    "\u5168\u90e8",
    "private",
    "\u79c1\u804a",
    "contacts",
    "\u901a\u8baf\u5f55",
    "workspace",
    "\u5de5\u4f5c\u53f0",
    "mail",
    "\u90ae\u4ef6",
    "search",
    "\u641c\u7d22",
    "\u8bbe\u7f6e",
    "setting",
    "full image",
    "image",
    "video",
    "voice",
    "file",
)

NAME_SUFFIXES = (
    "\u5c0f\u53f7",
    "\u5927\u53f7",
    "\u5206\u53f7",
    "\u5206\u8eab",
    "\u6d4b\u8bd5\u53f7",
    "\u5ba2\u670d\u53f7",
)


@dataclass(frozen=True)
class TextNode:
    text: str
    resource_id: str
    class_name: str
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def height(self) -> int:
        return self.y2 - self.y1


@dataclass(frozen=True)
class ProfileBlock:
    lines: tuple[TextNode, ...]
    score: int


@dataclass(frozen=True)
class ParsedKefuProfile:
    name: str
    name_raw: str
    role: str | None = None
    department: str | None = None
    verification_status: str | None = None
    block: ProfileBlock | None = None


def _normalize_tree_roots(tree: Any) -> list[dict[str, Any]]:
    if isinstance(tree, dict):
        return [tree]
    if isinstance(tree, (list, tuple)):
        return [node for node in tree if isinstance(node, dict)]
    return []


def _iter_nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [node]
    for child in node.get("children") or []:
        if isinstance(child, dict):
            nodes.extend(_iter_nodes(child))
    return nodes


def _extract_bounds(node: dict[str, Any]) -> tuple[int, int, int, int] | None:
    for key in ("bounds", "visibleBounds", "boundsInScreen", "boundsInParent", "rect"):
        value = node.get(key)
        if isinstance(value, str):
            match = BOUNDS_RE.match(value)
            if match:
                return tuple(map(int, match.groups()))
        elif isinstance(value, dict):
            try:
                x1 = int(value.get("left", value.get("x", value.get("x1", 0))))
                y1 = int(value.get("top", value.get("y", value.get("y1", 0))))
                x2 = int(value.get("right", value.get("x2", x1 + value.get("width", 0))))
                y2 = int(value.get("bottom", value.get("y2", y1 + value.get("height", 0))))
                return (x1, y1, x2, y2)
            except (TypeError, ValueError):
                continue
        elif isinstance(value, (list, tuple)) and len(value) >= 4:
            try:
                return tuple(int(part) for part in value[:4])
            except (TypeError, ValueError):
                continue
    return None


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(pattern.lower() in lowered for pattern in patterns)


def _looks_like_role(text: str) -> bool:
    return _contains_any(text, ROLE_PATTERNS)


def _looks_like_department(text: str) -> bool:
    return _contains_any(text, DEPARTMENT_PATTERNS)


def _looks_like_verification(text: str) -> bool:
    return _contains_any(text, VERIFICATION_PATTERNS)


def _looks_like_noise(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 2:
        return True
    if stripped.isdigit():
        return True
    if "@" in stripped:
        return True
    if FILE_SIZE_RE.search(stripped):
        return True
    return _contains_any(stripped, NOISE_PATTERNS)


def _looks_like_name(text: str) -> bool:
    stripped = text.strip()
    if _looks_like_noise(stripped):
        return False
    if _looks_like_role(stripped) or _looks_like_department(stripped) or _looks_like_verification(stripped):
        return False
    if len(stripped) > 24:
        return False
    return True


def _normalize_name(text: str) -> str:
    normalized = text.strip().rstrip("> ")
    for suffix in NAME_SUFFIXES:
        if normalized.endswith(suffix) and len(normalized) > len(suffix) + 1:
            return normalized[: -len(suffix)].strip()
    return normalized


def _collect_text_nodes(tree: Any) -> list[TextNode]:
    nodes: list[TextNode] = []
    for root in _normalize_tree_roots(tree):
        for node in _iter_nodes(root):
            text = (node.get("text") or "").strip()
            if not text:
                continue

            bounds = _extract_bounds(node)
            if not bounds:
                continue

            x1, y1, x2, y2 = bounds
            nodes.append(
                TextNode(
                    text=text,
                    resource_id=(node.get("resourceId") or "").strip(),
                    class_name=(node.get("className") or "").strip(),
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                )
            )

    nodes.sort(key=lambda item: (item.y1, item.x1, item.x2, item.text))
    return nodes


def _score_block(lines: list[TextNode]) -> int:
    if not lines:
        return -1

    score = 0
    first = lines[0]
    first_text = first.text.strip()

    if 2 <= len(lines) <= 4:
        score += 25
    elif len(lines) == 1:
        score += 5

    if 100 <= first.y1 <= 320:
        score += 20
    elif first.y1 < 100:
        score += 8

    if first.x1 <= 420:
        score += 10

    if _looks_like_name(first_text):
        score += 35

    if 2 <= len(first_text) <= 20:
        score += 10

    if 28 <= first.height <= 90:
        score += 10

    if any(_looks_like_role(line.text) for line in lines[1:]):
        score += 25

    if any(_looks_like_department(line.text) for line in lines[1:]):
        score += 20

    if any(_looks_like_verification(line.text) for line in lines[1:]):
        score += 5

    x_positions = [line.x1 for line in lines]
    if max(x_positions) - min(x_positions) <= 72:
        score += 10

    if len(lines) >= 2:
        gaps = [curr.y1 - prev.y1 for prev, curr in zip(lines, lines[1:])]
        if all(12 <= gap <= 96 for gap in gaps):
            score += 10

    return score


def _build_profile_blocks(text_nodes: list[TextNode], *, max_x: int, min_y: int, max_y: int) -> list[ProfileBlock]:
    visible_nodes = [
        node
        for node in text_nodes
        if node.x1 <= max_x and min_y <= node.y1 <= max_y and len(node.text.strip()) <= 40 and not _looks_like_noise(node.text)
    ]

    blocks: list[ProfileBlock] = []
    for index, node in enumerate(visible_nodes):
        if not _looks_like_name(node.text):
            continue

        lines = [node]
        last_y = node.y1

        for other in visible_nodes[index + 1 :]:
            if other.y1 < node.y1:
                continue
            if other.y1 - node.y1 > 220:
                break
            if other.y1 - last_y < 12:
                continue
            if abs(other.x1 - node.x1) > 96:
                continue
            lines.append(other)
            last_y = other.y1
            if len(lines) == 4:
                break

        blocks.append(ProfileBlock(lines=tuple(lines), score=_score_block(lines)))

    blocks.sort(key=lambda block: (-block.score, block.lines[0].y1, block.lines[0].x1))
    return blocks


def parse_kefu_profile(
    tree: Any,
    *,
    max_x: int = 700,
    min_y: int = 80,
    max_y: int = 900,
) -> ParsedKefuProfile | None:
    text_nodes = _collect_text_nodes(tree)
    if not text_nodes:
        return None

    blocks = _build_profile_blocks(text_nodes, max_x=max_x, min_y=min_y, max_y=max_y)
    if not blocks:
        return None

    chosen = blocks[0]
    name_raw: str | None = None
    role: str | None = None
    department: str | None = None
    verification: str | None = None

    for line in chosen.lines:
        text = line.text.strip()
        if _looks_like_verification(text) and not verification:
            verification = text
            continue
        if _looks_like_role(text) and not role:
            role = text
            continue
        if _looks_like_department(text) and not department:
            department = text
            continue
        if not name_raw and _looks_like_name(text):
            name_raw = text

    if not name_raw:
        for line in chosen.lines:
            text = line.text.strip()
            if not _looks_like_role(text) and not _looks_like_department(text) and not _looks_like_verification(text):
                name_raw = text
                break

    if not name_raw:
        return None

    normalized_name = _normalize_name(name_raw)
    if not normalized_name:
        return None

    return ParsedKefuProfile(
        name=normalized_name,
        name_raw=name_raw,
        role=role,
        department=department,
        verification_status=verification,
        block=chosen,
    )


def extract_kefu_from_tree(
    tree: Any,
    *,
    max_x: int = 700,
    min_y: int = 80,
    max_y: int = 900,
) -> KefuInfo | None:
    parsed = parse_kefu_profile(tree, max_x=max_x, min_y=min_y, max_y=max_y)
    if not parsed:
        return None

    return KefuInfo(
        name=parsed.name,
        department=parsed.department,
        verification_status=parsed.verification_status,
    )
