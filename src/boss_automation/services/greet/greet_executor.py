"""Greet executor: orchestrate one greet attempt safely.

State-machine driven, with hard halts on RISK_CONTROL_BLOCKED and
UNKNOWN_UI. Blacklist is checked twice (pick + pre-send) to satisfy
the AGENTS.md send-safety rule.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from boss_automation.database.candidate_repository import CandidateRepository
from boss_automation.parsers.candidate_card_parser import (
    CandidateCard,
    parse_candidate_feed,
)
from boss_automation.parsers.greet_state_detector import (
    GreetState,
    detect_greet_state,
)
from boss_automation.services.adb_port import AdbPort
from boss_automation.services.greet.quota_guard import QuotaDecision, QuotaGuard
from boss_automation.services.greet.schedule import GreetSchedule, is_within_window

GREET_BUTTON_LABEL: Final[str] = "立即沟通"


class OutcomeKind(StrEnum):
    SENT = "sent"
    SKIPPED_ALREADY_GREETED = "skipped_already_greeted"
    SKIPPED_BLACKLISTED = "skipped_blacklisted"
    SKIPPED_QUOTA_DAY = "skipped_quota_day"
    SKIPPED_QUOTA_HOUR = "skipped_quota_hour"
    SKIPPED_QUOTA_JOB = "skipped_quota_job"
    SKIPPED_OUTSIDE_WINDOW = "skipped_outside_window"
    SKIPPED_NO_CANDIDATES = "skipped_no_candidates"
    HALTED_RISK_CONTROL = "halted_risk_control"
    HALTED_UNKNOWN_UI = "halted_unknown_ui"


@dataclass(frozen=True, slots=True)
class GreetOutcome:
    kind: OutcomeKind
    boss_candidate_id: str | None = None
    candidate_name: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class GreetEvent:
    stage: str
    boss_candidate_id: str | None = None
    detail: str | None = None


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


_RecentSendTimesProvider = Callable[[], "list[datetime]"]
_BlacklistChecker = Callable[[str], Awaitable[bool]]


class GreetExecutor:
    """Performs one full greet attempt against a real or fake AdbPort.

    Dependencies are injected to keep the executor unit-testable.
    """

    def __init__(
        self,
        *,
        adb: AdbPort,
        candidate_repo: CandidateRepository,
        recruiter_id: int,
        schedule: GreetSchedule,
        quota_guard: QuotaGuard,
        is_blacklisted: _BlacklistChecker | None = None,
        recent_send_times_provider: _RecentSendTimesProvider | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._adb = adb
        self._candidate_repo = candidate_repo
        self._recruiter_id = recruiter_id
        self._schedule = schedule
        self._quota_guard = quota_guard
        self._is_blacklisted = is_blacklisted
        self._recent_send_times_provider = recent_send_times_provider or (lambda: [])
        self._clock = clock

    async def execute_one(
        self,
        *,
        progress: Callable[[GreetEvent], None] | None = None,
    ) -> GreetOutcome:
        emit = progress or (lambda _e: None)

        if not is_within_window(self._schedule, self._clock()):
            emit(GreetEvent(stage="window_check", detail="outside"))
            return GreetOutcome(kind=OutcomeKind.SKIPPED_OUTSIDE_WINDOW)

        # Quota gate before doing any device work.
        decision = self._quota_guard.check(
            recent_send_times=self._recent_send_times_provider(),
        )
        if decision != QuotaDecision.ALLOWED:
            emit(GreetEvent(stage="quota_pre_pick", detail=decision.value))
            return GreetOutcome(kind=_quota_decision_to_outcome_kind(decision))

        feed_tree, _ = await self._adb.get_state()
        cards = parse_candidate_feed(feed_tree)
        if not cards:
            emit(GreetEvent(stage="feed_empty"))
            return GreetOutcome(kind=OutcomeKind.SKIPPED_NO_CANDIDATES)

        candidate = await self._pick_first_eligible(cards, emit)
        if candidate is None:
            return GreetOutcome(kind=OutcomeKind.SKIPPED_BLACKLISTED)

        # Persist the candidate snapshot regardless of what happens next
        # so the desktop UI can show their card.
        self._candidate_repo.upsert_from_card(self._recruiter_id, candidate)

        # Open the candidate detail page.
        opened = False
        if candidate.tap_x is not None and candidate.tap_y is not None:
            opened = await self._adb.tap(candidate.tap_x, candidate.tap_y)
        if not opened:
            opened = await self._adb.tap_by_text(candidate.name)
        emit(GreetEvent(stage="open_card", boss_candidate_id=candidate.boss_candidate_id))
        if not opened:
            return GreetOutcome(
                kind=OutcomeKind.HALTED_UNKNOWN_UI,
                boss_candidate_id=candidate.boss_candidate_id,
                detail="failed to open card",
            )

        detail_tree, _ = await self._adb.get_state()
        state = detect_greet_state(detail_tree)
        emit(
            GreetEvent(
                stage="classify_detail",
                boss_candidate_id=candidate.boss_candidate_id,
                detail=state.value,
            )
        )

        if state == GreetState.RISK_CONTROL_BLOCKED:
            return GreetOutcome(
                kind=OutcomeKind.HALTED_RISK_CONTROL,
                boss_candidate_id=candidate.boss_candidate_id,
            )
        if state == GreetState.QUOTA_EXHAUSTED:
            return GreetOutcome(
                kind=OutcomeKind.SKIPPED_QUOTA_DAY,
                boss_candidate_id=candidate.boss_candidate_id,
            )
        if state == GreetState.ALREADY_GREETED:
            self._candidate_repo.set_status(self._recruiter_id, candidate.boss_candidate_id, "greeted")
            return GreetOutcome(
                kind=OutcomeKind.SKIPPED_ALREADY_GREETED,
                boss_candidate_id=candidate.boss_candidate_id,
            )
        if state != GreetState.READY_TO_GREET:
            return GreetOutcome(
                kind=OutcomeKind.HALTED_UNKNOWN_UI,
                boss_candidate_id=candidate.boss_candidate_id,
                detail=state.value,
            )

        # Pre-send blacklist re-check (AGENTS.md guardrail).
        if self._is_blacklisted is not None and await self._is_blacklisted(candidate.boss_candidate_id):
            emit(
                GreetEvent(
                    stage="pre_send_blacklist_recheck",
                    boss_candidate_id=candidate.boss_candidate_id,
                )
            )
            return GreetOutcome(
                kind=OutcomeKind.SKIPPED_BLACKLISTED,
                boss_candidate_id=candidate.boss_candidate_id,
            )

        await self._adb.tap_by_text(GREET_BUTTON_LABEL)
        emit(GreetEvent(stage="sent_greet", boss_candidate_id=candidate.boss_candidate_id))
        self._candidate_repo.set_status(self._recruiter_id, candidate.boss_candidate_id, "greeted")
        return GreetOutcome(
            kind=OutcomeKind.SENT,
            boss_candidate_id=candidate.boss_candidate_id,
            candidate_name=candidate.name,
        )

    async def _pick_first_eligible(
        self,
        cards: list[CandidateCard],
        emit: Callable[[GreetEvent], None],
    ) -> CandidateCard | None:
        for card in cards:
            if self._is_blacklisted is not None and await self._is_blacklisted(card.boss_candidate_id):
                emit(
                    GreetEvent(
                        stage="pick_skip_blacklisted",
                        boss_candidate_id=card.boss_candidate_id,
                    )
                )
                continue
            return card
        return None


def _quota_decision_to_outcome_kind(decision: QuotaDecision) -> OutcomeKind:
    if decision == QuotaDecision.BLOCKED_HOUR:
        return OutcomeKind.SKIPPED_QUOTA_HOUR
    if decision == QuotaDecision.BLOCKED_DAY:
        return OutcomeKind.SKIPPED_QUOTA_DAY
    if decision == QuotaDecision.BLOCKED_JOB:
        return OutcomeKind.SKIPPED_QUOTA_JOB
    raise AssertionError(f"unhandled decision {decision!r}")
