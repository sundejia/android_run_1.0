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
from wecom_automation.services.media_actions.settings_loader import load_media_auto_action_settings

logger = logging.getLogger(__name__)


def build_media_event_bus(
    db_path: str,
    settings_db_path: str | None = None,
    effects_db_path: str | None = None,
    wecom_service=None,
    on_action_results: Callable | None = None,
) -> tuple[MediaEventBus | None, dict[str, Any]]:
    """
    Build a MediaEventBus pre-loaded with auto-actions if the feature is enabled.

    Args:
        db_path: Path to the SQLite database used for action side effects such
            as blacklist and group records.
        settings_db_path: Optional path to the SQLite database that stores the
            ``settings`` table. Defaults to ``db_path`` for backward
            compatibility.
        effects_db_path: Optional path to the SQLite database that stores
            media action side effects such as blacklist rows and group tracking.
            Defaults to ``settings_db_path`` when provided, otherwise ``db_path``.
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

    if not settings.get("enabled"):
        return None, settings

    bus = MediaEventBus(on_action_results=on_action_results)

    # Registration order matters: the bus dispatches actions in the order they
    # are registered, so this ordering encodes product semantics —
    #   1) contact-card share happens first while we are still in the active
    #      chat (no navigation restore so the next action stays in context),
    #   2) group invite then pulls the customer into the service group,
    #   3) blacklist runs last so the 1:1 chat is closed off only after the
    #      preceding UI flows have completed.
    if wecom_service is not None:
        try:
            from wecom_automation.services.contact_share.service import ContactShareService
            from wecom_automation.services.media_actions.actions.auto_contact_share import (
                AutoContactShareAction,
            )

            bus.register(AutoContactShareAction(
                ContactShareService(wecom_service=wecom_service, db_path=effects_db_path),
                db_path=effects_db_path,
                restore_navigation_after_execute=False,
            ))
        except Exception as exc:
            logger.warning("Could not register AutoContactShareAction: %s", exc)

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

    bus.register(AutoBlacklistAction(BlacklistWriter(effects_db_path), db_path=db_path))

    return bus, settings
