from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wecom_automation.services.media_actions.group_chat_service import GroupChatService


@pytest.mark.asyncio
async def test_group_chat_service_delegates_to_workflow_and_records_success(tmp_path):
    workflow = AsyncMock()
    workflow.create_group_chat.return_value = MagicMock(success=True, warnings=[])

    service = GroupChatService(
        wecom_service=MagicMock(),
        db_path=str(tmp_path / "group_chat.db"),
        workflow_service=workflow,
    )

    success = await service.create_group_chat(
        device_serial="device001",
        customer_name="张三",
        group_members=["经理A"],
        group_name="张三-服务群",
        send_test_message=False,
        test_message_text="联调消息",
        duplicate_name_policy="first",
        post_confirm_wait_seconds=2.0,
    )

    assert success is True
    workflow.create_group_chat.assert_awaited_once()
    assert await service.group_exists("device001", "张三", "张三-服务群") is True


@pytest.mark.asyncio
async def test_group_chat_service_returns_false_on_workflow_failure(tmp_path):
    workflow = AsyncMock()
    workflow.create_group_chat.return_value = MagicMock(
        success=False,
        error_message="member selection failed",
        warnings=[],
    )

    service = GroupChatService(
        wecom_service=MagicMock(),
        db_path=str(tmp_path / "group_chat.db"),
        workflow_service=workflow,
    )

    success = await service.create_group_chat(
        device_serial="device001",
        customer_name="张三",
        group_members=["经理A"],
        group_name="张三-服务群",
    )

    assert success is False
    assert await service.group_exists("device001", "张三", "张三-服务群") is False


@pytest.mark.asyncio
async def test_restore_navigation_delegates_to_wecom_service(tmp_path):
    wecom = AsyncMock()
    wecom.ensure_on_private_chats = AsyncMock(return_value=True)

    service = GroupChatService(
        wecom_service=wecom,
        db_path=str(tmp_path / "group_chat.db"),
    )

    result = await service.restore_navigation()

    assert result is True
    wecom.ensure_on_private_chats.assert_awaited_once()


@pytest.mark.asyncio
async def test_restore_navigation_returns_false_when_no_wecom_service(tmp_path):
    service = GroupChatService(
        wecom_service=None,
        db_path=str(tmp_path / "group_chat.db"),
    )

    result = await service.restore_navigation()

    assert result is False


@pytest.mark.asyncio
async def test_restore_navigation_handles_exception_gracefully(tmp_path):
    wecom = AsyncMock()
    wecom.ensure_on_private_chats = AsyncMock(side_effect=RuntimeError("ADB error"))

    service = GroupChatService(
        wecom_service=wecom,
        db_path=str(tmp_path / "group_chat.db"),
    )

    result = await service.restore_navigation()

    assert result is False
