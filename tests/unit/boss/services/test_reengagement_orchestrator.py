"""TDD tests for ReengagementOrchestrator.

Verifies the safety-critical flow: blacklist re-check at send time,
cancel-on-reply, daily quota cap, and the SENT happy path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from boss_automation.database.candidate_repository import CandidateRepository
from boss_automation.database.conversation_repository import ConversationRepository
from boss_automation.database.followup_attempts_repository import (
    FollowupAttemptsRepository,
)
from boss_automation.database.message_repository import MessageRepository
from boss_automation.database.recruiter_repository import RecruiterRepository
from boss_automation.parsers.candidate_card_parser import CandidateCard
from boss_automation.parsers.recruiter_profile_parser import RecruiterProfile
from boss_automation.services.reengagement.detector import EligibleCandidate
from boss_automation.services.reengagement.orchestrator import (
    ReengagementKind,
    ReengagementOrchestrator,
    ReengagementSettings,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "boss_reengage_orch.db"


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 7, 18, 0, 0, tzinfo=UTC)


@pytest.fixture
def seeds(db_path: Path) -> tuple[int, int, int, str]:
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
    return rid, cand, conv, "CAND-A"


def _send(db: Path, conv_id: int, direction: str, when: datetime) -> None:
    MessageRepository(db).insert(
        conversation_id=conv_id,
        direction=direction,
        content_type="text",
        text="x",
        sent_at=when,
        sent_by="auto" if direction == "out" else "manual",
    )


def _eligible(seeds: tuple[int, int, int, str], silent_secs: int = 4 * 86400) -> EligibleCandidate:
    rid, cand, conv, boss_id = seeds
    return EligibleCandidate(
        recruiter_id=rid,
        candidate_id=cand,
        conversation_id=conv,
        boss_candidate_id=boss_id,
        last_outbound_at_iso="2026-05-03T12:00:00+00:00",
        silent_for_seconds=silent_secs,
    )


class _AcceptingDispatcher:
    def __init__(self) -> None:
        self.calls = 0

    async def dispatch_one(self, **_kwargs: object) -> bool:
        self.calls += 1
        return True


class _FailingDispatcher:
    async def dispatch_one(self, **_kwargs: object) -> bool:
        raise RuntimeError("ui broke")


def _settings(daily_cap: int = 50) -> ReengagementSettings:
    return ReengagementSettings(
        silent_for_days=3,
        cooldown_days=7,
        daily_cap=daily_cap,
    )


@pytest.mark.asyncio
async def test_sent_happy_path(db_path: Path, seeds: tuple[int, int, int, str], now: datetime) -> None:
    rid, cand, conv, _ = seeds
    _send(db_path, conv, "out", now - timedelta(days=4))

    orch = ReengagementOrchestrator(
        attempts_repo=FollowupAttemptsRepository(db_path),
        message_repo=MessageRepository(db_path),
        dispatcher=_AcceptingDispatcher(),
        is_blacklisted=lambda _id: _async(False),
        clock=lambda: now,
        settings=_settings(),
    )
    outcome = await orch.run_one(eligible=_eligible(seeds))
    assert outcome.kind == ReengagementKind.SENT
    assert outcome.attempt_id is not None

    record = FollowupAttemptsRepository(db_path).get(outcome.attempt_id)
    assert record is not None
    assert record.status == "sent"


@pytest.mark.asyncio
async def test_skipped_when_candidate_blacklisted_at_send_time(
    db_path: Path, seeds: tuple[int, int, int, str], now: datetime
) -> None:
    rid, cand, conv, _ = seeds
    _send(db_path, conv, "out", now - timedelta(days=4))

    dispatcher = _AcceptingDispatcher()
    orch = ReengagementOrchestrator(
        attempts_repo=FollowupAttemptsRepository(db_path),
        message_repo=MessageRepository(db_path),
        dispatcher=dispatcher,
        is_blacklisted=lambda _id: _async(True),
        clock=lambda: now,
        settings=_settings(),
    )
    outcome = await orch.run_one(eligible=_eligible(seeds))
    assert outcome.kind == ReengagementKind.SKIPPED_BLACKLISTED
    assert dispatcher.calls == 0
    record = FollowupAttemptsRepository(db_path).get(outcome.attempt_id or 0)
    assert record is not None
    assert record.status == "cancelled"
    assert record.reason == "blacklisted"


@pytest.mark.asyncio
async def test_cancel_when_candidate_replied_between_scan_and_run(
    db_path: Path, seeds: tuple[int, int, int, str], now: datetime
) -> None:
    rid, cand, conv, _ = seeds
    _send(db_path, conv, "out", now - timedelta(days=4))
    # Candidate replied right before the orchestrator picked them up.
    _send(db_path, conv, "in", now - timedelta(minutes=5))

    dispatcher = _AcceptingDispatcher()
    orch = ReengagementOrchestrator(
        attempts_repo=FollowupAttemptsRepository(db_path),
        message_repo=MessageRepository(db_path),
        dispatcher=dispatcher,
        is_blacklisted=lambda _id: _async(False),
        clock=lambda: now,
        settings=_settings(),
    )
    outcome = await orch.run_one(eligible=_eligible(seeds))
    assert outcome.kind == ReengagementKind.SKIPPED_CANDIDATE_REPLIED
    assert dispatcher.calls == 0
    record = FollowupAttemptsRepository(db_path).get(outcome.attempt_id or 0)
    assert record is not None
    assert record.status == "cancelled"
    assert record.reason == "candidate_replied"


@pytest.mark.asyncio
async def test_skipped_when_daily_cap_reached(db_path: Path, seeds: tuple[int, int, int, str], now: datetime) -> None:
    rid, cand, conv, _ = seeds
    _send(db_path, conv, "out", now - timedelta(days=4))

    attempts = FollowupAttemptsRepository(db_path)
    aid = attempts.append_pending(
        candidate_id=cand,
        conversation_id=conv,
        scheduled_at=now - timedelta(hours=1),
    )
    attempts.mark_sent(aid, sent_at=now - timedelta(hours=1))

    dispatcher = _AcceptingDispatcher()
    orch = ReengagementOrchestrator(
        attempts_repo=attempts,
        message_repo=MessageRepository(db_path),
        dispatcher=dispatcher,
        is_blacklisted=lambda _id: _async(False),
        clock=lambda: now,
        settings=_settings(daily_cap=1),
    )
    outcome = await orch.run_one(eligible=_eligible(seeds))
    assert outcome.kind == ReengagementKind.SKIPPED_DAILY_CAP
    assert dispatcher.calls == 0


@pytest.mark.asyncio
async def test_dispatch_failure_marks_attempt_failed(
    db_path: Path, seeds: tuple[int, int, int, str], now: datetime
) -> None:
    rid, cand, conv, _ = seeds
    _send(db_path, conv, "out", now - timedelta(days=4))

    orch = ReengagementOrchestrator(
        attempts_repo=FollowupAttemptsRepository(db_path),
        message_repo=MessageRepository(db_path),
        dispatcher=_FailingDispatcher(),
        is_blacklisted=lambda _id: _async(False),
        clock=lambda: now,
        settings=_settings(),
    )
    outcome = await orch.run_one(eligible=_eligible(seeds))
    assert outcome.kind == ReengagementKind.FAILED
    assert outcome.detail and "ui broke" in outcome.detail
    record = FollowupAttemptsRepository(db_path).get(outcome.attempt_id or 0)
    assert record is not None
    assert record.status == "failed"


@pytest.mark.asyncio
async def test_no_dispatcher_returns_dry_run(db_path: Path, seeds: tuple[int, int, int, str], now: datetime) -> None:
    rid, cand, conv, _ = seeds
    _send(db_path, conv, "out", now - timedelta(days=4))

    orch = ReengagementOrchestrator(
        attempts_repo=FollowupAttemptsRepository(db_path),
        message_repo=MessageRepository(db_path),
        dispatcher=None,
        is_blacklisted=lambda _id: _async(False),
        clock=lambda: now,
        settings=_settings(),
    )
    outcome = await orch.run_one(eligible=_eligible(seeds))
    assert outcome.kind == ReengagementKind.DRY_RUN
    record = FollowupAttemptsRepository(db_path).get(outcome.attempt_id or 0)
    assert record is not None
    assert record.status == "cancelled"
    assert record.reason == "dry_run"


# Helper: tiny async wrapper for fixed-value blacklist callbacks.


async def _async(value: bool) -> bool:
    return value
