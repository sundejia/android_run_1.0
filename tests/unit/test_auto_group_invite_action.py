"""
Tests for AutoGroupInviteAction.

TDD red phase: defines expected behavior for auto-creating a group chat
with configured members when a customer sends an image or video.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from wecom_automation.services.media_actions.actions.auto_group_invite import (
    AutoGroupInviteAction,
)
from wecom_automation.services.media_actions.interfaces import (
    ActionStatus,
    MediaEvent,
)
from wecom_automation.services.media_actions.media_review_decision import (
    MediaReviewDecision,
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
        "timestamp": datetime(2026, 4, 4, 12, 0, 0),
    }
    defaults.update(overrides)
    return MediaEvent(**defaults)


def _default_settings(enabled: bool = True, **overrides) -> dict:
    base = {
        "enabled": True,
        "auto_group_invite": {
            "enabled": enabled,
            "group_members": ["经理A", "主管B"],
            "group_name_template": "{customer_name}-服务群",
            "skip_if_group_exists": True,
            "send_test_message_after_create": True,
            "test_message_text": "测试",
            "post_confirm_wait_seconds": 1.0,
            "duplicate_name_policy": "first",
        },
    }
    base["auto_group_invite"].update(overrides)
    return base


class TestAutoGroupInviteActionName:
    def test_action_name(self):
        service = AsyncMock()
        action = AutoGroupInviteAction(group_chat_service=service)
        assert action.action_name == "auto_group_invite"


class TestAutoGroupInviteShouldExecute:
    @pytest.mark.asyncio
    async def test_should_execute_when_enabled_and_image(self):
        service = AsyncMock()
        service.group_exists = AsyncMock(return_value=False)
        action = AutoGroupInviteAction(group_chat_service=service)

        event = _make_event(message_type="image")
        settings = _default_settings(enabled=True)

        assert await action.should_execute(event, settings) is True

    @pytest.mark.asyncio
    async def test_should_execute_when_enabled_and_video(self):
        service = AsyncMock()
        service.group_exists = AsyncMock(return_value=False)
        action = AutoGroupInviteAction(group_chat_service=service)

        event = _make_event(message_type="video")
        settings = _default_settings(enabled=True)

        assert await action.should_execute(event, settings) is True

    @pytest.mark.asyncio
    async def test_should_not_execute_when_disabled(self):
        service = AsyncMock()
        action = AutoGroupInviteAction(group_chat_service=service)

        event = _make_event(message_type="image")
        settings = _default_settings(enabled=False)

        assert await action.should_execute(event, settings) is False

    @pytest.mark.asyncio
    async def test_should_not_execute_when_global_disabled(self):
        service = AsyncMock()
        action = AutoGroupInviteAction(group_chat_service=service)

        event = _make_event(message_type="image")
        settings = {"enabled": False, "auto_group_invite": {"enabled": True}}

        assert await action.should_execute(event, settings) is False

    @pytest.mark.asyncio
    async def test_should_not_execute_when_no_members_configured(self):
        service = AsyncMock()
        action = AutoGroupInviteAction(group_chat_service=service)

        event = _make_event(message_type="image")
        settings = _default_settings(enabled=True, group_members=[])

        assert await action.should_execute(event, settings) is False

    @pytest.mark.asyncio
    async def test_should_not_execute_when_group_exists_and_skip_enabled(self):
        service = AsyncMock()
        service.group_exists = AsyncMock(return_value=True)
        action = AutoGroupInviteAction(group_chat_service=service)

        event = _make_event(message_type="image")
        settings = _default_settings(enabled=True, skip_if_group_exists=True)

        assert await action.should_execute(event, settings) is False

    @pytest.mark.asyncio
    async def test_should_execute_when_group_exists_but_skip_disabled(self):
        service = AsyncMock()
        service.group_exists = AsyncMock(return_value=True)
        action = AutoGroupInviteAction(group_chat_service=service)

        event = _make_event(message_type="image")
        settings = _default_settings(enabled=True, skip_if_group_exists=False)

        assert await action.should_execute(event, settings) is True

    @pytest.mark.asyncio
    async def test_should_not_execute_for_text_message(self):
        service = AsyncMock()
        action = AutoGroupInviteAction(group_chat_service=service)

        event = _make_event(message_type="text")
        settings = _default_settings(enabled=True)

        assert await action.should_execute(event, settings) is False


class TestAutoGroupInviteExecute:
    @pytest.mark.asyncio
    async def test_execute_creates_group(self):
        service = AsyncMock()
        service.create_group_chat = AsyncMock(return_value=True)
        action = AutoGroupInviteAction(group_chat_service=service)

        event = _make_event(customer_name="张三")
        settings = _default_settings(
            group_members=["经理A", "主管B"],
            group_name_template="{customer_name}-服务群",
        )

        result = await action.execute(event, settings)

        service.create_group_chat.assert_awaited_once_with(
            device_serial="device001",
            customer_name="张三",
            group_members=["经理A", "主管B"],
            group_name="张三-服务群",
            send_test_message=True,
            test_message_text="测试",
            duplicate_name_policy="first",
            post_confirm_wait_seconds=1.0,
            send_message_before_create=False,
            pre_create_message_text="",
        )
        assert result.status == ActionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_execute_uses_template_for_group_name(self):
        service = AsyncMock()
        service.create_group_chat = AsyncMock(return_value=True)
        action = AutoGroupInviteAction(group_chat_service=service)

        event = _make_event(customer_name="李四", kefu_name="客服B")
        settings = _default_settings(
            group_name_template="{customer_name}-{kefu_name}-VIP群",
        )

        exec_result = await action.execute(event, settings)

        call_kwargs = service.create_group_chat.call_args[1]
        assert call_kwargs["group_name"] == "李四-客服B-VIP群"
        assert call_kwargs["send_test_message"] is True
        assert exec_result.status == ActionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_execute_renders_template_for_test_message(self):
        service = AsyncMock()
        service.create_group_chat = AsyncMock(return_value=True)
        action = AutoGroupInviteAction(group_chat_service=service)

        event = _make_event(customer_name="李四", kefu_name="客服B", device_serial="android-01")
        settings = _default_settings(
            test_message_text="您好 {customer_name}，我是 {kefu_name}，当前设备 {device_serial}",
        )

        exec_result = await action.execute(event, settings)

        call_kwargs = service.create_group_chat.call_args[1]
        assert call_kwargs["test_message_text"] == "您好 李四，我是 客服B，当前设备 android-01"
        assert exec_result.status == ActionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_execute_preserves_unknown_placeholders_in_test_message(self):
        service = AsyncMock()
        service.create_group_chat = AsyncMock(return_value=True)
        action = AutoGroupInviteAction(group_chat_service=service)

        event = _make_event(customer_name="李四", kefu_name="客服B")
        settings = _default_settings(
            test_message_text="欢迎 {customer_name}，请联系 {missing_key}",
        )

        await action.execute(event, settings)

        call_kwargs = service.create_group_chat.call_args[1]
        assert call_kwargs["test_message_text"] == "欢迎 李四，请联系 {missing_key}"

    @pytest.mark.asyncio
    async def test_execute_failure_returns_error(self):
        service = AsyncMock()
        service.create_group_chat = AsyncMock(return_value=False)
        action = AutoGroupInviteAction(group_chat_service=service)

        event = _make_event()
        settings = _default_settings()

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.ERROR
        assert "failed" in result.message.lower()

    @pytest.mark.asyncio
    async def test_execute_exception_returns_error(self):
        service = AsyncMock()
        service.create_group_chat = AsyncMock(side_effect=RuntimeError("ADB timeout"))
        action = AutoGroupInviteAction(group_chat_service=service)

        event = _make_event()
        settings = _default_settings()

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.ERROR
        assert "ADB timeout" in result.message

    @pytest.mark.asyncio
    async def test_execute_with_default_template_when_missing(self):
        service = AsyncMock()
        service.create_group_chat = AsyncMock(return_value=True)
        action = AutoGroupInviteAction(group_chat_service=service)

        event = _make_event(customer_name="王五")
        settings = {
            "enabled": True,
            "auto_group_invite": {
                "enabled": True,
                "group_members": ["经理A"],
            },
        }

        result = await action.execute(event, settings)

        call_kwargs = service.create_group_chat.call_args[1]
        assert "王五" in call_kwargs["group_name"]
        assert result.status == ActionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_execute_passes_extended_group_invite_options(self):
        service = AsyncMock()
        service.create_group_chat = AsyncMock(return_value=True)
        action = AutoGroupInviteAction(group_chat_service=service)

        event = _make_event()
        settings = _default_settings(
            send_test_message_after_create=False,
            test_message_text="联调消息",
            post_confirm_wait_seconds=2.5,
            duplicate_name_policy="first",
        )

        await action.execute(event, settings)

        call_kwargs = service.create_group_chat.call_args.kwargs
        assert call_kwargs["send_test_message"] is False
        assert call_kwargs["test_message_text"] == "联调消息"
        assert call_kwargs["post_confirm_wait_seconds"] == 2.5
        assert call_kwargs["duplicate_name_policy"] == "first"


class TestAutoGroupInviteNavigationRecovery:
    """Verify restore_navigation is always called after group creation."""

    @pytest.mark.asyncio
    async def test_restore_navigation_called_on_success(self):
        service = AsyncMock()
        service.create_group_chat = AsyncMock(return_value=True)
        service.restore_navigation = AsyncMock(return_value=True)
        action = AutoGroupInviteAction(group_chat_service=service)

        event = _make_event()
        settings = _default_settings()

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.SUCCESS
        service.restore_navigation.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_restore_navigation_called_on_failure(self):
        service = AsyncMock()
        service.create_group_chat = AsyncMock(return_value=False)
        service.restore_navigation = AsyncMock(return_value=True)
        action = AutoGroupInviteAction(group_chat_service=service)

        event = _make_event()
        settings = _default_settings()

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.ERROR
        service.restore_navigation.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_restore_navigation_called_on_exception(self):
        service = AsyncMock()
        service.create_group_chat = AsyncMock(side_effect=RuntimeError("ADB error"))
        service.restore_navigation = AsyncMock(return_value=True)
        action = AutoGroupInviteAction(group_chat_service=service)

        event = _make_event()
        settings = _default_settings()

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.ERROR
        service.restore_navigation.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_restore_navigation_failure_does_not_mask_result(self):
        service = AsyncMock()
        service.create_group_chat = AsyncMock(return_value=True)
        service.restore_navigation = AsyncMock(side_effect=RuntimeError("nav failed"))
        action = AutoGroupInviteAction(group_chat_service=service)

        event = _make_event()
        settings = _default_settings()

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.SUCCESS
        service.restore_navigation.assert_awaited_once()


class TestAutoGroupInviteReviewGate:
    """Verify the portrait/decision review gate when ``db_path`` is wired in."""

    def _settings(self, *, gate_enabled: bool) -> dict:
        return {
            "enabled": True,
            "auto_group_invite": {
                "enabled": True,
                "group_members": ["经理A"],
                "skip_if_group_exists": False,
            },
            "review_gate": {"enabled": gate_enabled},
        }

    @pytest.mark.asyncio
    async def test_gate_off_portrait_true_executes(self):
        service = AsyncMock()
        service.group_exists = AsyncMock(return_value=False)
        action = AutoGroupInviteAction(group_chat_service=service, db_path="/db.sqlite")

        decision = MediaReviewDecision(
            gate_pass=True,
            has_data=True,
            reason="ok",
            details={"is_portrait": True},
        )

        with patch(
            "wecom_automation.services.media_actions.actions.auto_group_invite.evaluate_gate_pass",
            return_value=decision,
        ) as mock_eval:
            assert await action.should_execute(_make_event(), self._settings(gate_enabled=False)) is True
            mock_eval.assert_called_once()
            assert mock_eval.call_args.kwargs["gate_enabled"] is False

    @pytest.mark.asyncio
    async def test_gate_off_portrait_false_skips(self):
        service = AsyncMock()
        service.group_exists = AsyncMock(return_value=False)
        action = AutoGroupInviteAction(group_chat_service=service, db_path="/db.sqlite")

        decision = MediaReviewDecision(
            gate_pass=False,
            has_data=True,
            reason="portrait_false",
            details={"is_portrait": False},
        )

        with patch(
            "wecom_automation.services.media_actions.actions.auto_group_invite.evaluate_gate_pass",
            return_value=decision,
        ):
            assert await action.should_execute(_make_event(), self._settings(gate_enabled=False)) is False

    @pytest.mark.asyncio
    async def test_gate_on_portrait_and_qualified_executes(self):
        service = AsyncMock()
        service.group_exists = AsyncMock(return_value=False)
        action = AutoGroupInviteAction(group_chat_service=service, db_path="/db.sqlite")

        decision = MediaReviewDecision(
            gate_pass=True,
            has_data=True,
            reason="ok",
            details={"is_portrait": True, "decision": "合格"},
        )

        with patch(
            "wecom_automation.services.media_actions.actions.auto_group_invite.evaluate_gate_pass",
            return_value=decision,
        ) as mock_eval:
            assert await action.should_execute(_make_event(), self._settings(gate_enabled=True)) is True
            assert mock_eval.call_args.kwargs["gate_enabled"] is True

    @pytest.mark.asyncio
    async def test_gate_on_portrait_true_but_unqualified_skips(self):
        service = AsyncMock()
        service.group_exists = AsyncMock(return_value=False)
        action = AutoGroupInviteAction(group_chat_service=service, db_path="/db.sqlite")

        decision = MediaReviewDecision(
            gate_pass=False,
            has_data=True,
            reason="decision_not_qualified",
            details={"is_portrait": True, "decision": "不合格"},
        )

        with patch(
            "wecom_automation.services.media_actions.actions.auto_group_invite.evaluate_gate_pass",
            return_value=decision,
        ):
            assert await action.should_execute(_make_event(), self._settings(gate_enabled=True)) is False

    @pytest.mark.asyncio
    async def test_missing_review_data_skips_with_warning(self, caplog):
        service = AsyncMock()
        service.group_exists = AsyncMock(return_value=False)
        action = AutoGroupInviteAction(group_chat_service=service, db_path="/db.sqlite")

        decision = MediaReviewDecision(
            gate_pass=False,
            has_data=False,
            reason="ai_review_status='pending'",
            details={"message_id": 100},
        )

        with patch(
            "wecom_automation.services.media_actions.actions.auto_group_invite.evaluate_gate_pass",
            return_value=decision,
        ):
            import logging

            with caplog.at_level(
                logging.WARNING,
                logger="wecom_automation.services.media_actions.actions.auto_group_invite",
            ):
                assert await action.should_execute(_make_event(), self._settings(gate_enabled=True)) is False

        assert any("review data missing" in rec.message for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_legacy_no_db_path_keeps_behaviour(self):
        """When db_path is omitted (legacy mode), gate is skipped entirely."""
        service = AsyncMock()
        service.group_exists = AsyncMock(return_value=False)
        action = AutoGroupInviteAction(group_chat_service=service)

        with patch(
            "wecom_automation.services.media_actions.actions.auto_group_invite.evaluate_gate_pass",
        ) as mock_eval:
            assert await action.should_execute(_make_event(), self._settings(gate_enabled=False)) is True
            mock_eval.assert_not_called()
