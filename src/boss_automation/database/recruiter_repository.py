"""Repository for the ``recruiters`` table.

Single responsibility: persist and retrieve ``RecruiterProfile`` data
for a given Android device. Auto-ensures the BOSS schema on
construction so callers cannot accidentally hit a fresh empty database.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from boss_automation.database.schema import ensure_schema
from boss_automation.parsers.recruiter_profile_parser import RecruiterProfile


@dataclass(frozen=True, slots=True)
class RecruiterRecord:
    id: int
    device_serial: str
    name: str | None
    company: str | None
    position: str | None
    avatar_path: str | None


class RecruiterRepository:
    """Read/write API for recruiters bound to specific Android devices."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        ensure_schema(self._db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def upsert(self, device_serial: str, profile: RecruiterProfile) -> int:
        """Insert or update the recruiter row for the given device.

        Returns the row id of the (possibly pre-existing) row.
        """
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO recruiters
                    (device_serial, name, company, position, avatar_path)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(device_serial) DO UPDATE SET
                    name = excluded.name,
                    company = excluded.company,
                    position = excluded.position,
                    avatar_path = excluded.avatar_path,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    device_serial,
                    profile.name,
                    profile.company,
                    profile.position,
                    profile.avatar_path,
                ),
            )
            if cursor.lastrowid:
                return int(cursor.lastrowid)
            row = conn.execute(
                "SELECT id FROM recruiters WHERE device_serial = ?",
                (device_serial,),
            ).fetchone()
            return int(row[0])

    def get_by_serial(self, device_serial: str) -> RecruiterRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, device_serial, name, company, position, avatar_path
                FROM recruiters WHERE device_serial = ?
                """,
                (device_serial,),
            ).fetchone()
        if row is None:
            return None
        return RecruiterRecord(
            id=int(row["id"]),
            device_serial=row["device_serial"],
            name=row["name"],
            company=row["company"],
            position=row["position"],
            avatar_path=row["avatar_path"],
        )

    def list_all(self) -> list[RecruiterRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, device_serial, name, company, position, avatar_path
                FROM recruiters
                ORDER BY device_serial ASC
                """
            ).fetchall()
        return [
            RecruiterRecord(
                id=int(r["id"]),
                device_serial=r["device_serial"],
                name=r["name"],
                company=r["company"],
                position=r["position"],
                avatar_path=r["avatar_path"],
            )
            for r in rows
        ]
