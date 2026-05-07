"""Database schema for the BOSS Zhipin recruitment automation.

This module owns the SQLite schema for all BOSS-side business data:
recruiters, jobs, candidates, conversations, messages, greeting
templates, follow-up attempts, and job sync checkpoints.

Design notes
------------
- Schema lives separately from the WeCom legacy tables. Default DB path
  is `boss_recruitment.db` (override via env var ``BOSS_DB_PATH``) so
  legacy and new can coexist on disk without coupling.
- ``ensure_schema`` is idempotent. The migration policy mirrors the
  existing column-presence repair pattern in
  ``src/wecom_automation/database/schema.py`` so future schema bumps can
  add ``ALTER TABLE`` repairs without rewriting fresh-install SQL.
- Foreign keys are enabled on every connection that uses the BOSS DB.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Final

BOSS_SCHEMA_VERSION: Final[int] = 1

REQUIRED_TABLES: Final[frozenset[str]] = frozenset(
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

_SCHEMA_SQL: Final[str] = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS recruiters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_serial TEXT UNIQUE NOT NULL,
    name TEXT,
    company TEXT,
    position TEXT,
    avatar_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recruiter_id INTEGER NOT NULL REFERENCES recruiters(id) ON DELETE CASCADE,
    boss_job_id TEXT,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('open','closed','hidden','draft')),
    salary_min INTEGER,
    salary_max INTEGER,
    location TEXT,
    education TEXT,
    experience TEXT,
    last_seen_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(recruiter_id, boss_job_id)
);

CREATE TABLE IF NOT EXISTS greeting_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    scenario TEXT NOT NULL CHECK(scenario IN ('first_greet','reply','reengage')),
    content TEXT NOT NULL,
    variables_json TEXT,
    is_default BOOLEAN NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, scenario)
);

CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recruiter_id INTEGER NOT NULL REFERENCES recruiters(id) ON DELETE CASCADE,
    boss_candidate_id TEXT,
    name TEXT NOT NULL,
    age INTEGER,
    gender TEXT,
    current_company TEXT,
    current_position TEXT,
    education TEXT,
    experience TEXT,
    expected_salary TEXT,
    expected_location TEXT,
    resume_text TEXT,
    resume_screenshot_path TEXT,
    source_job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'new'
        CHECK(status IN ('new','greeted','replied','exchanged','interviewing','hired','rejected','silent','blocked')),
    last_active_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(recruiter_id, boss_candidate_id)
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recruiter_id INTEGER NOT NULL REFERENCES recruiters(id) ON DELETE CASCADE,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    last_message_at TIMESTAMP,
    last_direction TEXT CHECK(last_direction IN ('in','out')),
    unread_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(recruiter_id, candidate_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    direction TEXT NOT NULL CHECK(direction IN ('in','out')),
    content_type TEXT NOT NULL DEFAULT 'text'
        CHECK(content_type IN ('text','image','resume','exchange_request','interview','system','voice','file')),
    text TEXT,
    raw_payload TEXT,
    sent_at TIMESTAMP NOT NULL,
    sent_by TEXT CHECK(sent_by IN ('manual','auto','template','ai')),
    template_id INTEGER REFERENCES greeting_templates(id) ON DELETE SET NULL,
    message_hash TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS followup_attempts_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    scheduled_at TIMESTAMP NOT NULL,
    sent_at TIMESTAMP,
    template_id INTEGER REFERENCES greeting_templates(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending','sent','cancelled','failed')),
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS job_sync_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recruiter_id INTEGER NOT NULL REFERENCES recruiters(id) ON DELETE CASCADE,
    last_synced_at TIMESTAMP,
    last_cursor TEXT,
    payload_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(recruiter_id)
);

CREATE TABLE IF NOT EXISTS boss_schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

_INDEXES_SQL: Final[str] = """
CREATE INDEX IF NOT EXISTS idx_jobs_recruiter ON jobs(recruiter_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_candidates_recruiter ON candidates(recruiter_id);
CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status);
CREATE INDEX IF NOT EXISTS idx_candidates_source_job ON candidates(source_job_id);
CREATE INDEX IF NOT EXISTS idx_conversations_recruiter ON conversations(recruiter_id);
CREATE INDEX IF NOT EXISTS idx_conversations_candidate ON conversations(candidate_id);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_sent_at ON messages(sent_at);
CREATE INDEX IF NOT EXISTS idx_followup_status ON followup_attempts_v2(status);
CREATE INDEX IF NOT EXISTS idx_followup_scheduled ON followup_attempts_v2(scheduled_at);
"""

_TRIGGERS_SQL: Final[str] = """
CREATE TRIGGER IF NOT EXISTS update_recruiters_timestamp
AFTER UPDATE ON recruiters
BEGIN
    UPDATE recruiters SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_jobs_timestamp
AFTER UPDATE ON jobs
BEGIN
    UPDATE jobs SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_candidates_timestamp
AFTER UPDATE ON candidates
BEGIN
    UPDATE candidates SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_conversations_timestamp
AFTER UPDATE ON conversations
BEGIN
    UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_followup_v2_timestamp
AFTER UPDATE ON followup_attempts_v2
BEGIN
    UPDATE followup_attempts_v2 SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_job_sync_checkpoints_timestamp
AFTER UPDATE ON job_sync_checkpoints
BEGIN
    UPDATE job_sync_checkpoints SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
"""


def _connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a connection with foreign keys enabled."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _record_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO boss_schema_version (version) VALUES (?)",
        (version,),
    )


def ensure_schema(db_path: str | Path) -> None:
    """Create all BOSS tables on the given SQLite database (idempotent).

    Args:
        db_path: filesystem path or ``":memory:"``.

    Raises:
        sqlite3.Error: if SQLite reports a structural error.
    """
    conn = _connect(db_path)
    try:
        conn.executescript(_SCHEMA_SQL)
        conn.executescript(_INDEXES_SQL)
        conn.executescript(_TRIGGERS_SQL)
        _record_version(conn, BOSS_SCHEMA_VERSION)
        conn.commit()
    finally:
        conn.close()


def list_existing_tables(db_path: str | Path) -> set[str]:
    """Return the set of table names that exist on the given DB.

    Useful for migration tooling and for tests asserting the schema state.
    """
    conn = _connect(db_path)
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return {row[0] for row in cursor.fetchall()}
    finally:
        conn.close()


def missing_tables(db_path: str | Path) -> Iterable[str]:
    """Return the BOSS tables that are not yet present on the given DB."""
    return REQUIRED_TABLES - list_existing_tables(db_path)
