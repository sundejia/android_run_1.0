"""SQLite-backed storage for review-gating tables.

All access goes through ``ReviewStorage`` which holds the path to the same
SQLite DB used by the rest of android_run (the ``wecom_conversations.db``).
Methods are synchronous because callers always wrap them in
``asyncio.to_thread`` when running inside an async context — keeping the
storage layer thread-safe and easy to unit-test.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PendingReviewRow:
    message_id: int
    customer_id: int | None
    customer_name: str | None
    device_serial: str | None
    channel: str | None
    kefu_name: str | None
    image_path: str
    status: str = "pending"
    attempts: int = 0
    created_at: str | None = None
    expires_at: str | None = None
    last_error: str | None = None


@dataclass
class ReviewVerdictRow:
    message_id: int
    image_id: str | None
    decision: str
    is_portrait: bool
    is_real_person: bool
    face_visible: bool
    final_score: float | None
    raw_payload_json: str | None
    prompt_version_id: str | None
    skill_version: str | None
    received_at: str


@dataclass
class AnalyticsEventRow:
    id: int
    ts: str
    event_type: str
    trace_id: str | None
    payload: dict[str, Any] = field(default_factory=dict)


class ReviewStorage:
    """Synchronous facade over the review tables."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    # ---- pending_reviews -------------------------------------------------

    def insert_pending_review(self, row: PendingReviewRow) -> None:
        created_at = row.created_at or _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO pending_reviews (
                    message_id, customer_id, customer_name, device_serial,
                    channel, kefu_name, image_path, status, attempts,
                    created_at, expires_at, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.message_id,
                    row.customer_id,
                    row.customer_name,
                    row.device_serial,
                    row.channel,
                    row.kefu_name,
                    row.image_path,
                    row.status,
                    row.attempts,
                    created_at,
                    row.expires_at,
                    row.last_error,
                ),
            )

    def get_pending_review(self, message_id: int) -> PendingReviewRow | None:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM pending_reviews WHERE message_id = ?",
                (message_id,),
            )
            r = cur.fetchone()
        if r is None:
            return None
        return PendingReviewRow(
            message_id=r["message_id"],
            customer_id=r["customer_id"],
            customer_name=r["customer_name"],
            device_serial=r["device_serial"],
            channel=r["channel"],
            kefu_name=r["kefu_name"],
            image_path=r["image_path"],
            status=r["status"],
            attempts=int(r["attempts"]),
            created_at=r["created_at"],
            expires_at=r["expires_at"],
            last_error=r["last_error"],
        )

    def list_pending_reviews(self, status: str | None = None) -> list[PendingReviewRow]:
        with self._connect() as conn:
            if status is None:
                cur = conn.execute(
                    "SELECT * FROM pending_reviews ORDER BY created_at ASC"
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM pending_reviews WHERE status = ? ORDER BY created_at ASC",
                    (status,),
                )
            rows = cur.fetchall()
        return [
            PendingReviewRow(
                message_id=r["message_id"],
                customer_id=r["customer_id"],
                customer_name=r["customer_name"],
                device_serial=r["device_serial"],
                channel=r["channel"],
                kefu_name=r["kefu_name"],
                image_path=r["image_path"],
                status=r["status"],
                attempts=int(r["attempts"]),
                created_at=r["created_at"],
                expires_at=r["expires_at"],
                last_error=r["last_error"],
            )
            for r in rows
        ]

    def mark_pending_status(
        self, message_id: int, status: str, last_error: str | None = None
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE pending_reviews SET status = ?, last_error = COALESCE(?, last_error) "
                "WHERE message_id = ?",
                (status, last_error, message_id),
            )

    def increment_attempts(
        self, message_id: int, last_error: str | None = None
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE pending_reviews SET attempts = attempts + 1, "
                "last_error = COALESCE(?, last_error) "
                "WHERE message_id = ?",
                (last_error, message_id),
            )

    # ---- review_verdicts -------------------------------------------------

    def upsert_verdict(self, v: ReviewVerdictRow) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO review_verdicts (
                    message_id, image_id, decision, is_portrait,
                    is_real_person, face_visible, final_score,
                    raw_payload_json, prompt_version_id, skill_version,
                    received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    image_id = excluded.image_id,
                    decision = excluded.decision,
                    is_portrait = excluded.is_portrait,
                    is_real_person = excluded.is_real_person,
                    face_visible = excluded.face_visible,
                    final_score = excluded.final_score,
                    raw_payload_json = excluded.raw_payload_json,
                    prompt_version_id = excluded.prompt_version_id,
                    skill_version = excluded.skill_version,
                    received_at = excluded.received_at
                """,
                (
                    v.message_id,
                    v.image_id,
                    v.decision,
                    1 if v.is_portrait else 0,
                    1 if v.is_real_person else 0,
                    1 if v.face_visible else 0,
                    v.final_score,
                    v.raw_payload_json,
                    v.prompt_version_id,
                    v.skill_version,
                    v.received_at,
                ),
            )

    def get_verdict(self, message_id: int) -> ReviewVerdictRow | None:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM review_verdicts WHERE message_id = ?",
                (message_id,),
            )
            r = cur.fetchone()
        if r is None:
            return None
        return ReviewVerdictRow(
            message_id=r["message_id"],
            image_id=r["image_id"],
            decision=r["decision"],
            is_portrait=bool(r["is_portrait"]),
            is_real_person=bool(r["is_real_person"]),
            face_visible=bool(r["face_visible"]),
            final_score=r["final_score"],
            raw_payload_json=r["raw_payload_json"],
            prompt_version_id=r["prompt_version_id"],
            skill_version=r["skill_version"],
            received_at=r["received_at"],
        )

    # ---- webhook_idempotency --------------------------------------------

    def try_register_idempotency_key(self, key: str, received_at: str) -> bool:
        """Atomically claim an idempotency key.

        Returns ``True`` when this is the first time we've seen ``key`` and
        therefore should process the request; ``False`` if it's a replay.
        """
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO webhook_idempotency (idempotency_key, received_at) "
                "VALUES (?, ?)",
                (key, received_at),
            )
            return cur.rowcount == 1

    def purge_old_idempotency(self, before_iso: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM webhook_idempotency WHERE received_at < ?",
                (before_iso,),
            )
            return cur.rowcount

    # ---- analytics_events -----------------------------------------------

    def record_event(
        self,
        event_type: str,
        *,
        trace_id: str | None = None,
        payload: dict[str, Any] | None = None,
        ts: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO analytics_events (ts, event_type, trace_id, payload_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    ts or _now_iso(),
                    event_type,
                    trace_id,
                    json.dumps(payload or {}, ensure_ascii=False, default=str),
                ),
            )

    def list_events(
        self,
        *,
        event_type: str | None = None,
        trace_id: str | None = None,
        limit: int = 200,
    ) -> list[AnalyticsEventRow]:
        sql = "SELECT * FROM analytics_events WHERE 1=1"
        args: list[Any] = []
        if event_type is not None:
            sql += " AND event_type = ?"
            args.append(event_type)
        if trace_id is not None:
            sql += " AND trace_id = ?"
            args.append(trace_id)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(max(1, min(int(limit), 1000)))

        with self._connect() as conn:
            cur = conn.execute(sql, args)
            rows = cur.fetchall()

        out: list[AnalyticsEventRow] = []
        for r in rows:
            try:
                payload = json.loads(r["payload_json"] or "{}")
            except (TypeError, ValueError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            out.append(
                AnalyticsEventRow(
                    id=int(r["id"]),
                    ts=r["ts"],
                    event_type=r["event_type"],
                    trace_id=r["trace_id"],
                    payload=payload,
                )
            )
        return out
