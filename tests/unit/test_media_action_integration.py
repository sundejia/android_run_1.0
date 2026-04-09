"""
Integration tests for the full media action flow:
MessageProcessor -> MediaEventBus -> Actions

TDD red phase: verifies end-to-end behavior.
"""

from __future__ import annotations

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from wecom_automation.core.interfaces import MessageContext, MessageProcessResult
from wecom_automation.services.media_actions.interfaces import (
    ActionResult,
    ActionStatus,
    MediaEvent,
)
from wecom_automation.services.media_actions.event_bus import MediaEventBus
from wecom_automation.services.media_actions.actions.auto_blacklist import AutoBlacklistAction
from wecom_automation.services.media_actions.actions.auto_group_invite import AutoGroupInviteAction
from wecom_automation.services.message.processor import MessageProcessor


def _make_context() -> MessageContext:
    return MessageContext(
        customer_id=1,
        customer_name="张三",
        channel="@WeChat",
        kefu_name="客服A",
        device_serial="device001",
    )


def _make_image_message():
    msg = MagicMock()
    msg.content = "[图片]"
    msg.message_type = "image"
    msg.is_self = False
    msg.is_from_kefu = False
    msg.image = MagicMock()
    msg.image.bounds = "[100,200][300,400]"
    msg.timestamp = "10:30"
    return msg


def _make_video_message():
    msg = MagicMock()
    msg.content = "[Video 00:30]"
    msg.message_type = "video"
    msg.is_self = False
    msg.is_from_kefu = False
    msg.video_bounds = "[100,200][300,400]"
    msg.video_duration = "00:30"
    msg.timestamp = "10:30"
    return msg


def _make_text_message():
    msg = MagicMock()
    msg.content = "Hello"
    msg.message_type = "text"
    msg.is_self = False
    msg.is_from_kefu = False
    msg.timestamp = "10:30"
    # Ensure no media attributes
    msg.image = None
    msg.video_bounds = None
    msg.video_duration = None
    msg.voice_duration = None
    return msg


def _make_kefu_image_message():
    msg = _make_image_message()
    msg.is_self = True
    msg.is_from_kefu = True
    return msg


class TestMessageProcessorMediaEventIntegration:
    """Test that MessageProcessor emits events to MediaEventBus on customer media."""

    @pytest.mark.asyncio
    async def test_processor_emits_event_on_customer_image(self):
        repo = MagicMock()
        repo.add_message_if_not_exists = MagicMock(return_value=(True, MagicMock(id=100)))

        bus = MediaEventBus()
        spy_action = AsyncMock()
        spy_action.action_name = "spy"
        spy_action.should_execute = AsyncMock(return_value=True)
        spy_action.execute = AsyncMock(
            return_value=ActionResult(action_name="spy", status=ActionStatus.SUCCESS, message="ok")
        )
        bus.register(spy_action)

        handler = AsyncMock()
        handler.can_handle = AsyncMock(return_value=True)
        handler.process = AsyncMock(
            return_value=MessageProcessResult(added=True, message_type="image", message_id=100)
        )

        processor = MessageProcessor(repository=repo, handlers=[handler], media_event_bus=bus)

        msg = _make_image_message()
        context = _make_context()
        settings = {"enabled": True, "auto_blacklist": {"enabled": True}}
        processor.set_media_action_settings(settings)

        await processor.process(msg, context)

        spy_action.should_execute.assert_awaited_once()
        call_event = spy_action.should_execute.call_args[0][0]
        assert isinstance(call_event, MediaEvent)
        assert call_event.message_type == "image"
        assert call_event.customer_name == "张三"

    @pytest.mark.asyncio
    async def test_processor_does_not_emit_for_kefu_image(self):
        repo = MagicMock()
        repo.add_message_if_not_exists = MagicMock(return_value=(True, MagicMock(id=100)))

        bus = MediaEventBus()
        spy_action = AsyncMock()
        spy_action.action_name = "spy"
        spy_action.should_execute = AsyncMock(return_value=True)
        spy_action.execute = AsyncMock(
            return_value=ActionResult(action_name="spy", status=ActionStatus.SUCCESS, message="ok")
        )
        bus.register(spy_action)

        handler = AsyncMock()
        handler.can_handle = AsyncMock(return_value=True)
        handler.process = AsyncMock(
            return_value=MessageProcessResult(added=True, message_type="image", message_id=100)
        )

        processor = MessageProcessor(repository=repo, handlers=[handler], media_event_bus=bus)

        msg = _make_kefu_image_message()
        context = _make_context()
        settings = {"enabled": True}
        processor.set_media_action_settings(settings)

        await processor.process(msg, context)

        spy_action.should_execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_processor_does_not_emit_for_text(self):
        repo = MagicMock()
        repo.add_message_if_not_exists = MagicMock(return_value=(True, MagicMock(id=100)))

        bus = MediaEventBus()
        spy_action = AsyncMock()
        spy_action.action_name = "spy"
        spy_action.should_execute = AsyncMock(return_value=True)
        bus.register(spy_action)

        handler = AsyncMock()
        handler.can_handle = AsyncMock(return_value=True)
        handler.process = AsyncMock(
            return_value=MessageProcessResult(added=True, message_type="text", message_id=100)
        )

        processor = MessageProcessor(repository=repo, handlers=[handler], media_event_bus=bus)

        msg = _make_text_message()
        context = _make_context()
        settings = {"enabled": True}
        processor.set_media_action_settings(settings)

        await processor.process(msg, context)

        spy_action.should_execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_processor_emits_event_on_customer_video(self):
        repo = MagicMock()
        repo.add_message_if_not_exists = MagicMock(return_value=(True, MagicMock(id=101)))

        bus = MediaEventBus()
        spy_action = AsyncMock()
        spy_action.action_name = "spy"
        spy_action.should_execute = AsyncMock(return_value=True)
        spy_action.execute = AsyncMock(
            return_value=ActionResult(action_name="spy", status=ActionStatus.SUCCESS, message="ok")
        )
        bus.register(spy_action)

        handler = AsyncMock()
        handler.can_handle = AsyncMock(return_value=True)
        handler.process = AsyncMock(
            return_value=MessageProcessResult(added=True, message_type="video", message_id=101)
        )

        processor = MessageProcessor(repository=repo, handlers=[handler], media_event_bus=bus)

        msg = _make_video_message()
        context = _make_context()
        settings = {"enabled": True}
        processor.set_media_action_settings(settings)

        await processor.process(msg, context)

        spy_action.should_execute.assert_awaited_once()
        call_event = spy_action.should_execute.call_args[0][0]
        assert call_event.message_type == "video"

    @pytest.mark.asyncio
    async def test_bus_error_does_not_break_processor(self):
        """Even if the event bus raises, the processor should still return normally."""
        repo = MagicMock()
        repo.add_message_if_not_exists = MagicMock(return_value=(True, MagicMock(id=100)))

        bus = MediaEventBus()
        broken_action = AsyncMock()
        broken_action.action_name = "broken"
        broken_action.should_execute = AsyncMock(return_value=True)
        broken_action.execute = AsyncMock(side_effect=RuntimeError("catastrophic"))
        bus.register(broken_action)

        handler = AsyncMock()
        handler.can_handle = AsyncMock(return_value=True)
        handler.process = AsyncMock(
            return_value=MessageProcessResult(added=True, message_type="image", message_id=100)
        )

        processor = MessageProcessor(repository=repo, handlers=[handler], media_event_bus=bus)
        processor.set_media_action_settings({"enabled": True})

        msg = _make_image_message()
        context = _make_context()

        result = await processor.process(msg, context)

        assert result.added is True
        assert result.message_type == "image"


class TestFullPipelineWithRealActions:
    """Test with real action classes (mocked dependencies)."""

    @pytest.mark.asyncio
    async def test_image_triggers_blacklist_and_group(self):
        writer = MagicMock()
        writer.add_to_blacklist = MagicMock(return_value=True)
        writer.is_blacklisted_by_name = MagicMock(return_value=False)

        group_service = AsyncMock()
        group_service.group_exists = AsyncMock(return_value=False)
        group_service.create_group_chat = AsyncMock(return_value=True)

        bus = MediaEventBus()
        bus.register(AutoBlacklistAction(blacklist_writer=writer))
        bus.register(AutoGroupInviteAction(group_chat_service=group_service))

        event = MediaEvent(
            event_type="customer_media_detected",
            message_type="image",
            customer_id=1,
            customer_name="张三",
            channel="@WeChat",
            device_serial="device001",
            kefu_name="客服A",
            message_id=100,
            timestamp=datetime.now(),
        )

        settings = {
            "enabled": True,
            "auto_blacklist": {
                "enabled": True,
                "reason": "Auto: sent media",
                "skip_if_already_blacklisted": True,
            },
            "auto_group_invite": {
                "enabled": True,
                "group_members": ["经理A"],
                "group_name_template": "{customer_name}-服务群",
                "skip_if_group_exists": True,
            },
        }

        results = await bus.emit(event, settings)

        assert len(results) == 2
        assert results[0].status == ActionStatus.SUCCESS
        assert results[0].action_name == "auto_blacklist"
        assert results[1].status == ActionStatus.SUCCESS
        assert results[1].action_name == "auto_group_invite"

        writer.add_to_blacklist.assert_called_once()
        group_service.create_group_chat.assert_awaited_once()
