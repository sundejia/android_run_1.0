"""
Log streaming router.

Provides WebSocket endpoints for real-time log streaming from sync operations.
"""

import asyncio
import json
from typing import Dict, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from services.device_manager import DeviceManager

router = APIRouter()

# Store active WebSocket connections per device
_log_connections: Dict[str, Set[WebSocket]] = {}
_sync_connections: Dict[str, Set[WebSocket]] = {}


def get_device_manager() -> DeviceManager:
    """Get device manager from sync router."""
    from routers.sync import get_device_manager as get_manager

    return get_manager()


async def broadcast_log(serial: str, message: dict):
    """Broadcast a log message to all connected clients for a device."""
    if serial not in _log_connections:
        return

    disconnected = set()
    for ws in _log_connections[serial]:
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.add(ws)

    # Remove disconnected clients
    _log_connections[serial] -= disconnected


async def broadcast_sync_status(serial: str, status: dict):
    """Broadcast sync status to all connected clients for a device."""
    if serial not in _sync_connections:
        return

    disconnected = set()
    for ws in _sync_connections[serial]:
        try:
            await ws.send_json(status)
        except Exception:
            disconnected.add(ws)

    # Remove disconnected clients
    _sync_connections[serial] -= disconnected


@router.websocket("/ws/logs/{serial}")
async def websocket_logs(websocket: WebSocket, serial: str):
    """
    WebSocket endpoint for real-time log streaming.

    Receives logs from both Sync and FollowUp operations for a specific device.
    Logs are tagged with 'source' field to distinguish between sources.
    """
    await websocket.accept()

    # Register connection
    if serial not in _log_connections:
        _log_connections[serial] = set()
    _log_connections[serial].add(websocket)

    # Create unified log callback
    async def log_callback(message: dict):
        try:
            await websocket.send_json(message)
        except Exception:
            pass

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
    except Exception:
        pass

    try:
        # Send initial connection message
        from datetime import datetime

        await websocket.send_json(
            {
                "timestamp": datetime.now().isoformat(),
                "level": "INFO",
                "message": f"Connected to log stream for {serial}",
                "source": "system",
            }
        )

        # Keep connection alive and listen for client messages
        while True:
            try:
                # Wait for any message (ping/pong or close)
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)

                # Handle ping
                if data == "ping":
                    await websocket.send_text("pong")

            except asyncio.TimeoutError:
                # Send keepalive ping
                try:
                    await websocket.send_text("ping")
                except Exception:
                    break

    except WebSocketDisconnect:
        pass
    finally:
        # Unregister callbacks
        manager.unregister_log_callback(serial, log_callback)
        if followup_registered:
            try:
                from services.realtime_reply_manager import get_realtime_reply_manager

                followup_manager = get_realtime_reply_manager()
                followup_manager.unregister_log_callback(serial, log_callback)
            except Exception:
                pass

        if serial in _log_connections:
            _log_connections[serial].discard(websocket)


@router.websocket("/ws/sync/{serial}")
async def websocket_sync_status(websocket: WebSocket, serial: str):
    """
    WebSocket endpoint for real-time sync status updates.

    Clients connect to receive sync progress updates for a specific device.
    """
    await websocket.accept()

    # Register connection
    if serial not in _sync_connections:
        _sync_connections[serial] = set()
    _sync_connections[serial].add(websocket)

    # Get device manager and register status callback
    manager = get_device_manager()

    async def status_callback(status: dict):
        try:
            await websocket.send_json(status)
        except Exception:
            pass

    manager.register_status_callback(serial, status_callback)

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

        # Keep connection alive
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                try:
                    await websocket.send_text("ping")
                except Exception:
                    break

    except WebSocketDisconnect:
        pass
    finally:
        # Unregister connection
        manager.unregister_status_callback(serial, status_callback)
        if serial in _sync_connections:
            _sync_connections[serial].discard(websocket)
