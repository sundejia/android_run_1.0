"""Parse the BOSS Zhipin chat detail page.

Yields an ordered list of ``Message`` records. The recycler view's
parent resource id (``message_row_in`` / ``message_row_out``) gives
us the direction; child resource id distinguishes text vs image.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Literal

_RECYCLER_ID: Final[str] = "com.hpbr.bosszhipin:id/chat_message_recycler"
_ROW_IN_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/message_row_in",)
_ROW_OUT_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/message_row_out",)
_TEXT_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_message_text",)
_IMAGE_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/iv_message_image",)
_PARTNER_ID_BADGE_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_chat_candidate_id_badge",)
_ID_RE: Final[re.Pattern[str]] = re.compile(r"ID[:：]\s*([A-Za-z0-9_-]+)")


class Direction(StrEnum):
    IN = "in"
    OUT = "out"


ContentType = Literal["text", "image", "system"]


@dataclass(frozen=True, slots=True)
class Message:
    direction: Direction
    text: str | None
    content_type: ContentType


def _walk(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    if not isinstance(node, dict):
        return
    yield node
    for child in node.get("children", []) or []:
        yield from _walk(child)


def _find_text(row: dict[str, Any], ids: tuple[str, ...]) -> str | None:
    wanted = set(ids)
    for n in _walk(row):
        if n.get("resourceId") in wanted:
            text = str(n.get("text") or "").strip()
            return text or None
    return None


def _has_id(row: dict[str, Any], ids: tuple[str, ...]) -> bool:
    wanted = set(ids)
    return any(n.get("resourceId") in wanted for n in _walk(row))


def parse_conversation_detail(tree: dict[str, Any]) -> list[Message]:
    if not isinstance(tree, dict) or not tree:
        return []

    in_set = set(_ROW_IN_IDS)
    out_set = set(_ROW_OUT_IDS)
    messages: list[Message] = []

    for node in _walk(tree):
        rid = node.get("resourceId")
        if rid in in_set:
            direction = Direction.IN
        elif rid in out_set:
            direction = Direction.OUT
        else:
            continue

        text = _find_text(node, _TEXT_IDS)
        if text is not None:
            messages.append(Message(direction=direction, text=text, content_type="text"))
            continue
        if _has_id(node, _IMAGE_IDS):
            messages.append(Message(direction=direction, text=None, content_type="image"))
            continue
        # Unknown row type → skip silently.

    return messages


def extract_chat_partner_id(tree: dict[str, Any]) -> str | None:
    if not isinstance(tree, dict) or not tree:
        return None
    badge = _find_text(tree, _PARTNER_ID_BADGE_IDS)
    if not badge:
        return None
    match = _ID_RE.search(badge)
    return match.group(1) if match else None
