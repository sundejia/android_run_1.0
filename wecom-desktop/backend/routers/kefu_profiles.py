"""
Kefu Action Profiles Router - API endpoints for per-kefu action configuration.

Provides CRUD for per-kefu overrides of media auto-action settings (auto_group_invite,
auto_contact_share). Settings not overridden per-kefu fall through to the global defaults.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.settings import get_settings_service

logger = logging.getLogger("kefu_profiles.router")
router = APIRouter()


# ============================================================================
# Pydantic Models
# ============================================================================


class KefuGroupInviteConfig(BaseModel):
    group_members: List[str] = Field(default_factory=list)
    group_name_template: str = "{customer_name}-{kefu_name}服务群"
    skip_if_group_exists: bool = True
    send_message_before_create: bool = False
    pre_create_message_text: str = ""
    send_test_message_after_create: bool = True
    test_message_text: str = "测试"
    post_confirm_wait_seconds: float = 1.0
    duplicate_name_policy: str = "first"


class KefuContactShareConfig(BaseModel):
    contact_name: str = ""
    skip_if_already_shared: bool = True
    cooldown_seconds: int = 0
    send_message_before_share: bool = False
    pre_share_message_text: str = ""


class KefuActionProfileBase(BaseModel):
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class KefuActionProfileResponse(BaseModel):
    id: int
    kefu_id: int
    kefu_name: str
    action_type: str
    enabled: bool
    config: dict[str, Any]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class KefuActionProfileSummary(BaseModel):
    kefu_id: int
    kefu_name: str
    department: Optional[str] = None
    has_group_invite_override: bool = False
    has_contact_share_override: bool = False
    group_invite_enabled: Optional[bool] = None
    contact_share_enabled: Optional[bool] = None


class EffectiveSettingsResponse(BaseModel):
    kefu_id: int
    kefu_name: str
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


def _kefu_exists(conn: sqlite3.Connection, kefu_id: int) -> bool:
    cur = conn.execute("SELECT 1 FROM kefus WHERE id = ? LIMIT 1", (kefu_id,))
    return cur.fetchone() is not None


def _get_kefu_name(conn: sqlite3.Connection, kefu_id: int) -> str | None:
    cur = conn.execute("SELECT name FROM kefus WHERE id = ?", (kefu_id,))
    row = cur.fetchone()
    return row["name"] if row else None


# ============================================================================
# Endpoints
# ============================================================================


@router.get("", response_model=List[KefuActionProfileSummary])
async def list_kefu_profiles():
    """List all kefus with their action profile override status."""
    def _sync():
        conn = _get_db()
        try:
            cur = conn.execute("""
                SELECT k.id, k.name, k.department,
                       gi.enabled AS gi_enabled,
                       cs.enabled AS cs_enabled
                FROM kefus k
                LEFT JOIN kefu_action_profiles gi
                    ON gi.kefu_id = k.id AND gi.action_type = 'auto_group_invite'
                LEFT JOIN kefu_action_profiles cs
                    ON cs.kefu_id = k.id AND cs.action_type = 'auto_contact_share'
                ORDER BY k.name
            """)
            results = []
            for row in cur.fetchall():
                results.append(KefuActionProfileSummary(
                    kefu_id=row["id"],
                    kefu_name=row["name"],
                    department=row["department"],
                    has_group_invite_override=row["gi_enabled"] is not None,
                    has_contact_share_override=row["cs_enabled"] is not None,
                    group_invite_enabled=row["gi_enabled"] if row["gi_enabled"] is not None else None,
                    contact_share_enabled=row["cs_enabled"] if row["cs_enabled"] is not None else None,
                ))
            return results
        finally:
            conn.close()

    return await asyncio.to_thread(_sync)


@router.get("/{kefu_id}/actions", response_model=List[KefuActionProfileResponse])
async def get_kefu_actions(kefu_id: int):
    """Get all action profile overrides for a kefu."""
    def _sync():
        conn = _get_db()
        try:
            if not _kefu_exists(conn, kefu_id):
                raise HTTPException(status_code=404, detail="Kefu not found")

            kefu_name = _get_kefu_name(conn, kefu_id)
            cur = conn.execute(
                "SELECT * FROM kefu_action_profiles WHERE kefu_id = ? ORDER BY action_type",
                (kefu_id,),
            )
            results = []
            for row in cur.fetchall():
                config = json.loads(row["config_json"]) if row["config_json"] else {}
                results.append(KefuActionProfileResponse(
                    id=row["id"],
                    kefu_id=kefu_id,
                    kefu_name=kefu_name or "",
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


@router.put("/{kefu_id}/actions/{action_type}", response_model=KefuActionProfileResponse)
async def upsert_kefu_action(kefu_id: int, action_type: str, body: KefuActionProfileBase):
    """Create or update a per-kefu action profile override."""
    if action_type not in VALID_ACTION_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid action_type: {action_type}. Must be one of {VALID_ACTION_TYPES}")

    def _sync():
        conn = _get_db()
        try:
            if not _kefu_exists(conn, kefu_id):
                raise HTTPException(status_code=404, detail="Kefu not found")

            kefu_name = _get_kefu_name(conn, kefu_id)
            config_json = json.dumps(body.config, ensure_ascii=False)

            conn.execute(
                """
                INSERT INTO kefu_action_profiles (kefu_id, action_type, enabled, config_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(kefu_id, action_type) DO UPDATE SET
                    enabled = excluded.enabled,
                    config_json = excluded.config_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (kefu_id, action_type, int(body.enabled), config_json),
            )
            conn.commit()

            cur = conn.execute(
                "SELECT * FROM kefu_action_profiles WHERE kefu_id = ? AND action_type = ?",
                (kefu_id, action_type),
            )
            row = cur.fetchone()
            config = json.loads(row["config_json"]) if row["config_json"] else {}

            return KefuActionProfileResponse(
                id=row["id"],
                kefu_id=kefu_id,
                kefu_name=kefu_name or "",
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
        "type": "kefu_action_profile_updated",
        "timestamp": datetime.now().isoformat(),
        "data": result.model_dump(),
    })

    return result


@router.delete("/{kefu_id}/actions/{action_type}")
async def delete_kefu_action(kefu_id: int, action_type: str):
    """Delete a per-kefu action profile override (reverts to global defaults)."""
    if action_type not in VALID_ACTION_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid action_type: {action_type}")

    def _sync():
        conn = _get_db()
        try:
            cur = conn.execute(
                "DELETE FROM kefu_action_profiles WHERE kefu_id = ? AND action_type = ?",
                (kefu_id, action_type),
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
        "type": "kefu_action_profile_deleted",
        "timestamp": datetime.now().isoformat(),
        "data": {"kefu_id": kefu_id, "action_type": action_type},
    })

    return {"status": "ok", "kefu_id": kefu_id, "action_type": action_type}


@router.get("/{kefu_id}/effective", response_model=EffectiveSettingsResponse)
async def get_effective_settings(kefu_id: int):
    """Get the fully resolved (global + per-kefu) media action settings for a kefu."""
    def _sync():
        conn = _get_db()
        try:
            kefu_name = _get_kefu_name(conn, kefu_id)
            if not kefu_name:
                raise HTTPException(status_code=404, detail="Kefu not found")
            return kefu_name
        finally:
            conn.close()

    kefu_name = await asyncio.to_thread(_sync)

    def _resolve():
        from wecom_automation.database.schema import get_db_path
        from wecom_automation.services.media_actions.kefu_resolver import resolve_media_settings_from_db

        db_path = str(get_db_path())
        return resolve_media_settings_from_db(kefu_name, db_path)

    settings = await asyncio.to_thread(_resolve)

    return EffectiveSettingsResponse(
        kefu_id=kefu_id,
        kefu_name=kefu_name,
        settings=settings,
    )
