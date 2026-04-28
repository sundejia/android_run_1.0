"""Inbound webhook endpoints (image-rating-server -> android).

Exposes ``POST /api/webhooks/image-review`` which:

    1. Verifies the HMAC signature + idempotency key.
    2. Persists the verdict via :func:`services.webhook_receiver.handle_image_review`.
    3. Schedules ``ReviewGate.on_verdict(message_id)`` as a background task
       so the rating-server's HTTP call returns immediately while the gate
       (policy → governance → MediaEventBus) runs in process.

The route does **not** call into ADB / WeComService directly — that's the
gate / action chain's responsibility. Keeping this layer thin makes it
trivial to retry on failure: if the background task fails, the verdict is
already in the DB and the lifecycle scan will pick it up next startup.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from services.conversation_storage import get_control_db_path
from services.review_gate_runtime import get_review_gate
from services.webhook_receiver import (
    WebhookValidationError,
    handle_image_review,
)
from wecom_automation.services.review.storage import ReviewStorage

logger = logging.getLogger("webhooks.router")
router = APIRouter()


def _get_secret() -> str:
    """Resolve the webhook HMAC secret.

    Resolution order:
        1. ``REVIEW_WEBHOOK_SECRET`` environment variable (12-factor friendly)
        2. ``review_gate.webhook_secret`` setting (deferred fallback)

    Note: Both sources are operator-controlled — the model cannot rewrite
    them via chat / prompt output.
    """
    env_secret = os.environ.get("REVIEW_WEBHOOK_SECRET")
    if env_secret:
        return env_secret

    try:
        from services.settings import get_settings_service

        svc = get_settings_service()
        cat = svc.get_category("media_auto_actions") or {}
        gate = cat.get("review_gate") or {}
        return gate.get("webhook_secret") or ""
    except Exception:
        return ""


def _get_storage() -> ReviewStorage:
    db_path = str(get_control_db_path())
    return ReviewStorage(db_path)


async def _drive_gate(message_id: int) -> None:
    """Background driver: hand the persisted verdict to the ReviewGate."""
    gate = get_review_gate()
    if gate is None:
        logger.debug(
            "ReviewGate disabled by settings; skipping on_verdict(message_id=%s)",
            message_id,
        )
        return
    try:
        outcome = await gate.on_verdict(message_id)
        logger.info(
            "ReviewGate.on_verdict message_id=%s -> %s",
            message_id,
            getattr(outcome, "value", outcome),
        )
    except Exception:
        logger.exception("ReviewGate.on_verdict failed for message_id=%s", message_id)


@router.post("/image-review")
async def receive_image_review(request: Request, background_tasks: BackgroundTasks) -> dict:
    body = await request.body()
    headers = dict(request.headers)

    secret = _get_secret()
    if not secret:
        logger.error("REVIEW_WEBHOOK_SECRET is not configured; rejecting request")
        raise HTTPException(status_code=503, detail="webhook secret not configured")

    try:
        result = handle_image_review(
            body=body,
            headers=headers,
            secret=secret,
            storage=_get_storage(),
        )
    except WebhookValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:
        logger.exception("unexpected error handling image-review webhook")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if result.status == "accepted" and result.message_id is not None:
        background_tasks.add_task(_drive_gate, result.message_id)

    return {
        "status": result.status,
        "message_id": result.message_id,
        "decision": result.decision,
    }
