"""
Monitoring API router.

Exposes heartbeat, AI health, and process event data for the frontend
monitoring dashboard.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from services.heartbeat_service import (
    get_latest_heartbeat_per_device,
    get_recent_ai_health,
    get_recent_heartbeats,
    get_recent_process_events,
)

router = APIRouter()


@router.get("/heartbeats")
async def list_heartbeats(
    device_serial: str | None = Query(None),
    since: str | None = Query(None, description="ISO timestamp lower bound"),
    limit: int = Query(100, ge=1, le=1000),
):
    return get_recent_heartbeats(device_serial=device_serial, since=since, limit=limit)


@router.get("/heartbeats/latest")
async def latest_heartbeats():
    """Most recent heartbeat per device — used for the real-time status cards."""
    return get_latest_heartbeat_per_device()


@router.get("/ai-health")
async def list_ai_health(limit: int = Query(50, ge=1, le=500)):
    return get_recent_ai_health(limit=limit)


@router.get("/process-events")
async def list_process_events(
    device_serial: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    return get_recent_process_events(device_serial=device_serial, limit=limit)
