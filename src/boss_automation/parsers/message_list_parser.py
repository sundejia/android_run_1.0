"""Parse the BOSS Zhipin "消息" (messages list) page."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Final

_ROW_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/conversation_row_root",)
_NAME_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_conversation_name",)
_LAST_MSG_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_conversation_last_msg",)
_ID_BADGE_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_conversation_id_badge",)
_UNREAD_BADGE_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_unread_badge",)
_LIVE_LIST_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/recyclerView",)
_LIVE_NAME_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_name",)
_LIVE_POSITION_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_position",)
_LIVE_LAST_MSG_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_msg",)

_ID_RE: Final[re.Pattern[str]] = re.compile(r"ID[:：]\s*([A-Za-z0-9_-]+)")
_DIGITS_RE: Final[re.Pattern[str]] = re.compile(r"^\d+$")


@dataclass(frozen=True, slots=True)
class ConversationSummary:
    boss_candidate_id: str
    candidate_name: str
    last_message_text: str | None
    unread_count: int


def _walk(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    if not isinstance(node, dict):
        return
    yield node
    for child in node.get("children", []) or []:
        yield from _walk(child)


def _find(card: dict[str, Any], ids: tuple[str, ...]) -> dict[str, Any] | None:
    wanted = set(ids)
    for n in _walk(card):
        if n.get("resourceId") in wanted:
            return n
    return None


def _find_direct(card: dict[str, Any], ids: tuple[str, ...]) -> dict[str, Any] | None:
    wanted = set(ids)
    for n in card.get("children", []) or []:
        if isinstance(n, dict) and n.get("resourceId") in wanted:
            return n
    return None


def _text(node: dict[str, Any] | None) -> str | None:
    if node is None:
        return None
    text = str(node.get("text") or "").strip()
    return text or None


def _bounds(node: dict[str, Any]) -> dict[str, int] | None:
    bounds = node.get("boundsInScreen")
    if not isinstance(bounds, dict):
        return None
    if not all(k in bounds for k in ("left", "top", "right", "bottom")):
        return None
    return bounds


def _fallback_id(*parts: str | None) -> str:
    raw = "|".join(part or "" for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"live:{digest}"


def _parse_legacy_row(node: dict[str, Any]) -> ConversationSummary | None:
    badge_text = _text(_find(node, _ID_BADGE_IDS))
    match = _ID_RE.search(badge_text or "")
    if not match:
        return None
    boss_candidate_id = match.group(1)

    name = _text(_find(node, _NAME_IDS))
    if not name:
        return None

    unread_text = _text(_find(node, _UNREAD_BADGE_IDS))
    unread_count = int(unread_text) if unread_text and _DIGITS_RE.match(unread_text) else 0
    return ConversationSummary(
        boss_candidate_id=boss_candidate_id,
        candidate_name=name,
        last_message_text=_text(_find(node, _LAST_MSG_IDS)),
        unread_count=unread_count,
    )


def _parse_live_row(node: dict[str, Any]) -> ConversationSummary | None:
    name = _text(_find_direct(node, _LIVE_NAME_IDS))
    if not name:
        return None
    position = _text(_find_direct(node, _LIVE_POSITION_IDS))
    last_message = _text(_find_direct(node, _LIVE_LAST_MSG_IDS))
    row_bounds = _bounds(node)
    unread_count = 0
    if row_bounds:
        avatar_left = row_bounds["left"]
        avatar_right = row_bounds["left"] + 150
        row_top = row_bounds["top"]
        row_bottom = row_bounds["bottom"]
        for child in node.get("children", []) or []:
            if not isinstance(child, dict):
                continue
            text = _text(child)
            bounds = _bounds(child)
            if not text or not bounds or not _DIGITS_RE.match(text):
                continue
            if avatar_left <= bounds["left"] <= avatar_right and row_top <= bounds["top"] <= row_bottom:
                unread_count = int(text)
                break

    return ConversationSummary(
        boss_candidate_id=_fallback_id(name, position, last_message, str(row_bounds)),
        candidate_name=name,
        last_message_text=last_message,
        unread_count=unread_count,
    )


def _parse_live_flat_rows(nodes: list[dict[str, Any]]) -> list[ConversationSummary]:
    rows: list[ConversationSummary] = []
    seen: set[str] = set()
    name_indices = [
        index for index, node in enumerate(nodes) if node.get("resourceId") in _LIVE_NAME_IDS and _text(node)
    ]
    for position, name_index in enumerate(name_indices):
        row_nodes = nodes[name_index : name_indices[position + 1] if position + 1 < len(name_indices) else len(nodes)]
        row = _parse_live_flat_row(row_nodes, nodes[:name_index])
        if row is None or row.boss_candidate_id in seen:
            continue
        seen.add(row.boss_candidate_id)
        rows.append(row)
    return rows


def _parse_live_flat_row(row_nodes: list[dict[str, Any]], previous_nodes: list[dict[str, Any]]) -> ConversationSummary | None:
    name = _text(row_nodes[0]) if row_nodes else None
    if not name:
        return None
    position = _text(next((n for n in row_nodes if n.get("resourceId") in _LIVE_POSITION_IDS), None))
    last_message = _text(next((n for n in row_nodes if n.get("resourceId") in _LIVE_LAST_MSG_IDS), None))
    name_bounds = _bounds(row_nodes[0])
    unread_count = 0
    if name_bounds:
        for node in reversed(previous_nodes[-4:]):
            text = _text(node)
            bounds = _bounds(node)
            if not text or not bounds or not _DIGITS_RE.match(text):
                continue
            if bounds["right"] <= name_bounds["left"] and abs(bounds["top"] - name_bounds["top"]) <= 40:
                unread_count = int(text)
                break
    return ConversationSummary(
        boss_candidate_id=_fallback_id(name, position, last_message, str(name_bounds)),
        candidate_name=name,
        last_message_text=last_message,
        unread_count=unread_count,
    )


def parse_message_list(tree: dict[str, Any]) -> list[ConversationSummary]:
    if not isinstance(tree, dict) or not tree:
        return []

    rows: list[ConversationSummary] = []
    seen: set[str] = set()
    legacy_wanted = set(_ROW_IDS)
    live_list_wanted = set(_LIVE_LIST_IDS)
    for node in _walk(tree):
        row: ConversationSummary | None = None
        if node.get("resourceId") in legacy_wanted:
            row = _parse_legacy_row(node)
        elif node.get("resourceId") in live_list_wanted:
            for child in node.get("children", []) or []:
                if not isinstance(child, dict):
                    continue
                live_row = _parse_live_row(child)
                if live_row is None or live_row.boss_candidate_id in seen:
                    continue
                seen.add(live_row.boss_candidate_id)
                rows.append(live_row)
            continue
        if row is None or row.boss_candidate_id in seen:
            continue
        seen.add(row.boss_candidate_id)
        rows.append(row)
    if rows:
        return rows
    return _parse_live_flat_rows([node for node in _walk(tree) if isinstance(node, dict)])
