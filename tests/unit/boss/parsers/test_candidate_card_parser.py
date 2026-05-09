"""TDD tests for boss_automation/parsers/candidate_card_parser.py."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from boss_automation.parsers.candidate_card_parser import (
    CandidateCard,
    parse_candidate_feed,
)
from tests._fixtures.loader import load_fixture

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "boss"


def _tree(label: str) -> dict:
    return load_fixture(FIXTURE_ROOT / "candidates_feed" / f"{label}.json").ui_tree


def _runtime_tree(label: str) -> dict:
    return load_fixture(FIXTURE_ROOT / "runtime_probe" / f"{label}.json").ui_tree


class TestParseCandidateFeed:
    def test_yields_two_cards_from_feed(self) -> None:
        cards = parse_candidate_feed(_tree("feed_with_cards"))
        assert len(cards) == 2
        assert all(isinstance(c, CandidateCard) for c in cards)

    def test_first_card_extracts_full_metadata(self) -> None:
        cards = parse_candidate_feed(_tree("feed_with_cards"))
        first = cards[0]
        assert first.boss_candidate_id == "CAND20260507A"
        assert first.name == "李雷"
        assert first.gender == "男"
        assert first.age == 28
        assert first.education == "本科"
        assert first.experience_years == 5
        assert first.current_position == "高级Java工程师"
        assert first.current_company == "字节跳动"
        assert first.matched_job_title == "Senior Backend Engineer"

    def test_second_card_handles_female_and_master(self) -> None:
        cards = parse_candidate_feed(_tree("feed_with_cards"))
        second = cards[1]
        assert second.boss_candidate_id == "CAND20260507B"
        assert second.name == "韩梅梅"
        assert second.gender == "女"
        assert second.education == "硕士"
        assert second.experience_years == 3
        assert second.current_position == "前端工程师"
        assert second.current_company == "美团"

    def test_handles_empty_tree(self) -> None:
        assert parse_candidate_feed({}) == []

    def test_skips_card_without_id(self) -> None:
        # Hand-craft a tree with one missing id badge.
        tree = {
            "className": "android.widget.FrameLayout",
            "children": [
                {
                    "resourceId": "com.hpbr.bosszhipin:id/candidate_feed_recycler",
                    "children": [
                        {
                            "resourceId": "com.hpbr.bosszhipin:id/candidate_card_root",
                            "children": [
                                {
                                    "resourceId": "com.hpbr.bosszhipin:id/tv_candidate_name",
                                    "text": "无ID候选人",
                                },
                            ],
                        },
                    ],
                },
            ],
        }
        assert parse_candidate_feed(tree) == []

    def test_parses_live_may_2026_candidate_feed(self) -> None:
        cards = parse_candidate_feed(_runtime_tree("retry_20260508_185850"))

        assert [c.name for c in cards[:2]] == ["王卓", "吴思彤"]
        first = cards[0]
        assert first.boss_candidate_id.startswith("live:")
        assert first.education == "大专"
        assert first.experience_years == 10
        assert first.current_company == "飞趣游戏"
        assert first.current_position == "用户运营"
        assert first.matched_job_title == "经纪人/星探"

        reparsed = parse_candidate_feed(_runtime_tree("retry_20260508_185850"))
        assert reparsed[0].boss_candidate_id == first.boss_candidate_id


class TestCandidateCardDataclass:
    def test_is_frozen(self) -> None:
        c = CandidateCard(boss_candidate_id="X", name="A")
        with pytest.raises((AttributeError, FrozenInstanceError)):
            c.name = "B"  # type: ignore[misc]

    def test_optional_fields_default_to_none(self) -> None:
        c = CandidateCard(boss_candidate_id="X", name="A")
        assert c.age is None
        assert c.gender is None
        assert c.education is None
        assert c.experience_years is None
