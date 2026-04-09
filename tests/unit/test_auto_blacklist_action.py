"""
Tests for AutoBlacklistAction.

TDD red phase: defines expected behavior for auto-blacklisting
when a customer sends an image or video.
"""

from __future__ import annotations

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from wecom_automation.services.media_actions.interfaces import (
    ActionResult,
    ActionStatus,
    MediaEvent,
)
from wecom_automation.services.media_actions.actions.auto_blacklist import (
    AutoBlacklistAction,
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
        "auto_blacklist": {
            "enabled": enabled,
            "reason": "Customer sent media (auto)",
            "skip_if_already_blacklisted": True,
        },
    }
    base["auto_blacklist"].update(overrides)
    return base


class TestAutoBlacklistActionName:
    def test_action_name(self):
        writer = MagicMock()
        action = AutoBlacklistAction(blacklist_writer=writer)
        assert action.action_name == "auto_blacklist"


class TestAutoBlacklistShouldExecute:
    @pytest.mark.asyncio
    async def test_should_execute_when_enabled_and_image(self):
        writer = MagicMock()
        writer.is_blacklisted_by_name = MagicMock(return_value=False)
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event(message_type="image")
        settings = _default_settings(enabled=True)

        assert await action.should_execute(event, settings) is True

    @pytest.mark.asyncio
    async def test_should_execute_when_enabled_and_video(self):
        writer = MagicMock()
        writer.is_blacklisted_by_name = MagicMock(return_value=False)
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event(message_type="video")
        settings = _default_settings(enabled=True)

        assert await action.should_execute(event, settings) is True

    @pytest.mark.asyncio
    async def test_should_not_execute_when_disabled(self):
        writer = MagicMock()
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event(message_type="image")
        settings = _default_settings(enabled=False)

        assert await action.should_execute(event, settings) is False

    @pytest.mark.asyncio
    async def test_should_not_execute_when_global_disabled(self):
        writer = MagicMock()
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event(message_type="image")
        settings = {"enabled": False, "auto_blacklist": {"enabled": True}}

        assert await action.should_execute(event, settings) is False

    @pytest.mark.asyncio
    async def test_should_not_execute_when_already_blacklisted(self):
        writer = MagicMock()
        writer.is_blacklisted_by_name = MagicMock(return_value=True)
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event(message_type="image")
        settings = _default_settings(enabled=True, skip_if_already_blacklisted=True)

        assert await action.should_execute(event, settings) is False

    @pytest.mark.asyncio
    async def test_should_execute_even_if_already_blacklisted_when_skip_disabled(self):
        writer = MagicMock()
        writer.is_blacklisted_by_name = MagicMock(return_value=True)
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event(message_type="image")
        settings = _default_settings(enabled=True, skip_if_already_blacklisted=False)

        assert await action.should_execute(event, settings) is True

    @pytest.mark.asyncio
    async def test_should_not_execute_for_text_message(self):
        writer = MagicMock()
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event(message_type="text")
        settings = _default_settings(enabled=True)

        assert await action.should_execute(event, settings) is False


class TestAutoBlacklistExecute:
    @pytest.mark.asyncio
    async def test_execute_adds_to_blacklist(self):
        writer = MagicMock()
        writer.add_to_blacklist = MagicMock(return_value=True)
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event(message_type="image")
        settings = _default_settings()

        result = await action.execute(event, settings)

        writer.add_to_blacklist.assert_called_once_with(
            device_serial="device001",
            customer_name="张三",
            customer_channel="@WeChat",
            reason="Customer sent media (auto)",
            customer_db_id=1,
        )
        assert result.status == ActionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_execute_with_video(self):
        writer = MagicMock()
        writer.add_to_blacklist = MagicMock(return_value=True)
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event(message_type="video")
        settings = _default_settings()

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.SUCCESS
        writer.add_to_blacklist.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_failure_returns_error(self):
        writer = MagicMock()
        writer.add_to_blacklist = MagicMock(return_value=False)
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event()
        settings = _default_settings()

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.ERROR
        assert "failed" in result.message.lower()

    @pytest.mark.asyncio
    async def test_execute_exception_returns_error(self):
        writer = MagicMock()
        writer.add_to_blacklist = MagicMock(side_effect=RuntimeError("DB error"))
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event()
        settings = _default_settings()

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.ERROR
        assert "DB error" in result.message

    @pytest.mark.asyncio
    async def test_execute_uses_custom_reason(self):
        writer = MagicMock()
        writer.add_to_blacklist = MagicMock(return_value=True)
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event()
        settings = _default_settings(reason="Sent inappropriate content")

        result = await action.execute(event, settings)

        call_kwargs = writer.add_to_blacklist.call_args
        assert call_kwargs[1]["reason"] == "Sent inappropriate content"
