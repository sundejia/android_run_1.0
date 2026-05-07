"""TDD tests for boss_automation/database/followup_attempts_repository.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from boss_automation.database.candidate_repository import CandidateRepository
from boss_automation.database.conversation_repository import ConversationRepository
from boss_automation.database.followup_attempts_repository import (
    AttemptRecord,
    FollowupAttemptsRepository,
)
from boss_automation.database.recruiter_repository import RecruiterRepository
from boss_automation.parsers.candidate_card_parser import CandidateCard
from boss_automation.parsers.recruiter_profile_parser import RecruiterProfile


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "boss_attempts.db"


@pytest.fixture
def seeds(db_path: Path) -> tuple[int, int, int]:
    rid = RecruiterRepository(db_path).upsert("EMU-1", RecruiterProfile(name="X", company="Co", position="HR"))
    cand = CandidateRepository(db_path).upsert_from_card(
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
    conv = ConversationRepository(db_path).upsert(recruiter_id=rid, candidate_id=cand)
    return rid, cand, conv


def test_append_pending_returns_id_and_status(db_path: Path, seeds: tuple[int, int, int]) -> None:
    _rid, cand, conv = seeds
    repo = FollowupAttemptsRepository(db_path)
    aid = repo.append_pending(
        candidate_id=cand,
        conversation_id=conv,
        scheduled_at=datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC),
    )
    assert aid > 0
    record = repo.get(aid)
    assert isinstance(record, AttemptRecord)
    assert record.status == "pending"
    assert record.candidate_id == cand
    assert record.sent_at_iso is None


def test_mark_sent_transitions_status(db_path: Path, seeds: tuple[int, int, int]) -> None:
    _rid, cand, conv = seeds
    repo = FollowupAttemptsRepository(db_path)
    aid = repo.append_pending(
        candidate_id=cand,
        conversation_id=conv,
        scheduled_at=datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC),
    )
    repo.mark_sent(aid, sent_at=datetime(2026, 5, 7, 10, 5, 0, tzinfo=UTC))
    record = repo.get(aid)
    assert record is not None
    assert record.status == "sent"
    assert record.sent_at_iso is not None


def test_mark_sent_twice_raises(db_path: Path, seeds: tuple[int, int, int]) -> None:
    _rid, cand, conv = seeds
    repo = FollowupAttemptsRepository(db_path)
    aid = repo.append_pending(
        candidate_id=cand,
        conversation_id=conv,
        scheduled_at=datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC),
    )
    repo.mark_sent(aid, sent_at=datetime(2026, 5, 7, 10, 5, 0, tzinfo=UTC))
    with pytest.raises(ValueError):
        repo.mark_sent(aid, sent_at=datetime(2026, 5, 7, 11, 0, 0, tzinfo=UTC))


def test_mark_cancelled_records_reason(db_path: Path, seeds: tuple[int, int, int]) -> None:
    _rid, cand, conv = seeds
    repo = FollowupAttemptsRepository(db_path)
    aid = repo.append_pending(
        candidate_id=cand,
        conversation_id=conv,
        scheduled_at=datetime.now(tz=UTC),
    )
    repo.mark_cancelled(aid, reason="candidate_replied")
    record = repo.get(aid)
    assert record is not None
    assert record.status == "cancelled"
    assert record.reason == "candidate_replied"


def test_mark_failed_records_reason(db_path: Path, seeds: tuple[int, int, int]) -> None:
    _rid, cand, conv = seeds
    repo = FollowupAttemptsRepository(db_path)
    aid = repo.append_pending(
        candidate_id=cand,
        conversation_id=conv,
        scheduled_at=datetime.now(tz=UTC),
    )
    repo.mark_failed(aid, reason="ui_unknown")
    record = repo.get(aid)
    assert record is not None
    assert record.status == "failed"
    assert record.reason == "ui_unknown"


def test_latest_for_candidate_returns_most_recent(db_path: Path, seeds: tuple[int, int, int]) -> None:
    _rid, cand, conv = seeds
    repo = FollowupAttemptsRepository(db_path)
    older = repo.append_pending(
        candidate_id=cand,
        conversation_id=conv,
        scheduled_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    newer = repo.append_pending(
        candidate_id=cand,
        conversation_id=conv,
        scheduled_at=datetime(2026, 5, 5, tzinfo=UTC),
    )
    record = repo.latest_for_candidate(cand)
    assert record is not None
    assert record.id == newer
    _ = older


def test_count_sent_in_range(db_path: Path, seeds: tuple[int, int, int]) -> None:
    _rid, cand, conv = seeds
    repo = FollowupAttemptsRepository(db_path)
    base = datetime(2026, 5, 7, 8, 0, 0, tzinfo=UTC)
    aid_a = repo.append_pending(candidate_id=cand, conversation_id=conv, scheduled_at=base)
    repo.mark_sent(aid_a, sent_at=base + timedelta(minutes=1))
    aid_b = repo.append_pending(candidate_id=cand, conversation_id=conv, scheduled_at=base)
    repo.mark_sent(aid_b, sent_at=base + timedelta(hours=2))

    count = repo.count_sent_in_range(
        recruiter_id=_rid,
        since=base,
        until=base + timedelta(hours=3),
    )
    assert count == 2


def test_invalid_status_transition_raises(db_path: Path, seeds: tuple[int, int, int]) -> None:
    _rid, cand, conv = seeds
    repo = FollowupAttemptsRepository(db_path)
    aid = repo.append_pending(
        candidate_id=cand,
        conversation_id=conv,
        scheduled_at=datetime.now(tz=UTC),
    )
    repo.mark_cancelled(aid, reason="x")
    with pytest.raises(ValueError):
        repo.mark_sent(aid, sent_at=datetime.now(tz=UTC))
