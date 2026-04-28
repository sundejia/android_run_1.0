"""Image-review webhook receiver (pure handler).

This module is intentionally framework-agnostic so it can be unit-tested
without spinning up FastAPI / TestClient. The router in ``routers/webhooks.py``
is a thin adapter that translates HTTP request/response to/from this handler.

Responsibilities:
    * HMAC-SHA256 signature verification (replay/forgery resistance)
    * Idempotency check via ``webhook_idempotency`` table
    * Envelope parsing & event-type guard
    * Persisting the ``ReviewVerdict`` and updating the matching
      ``pending_reviews`` row's status
    * Emitting structured analytics events for observability

The module deliberately does *not* trigger any UI / ADB / group-invite work.
That belongs to the next layer (ReviewGate, M7) which subscribes to the
``review.verdict.received`` analytics event or polls ``review_verdicts``.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from wecom_automation.services.review.contracts import (
    IMAGE_REVIEW_COMPLETED_EVENT,
    WebhookEnvelope,
    parse_envelope,
)
from wecom_automation.services.review.storage import (
    ReviewStorage,
    ReviewVerdictRow,
)

logger = logging.getLogger("webhook_receiver.image_review")


SIGNATURE_HEADER = "X-IRS-Signature"
IDEMPOTENCY_HEADER = "X-IRS-Idempotency-Key"
EVENT_HEADER = "X-IRS-Event"


class WebhookValidationError(Exception):
    """Raised when the inbound request is malformed/forged.

    The router maps ``status_code`` directly to the HTTP response code.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class WebhookHandleResult:
    status: str  # "accepted" | "replay"
    message_id: int | None
    decision: str | None


def _compute_signature(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _safe_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _get_header(headers: Mapping[str, str], name: str) -> str | None:
    """Case-insensitive lookup that tolerates either dict-of-strings or a
    framework-provided ``Headers`` object.
    """
    if hasattr(headers, "get"):
        v = headers.get(name)
        if v is not None:
            return v
        v = headers.get(name.lower())
        if v is not None:
            return v
    for k, v in dict(headers).items():
        if k.lower() == name.lower():
            return v
    return None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _verdict_row_from_envelope(env: WebhookEnvelope) -> ReviewVerdictRow:
    import json

    return ReviewVerdictRow(
        message_id=int(env.data.correlation_id),
        image_id=env.data.image_id,
        decision=env.data.decision,
        is_portrait=env.data.is_portrait,
        is_real_person=env.data.is_real_person,
        face_visible=env.data.face_visible,
        final_score=env.data.final_score,
        raw_payload_json=json.dumps(env.to_dict(), ensure_ascii=False),
        prompt_version_id=env.data.prompt_version_id,
        skill_version="v1",
        received_at=_now_iso(),
    )


def handle_image_review(
    *,
    body: bytes,
    headers: Mapping[str, str],
    secret: str,
    storage: ReviewStorage,
) -> WebhookHandleResult:
    """Process one inbound image-review webhook.

    Args:
        body: Raw request body (bytes); MUST be the exact bytes the sender
            signed. Re-serializing parsed JSON would break HMAC verification.
        headers: Incoming HTTP headers (case-insensitive lookup).
        secret: Shared HMAC secret (loaded from settings/env, never from
            user-controllable model output).
        storage: Already-initialised ``ReviewStorage`` bound to the android DB.

    Returns:
        ``WebhookHandleResult`` with status ``"accepted"`` for first-seen
        events and ``"replay"`` if the idempotency key was already recorded.

    Raises:
        WebhookValidationError: On missing/invalid signature, malformed JSON,
            or wrong event type. The router translates ``status_code`` 1:1
            into the HTTP response.
    """
    if not secret:
        raise WebhookValidationError(500, "webhook secret not configured")

    signature = _get_header(headers, SIGNATURE_HEADER)
    if not signature:
        raise WebhookValidationError(401, "missing signature header")

    expected = _compute_signature(body, secret)
    if not _safe_eq(signature, expected):
        raise WebhookValidationError(401, "invalid signature")

    try:
        envelope = parse_envelope(body)
    except (ValueError, KeyError, TypeError) as exc:
        raise WebhookValidationError(400, f"invalid envelope: {exc}") from exc

    if envelope.event_type != IMAGE_REVIEW_COMPLETED_EVENT:
        raise WebhookValidationError(400, f"unsupported event_type: {envelope.event_type}")

    idempotency_key = _get_header(headers, IDEMPOTENCY_HEADER) or envelope.idempotency_key
    if not idempotency_key:
        raise WebhookValidationError(400, "missing idempotency key")

    first_seen = storage.try_register_idempotency_key(idempotency_key, _now_iso())

    correlation = envelope.data.correlation_id
    try:
        message_id = int(correlation)
    except (TypeError, ValueError) as exc:
        raise WebhookValidationError(400, f"correlation_id must be integer message_id, got {correlation!r}") from exc

    if not first_seen:
        logger.info(
            "webhook replay ignored idempotency_key=%s message_id=%s",
            idempotency_key,
            message_id,
        )
        storage.record_event(
            "review.webhook.replay",
            trace_id=str(message_id),
            payload={"idempotency_key": idempotency_key},
        )
        return WebhookHandleResult(status="replay", message_id=message_id, decision=envelope.data.decision)

    row = _verdict_row_from_envelope(envelope)
    storage.upsert_verdict(row)

    pending = storage.get_pending_review(message_id)
    if pending is not None:
        storage.mark_pending_status(message_id, "verdict_received")
    else:
        logger.warning(
            "verdict for unknown pending_review message_id=%s; storing anyway",
            message_id,
        )

    storage.record_event(
        "review.verdict.received",
        trace_id=str(message_id),
        payload={
            "decision": envelope.data.decision,
            "is_portrait": envelope.data.is_portrait,
            "is_real_person": envelope.data.is_real_person,
            "face_visible": envelope.data.face_visible,
            "prompt_version_id": envelope.data.prompt_version_id,
            "model_name": envelope.data.model_name,
            "had_pending": pending is not None,
        },
    )

    return WebhookHandleResult(
        status="accepted",
        message_id=message_id,
        decision=envelope.data.decision,
    )
