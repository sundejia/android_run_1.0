"""Dashboard telemetry store and event emitter.

DeviceTelemetryStore: in-memory per-device state (red dots, followup, AI)
that is snapshotted into heartbeat payloads.

DashboardEventEmitter: enqueues discrete events that HeartbeatClient
sends as ``{"type":"event", ...}`` on the same /ws/heartbeat connection.
Each emit also updates DeviceTelemetryStore so state is always consistent.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DeviceTelemetry:
    """Snapshot of one Android device's live telemetry."""

    red_dot_pending: int = 0
    current_target: str | None = None

    followup_in_progress: bool = False
    followup_target: str | None = None
    followup_batch_id: str | None = None

    ai_last_request_at: str | None = None
    ai_requests_total: int = 0
    ai_failures_total: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "red_dot_pending": self.red_dot_pending,
            "current_target": self.current_target,
            "followup": {
                "in_progress": self.followup_in_progress,
                "target": self.followup_target,
                "batch_id": self.followup_batch_id,
            },
            "ai": {
                "last_request_at": self.ai_last_request_at,
                "requests_total": self.ai_requests_total,
                "failures_total": self.ai_failures_total,
            },
        }


class DeviceTelemetryStore:
    """Thread-safe (single-event-loop) per-device telemetry state."""

    def __init__(self) -> None:
        self._devices: dict[str, DeviceTelemetry] = {}

    def _get(self, serial: str) -> DeviceTelemetry:
        if serial not in self._devices:
            self._devices[serial] = DeviceTelemetry()
        return self._devices[serial]

    def get_snapshot(self, serial: str) -> dict[str, Any]:
        return self._get(serial).to_dict()

    def set_red_dots(self, serial: str, pending: int, current: str | None) -> None:
        t = self._get(serial)
        t.red_dot_pending = pending
        t.current_target = current

    def mark_ai_request(self, serial: str, success: bool) -> None:
        t = self._get(serial)
        t.ai_requests_total += 1
        if not success:
            t.ai_failures_total += 1
        t.ai_last_request_at = datetime.now(timezone.utc).isoformat()

    def start_followup_batch(self, serial: str, batch_id: str) -> None:
        t = self._get(serial)
        t.followup_in_progress = True
        t.followup_batch_id = batch_id
        t.followup_target = None

    def mark_followup_progress(self, serial: str, target: str) -> None:
        t = self._get(serial)
        t.followup_in_progress = True
        t.followup_target = target

    def finish_followup_batch(self, serial: str) -> None:
        t = self._get(serial)
        t.followup_in_progress = False
        t.followup_target = None
        t.followup_batch_id = None

    def clear(self, serial: str) -> None:
        self._devices.pop(serial, None)


class DashboardEventEmitter:
    """Enqueues discrete events that HeartbeatClient sends alongside heartbeats.

    Usage:
        emitter = DashboardEventEmitter(store)
        emitter.emit("ai_request", "SERIAL", {"result": "ok", "latency_ms": 42})
        # HeartbeatClient drains emitter.queue
    """

    def __init__(self, store: DeviceTelemetryStore) -> None:
        self._store = store
        self.queue: asyncio.Queue[dict] = asyncio.Queue()

    @property
    def store(self) -> DeviceTelemetryStore:
        return self._store

    def emit(self, event_kind: str, serial: str, payload: dict[str, Any] | None = None) -> None:
        """Fire-and-forget: update store + enqueue for WS send."""
        payload = payload or {}
        self._update_store(event_kind, serial, payload)
        event = {
            "type": "event",
            "event_kind": event_kind,
            "serial": serial,
            "payload": payload,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("dashboard_event_queue_full: dropping %s for %s", event_kind, serial)

    def _update_store(self, kind: str, serial: str, payload: dict) -> None:
        if kind == "red_dot_update":
            self._store.set_red_dots(
                serial,
                payload.get("pending", 0),
                payload.get("current_target"),
            )
        elif kind == "ai_request":
            self._store.mark_ai_request(serial, payload.get("result") == "ok")
        elif kind == "followup_started":
            batch_id = payload.get("batch_id") or str(uuid.uuid4())[:8]
            self._store.start_followup_batch(serial, batch_id)
        elif kind == "followup_progress":
            self._store.mark_followup_progress(serial, payload.get("target", ""))
        elif kind in ("followup_finished", "followup_result"):
            if kind == "followup_finished":
                self._store.finish_followup_batch(serial)


# ── Singleton ──

_emitter: DashboardEventEmitter | None = None
_store: DeviceTelemetryStore | None = None


def get_telemetry_store() -> DeviceTelemetryStore:
    global _store
    if _store is None:
        _store = DeviceTelemetryStore()
    return _store


def get_dashboard_emitter() -> DashboardEventEmitter:
    global _emitter
    if _emitter is None:
        _emitter = DashboardEventEmitter(get_telemetry_store())
    return _emitter
