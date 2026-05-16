"""Unit tests for HeartbeatClient reader/writer command dispatch."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.heartbeat_client import HeartbeatClient


class _MockWebSocket:
    """Minimal async WebSocket: recv queue + recorded sends."""

    def __init__(self, inbound: list[dict]) -> None:
        self._inbound = [json.dumps(m) for m in inbound]
        self.sent: list[str] = []

    async def recv(self) -> str:
        if not self._inbound:
            await asyncio.sleep(3600)
        return self._inbound.pop(0)

    async def send(self, data: str) -> None:
        self.sent.append(data)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reader_dispatches_command_without_writer_delay() -> None:
    """Commands must be handled as soon as recv returns, not on heartbeat interval."""
    settings = MagicMock()
    general = MagicMock()
    general.device_id = "test-host"
    general.hostname = "test-host"
    general.person_name = "Tester"
    settings.get_general_settings.return_value = general
    ai = MagicMock()
    ai.use_ai_reply = False
    settings.get_ai_reply_settings.return_value = ai

    client = HeartbeatClient(
        dashboard_url="ws://localhost/ws/heartbeat",
        settings_service=settings,
        interval_s=10.0,
    )

    command = {
        "type": "command",
        "command_id": "test-host:1",
        "action": "device_start",
        "serial": "SERIAL1",
    }
    ws = _MockWebSocket([command])

    handled = asyncio.Event()

    async def fake_handle(_safe_send, data: dict) -> None:
        assert data["action"] == "device_start"
        handled.set()

    client._handle_command = fake_handle  # type: ignore[method-assign]

    reader = asyncio.create_task(client._reader_loop(ws, AsyncMock()))
    await asyncio.wait_for(handled.wait(), timeout=1.0)
    reader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reader
