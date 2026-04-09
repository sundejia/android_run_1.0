"""
Heartbeat & monitoring service.

Provides:
- Process heartbeat recording (written every scan cycle)
- AI health check recording
- Process lifecycle event recording
- Query APIs for the monitoring frontend
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from services.conversation_storage import get_control_db_path

_HEARTBEAT_DB_NAME = "monitoring.db"


def _get_monitoring_db_path() -> Path:
    """Monitoring DB lives next to the control DB."""
    return get_control_db_path().parent / _HEARTBEAT_DB_NAME


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_get_monitoring_db_path()), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_tables() -> None:
    """Create monitoring tables if they don't exist."""
    conn = _get_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS heartbeats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_serial TEXT NOT NULL,
                scan_number INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'alive',
                scan_duration_ms REAL,
                customers_in_queue INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_heartbeats_device_ts
                ON heartbeats (device_serial, timestamp);

            CREATE TABLE IF NOT EXISTS ai_health_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                ai_server_url TEXT,
                status TEXT,
                response_time_ms REAL,
                error_message TEXT,
                network TEXT,
                http_service TEXT,
                inference TEXT,
                diagnosis TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_ai_health_ts
                ON ai_health_checks (timestamp);

            CREATE TABLE IF NOT EXISTS process_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_serial TEXT NOT NULL,
                event_type TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                scan_count INTEGER,
                uptime_seconds REAL,
                exit_reason TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_process_events_device_ts
                ON process_events (device_serial, timestamp);
            """
        )
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------
# Write helpers (called from realtime_reply_process / manager)
# ------------------------------------------------------------------


def record_heartbeat(
    device_serial: str,
    scan_number: int,
    status: str = "alive",
    scan_duration_ms: float | None = None,
    customers_in_queue: int | None = None,
) -> None:
    conn = _get_connection()
    try:
        conn.execute(
            "INSERT INTO heartbeats (device_serial, scan_number, status, scan_duration_ms, customers_in_queue) "
            "VALUES (?, ?, ?, ?, ?)",
            (device_serial, scan_number, status, scan_duration_ms, customers_in_queue),
        )
        conn.commit()
    finally:
        conn.close()


def record_ai_health(
    ai_server_url: str,
    status: str,
    response_time_ms: float | None = None,
    error_message: str | None = None,
    network: str | None = None,
    http_service: str | None = None,
    inference: str | None = None,
    diagnosis: str | None = None,
) -> None:
    conn = _get_connection()
    try:
        conn.execute(
            "INSERT INTO ai_health_checks "
            "(ai_server_url, status, response_time_ms, error_message, network, http_service, inference, diagnosis) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ai_server_url, status, response_time_ms, error_message, network, http_service, inference, diagnosis),
        )
        conn.commit()
    finally:
        conn.close()


def record_process_event(
    device_serial: str,
    event_type: str,
    scan_count: int | None = None,
    uptime_seconds: float | None = None,
    exit_reason: str | None = None,
) -> None:
    conn = _get_connection()
    try:
        conn.execute(
            "INSERT INTO process_events (device_serial, event_type, scan_count, uptime_seconds, exit_reason) "
            "VALUES (?, ?, ?, ?, ?)",
            (device_serial, event_type, scan_count, uptime_seconds, exit_reason),
        )
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------
# Query helpers (called from the monitoring API)
# ------------------------------------------------------------------


def get_recent_heartbeats(
    device_serial: str | None = None,
    since: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return recent heartbeats, newest first."""
    conn = _get_connection()
    try:
        query = "SELECT * FROM heartbeats WHERE 1=1"
        params: list[Any] = []
        if device_serial:
            query += " AND device_serial = ?"
            params.append(device_serial)
        if since:
            query += " AND timestamp >= ?"
            params.append(since)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_latest_heartbeat_per_device() -> dict[str, dict[str, Any]]:
    """Return the most recent heartbeat for each device."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            """
            SELECT h.* FROM heartbeats h
            INNER JOIN (
                SELECT device_serial, MAX(timestamp) AS max_ts
                FROM heartbeats GROUP BY device_serial
            ) latest ON h.device_serial = latest.device_serial AND h.timestamp = latest.max_ts
            """
        ).fetchall()
        return {row["device_serial"]: dict(row) for row in rows}
    finally:
        conn.close()


def get_recent_ai_health(limit: int = 50) -> list[dict[str, Any]]:
    conn = _get_connection()
    try:
        rows = conn.execute("SELECT * FROM ai_health_checks ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_recent_process_events(device_serial: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    conn = _get_connection()
    try:
        query = "SELECT * FROM process_events WHERE 1=1"
        params: list[Any] = []
        if device_serial:
            query += " AND device_serial = ?"
            params.append(device_serial)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
