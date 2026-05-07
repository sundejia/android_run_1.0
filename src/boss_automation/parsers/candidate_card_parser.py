"""Parse the BOSS Zhipin "推荐牛人" (recommended candidates) feed.

Each card surfaces basic candidate metadata: name, gender/age/education,
current position/company, the source job, and a stable boss_candidate_id.
"""

from __future__ import annotations

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
_MATCH_PREFIX_RE: Final[re.Pattern[str]] = re.compile(r"^应聘[:：]\s*(.+?)\s*$")


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
    experience_years = int(exp_match.group(1)) if exp_match else None

    return gender, age, education, experience_years


def _parse_position(text: str | None) -> tuple[str | None, str | None]:
    if not text:
        return None, None
    match = _POSITION_AT_COMPANY_RE.match(text)
    if not match:
        return text, None
    return match.group("position"), match.group("company")


def _parse_match_job(text: str | None) -> str | None:
    if not text:
        return None
    match = _MATCH_PREFIX_RE.match(text)
    return match.group(1) if match else text


def parse_candidate_feed(tree: dict[str, Any]) -> list[CandidateCard]:
    if not isinstance(tree, dict) or not tree:
        return []

    seen: set[str] = set()
    cards: list[CandidateCard] = []

    wanted = set(_CARD_IDS)
    for node in _walk(tree):
        if node.get("resourceId") not in wanted:
            continue

        boss_candidate_id = _extract_id(_text_for(node, _ID_BADGE_IDS))
        name = _text_for(node, _NAME_IDS)
        if not boss_candidate_id or not name:
            continue
        if boss_candidate_id in seen:
            continue
        seen.add(boss_candidate_id)

        gender, age, education, exp_years = _parse_meta(_text_for(node, _META_IDS))
        position, company = _parse_position(_text_for(node, _POSITION_IDS))
        matched_job = _parse_match_job(_text_for(node, _MATCH_JOB_IDS))

        cards.append(
            CandidateCard(
                boss_candidate_id=boss_candidate_id,
                name=name,
                gender=gender,
                age=age,
                education=education,
                experience_years=exp_years,
                current_position=position,
                current_company=company,
                matched_job_title=matched_job,
            )
        )
    return cards
