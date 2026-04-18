"""
Log upload repository.

Stores upload runs and per-file upload results in the local SQLite database.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Generator


class LogUploadRepository:
    """Persist upload runs and uploaded file metadata."""

    SCHEMA_RUNS = """
    CREATE TABLE IF NOT EXISTS log_upload_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trigger_source TEXT NOT NULL,
        status TEXT NOT NULL,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        files_total INTEGER DEFAULT 0,
        files_uploaded INTEGER DEFAULT 0,
        files_skipped INTEGER DEFAULT 0,
        error_message TEXT,
        details_json TEXT
    );
    """

    SCHEMA_FILES = """
    CREATE TABLE IF NOT EXISTS log_upload_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hostname TEXT NOT NULL,
        upload_kind TEXT NOT NULL,
        original_filename TEXT NOT NULL,
        file_path TEXT NOT NULL,
        checksum TEXT NOT NULL,
        file_size INTEGER NOT NULL,
        mtime REAL NOT NULL,
        status TEXT NOT NULL,
        uploaded_at TEXT,
        last_error TEXT,
        response_json TEXT,
        run_id INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(hostname, upload_kind, original_filename, checksum)
    );
    """

    SCHEMA_INDEXES = """
    CREATE INDEX IF NOT EXISTS idx_log_upload_runs_started_at
    ON log_upload_runs(started_at);
    CREATE INDEX IF NOT EXISTS idx_log_upload_runs_trigger_source
    ON log_upload_runs(trigger_source);
    CREATE INDEX IF NOT EXISTS idx_log_upload_files_lookup
    ON log_upload_files(hostname, upload_kind, original_filename, checksum);
    CREATE INDEX IF NOT EXISTS idx_log_upload_files_status
    ON log_upload_files(status);
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._ensure_tables()

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        from services.conversation_storage import open_shared_sqlite

        conn = open_shared_sqlite(str(self._db_path), row_factory=True)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_tables(self) -> None:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.executescript(self.SCHEMA_RUNS)
            cursor.executescript(self.SCHEMA_FILES)
            cursor.executescript(self.SCHEMA_INDEXES)
            conn.commit()

    def start_run(self, trigger_source: str, started_at: datetime) -> int:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO log_upload_runs (
                    trigger_source,
                    status,
                    started_at
                ) VALUES (?, ?, ?)
                """,
                (trigger_source, "running", started_at.isoformat()),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: int,
        *,
        status: str,
        completed_at: datetime,
        files_total: int,
        files_uploaded: int,
        files_skipped: int,
        error_message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE log_upload_runs
                SET status = ?,
                    completed_at = ?,
                    files_total = ?,
                    files_uploaded = ?,
                    files_skipped = ?,
                    error_message = ?,
                    details_json = ?
                WHERE id = ?
                """,
                (
                    status,
                    completed_at.isoformat(),
                    files_total,
                    files_uploaded,
                    files_skipped,
                    error_message,
                    json.dumps(details, ensure_ascii=False) if details else None,
                    run_id,
                ),
            )
            conn.commit()

    def upsert_file_result(
        self,
        *,
        hostname: str,
        upload_kind: str,
        original_filename: str,
        file_path: str,
        checksum: str,
        file_size: int,
        mtime: float,
        status: str,
        uploaded_at: datetime | None,
        run_id: int | None,
        last_error: str | None = None,
        response: dict[str, Any] | None = None,
    ) -> None:
        payload = (
            hostname,
            upload_kind,
            original_filename,
            file_path,
            checksum,
            file_size,
            mtime,
            status,
            uploaded_at.isoformat() if uploaded_at else None,
            last_error,
            json.dumps(response, ensure_ascii=False) if response else None,
            run_id,
        )
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO log_upload_files (
                    hostname,
                    upload_kind,
                    original_filename,
                    file_path,
                    checksum,
                    file_size,
                    mtime,
                    status,
                    uploaded_at,
                    last_error,
                    response_json,
                    run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(hostname, upload_kind, original_filename, checksum)
                DO UPDATE SET
                    file_path = excluded.file_path,
                    file_size = excluded.file_size,
                    mtime = excluded.mtime,
                    status = excluded.status,
                    uploaded_at = excluded.uploaded_at,
                    last_error = excluded.last_error,
                    response_json = excluded.response_json,
                    run_id = excluded.run_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                payload,
            )
            conn.commit()

    def has_successful_upload(
        self,
        *,
        hostname: str,
        upload_kind: str,
        original_filename: str,
        checksum: str,
    ) -> bool:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT 1
                FROM log_upload_files
                WHERE hostname = ?
                  AND upload_kind = ?
                  AND original_filename = ?
                  AND checksum = ?
                  AND status = 'success'
                LIMIT 1
                """,
                (hostname, upload_kind, original_filename, checksum),
            )
            return cursor.fetchone() is not None

    def get_last_run(self, trigger_source: str | None = None) -> dict[str, Any] | None:
        query = """
            SELECT *
            FROM log_upload_runs
        """
        params: tuple[Any, ...] = ()
        if trigger_source:
            query += " WHERE trigger_source = ?"
            params = (trigger_source,)
        query += " ORDER BY started_at DESC LIMIT 1"

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            row = cursor.fetchone()
            if row is None:
                return None
            result = dict(row)
            if result.get("details_json"):
                result["details"] = json.loads(result["details_json"])
            else:
                result["details"] = None
            result.pop("details_json", None)
            return result
