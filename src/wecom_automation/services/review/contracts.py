"""Shared review/webhook contracts (android side mirror).

The on-the-wire JSON shape MUST stay identical to the rating-server module at
``image-rating-server/backend/app/services/webhook/contracts.py``. We avoid a
hard dependency on Pydantic on the android side (it does not bring it in as a
top-level dep), so we use frozen dataclasses with explicit validation.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Final

IMAGE_REVIEW_COMPLETED_EVENT: Final[str] = "image_review.completed"

DECISION_PASS: Final[str] = "合格"
DECISION_FAIL: Final[str] = "不合格"
_VALID_DECISIONS: Final[frozenset[str]] = frozenset({DECISION_PASS, DECISION_FAIL})

_REQUIRED_VERDICT_FIELDS: Final[tuple[str, ...]] = (
    "image_id",
    "correlation_id",
    "decision",
    "is_portrait",
    "is_real_person",
    "face_visible",
    "model_name",
    "analyzed_at",
)


@dataclass(frozen=True)
class ReviewVerdict:
    """Result of analyzing one image, ready for downstream gating."""

    image_id: str
    correlation_id: str
    decision: str
    is_portrait: bool
    is_real_person: bool
    face_visible: bool
    model_name: str
    analyzed_at: str
    final_score: float | None = None
    prompt_version_id: str | None = None
    prompt_version_number: int | None = None
    raw_details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ReviewVerdict:
        if not isinstance(payload, dict):
            raise TypeError("verdict payload must be a dict")
        for key in _REQUIRED_VERDICT_FIELDS:
            if key not in payload:
                raise KeyError(f"missing required field: {key}")
        decision = payload["decision"]
        if decision not in _VALID_DECISIONS:
            raise ValueError(
                f"invalid decision {decision!r}; expected one of {sorted(_VALID_DECISIONS)}"
            )
        return cls(
            image_id=str(payload["image_id"]),
            correlation_id=str(payload["correlation_id"]),
            decision=decision,
            is_portrait=bool(payload["is_portrait"]),
            is_real_person=bool(payload["is_real_person"]),
            face_visible=bool(payload["face_visible"]),
            model_name=str(payload["model_name"]),
            analyzed_at=str(payload["analyzed_at"]),
            final_score=payload.get("final_score"),
            prompt_version_id=payload.get("prompt_version_id"),
            prompt_version_number=payload.get("prompt_version_number"),
            raw_details=dict(payload.get("raw_details") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


@dataclass(frozen=True)
class WebhookEnvelope:
    """Outer wrapper carrying the verdict over HTTP."""

    event_id: str
    event_type: str
    idempotency_key: str
    occurred_at: str
    data: ReviewVerdict

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> WebhookEnvelope:
        for key in ("event_id", "event_type", "idempotency_key", "occurred_at", "data"):
            if key not in payload:
                raise KeyError(f"missing required field: {key}")
        if payload["event_type"] != IMAGE_REVIEW_COMPLETED_EVENT:
            raise ValueError(
                f"unsupported event_type {payload['event_type']!r}; "
                f"expected {IMAGE_REVIEW_COMPLETED_EVENT!r}"
            )
        return cls(
            event_id=str(payload["event_id"]),
            event_type=str(payload["event_type"]),
            idempotency_key=str(payload["idempotency_key"]),
            occurred_at=str(payload["occurred_at"]),
            data=ReviewVerdict.from_dict(payload["data"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "idempotency_key": self.idempotency_key,
            "occurred_at": self.occurred_at,
            "data": self.data.to_dict(),
        }


def parse_envelope(body: str | bytes) -> WebhookEnvelope:
    """Parse a JSON-encoded envelope and validate the schema.

    Raises ``ValueError`` for malformed JSON or unexpected ``event_type``.
    """
    if isinstance(body, (bytes, bytearray)):
        text = body.decode("utf-8")
    else:
        text = body
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON envelope: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("envelope must be a JSON object")
    return WebhookEnvelope.from_dict(payload)


def is_approved(verdict: ReviewVerdict) -> bool:
    """Approval rule (V1, skill v1).

    Approved iff decision == 合格 AND is_portrait AND is_real_person AND face_visible.
    """
    return (
        verdict.decision == DECISION_PASS
        and bool(verdict.is_portrait)
        and bool(verdict.is_real_person)
        and bool(verdict.face_visible)
    )
