"""
Federated read helpers for per-device conversation databases.

The backend writes conversations into device-local SQLite files while read-side
APIs aggregate those files on demand.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from services.conversation_storage import (
    PROJECT_ROOT,
    build_federated_db_label,
    compose_global_id,
    decode_global_id,
    get_control_db_path,
    list_federated_conversation_targets,
)
from wecom_automation.database.schema import get_connection


def _json_loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


class FederatedReadService:
    ENTITY_TABLES = {
        "customer": "customers",
        "message": "messages",
        "image": "images",
        "video": "videos",
        "kefu": "kefus",
    }

    def _targets(self, device_serial: str | None = None):
        return list_federated_conversation_targets(device_serial=device_serial)

    def _open_target(self, target):
        return get_connection(str(target.db_path))

    def _federated_label(self, targets) -> str:
        return build_federated_db_label(targets)

    def _encode(self, target, local_id: int | None) -> int | None:
        return compose_global_id(target.db_path, local_id)

    def _normalize_device_model(self, conn) -> str | None:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT model
            FROM devices
            WHERE model IS NOT NULL AND TRIM(model) != ''
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        return row["model"] if row else None

    def _decorate_customer_row(self, target, row: dict[str, Any]) -> dict[str, Any]:
        row["id"] = self._encode(target, row["id"])
        row["kefu_id"] = self._encode(target, row.get("kefu_id"))
        row["device_serial"] = target.device_serial
        row["source_db_path"] = str(target.db_path)
        return row

    def _decorate_message_row(self, target, row: dict[str, Any]) -> dict[str, Any]:
        row["id"] = self._encode(target, row["id"])
        if "customer_id" in row:
            row["customer_id"] = self._encode(target, row["customer_id"])
        if "video_table_id" in row:
            row["video_table_id"] = self._encode(target, row.get("video_table_id"))
        row["source_db_path"] = str(target.db_path)
        row["device_serial"] = target.device_serial
        return row

    def _decorate_image_row(self, target, row: dict[str, Any]) -> dict[str, Any]:
        row["id"] = self._encode(target, row["id"])
        row["message_id"] = self._encode(target, row.get("message_id"))
        row["customer_id"] = self._encode(target, row.get("customer_id"))
        row["kefu_id"] = self._encode(target, row.get("kefu_id"))
        row["device_serial"] = target.device_serial
        row["source_db_path"] = str(target.db_path)
        return row

    def _decorate_voice_row(self, target, row: dict[str, Any]) -> dict[str, Any]:
        row["id"] = self._encode(target, row["id"])
        row["customer_id"] = self._encode(target, row.get("customer_id"))
        row["kefu_id"] = self._encode(target, row.get("kefu_id"))
        row["device_serial"] = target.device_serial
        row["source_db_path"] = str(target.db_path)
        return row

    def _decorate_video_row(self, target, row: dict[str, Any]) -> dict[str, Any]:
        row["id"] = self._encode(target, row["id"])
        row["customer_id"] = self._encode(target, row.get("customer_id"))
        row["kefu_id"] = self._encode(target, row.get("kefu_id"))
        row["video_id"] = self._encode(target, row.get("video_id"))
        row["device_serial"] = target.device_serial
        row["source_db_path"] = str(target.db_path)
        return row

    def _decorate_image_info(self, target, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        row["image_id"] = self._encode(target, row.get("image_id"))
        row["message_id"] = self._encode(target, row.get("message_id"))
        row["source_db_path"] = str(target.db_path)
        row["device_serial"] = target.device_serial
        return row

    def _decorate_voice_info(self, target, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        row["message_id"] = self._encode(target, row.get("message_id"))
        row["customer_id"] = self._encode(target, row.get("customer_id"))
        row["source_db_path"] = str(target.db_path)
        row["device_serial"] = target.device_serial
        return row

    def _decorate_video_info(self, target, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        row["video_id"] = self._encode(target, row.get("video_id"))
        row["message_id"] = self._encode(target, row.get("message_id"))
        row["source_db_path"] = str(target.db_path)
        row["device_serial"] = target.device_serial
        return row

    def _resolve_entity(self, global_id: int, entity: str, device_serial: str | None = None):
        token, local_id = decode_global_id(global_id)
        table = self.ENTITY_TABLES[entity]
        matches = []
        for target in self._targets(device_serial=device_serial):
            if target.source_token != token:
                continue
            conn = self._open_target(target)
            try:
                cursor = conn.cursor()
                cursor.execute(f"SELECT 1 FROM {table} WHERE id = ? LIMIT 1", (local_id,))
                if cursor.fetchone():
                    matches.append((target, local_id))
            finally:
                conn.close()

        if not matches:
            raise HTTPException(status_code=404, detail=f"{entity} not found")
        if len(matches) > 1:
            raise HTTPException(status_code=409, detail=f"Ambiguous federated {entity} id")
        return matches[0]

    def resolve_customer(self, customer_id: int, device_serial: str | None = None):
        return self._resolve_entity(customer_id, "customer", device_serial=device_serial)

    def resolve_message(self, message_id: int, device_serial: str | None = None):
        return self._resolve_entity(message_id, "message", device_serial=device_serial)

    def resolve_image(self, image_id: int, device_serial: str | None = None):
        return self._resolve_entity(image_id, "image", device_serial=device_serial)

    def resolve_video(self, video_id: int, device_serial: str | None = None):
        return self._resolve_entity(video_id, "video", device_serial=device_serial)

    def resolve_kefu_filter(self, kefu_id: int):
        return self._resolve_entity(kefu_id, "kefu")

    def get_dashboard_overview(self, limit: int = 50) -> dict[str, Any]:
        targets = self._targets()
        stats = {
            "devices": 0,
            "kefus": 0,
            "customers": 0,
            "messages": 0,
            "images": 0,
            "messages_by_type": {},
        }
        devices: list[dict[str, Any]] = []
        kefus: list[dict[str, Any]] = []
        recent_conversations: list[dict[str, Any]] = []
        last_updated: str | None = None

        for target in targets:
            conn = self._open_target(target)
            try:
                cursor = conn.cursor()
                device_model = self._normalize_device_model(conn)

                for table in ("devices", "kefus", "customers", "messages", "images"):
                    cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
                    stats[table] += cursor.fetchone()["count"]

                cursor.execute("SELECT message_type, COUNT(*) as count FROM messages GROUP BY message_type")
                for row in cursor.fetchall():
                    stats["messages_by_type"][row["message_type"]] = (
                        stats["messages_by_type"].get(row["message_type"], 0) + row["count"]
                    )

                cursor.execute(
                    """
                    SELECT MAX(ts) as last_ts FROM (
                        SELECT MAX(COALESCE(timestamp_parsed, created_at)) as ts FROM messages
                        UNION ALL
                        SELECT MAX(updated_at) FROM customers
                        UNION ALL
                        SELECT MAX(updated_at) FROM kefus
                        UNION ALL
                        SELECT MAX(updated_at) FROM devices
                    )
                    """
                )
                candidate_last = cursor.fetchone()["last_ts"]
                if candidate_last and (last_updated is None or candidate_last > last_updated):
                    last_updated = candidate_last

                cursor.execute(
                    """
                    SELECT
                        d.id,
                        d.serial,
                        d.model,
                        d.manufacturer,
                        d.android_version,
                        d.created_at,
                        d.updated_at,
                        (
                            SELECT COUNT(DISTINCT kd.kefu_id) FROM kefu_devices kd
                            WHERE kd.device_id = d.id
                        ) AS kefu_count,
                        (
                            SELECT COUNT(DISTINCT c.id) FROM customers c
                            JOIN kefus k ON c.kefu_id = k.id
                            JOIN kefu_devices kd ON k.id = kd.kefu_id
                            WHERE kd.device_id = d.id
                        ) AS customer_count,
                        (
                            SELECT COUNT(*) FROM messages m
                            JOIN customers c ON m.customer_id = c.id
                            JOIN kefus k ON c.kefu_id = k.id
                            JOIN kefu_devices kd ON k.id = kd.kefu_id
                            WHERE kd.device_id = d.id
                        ) AS message_count,
                        (
                            SELECT COUNT(*) FROM messages m
                            JOIN customers c ON m.customer_id = c.id
                            JOIN kefus k ON c.kefu_id = k.id
                            JOIN kefu_devices kd ON k.id = kd.kefu_id
                            WHERE kd.device_id = d.id AND m.is_from_kefu = 1
                        ) AS sent_by_kefu,
                        (
                            SELECT COUNT(*) FROM messages m
                            JOIN customers c ON m.customer_id = c.id
                            JOIN kefus k ON c.kefu_id = k.id
                            JOIN kefu_devices kd ON k.id = kd.kefu_id
                            WHERE kd.device_id = d.id AND m.is_from_kefu = 0
                        ) AS sent_by_customer,
                        (
                            SELECT MAX(COALESCE(m.timestamp_parsed, m.created_at))
                            FROM messages m
                            JOIN customers c ON m.customer_id = c.id
                            JOIN kefus k ON c.kefu_id = k.id
                            JOIN kefu_devices kd ON k.id = kd.kefu_id
                            WHERE kd.device_id = d.id
                        ) AS last_message_at
                    FROM devices d
                    ORDER BY d.created_at DESC
                    """
                )
                for row in cursor.fetchall():
                    item = dict(row)
                    item["id"] = self._encode(target, item["id"])
                    devices.append(item)

                cursor.execute(
                    """
                    SELECT
                        k.id,
                        k.name,
                        k.department,
                        k.verification_status,
                        (
                            SELECT COUNT(*) FROM kefu_devices kd
                            WHERE kd.kefu_id = k.id
                        ) AS device_count,
                        (
                            SELECT COUNT(*) FROM customers c
                            WHERE c.kefu_id = k.id
                        ) AS customer_count,
                        (
                            SELECT COUNT(*) FROM messages m
                            JOIN customers c ON m.customer_id = c.id
                            WHERE c.kefu_id = k.id
                        ) AS message_count,
                        (
                            SELECT COUNT(*) FROM messages m
                            JOIN customers c ON m.customer_id = c.id
                            WHERE c.kefu_id = k.id AND m.is_from_kefu = 1
                        ) AS sent_by_kefu,
                        (
                            SELECT COUNT(*) FROM messages m
                            JOIN customers c ON m.customer_id = c.id
                            WHERE c.kefu_id = k.id AND m.is_from_kefu = 0
                        ) AS sent_by_customer,
                        (
                            SELECT MAX(COALESCE(m.timestamp_parsed, m.created_at))
                            FROM messages m
                            JOIN customers c ON m.customer_id = c.id
                            WHERE c.kefu_id = k.id
                        ) AS last_message_at,
                        (
                            SELECT c.name FROM customers c
                            WHERE c.kefu_id = k.id
                            ORDER BY COALESCE(c.last_message_date, c.updated_at, c.created_at) DESC
                            LIMIT 1
                        ) AS last_customer_name,
                        (
                            SELECT c.channel FROM customers c
                            WHERE c.kefu_id = k.id
                            ORDER BY COALESCE(c.last_message_date, c.updated_at, c.created_at) DESC
                            LIMIT 1
                        ) AS last_customer_channel,
                        (
                            SELECT c.last_message_preview FROM customers c
                            WHERE c.kefu_id = k.id
                            ORDER BY COALESCE(c.last_message_date, c.updated_at, c.created_at) DESC
                            LIMIT 1
                        ) AS last_message_preview,
                        (
                            SELECT c.last_message_date FROM customers c
                            WHERE c.kefu_id = k.id
                            ORDER BY COALESCE(c.last_message_date, c.updated_at, c.created_at) DESC
                            LIMIT 1
                        ) AS last_message_date,
                        k.created_at,
                        k.updated_at
                    FROM kefus k
                    ORDER BY k.updated_at DESC
                    """
                )
                for row in cursor.fetchall():
                    item = dict(row)
                    item["id"] = self._encode(target, item["id"])
                    item["device_serial"] = target.device_serial
                    item["device_model"] = device_model
                    kefus.append(item)

                cursor.execute(
                    """
                    SELECT
                        c.id,
                        c.name,
                        c.channel,
                        c.last_message_preview,
                        c.last_message_date,
                        c.updated_at,
                        c.created_at,
                        c.kefu_id,
                        k.name AS kefu_name,
                        k.department AS kefu_department,
                        (
                            SELECT COUNT(*) FROM messages m
                            WHERE m.customer_id = c.id
                        ) AS message_count,
                        (
                            SELECT COUNT(*) FROM messages m
                            WHERE m.customer_id = c.id AND m.is_from_kefu = 1
                        ) AS sent_by_kefu,
                        (
                            SELECT COUNT(*) FROM messages m
                            WHERE m.customer_id = c.id AND m.is_from_kefu = 0
                        ) AS sent_by_customer,
                        (
                            SELECT MAX(COALESCE(m.timestamp_parsed, m.created_at))
                            FROM messages m
                            WHERE m.customer_id = c.id
                        ) AS last_message_at
                    FROM customers c
                    JOIN kefus k ON c.kefu_id = k.id
                    ORDER BY COALESCE(last_message_at, c.last_message_date, c.updated_at, c.created_at) DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
                for row in cursor.fetchall():
                    recent_conversations.append(self._decorate_customer_row(target, dict(row)))
            finally:
                conn.close()

        recent_conversations.sort(
            key=lambda row: row.get("last_message_at") or row.get("last_message_date") or row.get("updated_at") or "",
            reverse=True,
        )
        return {
            "db_path": self._federated_label(targets),
            "last_updated": last_updated,
            "stats": stats,
            "devices": sorted(devices, key=lambda row: row.get("serial") or ""),
            "kefus": sorted(kefus, key=lambda row: row.get("updated_at") or "", reverse=True),
            "recent_conversations": recent_conversations[:limit],
        }

    def get_message_timeseries(
        self,
        kefu_ids: list[int] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        granularity: str = "day",
    ) -> dict[str, Any]:
        targets = self._targets()
        overall: dict[str, dict[str, int | str]] = {}
        by_kefu: dict[int, dict[str, dict[str, int | str]]] = {}
        kefu_names: dict[int, str] = {}
        date_formats = {
            "hour": "%Y-%m-%d %H:00",
            "day": "%Y-%m-%d",
            "week": "%Y-W%W",
            "month": "%Y-%m",
        }
        date_format = date_formats.get(granularity, "%Y-%m-%d")
        requested_kefu: dict[str, set[int]] | None = None
        if kefu_ids:
            requested_kefu = {}
            for kefu_id in kefu_ids:
                target, local_id = self.resolve_kefu_filter(kefu_id)
                requested_kefu.setdefault(str(target.db_path), set()).add(local_id)

        for target in targets:
            conn = self._open_target(target)
            try:
                cursor = conn.cursor()
                conditions = []
                params: list[Any] = []
                if start_date:
                    conditions.append("COALESCE(m.timestamp_parsed, m.created_at) >= ?")
                    params.append(start_date)
                if end_date:
                    conditions.append("COALESCE(m.timestamp_parsed, m.created_at) <= ?")
                    params.append(end_date)
                local_kefus = None
                if requested_kefu is not None:
                    local_kefus = requested_kefu.get(str(target.db_path))
                    if not local_kefus:
                        continue
                    placeholders = ",".join("?" for _ in local_kefus)
                    conditions.append(f"k.id IN ({placeholders})")
                    params.extend(sorted(local_kefus))
                where_clause = " AND ".join(conditions) if conditions else "1=1"

                cursor.execute(
                    f"""
                    SELECT
                        strftime('{date_format}', COALESCE(m.timestamp_parsed, m.created_at)) as time_bucket,
                        COUNT(*) as total,
                        SUM(CASE WHEN m.is_from_kefu = 1 THEN 1 ELSE 0 END) as outgoing,
                        SUM(CASE WHEN m.is_from_kefu = 0 THEN 1 ELSE 0 END) as incoming
                    FROM messages m
                    JOIN customers c ON m.customer_id = c.id
                    JOIN kefus k ON c.kefu_id = k.id
                    WHERE {where_clause}
                    GROUP BY time_bucket
                    ORDER BY time_bucket ASC
                    """,
                    tuple(params),
                )
                for row in cursor.fetchall():
                    bucket = row["time_bucket"]
                    data = overall.setdefault(bucket, {"time": bucket, "total": 0, "outgoing": 0, "incoming": 0})
                    data["total"] += row["total"] or 0
                    data["outgoing"] += row["outgoing"] or 0
                    data["incoming"] += row["incoming"] or 0

                if local_kefus is None:
                    cursor.execute("SELECT id, name FROM kefus")
                else:
                    placeholders = ",".join("?" for _ in local_kefus)
                    cursor.execute(
                        f"SELECT id, name FROM kefus WHERE id IN ({placeholders})",
                        tuple(sorted(local_kefus)),
                    )
                for row in cursor.fetchall():
                    local_kefu_id = row["id"]
                    global_kefu_id = self._encode(target, local_kefu_id)
                    kefu_names[global_kefu_id] = row["name"]
                    params = [local_kefu_id]
                    extra_conditions = []
                    if start_date:
                        extra_conditions.append("COALESCE(m.timestamp_parsed, m.created_at) >= ?")
                        params.append(start_date)
                    if end_date:
                        extra_conditions.append("COALESCE(m.timestamp_parsed, m.created_at) <= ?")
                        params.append(end_date)
                    extra_where = ""
                    if extra_conditions:
                        extra_where = " AND " + " AND ".join(extra_conditions)
                    cursor.execute(
                        f"""
                        SELECT
                            strftime('{date_format}', COALESCE(m.timestamp_parsed, m.created_at)) as time_bucket,
                            COUNT(*) as total,
                            SUM(CASE WHEN m.is_from_kefu = 1 THEN 1 ELSE 0 END) as outgoing,
                            SUM(CASE WHEN m.is_from_kefu = 0 THEN 1 ELSE 0 END) as incoming
                        FROM messages m
                        JOIN customers c ON m.customer_id = c.id
                        WHERE c.kefu_id = ?{extra_where}
                        GROUP BY time_bucket
                        ORDER BY time_bucket ASC
                        """,
                        tuple(params),
                    )
                    bucket_map = by_kefu.setdefault(global_kefu_id, {})
                    for series_row in cursor.fetchall():
                        bucket = series_row["time_bucket"]
                        bucket_map[bucket] = {
                            "time": bucket,
                            "total": series_row["total"] or 0,
                            "outgoing": series_row["outgoing"] or 0,
                            "incoming": series_row["incoming"] or 0,
                        }
            finally:
                conn.close()

        return {
            "db_path": self._federated_label(targets),
            "overall": [overall[key] for key in sorted(overall.keys())],
            "by_kefu": {
                kefu_id: [bucket_map[key] for key in sorted(bucket_map.keys())]
                for kefu_id, bucket_map in by_kefu.items()
            },
            "kefu_names": kefu_names,
            "granularity": granularity,
        }

    def get_customer_filter_options(self) -> dict[str, Any]:
        targets = self._targets()
        streamers: set[str] = set()
        agents: dict[int, dict[str, Any]] = {}
        devices: dict[str, dict[str, Any]] = {}
        for target in targets:
            conn = self._open_target(target)
            try:
                cursor = conn.cursor()
                devices[target.device_serial] = {
                    "serial": target.device_serial,
                    "model": self._normalize_device_model(conn),
                }
                cursor.execute("SELECT DISTINCT name FROM customers ORDER BY name")
                streamers.update(row["name"] for row in cursor.fetchall())
                cursor.execute("SELECT id, name, department FROM kefus ORDER BY name")
                for row in cursor.fetchall():
                    global_id = self._encode(target, row["id"])
                    agents[global_id] = {
                        "id": global_id,
                        "name": row["name"],
                        "department": row["department"],
                    }
            finally:
                conn.close()

        return {
            "db_path": self._federated_label(targets),
            "streamers": sorted(streamers),
            "agents": sorted(agents.values(), key=lambda row: row["name"]),
            "devices": sorted(devices.values(), key=lambda row: row["serial"]),
        }

    def list_customers(
        self,
        limit: int = 50,
        offset: int = 0,
        search: str | None = None,
        streamer: str | None = None,
        kefu_id: int | None = None,
        device_serial: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = "desc",
    ) -> dict[str, Any]:
        targets = self._targets(device_serial=device_serial)
        scoped_kefu = self.resolve_kefu_filter(kefu_id) if kefu_id is not None else None
        rows: list[dict[str, Any]] = []
        for target in targets:
            if scoped_kefu and str(scoped_kefu[0].db_path) != str(target.db_path):
                continue
            conn = self._open_target(target)
            try:
                cursor = conn.cursor()
                device_model = self._normalize_device_model(conn)
                where_conditions: list[str] = []
                params: list[Any] = []
                if search:
                    where_conditions.append("(c.name LIKE ? OR c.channel LIKE ?)")
                    like_term = f"%{search}%"
                    params.extend([like_term, like_term])
                if streamer:
                    where_conditions.append("c.name = ?")
                    params.append(streamer)
                if scoped_kefu and str(scoped_kefu[0].db_path) == str(target.db_path):
                    where_conditions.append("c.kefu_id = ?")
                    params.append(scoped_kefu[1])
                if date_from:
                    where_conditions.append(
                        """(COALESCE(
                            (SELECT MAX(COALESCE(m2.timestamp_parsed, m2.created_at))
                             FROM messages m2 WHERE m2.customer_id = c.id),
                            c.last_message_date,
                            c.created_at
                        ) >= ?)"""
                    )
                    params.append(date_from)
                if date_to:
                    where_conditions.append(
                        """(COALESCE(
                            (SELECT MAX(COALESCE(m2.timestamp_parsed, m2.created_at))
                             FROM messages m2 WHERE m2.customer_id = c.id),
                            c.last_message_date,
                            c.created_at
                        ) <= ? || ' 23:59:59')"""
                    )
                    params.append(date_to)
                where_clause = ""
                if where_conditions:
                    where_clause = "WHERE " + " AND ".join(where_conditions)
                cursor.execute(
                    f"""
                    SELECT
                        c.id,
                        c.name,
                        c.channel,
                        c.kefu_id,
                        c.last_message_preview,
                        c.last_message_date,
                        c.created_at,
                        c.updated_at,
                        k.name AS kefu_name,
                        k.department AS kefu_department,
                        k.verification_status AS kefu_verification_status,
                        (
                            SELECT COUNT(*) FROM messages m
                            WHERE m.customer_id = c.id
                        ) AS message_count,
                        (
                            SELECT COUNT(*) FROM messages m
                            WHERE m.customer_id = c.id AND m.is_from_kefu = 1
                        ) AS sent_by_kefu,
                        (
                            SELECT COUNT(*) FROM messages m
                            WHERE m.customer_id = c.id AND m.is_from_kefu = 0
                        ) AS sent_by_customer,
                        (
                            SELECT MAX(COALESCE(m.timestamp_parsed, m.created_at))
                            FROM messages m
                            WHERE m.customer_id = c.id
                        ) AS last_message_at
                    FROM customers c
                    JOIN kefus k ON c.kefu_id = k.id
                    {where_clause}
                    """,
                    tuple(params),
                )
                for row in cursor.fetchall():
                    item = self._decorate_customer_row(target, dict(row))
                    item["device_model"] = device_model
                    rows.append(item)
            finally:
                conn.close()

        sort_key_map = {
            "name": lambda row: row.get("name") or "",
            "kefu_name": lambda row: row.get("kefu_name") or "",
            "device_serial": lambda row: row.get("device_serial") or "",
            "last_message_at": lambda row: row.get("last_message_at") or row.get("last_message_date") or "",
            "message_count": lambda row: row.get("message_count") or 0,
            "sent_by_kefu": lambda row: row.get("sent_by_kefu") or 0,
            "sent_by_customer": lambda row: row.get("sent_by_customer") or 0,
            "channel": lambda row: row.get("channel") or "",
            "last_message_preview": lambda row: row.get("last_message_preview") or "",
        }
        key_func = sort_key_map.get(
            sort_by,
            lambda row: row.get("last_message_at") or row.get("last_message_date") or row.get("updated_at") or "",
        )
        rows.sort(key=key_func, reverse=(sort_order or "desc").lower() != "asc")
        return {
            "db_path": self._federated_label(targets),
            "total": len(rows),
            "limit": limit,
            "offset": offset,
            "items": rows[offset : offset + limit],
        }

    def decorate_customer_detail(self, target, customer: dict[str, Any], messages: list[dict[str, Any]]):
        return self._decorate_customer_row(target, customer), [self._decorate_message_row(target, msg) for msg in messages]

    def search_messages(self, q: str, limit: int = 50) -> dict[str, Any]:
        targets = self._targets()
        results: list[dict[str, Any]] = []
        like_term = f"%{q}%"
        for target in targets:
            conn = self._open_target(target)
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT
                        m.id AS message_id,
                        m.content,
                        m.message_type,
                        m.is_from_kefu,
                        COALESCE(m.timestamp_parsed, m.created_at) AS timestamp,
                        c.id AS customer_id,
                        c.name AS customer_name,
                        c.channel AS customer_channel,
                        k.name AS kefu_name,
                        k.department AS kefu_department
                    FROM messages m
                    JOIN customers c ON m.customer_id = c.id
                    JOIN kefus k ON c.kefu_id = k.id
                    WHERE m.content LIKE ? AND m.message_type = 'text'
                    ORDER BY COALESCE(m.timestamp_parsed, m.created_at) DESC
                    LIMIT ?
                    """,
                    (like_term, limit),
                )
                for row in cursor.fetchall():
                    result = dict(row)
                    result["message_id"] = self._encode(target, result["message_id"])
                    result["customer_id"] = self._encode(target, result["customer_id"])
                    result["device_serial"] = target.device_serial
                    content = result["content"] or ""
                    lower_content = content.lower()
                    lower_q = q.lower()
                    pos = lower_content.find(lower_q)
                    if pos != -1:
                        start = max(0, pos - 30)
                        end = min(len(content), pos + len(q) + 30)
                        preview = content[start:end]
                        if start > 0:
                            preview = "..." + preview
                        if end < len(content):
                            preview = preview + "..."
                        result["content_preview"] = preview
                        result["match_position"] = pos
                    else:
                        result["content_preview"] = content[:60] + ("..." if len(content) > 60 else "")
                        result["match_position"] = -1
                    results.append(result)
            finally:
                conn.close()
        results.sort(key=lambda row: row.get("timestamp") or "", reverse=True)
        results = results[:limit]
        return {
            "db_path": self._federated_label(targets),
            "query": q,
            "total": len(results),
            "results": results,
        }

    def get_resource_filter_options(self) -> dict[str, Any]:
        targets = self._targets()
        streamers: set[str] = set()
        agents: dict[int, dict[str, Any]] = {}
        devices: dict[str, dict[str, Any]] = {}
        counts = {"images": 0, "voice": 0, "videos": 0}
        for target in targets:
            conn = self._open_target(target)
            try:
                cursor = conn.cursor()
                devices[target.device_serial] = {
                    "serial": target.device_serial,
                    "model": self._normalize_device_model(conn),
                }
                cursor.execute(
                    """
                    SELECT DISTINCT c.name
                    FROM customers c
                    WHERE EXISTS (
                        SELECT 1 FROM messages m
                        JOIN images i ON i.message_id = m.id
                        WHERE m.customer_id = c.id
                    )
                    OR EXISTS (
                        SELECT 1 FROM messages m
                        WHERE m.customer_id = c.id
                        AND m.message_type IN ('voice', 'video')
                    )
                    ORDER BY c.name
                    """
                )
                streamers.update(row["name"] for row in cursor.fetchall())
                cursor.execute("SELECT id, name, department FROM kefus ORDER BY name")
                for row in cursor.fetchall():
                    global_id = self._encode(target, row["id"])
                    agents[global_id] = {
                        "id": global_id,
                        "name": row["name"],
                        "department": row["department"],
                    }
                cursor.execute("SELECT COUNT(*) as count FROM images")
                counts["images"] += cursor.fetchone()["count"]
                cursor.execute("SELECT COUNT(*) as count FROM messages WHERE message_type = 'voice'")
                counts["voice"] += cursor.fetchone()["count"]
                cursor.execute("SELECT COUNT(*) as count FROM messages WHERE message_type = 'video'")
                counts["videos"] += cursor.fetchone()["count"]
            finally:
                conn.close()
        return {
            "db_path": self._federated_label(targets),
            "streamers": sorted(streamers),
            "agents": sorted(agents.values(), key=lambda row: row["name"]),
            "devices": sorted(devices.values(), key=lambda row: row["serial"]),
            "counts": counts,
        }

    def list_images(
        self,
        limit: int = 50,
        offset: int = 0,
        search: str | None = None,
        streamer: str | None = None,
        kefu_id: int | None = None,
        device_serial: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        sort_by: str | None = "created_at",
        sort_order: str | None = "desc",
    ) -> dict[str, Any]:
        targets = self._targets(device_serial=device_serial)
        scoped_kefu = self.resolve_kefu_filter(kefu_id) if kefu_id is not None else None
        items: list[dict[str, Any]] = []
        for target in targets:
            if scoped_kefu and str(scoped_kefu[0].db_path) != str(target.db_path):
                continue
            conn = self._open_target(target)
            try:
                cursor = conn.cursor()
                where_conditions = []
                params: list[Any] = []
                if search:
                    where_conditions.append("(c.name LIKE ? OR c.channel LIKE ?)")
                    like_term = f"%{search}%"
                    params.extend([like_term, like_term])
                if streamer:
                    where_conditions.append("c.name = ?")
                    params.append(streamer)
                if scoped_kefu and str(scoped_kefu[0].db_path) == str(target.db_path):
                    where_conditions.append("c.kefu_id = ?")
                    params.append(scoped_kefu[1])
                if date_from:
                    where_conditions.append("i.created_at >= ?")
                    params.append(date_from)
                if date_to:
                    where_conditions.append("i.created_at <= ? || ' 23:59:59'")
                    params.append(date_to)
                where_clause = ""
                if where_conditions:
                    where_clause = "WHERE " + " AND ".join(where_conditions)
                cursor.execute(
                    f"""
                    SELECT
                        i.id,
                        i.message_id,
                        i.file_path,
                        i.file_name,
                        i.original_bounds,
                        i.width,
                        i.height,
                        i.file_size,
                        i.created_at,
                        m.customer_id,
                        m.content AS message_content,
                        m.is_from_kefu,
                        m.timestamp_parsed AS message_timestamp,
                        c.name AS streamer_name,
                        c.channel,
                        c.kefu_id,
                        k.name AS kefu_name,
                        k.department AS kefu_department
                    FROM images i
                    JOIN messages m ON i.message_id = m.id
                    JOIN customers c ON m.customer_id = c.id
                    JOIN kefus k ON c.kefu_id = k.id
                    {where_clause}
                    """,
                    tuple(params),
                )
                for row in cursor.fetchall():
                    items.append(self._decorate_image_row(target, dict(row)))
            finally:
                conn.close()
        sort_map = {
            "created_at": lambda row: row.get("created_at") or "",
            "file_name": lambda row: row.get("file_name") or "",
            "file_size": lambda row: row.get("file_size") or 0,
            "streamer_name": lambda row: row.get("streamer_name") or "",
            "kefu_name": lambda row: row.get("kefu_name") or "",
            "width": lambda row: row.get("width") or 0,
            "height": lambda row: row.get("height") or 0,
        }
        items.sort(key=sort_map.get(sort_by or "created_at", sort_map["created_at"]), reverse=(sort_order or "desc").lower() != "asc")
        return {
            "db_path": self._federated_label(targets),
            "total": len(items),
            "limit": limit,
            "offset": offset,
            "items": items[offset : offset + limit],
        }

    def list_voice_messages(
        self,
        limit: int = 50,
        offset: int = 0,
        search: str | None = None,
        streamer: str | None = None,
        kefu_id: int | None = None,
        device_serial: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        sort_by: str | None = "created_at",
        sort_order: str | None = "desc",
    ) -> dict[str, Any]:
        targets = self._targets(device_serial=device_serial)
        scoped_kefu = self.resolve_kefu_filter(kefu_id) if kefu_id is not None else None
        items: list[dict[str, Any]] = []
        for target in targets:
            if scoped_kefu and str(scoped_kefu[0].db_path) != str(target.db_path):
                continue
            conn = self._open_target(target)
            try:
                cursor = conn.cursor()
                where_conditions = ["m.message_type = 'voice'"]
                params: list[Any] = []
                if search:
                    where_conditions.append("(c.name LIKE ? OR c.channel LIKE ? OR m.content LIKE ?)")
                    like_term = f"%{search}%"
                    params.extend([like_term, like_term, like_term])
                if streamer:
                    where_conditions.append("c.name = ?")
                    params.append(streamer)
                if scoped_kefu and str(scoped_kefu[0].db_path) == str(target.db_path):
                    where_conditions.append("c.kefu_id = ?")
                    params.append(scoped_kefu[1])
                if date_from:
                    where_conditions.append("m.created_at >= ?")
                    params.append(date_from)
                if date_to:
                    where_conditions.append("m.created_at <= ? || ' 23:59:59'")
                    params.append(date_to)
                where_clause = "WHERE " + " AND ".join(where_conditions)
                cursor.execute(
                    f"""
                    SELECT
                        m.id,
                        m.customer_id,
                        m.content,
                        m.is_from_kefu,
                        m.timestamp_raw,
                        m.timestamp_parsed,
                        m.extra_info,
                        m.created_at,
                        c.name AS streamer_name,
                        c.channel,
                        c.kefu_id,
                        k.name AS kefu_name,
                        k.department AS kefu_department
                    FROM messages m
                    JOIN customers c ON m.customer_id = c.id
                    JOIN kefus k ON c.kefu_id = k.id
                    {where_clause}
                    """,
                    tuple(params),
                )
                for row in cursor.fetchall():
                    item = self._decorate_voice_row(target, dict(row))
                    extra = _json_loads(item.get("extra_info"), {}) or {}
                    item["voice_duration"] = extra.get("voice_duration")
                    item["voice_file_path"] = extra.get("voice_file_path")
                    item["voice_file_size"] = extra.get("voice_file_size")
                    voice_path = item.get("voice_file_path")
                    if voice_path:
                        full_path = PROJECT_ROOT / voice_path if not Path(voice_path).is_absolute() else Path(voice_path)
                        item["voice_file_exists"] = full_path.exists()
                    else:
                        item["voice_file_exists"] = False
                    items.append(item)
            finally:
                conn.close()
        sort_map = {
            "created_at": lambda row: row.get("created_at") or "",
            "streamer_name": lambda row: row.get("streamer_name") or "",
            "kefu_name": lambda row: row.get("kefu_name") or "",
            "timestamp": lambda row: row.get("timestamp_parsed") or row.get("created_at") or "",
        }
        items.sort(key=sort_map.get(sort_by or "created_at", sort_map["created_at"]), reverse=(sort_order or "desc").lower() != "asc")
        return {
            "db_path": self._federated_label(targets),
            "total": len(items),
            "limit": limit,
            "offset": offset,
            "items": items[offset : offset + limit],
        }

    def list_video_messages(
        self,
        limit: int = 50,
        offset: int = 0,
        search: str | None = None,
        streamer: str | None = None,
        kefu_id: int | None = None,
        device_serial: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        sort_by: str | None = "created_at",
        sort_order: str | None = "desc",
    ) -> dict[str, Any]:
        targets = self._targets(device_serial=device_serial)
        scoped_kefu = self.resolve_kefu_filter(kefu_id) if kefu_id is not None else None
        items: list[dict[str, Any]] = []
        for target in targets:
            if scoped_kefu and str(scoped_kefu[0].db_path) != str(target.db_path):
                continue
            conn = self._open_target(target)
            try:
                cursor = conn.cursor()
                where_conditions = ["m.message_type = 'video'"]
                params: list[Any] = []
                if search:
                    where_conditions.append("(c.name LIKE ? OR c.channel LIKE ?)")
                    like_term = f"%{search}%"
                    params.extend([like_term, like_term])
                if streamer:
                    where_conditions.append("c.name = ?")
                    params.append(streamer)
                if scoped_kefu and str(scoped_kefu[0].db_path) == str(target.db_path):
                    where_conditions.append("c.kefu_id = ?")
                    params.append(scoped_kefu[1])
                if date_from:
                    where_conditions.append("m.created_at >= ?")
                    params.append(date_from)
                if date_to:
                    where_conditions.append("m.created_at <= ? || ' 23:59:59'")
                    params.append(date_to)
                where_clause = "WHERE " + " AND ".join(where_conditions)
                cursor.execute(
                    f"""
                    SELECT
                        m.id,
                        m.customer_id,
                        m.content,
                        m.is_from_kefu,
                        m.timestamp_raw,
                        m.timestamp_parsed,
                        m.extra_info,
                        m.created_at,
                        c.name AS streamer_name,
                        c.channel,
                        c.kefu_id,
                        k.name AS kefu_name,
                        k.department AS kefu_department,
                        v.id AS video_id,
                        v.file_path AS video_file_path,
                        v.file_name AS video_file_name,
                        v.duration AS video_duration,
                        v.duration_seconds,
                        v.file_size AS video_file_size,
                        v.thumbnail_path
                    FROM messages m
                    JOIN customers c ON m.customer_id = c.id
                    JOIN kefus k ON c.kefu_id = k.id
                    LEFT JOIN videos v ON v.message_id = m.id
                    {where_clause}
                    """,
                    tuple(params),
                )
                for row in cursor.fetchall():
                    items.append(self._decorate_video_row(target, dict(row)))
            finally:
                conn.close()
        sort_map = {
            "created_at": lambda row: row.get("created_at") or "",
            "streamer_name": lambda row: row.get("streamer_name") or "",
            "kefu_name": lambda row: row.get("kefu_name") or "",
            "timestamp": lambda row: row.get("timestamp_parsed") or row.get("created_at") or "",
        }
        items.sort(key=sort_map.get(sort_by or "created_at", sort_map["created_at"]), reverse=(sort_order or "desc").lower() != "asc")
        return {
            "db_path": self._federated_label(targets),
            "total": len(items),
            "limit": limit,
            "offset": offset,
            "items": items[offset : offset + limit],
        }

    def ensure_streamer_tables(self):
        from services.conversation_storage import open_shared_sqlite

        conn = open_shared_sqlite(str(get_control_db_path()), row_factory=True)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS streamer_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                avatar_url TEXT,
                gender TEXT,
                age INTEGER,
                location TEXT,
                height INTEGER,
                weight INTEGER,
                education TEXT,
                occupation TEXT,
                interests TEXT,
                social_platforms TEXT,
                notes TEXT,
                custom_fields TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS streamer_personas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                streamer_id TEXT NOT NULL REFERENCES streamer_profiles(id),
                communication_style TEXT,
                language_patterns TEXT,
                tone TEXT,
                engagement_level TEXT,
                response_time_pattern TEXT,
                active_hours TEXT,
                topics_of_interest TEXT,
                personality_traits TEXT,
                dimensions TEXT,
                analysis_summary TEXT,
                recommendations TEXT,
                analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                analyzed_messages_count INTEGER DEFAULT 0,
                model_used TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
        return conn

    @staticmethod
    def generate_streamer_id(name: str, avatar_url: str | None) -> str:
        import hashlib

        key = f"{name}|{avatar_url or ''}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

    def _profile_row_to_dict(self, row) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "name": row["name"],
            "gender": row["gender"],
            "age": row["age"],
            "location": row["location"],
            "height": row["height"],
            "weight": row["weight"],
            "education": row["education"],
            "occupation": row["occupation"],
            "interests": _json_loads(row["interests"]),
            "social_platforms": _json_loads(row["social_platforms"]),
            "notes": row["notes"],
            "custom_fields": _json_loads(row["custom_fields"]),
        }

    def list_streamers(self, limit: int = 50, offset: int = 0, search: str | None = None) -> dict[str, Any]:
        targets = self._targets()
        aggregates: dict[str, dict[str, Any]] = {}
        for target in targets:
            conn = self._open_target(target)
            try:
                cursor = conn.cursor()
                params: list[Any] = []
                where_clause = ""
                if search:
                    where_clause = "WHERE c.name LIKE ?"
                    params.append(f"%{search}%")
                cursor.execute(
                    f"""
                    SELECT
                        c.name,
                        MIN(c.created_at) as first_seen,
                        MAX(COALESCE(
                            (SELECT MAX(COALESCE(m.timestamp_parsed, m.created_at))
                             FROM messages m WHERE m.customer_id = c.id),
                            c.updated_at
                        )) as last_seen,
                        COUNT(DISTINCT c.id) as conversation_count,
                        COALESCE(SUM((SELECT COUNT(*) FROM messages m WHERE m.customer_id = c.id)), 0) as total_messages,
                        GROUP_CONCAT(DISTINCT k.name) as agents,
                        GROUP_CONCAT(DISTINCT c.channel) as channels
                    FROM customers c
                    JOIN kefus k ON c.kefu_id = k.id
                    {where_clause}
                    GROUP BY c.name
                    """,
                    tuple(params),
                )
                for row in cursor.fetchall():
                    data = dict(row)
                    item = aggregates.setdefault(
                        data["name"],
                        {
                            "id": self.generate_streamer_id(data["name"], None),
                            "name": data["name"],
                            "avatar_url": None,
                            "conversation_count": 0,
                            "total_messages": 0,
                            "first_seen": data["first_seen"],
                            "last_seen": data["last_seen"],
                            "agents": set(),
                            "channels": set(),
                        },
                    )
                    item["conversation_count"] += data["conversation_count"]
                    item["total_messages"] += data["total_messages"]
                    if data["first_seen"] and (item["first_seen"] is None or data["first_seen"] < item["first_seen"]):
                        item["first_seen"] = data["first_seen"]
                    if data["last_seen"] and (item["last_seen"] is None or data["last_seen"] > item["last_seen"]):
                        item["last_seen"] = data["last_seen"]
                    item["agents"].update([v for v in (data["agents"] or "").split(",") if v])
                    item["channels"].update([v for v in (data["channels"] or "").split(",") if v])
            finally:
                conn.close()

        items = list(aggregates.values())
        items.sort(key=lambda row: row.get("last_seen") or "", reverse=True)
        sliced = items[offset : offset + limit]
        control_conn = self.ensure_streamer_tables()
        try:
            cursor = control_conn.cursor()
            for item in sliced:
                cursor.execute("SELECT * FROM streamer_profiles WHERE id = ?", (item["id"],))
                item["profile"] = self._profile_row_to_dict(cursor.fetchone())
                cursor.execute("SELECT id FROM streamer_personas WHERE streamer_id = ? LIMIT 1", (item["id"],))
                item["has_persona"] = cursor.fetchone() is not None
                item["agents"] = sorted(item["agents"])
                item["channels"] = sorted(item["channels"])
        finally:
            control_conn.close()
        return {
            "db_path": self._federated_label(targets),
            "total": len(items),
            "limit": limit,
            "offset": offset,
            "items": sliced,
        }

    def get_streamer_detail(self, streamer_id: str) -> dict[str, Any]:
        targets = self._targets()
        control_conn = self.ensure_streamer_tables()
        try:
            cursor = control_conn.cursor()
            cursor.execute("SELECT name, avatar_url FROM streamer_profiles WHERE id = ?", (streamer_id,))
            profile_row = cursor.fetchone()
            if profile_row:
                name = profile_row["name"]
                avatar_url = profile_row["avatar_url"]
            else:
                name = None
                avatar_url = None
                for target in targets:
                    conn = self._open_target(target)
                    try:
                        c = conn.cursor()
                        c.execute("SELECT DISTINCT name FROM customers")
                        for row in c.fetchall():
                            candidate_name = row["name"]
                            if self.generate_streamer_id(candidate_name, None) == streamer_id:
                                name = candidate_name
                                break
                    finally:
                        conn.close()
                    if name:
                        cursor.execute(
                            "INSERT OR IGNORE INTO streamer_profiles (id, name, avatar_url) VALUES (?, ?, ?)",
                            (streamer_id, name, avatar_url),
                        )
                        control_conn.commit()
                        break
                if not name:
                    raise HTTPException(status_code=404, detail="Streamer not found")

            conversations = []
            total_messages = 0
            first_interaction = None
            last_interaction = None
            for target in targets:
                conn = self._open_target(target)
                try:
                    c = conn.cursor()
                    c.execute(
                        """
                        SELECT
                            c.id,
                            c.channel,
                            c.last_message_preview,
                            k.name as agent_name,
                            k.department as agent_department,
                            (SELECT COUNT(*) FROM messages m WHERE m.customer_id = c.id) as message_count,
                            (SELECT MAX(COALESCE(m.timestamp_parsed, m.created_at))
                             FROM messages m WHERE m.customer_id = c.id) as last_message_at,
                            (SELECT MIN(COALESCE(m.timestamp_parsed, m.created_at))
                             FROM messages m WHERE m.customer_id = c.id) as first_message_at
                        FROM customers c
                        JOIN kefus k ON c.kefu_id = k.id
                        WHERE c.name = ?
                        ORDER BY last_message_at DESC
                        """,
                        (name,),
                    )
                    for row in c.fetchall():
                        conv = dict(row)
                        conv["id"] = self._encode(target, conv["id"])
                        conv["device_serial"] = target.device_serial
                        conversations.append(conv)
                        total_messages += conv["message_count"]
                        if conv["first_message_at"] and (first_interaction is None or conv["first_message_at"] < first_interaction):
                            first_interaction = conv["first_message_at"]
                        if conv["last_message_at"] and (last_interaction is None or conv["last_message_at"] > last_interaction):
                            last_interaction = conv["last_message_at"]
                finally:
                    conn.close()

            cursor.execute("SELECT * FROM streamer_profiles WHERE id = ?", (streamer_id,))
            profile = self._profile_row_to_dict(cursor.fetchone()) or {}
            cursor.execute(
                """
                SELECT * FROM streamer_personas
                WHERE streamer_id = ?
                ORDER BY analyzed_at DESC
                LIMIT 1
                """,
                (streamer_id,),
            )
            persona_row = cursor.fetchone()
            persona = None
            if persona_row:
                persona = {
                    "id": persona_row["id"],
                    "streamer_id": persona_row["streamer_id"],
                    "communication_style": persona_row["communication_style"],
                    "language_patterns": _json_loads(persona_row["language_patterns"], []),
                    "tone": persona_row["tone"],
                    "engagement_level": persona_row["engagement_level"],
                    "response_time_pattern": persona_row["response_time_pattern"],
                    "active_hours": _json_loads(persona_row["active_hours"], []),
                    "topics_of_interest": _json_loads(persona_row["topics_of_interest"], []),
                    "personality_traits": _json_loads(persona_row["personality_traits"], []),
                    "dimensions": _json_loads(persona_row["dimensions"], []),
                    "analysis_summary": persona_row["analysis_summary"],
                    "recommendations": _json_loads(persona_row["recommendations"], []),
                    "analyzed_at": persona_row["analyzed_at"],
                    "analyzed_messages_count": persona_row["analyzed_messages_count"],
                    "model_used": persona_row["model_used"],
                }

            return {
                "db_path": self._federated_label(targets),
                "streamer": {
                    "id": streamer_id,
                    "name": name,
                    "avatar_url": avatar_url,
                    "profile": profile,
                    "conversations": conversations,
                    "persona": persona,
                    "total_messages": total_messages,
                    "first_interaction": first_interaction,
                    "last_interaction": last_interaction,
                },
            }
        finally:
            control_conn.close()

    def update_streamer_profile(self, streamer_id: str, profile_data: dict[str, Any]) -> dict[str, Any]:
        conn = self.ensure_streamer_tables()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM streamer_profiles WHERE id = ?", (streamer_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Streamer profile not found")
            cursor.execute(
                """
                UPDATE streamer_profiles SET
                    gender = COALESCE(?, gender),
                    age = COALESCE(?, age),
                    location = COALESCE(?, location),
                    height = COALESCE(?, height),
                    weight = COALESCE(?, weight),
                    education = COALESCE(?, education),
                    occupation = COALESCE(?, occupation),
                    interests = COALESCE(?, interests),
                    social_platforms = COALESCE(?, social_platforms),
                    notes = COALESCE(?, notes),
                    custom_fields = COALESCE(?, custom_fields),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    profile_data.get("gender"),
                    profile_data.get("age"),
                    profile_data.get("location"),
                    profile_data.get("height"),
                    profile_data.get("weight"),
                    profile_data.get("education"),
                    profile_data.get("occupation"),
                    json.dumps(profile_data.get("interests")) if profile_data.get("interests") else None,
                    json.dumps(profile_data.get("social_platforms")) if profile_data.get("social_platforms") else None,
                    profile_data.get("notes"),
                    json.dumps(profile_data.get("custom_fields")) if profile_data.get("custom_fields") else None,
                    streamer_id,
                ),
            )
            conn.commit()
            return {"success": True, "message": "Profile updated"}
        finally:
            conn.close()

    async def analyze_streamer_persona(self, streamer_id: str) -> dict[str, Any]:
        detail = self.get_streamer_detail(streamer_id)["streamer"]
        name = detail["name"]
        message_texts: list[str] = []
        for target in self._targets():
            conn = self._open_target(target)
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT m.content
                    FROM messages m
                    JOIN customers c ON m.customer_id = c.id
                    WHERE c.name = ? AND m.is_from_kefu = 0 AND m.content IS NOT NULL
                    ORDER BY COALESCE(m.timestamp_parsed, m.created_at) ASC
                    LIMIT 500
                    """,
                    (name,),
                )
                message_texts.extend(row["content"] for row in cursor.fetchall() if row["content"])
            finally:
                conn.close()

        if len(message_texts) < 5:
            raise HTTPException(status_code=400, detail="Not enough messages for analysis (minimum 5 required)")

        try:
            from services.ai_analysis import analyze_streamer_persona as run_ai_analysis

            analysis_result = await run_ai_analysis(name, message_texts)
        except ImportError:
            analysis_result = self._mock_persona_analysis(name, message_texts)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"AI analysis failed: {str(exc)}")

        conn = self.ensure_streamer_tables()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO streamer_personas (
                    streamer_id, communication_style, language_patterns, tone,
                    engagement_level, response_time_pattern, active_hours,
                    topics_of_interest, personality_traits, dimensions,
                    analysis_summary, recommendations, analyzed_messages_count, model_used
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    streamer_id,
                    analysis_result.get("communication_style"),
                    json.dumps(analysis_result.get("language_patterns", [])),
                    analysis_result.get("tone"),
                    analysis_result.get("engagement_level"),
                    analysis_result.get("response_time_pattern"),
                    json.dumps(analysis_result.get("active_hours", [])),
                    json.dumps(analysis_result.get("topics_of_interest", [])),
                    json.dumps(analysis_result.get("personality_traits", [])),
                    json.dumps(analysis_result.get("dimensions", [])),
                    analysis_result.get("analysis_summary"),
                    json.dumps(analysis_result.get("recommendations", [])),
                    len(message_texts),
                    analysis_result.get("model_used", "unknown"),
                ),
            )
            conn.commit()
            return {
                "success": True,
                "message": f"Analyzed {len(message_texts)} messages",
                "persona_id": cursor.lastrowid,
            }
        finally:
            conn.close()

    def delete_streamer(self, streamer_id: str) -> dict[str, Any]:
        detail = self.get_streamer_detail(streamer_id)["streamer"]
        name = detail["name"]
        control_conn = self.ensure_streamer_tables()
        try:
            cursor = control_conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM streamer_profiles WHERE id = ?", (streamer_id,))
            has_profile = cursor.fetchone()["count"] > 0
            cursor.execute("SELECT COUNT(*) as count FROM streamer_personas WHERE streamer_id = ?", (streamer_id,))
            persona_count = cursor.fetchone()["count"]
            cursor.execute("DELETE FROM streamer_personas WHERE streamer_id = ?", (streamer_id,))
            cursor.execute("DELETE FROM streamer_profiles WHERE id = ?", (streamer_id,))
            control_conn.commit()
        finally:
            control_conn.close()

        for target in self._targets():
            conn = self._open_target(target)
            try:
                conn.execute("DELETE FROM customers WHERE name = ?", (name,))
                conn.commit()
            finally:
                conn.close()

        return {
            "success": True,
            "message": f"Deleted streamer '{name}' and all associated data",
            "deleted": {
                "streamer_id": streamer_id,
                "streamer_name": name,
                "conversations_removed": len(detail["conversations"]),
                "messages_removed": detail["total_messages"],
                "profile_removed": has_profile,
                "personas_removed": persona_count,
            },
            "db_path": self._federated_label(self._targets()),
        }

    @staticmethod
    def _mock_persona_analysis(name: str, messages: list[str]) -> dict[str, Any]:
        return {
            "communication_style": "Casual and friendly",
            "language_patterns": ["使用表情符号", "简短回复", "口语化表达"],
            "tone": "Warm and approachable",
            "engagement_level": "High - responds quickly and engages actively",
            "response_time_pattern": "Most active during evening hours",
            "active_hours": ["18:00-22:00", "12:00-14:00"],
            "topics_of_interest": ["直播内容", "粉丝互动", "收入变现"],
            "personality_traits": ["外向", "热情", "好奇心强"],
            "dimensions": [
                {"name": "外向性", "value": 75, "description": "善于表达,喜欢互动"},
                {"name": "开放性", "value": 68, "description": "愿意尝试新事物"},
                {"name": "尽责性", "value": 55, "description": "一般的时间管理能力"},
                {"name": "宜人性", "value": 82, "description": "友好且合作"},
                {"name": "情绪稳定性", "value": 60, "description": "情绪波动正常"},
            ],
            "analysis_summary": f"基于 {len(messages)} 条消息的分析，{name} 展现出热情友好的沟通风格。",
            "recommendations": [
                "在晚间18:00-22:00时段联系效果更好",
                "使用轻松友好的语气进行沟通",
            ],
            "model_used": "mock",
        }


federated_reads = FederatedReadService()
