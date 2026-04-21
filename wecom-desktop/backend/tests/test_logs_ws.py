"""
WebSocket regression tests for ``routers/logs.py``.

These tests deliberately avoid importing the full ``main`` app: the production
app spins up heartbeat services, opens databases, and registers many subprocess
managers. Instead we mount the logs router on a minimal FastAPI app and stub
out :func:`routers.logs.get_device_manager` so the tests stay hermetic.

The behaviors we lock in here previously caused users to see permanent
"Log stream disconnected" status after long runs:

* a client-driven ``"ping"`` must produce a server-side ``"pong"``
* the connection must NOT be closed proactively after a few seconds of silence
* an unrelated text frame from the client must be ignored, not echoed
"""

import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import logs as logs_router


class _StubDeviceManager:
    """Minimal stand-in for ``services.device_manager.DeviceManager``."""

    def __init__(self) -> None:
        self.registered: list = []

    def register_log_callback(self, serial: str, callback) -> None:
        self.registered.append(("register", serial, callback))

    def unregister_log_callback(self, serial: str, callback) -> None:
        self.registered.append(("unregister", serial, callback))


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    stub = _StubDeviceManager()
    monkeypatch.setattr(logs_router, "get_device_manager", lambda: stub)

    app = FastAPI()
    app.include_router(logs_router.router)
    return TestClient(app)


def test_ping_pong_roundtrip(client: TestClient) -> None:
    """A client-driven ping must be answered with pong and not close the socket."""
    with client.websocket_connect("/ws/logs/SERIAL_T") as ws:
        # The server emits an initial JSON "Connected" message.
        first = ws.receive_json()
        assert first["source"] == "system"
        assert first["level"] == "INFO"

        ws.send_text("ping")
        assert ws.receive_text() == "pong"

        # Round-trip should be repeatable.
        ws.send_text("ping")
        assert ws.receive_text() == "pong"


def test_short_idle_does_not_close_connection(client: TestClient) -> None:
    """A few seconds of inactivity must not trigger a server-side close."""
    with client.websocket_connect("/ws/logs/SERIAL_T") as ws:
        ws.receive_json()  # initial Connected envelope

        # Sleep a few seconds inside the same connection. Because the receive
        # loop's backstop is 90s, this should remain wide open.
        import time

        time.sleep(2)

        ws.send_text("ping")
        assert ws.receive_text() == "pong"


def test_unknown_text_frames_are_ignored(client: TestClient) -> None:
    """Anything other than ping/pong must be silently ignored, not echoed."""
    with client.websocket_connect("/ws/logs/SERIAL_T") as ws:
        ws.receive_json()  # initial Connected envelope

        ws.send_text("hello-from-client")

        # Follow up with a real ping; the response must still be "pong",
        # proving the previous frame did not corrupt the protocol state.
        ws.send_text("ping")
        assert ws.receive_text() == "pong"


def test_callback_unregistered_on_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closing the WebSocket must unregister the log callback."""
    stub = _StubDeviceManager()
    monkeypatch.setattr(logs_router, "get_device_manager", lambda: stub)

    app = FastAPI()
    app.include_router(logs_router.router)
    test_client = TestClient(app)

    with test_client.websocket_connect("/ws/logs/SERIAL_T") as ws:
        ws.receive_json()

    actions = [event[0] for event in stub.registered]
    assert "register" in actions
    assert "unregister" in actions
