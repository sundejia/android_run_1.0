"""
Customers router.

Provides endpoints to explore customers and their conversations so the UI
can drill into the data behind the dashboard cards.
"""

from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query

from services.federated_reads import federated_reads
from wecom_automation.database.schema import get_connection, get_db_path

from services.ai_review_details import extract_ai_review_breakdown, extract_ai_review_reason

router = APIRouter()


def _open_db(db_path: Optional[str]) -> Tuple[Any, str]:
    """
    Open the SQLite database and ensure it exists.

    Args:
        db_path: Optional override path supplied by the caller.

    Returns:
        Tuple of (connection, resolved_path_str)
    """
    resolved_path = get_db_path(db_path)
    if not resolved_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Database not found at {resolved_path}",
        )
    return get_connection(str(resolved_path)), str(resolved_path)


def _customer_base_query(where_clause: str = "", order_clause: str = "") -> str:
    """Reusable SELECT for customer summaries.

    Note: Uses GROUP BY c.id to prevent duplicate rows when a kefu is
    associated with multiple devices via kefu_devices table.
    """
    return f"""
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
            COALESCE(GROUP_CONCAT(DISTINCT d.serial), 'unknown') AS device_serial,
            MAX(d.model) AS device_model,
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
        LEFT JOIN kefu_devices kd ON k.id = kd.kefu_id
        LEFT JOIN devices d ON kd.device_id = d.id
        {where_clause}
        GROUP BY c.id
        {order_clause}
    """


@router.get("/filter-options")
async def get_filter_options(
    db_path: Optional[str] = Query(
        None,
        description="Optional override for the conversations database path.",
    ),
):
    """
    Get available filter options (streamers, agents, devices) for the conversations list.
    """
    if db_path is None:
        return federated_reads.get_customer_filter_options()

    conn, resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()

        # Get unique streamer names
        cursor.execute("SELECT DISTINCT name FROM customers ORDER BY name")
        streamers = [row["name"] for row in cursor.fetchall()]

        # Get unique agents (kefus)
        cursor.execute("SELECT id, name, department FROM kefus ORDER BY name")
        agents = [{"id": row["id"], "name": row["name"], "department": row["department"]} for row in cursor.fetchall()]

        # Get unique devices
        cursor.execute("SELECT DISTINCT serial, model FROM devices ORDER BY serial")
        devices = [{"serial": row["serial"], "model": row["model"]} for row in cursor.fetchall()]

        return {
            "db_path": resolved_path,
            "streamers": streamers,
            "agents": agents,
            "devices": devices,
        }
    finally:
        conn.close()


@router.get("")
async def list_customers(
    db_path: Optional[str] = Query(
        None,
        description="Optional override for the conversations database path.",
    ),
    limit: int = Query(
        50,
        ge=1,
        le=200,
        description="Maximum number of customers to return.",
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Number of customers to skip (for pagination).",
    ),
    search: Optional[str] = Query(
        None,
        description="Optional search term to filter by name or channel.",
    ),
    streamer: Optional[str] = Query(
        None,
        description="Filter by streamer (customer) name.",
    ),
    kefu_id: Optional[int] = Query(
        None,
        description="Filter by agent (kefu) ID.",
    ),
    device_serial: Optional[str] = Query(
        None,
        description="Filter by device serial number.",
    ),
    date_from: Optional[str] = Query(
        None,
        description="Filter messages from this date (ISO format, e.g., 2024-01-01).",
    ),
    date_to: Optional[str] = Query(
        None,
        description="Filter messages until this date (ISO format, e.g., 2024-12-31).",
    ),
    sort_by: Optional[str] = Query(
        None,
        description="Column to sort by: name, kefu_name, device_serial, last_message_at, message_count.",
    ),
    sort_order: Optional[str] = Query(
        "desc",
        description="Sort order: asc or desc.",
    ),
):
    """
    List customers with conversation metadata for dashboard drill-downs.
    Supports filtering by streamer, agent, device, and date range.
    Supports sorting by column with sort_by and sort_order parameters.
    """
    if db_path is None:
        return federated_reads.list_customers(
            limit=limit,
            offset=offset,
            search=search,
            streamer=streamer,
            kefu_id=kefu_id,
            device_serial=device_serial,
            date_from=date_from,
            date_to=date_to,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    conn, resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()

        where_conditions: List[str] = []
        params: List[Any] = []

        # Text search filter
        if search:
            where_conditions.append("(c.name LIKE ? OR c.channel LIKE ?)")
            like_term = f"%{search}%"
            params.extend([like_term, like_term])

        # Streamer name filter
        if streamer:
            where_conditions.append("c.name = ?")
            params.append(streamer)

        # Agent (kefu) filter
        if kefu_id is not None:
            where_conditions.append("c.kefu_id = ?")
            params.append(kefu_id)

        # Device filter - need to join through kefu_devices
        if device_serial:
            where_conditions.append("d.serial = ?")
            params.append(device_serial)

        # Date range filter (based on last_message_at or last_message_date)
        # We need to use a subquery since last_message_at is computed
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
            # Add time to include the end date fully
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

        # Build ORDER BY clause based on sort parameters
        # Map frontend column names to SQL expressions
        sort_column_map = {
            "name": "c.name",
            "kefu_name": "k.name",
            "device_serial": "COALESCE(d.serial, 'unknown')",
            "last_message_at": "COALESCE(last_message_at, c.last_message_date, c.updated_at, c.created_at)",
            "message_count": "message_count",
            "sent_by_kefu": "sent_by_kefu",
            "sent_by_customer": "sent_by_customer",
            "channel": "c.channel",
            "last_message_preview": "c.last_message_preview",
        }

        # Determine sort direction (default desc)
        direction = "ASC" if sort_order and sort_order.lower() == "asc" else "DESC"

        # Build order clause
        if sort_by and sort_by in sort_column_map:
            order_expr = sort_column_map[sort_by]
        else:
            # Default sort by last message time
            order_expr = "COALESCE(last_message_at, c.last_message_date, c.updated_at, c.created_at)"

        order_clause = f"""
            ORDER BY {order_expr} {direction}
            LIMIT ?
            OFFSET ?
        """

        query = _customer_base_query(
            where_clause=where_clause,
            order_clause=order_clause,
        )

        cursor.execute(query, (*params, limit, offset))
        items = [dict(row) for row in cursor.fetchall()]

        # Build count query with same filters
        count_query = """
            SELECT COUNT(DISTINCT c.id) as count 
            FROM customers c
            JOIN kefus k ON c.kefu_id = k.id
            LEFT JOIN kefu_devices kd ON k.id = kd.kefu_id
            LEFT JOIN devices d ON kd.device_id = d.id
        """
        if where_clause:
            count_query += f" {where_clause}"

        cursor.execute(count_query, tuple(params))
        total = cursor.fetchone()["count"]

        return {
            "db_path": resolved_path,
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": items,
        }
    finally:
        conn.close()


@router.delete("/{customer_id}")
async def delete_customer(
    customer_id: int,
    db_path: Optional[str] = Query(
        None,
        description="Optional override for the conversations database path.",
    ),
    device_serial: Optional[str] = Query(
        None,
        description="Optional device serial used to disambiguate federated customer IDs.",
    ),
):
    """
    Delete a customer (conversation) and all associated data.

    Due to CASCADE DELETE constraints, this will also delete:
    - messages entries (all messages in this conversation)
    - images entries (all images via messages)

    This operation is irreversible, but data can be re-synced from the device.
    """
    if db_path is None:
        target, local_customer_id = federated_reads.resolve_customer(customer_id, device_serial=device_serial)
        db_path = str(target.db_path)
        customer_id = local_customer_id

    conn, resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()

        # Verify the customer exists and get stats for the response
        cursor.execute(
            """
            SELECT 
                c.id,
                c.name,
                c.channel,
                c.kefu_id,
                k.name AS kefu_name,
                (SELECT COUNT(*) FROM messages m WHERE m.customer_id = c.id) AS message_count,
                (SELECT COUNT(*) FROM images i 
                 JOIN messages m ON i.message_id = m.id 
                 WHERE m.customer_id = c.id) AS image_count
            FROM customers c
            JOIN kefus k ON c.kefu_id = k.id
            WHERE c.id = ?
            """,
            (customer_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Customer not found")

        customer_info = dict(row)

        # Delete the customer (cascades to messages, images)
        cursor.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
        conn.commit()

        return {
            "success": True,
            "message": f"Deleted conversation with '{customer_info['name']}' and all associated data",
            "deleted": {
                "customer_id": customer_info["id"],
                "customer_name": customer_info["name"],
                "channel": customer_info["channel"],
                "kefu_name": customer_info["kefu_name"],
                "messages_removed": customer_info["message_count"],
                "images_removed": customer_info["image_count"],
            },
            "db_path": resolved_path,
        }
    finally:
        conn.close()


@router.get("/messages/search")
async def search_messages(
    db_path: Optional[str] = Query(
        None,
        description="Optional override for the conversations database path.",
    ),
    q: str = Query(
        ...,
        min_length=1,
        description="Search query to find in message content.",
    ),
    limit: int = Query(
        50,
        ge=1,
        le=200,
        description="Maximum number of results to return.",
    ),
):
    """
    Search messages by content across all conversations.
    Returns matching messages with their conversation (customer) context.
    """
    if db_path is None:
        return federated_reads.search_messages(q=q, limit=limit)

    conn, resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()

        # Search for messages containing the query text
        like_term = f"%{q}%"
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
                k.department AS kefu_department,
                COALESCE(d.serial, 'unknown') AS device_serial
            FROM messages m
            JOIN customers c ON m.customer_id = c.id
            JOIN kefus k ON c.kefu_id = k.id
            LEFT JOIN kefu_devices kd ON k.id = kd.kefu_id
            LEFT JOIN devices d ON kd.device_id = d.id
            WHERE m.content LIKE ? AND m.message_type = 'text'
            ORDER BY COALESCE(m.timestamp_parsed, m.created_at) DESC
            LIMIT ?
            """,
            (like_term, limit),
        )

        results = []
        for row in cursor.fetchall():
            result = dict(row)
            # Add a content preview with the search term highlighted position
            content = result["content"] or ""
            # Find the position of the search term (case-insensitive)
            lower_content = content.lower()
            lower_q = q.lower()
            pos = lower_content.find(lower_q)

            # Create a preview with context around the match
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

        return {
            "db_path": resolved_path,
            "query": q,
            "total": len(results),
            "results": results,
        }
    finally:
        conn.close()


@router.get("/{customer_id}")
async def get_customer_detail(
    customer_id: int,
    db_path: Optional[str] = Query(
        None,
        description="Optional override for the conversations database path.",
    ),
    device_serial: Optional[str] = Query(
        None,
        description="Optional device serial used to disambiguate federated customer IDs.",
    ),
    messages_limit: int = Query(
        150,
        ge=1,
        le=500,
        description="Maximum number of messages to return for the customer.",
    ),
    messages_offset: int = Query(
        0,
        ge=0,
        description="Number of messages to skip (for pagination).",
    ),
):
    """
    Return detailed information for a single customer, including messages.
    """
    resolved_target = None
    if db_path is None:
        resolved_target, local_customer_id = federated_reads.resolve_customer(customer_id, device_serial=device_serial)
        db_path = str(resolved_target.db_path)
        customer_id = local_customer_id

    conn, resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()

        cursor.execute(
            _customer_base_query(
                where_clause="WHERE c.id = ?",
                order_clause="LIMIT 1",
            ),
            (customer_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Customer not found")

        customer = dict(row)

        cursor.execute(
            """
            SELECT
                m.id,
                m.content,
                m.message_type,
                m.is_from_kefu,
                m.timestamp_raw,
                m.timestamp_parsed,
                m.extra_info,
                m.created_at,
                i.ai_review_score,
                i.ai_review_decision,
                i.ai_review_details_json,
                i.ai_review_at,
                i.ai_review_status,
                i.ai_review_error,
                i.ai_review_requested_at,
                v.id as video_table_id,
                v.ai_review_score as video_ai_review_score,
                v.ai_review_status as video_ai_review_status,
                v.ai_review_error as video_ai_review_error,
                v.ai_review_requested_at as video_ai_review_requested_at,
                v.ai_review_at as video_ai_review_at,
                v.ai_review_frames_json as video_ai_review_frames_json
            FROM messages m
            LEFT JOIN images i ON i.message_id = m.id
            LEFT JOIN videos v ON v.message_id = m.id
            WHERE m.customer_id = ?
            ORDER BY COALESCE(m.timestamp_parsed, m.created_at) ASC
            LIMIT ?
            OFFSET ?
            """,
            (customer_id, messages_limit, messages_offset),
        )
        messages = []
        for row in cursor.fetchall():
            raw = dict(row)
            details_json = raw.pop("ai_review_details_json", None)
            score_reasons, penalties = extract_ai_review_breakdown(details_json)
            raw["ai_review_reason"] = extract_ai_review_reason(details_json)
            raw["ai_review_score_reasons"] = score_reasons
            raw["ai_review_penalties"] = penalties
            messages.append(raw)

        cursor.execute(
            """
            SELECT message_type, COUNT(*) as count
            FROM messages
            WHERE customer_id = ?
            GROUP BY message_type
            """,
            (customer_id,),
        )
        message_breakdown: Dict[str, int] = {row["message_type"]: row["count"] for row in cursor.fetchall()}

        if resolved_target is not None:
            customer, messages = federated_reads.decorate_customer_detail(resolved_target, customer, messages)

        return {
            "db_path": resolved_path,
            "customer": customer,
            "messages": messages,
            "message_breakdown": message_breakdown,
        }
    finally:
        conn.close()
