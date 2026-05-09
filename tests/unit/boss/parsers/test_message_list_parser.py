"""TDD tests for boss_automation/parsers/message_list_parser.py."""

from __future__ import annotations

from pathlib import Path

from boss_automation.parsers.message_list_parser import (
    ConversationSummary,
    parse_message_list,
)
from tests._fixtures.loader import load_fixture

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "boss"


def _tree(label: str) -> dict:
    return load_fixture(FIXTURE_ROOT / "messages_list" / f"{label}.json").ui_tree


def test_parses_live_may_2026_messages_list() -> None:
    rows = parse_message_list(_tree("e2e_20260508_retry"))

    names = [r.candidate_name for r in rows]
    assert "刘女士" in names
    assert "李先生" in names
    li = next(r for r in rows if r.candidate_name == "李先生")
    assert li.boss_candidate_id.startswith("live:")
    assert li.unread_count == 1
    assert li.last_message_text == "我对您发布的这个职位很感兴趣，能否见面详聊呢？"


def test_parses_three_conversations() -> None:
    rows = parse_message_list(_tree("with_unread"))
    assert len(rows) == 3
    assert all(isinstance(r, ConversationSummary) for r in rows)


def test_extracts_full_metadata_for_first_row() -> None:
    rows = parse_message_list(_tree("with_unread"))
    first = rows[0]
    assert first.boss_candidate_id == "CAND20260507A"
    assert first.candidate_name == "李雷"
    assert first.last_message_text == "您好，请问还需要 Java 工程师吗？"
    assert first.unread_count == 2


def test_unread_count_defaults_to_zero_when_missing() -> None:
    rows = parse_message_list(_tree("with_unread"))
    assert rows[1].unread_count == 0


def test_handles_empty_tree() -> None:
    assert parse_message_list({}) == []


def test_skips_rows_without_id() -> None:
    tree = {
        "children": [
            {
                "resourceId": "com.hpbr.bosszhipin:id/conversation_list_recycler",
                "children": [
                    {
                        "resourceId": "com.hpbr.bosszhipin:id/conversation_row_root",
                        "children": [
                            {
                                "resourceId": "com.hpbr.bosszhipin:id/tv_conversation_name",
                                "text": "noid",
                            }
                        ],
                    }
                ],
            }
        ]
    }
    assert parse_message_list(tree) == []
