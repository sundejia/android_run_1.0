"""Sync event bridge: translates internal sync events to the sync protocol.

Hooks into sync orchestrator events and emits them via the SyncClient.
This is a weak dependency - failures are logged but never block the sync pipeline.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Module-level reference to the active SyncClient
_sync_client: Any | None = None


def set_sync_client(client: Any | None) -> None:
    """Set the active SyncClient instance."""
    global _sync_client
    _sync_client = client


def on_customer_created(
    *,
    customer_id: int,
    customer_name: str,
    channel: str | None = None,
    kefu_name: str | None = None,
    friend_added_at: str | None = None,
) -> None:
    """Called when a new customer is discovered during sync."""
    if not _sync_client or _sync_client.status != "connected":
        return
    try:
        _sync_client.emit_event("sync.customer.created", {
            "customer_id": customer_id,
            "customer_name": customer_name,
            "channel": channel,
            "kefu_name": kefu_name,
            "friend_added_at": friend_added_at,
        })
    except Exception:
        logger.debug("sync_bridge: failed to emit customer.created", exc_info=True)


def on_customer_media_detected(
    *,
    customer_id: int,
    customer_name: str,
    media_type: str,
    first_media_at: str,
) -> None:
    """Called when a customer sends their first photo/video."""
    if not _sync_client or _sync_client.status != "connected":
        return
    try:
        _sync_client.emit_event("sync.customer.media_detected", {
            "customer_id": customer_id,
            "customer_name": customer_name,
            "media_type": media_type,
            "first_media_at": first_media_at,
        })
    except Exception:
        logger.debug("sync_bridge: failed to emit customer.media_detected", exc_info=True)


def on_message_created(
    *,
    customer_id: int,
    customer_name: str,
    message_id: int,
    message_type: str,
    is_from_kefu: bool,
    content: str | None = None,
    timestamp_raw: str | None = None,
    timestamp_parsed: str | None = None,
) -> None:
    """Called when a new message is persisted."""
    if not _sync_client or _sync_client.status != "connected":
        return
    try:
        _sync_client.emit_event("sync.message.created", {
            "customer_id": customer_id,
            "customer_name": customer_name,
            "message_id": message_id,
            "message_type": message_type,
            "is_from_kefu": is_from_kefu,
            "content": content,
            "timestamp_raw": timestamp_raw,
            "timestamp_parsed": timestamp_parsed,
        })
    except Exception:
        logger.debug("sync_bridge: failed to emit message.created", exc_info=True)


def on_media_registered(
    *,
    media_type: str,
    message_id: int,
    customer_id: int,
    customer_name: str,
    file_path: str,
    file_name: str | None = None,
    file_size: int | None = None,
    width: int | None = None,
    height: int | None = None,
    duration: str | None = None,
    duration_seconds: int | None = None,
) -> None:
    """Called when a media file (image/video) is saved."""
    if not _sync_client or _sync_client.status != "connected":
        return
    try:
        _sync_client.emit_event("sync.media.registered", {
            "media_type": media_type,
            "message_id": message_id,
            "customer_id": customer_id,
            "customer_name": customer_name,
            "file_path": file_path,
            "file_name": file_name,
            "file_size": file_size,
            "width": width,
            "height": height,
            "duration": duration,
            "duration_seconds": duration_seconds,
        })

        # Auto-push small images immediately
        if media_type == "image" and file_size and file_size < 200_000:
            _auto_push_media(file_path, media_type, message_id, customer_id)

    except Exception:
        logger.debug("sync_bridge: failed to emit media.registered", exc_info=True)


def on_session_completed(
    *,
    customers_synced: int,
    messages_added: int,
    images_saved: int,
    videos_saved: int,
    duration_seconds: float,
) -> None:
    """Called when a sync session completes."""
    if not _sync_client or _sync_client.status != "connected":
        return
    try:
        _sync_client.emit_event("sync.session.completed", {
            "customers_synced": customers_synced,
            "messages_added": messages_added,
            "images_saved": images_saved,
            "videos_saved": videos_saved,
            "duration_seconds": duration_seconds,
        })
    except Exception:
        logger.debug("sync_bridge: failed to emit session.completed", exc_info=True)


def _auto_push_media(file_path: str, media_type: str, message_id: int, customer_id: int) -> None:
    """Immediately upload a small image file to the cloud."""
    if not _sync_client or _sync_client.status != "connected":
        return
    try:
        import asyncio
        from pathlib import Path

        source = _sync_client._build_source()
        base_url = _sync_client._sync_url.rsplit("/api/sync/ws", 1)[0]
        upload_url = f"{base_url}/api/sync/media/upload"

        async def _do_upload() -> None:
            import httpx
            request_token = f"auto-{message_id}-{media_type}"
            async with httpx.AsyncClient(timeout=30) as client:
                with open(file_path, "rb") as f:
                    await client.post(
                        upload_url,
                        files={"file": (Path(file_path).name, f)},
                        data={
                            "request_token": request_token,
                            "media_type": media_type,
                            "source_device_id": source.get("device_id", "unknown"),
                            "local_message_id": str(message_id),
                        },
                    )

        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_do_upload())
        logger.debug("sync_bridge: auto-pushed media %s", file_path)
    except Exception:
        logger.debug("sync_bridge: auto-push failed for %s", file_path, exc_info=True)
