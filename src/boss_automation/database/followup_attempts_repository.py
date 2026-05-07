"""Repository for the ``followup_attempts_v2`` table.

Append-only attempt history with a strict pending → sent / cancelled /
failed lifecycle. Once an attempt leaves ``pending`` it cannot
transition again, so the orchestrator must create a new row for any
retry.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from boss_automation.database.schema import ensure_schema

_VALID_STATUSES: Final[frozenset[str]] = frozenset({"pending", "sent", "cancelled", "failed"})


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    id: int
    candidate_id: int
    conversation_id: int | None
    scheduled_at_iso: str
    sent_at_iso: str | None
    status: str
    reason: str | None
    template_id: int | None


def _normalize_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


class FollowupAttemptsRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        ensure_schema(self._db_path)

    @property
    def db_path(self) -> str:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def append_pending(
        self,
        *,
        candidate_id: int,
        conversation_id: int | None,
        scheduled_at: datetime,
        template_id: int | None = None,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO followup_attempts_v2
                    (candidate_id, conversation_id, scheduled_at, template_id, status)
                VALUES (?, ?, ?, ?, 'pending')
                """,
                (
                    candidate_id,
                    conversation_id,
                    _normalize_iso(scheduled_at),
                    template_id,
                ),
            )
            assert cursor.lastrowid is not None
            return int(cursor.lastrowid)

    def mark_sent(self, attempt_id: int, *, sent_at: datetime) -> None:
        self._transition(attempt_id, "sent", reason=None, sent_at=sent_at)

    def mark_cancelled(self, attempt_id: int, *, reason: str) -> None:
        self._transition(attempt_id, "cancelled", reason=reason, sent_at=None)

    def mark_failed(self, attempt_id: int, *, reason: str) -> None:
        self._transition(attempt_id, "failed", reason=reason, sent_at=None)

    def _transition(
        self,
        attempt_id: int,
        new_status: str,
        *,
        reason: str | None,
        sent_at: datetime | None,
    ) -> None:
        if new_status not in _VALID_STATUSES:
            raise ValueError(f"invalid status {new_status!r}")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM followup_attempts_v2 WHERE id = ?",
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"no attempt with id {attempt_id}")
            current = row["status"]
            if current != "pending":
                raise ValueError(f"attempt {attempt_id} is {current!r}; cannot transition to {new_status!r}")
            conn.execute(
                """
                UPDATE followup_attempts_v2
                SET status = ?, reason = ?, sent_at = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    new_status,
                    reason,
                    _normalize_iso(sent_at) if sent_at else None,
                    attempt_id,
                ),
            )

    def get(self, attempt_id: int) -> AttemptRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, candidate_id, conversation_id, scheduled_at,
                       sent_at, status, reason, template_id
                FROM followup_attempts_v2 WHERE id = ?
                """,
                (attempt_id,),
            ).fetchone()
        return _to_record(row) if row else None

    def latest_for_candidate(self, candidate_id: int) -> AttemptRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, candidate_id, conversation_id, scheduled_at,
                       sent_at, status, reason, template_id
                FROM followup_attempts_v2
                WHERE candidate_id = ?
                ORDER BY scheduled_at DESC, id DESC LIMIT 1
                """,
                (candidate_id,),
            ).fetchone()
        return _to_record(row) if row else None

    def count_sent_in_range(self, *, recruiter_id: int, since: datetime, until: datetime) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM followup_attempts_v2 fa
                JOIN candidates c ON c.id = fa.candidate_id
                WHERE fa.status = 'sent'
                  AND fa.sent_at BETWEEN ? AND ?
                  AND c.recruiter_id = ?
                """,
                (
                    _normalize_iso(since),
                    _normalize_iso(until),
                    recruiter_id,
                ),
            ).fetchone()
        return int(row["n"]) if row else 0


def _to_record(row: sqlite3.Row) -> AttemptRecord:
    return AttemptRecord(
        id=int(row["id"]),
        candidate_id=int(row["candidate_id"]),
        conversation_id=(int(row["conversation_id"]) if row["conversation_id"] is not None else None),
        scheduled_at_iso=row["scheduled_at"],
        sent_at_iso=row["sent_at"],
        status=row["status"],
        reason=row["reason"],
        template_id=int(row["template_id"]) if row["template_id"] is not None else None,
    )
