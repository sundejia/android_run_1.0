"""
AutoContactShareAction - automatically share a supervisor's contact card on media detection.

When a customer sends an image or video, this action shares a configured
contact card (名片) with the customer. The contact can be configured per-kefu
via ``kefu_overrides`` or globally via ``contact_name``.
"""

from __future__ import annotations

import logging

from wecom_automation.services.contact_share.models import ContactShareRequest
from wecom_automation.services.contact_share.service import IContactShareService
from wecom_automation.services.media_actions.interfaces import (
    ActionResult,
    ActionStatus,
    IMediaAction,
    MediaEvent,
)
from wecom_automation.services.media_actions.template_resolver import render_media_template

logger = logging.getLogger(__name__)


class AutoContactShareAction(IMediaAction):
    """
    Shares a supervisor's contact card when a customer sends media.

    Requires an IContactShareService instance for the actual UI automation
    and idempotency tracking.
    """

    def __init__(self, contact_share_service: IContactShareService) -> None:
        self._service = contact_share_service

    @property
    def action_name(self) -> str:
        return "auto_contact_share"

    async def should_execute(self, event: MediaEvent, settings: dict) -> bool:
        if not settings.get("enabled", False):
            logger.debug(
                "Skipping auto-contact-share: media actions disabled "
                "(device=%s, customer=%s, message_type=%s, message_id=%s)",
                event.device_serial,
                event.customer_name,
                event.message_type,
                event.message_id,
            )
            return False

        cs = settings.get("auto_contact_share", {})
        if not cs.get("enabled", False):
            logger.debug(
                "Skipping auto-contact-share: action disabled "
                "(device=%s, customer=%s, message_type=%s, message_id=%s)",
                event.device_serial,
                event.customer_name,
                event.message_type,
                event.message_id,
            )
            return False

        if not self._service or not getattr(self._service, "_wecom", None):
            logger.debug(
                "Skipping auto-contact-share: ContactShareService has no WeComService "
                "(device=%s, customer=%s, message_type=%s, message_id=%s)",
                event.device_serial,
                event.customer_name,
                event.message_type,
                event.message_id,
            )
            return False

        if not event.is_media:
            logger.debug(
                "Skipping auto-contact-share: message is not media "
                "(device=%s, customer=%s, message_type=%s, message_id=%s)",
                event.device_serial,
                event.customer_name,
                event.message_type,
                event.message_id,
            )
            return False

        contact_name = self._resolve_contact_name(event, cs)
        if not contact_name:
            logger.debug(
                "Skipping auto-contact-share: no contact name configured "
                "(device=%s, customer=%s, kefu=%s, message_type=%s, message_id=%s)",
                event.device_serial,
                event.customer_name,
                event.kefu_name,
                event.message_type,
                event.message_id,
            )
            return False

        if cs.get("skip_if_already_shared", True):
            try:
                logger.debug(
                    "Checking contact share history before auto-contact-share "
                    "(device=%s, customer=%s, contact=%s)",
                    event.device_serial,
                    event.customer_name,
                    contact_name,
                )
                already = await self._service.contact_already_shared(
                    device_serial=event.device_serial,
                    customer_name=event.customer_name,
                    contact_name=contact_name,
                )
                if already:
                    logger.debug(
                        "Contact card already shared to %s; skipping",
                        event.customer_name,
                    )
                    return False
            except Exception as exc:
                logger.warning(
                    "Failed to check contact share history; continuing with auto-contact-share "
                    "(device=%s, customer=%s, contact=%s): %s",
                    event.device_serial,
                    event.customer_name,
                    contact_name,
                    exc,
                    exc_info=True,
                )

        logger.debug(
            "Auto-contact-share eligible "
            "(device=%s, customer=%s, kefu=%s, contact=%s, message_type=%s, message_id=%s)",
            event.device_serial,
            event.customer_name,
            event.kefu_name,
            contact_name,
            event.message_type,
            event.message_id,
        )
        return True

    async def execute(self, event: MediaEvent, settings: dict) -> ActionResult:
        cs = settings.get("auto_contact_share", {})
        contact_name = self._resolve_contact_name(event, cs)

        pre_share_text = ""
        if cs.get("send_message_before_share", False):
            template = cs.get("pre_share_message_text", "")
            if template.strip():
                pre_share_text = render_media_template(template, event, preserve_on_error=True)

        try:
            logger.info(
                "Starting auto-contact-share "
                "(device=%s, customer=%s, kefu=%s, contact=%s, message_type=%s, message_id=%s, "
                "send_pre_message=%s, pre_message_length=%d)",
                event.device_serial,
                event.customer_name,
                event.kefu_name,
                contact_name,
                event.message_type,
                event.message_id,
                bool(pre_share_text),
                len(pre_share_text),
            )
            request = ContactShareRequest(
                device_serial=event.device_serial,
                customer_name=event.customer_name,
                contact_name=contact_name,
                kefu_name=event.kefu_name,
                send_message_before_share=bool(pre_share_text),
                pre_share_message_text=pre_share_text,
            )
            success = await self._service.share_contact_card(request)

            if success:
                logger.info(
                    "Shared contact card '%s' to customer %s",
                    contact_name,
                    event.customer_name,
                )
                return ActionResult(
                    action_name=self.action_name,
                    status=ActionStatus.SUCCESS,
                    message=f"Shared contact '{contact_name}' to {event.customer_name}",
                    details={
                        "contact_name": contact_name,
                        "customer_name": event.customer_name,
                        "kefu_name": event.kefu_name,
                    },
                )
            else:
                logger.error(
                    "Auto-contact-share service returned failure "
                    "(device=%s, customer=%s, contact=%s, message_id=%s)",
                    event.device_serial,
                    event.customer_name,
                    contact_name,
                    event.message_id,
                )
                return ActionResult(
                    action_name=self.action_name,
                    status=ActionStatus.ERROR,
                    message=f"Failed to share contact card to {event.customer_name}",
                )

        except Exception as exc:
            logger.exception(
                "Auto-contact-share failed "
                "(device=%s, customer=%s, contact=%s, message_id=%s)",
                event.device_serial,
                event.customer_name,
                contact_name,
                event.message_id,
            )
            return ActionResult(
                action_name=self.action_name,
                status=ActionStatus.ERROR,
                message=str(exc),
            )
        finally:
            try:
                restored = await self._service.restore_navigation()
                if restored:
                    logger.info("Navigation restored after auto-contact-share")
                else:
                    logger.warning("Could not restore navigation after auto-contact-share")
            except Exception as nav_exc:
                logger.warning("Error restoring navigation after auto-contact-share: %s", nav_exc)

    @staticmethod
    def _resolve_contact_name(event: MediaEvent, cs: dict) -> str:
        """Resolve the contact name: per-kefu override first, then global default."""
        overrides = cs.get("kefu_overrides", {})
        if isinstance(overrides, dict):
            name = overrides.get(event.kefu_name, "").strip()
            if name:
                return name
        return cs.get("contact_name", "").strip()
