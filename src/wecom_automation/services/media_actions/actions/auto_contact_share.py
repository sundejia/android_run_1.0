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
            return False

        cs = settings.get("auto_contact_share", {})
        if not cs.get("enabled", False):
            return False

        if not self._service or not getattr(self._service, "_wecom", None):
            logger.debug("ContactShareService has no WeComService; skipping auto-contact-share")
            return False

        if not event.is_media:
            return False

        contact_name = self._resolve_contact_name(event, cs)
        if not contact_name:
            logger.debug("No contact name configured; skipping auto-contact-share")
            return False

        if cs.get("skip_if_already_shared", True):
            try:
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
            except Exception:
                pass

        return True

    async def execute(self, event: MediaEvent, settings: dict) -> ActionResult:
        cs = settings.get("auto_contact_share", {})
        contact_name = self._resolve_contact_name(event, cs)

        try:
            request = ContactShareRequest(
                device_serial=event.device_serial,
                customer_name=event.customer_name,
                contact_name=contact_name,
                kefu_name=event.kefu_name,
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
                return ActionResult(
                    action_name=self.action_name,
                    status=ActionStatus.ERROR,
                    message=f"Failed to share contact card to {event.customer_name}",
                )

        except Exception as exc:
            logger.error("Auto-contact-share failed for %s: %s", event.customer_name, exc)
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
