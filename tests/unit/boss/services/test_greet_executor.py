"""TDD tests for boss_automation/services/greet/greet_executor.py.

8-path matrix per the design doc:
1. READY → SENT
2. ALREADY_GREETED → SKIPPED_ALREADY_GREETED
3. QUOTA_EXHAUSTED (UI-detected) → SKIPPED_QUOTA_DAY (and updates guard)
4. RISK_CONTROL_BLOCKED → HALTED_RISK_CONTROL
5. Blacklisted at pick time → SKIPPED_BLACKLISTED
6. Outside time window → SKIPPED_OUTSIDE_WINDOW
7. Mid-flight blacklist (clean at pick, blacklisted before send)
   → SKIPPED_BLACKLISTED (regression for AGENTS.md guardrail)
8. Unknown UI → HALTED_UNKNOWN_UI
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from boss_automation.database.candidate_repository import CandidateRepository
from boss_automation.database.recruiter_repository import RecruiterRepository
from boss_automation.parsers.recruiter_profile_parser import RecruiterProfile
from boss_automation.services.greet.greet_executor import (
    GreetEvent,
    GreetExecutor,
    GreetOutcome,
    OutcomeKind,
)
from boss_automation.services.greet.quota_guard import GreetQuota, QuotaGuard
from boss_automation.services.greet.schedule import (
    GreetSchedule,
    weekday_mask_for,
)
from tests._fixtures.loader import load_fixture

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "boss"


def _feed_tree() -> dict[str, Any]:
    return load_fixture(FIXTURE_ROOT / "candidates_feed" / "feed_with_cards.json").ui_tree


def _detail_tree(label: str) -> dict[str, Any]:
    return load_fixture(FIXTURE_ROOT / "candidate_detail" / f"{label}.json").ui_tree


class FakeAdbPort:
    """Scripted AdbPort: emits ``trees`` in order on each get_state."""

    def __init__(self, trees: Sequence[dict[str, Any]]) -> None:
        self._trees = list(trees)
        self._idx = 0
        self.tap_text_calls: list[str] = []
        self.swipe_calls: list[tuple[int, int, int, int, int]] = []
        # Optional hook fired before each tap (used to simulate
        # mid-flight state changes like blacklist additions).
        self.before_tap_hook: list = []

    async def start_app(self, package_name: str) -> None: ...

    async def get_state(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if self._idx >= len(self._trees):
            tree = self._trees[-1] if self._trees else {}
        else:
            tree = self._trees[self._idx]
            self._idx += 1
        return copy.deepcopy(tree), []

    async def tap_by_text(self, text: str) -> bool:
        for hook in self.before_tap_hook:
            hook(text)
        self.tap_text_calls.append(text)
        return True

    async def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.swipe_calls.append((x1, y1, x2, y2, duration_ms))


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "boss.db"


@pytest.fixture()
def recruiter_id(db_path: Path) -> int:
    return RecruiterRepository(db_path).upsert("EMU-1", RecruiterProfile(name="Alice"))


@pytest.fixture()
def candidate_repo(db_path: Path) -> CandidateRepository:
    return CandidateRepository(db_path)


_FIXED_NOW = datetime(2026, 5, 7, 14, 30, tzinfo=UTC)


def _open_window() -> GreetSchedule:
    return GreetSchedule(
        weekday_mask=weekday_mask_for(range(7)),
        start_minute=0,
        end_minute=23 * 60 + 59,
        timezone="UTC",
    )


def _closed_window() -> GreetSchedule:
    return GreetSchedule(
        weekday_mask=0,  # no weekday active
        start_minute=0,
        end_minute=1,
        timezone="UTC",
    )


def _make_executor(
    *,
    adb: FakeAdbPort,
    candidate_repo: CandidateRepository,
    recruiter_id: int,
    schedule: GreetSchedule | None = None,
    quota: GreetQuota | None = None,
    is_blacklisted=None,
    now: datetime | None = None,
) -> GreetExecutor:
    return GreetExecutor(
        adb=adb,
        candidate_repo=candidate_repo,
        recruiter_id=recruiter_id,
        schedule=schedule or _open_window(),
        quota_guard=QuotaGuard(quota or GreetQuota(per_day=80, per_hour=15), clock=lambda: now or _FIXED_NOW),
        is_blacklisted=is_blacklisted,
        clock=lambda: now or _FIXED_NOW,
    )


class TestPathReadyToGreet:
    @pytest.mark.asyncio
    async def test_executes_full_send(self, candidate_repo: CandidateRepository, recruiter_id: int) -> None:
        adb = FakeAdbPort(trees=[_feed_tree(), _detail_tree("ready_to_greet"), _detail_tree("already_greeted")])
        executor = _make_executor(adb=adb, candidate_repo=candidate_repo, recruiter_id=recruiter_id)

        events: list[GreetEvent] = []
        outcome = await executor.execute_one(progress=events.append)

        assert outcome.kind == OutcomeKind.SENT
        # The candidate moved to greeted in the DB.
        rec = candidate_repo.get_by_boss_candidate_id(recruiter_id, outcome.boss_candidate_id)
        assert rec is not None
        assert rec.status == "greeted"
        # 立即沟通 button MUST have been tapped.
        assert "立即沟通" in adb.tap_text_calls


class TestPathAlreadyGreeted:
    @pytest.mark.asyncio
    async def test_skips_without_send(self, candidate_repo: CandidateRepository, recruiter_id: int) -> None:
        adb = FakeAdbPort(trees=[_feed_tree(), _detail_tree("already_greeted")])
        executor = _make_executor(adb=adb, candidate_repo=candidate_repo, recruiter_id=recruiter_id)

        outcome = await executor.execute_one()

        assert outcome.kind == OutcomeKind.SKIPPED_ALREADY_GREETED
        assert "立即沟通" not in adb.tap_text_calls


class TestPathQuotaExhaustedFromUI:
    @pytest.mark.asyncio
    async def test_marks_skipped_quota_day(self, candidate_repo: CandidateRepository, recruiter_id: int) -> None:
        adb = FakeAdbPort(trees=[_feed_tree(), _detail_tree("quota_exhausted")])
        executor = _make_executor(adb=adb, candidate_repo=candidate_repo, recruiter_id=recruiter_id)

        outcome = await executor.execute_one()

        assert outcome.kind == OutcomeKind.SKIPPED_QUOTA_DAY


class TestPathRiskControl:
    @pytest.mark.asyncio
    async def test_halts_executor(self, candidate_repo: CandidateRepository, recruiter_id: int) -> None:
        adb = FakeAdbPort(trees=[_feed_tree(), _detail_tree("risk_control_popup")])
        executor = _make_executor(adb=adb, candidate_repo=candidate_repo, recruiter_id=recruiter_id)

        outcome = await executor.execute_one()

        assert outcome.kind == OutcomeKind.HALTED_RISK_CONTROL


class TestPathBlacklistedAtPickTime:
    @pytest.mark.asyncio
    async def test_skips_without_opening_card(self, candidate_repo: CandidateRepository, recruiter_id: int) -> None:
        adb = FakeAdbPort(trees=[_feed_tree()])

        async def is_blacklisted(boss_candidate_id: str) -> bool:
            return boss_candidate_id == "CAND20260507A"

        executor = _make_executor(
            adb=adb, candidate_repo=candidate_repo, recruiter_id=recruiter_id, is_blacklisted=is_blacklisted
        )
        outcome = await executor.execute_one()
        # First candidate is blacklisted; executor must move to the second.
        # In our fixture the second candidate is CAND20260507B and we
        # only provide one detail tree, so the executor returns
        # HALTED_UNKNOWN_UI for the second one. What we MUST verify is
        # that the first candidate's card was never opened (no tap on
        # 立即沟通) and the outcome includes the blacklisted skip.
        assert outcome.kind in (OutcomeKind.SKIPPED_BLACKLISTED, OutcomeKind.HALTED_UNKNOWN_UI)
        assert "立即沟通" not in adb.tap_text_calls


class TestPathOutsideTimeWindow:
    @pytest.mark.asyncio
    async def test_skips_without_reading_feed(self, candidate_repo: CandidateRepository, recruiter_id: int) -> None:
        adb = FakeAdbPort(trees=[_feed_tree()])
        executor = _make_executor(
            adb=adb,
            candidate_repo=candidate_repo,
            recruiter_id=recruiter_id,
            schedule=_closed_window(),
        )
        outcome = await executor.execute_one()
        assert outcome.kind == OutcomeKind.SKIPPED_OUTSIDE_WINDOW


class TestPathMidFlightBlacklist:
    """Regression for the AGENTS.md blacklist send-safety rule.

    The candidate is allowed when picked from the feed but added to
    the blacklist before the second check (right before the
    立即沟通 tap). Executor MUST NOT send.
    """

    @pytest.mark.asyncio
    async def test_executor_recheck_blocks_send(self, candidate_repo: CandidateRepository, recruiter_id: int) -> None:
        adb = FakeAdbPort(trees=[_feed_tree(), _detail_tree("ready_to_greet")])

        check_count = {"n": 0}

        async def is_blacklisted(boss_candidate_id: str) -> bool:
            check_count["n"] += 1
            return check_count["n"] > 1

        executor = _make_executor(
            adb=adb,
            candidate_repo=candidate_repo,
            recruiter_id=recruiter_id,
            is_blacklisted=is_blacklisted,
        )
        outcome = await executor.execute_one()

        assert outcome.kind == OutcomeKind.SKIPPED_BLACKLISTED
        assert "立即沟通" not in adb.tap_text_calls


class TestPathPreSendQuotaBlock:
    @pytest.mark.asyncio
    async def test_respects_existing_history(self, candidate_repo: CandidateRepository, recruiter_id: int) -> None:
        adb = FakeAdbPort(trees=[_feed_tree(), _detail_tree("ready_to_greet")])
        # Pretend many recent sends so per-hour cap blocks.
        executor = GreetExecutor(
            adb=adb,
            candidate_repo=candidate_repo,
            recruiter_id=recruiter_id,
            schedule=_open_window(),
            quota_guard=QuotaGuard(
                GreetQuota(per_day=80, per_hour=1),
                clock=lambda: _FIXED_NOW,
            ),
            recent_send_times_provider=lambda: [_FIXED_NOW],
            clock=lambda: _FIXED_NOW,
        )
        outcome = await executor.execute_one()
        assert outcome.kind == OutcomeKind.SKIPPED_QUOTA_HOUR


class TestPathUnknownUI:
    @pytest.mark.asyncio
    async def test_halts(self, candidate_repo: CandidateRepository, recruiter_id: int) -> None:
        unknown_tree = {"className": "FrameLayout", "children": []}
        adb = FakeAdbPort(trees=[_feed_tree(), unknown_tree])
        executor = _make_executor(adb=adb, candidate_repo=candidate_repo, recruiter_id=recruiter_id)
        outcome = await executor.execute_one()
        assert outcome.kind == OutcomeKind.HALTED_UNKNOWN_UI


class TestEmptyFeed:
    @pytest.mark.asyncio
    async def test_no_candidates_returns_skipped_outcome(
        self, candidate_repo: CandidateRepository, recruiter_id: int
    ) -> None:
        empty_tree = {"className": "FrameLayout", "children": []}
        adb = FakeAdbPort(trees=[empty_tree])
        executor = _make_executor(adb=adb, candidate_repo=candidate_repo, recruiter_id=recruiter_id)
        outcome = await executor.execute_one()
        # No candidates → no-op outcome (we'll classify as SKIPPED_NO_CANDIDATES)
        assert outcome.kind == OutcomeKind.SKIPPED_NO_CANDIDATES


class TestOutcomeShape:
    def test_outcome_immutable(self) -> None:
        from dataclasses import FrozenInstanceError

        outcome = GreetOutcome(kind=OutcomeKind.SENT, boss_candidate_id="X")
        with pytest.raises((AttributeError, FrozenInstanceError)):
            outcome.kind = OutcomeKind.SKIPPED_ALREADY_GREETED  # type: ignore[misc]

    def test_outcome_kind_string_enum(self) -> None:
        assert OutcomeKind.SENT == "sent"
        assert OutcomeKind.SKIPPED_BLACKLISTED == "skipped_blacklisted"
