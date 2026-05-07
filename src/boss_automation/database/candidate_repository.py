"""Repository for the ``candidates`` table.

Persists ``CandidateCard`` snapshots from the recommended-candidates
feed and tracks per-candidate lifecycle status (``new``, ``greeted``,
``replied``, etc.). Identity is ``(recruiter_id, boss_candidate_id)``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from boss_automation.database.schema import ensure_schema
from boss_automation.parsers.candidate_card_parser import CandidateCard

_VALID_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "new",
        "greeted",
        "replied",
        "exchanged",
        "interviewing",
        "hired",
        "rejected",
        "silent",
        "blocked",
    }
)


@dataclass(frozen=True, slots=True)
class CandidateRecord:
    id: int
    recruiter_id: int
    boss_candidate_id: str
    name: str
    age: int | None
    gender: str | None
    education: str | None
    experience: str | None
    current_company: str | None
    current_position: str | None
    status: str


class CandidateRepository:
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

    def upsert_from_card(self, recruiter_id: int, card: CandidateCard) -> int:
        experience = f"{card.experience_years}年" if card.experience_years is not None else None
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO candidates (
                    recruiter_id, boss_candidate_id, name, age, gender,
                    current_company, current_position, education, experience
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(recruiter_id, boss_candidate_id) DO UPDATE SET
                    name = excluded.name,
                    age = excluded.age,
                    gender = excluded.gender,
                    current_company = excluded.current_company,
                    current_position = excluded.current_position,
                    education = excluded.education,
                    experience = excluded.experience,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    recruiter_id,
                    card.boss_candidate_id,
                    card.name,
                    card.age,
                    card.gender,
                    card.current_company,
                    card.current_position,
                    card.education,
                    experience,
                ),
            )
            if cursor.lastrowid:
                return int(cursor.lastrowid)
            row = conn.execute(
                "SELECT id FROM candidates WHERE recruiter_id = ? AND boss_candidate_id = ?",
                (recruiter_id, card.boss_candidate_id),
            ).fetchone()
            return int(row["id"])

    def set_status(self, recruiter_id: int, boss_candidate_id: str, status: str) -> None:
        if status not in _VALID_STATUSES:
            raise ValueError(f"invalid status {status!r}; expected one of {sorted(_VALID_STATUSES)}")
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE candidates SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE recruiter_id = ? AND boss_candidate_id = ?
                """,
                (status, recruiter_id, boss_candidate_id),
            )

    def get_by_boss_candidate_id(self, recruiter_id: int, boss_candidate_id: str) -> CandidateRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, recruiter_id, boss_candidate_id, name, age, gender,
                       education, experience, current_company, current_position, status
                FROM candidates WHERE recruiter_id = ? AND boss_candidate_id = ?
                """,
                (recruiter_id, boss_candidate_id),
            ).fetchone()
        return None if row is None else _row_to_record(row)

    def list_for_recruiter(self, recruiter_id: int) -> list[CandidateRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, recruiter_id, boss_candidate_id, name, age, gender,
                       education, experience, current_company, current_position, status
                FROM candidates WHERE recruiter_id = ? ORDER BY id ASC
                """,
                (recruiter_id,),
            ).fetchall()
        return [_row_to_record(r) for r in rows]

    def count_by_status(self, recruiter_id: int) -> Mapping[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS n FROM candidates
                WHERE recruiter_id = ? GROUP BY status
                """,
                (recruiter_id,),
            ).fetchall()
        return {row["status"]: int(row["n"]) for row in rows}


def _row_to_record(row: sqlite3.Row) -> CandidateRecord:
    return CandidateRecord(
        id=int(row["id"]),
        recruiter_id=int(row["recruiter_id"]),
        boss_candidate_id=row["boss_candidate_id"],
        name=row["name"],
        age=row["age"],
        gender=row["gender"],
        education=row["education"],
        experience=row["experience"],
        current_company=row["current_company"],
        current_position=row["current_position"],
        status=row["status"],
    )
