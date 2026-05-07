"""Repository for the ``messages`` table.

The dedupe story is owned by ``compute_message_hash``: persisting an
already-stored ``(conversation, direction, text, sent_at)`` tuple is a
no-op that returns the existing row id. This guards us against
re-parsing the same chat detail page repeatedly.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from boss_automation.database.schema import ensure_schema

_VALID_DIRECTIONS: Final[frozenset[str]] = frozenset({"in", "out"})
_VALID_CONTENT_TYPES: Final[frozenset[str]] = frozenset(
    {"text", "image", "resume", "exchange_request", "interview", "system", "voice", "file"}
)
_VALID_SENT_BY: Final[frozenset[str]] = frozenset({"manual", "auto", "template", "ai"})


@dataclass(frozen=True, slots=True)
class MessageRecord:
    id: int
    conversation_id: int
    direction: str
    content_type: str
    text: str | None
    sent_at_iso: str
    sent_by: str | None
    template_id: int | None
    message_hash: str


def compute_message_hash(
    *,
    conversation_id: int,
    direction: str,
    text: str | None,
    sent_at_iso: str,
) -> str:
    """SHA-256 hash of the natural identity tuple. Stable across runs."""
    payload = f"{conversation_id}|{direction}|{text or ''}|{sent_at_iso}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


class MessageRepository:
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

    def insert(
        self,
        *,
        conversation_id: int,
        direction: str,
        content_type: str,
        text: str | None,
        sent_at: datetime,
        sent_by: str | None = None,
        template_id: int | None = None,
        raw_payload: str | None = None,
    ) -> int:
        if direction not in _VALID_DIRECTIONS:
            raise ValueError(f"invalid direction {direction!r}; expected one of {sorted(_VALID_DIRECTIONS)}")
        if content_type not in _VALID_CONTENT_TYPES:
            raise ValueError(f"invalid content_type {content_type!r}; expected one of {sorted(_VALID_CONTENT_TYPES)}")
        if sent_by is not None and sent_by not in _VALID_SENT_BY:
            raise ValueError(f"invalid sent_by {sent_by!r}; expected one of {sorted(_VALID_SENT_BY)} or None")

        sent_at_iso = _normalize_iso(sent_at)
        msg_hash = compute_message_hash(
            conversation_id=conversation_id,
            direction=direction,
            text=text,
            sent_at_iso=sent_at_iso,
        )
        with self._connect() as conn:
            existing = conn.execute("SELECT id FROM messages WHERE message_hash = ?", (msg_hash,)).fetchone()
            if existing is not None:
                return int(existing["id"])
            cursor = conn.execute(
                """
                INSERT INTO messages
                    (conversation_id, direction, content_type, text, raw_payload,
                     sent_at, sent_by, template_id, message_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    direction,
                    content_type,
                    text,
                    raw_payload,
                    sent_at_iso,
                    sent_by,
                    template_id,
                    msg_hash,
                ),
            )
            assert cursor.lastrowid is not None
            return int(cursor.lastrowid)

    def list_for_conversation(self, conversation_id: int) -> list[MessageRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, conversation_id, direction, content_type, text,
                       sent_at, sent_by, template_id, message_hash
                FROM messages WHERE conversation_id = ?
                ORDER BY sent_at ASC, id ASC
                """,
                (conversation_id,),
            ).fetchall()
        return [
            MessageRecord(
                id=int(r["id"]),
                conversation_id=int(r["conversation_id"]),
                direction=r["direction"],
                content_type=r["content_type"],
                text=r["text"],
                sent_at_iso=r["sent_at"],
                sent_by=r["sent_by"],
                template_id=int(r["template_id"]) if r["template_id"] is not None else None,
                message_hash=r["message_hash"],
            )
            for r in rows
        ]
