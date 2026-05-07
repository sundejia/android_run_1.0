"""Parse the BOSS Zhipin "我的职位" (job list) page.

Pure functions over a UI tree dict. Returns typed ``Job`` records so
downstream code (repository, orchestrator) never has to peek inside
the raw accessibility tree.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

# Resource IDs used to identify each piece of a job card. Update only
# after re-dumping a real device fixture. Selectors are intentionally
# small tuples so a single line of editing handles BOSS app upgrades.
_TAB_OPEN_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tab_open",)
_TAB_CLOSED_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tab_closed",)
_TAB_HIDDEN_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tab_hidden",)
_TAB_DRAFT_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tab_draft",)

_JOB_CARD_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/job_card_root",)
_JOB_TITLE_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_job_title",)
_JOB_SALARY_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_job_salary",)
_JOB_LOCATION_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_job_location",)
_JOB_EXP_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_job_experience",)
_JOB_EDU_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_job_education",)
_JOB_ID_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/tv_job_id_badge",)

_EMPTY_STATE_IDS: Final[tuple[str, ...]] = (
    "com.hpbr.bosszhipin:id/job_list_empty_view",
    "com.hpbr.bosszhipin:id/tv_empty_title",
)

_NEGOTIABLE_SALARY_TOKENS: Final[frozenset[str]] = frozenset({"面议", "不限", "Negotiable"})

# K-style salary like "30K-60K" or "30k-60k·14薪"
_K_RANGE_RE: Final[re.Pattern[str]] = re.compile(r"(\d+)\s*[Kk]\s*-\s*(\d+)\s*[Kk]")
# Numeric range like "8000-12000"
_NUMERIC_RANGE_RE: Final[re.Pattern[str]] = re.compile(r"(\d{4,6})\s*-\s*(\d{4,6})")
# Job ID badge like "ID:JD20260507001"
_JOB_ID_RE: Final[re.Pattern[str]] = re.compile(r"ID[:：]\s*([A-Za-z0-9_-]+)")


class JobStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    HIDDEN = "hidden"
    DRAFT = "draft"


@dataclass(frozen=True, slots=True)
class Job:
    boss_job_id: str
    title: str
    status: JobStatus
    salary_min: int | None = None
    salary_max: int | None = None
    location: str | None = None
    education: str | None = None
    experience: str | None = None


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
    text = _text(node)
    return text or None


def parse_salary_range(raw: str | None) -> tuple[int | None, int | None]:
    """Parse a BOSS-style salary string to a (min, max) integer pair.

    Supports:
    - K-style ranges (``30K-60K``, ``20k-35k·14薪``) → multiplied by 1000.
    - Plain numeric ranges (``8000-12000``).
    - Negotiable / 面议 / 不限 → ``(None, None)``.
    """
    if raw is None:
        return None, None
    text = raw.strip()
    if not text:
        return None, None
    if any(token in text for token in _NEGOTIABLE_SALARY_TOKENS):
        return None, None

    k_match = _K_RANGE_RE.search(text)
    if k_match:
        return int(k_match.group(1)) * 1000, int(k_match.group(2)) * 1000

    n_match = _NUMERIC_RANGE_RE.search(text)
    if n_match:
        return int(n_match.group(1)), int(n_match.group(2))

    return None, None


def _extract_job_id(badge_text: str | None) -> str | None:
    if not badge_text:
        return None
    match = _JOB_ID_RE.search(badge_text)
    return match.group(1) if match else None


def detect_active_tab(tree: dict[str, Any]) -> JobStatus | None:
    """Return the currently-selected job status tab, or ``None``."""
    for node in _walk(tree):
        if not node.get("selected"):
            continue
        rid = node.get("resourceId")
        if rid in _TAB_OPEN_IDS:
            return JobStatus.OPEN
        if rid in _TAB_CLOSED_IDS:
            return JobStatus.CLOSED
        if rid in _TAB_HIDDEN_IDS:
            return JobStatus.HIDDEN
        if rid in _TAB_DRAFT_IDS:
            return JobStatus.DRAFT
    return None


def is_empty_state(tree: dict[str, Any]) -> bool:
    """``True`` when the BOSS empty-state placeholder is visible."""
    wanted = set(_EMPTY_STATE_IDS)
    for node in _walk(tree):
        if node.get("resourceId") in wanted:
            return True
    return False


def parse_job_list(tree: dict[str, Any]) -> list[Job]:
    """Extract every job card from the current page tree.

    The active tab is read from the tree itself so callers can persist
    job status without state-tracking. Cards without a parseable
    ``boss_job_id`` are skipped (avoids polluting the DB with rows that
    can never be deduped).

    Duplicate cards (same ``boss_job_id``) are kept only once — the
    first occurrence wins. This makes the function safe to call on a
    UI tree that includes already-scrolled-past cards.
    """
    if not isinstance(tree, dict) or not tree:
        return []

    status = detect_active_tab(tree) or JobStatus.OPEN
    seen: set[str] = set()
    jobs: list[Job] = []

    wanted_card = set(_JOB_CARD_IDS)
    for node in _walk(tree):
        if node.get("resourceId") not in wanted_card:
            continue

        title = _text_for(node, _JOB_TITLE_IDS)
        if not title:
            continue

        badge_text = _text_for(node, _JOB_ID_IDS)
        boss_job_id = _extract_job_id(badge_text)
        if not boss_job_id or boss_job_id in seen:
            continue
        seen.add(boss_job_id)

        salary_min, salary_max = parse_salary_range(_text_for(node, _JOB_SALARY_IDS))

        jobs.append(
            Job(
                boss_job_id=boss_job_id,
                title=title,
                status=status,
                salary_min=salary_min,
                salary_max=salary_max,
                location=_text_for(node, _JOB_LOCATION_IDS),
                experience=_text_for(node, _JOB_EXP_IDS),
                education=_text_for(node, _JOB_EDU_IDS),
            )
        )
    return jobs
