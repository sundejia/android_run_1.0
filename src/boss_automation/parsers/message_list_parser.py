"""Parse the BOSS Zhipin "消息" (messages list) page."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Final

_ROW_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/conversation_row_root",)
_NAME_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_conversation_name",)
_LAST_MSG_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_conversation_last_msg",)
_ID_BADGE_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_conversation_id_badge",)
_UNREAD_BADGE_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_unread_badge",)

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


def _text(node: dict[str, Any] | None) -> str | None:
    if node is None:
        return None
    text = str(node.get("text") or "").strip()
    return text or None


def parse_message_list(tree: dict[str, Any]) -> list[ConversationSummary]:
    if not isinstance(tree, dict) or not tree:
        return []

    rows: list[ConversationSummary] = []
    seen: set[str] = set()
    wanted = set(_ROW_IDS)
    for node in _walk(tree):
        if node.get("resourceId") not in wanted:
            continue

        badge_text = _text(_find(node, _ID_BADGE_IDS))
        match = _ID_RE.search(badge_text or "")
        if not match:
            continue
        boss_candidate_id = match.group(1)
        if boss_candidate_id in seen:
            continue
        seen.add(boss_candidate_id)

        name = _text(_find(node, _NAME_IDS))
        if not name:
            continue

        unread_text = _text(_find(node, _UNREAD_BADGE_IDS))
        unread_count = int(unread_text) if unread_text and _DIGITS_RE.match(unread_text) else 0

        rows.append(
            ConversationSummary(
                boss_candidate_id=boss_candidate_id,
                candidate_name=name,
                last_message_text=_text(_find(node, _LAST_MSG_IDS)),
                unread_count=unread_count,
            )
        )
    return rows
