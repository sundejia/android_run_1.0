"""
Conversation storage path and federation helpers.

This module separates the shared control/settings database from per-device
conversation databases and provides stable source-aware identifiers for
federated read APIs.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from utils.path_utils import get_project_root
from wecom_automation.core.config import get_default_db_path

PROJECT_ROOT = get_project_root()
DEVICE_STORAGE_ROOT = PROJECT_ROOT / "device_storage"
DEVICE_DB_FILENAME = "wecom_conversations.db"
FEDERATED_DB_LABEL = "federated://device-dbs"

LOCAL_ID_BITS = 40
LOCAL_ID_MASK = (1 << LOCAL_ID_BITS) - 1

# Default lock-wait window for cross-process SQLite contention. The shared
# control DB is written by the desktop backend, the per-device realtime_reply
# subprocesses, and several background services in parallel — without an
# explicit busy timeout SQLite raises "database is locked" almost immediately
# under contention. 10 seconds matches what `heartbeat_service` already uses.
DEFAULT_SQLITE_TIMEOUT_SECONDS = 10
DEFAULT_SQLITE_BUSY_TIMEOUT_MS = 10000


def open_shared_sqlite(
    db_path: str,
    *,
    timeout: float = DEFAULT_SQLITE_TIMEOUT_SECONDS,
    busy_timeout_ms: int = DEFAULT_SQLITE_BUSY_TIMEOUT_MS,
    enable_wal: bool = True,
    row_factory: bool = False,
    factory: type[sqlite3.Connection] | None = None,
) -> sqlite3.Connection:
    """Open a SQLite connection with sane multi-process defaults.

    - Sets a generous ``timeout`` so writers wait for a held lock instead of
      failing immediately when another process is mid-transaction.
    - Enables ``journal_mode=WAL`` once per database so readers and a single
      writer can proceed concurrently (the ``PRAGMA`` is persistent — repeating
      it is cheap and safe).
    - Sets ``busy_timeout`` at the connection level as a belt-and-braces
      safeguard against drivers that ignore the constructor ``timeout``.

    ``WAL`` mode requires the SQLite file to live on a local disk; for the
    in-memory or read-only URI use cases (currently only inside log_upload),
    the caller should pass ``enable_wal=False``.
    """
    if factory is not None:
        conn = sqlite3.connect(db_path, timeout=timeout, factory=factory)
    else:
        conn = sqlite3.connect(db_path, timeout=timeout)
    if row_factory:
        conn.row_factory = sqlite3.Row
    try:
        if enable_wal:
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError:
                # Some environments (read-only, network FS) don't support WAL;
                # tolerate that — busy_timeout is still useful.
                pass
        conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    except sqlite3.DatabaseError:
        # Never let a pragma failure prevent callers from using the connection.
        pass
    return conn


@dataclass(frozen=True)
class ConversationDbTarget:
    device_serial: str
    db_path: Path
    source_kind: str = "device"

    @property
    def source_token(self) -> int:
        digest = hashlib.sha256(str(self.db_path).encode("utf-8")).digest()
        return int.from_bytes(digest[:3], "big")


def get_control_db_path() -> Path:
    """Return the shared control-plane database path."""
    return get_default_db_path().resolve()


def sanitize_device_serial(serial: str) -> str:
    """Create a filesystem-safe path segment for a device serial."""
    import re

    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", serial).strip("._-")
    return sanitized or "unknown-device"


def get_device_storage_root(serial: str) -> Path:
    """Return the root storage directory for a device."""
    return DEVICE_STORAGE_ROOT / sanitize_device_serial(serial)


def get_device_conversation_db_path(serial: str) -> Path:
    """Return the default conversation database path for a device."""
    return (get_device_storage_root(serial) / DEVICE_DB_FILENAME).resolve()


def resolve_conversation_db_path(serial: str | None = None, db_path: str | None = None) -> Path:
    """Resolve an explicit or device-scoped conversation DB path."""
    if db_path:
        return Path(db_path).expanduser().resolve()
    if serial:
        return get_device_conversation_db_path(serial)
    return get_control_db_path()


def _table_exists(cursor: sqlite3.Cursor, table_name: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    )
    return cursor.fetchone() is not None


def _read_primary_device_serial(db_path: Path) -> str | None:
    """Best-effort read of the primary device serial stored in a DB."""
    if not db_path.exists():
        return None

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        if not _table_exists(cursor, "devices"):
            return None
        cursor.execute(
            """
            SELECT serial
            FROM devices
            WHERE serial IS NOT NULL AND TRIM(serial) != ''
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        return str(row["serial"]) if row else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _has_conversation_tables(db_path: Path) -> bool:
    if not db_path.exists():
        return False

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        return all(_table_exists(cursor, table_name) for table_name in ("customers", "messages", "kefus"))
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def list_device_conversation_targets() -> list[ConversationDbTarget]:
    """Enumerate known per-device conversation DBs on disk."""
    targets: list[ConversationDbTarget] = []
    seen_paths: set[str] = set()

    if not DEVICE_STORAGE_ROOT.exists():
        return targets

    for candidate in sorted(DEVICE_STORAGE_ROOT.glob(f"*/{DEVICE_DB_FILENAME}")):
        resolved = candidate.resolve()
        path_key = str(resolved).lower()
        if path_key in seen_paths:
            continue
        seen_paths.add(path_key)

        serial = _read_primary_device_serial(resolved) or candidate.parent.name
        targets.append(ConversationDbTarget(device_serial=serial, db_path=resolved))

    return targets


def list_federated_conversation_targets(device_serial: str | None = None) -> list[ConversationDbTarget]:
    """
    Enumerate conversation DBs that should participate in federated reads.

    If no per-device DBs exist yet, fall back to the legacy shared DB so
    upgraded deployments can still read historical data.
    """
    targets = list_device_conversation_targets()
    if device_serial:
        targets = [target for target in targets if target.device_serial == device_serial]

    if targets:
        return targets

    control_db = get_control_db_path()
    if device_serial is None and _has_conversation_tables(control_db):
        serial = _read_primary_device_serial(control_db) or "legacy-shared"
        return [ConversationDbTarget(device_serial=serial, db_path=control_db, source_kind="legacy-control")]

    return []


def build_federated_db_label(targets: Iterable[ConversationDbTarget]) -> str:
    targets = list(targets)
    if not targets:
        return FEDERATED_DB_LABEL
    return f"{FEDERATED_DB_LABEL}?count={len(targets)}"


def compose_global_id(db_path: Path, local_id: int | None) -> int | None:
    """Compose a stable numeric ID for aggregated responses."""
    if local_id is None:
        return None
    if local_id < 0 or local_id > LOCAL_ID_MASK:
        raise ValueError(f"Local ID out of range for federated encoding: {local_id}")
    token = ConversationDbTarget(device_serial="unknown", db_path=db_path.resolve()).source_token
    return (token << LOCAL_ID_BITS) | int(local_id)


def decode_global_id(global_id: int) -> tuple[int, int]:
    """Decode a federated numeric ID into (source_token, local_id)."""
    return (int(global_id) >> LOCAL_ID_BITS, int(global_id) & LOCAL_ID_MASK)


def target_matches_global_id(target: ConversationDbTarget, global_id: int, local_id: int) -> bool:
    """Return True when the target/local pair matches the federated ID."""
    token, decoded_local_id = decode_global_id(global_id)
    return token == target.source_token and decoded_local_id == int(local_id)
