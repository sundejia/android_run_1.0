"""TDD tests for boss_automation/database/message_repository.py."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from boss_automation.database.candidate_repository import CandidateRepository
from boss_automation.database.conversation_repository import ConversationRepository
from boss_automation.database.message_repository import (
    MessageRecord,
    MessageRepository,
    compute_message_hash,
)
from boss_automation.database.recruiter_repository import RecruiterRepository
from boss_automation.parsers.candidate_card_parser import CandidateCard
from boss_automation.parsers.recruiter_profile_parser import RecruiterProfile


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "boss_test.db"


@pytest.fixture
def conversation_id(db_path: Path) -> int:
    rid = RecruiterRepository(db_path).upsert(
        "EMU-1",
        RecruiterProfile(name="X", company="Co", position="HR"),
    )
    cand_id = CandidateRepository(db_path).upsert_from_card(
        rid,
        CandidateCard(
            boss_candidate_id="CAND-A",
            name="李雷",
            age=None,
            gender=None,
            education=None,
            experience_years=None,
            current_company=None,
            current_position=None,
        ),
    )
    return ConversationRepository(db_path).upsert(recruiter_id=rid, candidate_id=cand_id, unread_count=1)


def test_compute_message_hash_is_deterministic() -> None:
    h1 = compute_message_hash(conversation_id=1, direction="in", text="hi", sent_at_iso="2026-05-07T10:00:00")
    h2 = compute_message_hash(conversation_id=1, direction="in", text="hi", sent_at_iso="2026-05-07T10:00:00")
    assert h1 == h2
    assert len(h1) == 64


def test_compute_message_hash_changes_with_inputs() -> None:
    base = compute_message_hash(conversation_id=1, direction="in", text="hi", sent_at_iso="t")
    assert base != compute_message_hash(conversation_id=2, direction="in", text="hi", sent_at_iso="t")
    assert base != compute_message_hash(conversation_id=1, direction="out", text="hi", sent_at_iso="t")
    assert base != compute_message_hash(conversation_id=1, direction="in", text="bye", sent_at_iso="t")


def test_insert_and_list(db_path: Path, conversation_id: int) -> None:
    repo = MessageRepository(db_path)
    sent_at = datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC)
    mid = repo.insert(
        conversation_id=conversation_id,
        direction="in",
        content_type="text",
        text="您好",
        sent_at=sent_at,
        sent_by="manual",
    )
    assert mid > 0
    rows = repo.list_for_conversation(conversation_id)
    assert len(rows) == 1
    assert isinstance(rows[0], MessageRecord)
    assert rows[0].text == "您好"
    assert rows[0].direction == "in"


def test_insert_dedupes_on_message_hash(db_path: Path, conversation_id: int) -> None:
    repo = MessageRepository(db_path)
    sent_at = datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC)
    a = repo.insert(
        conversation_id=conversation_id,
        direction="in",
        content_type="text",
        text="您好",
        sent_at=sent_at,
        sent_by="manual",
    )
    b = repo.insert(
        conversation_id=conversation_id,
        direction="in",
        content_type="text",
        text="您好",
        sent_at=sent_at,
        sent_by="manual",
    )
    assert a == b
    assert len(repo.list_for_conversation(conversation_id)) == 1


def test_invalid_direction_rejected(db_path: Path, conversation_id: int) -> None:
    repo = MessageRepository(db_path)
    with pytest.raises(ValueError):
        repo.insert(
            conversation_id=conversation_id,
            direction="bogus",
            content_type="text",
            text="x",
            sent_at=datetime.now(tz=UTC),
            sent_by="manual",
        )


def test_list_in_chronological_order(db_path: Path, conversation_id: int) -> None:
    repo = MessageRepository(db_path)
    repo.insert(
        conversation_id=conversation_id,
        direction="in",
        content_type="text",
        text="first",
        sent_at=datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC),
        sent_by="manual",
    )
    repo.insert(
        conversation_id=conversation_id,
        direction="out",
        content_type="text",
        text="second",
        sent_at=datetime(2026, 5, 7, 10, 1, 0, tzinfo=UTC),
        sent_by="auto",
    )
    rows = repo.list_for_conversation(conversation_id)
    assert [r.text for r in rows] == ["first", "second"]
