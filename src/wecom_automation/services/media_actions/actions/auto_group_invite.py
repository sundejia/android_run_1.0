"""
AutoGroupInviteAction - automatically create a group chat on media detection.

When a customer sends an image or video, this action creates a group chat
with the customer and a configurable list of members (e.g., managers).
"""

from __future__ import annotations

import logging

from wecom_automation.services.media_actions.interfaces import (
    ActionResult,
    ActionStatus,
    IMediaAction,
    MediaEvent,
)
from wecom_automation.services.media_actions.template_resolver import render_media_template

logger = logging.getLogger(__name__)

DEFAULT_GROUP_NAME_TEMPLATE = "{customer_name}-服务群"


class AutoGroupInviteAction(IMediaAction):
    """
    Creates a group chat with configured members when a customer sends media.

    Requires a GroupChatService (or IGroupChatService) instance for the
    actual group creation logic.
    """

    def __init__(self, group_chat_service) -> None:
        self._service = group_chat_service

    @property
    def action_name(self) -> str:
        return "auto_group_invite"

    async def should_execute(self, event: MediaEvent, settings: dict) -> bool:
        if not settings.get("enabled", False):
            return False

        gi_settings = settings.get("auto_group_invite", {})
        if not gi_settings.get("enabled", False):
            return False

        if not event.is_media:
            return False

        members = gi_settings.get("group_members", [])
        if not members:
            logger.debug("No group members configured; skipping auto-group-invite")
            return False

        if gi_settings.get("skip_if_group_exists", True):
            group_name = self._resolve_group_name(event, gi_settings)
            try:
                exists = await self._service.group_exists(
                    device_serial=event.device_serial,
                    customer_name=event.customer_name,
                    group_name=group_name,
                )
                if exists:
                    logger.debug(
                        "Group '%s' already exists for %s; skipping",
                        group_name,
                        event.customer_name,
                    )
                    return False
            except Exception as exc:
                logger.warning("Failed to check group existence: %s", exc)

        return True

    async def execute(self, event: MediaEvent, settings: dict) -> ActionResult:
        gi_settings = settings.get("auto_group_invite", {})
        members = gi_settings.get("group_members", [])
        group_name = self._resolve_group_name(event, gi_settings)
        test_message_text = self._resolve_test_message(event, gi_settings)

        try:
            success = await self._service.create_group_chat(
                device_serial=event.device_serial,
                customer_name=event.customer_name,
                group_members=members,
                group_name=group_name,
                send_test_message=gi_settings.get("send_test_message_after_create", True),
                test_message_text=test_message_text,
                duplicate_name_policy=gi_settings.get("duplicate_name_policy", "first"),
                post_confirm_wait_seconds=float(gi_settings.get("post_confirm_wait_seconds", 1.0)),
            )

            if success:
                logger.info(
                    "Auto-created group '%s' for customer %s with members %s",
                    group_name,
                    event.customer_name,
                    members,
                )
                return ActionResult(
                    action_name=self.action_name,
                    status=ActionStatus.SUCCESS,
                    message=f"Created group '{group_name}'",
                    details={
                        "group_name": group_name,
                        "customer_name": event.customer_name,
                        "members": members,
                    },
                )
            else:
                return ActionResult(
                    action_name=self.action_name,
                    status=ActionStatus.ERROR,
                    message=f"Failed to create group '{group_name}'",
                )

        except Exception as exc:
            logger.error("Auto-group-invite failed for %s: %s", event.customer_name, exc)
            return ActionResult(
                action_name=self.action_name,
                status=ActionStatus.ERROR,
                message=str(exc),
            )
        finally:
            try:
                restored = await self._service.restore_navigation()
                if restored:
                    logger.info("Navigation restored to private chats after auto-group-invite")
                else:
                    logger.warning("Could not restore navigation to private chats after auto-group-invite")
            except Exception as nav_exc:
                logger.warning("Error restoring navigation after auto-group-invite: %s", nav_exc)

    @staticmethod
    def _resolve_group_name(event: MediaEvent, gi_settings: dict) -> str:
        template = gi_settings.get("group_name_template", DEFAULT_GROUP_NAME_TEMPLATE)
        return render_media_template(
            template,
            event,
            fallback=f"{event.customer_name}-服务群",
        )

    @staticmethod
    def _resolve_test_message(event: MediaEvent, gi_settings: dict) -> str:
        template = gi_settings.get("test_message_text", "测试")
        return render_media_template(
            template,
            event,
            preserve_on_error=True,
        )
