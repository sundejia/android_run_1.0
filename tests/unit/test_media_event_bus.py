"""
Tests for MediaEventBus - event registration, emission, and error isolation.

TDD red phase: these tests define the expected behavior of MediaEventBus.
"""

from __future__ import annotations

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from wecom_automation.services.media_actions.interfaces import (
    ActionResult,
    ActionStatus,
    IMediaAction,
    MediaEvent,
)
from wecom_automation.services.media_actions.event_bus import MediaEventBus


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


def _make_action(
    name: str = "test_action",
    should_execute: bool = True,
    result: ActionResult | None = None,
) -> IMediaAction:
    action = AsyncMock(spec=IMediaAction)
    action.action_name = name
    action.should_execute = AsyncMock(return_value=should_execute)
    if result is None:
        result = ActionResult(
            action_name=name,
            status=ActionStatus.SUCCESS,
            message="ok",
        )
    action.execute = AsyncMock(return_value=result)
    return action


class TestMediaEventBusRegistration:
    def test_register_single_action(self):
        bus = MediaEventBus()
        action = _make_action("action1")
        bus.register(action)
        assert len(bus._actions) == 1

    def test_register_multiple_actions(self):
        bus = MediaEventBus()
        bus.register(_make_action("a1"))
        bus.register(_make_action("a2"))
        bus.register(_make_action("a3"))
        assert len(bus._actions) == 3

    def test_unregister_action(self):
        bus = MediaEventBus()
        action = _make_action("removable")
        bus.register(action)
        bus.unregister("removable")
        assert len(bus._actions) == 0

    def test_unregister_nonexistent_is_noop(self):
        bus = MediaEventBus()
        bus.register(_make_action("keeper"))
        bus.unregister("nonexistent")
        assert len(bus._actions) == 1

    def test_clear_all_actions(self):
        bus = MediaEventBus()
        bus.register(_make_action("a1"))
        bus.register(_make_action("a2"))
        bus.clear()
        assert len(bus._actions) == 0


class TestMediaEventBusEmit:
    @pytest.mark.asyncio
    async def test_emit_calls_should_execute_and_execute(self):
        bus = MediaEventBus()
        action = _make_action("actor")
        bus.register(action)

        event = _make_event()
        settings = {"enabled": True}
        results = await bus.emit(event, settings)

        action.should_execute.assert_awaited_once_with(event, settings)
        action.execute.assert_awaited_once_with(event, settings)
        assert len(results) == 1
        assert results[0].status == ActionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_emit_skips_action_when_should_execute_false(self):
        bus = MediaEventBus()
        action = _make_action("skipped", should_execute=False)
        bus.register(action)

        results = await bus.emit(_make_event(), {})

        action.should_execute.assert_awaited_once()
        action.execute.assert_not_awaited()
        assert len(results) == 1
        assert results[0].status == ActionStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_emit_with_no_actions_returns_empty(self):
        bus = MediaEventBus()
        results = await bus.emit(_make_event(), {})
        assert results == []

    @pytest.mark.asyncio
    async def test_emit_multiple_actions_independent(self):
        bus = MediaEventBus()
        a1 = _make_action("first", should_execute=True)
        a2 = _make_action("second", should_execute=False)
        a3 = _make_action("third", should_execute=True)
        bus.register(a1)
        bus.register(a2)
        bus.register(a3)

        results = await bus.emit(_make_event(), {})

        assert len(results) == 3
        assert results[0].status == ActionStatus.SUCCESS
        assert results[1].status == ActionStatus.SKIPPED
        assert results[2].status == ActionStatus.SUCCESS


class TestMediaEventBusErrorIsolation:
    @pytest.mark.asyncio
    async def test_action_execute_error_does_not_block_others(self):
        bus = MediaEventBus()

        failing = _make_action("failing")
        failing.execute = AsyncMock(side_effect=RuntimeError("boom"))

        succeeding = _make_action("succeeding")
        bus.register(failing)
        bus.register(succeeding)

        results = await bus.emit(_make_event(), {})

        assert len(results) == 2
        assert results[0].status == ActionStatus.ERROR
        assert "boom" in results[0].message
        assert results[1].status == ActionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_action_should_execute_error_treated_as_skip(self):
        bus = MediaEventBus()

        broken = _make_action("broken")
        broken.should_execute = AsyncMock(side_effect=ValueError("bad config"))
        bus.register(broken)

        results = await bus.emit(_make_event(), {})

        assert len(results) == 1
        assert results[0].status == ActionStatus.ERROR


class TestMediaEvent:
    def test_media_event_creation(self):
        event = _make_event()
        assert event.event_type == "customer_media_detected"
        assert event.message_type == "image"
        assert event.customer_name == "张三"

    def test_media_event_is_image(self):
        event = _make_event(message_type="image")
        assert event.is_media
        assert event.message_type == "image"

    def test_media_event_is_video(self):
        event = _make_event(message_type="video")
        assert event.is_media
        assert event.message_type == "video"

    def test_media_event_text_is_not_media(self):
        event = _make_event(message_type="text")
        assert not event.is_media
