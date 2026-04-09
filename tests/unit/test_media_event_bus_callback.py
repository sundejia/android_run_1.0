"""
Tests for MediaEventBus on_action_results callback mechanism.

TDD red phase: defines the expected callback behavior added to MediaEventBus
for notifying external systems (e.g. WebSocket) after actions execute.
"""

from __future__ import annotations

import pytest
from datetime import datetime
from unittest.mock import AsyncMock

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
        "customer_name": "TestUser",
        "channel": "@WeChat",
        "device_serial": "device001",
        "kefu_name": "KefuA",
        "message_id": 100,
        "timestamp": datetime(2026, 4, 4, 12, 0, 0),
    }
    defaults.update(overrides)
    return MediaEvent(**defaults)


def _make_action(name: str, should_execute: bool = True, status: ActionStatus = ActionStatus.SUCCESS):
    action = AsyncMock(spec=IMediaAction)
    action.action_name = name
    action.should_execute = AsyncMock(return_value=should_execute)
    action.execute = AsyncMock(
        return_value=ActionResult(action_name=name, status=status, message="ok")
    )
    return action


class TestMediaEventBusCallback:
    @pytest.mark.asyncio
    async def test_callback_invoked_on_success(self):
        callback = AsyncMock()
        bus = MediaEventBus(on_action_results=callback)
        bus.register(_make_action("a1"))

        event = _make_event()
        results = await bus.emit(event, {"enabled": True})

        callback.assert_awaited_once()
        call_args = callback.call_args
        assert call_args[0][0] is event
        assert len(call_args[0][1]) == 1
        assert call_args[0][1][0].status == ActionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_callback_not_invoked_when_all_skipped(self):
        callback = AsyncMock()
        bus = MediaEventBus(on_action_results=callback)
        bus.register(_make_action("skipped", should_execute=False))

        await bus.emit(_make_event(), {})

        callback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_callback_not_invoked_when_all_errored(self):
        callback = AsyncMock()
        bus = MediaEventBus(on_action_results=callback)
        bus.register(_make_action("err", status=ActionStatus.ERROR))

        await bus.emit(_make_event(), {})

        callback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_callback_error_does_not_break_emit(self):
        callback = AsyncMock(side_effect=RuntimeError("callback explosion"))
        bus = MediaEventBus(on_action_results=callback)
        bus.register(_make_action("a1"))

        event = _make_event()
        results = await bus.emit(event, {"enabled": True})

        assert len(results) == 1
        assert results[0].status == ActionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_no_callback_by_default(self):
        bus = MediaEventBus()
        bus.register(_make_action("a1"))

        results = await bus.emit(_make_event(), {"enabled": True})

        assert len(results) == 1
        assert results[0].status == ActionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_callback_receives_mixed_results(self):
        """Callback fires if at least one action succeeds, even if others skip/error."""
        callback = AsyncMock()
        bus = MediaEventBus(on_action_results=callback)
        bus.register(_make_action("skipped", should_execute=False))
        bus.register(_make_action("success", should_execute=True, status=ActionStatus.SUCCESS))

        await bus.emit(_make_event(), {})

        callback.assert_awaited_once()
        results = callback.call_args[0][1]
        assert len(results) == 2
