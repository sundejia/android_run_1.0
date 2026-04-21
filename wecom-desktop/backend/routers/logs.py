"""
Log streaming router.

Provides WebSocket endpoints for real-time log streaming from sync operations.

Heartbeat contract
------------------
The frontend is responsible for sending an application-level ``"ping"`` text
frame every ~25s and treats the absence of any response within ~35s as a fatal
error (it then closes the socket and reconnects). The server only ever
*replies* with ``"pong"`` for those frames.

In addition uvicorn is configured to send WebSocket protocol ping frames
(``--ws-ping-interval 20 --ws-ping-timeout 30``) so half-open connections that
slip past the application heartbeat (for example because the client event loop
is stuck) are still detected by the transport layer.

The 90s ``receive_text`` timeout in this module is therefore only a backstop
for the case where both the application heartbeat and the transport ping have
gone silent: it tries one final ``send_text`` probe and breaks out if that
write itself fails.
"""

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from services.device_manager import DeviceManager

logger = logging.getLogger("logs_router")

router = APIRouter()

# Store active WebSocket connections per device
_log_connections: dict[str, set[WebSocket]] = {}
_sync_connections: dict[str, set[WebSocket]] = {}


def get_device_manager() -> DeviceManager:
    """Get device manager from sync router."""
    from routers.sync import get_device_manager as get_manager

    return get_manager()


async def broadcast_log(serial: str, message: dict):
    """Broadcast a log message to all connected clients for a device."""
    if serial not in _log_connections:
        return

    disconnected = set()
    for ws in list(_log_connections[serial]):
        try:
            await ws.send_json(message)
        except Exception as e:
            logger.debug("broadcast_log failed serial=%s: %s", serial, e)
            disconnected.add(ws)

    # Drop dead sockets and proactively close them so the per-connection
    # receive loop can exit promptly instead of hanging on a half-open socket.
    for ws in disconnected:
        _log_connections[serial].discard(ws)
        try:
            await ws.close(code=1011)
        except Exception:
            pass


async def broadcast_sync_status(serial: str, status: dict):
    """Broadcast sync status to all connected clients for a device."""
    if serial not in _sync_connections:
        return

    disconnected = set()
    for ws in list(_sync_connections[serial]):
        try:
            await ws.send_json(status)
        except Exception as e:
            logger.debug("broadcast_sync_status failed serial=%s: %s", serial, e)
            disconnected.add(ws)

    for ws in disconnected:
        _sync_connections[serial].discard(ws)
        try:
            await ws.close(code=1011)
        except Exception:
            pass


@router.websocket("/ws/logs/{serial}")
async def websocket_logs(websocket: WebSocket, serial: str):
    """
    WebSocket endpoint for real-time log streaming.

    Receives logs from both Sync and FollowUp operations for a specific device.
    Logs are tagged with 'source' field to distinguish between sources.
    """
    await websocket.accept()
    client_id = f"{serial}@{id(websocket):x}"

    # Register connection
    if serial not in _log_connections:
        _log_connections[serial] = set()
    _log_connections[serial].add(websocket)

    # Create unified log callback
    async def log_callback(message: dict):
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.debug("log_callback send failed for %s: %s", client_id, e)

    # Register Sync log callback
    manager = get_device_manager()
    manager.register_log_callback(serial, log_callback)

    # Register FollowUp log callback (if available)
    followup_registered = False
    try:
        from services.realtime_reply_manager import get_realtime_reply_manager

        followup_manager = get_realtime_reply_manager()
        followup_manager.register_log_callback(serial, log_callback)
        followup_registered = True
    except ImportError:
        pass
    except Exception as e:
        logger.warning(
            "followup log callback registration failed for %s: %s", client_id, e
        )

    disconnect_reason = "unknown"
    try:
        # Send initial connection message
        await websocket.send_json(
            {
                "timestamp": datetime.now().isoformat(),
                "level": "INFO",
                "message": f"Connected to log stream for {serial}",
                "source": "system",
            }
        )

        # Receive loop. The 90s timeout is the *backstop* described in the
        # module docstring; the primary keepalive is the client-driven
        # "ping"/"pong" exchange plus uvicorn's protocol ping frames.
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(), timeout=90.0
                )
            except TimeoutError:
                try:
                    await websocket.send_text("ping")
                    continue
                except Exception:
                    disconnect_reason = "inactivity-probe-failed"
                    break

            if data == "ping":
                try:
                    await websocket.send_text("pong")
                except Exception:
                    disconnect_reason = "pong-send-failed"
                    break
            elif data == "pong":
                # Client acknowledging our backstop probe; nothing else to do.
                continue
            # Any other inbound text is ignored: this channel is server -> client.

    except WebSocketDisconnect as e:
        disconnect_reason = f"client-disconnect:{e.code}"
    except Exception as e:
        disconnect_reason = f"server-error:{type(e).__name__}"
        logger.warning(
            "websocket_logs unexpected error for %s: %s", client_id, e
        )
    finally:
        logger.info(
            "websocket_logs closed client=%s reason=%s",
            client_id,
            disconnect_reason,
        )
        # Unregister callbacks
        manager.unregister_log_callback(serial, log_callback)
        if followup_registered:
            try:
                from services.realtime_reply_manager import (
                    get_realtime_reply_manager,
                )

                followup_manager = get_realtime_reply_manager()
                followup_manager.unregister_log_callback(serial, log_callback)
            except Exception:
                pass

        if serial in _log_connections:
            _log_connections[serial].discard(websocket)
            if not _log_connections[serial]:
                _log_connections.pop(serial, None)

        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/ws/sync/{serial}")
async def websocket_sync_status(websocket: WebSocket, serial: str):
    """
    WebSocket endpoint for real-time sync status updates.

    Clients connect to receive sync progress updates for a specific device.
    """
    await websocket.accept()
    client_id = f"{serial}@{id(websocket):x}"

    # Register connection
    if serial not in _sync_connections:
        _sync_connections[serial] = set()
    _sync_connections[serial].add(websocket)

    # Get device manager and register status callback
    manager = get_device_manager()

    async def status_callback(status: dict):
        try:
            await websocket.send_json(status)
        except Exception as e:
            logger.debug(
                "status_callback send failed for %s: %s", client_id, e
            )

    manager.register_status_callback(serial, status_callback)

    disconnect_reason = "unknown"
    try:
        # Send initial status
        state = manager.get_sync_state(serial)
        if state:
            await websocket.send_json(
                {
                    "status": state.status.value,
                    "progress": state.progress,
                    "message": state.message,
                    "customers_synced": state.customers_synced,
                    "messages_added": state.messages_added,
                }
            )

        # Same heartbeat contract as the log channel above.
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(), timeout=90.0
                )
            except TimeoutError:
                try:
                    await websocket.send_text("ping")
                    continue
                except Exception:
                    disconnect_reason = "inactivity-probe-failed"
                    break

            if data == "ping":
                try:
                    await websocket.send_text("pong")
                except Exception:
                    disconnect_reason = "pong-send-failed"
                    break
            elif data == "pong":
                continue

    except WebSocketDisconnect as e:
        disconnect_reason = f"client-disconnect:{e.code}"
    except Exception as e:
        disconnect_reason = f"server-error:{type(e).__name__}"
        logger.warning(
            "websocket_sync_status unexpected error for %s: %s",
            client_id,
            e,
        )
    finally:
        logger.info(
            "websocket_sync_status closed client=%s reason=%s",
            client_id,
            disconnect_reason,
        )
        # Unregister connection
        manager.unregister_status_callback(serial, status_callback)
        if serial in _sync_connections:
            _sync_connections[serial].discard(websocket)
            if not _sync_connections[serial]:
                _sync_connections.pop(serial, None)

        try:
            await websocket.close()
        except Exception:
            pass
