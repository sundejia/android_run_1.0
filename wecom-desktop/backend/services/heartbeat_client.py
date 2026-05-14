"""Heartbeat client: connects to device-dashboard and pushes periodic heartbeats."""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import uuid
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
        realtime_reply_manager: Any = None,
        interval_s: float = 10.0,
        app_version: str = "1.0.0",
    ) -> None:
        self._dashboard_url = dashboard_url
        self._settings = settings_service
        self._device_manager = device_manager
        self._realtime_reply_manager = realtime_reply_manager
        self._interval = interval_s
        self._app_version = app_version
        self._task: asyncio.Task | None = None
        self._status: str = "disconnected"  # disconnected | connecting | connected
        self._instance_id: str = ""
        self._ws: Any = None
        self._event_queue: asyncio.Queue = asyncio.Queue()

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
                # Wait for either the heartbeat interval or an event in the queue
                try:
                    event = await asyncio.wait_for(
                        self._event_queue.get(), timeout=self._interval
                    )
                    # Inject instance_id so dashboard knows the source
                    general = self._settings.get_general_settings()
                    event["instance_id"] = general.device_id or (general.hostname or platform.node())
                    await asyncio.wait_for(ws.send(json.dumps(event)), timeout=10)
                    # Read response(s) — may be ack or command
                    await self._read_ws_response(ws)
                    # Drain remaining queued events without blocking
                    while not self._event_queue.empty():
                        try:
                            ev = self._event_queue.get_nowait()
                            ev["instance_id"] = event["instance_id"]
                            await asyncio.wait_for(ws.send(json.dumps(ev)), timeout=10)
                            await self._read_ws_response(ws)
                        except asyncio.QueueEmpty:
                            break
                except asyncio.TimeoutError:
                    pass
                # Always send a heartbeat after draining events / on interval
                payload = self._build_heartbeat()
                await asyncio.wait_for(ws.send(json.dumps(payload)), timeout=10)
                await self._read_ws_response(ws)

    async def _read_ws_response(self, ws) -> None:
        """Read one or more messages from the WebSocket.

        Handles both simple acks and incoming commands from the dashboard.
        """
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=15)
            data = json.loads(raw)
            msg_type = data.get("type", "ack")

            if msg_type == "command":
                await self._handle_command(ws, data)
            # ack or other types: nothing to do
        except asyncio.TimeoutError:
            pass

    async def _handle_command(self, ws, data: dict) -> None:
        """Handle a remote command received from the dashboard."""
        command_id = data.get("command_id", str(uuid.uuid4()))
        action = data.get("action", "")
        serial = data.get("serial", "")

        logger.info("remote_command_received: action=%s serial=%s command_id=%s", action, serial, command_id)

        try:
            if action == "device_start":
                result = await self._cmd_device_start(serial)
            elif action == "device_stop":
                result = await self._cmd_device_stop(serial)
            elif action == "device_pause":
                result = await self._cmd_device_pause(serial)
            elif action == "device_resume":
                result = await self._cmd_device_resume(serial)
            elif action == "device_restart":
                result = await self._cmd_device_restart(serial)
            elif action == "app_restart":
                result = await self._cmd_app_restart(serial)
            else:
                result = {"success": False, "message": f"Unknown action: {action}"}
        except Exception as e:
            logger.error("remote_command_error: action=%s serial=%s error=%s", action, serial, e)
            result = {"success": False, "message": str(e)}

        response = {
            "type": "command_result",
            "command_id": command_id,
            **result,
        }
        try:
            await asyncio.wait_for(ws.send(json.dumps(response)), timeout=10)
        except Exception as e:
            logger.warning("remote_command_reply_failed: %s", e)

    async def _cmd_device_start(self, serial: str) -> dict:
        manager = self._get_realtime_manager()
        if not manager:
            return {"success": False, "message": "RealtimeReplyManager not available"}
        success = await manager.start_realtime_reply(serial)
        return {"success": success, "message": "Started" if success else "Failed to start"}

    async def _cmd_device_stop(self, serial: str) -> dict:
        manager = self._get_realtime_manager()
        if not manager:
            return {"success": False, "message": "RealtimeReplyManager not available"}
        success = await manager.stop_realtime_reply(serial)
        return {"success": success, "message": "Stopped" if success else "Failed to stop"}

    async def _cmd_device_pause(self, serial: str) -> dict:
        manager = self._get_realtime_manager()
        if not manager:
            return {"success": False, "message": "RealtimeReplyManager not available"}
        success = await manager.pause_realtime_reply(serial)
        return {"success": success, "message": "Paused" if success else "Failed to pause"}

    async def _cmd_device_resume(self, serial: str) -> dict:
        manager = self._get_realtime_manager()
        if not manager:
            return {"success": False, "message": "RealtimeReplyManager not available"}
        success = await manager.resume_realtime_reply(serial)
        return {"success": success, "message": "Resumed" if success else "Failed to resume"}

    async def _cmd_device_restart(self, serial: str) -> dict:
        manager = self._get_realtime_manager()
        if not manager:
            return {"success": False, "message": "RealtimeReplyManager not available"}
        # Stop
        await manager.stop_realtime_reply(serial)
        await asyncio.sleep(2)
        # Start
        success = await manager.start_realtime_reply(serial)
        return {"success": success, "message": "Restarted" if success else "Failed to restart"}

    async def _cmd_app_restart(self, serial: str) -> dict:
        """Restart the WeCom app on the Android device via ADB."""
        try:
            from routers.devices import get_discovery_service
            import httpx

            # Call the local system API to restart the WeCom app
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"http://localhost:8765/api/system/restart-wecom-app/{serial}"
                )
                if resp.status_code == 200:
                    return {"success": True, "message": "WeCom app restarted"}
                return {"success": False, "message": f"API error: {resp.status_code} {resp.text}"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def _get_realtime_manager(self):
        """Get the RealtimeReplyManager instance."""
        if self._realtime_reply_manager:
            return self._realtime_reply_manager
        try:
            from services.realtime_reply_manager import get_realtime_reply_manager
            return get_realtime_reply_manager()
        except Exception:
            return None

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

        # Build unified device list from DeviceManager + RealtimeReplyManager
        devices = self._build_device_list()

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

    def _build_device_list(self) -> list[dict]:
        """Build the union of all known device serials from both managers."""
        from .dashboard_events import get_telemetry_store

        seen: dict[str, dict] = {}
        store = get_telemetry_store()

        # DeviceManager (sync processes)
        if self._device_manager:
            try:
                for serial, proc in getattr(self._device_manager, "_processes", {}).items():
                    alive = proc is not None and (
                        proc.returncode is None
                        if hasattr(proc, "returncode")
                        else (proc.poll() is None if hasattr(proc, "poll") else False)
                    )
                    seen[serial] = {
                        "serial": serial,
                        "name": serial,
                        "status": "online",
                        "running": True,
                        "sync_running": alive,
                        "followup_running": False,
                    }
            except Exception:
                pass

        # RealtimeReplyManager (followup processes)
        if self._realtime_reply_manager:
            try:
                for serial, proc in getattr(self._realtime_reply_manager, "_processes", {}).items():
                    alive = proc is not None and (
                        proc.returncode is None
                        if hasattr(proc, "returncode")
                        else (proc.poll() is None if hasattr(proc, "poll") else False)
                    )
                    if serial in seen:
                        seen[serial]["followup_running"] = alive
                        seen[serial]["running"] = seen[serial]["sync_running"] or alive
                    else:
                        seen[serial] = {
                            "serial": serial,
                            "name": serial,
                            "status": "online",
                            "running": alive,
                            "sync_running": False,
                            "followup_running": alive,
                        }
            except Exception:
                pass

        # Merge telemetry store data (red dots, followup, ai)
        devices = []
        for serial, info in seen.items():
            telem = store.get_snapshot(serial)
            info.update(telem)
            devices.append(info)

        return devices
