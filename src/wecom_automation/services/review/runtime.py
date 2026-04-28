"""Runtime assembly helpers for the review-gating pipeline.

Centralises the (otherwise repetitive) work of:
    * Reading ``media_auto_actions.review_gate.*`` settings.
    * Constructing a ``ReviewClient`` pointed at the configured rating-server.
    * Returning a closure that ``MessageProcessor`` can call as
      ``review_submitter(message_id, image_path)``.

Keeping this in one place means the sync orchestrator factory and the
realtime-reply factory share the exact same wiring, so production never
diverges from what the tests cover.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from wecom_automation.services.review.client import (
    ReviewClient,
    ReviewSubmissionError,
)
from wecom_automation.services.review.storage import ReviewStorage

logger = logging.getLogger("review.runtime.assembly")


DEFAULT_RATING_SERVER_URL = "http://127.0.0.1:8080"


def review_gate_settings(media_settings: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(media_settings, dict):
        return {}
    return media_settings.get("review_gate") or {}


def review_gate_enabled(media_settings: dict[str, Any] | None) -> bool:
    cfg = review_gate_settings(media_settings)
    return bool(cfg.get("enabled", False))


def build_review_components(
    *,
    db_path: str,
    media_settings: dict[str, Any] | None,
) -> tuple[ReviewStorage | None, Callable[[int, str], Awaitable[None]] | None, bool]:
    """Return ``(storage, submitter, enabled)`` ready for ``MessageProcessor``.

    Returns ``(None, None, False)`` when the gate is disabled — callers
    should fall through to the legacy direct-emit behaviour.
    """
    if not review_gate_enabled(media_settings):
        return None, None, False

    cfg = review_gate_settings(media_settings)
    rating_server_url = cfg.get("rating_server_url") or DEFAULT_RATING_SERVER_URL
    timeout_seconds = float(cfg.get("upload_timeout_seconds", 30.0))
    max_attempts = int(cfg.get("upload_max_attempts", 3))

    storage = ReviewStorage(db_path)
    client = ReviewClient(
        rating_server_url=rating_server_url,
        request_timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
    )

    async def _submitter(message_id: int, image_path: str) -> None:
        try:
            await client.submit(image_path=image_path, message_id=int(message_id))
        except ReviewSubmissionError as exc:
            logger.warning("review submission failed message_id=%s err=%s", message_id, exc)
            try:
                storage.mark_pending_status(int(message_id), "submit_failed", last_error=str(exc))
            except Exception:
                logger.exception("failed to mark pending submit_failed")
            raise

    return storage, _submitter, True
