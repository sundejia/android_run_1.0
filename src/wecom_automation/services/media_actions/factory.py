"""
Shared factory for building a MediaEventBus with registered auto-actions.

Used by both the full-sync path (sync/factory.py) and the follow-up /
realtime-reply path (ResponseDetector) so that media auto-actions are
wired identically regardless of entry point.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from wecom_automation.services.blacklist_service import BlacklistWriter
from wecom_automation.services.media_actions.actions.auto_blacklist import AutoBlacklistAction
from wecom_automation.services.media_actions.event_bus import MediaEventBus
from wecom_automation.services.media_actions.kefu_resolver import resolve_media_settings
from wecom_automation.services.media_actions.settings_loader import load_media_auto_action_settings

logger = logging.getLogger(__name__)


def build_media_event_bus(
    db_path: str,
    settings_db_path: str | None = None,
    effects_db_path: str | None = None,
    wecom_service=None,
    on_action_results: Callable | None = None,
    kefu_name: str | None = None,
) -> tuple[MediaEventBus | None, dict[str, Any]]:
    """
    Build a MediaEventBus pre-loaded with auto-actions if the feature is enabled.

    Args:
        db_path: Path to the **per-device conversation** SQLite database (the
            one that owns ``messages`` / ``images`` / ``videos`` rows). Passed to
            ``AutoContactShareAction`` / ``AutoGroupInviteAction`` /
            ``AutoBlacklistAction`` so ``evaluate_gate_pass`` reads
            ``ai_review_*`` from the correct file. Callers that split control DB
            vs device DB **must** pass the device conversation path here.
        settings_db_path: Optional path to the SQLite database that stores the
            ``settings`` table. Defaults to ``db_path`` for backward
            compatibility.
        effects_db_path: Optional **control** database for blacklist rows, group
            tracking, and ``media_action_contact_shares`` idempotency.
            ``ContactShareService`` / ``GroupChatService`` use this path;
            gate evaluation still uses ``db_path``. Defaults to
            ``settings_db_path`` when provided, otherwise ``db_path``.
        wecom_service: Optional WeComService instance.  When provided,
            ``AutoGroupInviteAction`` is registered (it needs WeComService for
            group-chat creation).  When ``None``, only ``AutoBlacklistAction``
            is registered.
        on_action_results: Optional async callback ``(event, results) -> None``
            invoked after ``emit()`` when at least one action succeeds.

    Returns:
        ``(bus, settings)`` where *bus* is ``None`` when media auto-actions are
        disabled, and *settings* is the merged settings dict.
    """
    settings_db_path = settings_db_path or db_path
    effects_db_path = effects_db_path or settings_db_path or db_path

    try:
        settings = load_media_auto_action_settings(settings_db_path)
    except Exception as exc:
        logger.warning("Failed to load media auto-action settings: %s", exc)
        return None, {"enabled": False}

    # Apply per-kefu overrides when kefu_name is provided.
    if kefu_name:
        try:
            settings = resolve_media_settings(settings, kefu_name, settings_db_path)
        except Exception as exc:
            logger.warning("Failed to resolve per-kefu settings for kefu=%s: %s", kefu_name, exc)

    if not settings.get("enabled"):
        return None, settings

    bus = MediaEventBus(on_action_results=on_action_results)

    # Registration order matters: the bus dispatches actions in the order they
    # are registered, so this ordering encodes product semantics —
    #   1) blacklist runs first so the customer is blocked from AI reply/follow-up,
    #   2) group invite then pulls the customer into the service group,
    #   3) contact-card share happens last (no navigation restore so it stays
    #      in context for any UI that follows).
    bus.register(AutoBlacklistAction(BlacklistWriter(effects_db_path), db_path=db_path))

    if wecom_service is not None:
        try:
            from wecom_automation.services.media_actions.actions.auto_group_invite import (
                AutoGroupInviteAction,
            )
            from wecom_automation.services.media_actions.group_chat_service import GroupChatService

            bus.register(
                AutoGroupInviteAction(
                    GroupChatService(wecom_service=wecom_service, db_path=effects_db_path),
                    db_path=db_path,
                )
            )
        except Exception as exc:
            logger.warning("Could not register AutoGroupInviteAction: %s", exc)

    if wecom_service is not None:
        try:
            from wecom_automation.services.contact_share.service import ContactShareService
            from wecom_automation.services.media_actions.actions.auto_contact_share import (
                AutoContactShareAction,
            )

            # Note: AutoContactShareAction.db_path MUST be the conversation DB
            # (the one that owns the messages/images/videos rows), because
            # ``evaluate_gate_pass`` queries ``images.ai_review_*`` /
            # ``videos.ai_review_*`` against it. ContactShareService keeps
            # ``effects_db_path`` for the idempotency table
            # (``media_action_contact_shares``), which is intentionally a
            # control-level concern.
            bus.register(AutoContactShareAction(
                ContactShareService(wecom_service=wecom_service, db_path=effects_db_path),
                db_path=db_path,
                restore_navigation_after_execute=False,
            ))
        except Exception as exc:
            logger.warning("Could not register AutoContactShareAction: %s", exc)

    return bus, settings
