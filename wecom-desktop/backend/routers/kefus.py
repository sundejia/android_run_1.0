"""
Kefus router.

Provides endpoints to browse 客服 (customer service agents) and drill into their
associated customers so the UI can jump from the dashboard statistic card into
per-kefu detail pages.
"""

from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query

from wecom_automation.database.schema import get_connection, get_db_path

router = APIRouter()


def _open_db(db_path: Optional[str]) -> Tuple[Any, str]:
    """Open the SQLite database and ensure it exists."""
    resolved_path = get_db_path(db_path)
    if not resolved_path.exists():
        raise HTTPException(status_code=404, detail=f"Database not found at {resolved_path}")
    return get_connection(str(resolved_path)), str(resolved_path)


def _kefu_base_query(where_clause: str = "", order_clause: str = "") -> str:
    """Reusable SELECT for kefu summaries with coverage metrics."""
    return f"""
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
        {where_clause}
        {order_clause}
    """


def _get_devices_for_kefu(conn, kefu_id: int) -> List[Dict[str, Any]]:
    """Get all devices associated with a kefu."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT d.id, d.serial, d.model, d.manufacturer, d.android_version,
               kd.created_at as linked_at
        FROM devices d
        JOIN kefu_devices kd ON d.id = kd.device_id
        WHERE kd.kefu_id = ?
        ORDER BY kd.created_at DESC
        """,
        (kefu_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def _customer_base_query(where_clause: str = "", order_clause: str = "") -> str:
    """Customer summary query scoped for a specific kefu."""
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
        {order_clause}
    """


@router.get("")
async def list_kefus(
    db_path: Optional[str] = Query(None, description="Optional override for the conversations database path."),
    limit: int = Query(
        50,
        ge=1,
        le=200,
        description="Maximum number of kefus to return.",
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Number of kefus to skip (for pagination).",
    ),
    search: Optional[str] = Query(
        None,
        description="Optional search term to filter by name, department, or device serial.",
    ),
):
    """
    List 客服 records with aggregate coverage stats.
    Kefus are identified by name + department, not by device.
    """
    conn, resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()

        where_clause = ""
        search_params: List[str] = []
        if search:
            # Search by name, department, or any linked device serial
            where_clause = """
                WHERE k.name LIKE ? OR k.department LIKE ? OR k.id IN (
                    SELECT kd.kefu_id FROM kefu_devices kd
                    JOIN devices d ON kd.device_id = d.id
                    WHERE d.serial LIKE ?
                )
            """
            like_term = f"%{search}%"
            search_params = [like_term, like_term, like_term]

        query = _kefu_base_query(
            where_clause=where_clause,
            order_clause="""
                ORDER BY COALESCE(last_message_at, k.updated_at, k.created_at) DESC
                LIMIT ?
                OFFSET ?
            """,
        )

        cursor.execute(query, (*search_params, limit, offset))
        rows = cursor.fetchall()

        # Enrich each kefu with their devices list
        items = []
        for row in rows:
            item = dict(row)
            item["devices"] = _get_devices_for_kefu(conn, item["id"])
            items.append(item)

        count_query = "SELECT COUNT(*) as count FROM kefus k"
        if where_clause:
            count_query += f" {where_clause}"
        cursor.execute(count_query, tuple(search_params))
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


@router.delete("/{kefu_id}")
async def delete_kefu(
    kefu_id: int,
    db_path: Optional[str] = Query(None, description="Optional override for the conversations database path."),
):
    """
    Delete a 客服 and all associated data.

    Due to CASCADE DELETE constraints, this will also delete:
    - kefu_devices entries (device-kefu links)
    - customers entries (all customers of this kefu)
    - messages entries (all messages via customers)
    - images entries (all images via messages)

    This operation is irreversible, but data can be re-synced from the device.
    """
    conn, resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()

        # First, verify the kefu exists and get its stats for the response
        cursor.execute(
            """
            SELECT 
                k.id,
                k.name,
                k.department,
                (SELECT COUNT(*) FROM kefu_devices kd WHERE kd.kefu_id = k.id) AS device_count,
                (SELECT COUNT(*) FROM customers c WHERE c.kefu_id = k.id) AS customer_count,
                (SELECT COUNT(*) FROM messages m JOIN customers c ON m.customer_id = c.id WHERE c.kefu_id = k.id) AS message_count
            FROM kefus k
            WHERE k.id = ?
            """,
            (kefu_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Kefu not found")

        kefu_info = dict(row)

        # Delete the kefu (cascades to kefu_devices, customers, messages, images)
        cursor.execute("DELETE FROM kefus WHERE id = ?", (kefu_id,))
        conn.commit()

        return {
            "success": True,
            "message": f"Deleted kefu '{kefu_info['name']}' and all associated data",
            "deleted": {
                "kefu_id": kefu_info["id"],
                "kefu_name": kefu_info["name"],
                "department": kefu_info["department"],
                "device_links_removed": kefu_info["device_count"],
                "customers_removed": kefu_info["customer_count"],
                "messages_removed": kefu_info["message_count"],
            },
            "db_path": resolved_path,
        }
    finally:
        conn.close()


@router.get("/{kefu_id}")
async def get_kefu_detail(
    kefu_id: int,
    db_path: Optional[str] = Query(None, description="Optional override for the conversations database path."),
    customers_limit: int = Query(
        50,
        ge=1,
        le=200,
        description="Maximum number of customers to return for the kefu.",
    ),
    customers_offset: int = Query(
        0,
        ge=0,
        description="Number of customers to skip (for pagination).",
    ),
):
    """
    Return detailed information for a single 客服, including their customers and devices.
    """
    conn, resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()

        cursor.execute(
            _kefu_base_query(
                where_clause="WHERE k.id = ?",
                order_clause="LIMIT 1",
            ),
            (kefu_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Kefu not found")
        kefu = dict(row)

        # Add devices list to kefu
        kefu["devices"] = _get_devices_for_kefu(conn, kefu_id)

        cursor.execute(
            _customer_base_query(
                where_clause="WHERE c.kefu_id = ?",
                order_clause="""
                    ORDER BY COALESCE(last_message_at, c.last_message_date, c.updated_at, c.created_at) DESC
                    LIMIT ?
                    OFFSET ?
                """,
            ),
            (kefu_id, customers_limit, customers_offset),
        )
        customers = [dict(row) for row in cursor.fetchall()]

        cursor.execute(
            "SELECT COUNT(*) as count FROM customers c WHERE c.kefu_id = ?",
            (kefu_id,),
        )
        customers_total = cursor.fetchone()["count"]

        cursor.execute(
            """
            SELECT m.message_type, COUNT(*) as count
            FROM messages m
            JOIN customers c ON m.customer_id = c.id
            WHERE c.kefu_id = ?
            GROUP BY m.message_type
            """,
            (kefu_id,),
        )
        message_breakdown: Dict[str, int] = {row["message_type"]: row["count"] for row in cursor.fetchall()}

        return {
            "db_path": resolved_path,
            "kefu": kefu,
            "customers": customers,
            "customers_total": customers_total,
            "message_breakdown": message_breakdown,
        }
    finally:
        conn.close()
