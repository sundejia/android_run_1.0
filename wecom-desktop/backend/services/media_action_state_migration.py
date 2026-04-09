"""
Helpers for consolidating media action state into the shared control DB.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from services.conversation_storage import get_control_db_path, list_device_conversation_targets
from wecom_automation.database.schema import repair_blacklist_schema
from wecom_automation.services.blacklist_service import BlacklistChecker
from wecom_automation.services.media_actions.group_chat_service import ensure_media_action_groups_table

logger = logging.getLogger("media_action_state_migration")


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _row_sort_key(row: sqlite3.Row | dict[str, Any]) -> tuple[str, str, int]:
    updated = str(row["updated_at"] or row["created_at"] or "")
    created = str(row["created_at"] or row["updated_at"] or "")
    try:
        row_id_value = row["id"]
    except (KeyError, IndexError):
        row_id_value = None
    row_id = int(row_id_value) if row_id_value not in (None, "") else 0
    return (updated, created, row_id)


def _latest_non_empty(rows: list[sqlite3.Row | dict[str, Any]], column_name: str):
    for row in rows:
        value = row[column_name]
        if value not in (None, ""):
            return value
    return None


def _oldest_timestamp(rows: list[sqlite3.Row | dict[str, Any]], *column_names: str) -> str | None:
    values = [
        str(row[column_name])
        for row in rows
        for column_name in column_names
        if row[column_name] not in (None, "")
    ]
    return min(values) if values else None


def _newest_timestamp(rows: list[sqlite3.Row | dict[str, Any]], *column_names: str) -> str | None:
    values = [
        str(row[column_name])
        for row in rows
        for column_name in column_names
        if row[column_name] not in (None, "")
    ]
    return max(values) if values else None


def _collapse_blacklist_rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault((row["device_serial"], row["customer_name"]), []).append(row)

    collapsed: list[dict[str, Any]] = []
    for (device_serial, customer_name), group_rows in grouped.items():
        ordered_rows = sorted(group_rows, key=_row_sort_key, reverse=True)
        collapsed.append(
            {
                "device_serial": device_serial,
                "customer_name": customer_name,
                "customer_channel": _latest_non_empty(ordered_rows, "customer_channel"),
                "reason": _latest_non_empty(ordered_rows, "reason"),
                "deleted_by_user": 1 if any(bool(row["deleted_by_user"]) for row in ordered_rows) else 0,
                "is_blacklisted": 1 if any(bool(row["is_blacklisted"]) for row in ordered_rows) else 0,
                "avatar_url": _latest_non_empty(ordered_rows, "avatar_url"),
                "customer_db_id": _latest_non_empty(ordered_rows, "customer_db_id"),
                "created_at": _oldest_timestamp(ordered_rows, "created_at", "updated_at"),
                "updated_at": _newest_timestamp(ordered_rows, "updated_at", "created_at"),
            }
        )

    return collapsed


def _collapse_group_rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault((row["device_serial"], row["customer_name"], row["group_name"]), []).append(row)

    collapsed: list[dict[str, Any]] = []
    for (device_serial, customer_name, group_name), group_rows in grouped.items():
        ordered_rows = sorted(group_rows, key=_row_sort_key, reverse=True)
        collapsed.append(
            {
                "device_serial": device_serial,
                "customer_name": customer_name,
                "group_name": group_name,
                "group_members": _latest_non_empty(ordered_rows, "group_members"),
                "status": _latest_non_empty(ordered_rows, "status") or "created",
                "created_at": _oldest_timestamp(ordered_rows, "created_at", "updated_at"),
                "updated_at": _newest_timestamp(ordered_rows, "updated_at", "created_at"),
            }
        )

    return collapsed


def _upsert_blacklist_record(control_conn: sqlite3.Connection, row: dict[str, Any]) -> str:
    existing_rows = control_conn.execute(
        """
        SELECT *
        FROM blacklist
        WHERE device_serial = ?
          AND customer_name = ?
        ORDER BY COALESCE(updated_at, created_at) DESC,
                 COALESCE(created_at, updated_at) DESC,
                 id DESC
        """,
        (row["device_serial"], row["customer_name"]),
    ).fetchall()

    merged_rows: list[sqlite3.Row | dict[str, Any]] = sorted([*existing_rows, row], key=_row_sort_key, reverse=True)
    merged_row = {
        "customer_channel": _latest_non_empty(merged_rows, "customer_channel"),
        "reason": _latest_non_empty(merged_rows, "reason"),
        "deleted_by_user": 1 if any(bool(r["deleted_by_user"]) for r in merged_rows) else 0,
        "is_blacklisted": 1 if any(bool(r["is_blacklisted"]) for r in merged_rows) else 0,
        "avatar_url": _latest_non_empty(merged_rows, "avatar_url"),
        "customer_db_id": _latest_non_empty(merged_rows, "customer_db_id"),
        "created_at": _oldest_timestamp(merged_rows, "created_at", "updated_at"),
        "updated_at": _newest_timestamp(merged_rows, "updated_at", "created_at"),
    }

    if existing_rows:
        canonical_id = existing_rows[0]["id"]
        control_conn.execute(
            """
            UPDATE blacklist
            SET customer_channel = ?,
                reason = ?,
                deleted_by_user = ?,
                is_blacklisted = ?,
                avatar_url = ?,
                customer_db_id = ?,
                created_at = COALESCE(?, created_at),
                updated_at = COALESCE(?, updated_at)
            WHERE id = ?
            """,
            (
                merged_row["customer_channel"],
                merged_row["reason"],
                merged_row["deleted_by_user"],
                merged_row["is_blacklisted"],
                merged_row["avatar_url"],
                merged_row["customer_db_id"],
                merged_row["created_at"],
                merged_row["updated_at"],
                canonical_id,
            ),
        )
        return "updated"

    control_conn.execute(
        """
        INSERT INTO blacklist (
            device_serial,
            customer_name,
            customer_channel,
            reason,
            deleted_by_user,
            is_blacklisted,
            avatar_url,
            customer_db_id,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), COALESCE(?, CURRENT_TIMESTAMP))
        """,
        (
            row["device_serial"],
            row["customer_name"],
            row["customer_channel"],
            row["reason"],
            row["deleted_by_user"],
            row["is_blacklisted"],
            row["avatar_url"],
            row["customer_db_id"],
            row["created_at"],
            row["updated_at"],
        ),
    )
    return "inserted"


def _upsert_group_record(control_conn: sqlite3.Connection, row: dict[str, Any]) -> str:
    existing_row = control_conn.execute(
        """
        SELECT id
        FROM media_action_groups
        WHERE device_serial = ?
          AND customer_name = ?
          AND group_name = ?
        ORDER BY COALESCE(updated_at, created_at) DESC,
                 COALESCE(created_at, updated_at) DESC,
                 id DESC
        LIMIT 1
        """,
        (row["device_serial"], row["customer_name"], row["group_name"]),
    ).fetchone()

    if existing_row:
        control_conn.execute(
            """
            UPDATE media_action_groups
            SET group_members = COALESCE(?, group_members),
                status = COALESCE(?, status),
                created_at = COALESCE(?, created_at),
                updated_at = COALESCE(?, updated_at)
            WHERE id = ?
            """,
            (
                row["group_members"],
                row["status"],
                row["created_at"],
                row["updated_at"],
                existing_row["id"],
            ),
        )
        return "updated"

    control_conn.execute(
        """
        INSERT INTO media_action_groups (
            device_serial,
            customer_name,
            group_name,
            group_members,
            status,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), COALESCE(?, CURRENT_TIMESTAMP))
        """,
        (
            row["device_serial"],
            row["customer_name"],
            row["group_name"],
            row["group_members"],
            row["status"],
            row["created_at"],
            row["updated_at"],
        ),
    )
    return "inserted"


def migrate_media_action_state_to_control(control_db_path: str | None = None) -> dict[str, int]:
    """
    Merge device-local media action state into the shared control DB.

    The migration is idempotent and can safely run at every backend startup.
    """
    resolved_control_db = str(Path(control_db_path or get_control_db_path()).resolve())
    ensure_media_action_groups_table(resolved_control_db)
    repair_blacklist_schema(resolved_control_db)

    stats = {
        "blacklist_inserted": 0,
        "blacklist_updated": 0,
        "groups_inserted": 0,
        "groups_updated": 0,
        "source_dbs_scanned": 0,
    }

    control_conn = sqlite3.connect(resolved_control_db)
    control_conn.row_factory = sqlite3.Row
    try:
        for target in list_device_conversation_targets():
            source_db_path = str(target.db_path.resolve())
            if source_db_path == resolved_control_db:
                continue

            stats["source_dbs_scanned"] += 1
            source_conn = sqlite3.connect(source_db_path)
            source_conn.row_factory = sqlite3.Row
            try:
                if _table_exists(source_conn, "blacklist"):
                    rows = source_conn.execute("SELECT * FROM blacklist").fetchall()
                    for row in _collapse_blacklist_rows(rows):
                        result = _upsert_blacklist_record(control_conn, row)
                        stats[f"blacklist_{result}"] += 1

                if _table_exists(source_conn, "media_action_groups"):
                    rows = source_conn.execute("SELECT * FROM media_action_groups").fetchall()
                    for row in _collapse_group_rows(rows):
                        result = _upsert_group_record(control_conn, row)
                        stats[f"groups_{result}"] += 1
            finally:
                source_conn.close()

        control_conn.commit()
    finally:
        control_conn.close()

    repairs = repair_blacklist_schema(resolved_control_db)
    if repairs:
        logger.info("Applied control DB blacklist repairs after migration: %s", ", ".join(repairs))
    BlacklistChecker.invalidate_cache()
    return stats
