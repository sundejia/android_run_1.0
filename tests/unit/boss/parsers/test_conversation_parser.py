"""TDD tests for boss_automation/parsers/conversation_parser.py."""

from __future__ import annotations

from pathlib import Path

from boss_automation.parsers.conversation_parser import (
    Direction,
    Message,
    extract_chat_partner_id,
    parse_conversation_detail,
)
from tests._fixtures.loader import load_fixture

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "boss"


def _tree(label: str) -> dict:
    return load_fixture(FIXTURE_ROOT / "conversation_detail" / f"{label}.json").ui_tree


def test_text_only_three_messages() -> None:
    msgs = parse_conversation_detail(_tree("text_only"))
    assert len(msgs) == 3
    assert msgs[0].direction == Direction.IN
    assert msgs[0].text == "您好，请问这个职位还在招吗？"
    assert msgs[1].direction == Direction.OUT
    assert msgs[1].text == "在招的，方便发份简历吗？"
    assert msgs[2].direction == Direction.IN


def test_with_image_classifies_image_message() -> None:
    msgs = parse_conversation_detail(_tree("with_image"))
    image_msgs = [m for m in msgs if m.content_type == "image"]
    assert len(image_msgs) == 1
    assert image_msgs[0].direction == Direction.IN
    text_msgs = [m for m in msgs if m.content_type == "text"]
    assert any(m.text == "你好" for m in text_msgs)
    assert any(m.text == "收到您的简历啦" and m.direction == Direction.OUT for m in text_msgs)


def test_extract_chat_partner_id() -> None:
    assert extract_chat_partner_id(_tree("text_only")) == "CAND20260507A"
    assert extract_chat_partner_id(_tree("with_image")) == "CAND20260507B"


def test_empty_tree_returns_empty_list() -> None:
    assert parse_conversation_detail({}) == []


def test_message_dataclass_immutable() -> None:
    from dataclasses import FrozenInstanceError

    import pytest

    msg = Message(direction=Direction.IN, text="x", content_type="text")
    with pytest.raises((AttributeError, FrozenInstanceError)):
        msg.text = "y"  # type: ignore[misc]
