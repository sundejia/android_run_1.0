"""
Media Auto-Actions Router - API endpoints for media-triggered automation settings.

Provides endpoints for:
- Getting/updating media auto-action settings
- Viewing action execution logs
- Testing action triggers manually
"""

from __future__ import annotations

import asyncio
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
        "require_review_pass": False,
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
        "video_invite_policy": "extract_frame",
        "send_message_before_create": False,
        "pre_create_message_text": "",
    },
    "auto_contact_share": {
        "enabled": False,
        "contact_name": "",
        "skip_if_already_shared": True,
        "cooldown_seconds": 0,
        "kefu_overrides": {},
        "send_message_before_share": False,
        "pre_share_message_text": "",
    },
    "review_gate": {
        "enabled": False,
        "rating_server_url": "http://127.0.0.1:8080",
        "upload_timeout_seconds": 30.0,
        "upload_max_attempts": 3,
        "video_review_policy": "extract_frame",
    },
}


# ============================================================================
# Pydantic Models
# ============================================================================


class AutoBlacklistSettings(BaseModel):
    enabled: bool = False
    reason: str = "Customer sent media (auto)"
    skip_if_already_blacklisted: bool = True
    # False (default): customer media → blacklist immediately, no review-pipeline
    # dependency. True: defer to the image-rating-server review verdict so the
    # blacklist gate mirrors auto-group-invite. Only flip on when rating pipeline
    # is actually deployed.
    require_review_pass: bool = False


class AutoGroupInviteSettings(BaseModel):
    enabled: bool = False
    group_members: List[str] = Field(default_factory=list)
    group_name_template: str = "{customer_name}-服务群"
    skip_if_group_exists: bool = True
    member_source: str = "manual"
    send_message_before_create: bool = False
    pre_create_message_text: str = ""
    send_test_message_after_create: bool = True
    test_message_text: str = "测试"
    post_confirm_wait_seconds: float = 1.0
    duplicate_name_policy: str = "first"
    video_invite_policy: str = "extract_frame"


class AutoContactShareSettings(BaseModel):
    enabled: bool = False
    contact_name: str = ""
    skip_if_already_shared: bool = True
    cooldown_seconds: int = 0
    kefu_overrides: dict[str, str] = Field(default_factory=dict)
    send_message_before_share: bool = False
    pre_share_message_text: str = ""


class ReviewGateSettings(BaseModel):
    enabled: bool = False
    rating_server_url: str = "http://127.0.0.1:8080"
    upload_timeout_seconds: float = 30.0
    upload_max_attempts: int = 3
    video_review_policy: str = "extract_frame"


class MediaAutoActionSettings(BaseModel):
    enabled: bool = False
    auto_blacklist: AutoBlacklistSettings = Field(default_factory=AutoBlacklistSettings)
    auto_group_invite: AutoGroupInviteSettings = Field(default_factory=AutoGroupInviteSettings)
    auto_contact_share: AutoContactShareSettings = Field(default_factory=AutoContactShareSettings)
    review_gate: ReviewGateSettings = Field(default_factory=ReviewGateSettings)


class UpdateMediaActionSettingsRequest(BaseModel):
    enabled: Optional[bool] = None
    auto_blacklist: Optional[AutoBlacklistSettings] = None
    auto_group_invite: Optional[AutoGroupInviteSettings] = None
    auto_contact_share: Optional[AutoContactShareSettings] = None
    review_gate: Optional[ReviewGateSettings] = None


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

        for section_key in ("auto_blacklist", "auto_group_invite", "auto_contact_share", "review_gate"):
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
        settings = await asyncio.to_thread(_get_settings)
        return settings
    except Exception as exc:
        logger.error("Failed to get media action settings: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


def _apply_media_action_settings_update_sync(
    request: UpdateMediaActionSettingsRequest,
) -> dict[str, Any]:
    """Synchronous merge + save - runs in worker thread."""
    current = _get_settings()

    if request.enabled is not None:
        current["enabled"] = request.enabled

    if request.auto_blacklist is not None:
        current["auto_blacklist"] = request.auto_blacklist.model_dump()

    if request.auto_group_invite is not None:
        current["auto_group_invite"] = request.auto_group_invite.model_dump()

    if request.auto_contact_share is not None:
        current["auto_contact_share"] = request.auto_contact_share.model_dump()

    if request.review_gate is not None:
        current["review_gate"] = request.review_gate.model_dump()

    return _save_settings(current)


@router.put("/settings", response_model=MediaAutoActionSettings)
async def update_media_action_settings(request: UpdateMediaActionSettingsRequest):
    """Update media auto-action settings (partial update supported)."""
    try:
        saved = await asyncio.to_thread(_apply_media_action_settings_update_sync, request)

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


def _get_action_logs_sync(
    device_serial: Optional[str],
    action_name: Optional[str],
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """Synchronous body of ``get_action_logs`` - runs in worker thread."""
    import sqlite3 as _sqlite3

    from services.conversation_storage import open_shared_sqlite
    from wecom_automation.database.schema import get_db_path

    db_path = str(get_db_path())
    conn = open_shared_sqlite(db_path, row_factory=True)

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
    except _sqlite3.OperationalError:
        conn.close()
        return {"logs": [], "total": 0}


@router.get("/logs")
async def get_action_logs(
    device_serial: Optional[str] = None,
    action_name: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """Get media action execution logs."""
    try:
        return await asyncio.to_thread(
            _get_action_logs_sync, device_serial, action_name, limit, offset
        )
    except Exception as exc:
        logger.error("Failed to get action logs: %s", exc)
        return {"logs": [], "total": 0}


class TestContactReachabilityRequest(BaseModel):
    device_serial: str
    contact_name: str


class TestContactReachabilityResponse(BaseModel):
    reachable: bool
    finder: str
    contact_name: str
    device_serial: str
    message: str


@router.post("/auto-contact-share/test-reachability", response_model=TestContactReachabilityResponse)
async def test_contact_reachability(request: TestContactReachabilityRequest):
    """Run a non-destructive picker search for ``contact_name`` on the given device.

    Pre-conditions:
        - The device is connected and ADB-reachable.
        - WeCom is open on a chat screen (the picker is opened from the input bar).

    Behavior:
        1. Tap the attach button.
        2. Open the Contact Card menu.
        3. Run the composite (search → scroll) picker finder for ``contact_name``.
        4. ALWAYS press back twice to dismiss the picker and attach panel — we
           never tap "Send" so no card is actually delivered to anyone.

    Returns ``reachable=True`` only if the picker successfully selected a row.
    """
    contact_name = (request.contact_name or "").strip()
    serial = (request.device_serial or "").strip()
    if not contact_name:
        return TestContactReachabilityResponse(
            reachable=False,
            finder="none",
            contact_name=contact_name,
            device_serial=serial,
            message="contact_name is empty",
        )
    if not serial:
        return TestContactReachabilityResponse(
            reachable=False,
            finder="none",
            contact_name=contact_name,
            device_serial=serial,
            message="device_serial is empty",
        )

    try:
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService
        from wecom_automation.services.contact_share.service import ContactShareService
        from wecom_automation.services.wecom_service import WeComService

        config = Config.from_env().with_overrides(device_serial=serial)
        adb = ADBService(config)
        wecom = WeComService(config, adb)
        share_service = ContactShareService(wecom_service=wecom)

        # Step 1: Open attach panel
        if not await share_service._tap_attach_button(device_serial=serial):
            return TestContactReachabilityResponse(
                reachable=False,
                finder="attach_button",
                contact_name=contact_name,
                device_serial=serial,
                message="Attach button not found — make sure WeCom is on a chat screen",
            )

        await asyncio.sleep(share_service._STEP_DELAY)

        # Step 2: Open Contact Card menu
        if not await share_service._open_contact_card_menu():
            return TestContactReachabilityResponse(
                reachable=False,
                finder="contact_card_menu",
                contact_name=contact_name,
                device_serial=serial,
                message="Contact Card menu not found in attach panel",
            )

        await asyncio.sleep(share_service._STEP_DELAY)

        # Step 3: Composite picker search
        from wecom_automation.services.ui_search.strategy import (
            CompositeContactFinder,
            ScrollContactFinder,
            SearchContactFinder,
        )

        finder = CompositeContactFinder([
            SearchContactFinder(),
            ScrollContactFinder(),
        ])
        ok = False
        try:
            ok = await finder.find_and_select(contact_name, wecom.adb)
        finally:
            # Always back out — we never want to actually send a card here.
            for _ in range(3):
                try:
                    await wecom.go_back()
                except Exception:
                    break

        return TestContactReachabilityResponse(
            reachable=bool(ok),
            finder="composite_search_then_scroll",
            contact_name=contact_name,
            device_serial=serial,
            message=(
                "Contact found in picker"
                if ok
                else "Contact NOT found in picker — verify the name appears in WeCom contact picker"
            ),
        )
    except Exception as exc:
        logger.exception("Contact reachability probe failed")
        return TestContactReachabilityResponse(
            reachable=False,
            finder="error",
            contact_name=contact_name,
            device_serial=serial,
            message=f"Probe failed: {exc}",
        )


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
        from wecom_automation.services.media_actions.actions.auto_contact_share import AutoContactShareAction
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

        from wecom_automation.services.contact_share.service import ContactShareService
        contact_share_service = ContactShareService(wecom_service=None)
        bus.register(AutoContactShareAction(contact_share_service=contact_share_service))

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
