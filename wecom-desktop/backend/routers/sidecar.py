from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from wecom_automation.core.performance import runtime_metrics
from pydantic import BaseModel, ConfigDict, Field

from wecom_automation.core.config import Config
from wecom_automation.core.exceptions import DeviceConnectionError
from wecom_automation.services.blacklist_service import BlacklistChecker
from wecom_automation.services.wecom_service import WeComService
from wecom_automation.database.schema import get_connection, get_db_path

from services.ai_review_details import extract_ai_review_breakdown, extract_ai_review_reason

router = APIRouter()


class MessageStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"  # 超时后标记为过期，防止误发


class QueuedMessageModel(BaseModel):
    """A message queued for sending via sidecar."""

    id: str
    serial: str
    customerName: str
    channel: Optional[str] = None
    message: str
    timestamp: float
    status: MessageStatus = MessageStatus.PENDING
    error: Optional[str] = None
    source: str = "manual"  # Message source: "manual" | "sync" | "followup"


class SyncQueueStateModel(BaseModel):
    """State of the sync queue for a device."""

    paused: bool = False
    currentMessageId: Optional[str] = None
    totalMessages: int = 0
    processedMessages: int = 0


class QueueStateResponse(BaseModel):
    """Combined queue and sync state response."""

    queue: List[QueuedMessageModel] = Field(default_factory=list)
    syncState: Optional[SyncQueueStateModel] = None


class AddMessageRequest(BaseModel):
    """Request to add a message to the queue."""

    customerName: str
    channel: Optional[str] = None
    message: str
    source: str = "manual"  # Message source: "manual" | "sync" | "followup"


class AddMessageResponse(BaseModel):
    """Response after adding a message."""

    id: str
    success: bool


class ProcessMessageRequest(BaseModel):
    """Request to process (send) a queued message."""

    messageId: str


# In-memory queue storage (per device)
_queues: Dict[str, List[QueuedMessageModel]] = {}
_sync_states: Dict[str, SyncQueueStateModel] = {}
_waiting_events: Dict[str, asyncio.Event] = {}  # For sync process to wait on
_skip_flags: Dict[str, bool] = {}  # Skip flags per device (independent of queue)


class KefuModel(BaseModel):
    """Serialized 客服 info for the sidecar."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    department: Optional[str] = None
    verification_status: Optional[str] = None


class ConversationModel(BaseModel):
    """Conversation context returned to the renderer."""

    model_config = ConfigDict(from_attributes=True)

    contact_name: Optional[str] = None
    channel: Optional[str] = None


class SidecarStateResponse(BaseModel):
    """State payload streamed to the sidecar window."""

    model_config = ConfigDict(from_attributes=True)

    in_conversation: bool
    tree_hash: Optional[str] = None
    focused_text: Optional[str] = None
    kefu: Optional[KefuModel] = None
    conversation: Optional[ConversationModel] = None


class LastMessageModel(BaseModel):
    """Information about the last message in the conversation."""

    is_from_kefu: bool
    content: Optional[str] = None
    message_type: str = "text"


class LastMessageResponse(BaseModel):
    """Response for getting the last message."""

    success: bool
    last_message: Optional[LastMessageModel] = None
    error: Optional[str] = None


class SidecarQueueItem(BaseModel):
    """Placeholder queue item for sidecar polling clients."""

    id: str = "noop"
    type: str = "noop"
    payload: Dict[str, str] = Field(default_factory=dict)


class SidecarQueueResponse(BaseModel):
    """Queue payload returned to sidecar consumers."""

    items: List[SidecarQueueItem] = Field(default_factory=list)
    has_items: bool = False
    detail: str = "Queue is empty"


class SendMessageRequest(BaseModel):
    """Request payload for sending a message via automation."""

    message: str
    contact_name: Optional[str] = None
    channel: Optional[str] = None


class SendMessageResponse(BaseModel):
    """Response payload for message send attempts."""

    success: bool
    detail: Optional[str] = None


class ConversationHistoryMessage(BaseModel):
    """A message in the conversation history."""

    id: int
    content: Optional[str] = None
    message_type: str
    is_from_kefu: bool
    timestamp_raw: Optional[str] = None
    timestamp_parsed: Optional[str] = None
    extra_info: Optional[str] = None
    created_at: str
    # Image fields for displaying images in Sidecar
    image_url: Optional[str] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    # AI image review (from local images table, image-rating-server)
    ai_review_score: Optional[float] = None
    ai_review_decision: Optional[str] = None
    ai_review_reason: Optional[str] = None
    ai_review_score_reasons: List[Dict[str, str]] = Field(default_factory=list)
    ai_review_penalties: List[str] = Field(default_factory=list)
    ai_review_at: Optional[str] = None
    ai_review_status: Optional[str] = None
    ai_review_error: Optional[str] = None
    ai_review_requested_at: Optional[str] = None
    # Video fields for displaying playable video messages in Sidecar
    video_id: Optional[int] = None
    video_duration: Optional[str] = None
    # AI video review (multi-frame aggregate on videos table)
    video_ai_review_score: Optional[float] = None
    video_ai_review_status: Optional[str] = None
    video_ai_review_error: Optional[str] = None
    video_ai_review_requested_at: Optional[str] = None
    video_ai_review_at: Optional[str] = None
    video_ai_review_frames_json: Optional[str] = None


class ConversationHistoryResponse(BaseModel):
    """Response for conversation history lookup."""

    success: bool
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    channel: Optional[str] = None
    kefu_name: Optional[str] = None
    messages: List[ConversationHistoryMessage] = Field(default_factory=list)
    total_messages: int = 0
    error: Optional[str] = None
    db_path: Optional[str] = Field(
        None,
        description="Absolute path of the SQLite file used (e.g. for review-frame URLs).",
    )


def _normalize_channel_text(channel: Optional[str]) -> Optional[str]:
    """Normalize channel text to reduce cross-view mismatches."""
    if channel is None:
        return None
    normalized = channel.strip().replace("＠", "@")
    return normalized or None


async def _ensure_contact_not_blacklisted(
    serial: str,
    *,
    contact_name: Optional[str],
    channel: Optional[str],
    session: Optional["SidecarSession"] = None,
) -> None:
    """Block sends to blacklisted contacts using the latest shared state."""
    resolved_name = contact_name
    resolved_channel = channel

    if session and not resolved_name and not resolved_channel:
        try:
            state = await session.snapshot()
            if state.conversation:
                resolved_name = state.conversation.contact_name
                resolved_channel = state.conversation.channel
        except Exception:
            resolved_name = contact_name
            resolved_channel = channel

    if not resolved_name:
        return

    is_blocked = await asyncio.to_thread(
        BlacklistChecker.is_blacklisted,
        serial,
        resolved_name,
        resolved_channel,
        False,
        True,
    )
    if is_blocked:
        raise HTTPException(status_code=409, detail=f"Contact is blacklisted: {resolved_name}")


def _get_device_kefu_candidates(cursor, serial: str, preferred_kefu_name: Optional[str] = None):
    """Return all kefus linked to a device, ordered by best-fit for sidecar lookups."""
    cursor.execute(
        """
        SELECT DISTINCT
            k.id,
            k.name,
            k.department,
            k.verification_status,
            k.created_at,
            k.updated_at,
            CASE
                WHEN ? IS NOT NULL AND k.name = ? THEN 0
                ELSE 1
            END AS preferred_rank,
            CASE
                WHEN k.name LIKE 'Kefu-%' THEN 1
                ELSE 0
            END AS placeholder_rank
        FROM kefus k
        JOIN kefu_devices kd ON k.id = kd.kefu_id
        JOIN devices d ON kd.device_id = d.id
        WHERE d.serial = ?
        ORDER BY
            preferred_rank ASC,
            placeholder_rank ASC,
            COALESCE(k.updated_at, k.created_at) DESC,
            k.id DESC
        """,
        (preferred_kefu_name, preferred_kefu_name, serial),
    )
    return cursor.fetchall()


def _query_customer_match_for_kefu(
    cursor,
    *,
    kefu_id: int,
    strategy: str,
    contact_name: Optional[str],
    normalized_channel: Optional[str],
):
    """Run one matching strategy for a single kefu."""
    if strategy == "exact":
        where_conditions = ["c.kefu_id = ?"]
        params: List = [kefu_id]

        if contact_name:
            where_conditions.append("c.name = ?")
            params.append(contact_name)

        if normalized_channel:
            where_conditions.append("c.channel = ?")
            params.append(normalized_channel)

        cursor.execute(
            f"""
            SELECT c.id, c.name, c.channel
            FROM customers c
            WHERE {" AND ".join(where_conditions)}
            ORDER BY c.updated_at DESC, c.id DESC
            LIMIT 1
            """,
            params,
        )
        return cursor.fetchone()

    if strategy == "like" and contact_name:
        cursor.execute(
            """
            SELECT c.id, c.name, c.channel
            FROM customers c
            WHERE c.kefu_id = ? AND (
                c.name LIKE ? OR ? LIKE '%' || c.name || '%'
            )
            ORDER BY c.updated_at DESC, c.id DESC
            LIMIT 1
            """,
            (kefu_id, f"%{contact_name}%", contact_name),
        )
        return cursor.fetchone()

    if strategy == "name_only" and contact_name:
        cursor.execute(
            """
            SELECT c.id, c.name, c.channel
            FROM customers c
            WHERE c.kefu_id = ? AND c.name = ?
            ORDER BY c.updated_at DESC, c.id DESC
            LIMIT 1
            """,
            (kefu_id, contact_name),
        )
        return cursor.fetchone()

    return None


def _find_matching_customers_for_device(
    cursor,
    *,
    serial: str,
    contact_name: Optional[str],
    channel: Optional[str],
    preferred_kefu_name: Optional[str] = None,
):
    """
    Find matching customers across all kefus linked to the device.

    This avoids picking a placeholder `Kefu-<serial>` record when a real kefu
    already exists, and also allows history aggregation when both placeholder
    and real kefu records contain parts of the same conversation.
    """
    normalized_channel = _normalize_channel_text(channel)
    if channel and normalized_channel != channel:
        print(f"[conversation-history] Normalized channel: '{channel}' -> '{normalized_channel}'")

    kefu_candidates = _get_device_kefu_candidates(cursor, serial, preferred_kefu_name)
    if not kefu_candidates:
        return [], None, normalized_channel

    strategies = ["exact"]
    if contact_name:
        strategies.append("like")
        if normalized_channel:
            strategies.append("name_only")

    for strategy in strategies:
        matches = []
        for kefu in kefu_candidates:
            match = _query_customer_match_for_kefu(
                cursor,
                kefu_id=kefu["id"],
                strategy=strategy,
                contact_name=contact_name,
                normalized_channel=normalized_channel,
            )
            if match:
                matches.append(
                    {
                        "id": match["id"],
                        "name": match["name"],
                        "channel": match["channel"],
                        "kefu_id": kefu["id"],
                        "kefu_name": kefu["name"],
                    }
                )

        if matches:
            print(
                f"[conversation-history] Strategy={strategy}, "
                f"matched {len(matches)} customer record(s) for serial={serial}"
            )
            return matches, kefu_candidates[0], normalized_channel

    print(f"[conversation-history] No customer found for: name={contact_name}, channel={channel}")
    return [], kefu_candidates[0], normalized_channel


def _message_signature(row) -> tuple:
    """Best-effort signature for deduplicating fragmented cross-kefu history rows."""
    return (
        bool(row["is_from_kefu"]),
        row["message_type"],
        row["content"] or "",
        row["timestamp_parsed"] or "",
        row["timestamp_raw"] or "",
        row["image_path"] or "",
        row["extra_info"] or "",
    )


class SidecarSession:
    """Per-device session that reuses ADB + parser instances."""

    def __init__(self, serial: str):
        self.serial = serial
        self.service = WeComService(Config().with_overrides(device_serial=serial))
        self.lock = asyncio.Lock()
        self._kefu_cache: Optional[KefuModel] = None
        # Track whether a send is in flight so low-priority polling won't contend
        self._send_idle = asyncio.Event()
        self._send_idle.set()
        self._last_state: Optional[SidecarStateResponse] = None

    def _extract_basic_state(self, tree):
        """CPU-bound parsing of the UI tree, offloaded to a thread."""
        contact_name, channel = self.service.ui_parser.get_conversation_header_info(tree)
        tree_hash = self.service.adb.hash_ui_tree(tree)
        return contact_name, channel, tree_hash

    async def ensure_connected(self) -> None:
        """Ensure the underlying ADB connection is alive."""
        if not self.service.adb.is_connected:
            await self.service.adb.connect()

    async def snapshot(self) -> SidecarStateResponse:
        """Return the latest UI-derived state for the device."""
        # If a send is in progress, serve the last known state immediately
        # instead of competing for the device connection.
        if not self._send_idle.is_set():
            if self._last_state:
                return self._last_state
            await self._send_idle.wait()

        async with self.lock:
            await self.ensure_connected()
            tree, _ = await self.service.adb.get_ui_state(force=True)
            focused_text = self.service.adb.last_focused_text

        if tree is None:
            raise HTTPException(status_code=500, detail="UI tree unavailable")

        # Offload CPU-bound parsing so message sending can pre-empt.
        contact_name, channel, tree_hash = await asyncio.to_thread(self._extract_basic_state, tree)

        # Capture 客服 info primarily from non-conversation views to avoid chat text.
        # If the cache is still empty, attempt a wider pass even in conversation views.
        kefu_info = None
        should_try_kefu = self._kefu_cache is None or not (contact_name or channel)
        if should_try_kefu:
            kefu_info = await asyncio.to_thread(
                self.service.ui_parser.extract_kefu_info_from_tree,
                tree,
                max_x=1400,  # allow wider layouts
                min_y=0,  # allow top bar/header
                max_y=2000,  # allow taller screens
            )
            if kefu_info:
                self._kefu_cache = KefuModel(
                    name=kefu_info.name,
                    department=kefu_info.department,
                    verification_status=kefu_info.verification_status,
                )

        # Filter out invalid contact names (UI elements like "Messages")
        is_valid_contact = contact_name and contact_name not in INVALID_CONTACT_NAMES and len(contact_name.strip()) > 0

        in_conversation = bool(is_valid_contact or channel)

        conversation = None
        if in_conversation:
            # Use the validated contact name, or None if it was invalid
            valid_name = contact_name if is_valid_contact else None
            conversation = ConversationModel(
                contact_name=valid_name,
                channel=channel,
            )

        kefu = self._kefu_cache

        state = SidecarStateResponse(
            in_conversation=in_conversation,
            tree_hash=tree_hash,
            focused_text=focused_text,
            kefu=kefu,
            conversation=conversation,
        )
        self._last_state = state
        return state

    async def send_message(self, text: str) -> bool:
        """Send a message through the active conversation."""
        self._send_idle.clear()
        try:
            async with self.lock:
                await self.ensure_connected()
                # send_message returns (success, actual_message_sent), we just need the success flag
                success, _ = await self.service.send_message(text)
                return success
        finally:
            self._send_idle.set()


_sessions: Dict[str, SidecarSession] = {}


# Invalid contact names that should be filtered out (UI elements, not actual users)
INVALID_CONTACT_NAMES = {
    "Messages",
    "消息",
    "Message",
    "Chat",
    "聊天",
    "Conversation",
    "会话",
}


def get_session(serial: str) -> SidecarSession:
    """Reuse a session per serial to avoid reconnect churn."""
    if serial not in _sessions:
        _sessions[serial] = SidecarSession(serial)
    return _sessions[serial]


@router.get("/{serial}/state", response_model=SidecarStateResponse)
async def get_sidecar_state(serial: str) -> SidecarStateResponse:
    """Return the latest conversation-focused UI snapshot for a device."""
    runtime_metrics.record_poll("backend.sidecar.state_request", 0)
    session = get_session(serial)
    try:
        return await session.snapshot()
    except DeviceConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{serial}/last-message", response_model=LastMessageResponse)
async def get_last_message(serial: str) -> LastMessageResponse:
    """Get the last message in the current conversation for generating replies."""
    runtime_metrics.record_poll("backend.sidecar.last_message_request", 0)
    session = get_session(serial)
    try:
        async with session.lock:
            await session.ensure_connected()
            tree, _ = await session.service.adb.get_ui_state(force=True)

        if tree is None:
            return LastMessageResponse(success=False, error="UI tree unavailable")

        # Extract messages from current conversation view
        messages = await asyncio.to_thread(session.service.ui_parser.extract_conversation_messages, tree)

        if not messages:
            return LastMessageResponse(success=False, error="No messages found in conversation")

        # Get the last message (bottom of the visible conversation)
        last_msg = messages[-1]

        return LastMessageResponse(
            success=True,
            last_message=LastMessageModel(
                is_from_kefu=last_msg.is_self,
                content=last_msg.content,
                message_type=last_msg.message_type,
            ),
        )

    except DeviceConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        return LastMessageResponse(success=False, error=str(exc))


class SendAndSaveRequest(BaseModel):
    """Request payload for sending a message and saving to database."""

    message: str
    contact_name: Optional[str] = None
    channel: Optional[str] = None
    kefu_name: Optional[str] = None


class SendAndSaveResponse(BaseModel):
    """Response for send and save operation."""

    success: bool
    message_saved: bool = False
    detail: Optional[str] = None


@router.post("/{serial}/send", response_model=SendMessageResponse)
async def send_sidecar_message(serial: str, request: SendMessageRequest) -> SendMessageResponse:
    """Send a pending message with a device-scoped automation session."""
    session = get_session(serial)
    message = request.message.strip()

    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    try:
        await _ensure_contact_not_blacklisted(
            serial,
            contact_name=request.contact_name,
            channel=request.channel,
            session=session,
        )
        success = await session.send_message(message)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to send message")
        return SendMessageResponse(success=True)
    except DeviceConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _save_sidecar_message_sync(
    *,
    resolved_path_str: str,
    serial: str,
    contact_name: Optional[str],
    channel: Optional[str],
    preferred_kefu_name: Optional[str],
    message: str,
    timestamp: datetime,
    message_hash: str,
) -> Optional[Dict[str, Any]]:
    """Synchronous DB write helper for ``send_and_save_message``.

    Runs the customer match + INSERT + commit inside a worker thread so the
    FastAPI event loop is not blocked while one device is saving a sidecar
    message.     Returns the matched customer info needed for ``notify_message_added``,
    or ``None`` if no matching customer was found / DB does not exist.
    """
    if not Path(resolved_path_str).exists():
        return None

    conn = get_connection(resolved_path_str)
    try:
        cursor = conn.cursor()
        matched_customers, _, _ = _find_matching_customers_for_device(
            cursor,
            serial=serial,
            contact_name=contact_name,
            channel=channel,
            preferred_kefu_name=preferred_kefu_name,
        )

        if not matched_customers:
            return None

        primary_customer = matched_customers[0]
        customer_id = primary_customer["id"]
        saved_contact_name = primary_customer["name"]
        saved_channel = primary_customer["channel"]

        cursor.execute(
            """
            INSERT INTO messages (
                customer_id,
                content,
                message_type,
                is_from_kefu,
                timestamp_raw,
                timestamp_parsed,
                message_hash,
                created_at
            ) VALUES (?, ?, 'text', 1, ?, ?, ?, ?)
            """,
            (
                customer_id,
                message,
                timestamp.strftime("%H:%M"),
                timestamp.isoformat(),
                message_hash,
                timestamp.isoformat(),
            ),
        )
        conn.commit()
        return {
            "customer_id": customer_id,
            "contact_name": saved_contact_name,
            "channel": saved_channel,
        }
    finally:
        conn.close()


@router.post("/{serial}/send-and-save", response_model=SendAndSaveResponse)
async def send_and_save_message(serial: str, request: SendAndSaveRequest) -> SendAndSaveResponse:
    """
    Send a message and save it to the database immediately.

    This is useful when sending a message during sync or at any time
    when you want the message to be recorded in the database without
    waiting for the next sync cycle.

    The message will be saved as a kefu (agent) message in the database.
    """
    session = get_session(serial)
    message = request.message.strip()

    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # First, send the message
    try:
        await _ensure_contact_not_blacklisted(
            serial,
            contact_name=request.contact_name,
            channel=request.channel,
            session=session,
        )
        success = await session.send_message(message)
        if not success:
            return SendAndSaveResponse(success=False, message_saved=False, detail="Failed to send message")
    except DeviceConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        return SendAndSaveResponse(success=False, message_saved=False, detail=str(exc))

    # Message sent successfully, now save to database
    message_saved = False
    try:
        # Get contact info from request or from current session state
        contact_name = request.contact_name
        channel = request.channel

        if not contact_name and not channel:
            # Try to get from current session state
            try:
                state = await session.snapshot()
                if state.conversation:
                    contact_name = state.conversation.contact_name
                    channel = state.conversation.channel
            except Exception:
                pass

        if contact_name or channel:
            resolved_path = get_db_path(None)
            now = datetime.now()
            hash_source = f"sidecar_{serial}_{now.isoformat()}_{uuid.uuid4()}"
            message_hash = hashlib.sha256(hash_source.encode()).hexdigest()

            saved_info = await asyncio.to_thread(
                _save_sidecar_message_sync,
                resolved_path_str=str(resolved_path),
                serial=serial,
                contact_name=contact_name,
                channel=channel,
                preferred_kefu_name=request.kefu_name,
                message=message,
                timestamp=now,
                message_hash=message_hash,
            )

            if saved_info is not None:
                message_saved = True

                try:
                    from services.message_publisher import notify_message_added

                    await notify_message_added(
                        serial,
                        saved_info["customer_id"],
                        saved_info["contact_name"],
                        saved_info["channel"],
                        {
                            "content": message,
                            "is_from_kefu": True,
                            "message_type": "text",
                            "timestamp": now.isoformat(),
                        },
                    )
                except Exception as e:
                    print(f"Failed to publish message event: {e}")
    except Exception as e:
        # Log but don't fail - message was sent successfully
        print(f"Failed to save message to database: {e}")

    return SendAndSaveResponse(
        success=True,
        message_saved=message_saved,
        detail="Message sent" + (" and saved" if message_saved else " (not saved to database)"),
    )


@router.get("/images")
async def serve_image(
    path: str = Query(..., description="Path to the image file"),
):
    """
    Serve image files for display in Sidecar interface.

    This endpoint serves images that were captured during conversation sync.
    The path parameter should be the file_path from the images table.
    """
    # Normalize path separators for cross-platform compatibility
    normalized_path = path.replace("\\", "/")

    # Try multiple possible base directories
    from utils.path_utils import get_project_root
    project_root = get_project_root()
    possible_paths = [
        Path(path),  # Direct path (might be absolute)
        Path(normalized_path),  # Normalized path
        Path.cwd() / path,  # Relative to current working directory
        Path.cwd() / normalized_path,
        project_root / path,  # Project root
        project_root / normalized_path,
    ]

    resolved_path = None
    for try_path in possible_paths:
        try:
            candidate = try_path.resolve()
            if candidate.exists() and candidate.is_file():
                resolved_path = candidate
                break
        except Exception:
            continue

    if not resolved_path:
        raise HTTPException(status_code=404, detail=f"Image not found: {path}")

    # Verify it's an image file (basic check)
    suffix = resolved_path.suffix.lower()
    if suffix not in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"]:
        raise HTTPException(status_code=400, detail="Not an image file")

    # Determine media type
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    media_type = media_types.get(suffix, "image/png")

    return FileResponse(
        resolved_path,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=86400"},  # Cache for 24 hours
    )


@router.get("/{serial}/conversation-history", response_model=ConversationHistoryResponse)
async def get_conversation_history(
    serial: str,
    contact_name: Optional[str] = Query(None, description="Customer contact name"),
    channel: Optional[str] = Query(None, description="Customer channel"),
    kefu_name: Optional[str] = Query(None, description="Current kefu name from sidecar state"),
    limit: int = Query(100, ge=1, le=500, description="Max messages to return"),
    db_path: Optional[str] = Query(None, description="Database path override"),
) -> ConversationHistoryResponse:
    """
    Get conversation history from the database for the current sidecar conversation.
    Looks up customer by device serial + contact name + channel.
    """
    if not contact_name and not channel:
        return ConversationHistoryResponse(success=False, error="Either contact_name or channel is required")

    try:
        resolved_path = get_db_path(db_path)
        if not resolved_path.exists():
            return ConversationHistoryResponse(
                success=False,
                error=f"Database not found at {resolved_path}",
                db_path=str(resolved_path),
            )

        conn = get_connection(str(resolved_path))
        try:
            cursor = conn.cursor()

            matched_customers, best_kefu, normalized_channel = _find_matching_customers_for_device(
                cursor,
                serial=serial,
                contact_name=contact_name,
                channel=channel,
                preferred_kefu_name=kefu_name,
            )

            if not best_kefu:
                return ConversationHistoryResponse(
                    success=False,
                    error=f"No kefu found for device {serial}",
                    db_path=str(resolved_path),
                )
            if not matched_customers:
                return ConversationHistoryResponse(
                    success=True,
                    kefu_name=best_kefu["name"],
                    messages=[],
                    total_messages=0,
                    error=f"Customer not found in database (searched: name={contact_name}, channel={channel})",
                    db_path=str(resolved_path),
                )

            primary_customer = matched_customers[0]
            customer_ids = [customer["id"] for customer in matched_customers]
            customer_id = primary_customer["id"]
            customer_name = primary_customer["name"]
            customer_channel = primary_customer["channel"]
            resolved_kefu_name = primary_customer["kefu_name"]

            if len(customer_ids) == 1:
                cursor.execute("SELECT COUNT(*) as count FROM messages WHERE customer_id = ?", (customer_id,))
                total_messages = cursor.fetchone()["count"]

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
                        m.ui_position,
                        i.file_path as image_path,
                        i.width as image_width,
                        i.height as image_height,
                        i.ai_review_score as ai_review_score,
                        i.ai_review_decision as ai_review_decision,
                        i.ai_review_details_json as ai_review_details_json,
                        i.ai_review_at as ai_review_at,
                        i.ai_review_status as ai_review_status,
                        i.ai_review_error as ai_review_error,
                        i.ai_review_requested_at as ai_review_requested_at,
                        v.id as video_id,
                        v.duration as video_duration,
                        v.ai_review_score as video_ai_review_score,
                        v.ai_review_status as video_ai_review_status,
                        v.ai_review_error as video_ai_review_error,
                        v.ai_review_requested_at as video_ai_review_requested_at,
                        v.ai_review_at as video_ai_review_at,
                        v.ai_review_frames_json as video_ai_review_frames_json
                    FROM messages m
                    LEFT JOIN images i ON m.id = i.message_id
                    LEFT JOIN videos v ON m.id = v.message_id
                    WHERE m.customer_id = ?
                    ORDER BY
                        CASE WHEN m.ui_position IS NOT NULL THEN 0 ELSE 1 END,
                        m.ui_position ASC,
                        COALESCE(m.timestamp_parsed, m.created_at) ASC
                    LIMIT ?
                    """,
                    (customer_id, limit),
                )
                messages_raw = cursor.fetchall()
            else:
                print(
                    f"[conversation-history] Aggregating fragmented history across "
                    f"{len(customer_ids)} customer rows for serial={serial}"
                )
                placeholders = ",".join("?" for _ in customer_ids)
                cursor.execute(
                    f"""
                    SELECT
                        m.id,
                        m.content,
                        m.message_type,
                        m.is_from_kefu,
                        m.timestamp_raw,
                        m.timestamp_parsed,
                        m.extra_info,
                        m.created_at,
                        m.ui_position,
                        i.file_path as image_path,
                        i.width as image_width,
                        i.height as image_height,
                        i.ai_review_score as ai_review_score,
                        i.ai_review_decision as ai_review_decision,
                        i.ai_review_details_json as ai_review_details_json,
                        i.ai_review_at as ai_review_at,
                        i.ai_review_status as ai_review_status,
                        i.ai_review_error as ai_review_error,
                        i.ai_review_requested_at as ai_review_requested_at,
                        v.id as video_id,
                        v.duration as video_duration,
                        v.ai_review_score as video_ai_review_score,
                        v.ai_review_status as video_ai_review_status,
                        v.ai_review_error as video_ai_review_error,
                        v.ai_review_requested_at as video_ai_review_requested_at,
                        v.ai_review_at as video_ai_review_at,
                        v.ai_review_frames_json as video_ai_review_frames_json
                    FROM messages m
                    LEFT JOIN images i ON m.id = i.message_id
                    LEFT JOIN videos v ON m.id = v.message_id
                    WHERE m.customer_id IN ({placeholders})
                    ORDER BY
                        COALESCE(m.timestamp_parsed, m.created_at) ASC,
                        m.id ASC
                    """,
                    customer_ids,
                )
                deduped_rows = []
                seen_signatures = set()
                for row in cursor.fetchall():
                    signature = _message_signature(row)
                    if signature in seen_signatures:
                        continue
                    seen_signatures.add(signature)
                    deduped_rows.append(row)

                total_messages = len(deduped_rows)
                messages_raw = deduped_rows[:limit]

            # Messages are already ordered by ui_position ASC (top to bottom display order)
            messages = []
            for row in messages_raw:
                # Build image URL if image exists
                image_url = None
                if row["image_path"]:
                    # Convert local path to API URL with proper encoding
                    image_path = row["image_path"]
                    # URL-encode the path to handle special characters and backslashes
                    encoded_path = quote(image_path, safe="")
                    image_url = f"/api/sidecar/images?path={encoded_path}"

                row_keys = row.keys()
                details_json = row["ai_review_details_json"] if "ai_review_details_json" in row_keys else None
                score = row["ai_review_score"] if "ai_review_score" in row_keys else None
                if score is not None:
                    try:
                        score = float(score)
                    except (TypeError, ValueError):
                        score = None
                score_reasons, penalties = extract_ai_review_breakdown(details_json)

                v_score = row["video_ai_review_score"] if "video_ai_review_score" in row_keys else None
                if v_score is not None:
                    try:
                        v_score = float(v_score)
                    except (TypeError, ValueError):
                        v_score = None

                messages.append(
                    ConversationHistoryMessage(
                        id=row["id"],
                        content=row["content"],
                        message_type=row["message_type"],
                        is_from_kefu=bool(row["is_from_kefu"]),
                        timestamp_raw=row["timestamp_raw"],
                        timestamp_parsed=row["timestamp_parsed"],
                        extra_info=row["extra_info"],
                        created_at=row["created_at"],
                        image_url=image_url,
                        image_width=row["image_width"],
                        image_height=row["image_height"],
                        ai_review_score=score,
                        ai_review_decision=(
                            row["ai_review_decision"] if "ai_review_decision" in row_keys else None
                        ),
                        ai_review_reason=extract_ai_review_reason(details_json),
                        ai_review_score_reasons=score_reasons,
                        ai_review_penalties=penalties,
                        ai_review_at=row["ai_review_at"] if "ai_review_at" in row_keys else None,
                        ai_review_status=(
                            row["ai_review_status"] if "ai_review_status" in row_keys else None
                        ),
                        ai_review_error=(
                            row["ai_review_error"] if "ai_review_error" in row_keys else None
                        ),
                        ai_review_requested_at=(
                            row["ai_review_requested_at"]
                            if "ai_review_requested_at" in row_keys
                            else None
                        ),
                        video_id=row["video_id"],
                        video_duration=row["video_duration"],
                        video_ai_review_score=v_score,
                        video_ai_review_status=(
                            row["video_ai_review_status"] if "video_ai_review_status" in row_keys else None
                        ),
                        video_ai_review_error=(
                            row["video_ai_review_error"] if "video_ai_review_error" in row_keys else None
                        ),
                        video_ai_review_requested_at=(
                            row["video_ai_review_requested_at"]
                            if "video_ai_review_requested_at" in row_keys
                            else None
                        ),
                        video_ai_review_at=(
                            row["video_ai_review_at"] if "video_ai_review_at" in row_keys else None
                        ),
                        video_ai_review_frames_json=(
                            row["video_ai_review_frames_json"]
                            if "video_ai_review_frames_json" in row_keys
                            else None
                        ),
                    )
                )

            return ConversationHistoryResponse(
                success=True,
                customer_id=customer_id,
                customer_name=customer_name,
                channel=customer_channel,
                kefu_name=resolved_kefu_name,
                messages=messages,
                total_messages=total_messages,
                db_path=str(resolved_path),
            )

        finally:
            conn.close()

    except Exception as exc:
        return ConversationHistoryResponse(success=False, error=str(exc))


# ============= Queue Management Endpoints =============


def _get_queue(serial: str) -> List[QueuedMessageModel]:
    """Get or create queue for a device."""
    if serial not in _queues:
        _queues[serial] = []
    return _queues[serial]


def _get_sync_state(serial: str) -> SyncQueueStateModel:
    """Get or create sync state for a device."""
    if serial not in _sync_states:
        _sync_states[serial] = SyncQueueStateModel()
    return _sync_states[serial]


def _get_waiting_event(serial: str) -> asyncio.Event:
    """Get or create waiting event for a device."""
    if serial not in _waiting_events:
        _waiting_events[serial] = asyncio.Event()
    return _waiting_events[serial]


@router.get("/{serial}/queue", response_model=QueueStateResponse)
async def get_queue_state(serial: str) -> QueueStateResponse:
    """Get the current queue state for a device."""
    runtime_metrics.record_poll("backend.sidecar.queue_request", 0)
    queue = _get_queue(serial)
    sync_state = _get_sync_state(serial)
    return QueueStateResponse(queue=queue, syncState=sync_state)


@router.post("/{serial}/queue/add", response_model=AddMessageResponse)
async def add_to_queue(serial: str, request: AddMessageRequest) -> AddMessageResponse:
    """Add a message to the sidecar queue."""
    queue = _get_queue(serial)
    sync_state = _get_sync_state(serial)

    msg = QueuedMessageModel(
        id=str(uuid.uuid4()),
        serial=serial,
        customerName=request.customerName,
        channel=request.channel,
        message=request.message,
        timestamp=time.time(),
        status=MessageStatus.PENDING,
        source=request.source,  # Pass the source from request
    )

    queue.append(msg)
    sync_state.totalMessages = len(queue)

    return AddMessageResponse(id=msg.id, success=True)


@router.post("/{serial}/queue/ready/{message_id}")
async def set_message_ready(serial: str, message_id: str):
    """Mark a message as ready for sending (shows in sidecar UI)."""
    queue = _get_queue(serial)
    sync_state = _get_sync_state(serial)

    msg = next((m for m in queue if m.id == message_id), None)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    msg.status = MessageStatus.READY
    sync_state.currentMessageId = message_id

    return {"success": True, "message": "Message marked as ready"}


class SendQueuedMessageRequest(BaseModel):
    """Request body for sending a queued message with optional edited content."""

    edited_message: Optional[str] = None  # If provided, send this instead of the original


@router.post("/{serial}/queue/send/{message_id}", response_model=SendMessageResponse)
async def send_queued_message(
    serial: str, message_id: str, request: Optional[SendQueuedMessageRequest] = None
) -> SendMessageResponse:
    """Send a queued message through the device. If edited_message is provided, use it instead of original."""
    queue = _get_queue(serial)
    sync_state = _get_sync_state(serial)

    msg = next((m for m in queue if m.id == message_id), None)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    if msg.status not in (MessageStatus.READY, MessageStatus.PENDING):
        raise HTTPException(status_code=400, detail=f"Message status is {msg.status}, cannot send")

    msg.status = MessageStatus.SENDING

    # Use edited message if provided, otherwise use original
    message_to_send = request.edited_message if request and request.edited_message else msg.message

    try:
        session = get_session(serial)
        await _ensure_contact_not_blacklisted(
            serial,
            contact_name=msg.customerName,
            channel=msg.channel,
            session=session,
        )
        success = await session.send_message(message_to_send)

        if success:
            msg.status = MessageStatus.SENT
            # Save the actual sent message (may be edited by user)
            if request and request.edited_message:
                msg.message = request.edited_message
            sync_state.processedMessages += 1
            sync_state.currentMessageId = None

            # Signal waiting sync process
            event = _get_waiting_event(serial)
            event.set()

            return SendMessageResponse(success=True)
        else:
            msg.status = MessageStatus.FAILED
            msg.error = "Failed to send message"
            sync_state.currentMessageId = None

            # Signal waiting sync process even on failure
            event = _get_waiting_event(serial)
            event.set()

            return SendMessageResponse(success=False, detail="Failed to send message")

    except Exception as exc:
        if isinstance(exc, HTTPException) and exc.status_code == 409:
            msg.status = MessageStatus.CANCELLED
            msg.error = exc.detail
        else:
            msg.status = MessageStatus.FAILED
            msg.error = str(exc)
        sync_state.currentMessageId = None

        # Signal waiting sync process even on error
        event = _get_waiting_event(serial)
        event.set()

        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{serial}/queue/pause")
async def pause_queue(serial: str):
    """Pause the sync queue for a device."""
    sync_state = _get_sync_state(serial)
    sync_state.paused = True
    return {"success": True, "message": "Queue paused"}


@router.post("/{serial}/queue/resume")
async def resume_queue(serial: str):
    """Resume the sync queue for a device."""
    sync_state = _get_sync_state(serial)
    sync_state.paused = False

    # Signal waiting sync process to continue
    event = _get_waiting_event(serial)
    event.set()

    return {"success": True, "message": "Queue resumed"}


@router.post("/{serial}/queue/cancel")
async def cancel_queue(serial: str):
    """Cancel all pending messages in the queue."""
    queue = _get_queue(serial)
    sync_state = _get_sync_state(serial)

    for msg in queue:
        if msg.status in (MessageStatus.PENDING, MessageStatus.READY):
            msg.status = MessageStatus.CANCELLED

    sync_state.currentMessageId = None

    # Also set skip flag for comprehensive skip support
    _skip_flags[serial] = True

    # Signal waiting sync process to exit
    event = _get_waiting_event(serial)
    event.set()

    return {"success": True, "message": "Queue cancelled"}


# ==================== P0 Fix: Queue Cleanup APIs ====================


@router.post("/{serial}/queue/mark-sent/{message_id}")
async def mark_message_as_sent(serial: str, message_id: str):
    """
    标记消息为已发送（直接发送成功后调用）

    当 Sidecar 超时后回退到直接发送成功时，调用此 API 标记队列中的消息，
    防止后续误发到错误的用户。
    """
    logger = logging.getLogger(__name__)
    queue = _get_queue(serial)

    msg = next((m for m in queue if m.id == message_id), None)
    if not msg:
        # 消息不存在也返回成功，避免阻塞流程
        logger.debug(f"Message {message_id} not found in queue (may have been cleaned)")
        return {"success": True, "message": "Message not found (already cleaned)"}

    if msg.status in (MessageStatus.SENT, MessageStatus.FAILED, MessageStatus.CANCELLED, MessageStatus.EXPIRED):
        # 已经是终态，不需要更新
        return {"success": True, "message": f"Message already in terminal state: {msg.status}"}

    # 标记为已发送
    msg.status = MessageStatus.SENT
    logger.info(f"✅ Message {message_id} marked as SENT (direct send fallback)")

    return {"success": True, "message": "Message marked as sent"}


@router.post("/{serial}/queue/clear-expired")
async def clear_expired_messages(serial: str):
    """
    清理队列中过期的消息

    删除所有 EXPIRED、CANCELLED、SENT、FAILED 状态的消息，
    防止队列积累垃圾消息导致后续误操作。

    Returns:
        cleared: 清理的消息数量
    """
    logger = logging.getLogger(__name__)
    queue = _get_queue(serial)

    terminal_states = (
        MessageStatus.SENT,
        MessageStatus.FAILED,
        MessageStatus.CANCELLED,
        MessageStatus.EXPIRED,
    )

    # 找出需要清理的消息
    to_clear = [m for m in queue if m.status in terminal_states]
    cleared_count = len(to_clear)

    # 从队列中移除
    _queues[serial] = [m for m in queue if m.status not in terminal_states]

    if cleared_count > 0:
        logger.info(f"🧹 Cleared {cleared_count} expired/terminal messages from queue for {serial}")
        for m in to_clear:
            logger.debug(f"   - {m.id}: {m.customerName} ({m.status})")

    return {"success": True, "cleared": cleared_count}


# ==================== Skip Flag API ====================
# Independent skip mechanism that doesn't depend on queue state


def _get_skip_flag(serial: str) -> bool:
    """Get skip flag for a device."""
    return _skip_flags.get(serial, False)


def _set_skip_flag(serial: str, value: bool) -> None:
    """Set skip flag for a device."""
    _skip_flags[serial] = value


def clear_device_sidecar_state(serial: str) -> None:
    """
    Clear all sidecar state for a device.

    Called when follow-up is stopped to prevent stale state from
    affecting the next follow-up session.

    Clears:
    - Skip flag
    - Message queue
    - Sync state
    - Waiting events
    """
    logger = logging.getLogger(__name__)
    logger.info(f"🧹 Clearing sidecar state for {serial}")

    # Clear skip flag
    _set_skip_flag(serial, False)

    # Clear queue
    if serial in _queues:
        _queues[serial] = []

    # Clear sync state
    if serial in _sync_states:
        _sync_states[serial] = SyncQueueStateModel()

    # Clear waiting events (signal any waiting coroutines first)
    if serial in _waiting_events:
        _waiting_events[serial].set()
        del _waiting_events[serial]

    logger.info(f"✅ Sidecar state cleared for {serial}")


@router.post("/{serial}/skip")
async def request_skip(serial: str):
    """
    Request to skip the current user.
    Sets a skip flag that can be checked by sync processes.
    Also cancels any pending queue messages.
    """
    logger = logging.getLogger(__name__)
    logger.info(f"🔴 POST /sidecar/{serial}/skip - Setting skip flag to True")

    # Set the skip flag
    _set_skip_flag(serial, True)
    logger.debug(f"🔴 Skip flag set: _skip_flags[{serial}] = True")

    # Cancel queue as well for comprehensive skip
    queue = _get_queue(serial)
    cancelled_count = 0
    for msg in queue:
        if msg.status in (MessageStatus.PENDING, MessageStatus.READY):
            msg.status = MessageStatus.CANCELLED
            cancelled_count += 1
    logger.debug(f"🔴 Cancelled {cancelled_count} pending messages in queue")

    # Signal waiting processes
    event = _get_waiting_event(serial)
    event.set()
    logger.debug(f"🔴 Signaled waiting event for {serial}")

    return {"success": True, "message": "Skip requested", "skip_flag": True}


@router.get("/{serial}/skip")
async def get_skip_status(serial: str):
    """Check if skip has been requested for this device."""
    logger = logging.getLogger(__name__)
    skip_flag = _get_skip_flag(serial)
    logger.debug(f"🔍 GET /sidecar/{serial}/skip - Returning skip_requested={skip_flag}")
    return {"skip_requested": skip_flag}


@router.delete("/{serial}/skip")
async def clear_skip(serial: str):
    """Clear the skip flag for a device."""
    logger = logging.getLogger(__name__)
    logger.info(f"🟢 DELETE /sidecar/{serial}/skip - Clearing skip flag")

    _set_skip_flag(serial, False)
    logger.debug(f"🟢 Skip flag cleared: _skip_flags[{serial}] = False")

    # Also clear cancelled messages from queue to prevent false positive
    # in is_skip_requested() fallback check
    queue = _get_queue(serial)
    cleared_count = len([m for m in queue if m.status == MessageStatus.CANCELLED])
    _queues[serial] = [m for m in queue if m.status != MessageStatus.CANCELLED]
    logger.debug(f"🟢 Removed {cleared_count} cancelled messages from queue")

    return {"success": True, "message": "Skip flag cleared", "skip_flag": False}


@router.delete("/{serial}/queue")
async def clear_queue(serial: str):
    """Clear the queue for a device."""
    if serial in _queues:
        _queues[serial] = []
    if serial in _sync_states:
        _sync_states[serial] = SyncQueueStateModel()
    if serial in _waiting_events:
        _waiting_events[serial].set()
        del _waiting_events[serial]

    return {"success": True, "message": "Queue cleared"}


@router.post("/{serial}/queue/wait/{message_id}")
async def wait_for_send(serial: str, message_id: str, timeout: float = 60.0):
    """
    Wait for a specific message to be sent.
    Uses simple polling to check message status.

    Returns when:
    - Message status is SENT
    - Message status is FAILED
    - Message status is CANCELLED
    - Skip flag is set
    - Timeout is reached
    """
    logger = logging.getLogger(__name__)
    start_time = time.time()
    event = _get_waiting_event(serial)

    while True:
        # Check timeout
        elapsed = time.time() - start_time
        if elapsed >= timeout:
            # P0 修复: 超时后标记消息为 EXPIRED，防止后续误发
            queue = _get_queue(serial)
            msg = next((m for m in queue if m.id == message_id), None)
            if msg and msg.status in (MessageStatus.PENDING, MessageStatus.READY):
                msg.status = MessageStatus.EXPIRED
                logger.info(f"⏰ Message {message_id} marked as EXPIRED due to timeout (was {msg.customerName})")
            return {"success": False, "reason": "timeout"}

        # Check skip flag - allows user to cancel during wait
        if _get_skip_flag(serial):
            logger.info(f"⏭️ Skip flag detected during wait_for_send for {serial}")
            # Mark message as cancelled
            queue = _get_queue(serial)
            msg = next((m for m in queue if m.id == message_id), None)
            if msg and msg.status not in (MessageStatus.SENT, MessageStatus.FAILED):
                msg.status = MessageStatus.CANCELLED
                logger.debug(f"Message {message_id} marked as CANCELLED due to skip")
            return {"success": False, "reason": "cancelled"}

        # Get current state
        queue = _get_queue(serial)

        # Find the message
        msg = next((m for m in queue if m.id == message_id), None)

        if msg is None:
            # Message not found - might have been cleared
            return {"success": False, "reason": "not_found"}

        # Check message status - only care about terminal states
        if msg.status == MessageStatus.SENT:
            return {"success": True, "reason": "sent", "message": msg.message}

        if msg.status == MessageStatus.FAILED:
            return {"success": False, "reason": "failed", "error": msg.error}

        if msg.status == MessageStatus.CANCELLED:
            return {"success": False, "reason": "cancelled"}

        if msg.status == MessageStatus.EXPIRED:
            return {"success": False, "reason": "expired"}

        remaining = timeout - elapsed
        if remaining <= 0:
            continue

        runtime_metrics.record_poll("backend.sidecar.wait_for_send", min(remaining, 5.0) * 1000)
        try:
            await asyncio.wait_for(event.wait(), timeout=min(remaining, 5.0))
        except asyncio.TimeoutError:
            continue
        finally:
            if event.is_set():
                event.clear()


# =============================================================================
# WebSocket Endpoint for Real-time Message Push
# =============================================================================

from fastapi import WebSocket, WebSocketDisconnect
from services.websocket_manager import get_sidecar_message_manager


@router.websocket("/{serial}/ws/messages")
async def websocket_messages(
    websocket: WebSocket,
    serial: str,
    contact_name: str = None,
    channel: str = None,
):
    """
    WebSocket 端点：实时消息推送

    客户端连接后，当该对话有新消息时会收到推送。

    Query Params:
        contact_name: 客户名称（可选）
        channel: 渠道（可选）

    推送消息格式:
        {
            "type": "message_added" | "message_batch" | "history_refresh",
            "data": { ... }
        }
    """
    logger = logging.getLogger(__name__)
    manager = get_sidecar_message_manager()

    await manager.connect(websocket, serial, contact_name, channel)

    try:
        # 发送连接成功消息
        await websocket.send_json(
            {
                "type": "connected",
                "message": f"Connected to message stream for {serial}",
                "contact_name": contact_name,
                "channel": channel,
            }
        )

        # 保持连接，等待客户端消息（心跳等）
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)

                if data == "ping":
                    await websocket.send_text("pong")

            except asyncio.TimeoutError:
                # 发送心跳
                await websocket.send_json({"type": "heartbeat"})

    except WebSocketDisconnect:
        logger.info(f"[WS] Client disconnected from {serial} messages")
    except Exception as e:
        logger.error(f"[WS] Error in message websocket: {e}")
    finally:
        await manager.disconnect(websocket, serial, contact_name, channel)
