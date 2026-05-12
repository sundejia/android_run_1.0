"""Runtime assembly helpers for the review-gating pipeline.

Centralises the (otherwise repetitive) work of:
    * Reading ``media_auto_actions.review_gate.enabled`` (gate toggle).
    * Reading ``general.image_server_ip`` /
      ``general.image_review_timeout_seconds`` (the app-level singletons
      that also back the realtime ``image_review_client``).
    * Constructing a ``ReviewClient`` pointed at the configured rating-server.
    * Returning a closure that ``MessageProcessor`` can call as
      ``review_submitter(message_id, image_path)``.

Keeping this in one place means the sync orchestrator factory and the
realtime-reply factory share the exact same wiring, so production never
diverges from what the tests cover.

Note (2026-05-12 dedup): the rating-server URL/timeout used to live under
``media_auto_actions.review_gate`` so they had to be filled in twice
(once in SettingsView, once in MediaActionsView). They are now read from
``general.*`` only. ``review_gate.rating_server_url`` etc. on legacy
settings rows are ignored (and migrated by ``SettingsService`` on the
next process start).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from wecom_automation.services.media_actions.settings_loader import (
    DEFAULT_IMAGE_REVIEW_TIMEOUT_SECONDS,
    load_general_image_review_settings,
)
from wecom_automation.services.review.client import (
    ReviewClient,
    ReviewSubmissionError,
)
from wecom_automation.services.review.storage import ReviewStorage

logger = logging.getLogger("review.runtime.assembly")


# Legacy default kept ONLY for callers that pass an explicit
# ``general_settings={"image_server_ip": ""}`` and want the old behaviour
# of falling through to a localhost rating-server. Anything else should
# leave general.image_server_ip blank, which now correctly disables the
# gate (instead of silently pointing at 127.0.0.1).
_LEGACY_LOCALHOST_URL = "http://127.0.0.1:8080"


def review_gate_settings(media_settings: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(media_settings, dict):
        return {}
    return media_settings.get("review_gate") or {}


def review_gate_enabled(media_settings: dict[str, Any] | None) -> bool:
    cfg = review_gate_settings(media_settings)
    return bool(cfg.get("enabled", False))


def _resolve_image_review_settings(
    *,
    settings_db_path: str | None,
    general_settings: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge caller-supplied general settings with what's on disk.

    Precedence:
        1. ``general_settings`` argument (test or caller override).
        2. Rows in the ``general`` category of the SQLite ``settings``
           table at ``settings_db_path``.
        3. Module defaults (empty URL, 40s timeout, upload enabled).
    """
    on_disk: dict[str, Any] = {}
    if settings_db_path:
        on_disk = load_general_image_review_settings(settings_db_path)
    overrides = general_settings or {}
    return {**on_disk, **overrides}


def build_review_components(
    *,
    db_path: str,
    media_settings: dict[str, Any] | None,
    settings_db_path: str | None = None,
    general_settings: dict[str, Any] | None = None,
) -> tuple[ReviewStorage | None, Callable[[int, str], Awaitable[None]] | None, bool]:
    """Return ``(storage, submitter, enabled)`` ready for ``MessageProcessor``.

    Args:
        db_path: Conversation/device DB; passed to ``ReviewStorage``.
        media_settings: Already-loaded ``media_auto_actions`` dict (callers
            usually get this from ``build_media_event_bus``).
        settings_db_path: SQLite file that owns the ``settings`` table.
            Defaults to ``db_path`` for backward compatibility (the
            simple deployments where conversation DB and settings DB are
            the same file).
        general_settings: Optional override for the resolved general
            settings (image_server_ip / image_review_timeout_seconds /
            image_upload_enabled). Tests use this to bypass disk I/O.

    Returns ``(None, None, False)`` when the gate is disabled, the upload
    feature is turned off, or no rating-server URL is configured. Callers
    fall through to legacy direct-emit behaviour in that case.
    """
    if not review_gate_enabled(media_settings):
        return None, None, False

    resolved_settings_db = settings_db_path or db_path
    general = _resolve_image_review_settings(
        settings_db_path=resolved_settings_db,
        general_settings=general_settings,
    )

    if not bool(general.get("image_upload_enabled", True)):
        logger.warning(
            "review gate enabled but general.image_upload_enabled=False; "
            "skipping review pipeline (server URL=%r)",
            general.get("image_server_ip"),
        )
        return None, None, False

    rating_server_url = str(general.get("image_server_ip") or "").strip()
    if not rating_server_url:
        logger.warning(
            "review gate enabled but general.image_server_ip is empty; "
            "configure the image-rating-server in System Settings to enable the gate."
        )
        return None, None, False

    try:
        timeout_seconds = max(1, int(general.get("image_review_timeout_seconds", DEFAULT_IMAGE_REVIEW_TIMEOUT_SECONDS)))
    except (TypeError, ValueError):
        timeout_seconds = DEFAULT_IMAGE_REVIEW_TIMEOUT_SECONDS

    storage = ReviewStorage(db_path)
    client = ReviewClient(
        rating_server_url=rating_server_url,
        request_timeout_seconds=float(timeout_seconds),
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
