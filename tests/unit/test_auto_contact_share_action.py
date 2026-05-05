"""
Tests for AutoContactShareAction.

Covers should_execute gating (enabled/disabled, media/non-media, contact name,
idempotency, per-kefu overrides), execute success/failure/exception paths,
and navigation recovery via finally block.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from wecom_automation.services.media_actions.actions.auto_contact_share import (
    AutoContactShareAction,
)
from wecom_automation.services.media_actions.interfaces import (
    ActionStatus,
    MediaEvent,
)


def _make_event(**overrides) -> MediaEvent:
    defaults = {
        "event_type": "customer_media_detected",
        "message_type": "image",
        "customer_id": 1,
        "customer_name": "张三",
        "channel": "@WeChat",
        "device_serial": "device001",
        "kefu_name": "客服A",
        "message_id": 100,
        "timestamp": datetime(2026, 4, 30, 12, 0, 0),
    }
    defaults.update(overrides)
    return MediaEvent(**defaults)


def _default_settings(enabled: bool = True, **overrides) -> dict:
    base = {
        "enabled": True,
        "auto_contact_share": {
            "enabled": enabled,
            "contact_name": "主管王",
            "skip_if_already_shared": True,
            "cooldown_seconds": 0,
            "kefu_overrides": {},
        },
    }
    base["auto_contact_share"].update(overrides)
    return base


class TestAutoContactShareActionName:
    def test_action_name(self):
        service = AsyncMock()
        action = AutoContactShareAction(contact_share_service=service)
        assert action.action_name == "auto_contact_share"


class TestAutoContactShareShouldExecute:
    @pytest.mark.asyncio
    async def test_should_execute_when_enabled_and_image(self):
        service = AsyncMock()
        service.contact_already_shared = AsyncMock(return_value=False)
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event(message_type="image")
        settings = _default_settings(enabled=True)

        assert await action.should_execute(event, settings) is True

    @pytest.mark.asyncio
    async def test_should_execute_when_enabled_and_video(self):
        service = AsyncMock()
        service.contact_already_shared = AsyncMock(return_value=False)
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event(message_type="video")
        settings = _default_settings(enabled=True)

        assert await action.should_execute(event, settings) is True

    @pytest.mark.asyncio
    async def test_should_not_execute_when_action_disabled(self):
        service = AsyncMock()
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event(message_type="image")
        settings = _default_settings(enabled=False)

        assert await action.should_execute(event, settings) is False

    @pytest.mark.asyncio
    async def test_should_not_execute_when_global_disabled(self):
        service = AsyncMock()
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event(message_type="image")
        settings = {"enabled": False, "auto_contact_share": {"enabled": True}}

        assert await action.should_execute(event, settings) is False

    @pytest.mark.asyncio
    async def test_should_not_execute_for_text_message(self):
        service = AsyncMock()
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event(message_type="text")
        settings = _default_settings(enabled=True)

        assert await action.should_execute(event, settings) is False

    @pytest.mark.asyncio
    async def test_should_not_execute_when_no_contact_name(self):
        service = AsyncMock()
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event(message_type="image")
        settings = _default_settings(enabled=True, contact_name="")

        assert await action.should_execute(event, settings) is False

    @pytest.mark.asyncio
    async def test_should_not_execute_when_already_shared(self):
        service = AsyncMock()
        service.contact_already_shared = AsyncMock(return_value=True)
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event(message_type="image")
        settings = _default_settings(enabled=True, skip_if_already_shared=True)

        assert await action.should_execute(event, settings) is False

    @pytest.mark.asyncio
    async def test_should_execute_when_already_shared_but_skip_disabled(self):
        service = AsyncMock()
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event(message_type="image")
        settings = _default_settings(enabled=True, skip_if_already_shared=False)

        assert await action.should_execute(event, settings) is True

    @pytest.mark.asyncio
    async def test_should_execute_when_idempotency_check_fails(self):
        """If the DB check raises, should_execute still proceeds (fail-open)."""
        service = AsyncMock()
        service.contact_already_shared = AsyncMock(side_effect=RuntimeError("DB locked"))
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event(message_type="image")
        settings = _default_settings(enabled=True, skip_if_already_shared=True)

        assert await action.should_execute(event, settings) is True


class TestAutoContactShareResolveContactName:
    """Test per-kefu override and global fallback logic."""

    def test_kefu_override_takes_priority(self):
        event = _make_event(kefu_name="客服A")
        cs = {
            "contact_name": "全局主管",
            "kefu_overrides": {"客服A": "主管X", "客服B": "主管Y"},
        }
        assert AutoContactShareAction._resolve_contact_name(event, cs) == "主管X"

    def test_global_fallback_when_no_override(self):
        event = _make_event(kefu_name="客服C")
        cs = {
            "contact_name": "全局主管",
            "kefu_overrides": {"客服A": "主管X"},
        }
        assert AutoContactShareAction._resolve_contact_name(event, cs) == "全局主管"

    def test_empty_string_when_no_config(self):
        event = _make_event(kefu_name="客服A")
        cs = {"contact_name": "", "kefu_overrides": {}}
        assert AutoContactShareAction._resolve_contact_name(event, cs) == ""

    def test_override_with_whitespace_stripped(self):
        event = _make_event(kefu_name="客服A")
        cs = {
            "contact_name": "全局主管",
            "kefu_overrides": {"客服A": "  主管X  "},
        }
        assert AutoContactShareAction._resolve_contact_name(event, cs) == "主管X"

    def test_kefu_overrides_not_dict_falls_back(self):
        event = _make_event(kefu_name="客服A")
        cs = {
            "contact_name": "全局主管",
            "kefu_overrides": "invalid",
        }
        assert AutoContactShareAction._resolve_contact_name(event, cs) == "全局主管"


class TestAutoContactShareExecute:
    @pytest.mark.asyncio
    async def test_execute_shares_contact(self):
        service = AsyncMock()
        service.share_contact_card = AsyncMock(return_value=True)
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event(customer_name="张三", kefu_name="客服A")
        settings = _default_settings(contact_name="主管王")

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.SUCCESS
        assert "主管王" in result.message
        assert result.details["contact_name"] == "主管王"
        assert result.details["customer_name"] == "张三"
        assert result.details["kefu_name"] == "客服A"
        service.share_contact_card.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_uses_kefu_override(self):
        service = AsyncMock()
        service.share_contact_card = AsyncMock(return_value=True)
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event(customer_name="张三", kefu_name="客服A")
        settings = _default_settings(
            contact_name="全局主管",
            kefu_overrides={"客服A": "专属主管"},
        )

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.SUCCESS
        assert result.details["contact_name"] == "专属主管"

    @pytest.mark.asyncio
    async def test_execute_failure_returns_error(self):
        service = AsyncMock()
        service.share_contact_card = AsyncMock(return_value=False)
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event()
        settings = _default_settings()

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.ERROR
        assert "failed" in result.message.lower()

    @pytest.mark.asyncio
    async def test_execute_exception_returns_error(self):
        service = AsyncMock()
        service.share_contact_card = AsyncMock(side_effect=RuntimeError("UI timeout"))
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event()
        settings = _default_settings()

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.ERROR
        assert "UI timeout" in result.message


class TestAutoContactShareNavigationRecovery:
    """Verify restore_navigation is always called, even on failure."""

    @pytest.mark.asyncio
    async def test_restore_navigation_called_on_success(self):
        service = AsyncMock()
        service.share_contact_card = AsyncMock(return_value=True)
        service.restore_navigation = AsyncMock(return_value=True)
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event()
        settings = _default_settings()

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.SUCCESS
        service.restore_navigation.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_restore_navigation_called_on_failure(self):
        service = AsyncMock()
        service.share_contact_card = AsyncMock(return_value=False)
        service.restore_navigation = AsyncMock(return_value=True)
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event()
        settings = _default_settings()

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.ERROR
        service.restore_navigation.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_restore_navigation_called_on_exception(self):
        service = AsyncMock()
        service.share_contact_card = AsyncMock(side_effect=RuntimeError("ADB error"))
        service.restore_navigation = AsyncMock(return_value=True)
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event()
        settings = _default_settings()

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.ERROR
        service.restore_navigation.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_restore_navigation_failure_does_not_mask_result(self):
        service = AsyncMock()
        service.share_contact_card = AsyncMock(return_value=True)
        service.restore_navigation = AsyncMock(side_effect=RuntimeError("nav failed"))
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event()
        settings = _default_settings()

        result = await action.execute(event, settings)

        # Success result should not be masked by navigation failure
        assert result.status == ActionStatus.SUCCESS
        service.restore_navigation.assert_awaited_once()


class TestAutoContactSharePreShareMessage:
    """Tests for send_message_before_share feature."""

    @pytest.mark.asyncio
    async def test_execute_sends_message_before_card_when_enabled(self):
        """When send_message_before_share is enabled with text, share_contact_card
        should receive a request with pre_share_message_text populated."""
        service = AsyncMock()
        service.share_contact_card = AsyncMock(return_value=True)
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event(customer_name="张三")
        settings = _default_settings(
            contact_name="主管王",
            send_message_before_share=True,
            pre_share_message_text="你好{customer_name}，这是我主管的名片",
        )

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.SUCCESS
        call_args = service.share_contact_card.call_args[0][0]
        assert call_args.send_message_before_share is True
        assert "张三" in call_args.pre_share_message_text

    @pytest.mark.asyncio
    async def test_execute_skips_message_when_disabled(self):
        """When send_message_before_share is False, request should have empty pre_share fields."""
        service = AsyncMock()
        service.share_contact_card = AsyncMock(return_value=True)
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event()
        settings = _default_settings(
            contact_name="主管王",
            send_message_before_share=False,
            pre_share_message_text="你好",
        )

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.SUCCESS
        call_args = service.share_contact_card.call_args[0][0]
        assert call_args.send_message_before_share is False

    @pytest.mark.asyncio
    async def test_execute_skips_message_when_text_empty(self):
        """When enabled but text is empty/whitespace, send_message_before_share should be False."""
        service = AsyncMock()
        service.share_contact_card = AsyncMock(return_value=True)
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event()
        settings = _default_settings(
            contact_name="主管王",
            send_message_before_share=True,
            pre_share_message_text="   ",
        )

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.SUCCESS
        call_args = service.share_contact_card.call_args[0][0]
        assert call_args.send_message_before_share is False
        assert call_args.pre_share_message_text == ""

    @pytest.mark.asyncio
    async def test_execute_message_uses_template(self):
        """Template placeholders like {customer_name} should be resolved."""
        service = AsyncMock()
        service.share_contact_card = AsyncMock(return_value=True)
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event(customer_name="李四", kefu_name="客服B")
        settings = _default_settings(
            contact_name="主管王",
            send_message_before_share=True,
            pre_share_message_text="{customer_name}您好，{kefu_name}为您推荐主管",
        )

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.SUCCESS
        call_args = service.share_contact_card.call_args[0][0]
        assert call_args.pre_share_message_text == "李四您好，客服B为您推荐主管"

    @pytest.mark.asyncio
    async def test_execute_card_still_sent_if_message_fails(self):
        """Card sharing should proceed even if the pre-share message sending fails.
        The failure is handled inside ContactShareService, so at the action level
        we just verify the request is properly constructed."""
        service = AsyncMock()
        service.share_contact_card = AsyncMock(return_value=True)
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event()
        settings = _default_settings(
            contact_name="主管王",
            send_message_before_share=True,
            pre_share_message_text="你好",
        )

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.SUCCESS
        service.share_contact_card.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_without_pre_share_settings_uses_defaults(self):
        """When settings don't include pre_share fields, defaults should apply (no message)."""
        service = AsyncMock()
        service.share_contact_card = AsyncMock(return_value=True)
        action = AutoContactShareAction(contact_share_service=service)

        event = _make_event()
        settings = _default_settings(contact_name="主管王")

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.SUCCESS
        call_args = service.share_contact_card.call_args[0][0]
        assert call_args.send_message_before_share is False
        assert call_args.pre_share_message_text == ""
