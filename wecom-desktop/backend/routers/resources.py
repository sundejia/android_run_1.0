"""
Resources router.

Provides endpoints to explore media resources (images, voice messages, videos)
stored in the database with their associated conversation context.
"""

import asyncio
import hashlib
import json
import subprocess
import tempfile
import time
import uuid
import httpx
from pathlib import Path
from typing import Any, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from services.federated_reads import federated_reads
from wecom_automation.database.schema import get_connection, get_db_path, PROJECT_ROOT
from utils.ffmpeg_bins import resolve_ffmpeg_binary

# Cache directory for video thumbnails
THUMBNAIL_CACHE_DIR = PROJECT_ROOT / ".cache" / "thumbnails"
THUMBNAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Volcengine ASR API configuration
VOLCENGINE_SUBMIT_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
VOLCENGINE_QUERY_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"

# Import settings loader
from .settings import load_settings as load_app_settings


def get_volcengine_settings():
    """Get Volcengine ASR settings from app settings."""
    settings = load_app_settings()
    asr_settings = settings.get("volcengine_asr", {})
    return {
        "enabled": asr_settings.get("enabled", True),
        "api_key": asr_settings.get("api_key", ""),
        "resource_id": asr_settings.get("resource_id", "volc.seedasr.auc"),
    }


router = APIRouter()


class TranscribeRequest(BaseModel):
    """Request body for voice transcription."""

    pass


class TranscribeResponse(BaseModel):
    """Response for voice transcription."""

    success: bool
    message_id: int
    transcription: Optional[str] = None
    error: Optional[str] = None


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


# ─────────────────────────────────────────────────────────────────────────────
# Images endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/images")
async def list_images(
    db_path: Optional[str] = Query(
        None,
        description="Optional override for the conversations database path.",
    ),
    limit: int = Query(
        50,
        ge=1,
        le=500,
        description="Maximum number of images to return.",
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Number of images to skip (for pagination).",
    ),
    search: Optional[str] = Query(
        None,
        description="Search in customer name or channel.",
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
        description="Filter images from this date (ISO format).",
    ),
    date_to: Optional[str] = Query(
        None,
        description="Filter images until this date (ISO format).",
    ),
    sort_by: Optional[str] = Query(
        "created_at",
        description="Column to sort by: created_at, file_name, file_size, streamer_name, kefu_name.",
    ),
    sort_order: Optional[str] = Query(
        "desc",
        description="Sort order: asc or desc.",
    ),
):
    """
    List all images with their conversation context.
    Supports filtering, sorting, and pagination.
    """
    if db_path is None:
        return federated_reads.list_images(
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

        # Search filter
        if search:
            where_conditions.append("(c.name LIKE ? OR c.channel LIKE ?)")
            like_term = f"%{search}%"
            params.extend([like_term, like_term])

        # Streamer filter
        if streamer:
            where_conditions.append("c.name = ?")
            params.append(streamer)

        # Agent filter
        if kefu_id is not None:
            where_conditions.append("c.kefu_id = ?")
            params.append(kefu_id)

        # Device filter
        if device_serial:
            where_conditions.append("d.serial = ?")
            params.append(device_serial)

        # Date range filters
        if date_from:
            where_conditions.append("i.created_at >= ?")
            params.append(date_from)

        if date_to:
            where_conditions.append("i.created_at <= ? || ' 23:59:59'")
            params.append(date_to)

        where_clause = ""
        if where_conditions:
            where_clause = "WHERE " + " AND ".join(where_conditions)

        # Sort mapping
        sort_column_map = {
            "created_at": "i.created_at",
            "file_name": "i.file_name",
            "file_size": "i.file_size",
            "streamer_name": "c.name",
            "kefu_name": "k.name",
            "width": "i.width",
            "height": "i.height",
        }

        direction = "ASC" if sort_order and sort_order.lower() == "asc" else "DESC"
        sort_col = sort_column_map.get(sort_by, "i.created_at")

        query = f"""
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
                k.department AS kefu_department,
                COALESCE(d.serial, 'unknown') AS device_serial,
                d.model AS device_model
            FROM images i
            JOIN messages m ON i.message_id = m.id
            JOIN customers c ON m.customer_id = c.id
            JOIN kefus k ON c.kefu_id = k.id
            LEFT JOIN kefu_devices kd ON k.id = kd.kefu_id
            LEFT JOIN devices d ON kd.device_id = d.id
            {where_clause}
            ORDER BY {sort_col} {direction}
            LIMIT ?
            OFFSET ?
        """

        cursor.execute(query, (*params, limit, offset))
        items = [dict(row) for row in cursor.fetchall()]

        # Count query
        count_query = f"""
            SELECT COUNT(DISTINCT i.id) as count
            FROM images i
            JOIN messages m ON i.message_id = m.id
            JOIN customers c ON m.customer_id = c.id
            JOIN kefus k ON c.kefu_id = k.id
            LEFT JOIN kefu_devices kd ON k.id = kd.kefu_id
            LEFT JOIN devices d ON kd.device_id = d.id
            {where_clause}
        """
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


@router.get("/images/{image_id}")
async def get_image_detail(
    image_id: int,
    db_path: Optional[str] = Query(
        None,
        description="Optional override for the conversations database path.",
    ),
):
    """
    Get detailed information about a specific image.
    """
    resolved_target = None
    if db_path is None:
        resolved_target, local_image_id = federated_reads.resolve_image(image_id)
        db_path = str(resolved_target.db_path)
        image_id = local_image_id

    conn, resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()

        cursor.execute(
            """
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
                m.timestamp_raw,
                m.extra_info,
                c.name AS streamer_name,
                c.channel,
                c.kefu_id,
                k.name AS kefu_name,
                k.department AS kefu_department,
                COALESCE(d.serial, 'unknown') AS device_serial,
                d.model AS device_model
            FROM images i
            JOIN messages m ON i.message_id = m.id
            JOIN customers c ON m.customer_id = c.id
            JOIN kefus k ON c.kefu_id = k.id
            LEFT JOIN kefu_devices kd ON k.id = kd.kefu_id
            LEFT JOIN devices d ON kd.device_id = d.id
            WHERE i.id = ?
            """,
            (image_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Image not found")

        image = dict(row)
        if resolved_target is not None:
            image = federated_reads._decorate_image_row(resolved_target, image)

        return {
            "db_path": resolved_path,
            "image": image,
        }
    finally:
        conn.close()


@router.get("/images/by-message/{message_id}")
async def get_image_by_message_id(
    message_id: int,
    db_path: Optional[str] = Query(
        None,
        description="Optional override for the conversations database path.",
    ),
):
    """
    Get image information for a specific message ID.

    This is useful for the conversation detail page where we have message IDs
    but need to look up the corresponding image record.
    """
    resolved_target = None
    if db_path is None:
        resolved_target, local_message_id = federated_reads.resolve_message(message_id)
        db_path = str(resolved_target.db_path)
        message_id = local_message_id

    conn, resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                i.id AS image_id,
                i.message_id,
                i.file_path,
                i.file_name,
                i.original_bounds,
                i.width,
                i.height,
                i.file_size,
                i.created_at
            FROM images i
            WHERE i.message_id = ?
            """,
            (message_id,),
        )
        row = cursor.fetchone()
        if not row:
            # No image record for this message
            return {
                "db_path": resolved_path,
                "image": None,
            }

        image = dict(row)
        if resolved_target is not None:
            image = federated_reads._decorate_image_info(resolved_target, image)

        return {
            "db_path": resolved_path,
            "image": image,
        }
    finally:
        conn.close()


@router.delete("/images/{image_id}")
async def delete_image(
    image_id: int,
    db_path: Optional[str] = Query(
        None,
        description="Optional override for the conversations database path.",
    ),
):
    """
    Delete an image record from the database.
    Note: This only removes the database record, not the actual file.
    """
    resolved_target = None
    if db_path is None:
        resolved_target, local_image_id = federated_reads.resolve_image(image_id)
        db_path = str(resolved_target.db_path)
        image_id = local_image_id

    conn, resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()

        # Get image info before deletion
        cursor.execute(
            """
            SELECT
                i.id,
                i.file_path,
                i.file_name,
                c.name AS streamer_name,
                c.channel,
                m.customer_id
            FROM images i
            JOIN messages m ON i.message_id = m.id
            JOIN customers c ON m.customer_id = c.id
            WHERE i.id = ?
            """,
            (image_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Image not found")

        image_info = dict(row)

        # Delete the image record
        cursor.execute("DELETE FROM images WHERE id = ?", (image_id,))
        conn.commit()

        deleted = {
            "image_id": image_info["id"],
            "file_path": image_info["file_path"],
            "file_name": image_info["file_name"],
            "streamer_name": image_info["streamer_name"],
            "channel": image_info["channel"],
            "customer_id": image_info["customer_id"],
        }
        if resolved_target is not None:
            deleted["image_id"] = federated_reads._encode(resolved_target, deleted["image_id"])
            deleted["customer_id"] = federated_reads._encode(resolved_target, deleted["customer_id"])

        return {
            "success": True,
            "message": f"Deleted image '{image_info['file_name']}'",
            "deleted": deleted,
            "db_path": resolved_path,
        }
    finally:
        conn.close()


@router.get("/images/{image_id}/file")
async def get_image_file(
    image_id: int,
    db_path: Optional[str] = Query(
        None,
        description="Optional override for the conversations database path.",
    ),
):
    """
    Serve the actual image file for display.
    Returns the image file directly.
    """
    if db_path is None:
        target, local_image_id = federated_reads.resolve_image(image_id)
        db_path = str(target.db_path)
        image_id = local_image_id

    conn, resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT file_path, file_name FROM images WHERE id = ?",
            (image_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Image not found")

        file_path = row["file_path"]
        file_name = row["file_name"] or "image.png"

        # Resolve the full path relative to project root
        if not Path(file_path).is_absolute():
            full_path = PROJECT_ROOT / file_path
        else:
            full_path = Path(file_path)

        if not full_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Image file not found at {full_path}",
            )

        # Determine media type based on extension
        extension = full_path.suffix.lower()
        media_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }
        media_type = media_types.get(extension, "image/png")

        return FileResponse(
            path=str(full_path),
            media_type=media_type,
            filename=file_name,
        )
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Voice messages endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/voice")
async def list_voice_messages(
    db_path: Optional[str] = Query(
        None,
        description="Optional override for the conversations database path.",
    ),
    limit: int = Query(
        50,
        ge=1,
        le=500,
        description="Maximum number of voice messages to return.",
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Number of voice messages to skip (for pagination).",
    ),
    search: Optional[str] = Query(
        None,
        description="Search in customer name, channel, or transcription.",
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
        description="Filter voice messages from this date (ISO format).",
    ),
    date_to: Optional[str] = Query(
        None,
        description="Filter voice messages until this date (ISO format).",
    ),
    sort_by: Optional[str] = Query(
        "created_at",
        description="Column to sort by: created_at, streamer_name, kefu_name, duration.",
    ),
    sort_order: Optional[str] = Query(
        "desc",
        description="Sort order: asc or desc.",
    ),
):
    """
    List all voice messages with their conversation context.
    Voice messages are identified by message_type = 'voice'.
    """
    if db_path is None:
        return federated_reads.list_voice_messages(
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

        where_conditions: List[str] = ["m.message_type = 'voice'"]
        params: List[Any] = []

        # Search filter (includes transcription in content)
        if search:
            where_conditions.append("(c.name LIKE ? OR c.channel LIKE ? OR m.content LIKE ?)")
            like_term = f"%{search}%"
            params.extend([like_term, like_term, like_term])

        # Streamer filter
        if streamer:
            where_conditions.append("c.name = ?")
            params.append(streamer)

        # Agent filter
        if kefu_id is not None:
            where_conditions.append("c.kefu_id = ?")
            params.append(kefu_id)

        # Device filter
        if device_serial:
            where_conditions.append("d.serial = ?")
            params.append(device_serial)

        # Date range filters
        if date_from:
            where_conditions.append("m.created_at >= ?")
            params.append(date_from)

        if date_to:
            where_conditions.append("m.created_at <= ? || ' 23:59:59'")
            params.append(date_to)

        where_clause = "WHERE " + " AND ".join(where_conditions)

        # Sort mapping
        sort_column_map = {
            "created_at": "m.created_at",
            "streamer_name": "c.name",
            "kefu_name": "k.name",
            "timestamp": "COALESCE(m.timestamp_parsed, m.created_at)",
        }

        direction = "ASC" if sort_order and sort_order.lower() == "asc" else "DESC"
        sort_col = sort_column_map.get(sort_by, "m.created_at")

        query = f"""
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
                COALESCE(d.serial, 'unknown') AS device_serial,
                d.model AS device_model
            FROM messages m
            JOIN customers c ON m.customer_id = c.id
            JOIN kefus k ON c.kefu_id = k.id
            LEFT JOIN kefu_devices kd ON k.id = kd.kefu_id
            LEFT JOIN devices d ON kd.device_id = d.id
            {where_clause}
            ORDER BY {sort_col} {direction}
            LIMIT ?
            OFFSET ?
        """

        cursor.execute(query, (*params, limit, offset))
        raw_items = [dict(row) for row in cursor.fetchall()]

        # Parse extra_info for each item to extract voice-specific fields
        items = []
        for item in raw_items:
            # Parse extra_info JSON
            extra = {}
            if item.get("extra_info"):
                try:
                    extra = json.loads(item["extra_info"])
                except json.JSONDecodeError:
                    pass

            # Add parsed voice fields to item
            item["voice_duration"] = extra.get("voice_duration")
            item["voice_file_path"] = extra.get("voice_file_path")
            item["voice_file_size"] = extra.get("voice_file_size")

            # Check if file actually exists
            file_path = item.get("voice_file_path")
            if file_path:
                if not Path(file_path).is_absolute():
                    full_path = PROJECT_ROOT / file_path
                else:
                    full_path = Path(file_path)
                item["voice_file_exists"] = full_path.exists()
            else:
                item["voice_file_exists"] = False

            items.append(item)

        # Count query
        count_query = f"""
            SELECT COUNT(*) as count
            FROM messages m
            JOIN customers c ON m.customer_id = c.id
            JOIN kefus k ON c.kefu_id = k.id
            LEFT JOIN kefu_devices kd ON k.id = kd.kefu_id
            LEFT JOIN devices d ON kd.device_id = d.id
            {where_clause}
        """
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


@router.get("/voice/by-message/{message_id}")
async def get_voice_by_message_id(
    message_id: int,
    db_path: Optional[str] = Query(
        None,
        description="Optional override for the conversations database path.",
    ),
):
    """
    Get voice information for a specific message ID.

    Returns voice metadata including file path, duration, and playback URL.
    """
    resolved_target = None
    if db_path is None:
        resolved_target, local_message_id = federated_reads.resolve_message(message_id)
        db_path = str(resolved_target.db_path)
        message_id = local_message_id

    conn, resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT 
                m.id,
                m.customer_id,
                m.content,
                m.is_from_kefu,
                m.extra_info,
                m.created_at,
                c.name AS streamer_name,
                c.channel
            FROM messages m
            JOIN customers c ON m.customer_id = c.id
            WHERE m.id = ? AND m.message_type = 'voice'
            """,
            (message_id,),
        )
        row = cursor.fetchone()
        if not row:
            return {
                "db_path": resolved_path,
                "message_id": message_id,
                "voice": None,
            }

        item = dict(row)

        # Parse extra_info for voice-specific fields
        extra = {}
        if item.get("extra_info"):
            try:
                extra = json.loads(item["extra_info"])
            except json.JSONDecodeError:
                pass

        # Add parsed voice fields
        voice_duration = extra.get("voice_duration")
        voice_file_path = extra.get("voice_file_path")
        voice_file_size = extra.get("voice_file_size")

        # Check if file exists
        voice_file_exists = False
        if voice_file_path:
            if not Path(voice_file_path).is_absolute():
                full_path = PROJECT_ROOT / voice_file_path
            else:
                full_path = Path(voice_file_path)
            voice_file_exists = full_path.exists()
            if voice_file_exists and voice_file_size is None:
                voice_file_size = full_path.stat().st_size

        voice = {
            "message_id": item["id"],
            "customer_id": item["customer_id"],
            "content": item["content"],
            "is_from_kefu": item["is_from_kefu"],
            "created_at": item["created_at"],
            "streamer_name": item["streamer_name"],
            "channel": item["channel"],
            "duration": voice_duration,
            "file_path": voice_file_path,
            "file_size": voice_file_size,
            "file_exists": voice_file_exists,
        }
        if resolved_target is not None:
            voice = federated_reads._decorate_voice_info(resolved_target, voice)

        return {
            "db_path": resolved_path,
            "message_id": voice["message_id"],
            "voice": voice,
        }
    finally:
        conn.close()


@router.get("/voice/{message_id}/file")
async def serve_voice_file(
    message_id: int,
    db_path: Optional[str] = Query(
        None,
        description="Optional override for the conversations database path.",
    ),
):
    """
    Serve the actual voice audio file for playback.
    Returns the audio file directly (WAV format).
    """
    if db_path is None:
        target, local_message_id = federated_reads.resolve_message(message_id)
        db_path = str(target.db_path)
        message_id = local_message_id

    conn, resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT extra_info FROM messages WHERE id = ? AND message_type = 'voice'",
            (message_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Voice message not found")

        # Parse extra_info to get the file path
        extra_info = {}
        if row["extra_info"]:
            try:
                extra_info = json.loads(row["extra_info"])
            except json.JSONDecodeError:
                pass

        file_path = extra_info.get("voice_file_path")
        if not file_path:
            raise HTTPException(
                status_code=404,
                detail="Voice file not downloaded yet.",
            )

        # Resolve the full path relative to project root
        if not Path(file_path).is_absolute():
            full_path = PROJECT_ROOT / file_path
        else:
            full_path = Path(file_path)

        if not full_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Voice file not found at {full_path}",
            )

        # Determine media type based on extension
        extension = full_path.suffix.lower()
        media_types = {
            ".wav": "audio/wav",
            ".mp3": "audio/mpeg",
            ".ogg": "audio/ogg",
            ".silk": "audio/silk",
            ".amr": "audio/amr",
        }
        media_type = media_types.get(extension, "audio/wav")

        return FileResponse(
            path=str(full_path),
            media_type=media_type,
            filename=full_path.name,
        )
    finally:
        conn.close()


@router.delete("/voice/{message_id}")
async def delete_voice_message(
    message_id: int,
    db_path: Optional[str] = Query(
        None,
        description="Optional override for the conversations database path.",
    ),
):
    """
    Delete a voice message record from the database.
    """
    resolved_target = None
    if db_path is None:
        resolved_target, local_message_id = federated_reads.resolve_message(message_id)
        db_path = str(resolved_target.db_path)
        message_id = local_message_id

    conn, resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()

        # Get message info before deletion
        cursor.execute(
            """
            SELECT
                m.id,
                m.content,
                m.is_from_kefu,
                m.message_type,
                c.id AS customer_id,
                c.name AS streamer_name,
                c.channel
            FROM messages m
            JOIN customers c ON m.customer_id = c.id
            WHERE m.id = ? AND m.message_type = 'voice'
            """,
            (message_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Voice message not found")

        message_info = dict(row)

        # Delete the message record (will also cascade delete any related images)
        cursor.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        conn.commit()

        deleted = {
            "message_id": message_info["id"],
            "content": message_info["content"],
            "is_from_kefu": message_info["is_from_kefu"],
            "streamer_name": message_info["streamer_name"],
            "channel": message_info["channel"],
            "customer_id": message_info["customer_id"],
        }
        if resolved_target is not None:
            deleted["message_id"] = federated_reads._encode(resolved_target, deleted["message_id"])
            deleted["customer_id"] = federated_reads._encode(resolved_target, deleted["customer_id"])

        return {
            "success": True,
            "message": f"Deleted voice message from conversation with '{message_info['streamer_name']}'",
            "deleted": deleted,
            "db_path": resolved_path,
        }
    finally:
        conn.close()


@router.post("/voice/{message_id}/transcribe")
async def transcribe_voice_message(
    message_id: int,
    db_path: Optional[str] = Query(
        None,
        description="Optional override for the conversations database path.",
    ),
):
    """
    Transcribe a voice message using Volcengine ASR (Automatic Speech Recognition).

    This endpoint:
    1. Fetches the voice file from the database
    2. Converts WAV to MP3 if needed (Volcengine prefers MP3)
    3. Submits the audio to Volcengine ASR API
    4. Polls for transcription result
    5. Updates the message content with the transcription
    """
    resolved_target = None
    if db_path is None:
        resolved_target, local_message_id = federated_reads.resolve_message(message_id)
        db_path = str(resolved_target.db_path)
        message_id = local_message_id

    conn, resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()

        # Get voice message info
        cursor.execute(
            "SELECT id, content, extra_info FROM messages WHERE id = ? AND message_type = 'voice'",
            (message_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Voice message not found")

        # Parse extra_info to get the file path
        extra_info = {}
        if row["extra_info"]:
            try:
                extra_info = json.loads(row["extra_info"])
            except json.JSONDecodeError:
                pass

        voice_file_path = extra_info.get("voice_file_path")
        if not voice_file_path:
            raise HTTPException(
                status_code=404,
                detail="Voice file not downloaded yet.",
            )

        # Resolve the full path relative to project root
        if not Path(voice_file_path).is_absolute():
            full_path = PROJECT_ROOT / voice_file_path
        else:
            full_path = Path(voice_file_path)

        if not full_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Voice file not found at {full_path}",
            )

        # Get Volcengine settings
        volcengine_settings = get_volcengine_settings()

        if not volcengine_settings["enabled"]:
            raise HTTPException(
                status_code=400,
                detail="Voice transcription is disabled. Enable it in Settings.",
            )

        if not volcengine_settings["api_key"]:
            raise HTTPException(
                status_code=400,
                detail="Volcengine API key is not configured. Set it in Settings.",
            )

        # Generate a unique request ID
        request_id = str(uuid.uuid4())

        # Determine audio format from file extension
        extension = full_path.suffix.lower()
        audio_format = "wav"
        if extension == ".mp3":
            audio_format = "mp3"
        elif extension == ".wav":
            audio_format = "wav"
        elif extension == ".silk":
            audio_format = "silk"
        elif extension == ".amr":
            audio_format = "amr"

        # Read audio file and convert to base64 for upload
        import base64

        audio_data = full_path.read_bytes()
        audio_base64 = base64.b64encode(audio_data).decode("utf-8")

        # Submit to Volcengine ASR API
        headers = {
            "Content-Type": "application/json",
            "x-api-key": volcengine_settings["api_key"],
            "X-Api-Resource-Id": volcengine_settings["resource_id"],
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence": "-1",
        }

        submit_payload = {
            "user": {"uid": "wecom_automation"},
            "audio": {
                "data": audio_base64,
                "format": audio_format,
                "codec": "raw",
                "rate": 16000,
                "bits": 16,
                "channel": 1,
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "enable_ddc": False,
                "enable_speaker_info": False,
                "enable_channel_split": False,
                "show_utterances": False,
                "vad_segment": False,
                "sensitive_words_filter": "",
            },
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            # Submit the audio for transcription
            submit_response = await client.post(
                VOLCENGINE_SUBMIT_URL,
                headers=headers,
                json=submit_payload,
            )

            if submit_response.status_code != 200:
                raise HTTPException(
                    status_code=500,
                    detail=f"ASR API submit failed: {submit_response.text}",
                )

            submit_result = submit_response.json()

            # Check for immediate errors
            if submit_result.get("code") and submit_result.get("code") != 0:
                raise HTTPException(
                    status_code=500,
                    detail=f"ASR API error: {submit_result.get('message', 'Unknown error')}",
                )

            # Poll for result (query endpoint)
            query_headers = {
                "Content-Type": "application/json",
                "x-api-key": volcengine_settings["api_key"],
                "X-Api-Resource-Id": volcengine_settings["resource_id"],
                "X-Api-Request-Id": request_id,
            }

            # Poll for up to 60 seconds
            max_attempts = 30
            poll_interval = 2  # seconds
            transcription = None

            for attempt in range(max_attempts):
                await asyncio.sleep(poll_interval)

                query_response = await client.post(
                    VOLCENGINE_QUERY_URL,
                    headers=query_headers,
                    json={},
                )

                if query_response.status_code != 200:
                    continue

                query_result = query_response.json()

                # Check if transcription is complete
                # Response structure: {"result": {"text": "..."}, "audio_info": {...}}
                result = query_result.get("result", {})

                # Check for completion
                if result.get("text"):
                    transcription = result["text"]
                    break

                # Check for error codes (20000001 = processing, 20000002 = in queue)
                code = query_result.get("code")
                if code and code not in [0, 20000000, 20000001, 20000002]:
                    raise HTTPException(
                        status_code=500,
                        detail=f"ASR API query error: {query_result.get('message', 'Unknown error')} (code: {code})",
                    )

            if not transcription:
                raise HTTPException(
                    status_code=500,
                    detail="Transcription timed out. Please try again.",
                )

        # Update the message content with the transcription
        cursor.execute(
            "UPDATE messages SET content = ? WHERE id = ?",
            (transcription, message_id),
        )
        conn.commit()

        response_message_id = message_id
        if resolved_target is not None:
            response_message_id = federated_reads._encode(resolved_target, message_id)

        return {
            "success": True,
            "message_id": response_message_id,
            "transcription": transcription,
            "db_path": resolved_path,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Transcription failed: {str(e)}",
        )
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Video messages endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/videos")
async def list_video_messages(
    db_path: Optional[str] = Query(
        None,
        description="Optional override for the conversations database path.",
    ),
    limit: int = Query(
        50,
        ge=1,
        le=500,
        description="Maximum number of video messages to return.",
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Number of video messages to skip (for pagination).",
    ),
    search: Optional[str] = Query(
        None,
        description="Search in customer name or channel.",
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
        description="Filter video messages from this date (ISO format).",
    ),
    date_to: Optional[str] = Query(
        None,
        description="Filter video messages until this date (ISO format).",
    ),
    sort_by: Optional[str] = Query(
        "created_at",
        description="Column to sort by: created_at, streamer_name, kefu_name.",
    ),
    sort_order: Optional[str] = Query(
        "desc",
        description="Sort order: asc or desc.",
    ),
):
    """
    List all video messages with their conversation context.
    Video messages are identified by message_type = 'video'.
    """
    if db_path is None:
        return federated_reads.list_video_messages(
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

        where_conditions: List[str] = ["m.message_type = 'video'"]
        params: List[Any] = []

        # Search filter
        if search:
            where_conditions.append("(c.name LIKE ? OR c.channel LIKE ?)")
            like_term = f"%{search}%"
            params.extend([like_term, like_term])

        # Streamer filter
        if streamer:
            where_conditions.append("c.name = ?")
            params.append(streamer)

        # Agent filter
        if kefu_id is not None:
            where_conditions.append("c.kefu_id = ?")
            params.append(kefu_id)

        # Device filter
        if device_serial:
            where_conditions.append("d.serial = ?")
            params.append(device_serial)

        # Date range filters
        if date_from:
            where_conditions.append("m.created_at >= ?")
            params.append(date_from)

        if date_to:
            where_conditions.append("m.created_at <= ? || ' 23:59:59'")
            params.append(date_to)

        where_clause = "WHERE " + " AND ".join(where_conditions)

        # Sort mapping
        sort_column_map = {
            "created_at": "m.created_at",
            "streamer_name": "c.name",
            "kefu_name": "k.name",
            "timestamp": "COALESCE(m.timestamp_parsed, m.created_at)",
        }

        direction = "ASC" if sort_order and sort_order.lower() == "asc" else "DESC"
        sort_col = sort_column_map.get(sort_by, "m.created_at")

        query = f"""
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
                COALESCE(d.serial, 'unknown') AS device_serial,
                d.model AS device_model,
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
            LEFT JOIN kefu_devices kd ON k.id = kd.kefu_id
            LEFT JOIN devices d ON kd.device_id = d.id
            LEFT JOIN videos v ON v.message_id = m.id
            {where_clause}
            ORDER BY {sort_col} {direction}
            LIMIT ?
            OFFSET ?
        """

        cursor.execute(query, (*params, limit, offset))
        items = [dict(row) for row in cursor.fetchall()]

        # Count query
        count_query = f"""
            SELECT COUNT(*) as count
            FROM messages m
            JOIN customers c ON m.customer_id = c.id
            JOIN kefus k ON c.kefu_id = k.id
            LEFT JOIN kefu_devices kd ON k.id = kd.kefu_id
            LEFT JOIN devices d ON kd.device_id = d.id
            {where_clause}
        """
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


@router.get("/videos/{video_id}")
async def get_video_detail(
    video_id: int,
    db_path: Optional[str] = Query(
        None,
        description="Optional override for the conversations database path.",
    ),
):
    """
    Get detailed information about a specific video record.

    Note: video_id here refers to the videos table ID, not the message ID.
    """
    resolved_target = None
    if db_path is None:
        resolved_target, local_video_id = federated_reads.resolve_video(video_id)
        db_path = str(resolved_target.db_path)
        video_id = local_video_id

    conn, resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                v.id,
                v.message_id,
                v.file_path,
                v.file_name,
                v.duration,
                v.duration_seconds,
                v.thumbnail_path,
                v.width,
                v.height,
                v.file_size,
                v.created_at,
                m.customer_id,
                m.content AS message_content,
                m.is_from_kefu,
                m.timestamp_parsed AS message_timestamp,
                m.timestamp_raw,
                m.extra_info,
                c.name AS streamer_name,
                c.channel,
                c.kefu_id,
                k.name AS kefu_name,
                k.department AS kefu_department,
                COALESCE(d.serial, 'unknown') AS device_serial,
                d.model AS device_model
            FROM videos v
            JOIN messages m ON v.message_id = m.id
            JOIN customers c ON m.customer_id = c.id
            JOIN kefus k ON c.kefu_id = k.id
            LEFT JOIN kefu_devices kd ON k.id = kd.kefu_id
            LEFT JOIN devices d ON kd.device_id = d.id
            WHERE v.id = ?
            """,
            (video_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Video not found")

        video = dict(row)
        if resolved_target is not None:
            video["id"] = federated_reads._encode(resolved_target, video["id"])
            video["message_id"] = federated_reads._encode(resolved_target, video["message_id"])
            video["customer_id"] = federated_reads._encode(resolved_target, video["customer_id"])

        return {
            "db_path": resolved_path,
            "video": video,
        }
    finally:
        conn.close()


@router.get("/videos/by-message/{message_id}")
async def get_video_by_message_id(
    message_id: int,
    db_path: Optional[str] = Query(
        None,
        description="Optional override for the conversations database path.",
    ),
):
    """
    Get video information for a specific message ID.

    This is useful for the conversation detail page where we have message IDs
    but need to look up the corresponding video record.
    """
    resolved_target = None
    if db_path is None:
        resolved_target, local_message_id = federated_reads.resolve_message(message_id)
        db_path = str(resolved_target.db_path)
        message_id = local_message_id

    conn, resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                v.id AS video_id,
                v.message_id,
                v.file_path,
                v.file_name,
                v.duration,
                v.duration_seconds,
                v.thumbnail_path,
                v.width,
                v.height,
                v.file_size,
                v.created_at,
                v.ai_review_score,
                v.ai_review_frames_json,
                v.ai_review_at,
                v.ai_review_status,
                v.ai_review_error,
                v.ai_review_requested_at
            FROM videos v
            WHERE v.message_id = ?
            """,
            (message_id,),
        )
        row = cursor.fetchone()
        if not row:
            # No video record for this message - it might not have been downloaded
            return {
                "db_path": resolved_path,
                "video": None,
            }

        video = dict(row)
        if resolved_target is not None:
            video = federated_reads._decorate_video_info(resolved_target, video)

        return {
            "db_path": resolved_path,
            "video": video,
        }
    finally:
        conn.close()


REVIEW_FRAMES_REL_PREFIX = "conversation_videos/review_frames/"


def _expected_video_review_frames_dir(video_file_path: str | None) -> Path | None:
    """Directory where review JPEGs live: same parent as video, subfolder named like the video stem."""
    if not video_file_path or video_file_path.startswith("[not downloaded]"):
        return None
    p = Path(video_file_path).expanduser()
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve()
    else:
        p = p.resolve()
    return p.parent / p.stem


def _review_frame_path_allowed(norm: str, video_file_path: str | None) -> bool:
    """Allow legacy review_frames/msg_* paths or frames under <video_dir>/<video_stem>/."""
    if ".." in norm:
        return False
    if norm.startswith(REVIEW_FRAMES_REL_PREFIX):
        return True
    expected = _expected_video_review_frames_dir(video_file_path)
    if expected is None:
        return False
    try:
        full = (PROJECT_ROOT / norm).resolve()
        full.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return False
    try:
        full.relative_to(expected.resolve())
        return True
    except ValueError:
        return False


@router.get("/videos/by-message/{message_id}/review-frame/{frame_index}")
async def get_video_review_frame(
    message_id: int,
    frame_index: int,
    db_path: Optional[str] = Query(
        None,
        description="Optional conversations database path (must match review JSON source).",
    ),
):
    """Serve one extracted JPEG frame from video AI review (whitelist path only)."""
    if db_path is None:
        target, local_message_id = federated_reads.resolve_message(message_id)
        db_path = str(target.db_path)
        message_id = local_message_id

    if frame_index < 0 or frame_index > 3:
        raise HTTPException(status_code=400, detail="frame_index must be 0..3")

    conn, _resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT file_path, ai_review_frames_json FROM videos WHERE message_id = ?",
            (message_id,),
        )
        row = cursor.fetchone()
        if not row or not row["ai_review_frames_json"]:
            raise HTTPException(status_code=404, detail="No review frames for this message")

        try:
            frames = json.loads(row["ai_review_frames_json"])
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail="Invalid review frames JSON")

        if not isinstance(frames, list):
            raise HTTPException(status_code=500, detail="Invalid review frames JSON")

        rel: str | None = None
        for item in frames:
            if not isinstance(item, dict):
                continue
            raw_idx = item.get("frame_index", -1)
            try:
                idx = int(raw_idx)
            except (TypeError, ValueError):
                continue
            if idx == frame_index:
                fp = item.get("file_path")
                if isinstance(fp, str) and fp.strip():
                    rel = fp.strip()
                break

        if not rel:
            raise HTTPException(status_code=404, detail="Frame index not found")

        norm = rel.replace("\\", "/")
        if not _review_frame_path_allowed(norm, row["file_path"]):
            raise HTTPException(status_code=400, detail="Invalid frame path")

        full_path = (PROJECT_ROOT / norm).resolve()
        try:
            full_path.relative_to(PROJECT_ROOT.resolve())
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid frame path")

        if not full_path.is_file():
            raise HTTPException(status_code=404, detail="Frame file not found")

        return FileResponse(
            path=str(full_path),
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )
    finally:
        conn.close()


@router.get("/videos/{video_id}/file")
async def get_video_file(
    video_id: int,
    db_path: Optional[str] = Query(
        None,
        description="Optional override for the conversations database path.",
    ),
):
    """
    Serve the actual video file for playback.
    Returns the video file directly.
    """
    if db_path is None:
        target, local_video_id = federated_reads.resolve_video(video_id)
        db_path = str(target.db_path)
        video_id = local_video_id

    conn, resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT file_path, file_name FROM videos WHERE id = ?",
            (video_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Video not found")

        file_path = row["file_path"]
        file_name = row["file_name"] or "video.mp4"

        # Check if video is actually downloaded
        if file_path.startswith("[not downloaded]"):
            raise HTTPException(
                status_code=404,
                detail="Video file not downloaded yet. Use WeCom to save video to phone first.",
            )

        # Resolve the full path relative to project root
        if not Path(file_path).is_absolute():
            full_path = PROJECT_ROOT / file_path
        else:
            full_path = Path(file_path)

        if not full_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Video file not found at {full_path}",
            )

        # Determine media type based on extension
        extension = full_path.suffix.lower()
        media_types = {
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".mov": "video/quicktime",
            ".avi": "video/x-msvideo",
            ".mkv": "video/x-matroska",
        }
        media_type = media_types.get(extension, "video/mp4")

        return FileResponse(
            path=str(full_path),
            media_type=media_type,
            filename=file_name,
        )
    finally:
        conn.close()


@router.get("/videos/{video_id}/thumbnail")
async def get_video_thumbnail(
    video_id: int,
    db_path: Optional[str] = Query(
        None,
        description="Optional override for the conversations database path.",
    ),
):
    """
    Generate and serve a thumbnail for a video.

    Thumbnails are generated on first request using ffmpeg and cached for subsequent requests.
    Returns a JPEG image extracted from the first second of the video.
    """
    if db_path is None:
        target, local_video_id = federated_reads.resolve_video(video_id)
        db_path = str(target.db_path)
        video_id = local_video_id

    conn, resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT file_path, file_name FROM videos WHERE id = ?",
            (video_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Video not found")

        file_path = row["file_path"]

        # Check if video is actually downloaded
        if file_path.startswith("[not downloaded]"):
            raise HTTPException(
                status_code=404,
                detail="Video file not downloaded yet. Cannot generate thumbnail.",
            )

        # Resolve the full path relative to project root
        if not Path(file_path).is_absolute():
            full_path = PROJECT_ROOT / file_path
        else:
            full_path = Path(file_path)

        if not full_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Video file not found at {full_path}",
            )

        # Generate cache key based on video path and modification time
        cache_key = hashlib.md5(f"{full_path}:{full_path.stat().st_mtime}".encode()).hexdigest()
        thumbnail_path = THUMBNAIL_CACHE_DIR / f"{cache_key}.jpg"

        # Return cached thumbnail if exists
        if thumbnail_path.exists():
            return FileResponse(
                path=str(thumbnail_path),
                media_type="image/jpeg",
                filename=f"thumbnail_{video_id}.jpg",
            )

        # Generate thumbnail using ffmpeg
        try:
            ffmpeg_bin = resolve_ffmpeg_binary()
            if not ffmpeg_bin:
                raise FileNotFoundError("ffmpeg")
            # Extract frame at 1 second (or 0.5s for short videos)
            cmd = [
                str(ffmpeg_bin),
                "-i",
                str(full_path),
                "-ss",
                "00:00:01",  # Seek to 1 second
                "-vframes",
                "1",  # Extract 1 frame
                "-vf",
                "scale=320:-1",  # Scale to 320px width, maintain aspect ratio
                "-q:v",
                "2",  # High quality JPEG
                "-y",  # Overwrite output
                str(thumbnail_path),
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=10,  # 10 second timeout
            )

            # If failed at 1s, try at 0.1s (for very short videos)
            if not thumbnail_path.exists():
                cmd[4] = "00:00:00.1"
                subprocess.run(cmd, capture_output=True, timeout=10)

            if thumbnail_path.exists():
                return FileResponse(
                    path=str(thumbnail_path),
                    media_type="image/jpeg",
                    filename=f"thumbnail_{video_id}.jpg",
                )
            else:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to generate thumbnail from video",
                )
        except subprocess.TimeoutExpired:
            raise HTTPException(
                status_code=500,
                detail="Thumbnail generation timed out",
            )
        except FileNotFoundError:
            raise HTTPException(
                status_code=500,
                detail="ffmpeg not found. Please install ffmpeg to generate video thumbnails.",
            )
    finally:
        conn.close()


@router.delete("/videos/{message_id}")
async def delete_video_message(
    message_id: int,
    db_path: Optional[str] = Query(
        None,
        description="Optional override for the conversations database path.",
    ),
):
    """
    Delete a video message record from the database.
    """
    resolved_target = None
    if db_path is None:
        resolved_target, local_message_id = federated_reads.resolve_message(message_id)
        db_path = str(resolved_target.db_path)
        message_id = local_message_id

    conn, resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()

        # Get message info before deletion
        cursor.execute(
            """
            SELECT
                m.id,
                m.content,
                m.is_from_kefu,
                m.message_type,
                c.id AS customer_id,
                c.name AS streamer_name,
                c.channel
            FROM messages m
            JOIN customers c ON m.customer_id = c.id
            WHERE m.id = ? AND m.message_type = 'video'
            """,
            (message_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Video message not found")

        message_info = dict(row)

        # Delete the message record (will cascade delete video record)
        cursor.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        conn.commit()

        deleted = {
            "message_id": message_info["id"],
            "content": message_info["content"],
            "is_from_kefu": message_info["is_from_kefu"],
            "streamer_name": message_info["streamer_name"],
            "channel": message_info["channel"],
            "customer_id": message_info["customer_id"],
        }
        if resolved_target is not None:
            deleted["message_id"] = federated_reads._encode(resolved_target, deleted["message_id"])
            deleted["customer_id"] = federated_reads._encode(resolved_target, deleted["customer_id"])

        return {
            "success": True,
            "message": f"Deleted video message from conversation with '{message_info['streamer_name']}'",
            "deleted": deleted,
            "db_path": resolved_path,
        }
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Filter options endpoint (shared for all resource types)
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/filter-options")
async def get_resource_filter_options(
    db_path: Optional[str] = Query(
        None,
        description="Optional override for the conversations database path.",
    ),
):
    """
    Get available filter options (streamers, agents, devices) for resource filtering.
    """
    if db_path is None:
        return federated_reads.get_resource_filter_options()

    conn, resolved_path = _open_db(db_path)
    try:
        cursor = conn.cursor()

        # Get unique streamer names that have resources
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
        streamers = [row["name"] for row in cursor.fetchall()]

        # Get unique agents
        cursor.execute("SELECT id, name, department FROM kefus ORDER BY name")
        agents = [{"id": row["id"], "name": row["name"], "department": row["department"]} for row in cursor.fetchall()]

        # Get unique devices
        cursor.execute("SELECT DISTINCT serial, model FROM devices ORDER BY serial")
        devices = [{"serial": row["serial"], "model": row["model"]} for row in cursor.fetchall()]

        # Get resource counts
        cursor.execute("SELECT COUNT(*) as count FROM images")
        image_count = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) as count FROM messages WHERE message_type = 'voice'")
        voice_count = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) as count FROM messages WHERE message_type = 'video'")
        video_count = cursor.fetchone()["count"]

        return {
            "db_path": resolved_path,
            "streamers": streamers,
            "agents": agents,
            "devices": devices,
            "counts": {
                "images": image_count,
                "voice": voice_count,
                "videos": video_count,
            },
        }
    finally:
        conn.close()
