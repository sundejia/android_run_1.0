"""Repository for the ``conversations`` table.

A conversation is a 1:1 mapping between a recruiter and a candidate.
The unique constraint ``(recruiter_id, candidate_id)`` guarantees that
``upsert`` always converges to a single row even if the messages list
is re-parsed many times.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from boss_automation.database.schema import ensure_schema

_VALID_DIRECTIONS: Final[frozenset[str]] = frozenset({"in", "out"})


@dataclass(frozen=True, slots=True)
class ConversationRecord:
    id: int
    recruiter_id: int
    candidate_id: int
    job_id: int | None
    unread_count: int
    last_direction: str | None


class ConversationRepository:
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

    def upsert(
        self,
        *,
        recruiter_id: int,
        candidate_id: int,
        job_id: int | None = None,
        unread_count: int = 0,
        last_direction: str | None = None,
    ) -> int:
        if last_direction is not None and last_direction not in _VALID_DIRECTIONS:
            raise ValueError(f"invalid direction {last_direction!r}; expected 'in'|'out'|None")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO conversations
                    (recruiter_id, candidate_id, job_id, unread_count, last_direction)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(recruiter_id, candidate_id) DO UPDATE SET
                    job_id = COALESCE(excluded.job_id, conversations.job_id),
                    unread_count = excluded.unread_count,
                    last_direction = COALESCE(excluded.last_direction, conversations.last_direction),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    recruiter_id,
                    candidate_id,
                    job_id,
                    unread_count,
                    last_direction,
                ),
            )
            if cursor.lastrowid:
                return int(cursor.lastrowid)
            row = conn.execute(
                "SELECT id FROM conversations WHERE recruiter_id = ? AND candidate_id = ?",
                (recruiter_id, candidate_id),
            ).fetchone()
            return int(row["id"])

    def get(self, conversation_id: int) -> ConversationRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, recruiter_id, candidate_id, job_id, unread_count, last_direction
                FROM conversations WHERE id = ?
                """,
                (conversation_id,),
            ).fetchone()
        return _to_record(row) if row else None

    def get_by_candidate(self, recruiter_id: int, candidate_id: int) -> ConversationRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, recruiter_id, candidate_id, job_id, unread_count, last_direction
                FROM conversations WHERE recruiter_id = ? AND candidate_id = ?
                """,
                (recruiter_id, candidate_id),
            ).fetchone()
        return _to_record(row) if row else None

    def list_for_recruiter(self, recruiter_id: int) -> list[ConversationRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, recruiter_id, candidate_id, job_id, unread_count, last_direction
                FROM conversations WHERE recruiter_id = ?
                ORDER BY updated_at DESC, id DESC
                """,
                (recruiter_id,),
            ).fetchall()
        return [_to_record(r) for r in rows]


def _to_record(row: sqlite3.Row) -> ConversationRecord:
    return ConversationRecord(
        id=int(row["id"]),
        recruiter_id=int(row["recruiter_id"]),
        candidate_id=int(row["candidate_id"]),
        job_id=int(row["job_id"]) if row["job_id"] is not None else None,
        unread_count=int(row["unread_count"]),
        last_direction=row["last_direction"],
    )
