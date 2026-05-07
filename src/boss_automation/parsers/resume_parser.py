"""Parse the BOSS Zhipin resume view."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Final

_NAME_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_resume_name",)
_ID_BADGE_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_resume_id_badge",)
_AGE_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_resume_age",)
_EDU_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_resume_education",)
_CURRENT_POS_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_resume_current_position",)
_EXPECTED_SAL_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_resume_expected_salary",)
_EXPECTED_LOC_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_resume_expected_location",)
_SUMMARY_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_resume_summary",)

_ID_RE: Final[re.Pattern[str]] = re.compile(r"ID[:：]\s*([A-Za-z0-9_-]+)")
_AGE_RE: Final[re.Pattern[str]] = re.compile(r"(\d{1,2})\s*岁")
_POS_AT_CO_RE: Final[re.Pattern[str]] = re.compile(r"^\s*(?P<position>[^@]+?)\s*@\s*(?P<company>.+?)\s*$")
_EXPECTED_SAL_RE: Final[re.Pattern[str]] = re.compile(r"期望薪资[:：]\s*(.+)")
_EXPECTED_LOC_RE: Final[re.Pattern[str]] = re.compile(r"期望地[:：]\s*(.+)")


@dataclass(frozen=True, slots=True)
class ResumeSnapshot:
    boss_candidate_id: str | None
    name: str
    age: int | None
    education: str | None
    current_position: str | None
    current_company: str | None
    expected_salary: str | None
    expected_location: str | None
    summary: str | None


def _walk(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    if not isinstance(node, dict):
        return
    yield node
    for child in node.get("children", []) or []:
        yield from _walk(child)


def _find_text(tree: dict[str, Any], ids: tuple[str, ...]) -> str | None:
    wanted = set(ids)
    for n in _walk(tree):
        if n.get("resourceId") in wanted:
            text = str(n.get("text") or "").strip()
            return text or None
    return None


def parse_resume(tree: dict[str, Any]) -> ResumeSnapshot | None:
    if not isinstance(tree, dict) or not tree:
        return None
    name = _find_text(tree, _NAME_IDS)
    if not name:
        return None

    badge = _find_text(tree, _ID_BADGE_IDS)
    boss_candidate_id = None
    if badge:
        m = _ID_RE.search(badge)
        if m:
            boss_candidate_id = m.group(1)

    age_text = _find_text(tree, _AGE_IDS)
    age = None
    if age_text:
        m = _AGE_RE.search(age_text)
        if m:
            age = int(m.group(1))

    pos_text = _find_text(tree, _CURRENT_POS_IDS)
    position, company = (None, None)
    if pos_text:
        m = _POS_AT_CO_RE.match(pos_text)
        if m:
            position, company = m.group("position"), m.group("company")
        else:
            position = pos_text

    salary_text = _find_text(tree, _EXPECTED_SAL_IDS)
    expected_salary = None
    if salary_text:
        m = _EXPECTED_SAL_RE.match(salary_text)
        expected_salary = m.group(1) if m else salary_text

    loc_text = _find_text(tree, _EXPECTED_LOC_IDS)
    expected_location = None
    if loc_text:
        m = _EXPECTED_LOC_RE.match(loc_text)
        expected_location = m.group(1) if m else loc_text

    return ResumeSnapshot(
        boss_candidate_id=boss_candidate_id,
        name=name,
        age=age,
        education=_find_text(tree, _EDU_IDS),
        current_position=position,
        current_company=company,
        expected_salary=expected_salary,
        expected_location=expected_location,
        summary=_find_text(tree, _SUMMARY_IDS),
    )
