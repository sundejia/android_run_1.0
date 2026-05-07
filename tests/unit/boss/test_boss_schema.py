"""TDD tests for src/boss_automation/database/schema.py.

These tests pin the M0 contract:
- ensure_schema(db_path) creates all required BOSS tables.
- The function is idempotent (running it twice is a no-op).
- A boss_schema_version row is recorded.
- All check constraints reject invalid enum values.

These tests intentionally have no dependency on a real Android device.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from boss_automation.database.schema import (
    BOSS_SCHEMA_VERSION,
    REQUIRED_TABLES,
    ensure_schema,
    list_existing_tables,
    missing_tables,
)


def _list_tables(conn: sqlite3.Connection) -> set[str]:
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return {row[0] for row in cursor.fetchall()}


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "boss_test.db")


class TestEnsureSchemaCreatesAllTables:
    def test_required_tables_constant_lists_eight_business_tables(self) -> None:
        # Pinning the contract; if we add tables, this test must change first.
        assert REQUIRED_TABLES == frozenset(
            {
                "recruiters",
                "jobs",
                "candidates",
                "conversations",
                "messages",
                "greeting_templates",
                "followup_attempts_v2",
                "job_sync_checkpoints",
            }
        )

    def test_creates_all_required_tables(self, db_path: str) -> None:
        ensure_schema(db_path)
        with sqlite3.connect(db_path) as conn:
            tables = _list_tables(conn)
        missing = REQUIRED_TABLES - tables
        assert not missing, f"missing tables: {missing}"

    def test_creates_version_table_and_records_current_version(self, db_path: str) -> None:
        ensure_schema(db_path)
        with sqlite3.connect(db_path) as conn:
            tables = _list_tables(conn)
            assert "boss_schema_version" in tables
            row = conn.execute("SELECT version FROM boss_schema_version ORDER BY version DESC LIMIT 1").fetchone()
        assert row is not None
        assert row[0] == BOSS_SCHEMA_VERSION

    def test_supports_in_memory_database(self) -> None:
        ensure_schema(":memory:")  # must not raise


class TestEnsureSchemaIdempotency:
    def test_running_twice_does_not_error(self, db_path: str) -> None:
        ensure_schema(db_path)
        ensure_schema(db_path)  # second call must be a no-op

    def test_running_twice_does_not_duplicate_version_row(self, db_path: str) -> None:
        ensure_schema(db_path)
        ensure_schema(db_path)
        with sqlite3.connect(db_path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM boss_schema_version WHERE version = ?",
                (BOSS_SCHEMA_VERSION,),
            ).fetchone()[0]
        assert count == 1


class TestSchemaCheckConstraints:
    def _setup_recruiter_and_job(self, conn: sqlite3.Connection) -> tuple[int, int]:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO recruiters (device_serial, name) VALUES (?, ?)",
            ("EMU-1", "Test Recruiter"),
        )
        recruiter_id = conn.execute("SELECT id FROM recruiters WHERE device_serial = ?", ("EMU-1",)).fetchone()[0]
        conn.execute(
            "INSERT INTO jobs (recruiter_id, title, status) VALUES (?, ?, ?)",
            (recruiter_id, "Senior Engineer", "open"),
        )
        job_id = conn.execute("SELECT id FROM jobs WHERE title = ?", ("Senior Engineer",)).fetchone()[0]
        return recruiter_id, job_id

    def test_jobs_status_rejects_invalid_value(self, db_path: str) -> None:
        ensure_schema(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO recruiters (device_serial, name) VALUES (?, ?)",
                ("EMU-1", "X"),
            )
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO jobs (recruiter_id, title, status) VALUES (?, ?, ?)",
                    (1, "Job", "deleted"),
                )

    def test_candidates_status_default_is_new(self, db_path: str) -> None:
        ensure_schema(db_path)
        with sqlite3.connect(db_path) as conn:
            self._setup_recruiter_and_job(conn)
            conn.execute(
                "INSERT INTO candidates (recruiter_id, name) VALUES (?, ?)",
                (1, "Alice"),
            )
            status = conn.execute("SELECT status FROM candidates WHERE name = ?", ("Alice",)).fetchone()[0]
        assert status == "new"

    def test_messages_direction_check_constraint(self, db_path: str) -> None:
        ensure_schema(db_path)
        with sqlite3.connect(db_path) as conn:
            self._setup_recruiter_and_job(conn)
            conn.execute(
                "INSERT INTO candidates (recruiter_id, name) VALUES (?, ?)",
                (1, "Bob"),
            )
            conn.execute(
                "INSERT INTO conversations (recruiter_id, candidate_id) VALUES (?, ?)",
                (1, 1),
            )
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO messages
                        (conversation_id, direction, content_type, sent_at, message_hash)
                    VALUES (?, ?, ?, datetime('now'), ?)
                    """,
                    (1, "sideways", "text", "hash-1"),
                )

    def test_messages_message_hash_must_be_unique(self, db_path: str) -> None:
        ensure_schema(db_path)
        with sqlite3.connect(db_path) as conn:
            self._setup_recruiter_and_job(conn)
            conn.execute(
                "INSERT INTO candidates (recruiter_id, name) VALUES (?, ?)",
                (1, "Bob"),
            )
            conn.execute(
                "INSERT INTO conversations (recruiter_id, candidate_id) VALUES (?, ?)",
                (1, 1),
            )
            conn.execute(
                """
                INSERT INTO messages
                    (conversation_id, direction, content_type, sent_at, message_hash)
                VALUES (?, ?, ?, datetime('now'), ?)
                """,
                (1, "in", "text", "hash-dup"),
            )
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO messages
                        (conversation_id, direction, content_type, sent_at, message_hash)
                    VALUES (?, ?, ?, datetime('now'), ?)
                    """,
                    (1, "out", "text", "hash-dup"),
                )

    def test_greeting_templates_scenario_check_constraint(self, db_path: str) -> None:
        ensure_schema(db_path)
        with sqlite3.connect(db_path) as conn:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO greeting_templates (name, scenario, content) VALUES (?, ?, ?)",
                    ("BadOne", "totally_invalid_scenario", "hi"),
                )
            conn.execute(
                "INSERT INTO greeting_templates (name, scenario, content) VALUES (?, ?, ?)",
                ("Greet", "first_greet", "Hello {name}"),
            )

    def test_recruiter_uniqueness_on_device_serial(self, db_path: str) -> None:
        ensure_schema(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO recruiters (device_serial, name) VALUES (?, ?)",
                ("EMU-1", "Alice"),
            )
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO recruiters (device_serial, name) VALUES (?, ?)",
                    ("EMU-1", "Bob"),
                )


class TestForeignKeyCascades:
    def test_deleting_recruiter_cascades_jobs(self, db_path: str) -> None:
        ensure_schema(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                "INSERT INTO recruiters (device_serial, name) VALUES (?, ?)",
                ("EMU-X", "Z"),
            )
            conn.execute(
                "INSERT INTO jobs (recruiter_id, title, status) VALUES (?, ?, ?)",
                (1, "T", "open"),
            )
            conn.execute("DELETE FROM recruiters WHERE id = 1")
            count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        assert count == 0


class TestSchemaIntrospectionHelpers:
    def test_list_existing_tables_returns_required_tables_after_ensure(
        self, db_path: str
    ) -> None:
        ensure_schema(db_path)
        tables = list_existing_tables(db_path)
        assert REQUIRED_TABLES.issubset(tables)
        assert "boss_schema_version" in tables

    def test_list_existing_tables_returns_empty_for_fresh_db(self, db_path: str) -> None:
        # Touch the file so sqlite can open it but do NOT run ensure_schema.
        Path(db_path).touch()
        tables = list_existing_tables(db_path)
        assert REQUIRED_TABLES.isdisjoint(tables)

    def test_missing_tables_returns_full_set_for_fresh_db(self, db_path: str) -> None:
        Path(db_path).touch()
        missing = set(missing_tables(db_path))
        assert missing == set(REQUIRED_TABLES)

    def test_missing_tables_is_empty_after_ensure_schema(self, db_path: str) -> None:
        ensure_schema(db_path)
        missing = set(missing_tables(db_path))
        assert missing == set()
