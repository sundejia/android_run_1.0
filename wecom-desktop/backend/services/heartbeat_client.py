"""Heartbeat client: connects to device-dashboard and pushes periodic heartbeats."""

from __future__ import annotations

import asyncio
import json
import logging
import platform
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class HeartbeatClient:
    """WebSocket client that sends heartbeats to the device-dashboard."""

    def __init__(
        self,
        dashboard_url: str,
        settings_service: Any,
        device_manager: Any = None,
        interval_s: float = 10.0,
        app_version: str = "1.0.0",
    ) -> None:
        self._dashboard_url = dashboard_url
        self._settings = settings_service
        self._device_manager = device_manager
        self._interval = interval_s
        self._app_version = app_version
        self._task: asyncio.Task | None = None
        self._status: str = "disconnected"  # disconnected | connecting | connected
        self._instance_id: str = ""
        self._ws: Any = None

    @property
    def status(self) -> str:
        return self._status

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run())
        logger.info("heartbeat_client_started: url=%s", self._dashboard_url)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._status = "disconnected"
        logger.info("heartbeat_client_stopped")

    async def test_connection(self) -> dict:
        """Test connection to dashboard. Returns {success, message}."""
        try:
            import websockets.asyncio.client

            async with websockets.asyncio.client.connect(
                self._dashboard_url, open_timeout=5
            ) as ws:
                payload = self._build_heartbeat()
                await ws.send(json.dumps(payload))
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                resp = json.loads(raw)
                if resp.get("type") == "welcome":
                    return {"success": True, "message": "Connection successful"}
                return {"success": False, "message": f"Unexpected response: {resp}"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def _run(self) -> None:
        backoff = 3.0
        while True:
            try:
                self._status = "connecting"
                await self._connect_and_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._status = "disconnected"
                logger.warning("heartbeat_client_error: %s", exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 30.0)

    async def _connect_and_heartbeat(self) -> None:
        import websockets.asyncio.client

        async with websockets.asyncio.client.connect(
            self._dashboard_url,
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
        ) as ws:
            self._ws = ws
            self._status = "connected"

            # Send first heartbeat
            payload = self._build_heartbeat()
            await asyncio.wait_for(ws.send(json.dumps(payload)), timeout=10)
            raw = await asyncio.wait_for(ws.recv(), timeout=15)
            logger.info("heartbeat_client_connected: url=%s", self._dashboard_url)

            while True:
                await asyncio.sleep(self._interval)
                payload = self._build_heartbeat()
                await asyncio.wait_for(ws.send(json.dumps(payload)), timeout=10)
                await asyncio.wait_for(ws.recv(), timeout=15)

    def _build_heartbeat(self) -> dict:
        now = datetime.now(timezone.utc).isoformat()

        # Get identity
        general = self._settings.get_general_settings()
        hostname = general.hostname or platform.node()
        person_name = general.person_name or hostname
        device_id = general.device_id or hostname

        # Get brain URL
        ai_reply = self._settings.get_ai_reply_settings()
        brain_url = ai_reply.server_url if ai_reply.use_ai_reply else ""

        # Get devices
        devices = []
        if self._device_manager:
            try:
                for serial, proc_info in getattr(self._device_manager, "_processes", {}).items():
                    devices.append({
                        "serial": serial,
                        "name": serial,
                        "status": "online" if proc_info and proc_info.poll() is None else "offline",
                    })
            except Exception:
                pass

        # Get AI health (simplified)
        ai_reachable = True
        ai_response_ms = None

        return {
            "type": "heartbeat",
            "instance_id": device_id,
            "instance_type": "wecom_client",
            "name": person_name,
            "version": self._app_version,
            "timestamp": now,
            "brain_url": brain_url,
            "devices": devices,
            "device_count": len(devices),
            "health": {
                "status": "ok",
                "ai_reachable": ai_reachable,
                "ai_response_ms": ai_response_ms,
            },
        }
