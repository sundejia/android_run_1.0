from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from wecom_automation.services.group_invite.models import (
    DuplicateNamePolicy,
    GroupInviteRequest,
)
from wecom_automation.services.group_invite.service import GroupInviteWorkflowService


def _make_request(**overrides) -> GroupInviteRequest:
    base = {
        "device_serial": "device001",
        "customer_name": "张三",
        "members": ["经理A", "经理A", "主管B"],
        "group_name": "张三-服务群",
        "duplicate_name_policy": DuplicateNamePolicy.FIRST,
        "post_confirm_wait_seconds": 1.0,
        "send_test_message": True,
        "test_message_text": "测试",
    }
    base.update(overrides)
    return GroupInviteRequest(**base)


class TestGroupInviteRequest:
    def test_normalized_members_deduplicates_and_trims(self):
        request = _make_request(members=[" 经理A ", "", "经理A", "主管B"])

        assert request.normalized_members() == ["经理A", "主管B"]


class TestGroupInviteWorkflowService:
    @pytest.mark.asyncio
    async def test_runs_happy_path(self):
        navigator = AsyncMock()
        navigator.navigate_to_chat.return_value = True
        navigator.open_chat_info.return_value = True
        navigator.tap_add_member_button.return_value = True
        navigator.search_and_select_member.return_value = True
        navigator.confirm_group_creation.return_value = True
        navigator.set_group_name.return_value = True
        navigator.send_message.return_value = (True, "测试")

        service = GroupInviteWorkflowService(navigator)
        result = await service.create_group_chat(_make_request())

        assert result.success is True
        assert result.selected_members == ["经理A", "主管B"]
        navigator.search_and_select_member.assert_any_await("device001", "经理A", duplicate_name_policy="first")
        navigator.search_and_select_member.assert_any_await("device001", "主管B", duplicate_name_policy="first")
        navigator.send_message.assert_awaited_once_with("测试")

    @pytest.mark.asyncio
    async def test_sends_rendered_message_text_without_reparsing_template(self):
        navigator = AsyncMock()
        navigator.navigate_to_chat.return_value = True
        navigator.open_chat_info.return_value = True
        navigator.tap_add_member_button.return_value = True
        navigator.search_and_select_member.return_value = True
        navigator.confirm_group_creation.return_value = True
        navigator.set_group_name.return_value = True
        navigator.send_message.return_value = (True, "您好 张三")

        service = GroupInviteWorkflowService(navigator)
        result = await service.create_group_chat(
            _make_request(
                members=["经理A"],
                test_message_text="您好 张三",
            )
        )

        assert result.success is True
        navigator.send_message.assert_awaited_once_with("您好 张三")

    @pytest.mark.asyncio
    async def test_returns_error_when_member_selection_fails(self):
        navigator = AsyncMock()
        navigator.navigate_to_chat.return_value = True
        navigator.open_chat_info.return_value = True
        navigator.tap_add_member_button.return_value = True
        navigator.search_and_select_member.side_effect = [True, False]

        service = GroupInviteWorkflowService(navigator)
        result = await service.create_group_chat(_make_request(members=["经理A", "主管B"]))

        assert result.success is False
        assert result.selected_members == ["经理A"]
        assert result.error_message == "Could not select member '主管B'"

    @pytest.mark.asyncio
    async def test_returns_error_when_test_message_fails(self):
        navigator = AsyncMock()
        navigator.navigate_to_chat.return_value = True
        navigator.open_chat_info.return_value = True
        navigator.tap_add_member_button.return_value = True
        navigator.search_and_select_member.return_value = True
        navigator.confirm_group_creation.return_value = True
        navigator.set_group_name.return_value = True
        navigator.send_message.return_value = (False, "测试")

        service = GroupInviteWorkflowService(navigator)
        result = await service.create_group_chat(_make_request(members=["经理A"]))

        assert result.success is False
        assert result.error_message == "Group was created but the test message was not sent"

    @pytest.mark.asyncio
    async def test_returns_error_when_group_creation_cannot_be_confirmed(self):
        navigator = AsyncMock()
        navigator.navigate_to_chat.return_value = True
        navigator.open_chat_info.return_value = True
        navigator.tap_add_member_button.return_value = True
        navigator.search_and_select_member.return_value = True
        navigator.confirm_group_creation.return_value = False

        service = GroupInviteWorkflowService(navigator)
        result = await service.create_group_chat(_make_request(members=["经理A"]))

        assert result.success is False
        assert result.error_message == "Could not confirm group creation"
        navigator.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rename_failure_becomes_warning(self):
        navigator = AsyncMock()
        navigator.navigate_to_chat.return_value = True
        navigator.open_chat_info.return_value = True
        navigator.tap_add_member_button.return_value = True
        navigator.search_and_select_member.return_value = True
        navigator.confirm_group_creation.return_value = True
        navigator.set_group_name.return_value = False
        navigator.send_message.return_value = (True, "测试")

        service = GroupInviteWorkflowService(navigator)
        result = await service.create_group_chat(_make_request(members=["经理A"]))

        assert result.success is True
        assert result.warnings == ["Requested group name was not applied"]
