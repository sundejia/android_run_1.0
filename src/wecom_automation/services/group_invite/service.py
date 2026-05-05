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
        self._logger.info(
            "Group invite workflow started "
            "(device=%s, customer=%s, group_name=%s, requested_members=%s, normalized_members=%s, "
            "send_test_message=%s, duplicate_policy=%s, post_confirm_wait=%.2f)",
            request.device_serial,
            request.customer_name,
            request.group_name,
            request.members,
            members,
            request.send_test_message,
            request.duplicate_name_policy.value,
            request.post_confirm_wait_seconds,
        )
        result = GroupInviteResult(
            success=False,
            customer_name=request.customer_name,
            group_name=request.group_name,
            requested_members=members,
        )

        if not members:
            result.error_message = "No group members configured"
            self._logger.warning(
                "Group invite workflow stopped: no normalized members "
                "(device=%s, customer=%s, raw_members=%s)",
                request.device_serial,
                request.customer_name,
                request.members,
            )
            return result

        self._logger.debug(
            "Group invite step: navigate to customer chat (device=%s, customer=%s)",
            request.device_serial,
            request.customer_name,
        )
        if not await self._navigator.navigate_to_chat(request.device_serial, request.customer_name):
            result.error_message = f"Could not open chat for '{request.customer_name}'"
            self._logger.error(
                "Group invite step failed: navigate to customer chat "
                "(device=%s, customer=%s)",
                request.device_serial,
                request.customer_name,
            )
            return result

        self._logger.debug(
            "Group invite step: open chat info (device=%s, customer=%s)",
            request.device_serial,
            request.customer_name,
        )
        if not await self._navigator.open_chat_info(request.device_serial):
            result.error_message = "Could not open chat information"
            self._logger.error(
                "Group invite step failed: open chat info (device=%s, customer=%s)",
                request.device_serial,
                request.customer_name,
            )
            return result

        self._logger.debug(
            "Group invite step: tap add-member button (device=%s, customer=%s)",
            request.device_serial,
            request.customer_name,
        )
        if not await self._navigator.tap_add_member_button(request.device_serial):
            result.error_message = "Could not enter add-member flow"
            self._logger.error(
                "Group invite step failed: tap add-member button (device=%s, customer=%s)",
                request.device_serial,
                request.customer_name,
            )
            return result

        for member in members:
            self._logger.debug(
                "Group invite step: search and select member "
                "(device=%s, customer=%s, member=%s, duplicate_policy=%s)",
                request.device_serial,
                request.customer_name,
                member,
                request.duplicate_name_policy.value,
            )
            selected = await self._navigator.search_and_select_member(
                request.device_serial,
                member,
                duplicate_name_policy=request.duplicate_name_policy.value,
            )
            if not selected:
                result.error_message = f"Could not select member '{member}'"
                self._logger.error(
                    "Group invite step failed: member not selected "
                    "(device=%s, customer=%s, member=%s, selected_members=%s)",
                    request.device_serial,
                    request.customer_name,
                    member,
                    result.selected_members,
                )
                return result
            result.selected_members.append(member)
            self._logger.info(
                "Group invite member selected "
                "(device=%s, customer=%s, member=%s, selected_count=%d/%d)",
                request.device_serial,
                request.customer_name,
                member,
                len(result.selected_members),
                len(members),
            )

        self._logger.debug(
            "Group invite step: confirm group creation "
            "(device=%s, customer=%s, selected_members=%s)",
            request.device_serial,
            request.customer_name,
            result.selected_members,
        )
        confirmed = await self._navigator.confirm_group_creation(
            request.device_serial,
            post_confirm_wait_seconds=request.post_confirm_wait_seconds,
        )
        if not confirmed:
            result.error_message = "Could not confirm group creation"
            self._logger.error(
                "Group invite step failed: confirm group creation "
                "(device=%s, customer=%s, selected_members=%s)",
                request.device_serial,
                request.customer_name,
                result.selected_members,
            )
            return result

        if request.group_name:
            self._logger.debug(
                "Group invite step: set group name "
                "(device=%s, customer=%s, group_name=%s)",
                request.device_serial,
                request.customer_name,
                request.group_name,
            )
            renamed = await self._navigator.set_group_name(request.device_serial, request.group_name)
            if not renamed:
                result.warnings.append("Requested group name was not applied")
                self._logger.warning(
                    "Group invite warning: requested group name was not applied "
                    "(device=%s, customer=%s, group_name=%s)",
                    request.device_serial,
                    request.customer_name,
                    request.group_name,
                )

        if request.send_test_message and request.test_message_text:
            self._logger.debug(
                "Group invite step: send test message "
                "(device=%s, customer=%s, text_length=%d)",
                request.device_serial,
                request.customer_name,
                len(request.test_message_text),
            )
            sent, _ = await self._navigator.send_message(request.test_message_text)
            if not sent:
                result.error_message = "Group was created but the test message was not sent"
                self._logger.error(
                    "Group invite step failed: test message was not sent "
                    "(device=%s, customer=%s, group_name=%s)",
                    request.device_serial,
                    request.customer_name,
                    request.group_name,
                )
                return result

        result.success = True
        self._logger.info(
            "Group invite workflow completed "
            "(device=%s, customer=%s, group_name=%s, selected_members=%s, warnings=%s)",
            request.device_serial,
            request.customer_name,
            request.group_name,
            result.selected_members,
            result.warnings,
        )
        return result
