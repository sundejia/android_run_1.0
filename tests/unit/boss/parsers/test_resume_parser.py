"""TDD tests for boss_automation/parsers/resume_parser.py."""

from __future__ import annotations

from pathlib import Path

from boss_automation.parsers.resume_parser import (
    ResumeSnapshot,
    parse_resume,
)
from tests._fixtures.loader import load_fixture

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "boss"


def _tree(label: str) -> dict:
    return load_fixture(FIXTURE_ROOT / "resume_view" / f"{label}.json").ui_tree


def test_extracts_full_resume() -> None:
    snap = parse_resume(_tree("full_resume"))
    assert snap is not None
    assert isinstance(snap, ResumeSnapshot)
    assert snap.boss_candidate_id == "CAND20260507A"
    assert snap.name == "李雷"
    assert snap.age == 28
    assert snap.education == "本科 · 清华大学"
    assert snap.current_position == "高级Java工程师"
    assert snap.current_company == "字节跳动"
    assert snap.expected_salary == "40K-60K"
    assert snap.expected_location == "上海/北京"
    assert "微服务" in (snap.summary or "")


def test_returns_none_for_empty_tree() -> None:
    assert parse_resume({}) is None


def test_returns_none_when_no_resume_marker() -> None:
    assert parse_resume({"children": []}) is None
