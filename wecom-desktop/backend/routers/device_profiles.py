"""
Device Action Profiles Router - API endpoints for per-device action configuration.

Provides CRUD for per-device overrides of media auto-action settings (auto_group_invite,
auto_contact_share). Settings not overridden per-device fall through to the global defaults.
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


class DeviceActionProfileSummary(BaseModel):
    device_serial: str
    model: Optional[str] = None
    manufacturer: Optional[str] = None
    has_group_invite_override: bool = False
    has_contact_share_override: bool = False
    group_invite_enabled: Optional[bool] = None
    contact_share_enabled: Optional[bool] = None


class DeviceEffectiveSettingsResponse(BaseModel):
    device_serial: str
    settings: dict[str, Any]


VALID_ACTION_TYPES = {"auto_group_invite", "auto_contact_share"}


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
    """List all devices with their action profile override status."""
    def _sync():
        conn = _get_db()
        try:
            cur = conn.execute("""
                SELECT d.serial, d.model, d.manufacturer,
                       gi.enabled AS gi_enabled,
                       cs.enabled AS cs_enabled
                FROM devices d
                LEFT JOIN device_action_profiles gi
                    ON gi.device_serial = d.serial AND gi.action_type = 'auto_group_invite'
                LEFT JOIN device_action_profiles cs
                    ON cs.device_serial = d.serial AND cs.action_type = 'auto_contact_share'
                ORDER BY d.serial
            """)
            results = []
            for row in cur.fetchall():
                results.append(DeviceActionProfileSummary(
                    device_serial=row["serial"],
                    model=row["model"],
                    manufacturer=row["manufacturer"],
                    has_group_invite_override=row["gi_enabled"] is not None,
                    has_contact_share_override=row["cs_enabled"] is not None,
                    group_invite_enabled=row["gi_enabled"] if row["gi_enabled"] is not None else None,
                    contact_share_enabled=row["cs_enabled"] if row["cs_enabled"] is not None else None,
                ))
            return results
        finally:
            conn.close()

    return await asyncio.to_thread(_sync)


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
