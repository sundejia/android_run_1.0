"""Drives one re-engagement attempt at a time.

The orchestrator is intentionally thin and ordered:

1. Append a ``pending`` row to ``followup_attempts_v2`` so we have a
   stable id to reference in subsequent state transitions.
2. Re-check the *latest* messages (real-time DB read) to see if the
   candidate replied between scan and run. If yes → cancel
   (``candidate_replied``) and skip.
3. Re-check daily cap (real-time, scoped to the recruiter). If
   reached → cancel (``daily_cap``) and skip.
4. Real-time blacklist check (AGENTS.md "Blacklist Send-Safety"
   guardrail). If blocked → cancel (``blacklisted``) and skip.
5. If no dispatcher is wired, mark cancelled with reason ``dry_run``
   and return ``DRY_RUN`` so the API can preview behaviour without
   touching the device.
6. Otherwise, call ``dispatcher.dispatch_one()``. Any exception →
   mark failed with the exception text. Success → mark sent.

Cancellations are *always* logged in the attempts table so the
operator can audit "why we didn't send" later.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol, runtime_checkable

from boss_automation.database.followup_attempts_repository import (
    FollowupAttemptsRepository,
)
from boss_automation.database.message_repository import MessageRepository
from boss_automation.services.reengagement.detector import EligibleCandidate


class ReengagementKind(StrEnum):
    SENT = "sent"
    DRY_RUN = "dry_run"
    SKIPPED_CANDIDATE_REPLIED = "skipped_candidate_replied"
    SKIPPED_BLACKLISTED = "skipped_blacklisted"
    SKIPPED_DAILY_CAP = "skipped_daily_cap"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ReengagementSettings:
    silent_for_days: int = 3
    cooldown_days: int = 7
    daily_cap: int = 50


@dataclass(frozen=True, slots=True)
class ReengagementOutcome:
    kind: ReengagementKind
    candidate_id: int | None
    boss_candidate_id: str | None
    attempt_id: int | None
    detail: str | None = None


@runtime_checkable
class _DispatcherLike(Protocol):
    async def dispatch_one(
        self,
        *,
        is_blacklisted: Callable[[str], Awaitable[bool]] | None = None,
    ) -> object: ...


def _DEFAULT_CLOCK() -> datetime:
    return datetime.now(tz=UTC)


class ReengagementOrchestrator:
    def __init__(
        self,
        *,
        attempts_repo: FollowupAttemptsRepository,
        message_repo: MessageRepository,
        dispatcher: _DispatcherLike | None,
        is_blacklisted: Callable[[str], Awaitable[bool]],
        settings: ReengagementSettings,
        clock: Callable[[], datetime] = _DEFAULT_CLOCK,
    ) -> None:
        self._attempts_repo = attempts_repo
        self._message_repo = message_repo
        self._dispatcher = dispatcher
        self._is_blacklisted = is_blacklisted
        self._settings = settings
        self._clock = clock

    async def run_one(self, *, eligible: EligibleCandidate) -> ReengagementOutcome:
        now = _ensure_utc(self._clock())
        attempt_id = self._attempts_repo.append_pending(
            candidate_id=eligible.candidate_id,
            conversation_id=eligible.conversation_id,
            scheduled_at=now,
        )

        # 1. cancel-on-reply (mid-flight; real-time read of messages)
        if self._candidate_replied_after(eligible, now):
            self._attempts_repo.mark_cancelled(attempt_id, reason="candidate_replied")
            return self._outcome(
                ReengagementKind.SKIPPED_CANDIDATE_REPLIED,
                eligible,
                attempt_id,
            )

        # 2. daily cap (real-time count over the rolling 24h window)
        if self._daily_cap_reached(eligible, now):
            self._attempts_repo.mark_cancelled(attempt_id, reason="daily_cap")
            return self._outcome(
                ReengagementKind.SKIPPED_DAILY_CAP,
                eligible,
                attempt_id,
            )

        # 3. blacklist (AGENTS.md "Blacklist Send-Safety" guardrail)
        if await self._is_blacklisted(eligible.boss_candidate_id):
            self._attempts_repo.mark_cancelled(attempt_id, reason="blacklisted")
            return self._outcome(
                ReengagementKind.SKIPPED_BLACKLISTED,
                eligible,
                attempt_id,
            )

        # 4. dry-run (no dispatcher wired)
        if self._dispatcher is None:
            self._attempts_repo.mark_cancelled(attempt_id, reason="dry_run")
            return self._outcome(ReengagementKind.DRY_RUN, eligible, attempt_id)

        # 5. dispatch
        try:
            await self._dispatcher.dispatch_one(is_blacklisted=self._is_blacklisted)
        except Exception as exc:  # noqa: BLE001
            self._attempts_repo.mark_failed(attempt_id, reason=str(exc))
            return self._outcome(ReengagementKind.FAILED, eligible, attempt_id, detail=str(exc))

        self._attempts_repo.mark_sent(attempt_id, sent_at=_ensure_utc(self._clock()))
        return self._outcome(ReengagementKind.SENT, eligible, attempt_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _candidate_replied_after(self, eligible: EligibleCandidate, now: datetime) -> bool:
        rows = self._message_repo.list_for_conversation(eligible.conversation_id)
        last_out_iso = eligible.last_outbound_at_iso
        for msg in reversed(rows):
            if msg.direction == "in" and msg.sent_at_iso > last_out_iso:
                return True
        return False

    def _daily_cap_reached(self, eligible: EligibleCandidate, now: datetime) -> bool:
        if self._settings.daily_cap <= 0:
            return True
        since = now - timedelta(days=1)
        sent = self._attempts_repo.count_sent_in_range(
            recruiter_id=eligible.recruiter_id,
            since=since,
            until=now,
        )
        return sent >= self._settings.daily_cap

    @staticmethod
    def _outcome(
        kind: ReengagementKind,
        eligible: EligibleCandidate,
        attempt_id: int | None,
        *,
        detail: str | None = None,
    ) -> ReengagementOutcome:
        return ReengagementOutcome(
            kind=kind,
            candidate_id=eligible.candidate_id,
            boss_candidate_id=eligible.boss_candidate_id,
            attempt_id=attempt_id,
            detail=detail,
        )


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
