"""
Tests that sidecar message sending is prioritized over background polling.
"""

import asyncio
import sys
import time
from pathlib import Path

import pytest

# Allow importing routers.* modules and shared src packages
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.path_utils import get_project_root

PROJECT_ROOT = get_project_root()
sys.path.insert(0, str(PROJECT_ROOT / "wecom-desktop" / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from routers import sidecar  # noqa: E402


class FakeADB:
    """Lightweight stand-in for the ADB service used by SidecarSession."""

    def __init__(self):
        self.is_connected = False
        self.last_focused_text = "input"

    async def connect(self):
        self.is_connected = True

    async def get_ui_state(self, force: bool = False):
        await asyncio.sleep(0.01)
        return {"root": True}, []

    def hash_ui_tree(self, tree):
        return "hash123"


class FakeUIParser:
    """Parses are intentionally CPU-ish to validate offloading."""

    def get_conversation_header_info(self, tree):
        return ("Alice", "DM")

    def extract_conversation_messages(self, tree):
        # Simulate heavier work that would block the event loop if not offloaded
        time.sleep(0.05)
        return [{"content": "hello", "timestamp": "t", "is_self": False}]

    def extract_kefu_info_from_tree(self, tree, max_x=0, min_y=0, max_y=0):
        return None


class FakeWeComService:
    def __init__(self, *args, **kwargs):
        self.adb = FakeADB()
        self.ui_parser = FakeUIParser()
        self._send_started: asyncio.Event = kwargs.get("send_started", asyncio.Event())

    async def send_message(self, text: str) -> tuple:
        # Mimic a slightly long-running send to check scheduling
        # Returns (success, actual_message_sent) tuple to match real interface
        self._send_started.set()
        await asyncio.sleep(0.05)
        return True, text


@pytest.mark.asyncio
async def test_snapshot_returns_cached_state_while_sending(monkeypatch):
    """
    When a send is in progress, snapshot should avoid competing for the lock
    and return cached state immediately so sending is never blocked.
    """

    send_started = asyncio.Event()

    # Inject the fake service so SidecarSession uses fast, deterministic stubs
    def fake_service_factory(config):
        return FakeWeComService(send_started=send_started)

    monkeypatch.setattr(sidecar, "WeComService", fake_service_factory)

    session = sidecar.SidecarSession("SERIAL-123")

    # Prime the cache with an initial snapshot
    initial_state = await session.snapshot()
    assert initial_state.in_conversation is True
    assert session._last_state is not None  # noqa: SLF001

    # Start sending, then immediately request another snapshot
    send_task = asyncio.create_task(session.send_message("hello"))
    await send_started.wait()  # ensure send has started and set the priority flag

    loop = asyncio.get_event_loop()
    start = loop.time()
    snapshot_state = await session.snapshot()
    elapsed = loop.time() - start

    await send_task

    # Snapshot should have short-circuited to cached state (< 20ms budget)
    assert elapsed < 0.02
    assert snapshot_state is session._last_state  # noqa: SLF001
