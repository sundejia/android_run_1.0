"""
Media Auto-Actions Router - API endpoints for media-triggered automation settings.

Provides endpoints for:
- Getting/updating media auto-action settings
- Viewing action execution logs
- Testing action triggers manually
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.settings import get_settings_service

logger = logging.getLogger("media_actions.router")
router = APIRouter()

CATEGORY = "media_auto_actions"

DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "auto_blacklist": {
        "enabled": False,
        "reason": "Customer sent media (auto)",
        "skip_if_already_blacklisted": True,
    },
    "auto_group_invite": {
        "enabled": False,
        "group_members": [],
        "group_name_template": "{customer_name}-服务群",
        "skip_if_group_exists": True,
        "member_source": "manual",
        "send_test_message_after_create": True,
        "test_message_text": "测试",
        "post_confirm_wait_seconds": 1.0,
        "duplicate_name_policy": "first",
    },
}


# ============================================================================
# Pydantic Models
# ============================================================================


class AutoBlacklistSettings(BaseModel):
    enabled: bool = False
    reason: str = "Customer sent media (auto)"
    skip_if_already_blacklisted: bool = True


class AutoGroupInviteSettings(BaseModel):
    enabled: bool = False
    group_members: List[str] = Field(default_factory=list)
    group_name_template: str = "{customer_name}-服务群"
    skip_if_group_exists: bool = True
    member_source: str = "manual"
    send_test_message_after_create: bool = True
    test_message_text: str = "测试"
    post_confirm_wait_seconds: float = 1.0
    duplicate_name_policy: str = "first"


class MediaAutoActionSettings(BaseModel):
    enabled: bool = False
    auto_blacklist: AutoBlacklistSettings = Field(default_factory=AutoBlacklistSettings)
    auto_group_invite: AutoGroupInviteSettings = Field(default_factory=AutoGroupInviteSettings)


class UpdateMediaActionSettingsRequest(BaseModel):
    enabled: Optional[bool] = None
    auto_blacklist: Optional[AutoBlacklistSettings] = None
    auto_group_invite: Optional[AutoGroupInviteSettings] = None


class ActionLogEntry(BaseModel):
    id: int
    device_serial: str
    customer_name: str
    action_name: str
    status: str
    message: str
    details: Optional[dict] = None
    created_at: str


# ============================================================================
# Helper functions
# ============================================================================


def _get_settings() -> dict[str, Any]:
    """Load media auto-action settings from the settings service."""
    service = get_settings_service()
    stored = service.get_category(CATEGORY)
    result = {**DEFAULT_SETTINGS}

    if stored:
        if "enabled" in stored:
            result["enabled"] = stored["enabled"]

        for section_key in ("auto_blacklist", "auto_group_invite"):
            if section_key in stored and isinstance(stored[section_key], dict):
                result[section_key] = {**DEFAULT_SETTINGS[section_key], **stored[section_key]}

    return result


def _save_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Save media auto-action settings."""
    service = get_settings_service()
    service.set_category(CATEGORY, settings, changed_by="api")
    return settings


# ============================================================================
# Endpoints
# ============================================================================


@router.get("/settings", response_model=MediaAutoActionSettings)
async def get_media_action_settings():
    """Get current media auto-action settings."""
    try:
        settings = _get_settings()
        return settings
    except Exception as exc:
        logger.error("Failed to get media action settings: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/settings", response_model=MediaAutoActionSettings)
async def update_media_action_settings(request: UpdateMediaActionSettingsRequest):
    """Update media auto-action settings (partial update supported)."""
    try:
        current = _get_settings()

        if request.enabled is not None:
            current["enabled"] = request.enabled

        if request.auto_blacklist is not None:
            current["auto_blacklist"] = request.auto_blacklist.model_dump()

        if request.auto_group_invite is not None:
            current["auto_group_invite"] = request.auto_group_invite.model_dump()

        saved = _save_settings(current)

        from routers.global_websocket import get_global_ws_manager

        manager = get_global_ws_manager()
        await manager.broadcast({
            "type": "media_action_settings_updated",
            "timestamp": datetime.now().isoformat(),
            "data": saved,
        })

        return saved
    except Exception as exc:
        logger.error("Failed to update media action settings: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/logs")
async def get_action_logs(
    device_serial: Optional[str] = None,
    action_name: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """Get media action execution logs."""
    try:
        import sqlite3
        from wecom_automation.database.schema import get_db_path

        db_path = str(get_db_path())
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        query = "SELECT * FROM media_action_logs WHERE 1=1"
        params: list[Any] = []

        if device_serial:
            query += " AND device_serial = ?"
            params.append(device_serial)
        if action_name:
            query += " AND action_name = ?"
            params.append(action_name)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        try:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            conn.close()
            return {
                "logs": [dict(row) for row in rows],
                "total": len(rows),
            }
        except sqlite3.OperationalError:
            conn.close()
            return {"logs": [], "total": 0}

    except Exception as exc:
        logger.error("Failed to get action logs: %s", exc)
        return {"logs": [], "total": 0}


@router.post("/test-trigger")
async def test_trigger_media_action(
    device_serial: str = "test_device",
    customer_name: str = "测试客户",
    message_type: str = "image",
):
    """
    Manually trigger media actions for testing.

    This simulates a customer sending media without requiring actual device interaction.
    """
    try:
        from wecom_automation.services.media_actions.interfaces import MediaEvent
        from wecom_automation.services.media_actions.event_bus import MediaEventBus
        from wecom_automation.services.media_actions.actions.auto_blacklist import AutoBlacklistAction
        from wecom_automation.services.media_actions.actions.auto_group_invite import AutoGroupInviteAction
        from wecom_automation.services.blacklist_service import BlacklistWriter

        settings = _get_settings()

        event = MediaEvent(
            event_type="customer_media_detected",
            message_type=message_type,
            customer_id=0,
            customer_name=customer_name,
            channel=None,
            device_serial=device_serial,
            kefu_name="test_kefu",
            message_id=None,
            timestamp=datetime.now(),
        )

        bus = MediaEventBus()

        writer = BlacklistWriter()
        bus.register(AutoBlacklistAction(blacklist_writer=writer))

        from wecom_automation.services.media_actions.group_chat_service import GroupChatService
        group_service = GroupChatService()
        bus.register(AutoGroupInviteAction(group_chat_service=group_service))

        results = await bus.emit(event, settings)

        from routers.global_websocket import get_global_ws_manager
        manager = get_global_ws_manager()
        await manager.broadcast({
            "type": "media_action_triggered",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "customer_name": customer_name,
                "device_serial": device_serial,
                "message_type": message_type,
                "results": [
                    {
                        "action_name": r.action_name,
                        "status": r.status.value,
                        "message": r.message,
                    }
                    for r in results
                ],
            },
        })

        return {
            "status": "ok",
            "results": [
                {
                    "action_name": r.action_name,
                    "status": r.status.value,
                    "message": r.message,
                    "details": r.details,
                }
                for r in results
            ],
        }
    except Exception as exc:
        logger.error("Test trigger failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
