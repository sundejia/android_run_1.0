"""
Integration tests for media auto-actions in the Follow-up (realtime reply) path.

TDD red phase: verifies that ResponseDetector properly wires media_event_bus
into MessageProcessor so customer image/video triggers auto-blacklist and
auto-group-invite during red-dot scanning.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wecom_automation.core.interfaces import MessageContext, MessageProcessResult
from wecom_automation.services.media_actions.event_bus import MediaEventBus
from wecom_automation.services.media_actions.interfaces import (
    ActionResult,
    ActionStatus,
    MediaEvent,
)
from wecom_automation.services.message.processor import MessageProcessor


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
    msg.content = "[Video 00:15]"
    msg.message_type = "video"
    msg.is_self = False
    msg.is_from_kefu = False
    msg.video_bounds = "[100,200][300,400]"
    msg.video_duration = "00:15"
    msg.timestamp = "10:30"
    return msg


def _make_text_message():
    msg = MagicMock()
    msg.content = "Hello"
    msg.message_type = "text"
    msg.is_self = False
    msg.is_from_kefu = False
    msg.timestamp = "10:30"
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


def _make_context() -> MessageContext:
    return MessageContext(
        customer_id=1,
        customer_name="TestCustomer",
        channel="@WeChat",
        kefu_name="",
        device_serial="device001",
    )


class TestFollowupMediaBusWiring:
    """Verify that MessageProcessor in the follow-up path receives media_event_bus."""

    @pytest.mark.asyncio
    async def test_processor_with_bus_emits_on_customer_image(self):
        """Core test: MessageProcessor constructed with bus emits for customer image."""
        repo = MagicMock()
        repo.add_message_if_not_exists = MagicMock(return_value=(True, MagicMock(id=200)))

        spy_action = AsyncMock()
        spy_action.action_name = "spy"
        spy_action.should_execute = AsyncMock(return_value=True)
        spy_action.execute = AsyncMock(
            return_value=ActionResult(action_name="spy", status=ActionStatus.SUCCESS, message="ok")
        )

        bus = MediaEventBus()
        bus.register(spy_action)

        handler = AsyncMock()
        handler.can_handle = AsyncMock(return_value=True)
        handler.process = AsyncMock(
            return_value=MessageProcessResult(added=True, message_type="image", message_id=200)
        )

        processor = MessageProcessor(
            repository=repo,
            handlers=[handler],
            media_event_bus=bus,
        )
        processor.set_media_action_settings({"enabled": True, "auto_blacklist": {"enabled": True}})

        await processor.process(_make_image_message(), _make_context())

        spy_action.should_execute.assert_awaited_once()
        event = spy_action.should_execute.call_args[0][0]
        assert isinstance(event, MediaEvent)
        assert event.message_type == "image"
        assert event.customer_name == "TestCustomer"

    @pytest.mark.asyncio
    async def test_processor_with_bus_emits_on_customer_video(self):
        repo = MagicMock()
        repo.add_message_if_not_exists = MagicMock(return_value=(True, MagicMock(id=201)))

        spy_action = AsyncMock()
        spy_action.action_name = "spy"
        spy_action.should_execute = AsyncMock(return_value=True)
        spy_action.execute = AsyncMock(
            return_value=ActionResult(action_name="spy", status=ActionStatus.SUCCESS, message="ok")
        )

        bus = MediaEventBus()
        bus.register(spy_action)

        handler = AsyncMock()
        handler.can_handle = AsyncMock(return_value=True)
        handler.process = AsyncMock(
            return_value=MessageProcessResult(added=True, message_type="video", message_id=201)
        )

        processor = MessageProcessor(repository=repo, handlers=[handler], media_event_bus=bus)
        processor.set_media_action_settings({"enabled": True})

        await processor.process(_make_video_message(), _make_context())

        spy_action.should_execute.assert_awaited_once()
        event = spy_action.should_execute.call_args[0][0]
        assert event.message_type == "video"

    @pytest.mark.asyncio
    async def test_text_message_does_not_trigger_media_event(self):
        repo = MagicMock()
        repo.add_message_if_not_exists = MagicMock(return_value=(True, MagicMock(id=202)))

        spy_action = AsyncMock()
        spy_action.action_name = "spy"
        spy_action.should_execute = AsyncMock(return_value=True)

        bus = MediaEventBus()
        bus.register(spy_action)

        handler = AsyncMock()
        handler.can_handle = AsyncMock(return_value=True)
        handler.process = AsyncMock(
            return_value=MessageProcessResult(added=True, message_type="text", message_id=202)
        )

        processor = MessageProcessor(repository=repo, handlers=[handler], media_event_bus=bus)
        processor.set_media_action_settings({"enabled": True})

        await processor.process(_make_text_message(), _make_context())

        spy_action.should_execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_kefu_image_does_not_trigger_media_event(self):
        repo = MagicMock()
        repo.add_message_if_not_exists = MagicMock(return_value=(True, MagicMock(id=203)))

        spy_action = AsyncMock()
        spy_action.action_name = "spy"
        spy_action.should_execute = AsyncMock(return_value=True)

        bus = MediaEventBus()
        bus.register(spy_action)

        handler = AsyncMock()
        handler.can_handle = AsyncMock(return_value=True)
        handler.process = AsyncMock(
            return_value=MessageProcessResult(added=True, message_type="image", message_id=203)
        )

        processor = MessageProcessor(repository=repo, handlers=[handler], media_event_bus=bus)
        processor.set_media_action_settings({"enabled": True})

        await processor.process(_make_kefu_image_message(), _make_context())

        spy_action.should_execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_media_bus_failure_does_not_break_message_storage(self):
        """Even if the bus raises, the message should still be stored."""
        repo = MagicMock()
        repo.add_message_if_not_exists = MagicMock(return_value=(True, MagicMock(id=204)))

        broken_action = AsyncMock()
        broken_action.action_name = "broken"
        broken_action.should_execute = AsyncMock(return_value=True)
        broken_action.execute = AsyncMock(side_effect=RuntimeError("boom"))

        bus = MediaEventBus()
        bus.register(broken_action)

        handler = AsyncMock()
        handler.can_handle = AsyncMock(return_value=True)
        handler.process = AsyncMock(
            return_value=MessageProcessResult(added=True, message_type="image", message_id=204)
        )

        processor = MessageProcessor(repository=repo, handlers=[handler], media_event_bus=bus)
        processor.set_media_action_settings({"enabled": True})

        result = await processor.process(_make_image_message(), _make_context())

        assert result.added is True
        assert result.message_type == "image"


class TestFollowupWebSocketBroadcast:
    """Verify that the on_action_results callback triggers WebSocket broadcast."""

    @pytest.mark.asyncio
    async def test_ws_broadcast_on_successful_action(self):
        callback = AsyncMock()
        bus = MediaEventBus(on_action_results=callback)

        spy_action = AsyncMock()
        spy_action.action_name = "auto_blacklist"
        spy_action.should_execute = AsyncMock(return_value=True)
        spy_action.execute = AsyncMock(
            return_value=ActionResult(
                action_name="auto_blacklist", status=ActionStatus.SUCCESS, message="ok"
            )
        )
        bus.register(spy_action)

        event = MediaEvent(
            event_type="customer_media_detected",
            message_type="image",
            customer_id=1,
            customer_name="TestCustomer",
            channel="@WeChat",
            device_serial="device001",
            kefu_name="",
            message_id=200,
            timestamp=datetime.now(),
        )

        await bus.emit(event, {"enabled": True})

        callback.assert_awaited_once()
        cb_event, cb_results = callback.call_args[0]
        assert cb_event.customer_name == "TestCustomer"
        assert cb_results[0].status == ActionStatus.SUCCESS


class TestBuildMediaBusGraceful:
    """Verify that _build_media_event_bus failure doesn't break the scan."""

    @pytest.mark.asyncio
    async def test_build_media_bus_error_leaves_bus_none(self):
        """If build_media_event_bus raises, the detector should gracefully continue."""
        with patch(
            "wecom_automation.services.media_actions.factory.load_media_auto_action_settings",
            side_effect=RuntimeError("DB corrupted"),
        ):
            from wecom_automation.services.media_actions.factory import build_media_event_bus

            bus, settings = build_media_event_bus("/nonexistent/path.db")

            assert bus is None
