"""
Device Action Profiles Router - API endpoints for per-device action configuration.

Provides CRUD for per-device overrides of media auto-action settings (auto_blacklist,
review_gate, auto_group_invite, auto_contact_share). Settings not overridden per-device
fall through to the global defaults.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("device_profiles.router")
router = APIRouter()


# ============================================================================
# Pydantic Models
# ============================================================================


class DeviceActionProfileBase(BaseModel):
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class DeviceActionProfileResponse(BaseModel):
    id: int
    device_serial: str
    action_type: str
    enabled: bool
    config: dict[str, Any]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ActionOverrideStatus(BaseModel):
    enabled: Optional[bool] = None


class DeviceActionProfileSummary(BaseModel):
    device_serial: str
    model: Optional[str] = None
    manufacturer: Optional[str] = None
    overrides: dict[str, ActionOverrideStatus] = Field(default_factory=dict)
    has_any_override: bool = False
    # Backward-compat convenience fields
    has_group_invite_override: bool = False
    has_contact_share_override: bool = False
    group_invite_enabled: Optional[bool] = None
    contact_share_enabled: Optional[bool] = None


class DeviceEffectiveSettingsResponse(BaseModel):
    device_serial: str
    settings: dict[str, Any]


VALID_ACTION_TYPES = {
    "auto_blacklist",
    "review_gate",
    "auto_group_invite",
    "auto_contact_share",
}


# ============================================================================
# Helpers
# ============================================================================


def _get_db() -> sqlite3.Connection:
    from services.conversation_storage import open_shared_sqlite
    from wecom_automation.database.schema import get_db_path

    db_path = str(get_db_path())
    return open_shared_sqlite(db_path, row_factory=True)


# ============================================================================
# Endpoints
# ============================================================================


@router.get("", response_model=List[DeviceActionProfileSummary])
async def list_device_profiles():
    """List all connected devices with their action profile override status.

    Uses ADB real-time discovery (same source as the Devices page) so
    devices appear immediately when plugged in, without requiring a sync.
    """
    from routers.devices import get_discovery_service

    try:
        service = get_discovery_service()
        adb_devices = await service.list_devices(include_properties=True)
    except Exception:
        adb_devices = []

    # Build override lookup from DB in one query
    def _load_overrides() -> dict:
        conn = _get_db()
        try:
            cur = conn.execute(
                "SELECT device_serial, action_type, enabled FROM device_action_profiles"
            )
            overrides: dict[str, dict[str, bool | None]] = {}
            for row in cur.fetchall():
                serial = row["device_serial"]
                overrides.setdefault(serial, {})[row["action_type"]] = bool(row["enabled"])
            return overrides
        finally:
            conn.close()

    overrides = await asyncio.to_thread(_load_overrides)

    results = []
    for d in adb_devices:
        dev_overrides = overrides.get(d.serial, {})
        override_map = {
            k: ActionOverrideStatus(enabled=v) for k, v in dev_overrides.items()
        }
        gi_enabled = dev_overrides.get("auto_group_invite")
        cs_enabled = dev_overrides.get("auto_contact_share")
        results.append(DeviceActionProfileSummary(
            device_serial=d.serial,
            model=d.model,
            manufacturer=d.manufacturer,
            overrides=override_map,
            has_any_override=len(dev_overrides) > 0,
            has_group_invite_override=gi_enabled is not None,
            has_contact_share_override=cs_enabled is not None,
            group_invite_enabled=gi_enabled,
            contact_share_enabled=cs_enabled,
        ))
    return results


@router.get("/{device_serial}/actions", response_model=List[DeviceActionProfileResponse])
async def get_device_actions(device_serial: str):
    """Get all action profile overrides for a device."""
    def _sync():
        conn = _get_db()
        try:
            cur = conn.execute(
                "SELECT * FROM device_action_profiles WHERE device_serial = ? ORDER BY action_type",
                (device_serial,),
            )
            results = []
            for row in cur.fetchall():
                config = json.loads(row["config_json"]) if row["config_json"] else {}
                results.append(DeviceActionProfileResponse(
                    id=row["id"],
                    device_serial=device_serial,
                    action_type=row["action_type"],
                    enabled=bool(row["enabled"]),
                    config=config,
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                ))
            return results
        finally:
            conn.close()

    return await asyncio.to_thread(_sync)


@router.put("/{device_serial}/actions/{action_type}", response_model=DeviceActionProfileResponse)
async def upsert_device_action(device_serial: str, action_type: str, body: DeviceActionProfileBase):
    """Create or update a per-device action profile override."""
    if action_type not in VALID_ACTION_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid action_type: {action_type}. Must be one of {VALID_ACTION_TYPES}")

    def _sync():
        conn = _get_db()
        try:
            config_json = json.dumps(body.config, ensure_ascii=False)

            conn.execute(
                """
                INSERT INTO device_action_profiles (device_serial, action_type, enabled, config_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(device_serial, action_type) DO UPDATE SET
                    enabled = excluded.enabled,
                    config_json = excluded.config_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (device_serial, action_type, int(body.enabled), config_json),
            )
            conn.commit()

            cur = conn.execute(
                "SELECT * FROM device_action_profiles WHERE device_serial = ? AND action_type = ?",
                (device_serial, action_type),
            )
            row = cur.fetchone()
            config = json.loads(row["config_json"]) if row["config_json"] else {}

            return DeviceActionProfileResponse(
                id=row["id"],
                device_serial=device_serial,
                action_type=row["action_type"],
                enabled=bool(row["enabled"]),
                config=config,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        finally:
            conn.close()

    result = await asyncio.to_thread(_sync)

    from datetime import datetime
    from routers.global_websocket import get_global_ws_manager

    manager = get_global_ws_manager()
    await manager.broadcast({
        "type": "device_action_profile_updated",
        "timestamp": datetime.now().isoformat(),
        "data": result.model_dump(),
    })

    return result


@router.delete("/{device_serial}/actions/{action_type}")
async def delete_device_action(device_serial: str, action_type: str):
    """Delete a per-device action profile override (reverts to global defaults)."""
    if action_type not in VALID_ACTION_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid action_type: {action_type}")

    def _sync():
        conn = _get_db()
        try:
            cur = conn.execute(
                "DELETE FROM device_action_profiles WHERE device_serial = ? AND action_type = ?",
                (device_serial, action_type),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    deleted = await asyncio.to_thread(_sync)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Profile not found")

    from datetime import datetime
    from routers.global_websocket import get_global_ws_manager

    manager = get_global_ws_manager()
    await manager.broadcast({
        "type": "device_action_profile_deleted",
        "timestamp": datetime.now().isoformat(),
        "data": {"device_serial": device_serial, "action_type": action_type},
    })

    return {"status": "ok", "device_serial": device_serial, "action_type": action_type}


@router.get("/{device_serial}/effective", response_model=DeviceEffectiveSettingsResponse)
async def get_effective_settings(device_serial: str):
    """Get the fully resolved (global + per-device) media action settings for a device."""
    def _resolve():
        from wecom_automation.database.schema import get_db_path
        from wecom_automation.services.media_actions.device_resolver import resolve_media_settings_by_device_from_db

        db_path = str(get_db_path())
        return resolve_media_settings_by_device_from_db(device_serial, db_path)

    settings = await asyncio.to_thread(_resolve)

    return DeviceEffectiveSettingsResponse(
        device_serial=device_serial,
        settings=settings,
    )
