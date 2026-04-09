"""
Reusable workflow service for Android WeCom group invites.
"""

from __future__ import annotations

import logging
from typing import Protocol

from wecom_automation.services.group_invite.models import GroupInviteRequest, GroupInviteResult

logger = logging.getLogger(__name__)


class GroupInviteNavigator(Protocol):
    """Minimal UI capabilities required by the workflow."""

    async def navigate_to_chat(self, device_serial: str, customer_name: str) -> bool: ...

    async def open_chat_info(self, device_serial: str) -> bool: ...

    async def tap_add_member_button(self, device_serial: str) -> bool: ...

    async def search_and_select_member(
        self,
        device_serial: str,
        member_name: str,
        duplicate_name_policy: str = "first",
    ) -> bool: ...

    async def confirm_group_creation(
        self,
        device_serial: str,
        post_confirm_wait_seconds: float = 1.0,
    ) -> bool: ...

    async def set_group_name(self, device_serial: str, group_name: str) -> bool: ...

    async def send_message(self, text: str) -> tuple[bool, str]: ...


class GroupInviteWorkflowService:
    """High-level orchestration for customer-to-group invite flows."""

    def __init__(
        self,
        navigator: GroupInviteNavigator,
        logger_: logging.Logger | None = None,
    ) -> None:
        self._navigator = navigator
        self._logger = logger_ or logger

    async def create_group_chat(self, request: GroupInviteRequest) -> GroupInviteResult:
        members = request.normalized_members()
        result = GroupInviteResult(
            success=False,
            customer_name=request.customer_name,
            group_name=request.group_name,
            requested_members=members,
        )

        if not members:
            result.error_message = "No group members configured"
            return result

        if not await self._navigator.navigate_to_chat(request.device_serial, request.customer_name):
            result.error_message = f"Could not open chat for '{request.customer_name}'"
            return result

        if not await self._navigator.open_chat_info(request.device_serial):
            result.error_message = "Could not open chat information"
            return result

        if not await self._navigator.tap_add_member_button(request.device_serial):
            result.error_message = "Could not enter add-member flow"
            return result

        for member in members:
            selected = await self._navigator.search_and_select_member(
                request.device_serial,
                member,
                duplicate_name_policy=request.duplicate_name_policy.value,
            )
            if not selected:
                result.error_message = f"Could not select member '{member}'"
                return result
            result.selected_members.append(member)

        confirmed = await self._navigator.confirm_group_creation(
            request.device_serial,
            post_confirm_wait_seconds=request.post_confirm_wait_seconds,
        )
        if not confirmed:
            result.error_message = "Could not confirm group creation"
            return result

        if request.group_name:
            renamed = await self._navigator.set_group_name(request.device_serial, request.group_name)
            if not renamed:
                result.warnings.append("Requested group name was not applied")

        if request.send_test_message and request.test_message_text:
            sent, _ = await self._navigator.send_message(request.test_message_text)
            if not sent:
                result.error_message = "Group was created but the test message was not sent"
                return result

        result.success = True
        return result
