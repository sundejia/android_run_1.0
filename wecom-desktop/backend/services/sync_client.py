"""Sync client: WebSocket client connecting to Analytics-Platform cloud.

Sends real-time sync events (customer, message, media metadata) and
receives commands (media_request) from the cloud server.

Follows the same reconnect pattern as HeartbeatClient.
"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class SyncClient:
    """WebSocket client for real-time sync to Analytics-Platform."""

    def __init__(
        self,
        sync_url: str,
        sync_token: str,
        settings_service: Any = None,
        heartbeat_interval: float = 30.0,
    ) -> None:
        self._sync_url = sync_url
        self._sync_token = sync_token
        self._settings = settings_service
        self._heartbeat_interval = heartbeat_interval
        self._task: asyncio.Task | None = None
        self._status: str = "disconnected"
        self._ws: Any = None
        self._event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self._events_sent: int = 0
        self._last_event_at: str = ""

    @property
    def status(self) -> str:
        return self._status

    @property
    def queue_size(self) -> int:
        return self._event_queue.qsize()

    @property
    def events_sent(self) -> int:
        return self._events_sent

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run())
        logger.info("sync_client_started: url=%s", self._sync_url)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._status = "disconnected"
        logger.info("sync_client_stopped")

    def emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Non-blocking: enqueue an event for sending. Drops if queue is full."""
        source = self._build_source()
        event = {
            "type": event_type,
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "payload": payload,
        }
        try:
            self._event_queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("sync_event_dropped: queue full, type=%s", event_type)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        backoff = 3.0
        while True:
            try:
                self._status = "connecting"
                await self._connect_and_sync()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._status = "disconnected"
                logger.warning("sync_client_error: %s (retry in %.0fs)", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 30.0)

    async def _connect_and_sync(self) -> None:
        import websockets.asyncio.client

        async with websockets.asyncio.client.connect(
            self._sync_url,
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
        ) as ws:
            self._ws = ws
            self._status = "connected"

            # Send auth
            auth_msg = {
                "type": "sync.auth",
                "token": self._sync_token,
                "device_id": self._get_device_id(),
                "hostname": self._get_hostname(),
                "person_name": self._get_person_name(),
            }
            await asyncio.wait_for(ws.send(json.dumps(auth_msg)), timeout=10)
            raw = await asyncio.wait_for(ws.recv(), timeout=15)
            resp = json.loads(raw)
            if resp.get("type") != "sync.auth_ok":
                raise ConnectionError(f"Auth failed: {resp}")

            logger.info("sync_client_connected: url=%s", self._sync_url)
            backoff = 3.0  # reset on successful connect

            # Run heartbeat + event sender + command receiver concurrently
            await asyncio.gather(
                self._heartbeat_loop(ws),
                self._event_sender_loop(ws),
                self._command_receiver_loop(ws),
            )

    async def _heartbeat_loop(self, ws: Any) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_interval)
            try:
                msg = {
                    "type": "sync.heartbeat",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": self._build_source(),
                }
                await asyncio.wait_for(ws.send(json.dumps(msg)), timeout=10)
            except Exception:
                break

    async def _event_sender_loop(self, ws: Any) -> None:
        while True:
            event = await self._event_queue.get()
            try:
                await asyncio.wait_for(ws.send(json.dumps(event)), timeout=10)
                self._events_sent += 1
                self._last_event_at = event.get("timestamp", "")
            except Exception:
                # Re-enqueue at front if possible, else drop
                logger.warning("sync_event_send_failed: type=%s", event.get("type"))
                raise

    async def _command_receiver_loop(self, ws: Any) -> None:
        while True:
            raw = await ws.recv()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = message.get("type", "")

            if msg_type == "sync.heartbeat_ack":
                continue
            if msg_type == "sync.ack":
                continue
            if msg_type == "command.media_request":
                asyncio.create_task(self._handle_media_request(message))
            elif msg_type == "command.ping":
                await ws.send(json.dumps({"type": "command.pong"}))
            else:
                logger.debug("sync_unhandled_message: type=%s", msg_type)

    async def _handle_media_request(self, message: dict[str, Any]) -> None:
        """Handle a media_request command from cloud: upload the requested file."""
        payload = message.get("payload", {})
        file_path = payload.get("file_path", "")
        request_token = payload.get("request_token", "")
        upload_url = payload.get("upload_url", "")
        command_id = message.get("command_id", "")

        if not file_path or not Path(file_path).exists():
            logger.warning("sync_media_request_file_missing: %s", file_path)
            return

        source = self._build_source()
        base_url = self._sync_url.rsplit("/api/sync/ws", 1)[0]
        full_upload_url = f"{base_url}{upload_url}"

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                with open(file_path, "rb") as f:
                    response = await client.post(
                        full_upload_url,
                        files={"file": (Path(file_path).name, f)},
                        data={
                            "request_token": request_token,
                            "media_type": payload.get("media_type", "image"),
                            "source_device_id": source.get("device_id", "unknown"),
                            "local_message_id": str(payload.get("message_id", "")),
                        },
                    )
                response.raise_for_status()
                logger.info("sync_media_uploaded: %s", file_path)

                # Notify cloud
                self.emit_event("sync.media.uploaded", {
                    "command_id": command_id,
                    "media_type": payload.get("media_type"),
                    "file_path": file_path,
                    "success": True,
                    "file_size": Path(file_path).stat().st_size,
                })
        except Exception as exc:
            logger.error("sync_media_upload_failed: %s - %s", file_path, exc)

    def _build_source(self) -> dict[str, str]:
        return {
            "device_id": self._get_device_id(),
            "hostname": self._get_hostname(),
            "person_name": self._get_person_name(),
        }

    def _get_device_id(self) -> str:
        if self._settings:
            try:
                general = self._settings.get_general_settings()
                return general.device_id or self._get_hostname()
            except Exception:
                pass
        return self._get_hostname()

    def _get_hostname(self) -> str:
        if self._settings:
            try:
                general = self._settings.get_general_settings()
                return general.hostname or platform.node()
            except Exception:
                pass
        return platform.node()

    def _get_person_name(self) -> str:
        if self._settings:
            try:
                general = self._settings.get_general_settings()
                return general.person_name or self._get_hostname()
            except Exception:
                pass
        return self._get_hostname()
