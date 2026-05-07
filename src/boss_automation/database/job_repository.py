"""Repository for the ``jobs`` table.

Owns persistence for ``Job`` records produced by
``boss_automation.parsers.job_list_parser.parse_job_list``. Uses SQLite
``ON CONFLICT`` upserts keyed on ``(recruiter_id, boss_job_id)`` so the
orchestrator can re-run sync without producing duplicate rows.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from boss_automation.database.schema import ensure_schema
from boss_automation.parsers.job_list_parser import Job, JobStatus


@dataclass(frozen=True, slots=True)
class JobRecord:
    id: int
    recruiter_id: int
    boss_job_id: str
    title: str
    status: JobStatus
    salary_min: int | None
    salary_max: int | None
    location: str | None
    education: str | None
    experience: str | None


class JobRepository:
    """CRUD operations for jobs scoped to a recruiter."""

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

    def upsert(self, recruiter_id: int, job: Job) -> int:
        """Insert or update a single job. Returns the row id."""
        with self._connect() as conn:
            return self._upsert_one(conn, recruiter_id, job)

    def upsert_many(self, recruiter_id: int, jobs: Iterable[Job]) -> list[int]:
        """Bulk upsert; preserves input order and returns row ids."""
        result: list[int] = []
        with self._connect() as conn:
            for job in jobs:
                result.append(self._upsert_one(conn, recruiter_id, job))
        return result

    def _upsert_one(self, conn: sqlite3.Connection, recruiter_id: int, job: Job) -> int:
        cursor = conn.execute(
            """
            INSERT INTO jobs (
                recruiter_id, boss_job_id, title, status,
                salary_min, salary_max, location, education, experience,
                last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(recruiter_id, boss_job_id) DO UPDATE SET
                title = excluded.title,
                status = excluded.status,
                salary_min = excluded.salary_min,
                salary_max = excluded.salary_max,
                location = excluded.location,
                education = excluded.education,
                experience = excluded.experience,
                last_seen_at = CURRENT_TIMESTAMP
            """,
            (
                recruiter_id,
                job.boss_job_id,
                job.title,
                job.status.value,
                job.salary_min,
                job.salary_max,
                job.location,
                job.education,
                job.experience,
            ),
        )
        if cursor.lastrowid:
            return int(cursor.lastrowid)
        row = conn.execute(
            "SELECT id FROM jobs WHERE recruiter_id = ? AND boss_job_id = ?",
            (recruiter_id, job.boss_job_id),
        ).fetchone()
        return int(row["id"])

    def list_for_recruiter(
        self,
        recruiter_id: int,
        *,
        status: JobStatus | None = None,
    ) -> list[JobRecord]:
        sql = (
            "SELECT id, recruiter_id, boss_job_id, title, status, "
            "salary_min, salary_max, location, education, experience "
            "FROM jobs WHERE recruiter_id = ?"
        )
        params: list[object] = [recruiter_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status.value)
        sql += " ORDER BY id ASC"

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_record(r) for r in rows]

    def get_by_boss_job_id(
        self,
        recruiter_id: int,
        boss_job_id: str,
    ) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, recruiter_id, boss_job_id, title, status,
                       salary_min, salary_max, location, education, experience
                FROM jobs WHERE recruiter_id = ? AND boss_job_id = ?
                """,
                (recruiter_id, boss_job_id),
            ).fetchone()
        return None if row is None else _row_to_record(row)


def _row_to_record(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        id=int(row["id"]),
        recruiter_id=int(row["recruiter_id"]),
        boss_job_id=row["boss_job_id"],
        title=row["title"],
        status=JobStatus(row["status"]),
        salary_min=row["salary_min"],
        salary_max=row["salary_max"],
        location=row["location"],
        education=row["education"],
        experience=row["experience"],
    )
