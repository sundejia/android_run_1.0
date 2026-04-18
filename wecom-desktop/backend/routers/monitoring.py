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
from wecom_automation.core.performance import runtime_metrics

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


@router.get("/runtime-hygiene")
async def get_runtime_hygiene(
    phase: str | None = Query(
        None,
        description="Filter lifecycle events by phase (startup|shutdown). "
        "Omit to return both.",
    ),
    limit: int = Query(50, ge=1, le=200, description="Max lifecycle events to return"),
):
    """Return the latest startup/shutdown timeline plus the most recent
    runtime_hygiene report.

    This is the dashboard answer to *"what happened at the last boot"* —
    how many orphan subprocesses were killed, how many stale ``$TMPDIR``
    upload snapshots were swept, whether the ``adb kill-server &&
    start-server`` baseline succeeded, and which startup steps emitted
    warnings or errors.

    Backed by the in-memory deque in ``runtime_metrics``; the underlying
    JSONL files (``logs/metrics/lifecycle.jsonl`` and ``hygiene.jsonl``)
    keep the long-term history if you need to dig further than the last
    ~200 events."""
    snapshot = runtime_metrics.snapshot()
    lifecycle = snapshot.get("lifecycle", {}) or {}
    events = lifecycle.get("events", []) or []
    if phase:
        events = [e for e in events if e.get("phase") == phase]
    # Newest events are appended at the tail of the deque; reverse so the
    # caller gets them in "most recent first" order, then cap to `limit`.
    events = list(reversed(events))[:limit]
    return {
        "startup": snapshot.get("startup", {}),
        "events": events,
        "event_count_total": lifecycle.get("event_count", 0),
        "hygiene": snapshot.get("hygiene"),
    }
