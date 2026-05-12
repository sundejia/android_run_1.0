"""
Monitoring API router.

Exposes heartbeat, AI health, and process event data for the frontend
monitoring dashboard.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from services.heartbeat_service import (
    get_latest_click_health_per_device,
    get_latest_heartbeat_per_device,
    get_recent_ai_health,
    get_recent_click_health,
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


@router.get("/click-health")
async def list_click_health(
    device_serial: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    """Recent click-health snapshots (per-scan dayblock / cooldown surface).

    Use this endpoint to spot the 2026-05-09 failure mode where a single
    customer dominates the priority queue. The signals to alert on:

    - ``dayblock_size`` sustained > 0 (any non-empty dayblock means a customer
      hit the click-failure threshold today; check ``dayblock_keys`` for who)
    - ``active_cooldown_count`` sustained > 3 for a single device
    - ``priority_queue_repeats`` rising while ``unique_customers_clicked``
      stays flat (priority queue is running in circles)

    See docs/04-bugs-and-fixes/resolved/2026-05-12-new-friend-false-positive-click-loop.md
    """
    return get_recent_click_health(device_serial=device_serial, limit=limit)


@router.get("/click-health/latest")
async def latest_click_health():
    """Latest click-health snapshot per device — feeds the dashboard cards."""
    return get_latest_click_health_per_device()
