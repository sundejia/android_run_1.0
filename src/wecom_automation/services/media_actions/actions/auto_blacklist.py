"""
AutoBlacklistAction - automatically add customer to blacklist on media detection.

When a customer sends an image or video, this action adds them to the
blacklist with a configurable reason. Supports idempotency via
skip_if_already_blacklisted.

By default the action operates in **standalone mode**: any customer who
sends an image/video is blacklisted immediately, without consulting the
image-rating-server review pipeline. This matches the typical product
expectation ("发图/视频 → 拉黑") and works for deployments that have not
opted into review_gate.

When ``auto_blacklist.require_review_pass`` is true, the action falls back
to the legacy **gated mode**: it consults the persisted review verdict
(``portrait`` + ``decision``) via ``evaluate_gate_pass`` and only
blacklists when the same gate that triggers auto-group-invite passes,
so the two actions stay aligned.
"""

from __future__ import annotations

import logging

from wecom_automation.services.media_actions.interfaces import (
    ActionResult,
    ActionStatus,
    IMediaAction,
    MediaEvent,
)
from wecom_automation.services.media_actions.media_review_decision import (
    evaluate_gate_pass,
)

logger = logging.getLogger(__name__)


class AutoBlacklistAction(IMediaAction):
    """
    Adds a customer to the blacklist when they send media.

    Requires a BlacklistWriter instance (from blacklist_service) for
    database operations. Optionally checks existing blacklist status
    to avoid duplicate entries.

    Review-pipeline coupling is governed by the
    ``auto_blacklist.require_review_pass`` setting (default ``False``).
    When ``True`` and ``db_path`` is provided, the action defers to
    ``evaluate_gate_pass`` so it stays aligned with auto-group-invite.
    When ``False`` (the default), the action ignores the review pipeline
    entirely — the moment a media MediaEvent reaches it and idempotency
    checks pass, the customer is blacklisted.
    """

    def __init__(self, blacklist_writer, db_path: str | None = None) -> None:
        self._writer = blacklist_writer
        self._db_path = db_path

    @property
    def action_name(self) -> str:
        return "auto_blacklist"

    async def should_execute(self, event: MediaEvent, settings: dict) -> bool:
        if not settings.get("enabled", False):
            return False

        bl_settings = settings.get("auto_blacklist", {})
        if not bl_settings.get("enabled", False):
            return False

        if not event.is_media:
            return False

        if bl_settings.get("skip_if_already_blacklisted", True):
            try:
                already = self._writer.is_blacklisted_by_name(
                    device_serial=event.device_serial,
                    customer_name=event.customer_name,
                )
                if already:
                    logger.debug(
                        "Skipping auto-blacklist for %s: already blacklisted",
                        event.customer_name,
                    )
                    return False
            except Exception as exc:
                logger.warning("Failed to check blacklist status: %s", exc)

        # Review-pipeline coupling is OFF by default. Customers who send
        # media are blacklisted immediately — no dependency on
        # image-rating-server. Only flip ``require_review_pass=True``
        # when the deployment runs the rating pipeline AND wants
        # blacklist to mirror auto-group-invite's portrait/decision gate.
        require_review = bool(bl_settings.get("require_review_pass", False))
        if require_review and self._db_path is not None:
            gate_enabled = bool(settings.get("review_gate", {}).get("enabled", False))
            decision = evaluate_gate_pass(
                message_id=event.message_id,
                message_type=event.message_type,
                db_path=self._db_path,
                gate_enabled=gate_enabled,
            )
            if not decision.has_data:
                logger.warning(
                    "Skipping auto-blacklist: review data missing "
                    "(device=%s, customer=%s, message_type=%s, message_id=%s, "
                    "gate_enabled=%s, reason=%s, details=%s)",
                    event.device_serial,
                    event.customer_name,
                    event.message_type,
                    event.message_id,
                    gate_enabled,
                    decision.reason,
                    decision.details,
                )
                return False
            if not decision.gate_pass:
                logger.debug(
                    "Skipping auto-blacklist: portrait/decision gate rejected "
                    "(device=%s, customer=%s, message_type=%s, message_id=%s, "
                    "gate_enabled=%s, reason=%s, details=%s)",
                    event.device_serial,
                    event.customer_name,
                    event.message_type,
                    event.message_id,
                    gate_enabled,
                    decision.reason,
                    decision.details,
                )
                return False
            logger.info(
                "Auto-blacklist gate passed "
                "(device=%s, customer=%s, message_type=%s, message_id=%s, "
                "gate_enabled=%s, details=%s)",
                event.device_serial,
                event.customer_name,
                event.message_type,
                event.message_id,
                gate_enabled,
                decision.details,
            )

        return True

    async def execute(self, event: MediaEvent, settings: dict) -> ActionResult:
        bl_settings = settings.get("auto_blacklist", {})
        reason = bl_settings.get("reason", "Customer sent media (auto)")

        try:
            success = self._writer.add_to_blacklist(
                device_serial=event.device_serial,
                customer_name=event.customer_name,
                customer_channel=event.channel,
                reason=reason,
                customer_db_id=event.customer_id,
            )

            if success:
                logger.info(
                    "Auto-blacklisted customer %s (device=%s, reason=%s)",
                    event.customer_name,
                    event.device_serial,
                    reason,
                )
                return ActionResult(
                    action_name=self.action_name,
                    status=ActionStatus.SUCCESS,
                    message=f"Blacklisted {event.customer_name}",
                    details={
                        "customer_name": event.customer_name,
                        "device_serial": event.device_serial,
                        "reason": reason,
                    },
                )
            else:
                return ActionResult(
                    action_name=self.action_name,
                    status=ActionStatus.ERROR,
                    message=f"Failed to blacklist {event.customer_name}",
                )

        except Exception as exc:
            logger.error("Auto-blacklist failed for %s: %s", event.customer_name, exc)
            return ActionResult(
                action_name=self.action_name,
                status=ActionStatus.ERROR,
                message=str(exc),
            )
