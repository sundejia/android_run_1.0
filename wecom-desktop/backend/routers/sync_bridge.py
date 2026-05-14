"""Router for sync bridge diagnostics."""

from __future__ import annotations

from fastapi import APIRouter

from services.sync_client import SyncClient
from services.sync_event_bridge import _sync_client

router = APIRouter(prefix="/api/sync-bridge", tags=["Sync Bridge"])


@router.get("/status")
def get_sync_bridge_status() -> dict:
    """Return the current status of the sync bridge."""
    client: SyncClient | None = _sync_client
    if not client:
        return {
            "enabled": False,
            "status": "not_configured",
            "message": "Sync client not initialized",
        }
    return {
        "enabled": True,
        "status": client.status,
        "queue_size": client.queue_size,
        "events_sent": client.events_sent,
        "last_event_at": client._last_event_at,
    }
