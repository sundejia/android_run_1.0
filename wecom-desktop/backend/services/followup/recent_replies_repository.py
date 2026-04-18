"""
Cross-device recent replies dedup repository.

When two phones service the same WeCom workspace, both `realtime_reply_process`
instances can pick up the same customer message at roughly the same time and
each generate + enqueue a reply. The result is a duplicate reply landing in the
customer's chat from two different agent accounts within seconds of each other.

This repository persists a tiny rolling table on the *shared control DB* so any
process can claim "I'm replying to (customer, message_hash) right now" before
spending sidecar/AI cycles. The first writer wins; the second sees the row and
skips. Entries older than the configured window are ignored on read and lazily
pruned on write.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
from dataclasses import dataclass

from services.conversation_storage import get_control_db_path, open_shared_sqlite

logger = logging.getLogger("followup.recent_replies_repository")

DEFAULT_DEDUP_WINDOW_SECONDS = 60
# Trim the table when it grows past this many rows to keep lookups cheap.
_MAX_RETENTION_ROWS = 2000


def hash_message(message: str | None) -> str:
    """Deterministic short hash for a customer/agent message body.

    Truncates to 16 hex chars (64 bits) — collision risk is negligible for the
    deduplication window (a single minute of activity across all devices).
    """
    payload = (message or "").strip()
    return hashlib.sha1(payload.encode("utf-8", errors="replace")).hexdigest()[:16]


def make_customer_key(customer_name: str, customer_channel: str | None) -> str:
    """Stable cross-device key for a customer.

    Uses ``name|channel`` so the same display name on different channels is
    not collapsed. Channel is normalised to empty string when absent so two
    devices computing the key agree even when only one has the channel.
    """
    return f"{(customer_name or '').strip()}|{(customer_channel or '').strip()}"


@dataclass
class RecentReplyRecord:
    customer_key: str
    message_hash: str
    sent_at: float
    device_serial: str


class RecentRepliesRepository:
    """Tiny shared table acting as a TTL-bounded dedup set."""

    def __init__(self, db_path: str | None = None):
        self._db_path = str(db_path or get_control_db_path())
        self._ensure_table()

    def _ensure_table(self) -> None:
        try:
            with open_shared_sqlite(self._db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS recent_replies (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        customer_key TEXT NOT NULL,
                        message_hash TEXT NOT NULL,
                        sent_at REAL NOT NULL,
                        device_serial TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_recent_replies_lookup
                    ON recent_replies(customer_key, message_hash, sent_at)
                    """
                )
                conn.commit()
        except sqlite3.DatabaseError as exc:
            logger.warning("recent_replies table init failed: %s", exc)

    def find_recent(
        self,
        customer_key: str,
        message_hash: str,
        *,
        window_seconds: float = DEFAULT_DEDUP_WINDOW_SECONDS,
    ) -> RecentReplyRecord | None:
        """Return the most recent matching row inside the dedup window, or ``None``.

        On any DB error we *fail open* (return None) so a transient lock never
        blocks a real reply — the worst case is we send a duplicate, which is
        what the system did before this dedup ever existed.
        """
        cutoff = time.time() - max(0.0, float(window_seconds))
        try:
            with open_shared_sqlite(self._db_path, row_factory=True) as conn:
                row = conn.execute(
                    """
                    SELECT customer_key, message_hash, sent_at, device_serial
                    FROM recent_replies
                    WHERE customer_key = ?
                      AND message_hash = ?
                      AND sent_at >= ?
                    ORDER BY sent_at DESC
                    LIMIT 1
                    """,
                    (customer_key, message_hash, cutoff),
                ).fetchone()
        except sqlite3.DatabaseError as exc:
            logger.warning("recent_replies lookup failed (fail-open): %s", exc)
            return None

        if not row:
            return None
        return RecentReplyRecord(
            customer_key=row["customer_key"],
            message_hash=row["message_hash"],
            sent_at=float(row["sent_at"]),
            device_serial=row["device_serial"],
        )

    def record(
        self,
        customer_key: str,
        message_hash: str,
        device_serial: str,
    ) -> None:
        """Insert a row marking ``(customer_key, message_hash)`` as taken now."""
        now = time.time()
        try:
            with open_shared_sqlite(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO recent_replies (customer_key, message_hash, sent_at, device_serial)
                    VALUES (?, ?, ?, ?)
                    """,
                    (customer_key, message_hash, now, device_serial),
                )
                conn.commit()
        except sqlite3.DatabaseError as exc:
            logger.warning("recent_replies insert failed: %s", exc)
            return

        # Opportunistic pruning: cheap to do a few times per minute, prevents
        # the table from growing unboundedly during long-running deployments.
        try:
            with open_shared_sqlite(self._db_path) as conn:
                conn.execute(
                    """
                    DELETE FROM recent_replies
                    WHERE id NOT IN (
                        SELECT id FROM recent_replies
                        ORDER BY sent_at DESC
                        LIMIT ?
                    )
                    """,
                    (_MAX_RETENTION_ROWS,),
                )
                conn.commit()
        except sqlite3.DatabaseError:
            pass


_singleton: RecentRepliesRepository | None = None


def get_recent_replies_repository() -> RecentRepliesRepository:
    """Module-level singleton so each process opens at most one connection cache."""
    global _singleton
    if _singleton is None:
        _singleton = RecentRepliesRepository()
    return _singleton
