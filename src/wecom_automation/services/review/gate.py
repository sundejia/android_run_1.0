"""ReviewGate — bridge from persisted verdicts to MediaEventBus emissions.

Lifecycle of a single image:

    MessageProcessor inserts a pending_review row + asks ReviewClient to
    submit it to the rating-server. Eventually the inbound webhook receiver
    upserts a ``review_verdicts`` row and (in M8) calls ``ReviewGate.on_verdict``
    with the same ``message_id``.

    ReviewGate then:
        1. Loads the matching pending_review and verdict (no verdict ⇒ NO_VERDICT)
        2. Asks ``PolicyEvaluator`` whether the verdict is approved
        3. If approved → builds the same ``MediaEvent`` the legacy hot-path
           used and emits it on the existing ``MediaEventBus`` (so
           ``AutoGroupInviteAction`` keeps working unchanged)
        4. If rejected → marks the pending row and records analytics

The gate is idempotent per ``message_id``. The first call decides the
outcome; subsequent calls return ``ALREADY_PROCESSED`` without re-emitting.

Concurrency note: ``MessageProcessor._maybe_emit_media_event`` (M8) will
schedule ``on_verdict`` from the webhook handler. Because everything is
single-process and the storage layer is sqlite-serialised, a per-instance
``set`` is enough to dedupe without an external lock.
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from wecom_automation.services.media_actions.event_bus import MediaEventBus
from wecom_automation.services.media_actions.interfaces import MediaEvent
from wecom_automation.services.review.policy import PolicyEvaluator
from wecom_automation.services.review.storage import (
    PendingReviewRow,
    ReviewStorage,
)

logger = logging.getLogger("review.gate")


class ReviewGateOutcome(enum.StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    NO_VERDICT = "no_verdict"
    NO_PENDING = "no_pending"
    ALREADY_PROCESSED = "already_processed"


class ReviewGate:
    """Bridges review verdicts to the MediaEventBus."""

    EVENT_TYPE = "customer_media_detected"

    def __init__(
        self,
        *,
        storage: ReviewStorage,
        bus: MediaEventBus,
        settings_provider: Callable[[], dict[str, Any]] | None = None,
        evaluator: PolicyEvaluator | None = None,
        guard=None,
        settings_db_path: str | None = None,
    ) -> None:
        self._storage = storage
        self._bus = bus
        self._settings_provider = settings_provider or (lambda: {})
        self._evaluator = evaluator or PolicyEvaluator()
        self._guard = guard
        self._settings_db_path = settings_db_path
        self._processed: set[int] = set()

    @property
    def evaluator(self) -> PolicyEvaluator:
        return self._evaluator

    async def on_verdict(self, message_id: int) -> ReviewGateOutcome:
        if message_id in self._processed:
            logger.debug("gate already processed message_id=%s", message_id)
            return ReviewGateOutcome.ALREADY_PROCESSED

        pending = self._storage.get_pending_review(message_id)
        verdict = self._storage.get_verdict(message_id)

        if verdict is None:
            logger.warning("gate has no verdict for message_id=%s", message_id)
            return ReviewGateOutcome.NO_VERDICT

        if pending is None:
            logger.warning(
                "gate has verdict but no pending row for message_id=%s; recording rejected",
                message_id,
            )
            self._storage.record_event(
                "review.gate.no_pending",
                trace_id=str(message_id),
                payload={"decision": verdict.decision},
            )
            self._processed.add(message_id)
            return ReviewGateOutcome.NO_PENDING

        decision = self._evaluator.evaluate_verdict(verdict)

        if not decision.approved:
            self._storage.mark_pending_status(message_id, "rejected", last_error=decision.reason)
            self._storage.record_event(
                "review.gate.rejected",
                trace_id=str(message_id),
                payload={
                    "decision": verdict.decision,
                    "is_portrait": verdict.is_portrait,
                    "is_real_person": verdict.is_real_person,
                    "face_visible": verdict.face_visible,
                    "reason": decision.reason,
                    "skill_version": decision.skill_version,
                },
            )
            self._processed.add(message_id)
            return ReviewGateOutcome.REJECTED

        event = self._build_event(pending)
        settings = self._settings_provider() or {}

        # Resolve per-device overrides when device_serial and db path are available.
        if pending.device_serial and self._settings_db_path:
            from wecom_automation.services.media_actions.device_resolver import resolve_media_settings_by_device
            settings = resolve_media_settings_by_device(
                settings, pending.device_serial, self._settings_db_path,
            )

        if self._guard is not None:
            from wecom_automation.services.governance.guard import (
                GovernanceAction,
                GuardOutcome,
            )

            gov_decision = self._guard.check(
                action=GovernanceAction.GROUP_INVITE,
                device_serial=event.device_serial or "",
                settings=settings,
                trace_id=str(message_id),
            )
            if gov_decision.outcome == GuardOutcome.BLOCKED:
                self._storage.mark_pending_status(message_id, "blocked", last_error=gov_decision.reason)
                self._storage.record_event(
                    "review.gate.blocked",
                    trace_id=str(message_id),
                    payload={"reason": gov_decision.reason},
                )
                self._processed.add(message_id)
                return ReviewGateOutcome.REJECTED

        try:
            results = await self._bus.emit(event, settings)
        except Exception as exc:
            logger.exception("MediaEventBus.emit failed for message_id=%s", message_id)
            self._storage.mark_pending_status(message_id, "emit_failed", last_error=str(exc))
            self._storage.record_event(
                "review.gate.emit_failed",
                trace_id=str(message_id),
                payload={"error": str(exc)},
            )
            self._processed.add(message_id)
            return ReviewGateOutcome.APPROVED

        self._storage.mark_pending_status(message_id, "approved")
        self._storage.record_event(
            "review.gate.approved",
            trace_id=str(message_id),
            payload={
                "skill_version": decision.skill_version,
                "reason": decision.reason,
                "actions": [{"name": r.action_name, "status": r.status.value} for r in results],
            },
        )
        self._processed.add(message_id)
        return ReviewGateOutcome.APPROVED

    def _build_event(self, pending: PendingReviewRow) -> MediaEvent:
        return MediaEvent(
            event_type=self.EVENT_TYPE,
            message_type="image",
            customer_id=int(pending.customer_id or 0),
            customer_name=pending.customer_name or "",
            channel=pending.channel,
            device_serial=pending.device_serial or "",
            kefu_name=pending.kefu_name or "",
            message_id=pending.message_id,
            timestamp=datetime.now(UTC),
        )
