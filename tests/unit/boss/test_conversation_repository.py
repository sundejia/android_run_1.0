"""TDD tests for boss_automation/database/conversation_repository.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from boss_automation.database.candidate_repository import CandidateRepository
from boss_automation.database.conversation_repository import (
    ConversationRecord,
    ConversationRepository,
)
from boss_automation.database.recruiter_repository import RecruiterRepository
from boss_automation.parsers.candidate_card_parser import CandidateCard
from boss_automation.parsers.recruiter_profile_parser import RecruiterProfile


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "boss_test.db"


@pytest.fixture
def recruiter_id(db_path: Path) -> int:
    repo = RecruiterRepository(db_path)
    return repo.upsert(
        "EMU-1",
        RecruiterProfile(name="测试招聘", company="X", position="HR"),
    )


@pytest.fixture
def candidate_id(db_path: Path, recruiter_id: int) -> int:
    repo = CandidateRepository(db_path)
    card = CandidateCard(
        boss_candidate_id="CAND-A",
        name="李雷",
        age=28,
        gender=None,
        education=None,
        experience_years=None,
        current_company=None,
        current_position=None,
    )
    return repo.upsert_from_card(recruiter_id, card)


def test_upsert_creates_conversation(db_path: Path, recruiter_id: int, candidate_id: int) -> None:
    repo = ConversationRepository(db_path)
    cid = repo.upsert(
        recruiter_id=recruiter_id,
        candidate_id=candidate_id,
        unread_count=2,
        last_direction="in",
    )
    assert cid > 0
    record = repo.get(cid)
    assert isinstance(record, ConversationRecord)
    assert record.recruiter_id == recruiter_id
    assert record.candidate_id == candidate_id
    assert record.unread_count == 2
    assert record.last_direction == "in"


def test_upsert_is_idempotent_on_recruiter_candidate(db_path: Path, recruiter_id: int, candidate_id: int) -> None:
    repo = ConversationRepository(db_path)
    cid_a = repo.upsert(recruiter_id=recruiter_id, candidate_id=candidate_id, unread_count=2)
    cid_b = repo.upsert(recruiter_id=recruiter_id, candidate_id=candidate_id, unread_count=5)
    assert cid_a == cid_b
    record = repo.get(cid_a)
    assert record is not None
    assert record.unread_count == 5


def test_get_by_recruiter_and_candidate(db_path: Path, recruiter_id: int, candidate_id: int) -> None:
    repo = ConversationRepository(db_path)
    cid = repo.upsert(recruiter_id=recruiter_id, candidate_id=candidate_id)
    record = repo.get_by_candidate(recruiter_id, candidate_id)
    assert record is not None
    assert record.id == cid


def test_list_for_recruiter_returns_all(db_path: Path, recruiter_id: int, candidate_id: int) -> None:
    repo = ConversationRepository(db_path)
    repo.upsert(recruiter_id=recruiter_id, candidate_id=candidate_id)
    cards = ConversationRepository(db_path).list_for_recruiter(recruiter_id)
    assert len(cards) == 1


def test_invalid_direction_rejected(db_path: Path, recruiter_id: int, candidate_id: int) -> None:
    repo = ConversationRepository(db_path)
    with pytest.raises(ValueError):
        repo.upsert(
            recruiter_id=recruiter_id,
            candidate_id=candidate_id,
            last_direction="sideways",
        )
