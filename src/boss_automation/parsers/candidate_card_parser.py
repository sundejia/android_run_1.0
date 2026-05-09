"""Parse the BOSS Zhipin "推荐牛人" (recommended candidates) feed.

Each card surfaces basic candidate metadata: name, gender/age/education,
current position/company, the source job, and a stable boss_candidate_id.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Final

_CARD_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/candidate_card_root",)
_NAME_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_candidate_name",)
_META_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_candidate_meta",)
_POSITION_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_candidate_position",)
_ID_BADGE_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_candidate_id_badge",)
_MATCH_JOB_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_candidate_match_job",)
_LIVE_LIST_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/rv_list",)
_LIVE_NAME_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_geek_name",)
_LIVE_META_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_work_edu_other_desc",)
_LIVE_CONTENT_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_content",)

_ID_RE: Final[re.Pattern[str]] = re.compile(r"ID[:：]\s*([A-Za-z0-9_-]+)")
_AGE_RE: Final[re.Pattern[str]] = re.compile(r"(\d{1,2})\s*岁")
_EXP_RE: Final[re.Pattern[str]] = re.compile(r"(\d{1,2})\s*年经验")
_GENDER_RE: Final[re.Pattern[str]] = re.compile(r"^\s*(男|女)\b")
_EDU_TOKENS: Final[tuple[str, ...]] = (
    "博士",
    "硕士",
    "本科",
    "大专",
    "高中",
    "中专",
    "MBA",
)
_POSITION_AT_COMPANY_RE: Final[re.Pattern[str]] = re.compile(r"^\s*(?P<position>[^@]+?)\s*@\s*(?P<company>.+?)\s*$")
_LIVE_COMPANY_POSITION_RE: Final[re.Pattern[str]] = re.compile(r"^\s*(?P<company>[^·]+?)\s*·\s*(?P<position>.+?)\s*$")
_MATCH_PREFIX_RE: Final[re.Pattern[str]] = re.compile(r"^(?:应聘|求职期望|最近关注)[:：]\s*(.+?)\s*$")


@dataclass(frozen=True, slots=True)
class CandidateCard:
    boss_candidate_id: str
    name: str
    gender: str | None = None
    age: int | None = None
    education: str | None = None
    experience_years: int | None = None
    current_position: str | None = None
    current_company: str | None = None
    matched_job_title: str | None = None
    tap_x: int | None = None
    tap_y: int | None = None


def _walk(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    if not isinstance(node, dict):
        return
    yield node
    for child in node.get("children", []) or []:
        yield from _walk(child)


def _text(node: dict[str, Any]) -> str:
    return str(node.get("text") or "").strip()


def _node_with_id(card: dict[str, Any], ids: tuple[str, ...]) -> dict[str, Any] | None:
    wanted = set(ids)
    for n in _walk(card):
        if n.get("resourceId") in wanted:
            return n
    return None


def _text_for(card: dict[str, Any], ids: tuple[str, ...]) -> str | None:
    node = _node_with_id(card, ids)
    if node is None:
        return None
    return _text(node) or None


def _texts_for(card: dict[str, Any], ids: tuple[str, ...]) -> list[str]:
    wanted = set(ids)
    texts: list[str] = []
    for node in _walk(card):
        if node.get("resourceId") in wanted:
            text = _text(node)
            if text:
                texts.append(text)
    return texts


def _extract_id(badge: str | None) -> str | None:
    if not badge:
        return None
    m = _ID_RE.search(badge)
    return m.group(1) if m else None


def _parse_meta(meta: str | None) -> tuple[str | None, int | None, str | None, int | None]:
    if not meta:
        return None, None, None, None
    gender_match = _GENDER_RE.search(meta)
    gender = gender_match.group(1) if gender_match else None

    age_match = _AGE_RE.search(meta)
    age = int(age_match.group(1)) if age_match else None

    education = next((token for token in _EDU_TOKENS if token in meta), None)

    exp_match = _EXP_RE.search(meta)
    if exp_match:
        experience_years = int(exp_match.group(1))
    else:
        compact_meta = meta.replace(" ", "")
        simple_exp_match = re.search(r"(\d{1,2})年(?!应届生)", compact_meta)
        experience_years = int(simple_exp_match.group(1)) if simple_exp_match else None

    return gender, age, education, experience_years


def _parse_position(text: str | None) -> tuple[str | None, str | None]:
    if not text:
        return None, None
    match = _POSITION_AT_COMPANY_RE.match(text)
    if match:
        return match.group("position"), match.group("company")
    live_match = _LIVE_COMPANY_POSITION_RE.match(text)
    if live_match:
        return live_match.group("position"), live_match.group("company")
    return text, None


def _parse_match_job(text: str | None) -> str | None:
    if not text:
        return None
    match = _MATCH_PREFIX_RE.match(text)
    return match.group(1) if match else text


def _bounds_key(node: dict[str, Any]) -> str:
    bounds = node.get("boundsInScreen")
    if not isinstance(bounds, dict):
        return ""
    return ",".join(str(bounds.get(k, "")) for k in ("left", "top", "right", "bottom"))


def _fallback_id(*parts: str | None) -> str:
    raw = "|".join(part or "" for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"live:{digest}"


def _tap_target(node: dict[str, Any]) -> tuple[int | None, int | None]:
    bounds = node.get("boundsInScreen")
    if not isinstance(bounds, dict):
        return None, None
    try:
        left = int(bounds["left"])
        top = int(bounds["top"])
        right = int(bounds["right"])
        bottom = int(bounds["bottom"])
    except (KeyError, TypeError, ValueError):
        return None, None
    if right <= left or bottom <= top:
        return None, None
    return (left + right) // 2, (top + bottom) // 2


def _parse_legacy_card(node: dict[str, Any]) -> CandidateCard | None:
    boss_candidate_id = _extract_id(_text_for(node, _ID_BADGE_IDS))
    name = _text_for(node, _NAME_IDS)
    if not boss_candidate_id or not name:
        return None

    gender, age, education, exp_years = _parse_meta(_text_for(node, _META_IDS))
    position, company = _parse_position(_text_for(node, _POSITION_IDS))
    matched_job = _parse_match_job(_text_for(node, _MATCH_JOB_IDS))

    tap_x, tap_y = _tap_target(node)
    return CandidateCard(
        boss_candidate_id=boss_candidate_id,
        name=name,
        gender=gender,
        age=age,
        education=education,
        experience_years=exp_years,
        current_position=position,
        current_company=company,
        matched_job_title=matched_job,
        tap_x=tap_x,
        tap_y=tap_y,
    )


def _parse_live_card(node: dict[str, Any]) -> CandidateCard | None:
    name = _text_for(node, _LIVE_NAME_IDS)
    if not name:
        return None

    meta = _text_for(node, _LIVE_META_IDS)
    gender, age, education, exp_years = _parse_meta(meta)
    content_rows = _texts_for(node, _LIVE_CONTENT_IDS)

    position: str | None = None
    company: str | None = None
    matched_job: str | None = None
    for text in content_rows:
        if matched_job is None and (match := _MATCH_PREFIX_RE.match(text)):
            matched_job = match.group(1)
            continue
        if company is None and (match := _LIVE_COMPANY_POSITION_RE.match(text)):
            company = match.group("company")
            position = match.group("position")

    boss_candidate_id = _extract_id(_text_for(node, _ID_BADGE_IDS)) or _fallback_id(
        name,
        meta,
        company,
        position,
        matched_job,
        _bounds_key(node),
    )

    tap_x, tap_y = _tap_target(node)
    return CandidateCard(
        boss_candidate_id=boss_candidate_id,
        name=name,
        gender=gender,
        age=age,
        education=education,
        experience_years=exp_years,
        current_position=position,
        current_company=company,
        matched_job_title=matched_job,
        tap_x=tap_x,
        tap_y=tap_y,
    )


def _parse_live_flat_cards(nodes: list[dict[str, Any]]) -> list[CandidateCard]:
    cards: list[CandidateCard] = []
    seen: set[str] = set()
    name_indices = [
        index for index, node in enumerate(nodes) if node.get("resourceId") in _LIVE_NAME_IDS and _text(node)
    ]
    for position, name_index in enumerate(name_indices):
        card_nodes = nodes[name_index : name_indices[position + 1] if position + 1 < len(name_indices) else len(nodes)]
        card = _parse_live_card({"children": card_nodes, "boundsInScreen": card_nodes[0].get("boundsInScreen")})
        if card is None or card.boss_candidate_id in seen:
            continue
        seen.add(card.boss_candidate_id)
        cards.append(card)
    return cards


def parse_candidate_feed(tree: dict[str, Any]) -> list[CandidateCard]:
    if not isinstance(tree, dict) or not tree:
        return []

    seen: set[str] = set()
    cards: list[CandidateCard] = []

    legacy_wanted = set(_CARD_IDS)
    live_list_wanted = set(_LIVE_LIST_IDS)
    for node in _walk(tree):
        card: CandidateCard | None = None
        if node.get("resourceId") in legacy_wanted:
            card = _parse_legacy_card(node)
        elif node.get("resourceId") in live_list_wanted:
            for child in node.get("children", []) or []:
                live_card = _parse_live_card(child)
                if live_card is None or live_card.boss_candidate_id in seen:
                    continue
                seen.add(live_card.boss_candidate_id)
                cards.append(live_card)
            continue
        if card is None or card.boss_candidate_id in seen:
            continue
        seen.add(card.boss_candidate_id)
        cards.append(card)

    if cards:
        return cards
    return _parse_live_flat_cards([node for node in _walk(tree) if isinstance(node, dict)])
