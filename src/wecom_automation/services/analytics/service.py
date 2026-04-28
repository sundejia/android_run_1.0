"""AnalyticsService — the single recording entry-point for android_run.

Replaces ad-hoc ``print`` calls and the previous direct
``ReviewStorage.record_event`` reach-throughs with a small named-event
vocabulary that downstream consumers (dashboards, replay tools, training
pipelines) can rely on.

Usage::

    analytics = AnalyticsService(storage)
    analytics.record(EventType.REVIEW_SUBMITTED, trace_id=str(message_id),
                     payload={"image_path": image_path})

The service intentionally swallows persistence errors: telemetry
failures must never block business logic. If you need stronger
guarantees, persist explicitly before calling ``record``.
"""

from __future__ import annotations

import enum
import logging
import threading
from typing import Any

from wecom_automation.services.review.storage import (
    AnalyticsEventRow,
    ReviewStorage,
)

logger = logging.getLogger("analytics.android")


class EventType(enum.StrEnum):
    # Review pipeline
    REVIEW_SUBMITTED = "review.submitted"
    REVIEW_VERDICT_RECEIVED = "review.verdict.received"
    REVIEW_GATE_APPROVED = "review.gate.approved"
    REVIEW_GATE_REJECTED = "review.gate.rejected"
    REVIEW_GATE_BLOCKED = "review.gate.blocked"
    REVIEW_GATE_EMIT_FAILED = "review.gate.emit_failed"
    REVIEW_GATE_NO_PENDING = "review.gate.no_pending"
    REVIEW_WEBHOOK_REPLAY = "review.webhook.replay"

    # Video policy
    VIDEO_INVITE_SKIPPED = "video.invite.skipped"

    # Governance
    GOVERNANCE_ALLOWED = "governance.allowed"
    GOVERNANCE_BLOCKED = "governance.blocked"

    # Lifecycle
    LIFECYCLE_PENDING_RESUBMITTED = "lifecycle.pending.resubmitted"
    LIFECYCLE_PENDING_EXPIRED = "lifecycle.pending.expired"
    LIFECYCLE_IDEMPOTENCY_PURGED = "lifecycle.idempotency.purged"
    LIFECYCLE_ORPHAN_MOVED = "lifecycle.orphan.moved"


class AnalyticsService:
    """Thin facade over :meth:`ReviewStorage.record_event`."""

    def __init__(self, storage: ReviewStorage) -> None:
        self._storage = storage

    def record(
        self,
        event: EventType | str,
        *,
        trace_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        event_type = event.value if isinstance(event, EventType) else str(event)
        try:
            self._storage.record_event(event_type, trace_id=trace_id, payload=payload or {})
        except Exception:
            logger.exception(
                "analytics.record failed event=%s trace_id=%s",
                event_type,
                trace_id,
            )

    def list_events(
        self,
        *,
        event_type: str | None = None,
        trace_id: str | None = None,
        limit: int = 200,
    ) -> list[AnalyticsEventRow]:
        return self._storage.list_events(event_type=event_type, trace_id=trace_id, limit=limit)


_lock = threading.Lock()
_default: dict[str, AnalyticsService] = {}


def get_default_service(*, storage: ReviewStorage | None = None) -> AnalyticsService:
    """Return the process-singleton AnalyticsService.

    The first caller binds ``storage``; subsequent calls reuse it.
    """
    with _lock:
        svc = _default.get("svc")
        if svc is not None:
            return svc
        if storage is None:
            raise RuntimeError("AnalyticsService not yet initialised; pass storage on first call")
        svc = AnalyticsService(storage)
        _default["svc"] = svc
        return svc


def reset_default_service() -> None:
    with _lock:
        _default.clear()
