"""
Database models for WeCom Automation.

This module defines dataclass models that map to database tables,
providing type-safe data structures for conversation storage.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class MessageType(str, Enum):
    """Enumeration of supported message types."""

    TEXT = "text"
    VOICE = "voice"
    IMAGE = "image"
    VIDEO = "video"
    STICKER = "sticker"  # 表情包消息
    FILE = "file"
    LINK = "link"
    LOCATION = "location"
    SYSTEM = "system"
    UNKNOWN = "unknown"

    @classmethod
    def from_string(cls, value: str) -> MessageType:
        """Convert string to MessageType, defaulting to UNKNOWN."""
        try:
            return cls(value.lower())
        except ValueError:
            return cls.UNKNOWN


@dataclass
class DeviceRecord:
    """
    Represents a connected Android device.

    Attributes:
        id: Database primary key (None for new records)
        serial: Unique device serial number
        model: Device model name
        manufacturer: Device manufacturer
        android_version: Android OS version
        created_at: Record creation timestamp
        updated_at: Last update timestamp
    """

    serial: str
    id: int | None = None
    model: str | None = None
    manufacturer: str | None = None
    android_version: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            "serial": self.serial,
            "model": self.model,
            "manufacturer": self.manufacturer,
            "android_version": self.android_version,
        }

    @classmethod
    def from_row(cls, row: Any) -> DeviceRecord:
        """Create from database row."""
        return cls(
            id=row["id"],
            serial=row["serial"],
            model=row["model"],
            manufacturer=row["manufacturer"],
            android_version=row["android_version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class KefuRecord:
    """
    Represents a customer service representative (客服).

    Kefus are identified by name + department (organization), not by device.
    A kefu can use multiple devices, tracked via the kefu_devices junction table.

    Attributes:
        id: Database primary key (None for new records)
        name: Kefu display name
        department: Department/organization name
        verification_status: Verification status (e.g., "未认证")
        created_at: Record creation timestamp
        updated_at: Last update timestamp
    """

    name: str
    id: int | None = None
    department: str | None = None
    verification_status: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            "name": self.name,
            "department": self.department,
            "verification_status": self.verification_status,
        }

    @classmethod
    def from_row(cls, row: Any) -> KefuRecord:
        """Create from database row."""
        return cls(
            id=row["id"],
            name=row["name"],
            department=row["department"],
            verification_status=row["verification_status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class CustomerRecord:
    """
    Represents a customer/contact in private chats.

    Attributes:
        id: Database primary key (None for new records)
        name: Customer display name
        channel: Message source channel (e.g., @WeChat)
        kefu_id: Foreign key to kefus table
        last_message_preview: Preview of last message
        last_message_date: Timestamp of last message
        friend_added_at: First detected true new-friend timestamp
        first_customer_media_at: First customer-side photo/video timestamp
        has_customer_media: Whether customer has sent photo/video
        created_at: Record creation timestamp
        updated_at: Last update timestamp
    """

    name: str
    kefu_id: int
    id: int | None = None
    channel: str | None = None
    last_message_preview: str | None = None
    last_message_date: str | None = None
    friend_added_at: datetime | str | None = None
    first_customer_media_at: datetime | str | None = None
    has_customer_media: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            "name": self.name,
            "channel": self.channel,
            "kefu_id": self.kefu_id,
            "last_message_preview": self.last_message_preview,
            "last_message_date": self.last_message_date,
            "friend_added_at": self.friend_added_at,
            "first_customer_media_at": self.first_customer_media_at,
            "has_customer_media": 1 if self.has_customer_media else 0,
        }

    def unique_key(self) -> str:
        """Generate unique key for this customer."""
        return f"{self.name}|{self.channel or ''}|{self.kefu_id}"

    @classmethod
    def from_row(cls, row: Any) -> CustomerRecord:
        """Create from database row."""
        keys = set(row.keys())

        def col(name: str, default: Any = None) -> Any:
            return row[name] if name in keys else default

        return cls(
            id=row["id"],
            name=row["name"],
            channel=row["channel"],
            kefu_id=row["kefu_id"],
            last_message_preview=row["last_message_preview"],
            last_message_date=row["last_message_date"],
            friend_added_at=col("friend_added_at"),
            first_customer_media_at=col("first_customer_media_at"),
            has_customer_media=bool(col("has_customer_media", 0)),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class MessageRecord:
    """
    Represents a single message in a conversation.

    Attributes:
        id: Database primary key (None for new records)
        customer_id: Foreign key to customers table
        content: Message text content
        message_type: Type of message (text, voice, image, etc.)
        is_from_kefu: True if message is from kefu, False if from customer
        timestamp_raw: Original timestamp string from UI
        timestamp_parsed: Parsed datetime if available
        extra_info: JSON string with additional metadata
        message_hash: SHA256 hash for deduplication
        ui_position: Position in UI extraction order (for accurate context ordering)
        created_at: Record creation timestamp
    """

    customer_id: int
    message_type: MessageType
    is_from_kefu: bool
    id: int | None = None
    content: str | None = None
    timestamp_raw: str | None = None
    timestamp_parsed: datetime | None = None
    extra_info: str | None = None
    message_hash: str | None = None
    ui_position: int | None = None
    created_at: datetime | None = None

    def __post_init__(self):
        """Generate hash if not provided."""
        if self.message_hash is None:
            self.message_hash = self.compute_hash()

    def compute_hash(self) -> str:
        """
        Compute a unique hash for this message.

        改进后的去重机制：
        - customer_id
        - content (or image_bounds for image messages - 优先使用 bounds)
        - message_type
        - is_from_kefu
        - timestamp_bucket (30-minute bucket for fuzzy matching - 改进：从 2 小时缩短)
        - sequence (from extra_info, for identical messages at same timestamp)
        - ui_position (from extra_info, UI 位置信息 - 改进：新增)

        改进要点：
        1. 30 分钟时间桶：减少误去重，宁可重复不可丢失
        2. 图片使用 bounds 而非尺寸：解决同时发送多张相同尺寸图片被误去重的问题
        3. 添加 ui_position：使用消息在 UI 树中的位置作为额外区分因素

        Example:
        - 21:18 and 21:45 both round to 21:30 bucket -> same hash (deduplicated)
        - 21:18 and 22:15 round to 21:00 and 22:00 -> different hashes (kept)

        For image/video messages, we include media-specific identifiers (bounds, dimensions, duration)
        since content is typically empty for these message types.

        This allows deduplication across sync sessions.
        """
        # 改进 1: 使用 30 分钟时间桶（从 2 小时缩短）
        ts_str = ""
        if self.timestamp_parsed:
            ts = self.timestamp_parsed
            # 30 分钟桶：0, 30
            bucket_minute = (ts.minute // 30) * 30
            bucketed = ts.replace(minute=bucket_minute, second=0, microsecond=0)
            ts_str = bucketed.isoformat()
        elif self.timestamp_raw:
            ts_str = self.timestamp_raw

        # Get extra info for additional deduplication fields
        extra = self.get_extra_info_dict()

        # Get sequence from extra_info if available
        seq_str = str(extra.get("sequence", ""))

        # 改进 2: 添加 ui_position 作为额外区分因素
        pos_str = str(extra.get("ui_position", "")) if extra.get("ui_position") is not None else ""

        # For image messages, use bounds as content identifier (改进：优先使用 bounds)
        # This is CRITICAL because images have no text content
        content_str = self.content or ""
        msg_type = self.message_type.value if isinstance(self.message_type, MessageType) else str(self.message_type)

        if msg_type == "image":
            # 改进 3: 优先使用 image_bounds（唯一标识图片位置），而非仅尺寸
            # bounds 对每张图片唯一，解决同时发送多张相同尺寸图片被误去重的问题
            img_bounds = extra.get("image_bounds", "")
            img_dims = extra.get("image_dimensions", "")
            if img_bounds:
                # bounds 格式: [x1,y1][x2,y2] - 对每张图片唯一
                content_str = f"[IMG:{img_bounds}]"
            elif img_dims:
                # 备用：尺寸 + 序列号
                content_str = f"[IMG:{img_dims}:{seq_str}]"
            else:
                # 最后备用：仅序列号
                content_str = f"[IMG:{seq_str}]"
        elif msg_type == "video":
            # Prefer video_duration (handler + sync_service); fall back to legacy "duration" key.
            vid_dur = extra.get("video_duration", "") or extra.get("duration", "")
            if vid_dur:
                content_str = f"[VID:{vid_dur}]"
            else:
                # No on-screen duration (thumbnail+play only): bounds distinguishes adjacent videos.
                vid_bounds = extra.get("original_bounds", "")
                if vid_bounds:
                    content_str = f"[VID:{vid_bounds}]"
        elif msg_type == "voice":
            # Prefer voice_duration; fall back to legacy "duration" key.
            voice_dur = extra.get("voice_duration", "") or extra.get("duration", "")
            if voice_dur:
                content_str = f"[VOICE:{voice_dur}]"
        elif msg_type == "sticker":
            # 表情包：使用 bounds（与图片类似）
            sticker_bounds = extra.get("original_bounds", "")
            if sticker_bounds:
                content_str = f"[STICKER:{sticker_bounds}]"

        hash_input = "|".join(
            [
                str(self.customer_id),
                content_str,
                msg_type,
                "1" if self.is_from_kefu else "0",
                ts_str,
                seq_str,
                pos_str,  # 新增：ui_position
            ]
        )
        return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database insertion."""
        msg_type = self.message_type.value if isinstance(self.message_type, MessageType) else str(self.message_type)
        return {
            "customer_id": self.customer_id,
            "content": self.content,
            "message_type": msg_type,
            "is_from_kefu": 1 if self.is_from_kefu else 0,
            "timestamp_raw": self.timestamp_raw,
            "timestamp_parsed": self.timestamp_parsed,
            "extra_info": self.extra_info,
            "message_hash": self.message_hash or self.compute_hash(),
            "ui_position": self.ui_position,
        }

    def get_extra_info_dict(self) -> dict[str, Any]:
        """Parse extra_info JSON to dictionary."""
        if not self.extra_info:
            return {}
        try:
            return json.loads(self.extra_info)
        except json.JSONDecodeError:
            return {}

    def set_extra_info_dict(self, data: dict[str, Any]) -> None:
        """Set extra_info from dictionary."""
        self.extra_info = json.dumps(data, ensure_ascii=False)

    @classmethod
    def from_row(cls, row: Any) -> MessageRecord:
        """Create from database row."""
        # Handle ui_position which may not exist in older databases
        ui_position = None
        try:
            ui_position = row["ui_position"]
        except (KeyError, IndexError):
            pass

        return cls(
            id=row["id"],
            customer_id=row["customer_id"],
            content=row["content"],
            message_type=MessageType.from_string(row["message_type"]),
            is_from_kefu=bool(row["is_from_kefu"]),
            timestamp_raw=row["timestamp_raw"],
            timestamp_parsed=row["timestamp_parsed"],
            extra_info=row["extra_info"],
            message_hash=row["message_hash"],
            ui_position=ui_position,
            created_at=row["created_at"],
        )


@dataclass
class ImageRecord:
    """
    Represents an image file associated with a message.

    Attributes:
        id: Database primary key (None for new records)
        message_id: Foreign key to messages table
        file_path: Path to the image file
        file_name: Original file name
        original_bounds: UI bounds when captured
        width: Image width in pixels
        height: Image height in pixels
        file_size: File size in bytes
        review_external_id: UUID on image-rating-server (optional)
        ai_review_score: Latest AI analysis score (optional)
        ai_review_model: Model name used for analysis (optional)
        ai_review_decision: e.g. 合格 / 不合格 (optional)
        ai_review_details_json: Full analysis details JSON (optional)
        ai_review_at: Analysis timestamp ISO string (optional)
        ai_review_status: pending / completed / timeout / failed (optional)
        ai_review_error: Review failure or timeout text (optional)
        ai_review_requested_at: Review request timestamp ISO string (optional)
        created_at: Record creation timestamp
    """

    message_id: int
    file_path: str
    id: int | None = None
    file_name: str | None = None
    original_bounds: str | None = None
    width: int | None = None
    height: int | None = None
    file_size: int | None = None
    review_external_id: str | None = None
    ai_review_score: float | None = None
    ai_review_model: str | None = None
    ai_review_decision: str | None = None
    ai_review_details_json: str | None = None
    ai_review_at: str | None = None
    ai_review_status: str | None = None
    ai_review_error: str | None = None
    ai_review_requested_at: str | None = None
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            "message_id": self.message_id,
            "file_path": self.file_path,
            "file_name": self.file_name,
            "original_bounds": self.original_bounds,
            "width": self.width,
            "height": self.height,
            "file_size": self.file_size,
        }

    @classmethod
    def from_row(cls, row: Any) -> ImageRecord:
        """Create from database row."""
        keys = set(row.keys())

        def col(name: str) -> Any:
            return row[name] if name in keys else None

        return cls(
            id=row["id"],
            message_id=row["message_id"],
            file_path=row["file_path"],
            file_name=row["file_name"],
            original_bounds=row["original_bounds"],
            width=row["width"],
            height=row["height"],
            file_size=row["file_size"],
            review_external_id=col("review_external_id"),
            ai_review_score=col("ai_review_score"),
            ai_review_model=col("ai_review_model"),
            ai_review_decision=col("ai_review_decision"),
            ai_review_details_json=col("ai_review_details_json"),
            ai_review_at=col("ai_review_at"),
            ai_review_status=col("ai_review_status"),
            ai_review_error=col("ai_review_error"),
            ai_review_requested_at=col("ai_review_requested_at"),
            created_at=row["created_at"],
        )


@dataclass
class VideoRecord:
    """
    Represents a video file associated with a message.

    Attributes:
        id: Database primary key (None for new records)
        message_id: Foreign key to messages table
        file_path: Path to the video file
        file_name: Original file name
        duration: Duration string (e.g., "00:45", "1:23")
        duration_seconds: Duration in seconds for sorting/filtering
        thumbnail_path: Path to video thumbnail image
        width: Video width in pixels
        height: Video height in pixels
        file_size: File size in bytes
        ai_review_score: Mean score across sampled frames (optional)
        ai_review_frames_json: JSON array of per-frame review payloads (optional)
        ai_review_at: Analysis timestamp ISO string (optional)
        ai_review_status: pending / completed / timeout / failed / partial (optional)
        ai_review_error: Review failure or timeout text (optional)
        ai_review_requested_at: Review request timestamp ISO string (optional)
        created_at: Record creation timestamp
    """

    message_id: int
    file_path: str
    id: int | None = None
    file_name: str | None = None
    duration: str | None = None
    duration_seconds: int | None = None
    thumbnail_path: str | None = None
    width: int | None = None
    height: int | None = None
    file_size: int | None = None
    ai_review_score: float | None = None
    ai_review_frames_json: str | None = None
    ai_review_at: str | None = None
    ai_review_status: str | None = None
    ai_review_error: str | None = None
    ai_review_requested_at: str | None = None
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            "message_id": self.message_id,
            "file_path": self.file_path,
            "file_name": self.file_name,
            "duration": self.duration,
            "duration_seconds": self.duration_seconds,
            "thumbnail_path": self.thumbnail_path,
            "width": self.width,
            "height": self.height,
            "file_size": self.file_size,
        }

    @classmethod
    def from_row(cls, row: Any) -> VideoRecord:
        """Create from database row."""
        keys = set(row.keys())

        def col(name: str) -> Any:
            return row[name] if name in keys else None

        return cls(
            id=row["id"],
            message_id=row["message_id"],
            file_path=row["file_path"],
            file_name=row["file_name"],
            duration=row["duration"],
            duration_seconds=row["duration_seconds"],
            thumbnail_path=row["thumbnail_path"],
            width=row["width"],
            height=row["height"],
            file_size=row["file_size"],
            ai_review_score=col("ai_review_score"),
            ai_review_frames_json=col("ai_review_frames_json"),
            ai_review_at=col("ai_review_at"),
            ai_review_status=col("ai_review_status"),
            ai_review_error=col("ai_review_error"),
            ai_review_requested_at=col("ai_review_requested_at"),
            created_at=row["created_at"],
        )

    @staticmethod
    def parse_duration_to_seconds(duration_str: str | None) -> int | None:
        """
        Parse a duration string to seconds.

        Args:
            duration_str: Duration like "00:45", "1:23", "1:02:30"

        Returns:
            Duration in seconds, or None if parsing fails
        """
        if not duration_str:
            return None

        try:
            parts = duration_str.split(":")
            if len(parts) == 2:
                # MM:SS format
                minutes, seconds = map(int, parts)
                return minutes * 60 + seconds
            elif len(parts) == 3:
                # HH:MM:SS format
                hours, minutes, seconds = map(int, parts)
                return hours * 3600 + minutes * 60 + seconds
            else:
                return None
        except (ValueError, TypeError):
            return None


@dataclass
class VoiceRecord:
    """
    Represents a voice audio file associated with a message.

    Attributes:
        id: Database primary key (None for new records)
        message_id: Foreign key to messages table
        file_path: Path to the voice file (typically WAV)
        file_name: Original file name
        duration: Duration string from UI (e.g. '2"', '5')
        duration_seconds: Parsed duration in seconds for sorting/filtering
        file_size: File size in bytes
        created_at: Record creation timestamp
    """

    message_id: int
    file_path: str
    id: int | None = None
    file_name: str | None = None
    duration: str | None = None
    duration_seconds: int | None = None
    file_size: int | None = None
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            "message_id": self.message_id,
            "file_path": self.file_path,
            "file_name": self.file_name,
            "duration": self.duration,
            "duration_seconds": self.duration_seconds,
            "file_size": self.file_size,
        }

    @classmethod
    def from_row(cls, row: Any) -> VoiceRecord:
        """Create from database row."""
        return cls(
            id=row["id"],
            message_id=row["message_id"],
            file_path=row["file_path"],
            file_name=row["file_name"],
            duration=row["duration"],
            duration_seconds=row["duration_seconds"],
            file_size=row["file_size"],
            created_at=row["created_at"],
        )


# Helper functions for conversion between core models and database records


def message_record_from_conversation_message(
    conv_msg: Any,  # ConversationMessage from core.models
    customer_id: int,
) -> MessageRecord:
    """
    Convert a ConversationMessage to a MessageRecord.

    Args:
        conv_msg: ConversationMessage instance from core.models
        customer_id: Database ID of the customer

    Returns:
        MessageRecord ready for database insertion
    """
    # Build extra_info for special message types
    extra_info = {}

    if hasattr(conv_msg, "voice_duration") and conv_msg.voice_duration:
        extra_info["voice_duration"] = conv_msg.voice_duration

    if hasattr(conv_msg, "sender_name") and conv_msg.sender_name:
        extra_info["sender_name"] = conv_msg.sender_name

    extra_info_str = json.dumps(extra_info, ensure_ascii=False) if extra_info else None

    return MessageRecord(
        customer_id=customer_id,
        content=conv_msg.content,
        message_type=MessageType.from_string(conv_msg.message_type),
        is_from_kefu=conv_msg.is_self,  # is_self in UI means kefu sent it
        timestamp_raw=conv_msg.timestamp,
        extra_info=extra_info_str,
    )
