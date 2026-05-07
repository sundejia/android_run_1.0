"""TDD tests for boss_automation/services/reengagement/detector.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from boss_automation.database.candidate_repository import CandidateRepository
from boss_automation.database.conversation_repository import ConversationRepository
from boss_automation.database.message_repository import MessageRepository
from boss_automation.database.recruiter_repository import RecruiterRepository
from boss_automation.parsers.candidate_card_parser import CandidateCard
from boss_automation.parsers.recruiter_profile_parser import RecruiterProfile
from boss_automation.services.reengagement.detector import (
    EligibleCandidate,
    find_eligible,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "boss_reengage.db"


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 7, 18, 0, 0, tzinfo=UTC)


def _seed_candidate(
    db: Path,
    recruiter_id: int,
    boss_id: str,
    name: str = "李雷",
) -> int:
    return CandidateRepository(db).upsert_from_card(
        recruiter_id,
        CandidateCard(
            boss_candidate_id=boss_id,
            name=name,
            age=28,
            gender=None,
            education=None,
            experience_years=None,
            current_company=None,
            current_position=None,
        ),
    )


def _send_message(
    db: Path,
    conversation_id: int,
    direction: str,
    text: str,
    when: datetime,
) -> None:
    MessageRepository(db).insert(
        conversation_id=conversation_id,
        direction=direction,
        content_type="text",
        text=text,
        sent_at=when,
        sent_by="manual" if direction == "in" else "auto",
    )


def test_returns_empty_when_no_conversations(db_path: Path, now: datetime) -> None:
    rid = RecruiterRepository(db_path).upsert("EMU-1", RecruiterProfile(name="X", company="Co", position="HR"))
    rows = find_eligible(
        db_path=str(db_path),
        recruiter_id=rid,
        silent_for_days=3,
        cooldown_days=7,
        now=now,
    )
    assert rows == []


def test_yields_candidate_silent_past_threshold(db_path: Path, now: datetime) -> None:
    rid = RecruiterRepository(db_path).upsert("EMU-1", RecruiterProfile(name="X", company="Co", position="HR"))
    cand = _seed_candidate(db_path, rid, "CAND-A")
    conv = ConversationRepository(db_path).upsert(recruiter_id=rid, candidate_id=cand, last_direction="out")
    _send_message(db_path, conv, "out", "hi", now - timedelta(days=4))

    rows = find_eligible(
        db_path=str(db_path),
        recruiter_id=rid,
        silent_for_days=3,
        cooldown_days=7,
        now=now,
    )
    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, EligibleCandidate)
    assert row.candidate_id == cand
    assert row.boss_candidate_id == "CAND-A"
    assert row.silent_for_seconds >= 4 * 86400 - 60


def test_skips_candidate_who_replied(db_path: Path, now: datetime) -> None:
    rid = RecruiterRepository(db_path).upsert("EMU-1", RecruiterProfile(name="X", company="Co", position="HR"))
    cand = _seed_candidate(db_path, rid, "CAND-B")
    conv = ConversationRepository(db_path).upsert(recruiter_id=rid, candidate_id=cand)
    _send_message(db_path, conv, "out", "hi", now - timedelta(days=5))
    _send_message(db_path, conv, "in", "thanks", now - timedelta(days=4))

    rows = find_eligible(
        db_path=str(db_path),
        recruiter_id=rid,
        silent_for_days=3,
        cooldown_days=7,
        now=now,
    )
    assert rows == []


def test_skips_candidate_silent_under_threshold(db_path: Path, now: datetime) -> None:
    rid = RecruiterRepository(db_path).upsert("EMU-1", RecruiterProfile(name="X", company="Co", position="HR"))
    cand = _seed_candidate(db_path, rid, "CAND-C")
    conv = ConversationRepository(db_path).upsert(recruiter_id=rid, candidate_id=cand)
    _send_message(db_path, conv, "out", "hi", now - timedelta(hours=12))

    rows = find_eligible(
        db_path=str(db_path),
        recruiter_id=rid,
        silent_for_days=3,
        cooldown_days=7,
        now=now,
    )
    assert rows == []


def test_skips_blocked_candidates(db_path: Path, now: datetime) -> None:
    rid = RecruiterRepository(db_path).upsert("EMU-1", RecruiterProfile(name="X", company="Co", position="HR"))
    cand = _seed_candidate(db_path, rid, "CAND-D")
    repo = CandidateRepository(db_path)
    repo.set_status(rid, "CAND-D", "blocked")
    conv = ConversationRepository(db_path).upsert(recruiter_id=rid, candidate_id=cand)
    _send_message(db_path, conv, "out", "hi", now - timedelta(days=5))

    rows = find_eligible(
        db_path=str(db_path),
        recruiter_id=rid,
        silent_for_days=3,
        cooldown_days=7,
        now=now,
    )
    assert rows == []


def test_respects_cooldown_window(db_path: Path, now: datetime) -> None:
    """A candidate that was re-engaged 2 days ago must not be picked
    again when the cooldown is 7 days."""
    from boss_automation.database.followup_attempts_repository import (
        FollowupAttemptsRepository,
    )

    rid = RecruiterRepository(db_path).upsert("EMU-1", RecruiterProfile(name="X", company="Co", position="HR"))
    cand = _seed_candidate(db_path, rid, "CAND-E")
    conv = ConversationRepository(db_path).upsert(recruiter_id=rid, candidate_id=cand)
    _send_message(db_path, conv, "out", "hi", now - timedelta(days=10))

    attempts = FollowupAttemptsRepository(db_path)
    aid = attempts.append_pending(
        candidate_id=cand,
        conversation_id=conv,
        scheduled_at=now - timedelta(days=2),
    )
    attempts.mark_sent(aid, sent_at=now - timedelta(days=2))

    rows = find_eligible(
        db_path=str(db_path),
        recruiter_id=rid,
        silent_for_days=3,
        cooldown_days=7,
        now=now,
    )
    assert rows == []


def test_orders_by_oldest_first(db_path: Path, now: datetime) -> None:
    rid = RecruiterRepository(db_path).upsert("EMU-1", RecruiterProfile(name="X", company="Co", position="HR"))
    older = _seed_candidate(db_path, rid, "CAND-OLDER", "Older")
    newer = _seed_candidate(db_path, rid, "CAND-NEWER", "Newer")
    conv_old = ConversationRepository(db_path).upsert(recruiter_id=rid, candidate_id=older)
    conv_new = ConversationRepository(db_path).upsert(recruiter_id=rid, candidate_id=newer)
    _send_message(db_path, conv_old, "out", "hi", now - timedelta(days=10))
    _send_message(db_path, conv_new, "out", "hi", now - timedelta(days=4))

    rows = find_eligible(
        db_path=str(db_path),
        recruiter_id=rid,
        silent_for_days=3,
        cooldown_days=7,
        now=now,
    )
    assert [r.boss_candidate_id for r in rows] == ["CAND-OLDER", "CAND-NEWER"]
