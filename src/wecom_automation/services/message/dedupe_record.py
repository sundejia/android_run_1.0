"""
Build MessageRecord snapshots that match handler logic for preload deduplication.

Used to skip media pre-download when the same message is already in the database.
"""

from __future__ import annotations

import json
from typing import Any

from wecom_automation.database.models import MessageRecord, MessageType
from wecom_automation.services.timestamp_parser import TimestampParser

_ts_parser = TimestampParser()


def _is_from_kefu_message(message: Any) -> bool:
    if hasattr(message, "is_self"):
        return bool(message.is_self)
    if hasattr(message, "is_from_kefu"):
        return bool(message.is_from_kefu)
    return False


def _timestamp_raw_and_parsed(message: Any) -> tuple[str | None, Any]:
    raw = (
        getattr(message, "timestamp", None) or getattr(message, "timestamp_raw", None) or getattr(message, "time", None)
    )
    if not raw:
        return None, None
    _ts_parser.set_reference_time()
    return str(raw), _ts_parser.parse(str(raw))


def video_message_record_for_dedupe(message: Any, customer_id: int) -> MessageRecord:
    """Same fields as VideoMessageHandler.process() before add_message_if_not_exists."""
    video_duration = getattr(message, "video_duration", None)
    timestamp_raw, timestamp_parsed = _timestamp_raw_and_parsed(message)
    extra_info: dict[str, Any] = {}
    if video_duration:
        extra_info["video_duration"] = video_duration
    return MessageRecord(
        customer_id=customer_id,
        content="[视频]",
        message_type=MessageType.VIDEO,
        is_from_kefu=_is_from_kefu_message(message),
        timestamp_raw=timestamp_raw,
        timestamp_parsed=timestamp_parsed,
        extra_info=json.dumps(extra_info, ensure_ascii=False) if extra_info else None,
    )


def image_message_record_for_dedupe(message: Any, customer_id: int) -> MessageRecord:
    """Same fields as ImageMessageHandler.process() before add_message_if_not_exists."""
    img = getattr(message, "image", None)
    image_bounds = img.bounds if (img and hasattr(img, "bounds")) else None

    timestamp_raw, timestamp_parsed = _timestamp_raw_and_parsed(message)
    extra_info: dict[str, Any] = {}
    if image_bounds:
        extra_info["original_bounds"] = image_bounds
        extra_info["image_bounds"] = image_bounds
        if hasattr(img, "parse_bounds") and img.parse_bounds():
            width = img.x2 - img.x1
            height = img.y2 - img.y1
            extra_info["image_dimensions"] = f"{width}x{height}"

    if hasattr(message, "_sequence"):
        extra_info["sequence"] = message._sequence
    if hasattr(message, "_raw_index") and message._raw_index >= 0:
        extra_info["ui_position"] = message._raw_index

    return MessageRecord(
        customer_id=customer_id,
        content="[图片]",
        message_type=MessageType.IMAGE,
        is_from_kefu=_is_from_kefu_message(message),
        timestamp_raw=timestamp_raw,
        timestamp_parsed=timestamp_parsed,
        extra_info=json.dumps(extra_info, ensure_ascii=False) if extra_info else None,
    )


def voice_message_record_for_dedupe(
    message: Any,
    customer_id: int,
    *,
    content: str | None = None,
) -> MessageRecord:
    """
    Same fields as VoiceMessageHandler.process() before add_message_if_not_exists.

    Args:
        message: ConversationMessage (or compatible).
        customer_id: Customer DB id.
        content: Resolved display/transcription text; if None, uses message.content or placeholder.
    """
    voice_duration = getattr(message, "voice_duration", None)
    voice_caption = getattr(message, "voice_caption", None)
    resolved_content = content if content is not None else (getattr(message, "content", None) or "[语音消息]")
    if isinstance(resolved_content, str):
        resolved_content = resolved_content.strip() or "[语音消息]"
    else:
        resolved_content = "[语音消息]"

    timestamp_raw, timestamp_parsed = _timestamp_raw_and_parsed(message)
    extra_info: dict[str, Any] = {}
    if voice_duration:
        extra_info["voice_duration"] = voice_duration
        extra_info["duration"] = voice_duration
    if voice_caption:
        extra_info["caption"] = voice_caption
    if hasattr(message, "_sequence"):
        extra_info["sequence"] = message._sequence
    if hasattr(message, "_raw_index") and message._raw_index >= 0:
        extra_info["ui_position"] = message._raw_index

    return MessageRecord(
        customer_id=customer_id,
        content=resolved_content,
        message_type=MessageType.VOICE,
        is_from_kefu=_is_from_kefu_message(message),
        timestamp_raw=timestamp_raw,
        timestamp_parsed=timestamp_parsed,
        extra_info=json.dumps(extra_info, ensure_ascii=False) if extra_info else None,
    )
