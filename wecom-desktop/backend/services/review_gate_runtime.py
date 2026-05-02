"""Process-singleton wiring for the inbound review pipeline.

The webhook router needs three collaborators to actually drive a group invite:

    1. ``ReviewStorage``       — persistence layer
    2. ``MediaEventBus``       — emits ``MediaEvent`` to ``AutoGroupInviteAction``
    3. ``ReviewGate``          — bridges (1) and (2) after policy + governance

These were unit-tested in isolation, but until this module they were not
constructed at runtime. We expose a tiny ``get_review_gate()`` factory so the
router can ``asyncio.create_task(gate.on_verdict(message_id))`` immediately
after the verdict is persisted, without blocking the HTTP response.

Design notes:
    * The bus / actions are wired here too so the desktop backend can drive
      group invites end-to-end. ``WeComService`` is intentionally pluggable
      via ``set_wecom_service`` — it is set when sync subprocesses come up.
    * The whole module is a no-op (returns ``None``) when
      ``review_gate.enabled = false`` so legacy deployments keep working.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from wecom_automation.services.governance import ExecutionPolicyGuard
from wecom_automation.services.media_actions.event_bus import MediaEventBus
from wecom_automation.services.review.gate import ReviewGate
from wecom_automation.services.review.policy import PolicyEvaluator
from wecom_automation.services.review.storage import ReviewStorage

logger = logging.getLogger("review.runtime")

_lock = threading.Lock()
_singleton: dict[str, Any] = {}


def _settings_provider() -> dict[str, Any]:
    """Read the live media_auto_actions settings without caching.

    Returning a fresh dict on every call means kill-switch / rate-limit
    changes take effect immediately without a process restart.
    """
    try:
        from services.settings import get_settings_service

        svc = get_settings_service()
        return svc.get_category("media_auto_actions") or {}
    except Exception as exc:
        logger.warning("failed to read media_auto_actions settings: %s", exc)
        return {}


def _is_enabled(settings: dict[str, Any]) -> bool:
    gate_cfg = (settings.get("review_gate") or {}) if isinstance(settings, dict) else {}
    # Default ON when the new pipeline is in use; legacy deployments can set it to false.
    return bool(gate_cfg.get("enabled", True))


def get_review_gate(*, storage: ReviewStorage | None = None) -> ReviewGate | None:
    """Lazily build (and memoize) the process-wide ReviewGate.

    Returns ``None`` if the feature is disabled in settings.
    """
    settings = _settings_provider()
    if not _is_enabled(settings):
        return None

    with _lock:
        gate = _singleton.get("gate")
        if gate is not None:
            return gate

        if storage is None:
            from services.conversation_storage import get_control_db_path

            storage = ReviewStorage(str(get_control_db_path()))

        bus = MediaEventBus()
        _register_default_actions(bus)

        guard = ExecutionPolicyGuard(storage=storage)
        gate = ReviewGate(
            storage=storage,
            bus=bus,
            settings_provider=_settings_provider,
            evaluator=PolicyEvaluator(),
            guard=guard,
        )
        _singleton["gate"] = gate
        _singleton["bus"] = bus
        _singleton["storage"] = storage
        logger.info("ReviewGate runtime initialised")
        return gate


def get_storage() -> ReviewStorage | None:
    """Return the singleton storage (constructed alongside the gate)."""
    return _singleton.get("storage")


def reset_for_tests() -> None:
    with _lock:
        _singleton.clear()


def _register_default_actions(bus: MediaEventBus) -> None:
    """Best-effort registration of canonical auto-actions.

    Each action requires a live ``WeComService``. In production that is
    injected per device by the sync subprocess via :func:`bind_wecom_service`.
    Here we register placeholders that short-circuit in ``should_execute``
    until wired up. If an import fails (e.g. running without the full
    dependency tree), we skip gracefully — tests register their own actions.
    """
    try:
        from wecom_automation.services.media_actions.actions.auto_group_invite import (
            AutoGroupInviteAction,
        )

        action = AutoGroupInviteAction(group_chat_service=None)
        bus.register(action)
    except Exception as exc:
        logger.warning("AutoGroupInviteAction not registered: %s", exc)

    try:
        from wecom_automation.services.media_actions.actions.auto_contact_share import (
            AutoContactShareAction,
        )
        from wecom_automation.services.contact_share.service import ContactShareService

        action = AutoContactShareAction(
            contact_share_service=ContactShareService(wecom_service=None)
        )
        bus.register(action)
    except Exception as exc:
        logger.warning("AutoContactShareAction not registered: %s", exc)


def bind_wecom_service(wecom_service: Any, *, db_path: str | None = None) -> None:
    """Inject a live WeComService into all registered auto-actions.

    Called by the follow-up / sync subprocess once it has acquired a device
    session.  Builds concrete service objects (GroupChatService,
    ContactShareService) and replaces the placeholder ``action._service``.
    """
    bus = _singleton.get("bus")
    if bus is None:
        return
    bound = 0
    for action in getattr(bus, "_actions", []):
        name = getattr(action, "action_name", "")
        try:
            if name == "auto_group_invite":
                from wecom_automation.services.media_actions.group_chat_service import (
                    GroupChatService,
                )

                action._service = GroupChatService(
                    wecom_service=wecom_service, db_path=db_path
                )
                bound += 1
            elif name == "auto_contact_share":
                from wecom_automation.services.contact_share.service import (
                    ContactShareService,
                )

                action._service = ContactShareService(
                    wecom_service=wecom_service, db_path=db_path
                )
                bound += 1
        except Exception as exc:
            logger.warning("Failed to inject WeComService into action %s: %s", name, exc)
    if bound:
        logger.info("Bound WeComService to %d review gate action(s)", bound)
