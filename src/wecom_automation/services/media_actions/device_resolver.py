"""
Per-device media action settings resolver.

Merges global settings (from ``settings_loader``) with per-device overrides
stored in ``device_action_profiles``, producing a single settings dict that
is structurally identical to what ``load_media_auto_action_settings`` returns.
Downstream actions receive the merged dict without needing any code changes.
"""

from __future__ import annotations

import copy
import json
import logging
import sqlite3
from typing import Any

from wecom_automation.services.media_actions.settings_loader import (
    load_media_auto_action_settings,
)

logger = logging.getLogger(__name__)

_SUPPORTED_ACTION_TYPES: dict[str, str] = {
    "auto_group_invite": "auto_group_invite",
    "auto_contact_share": "auto_contact_share",
}


def resolve_media_settings_by_device(
    global_settings: dict[str, Any],
    device_serial: str,
    db_path: str,
) -> dict[str, Any]:
    """Merge global settings with per-device overrides from ``device_action_profiles``.

    Resolution order (later wins):
    1. Code defaults (already baked into *global_settings*)
    2. ``settings`` table global overrides (already baked into *global_settings*)
    3. ``device_action_profiles`` rows for this device serial

    When *device_serial* is empty or no profile rows exist, returns *global_settings*
    unchanged.
    """
    if not device_serial or not db_path:
        return global_settings

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")

        cur = conn.execute(
            "SELECT action_type, enabled, config_json FROM device_action_profiles WHERE device_serial = ?",
            (device_serial,),
        )
        rows = cur.fetchall()
        conn.close()
    except Exception as exc:
        logger.debug("Could not load device_action_profiles for serial=%s: %s", device_serial, exc)
        return global_settings

    if not rows:
        return global_settings

    result = copy.deepcopy(global_settings)

    for row in rows:
        action_type = row["action_type"]
        section_key = _SUPPORTED_ACTION_TYPES.get(action_type)
        if not section_key:
            continue

        if not row["enabled"]:
            result.setdefault(section_key, {})["enabled"] = False
            logger.info("Per-device override: device=%s action=%s disabled", device_serial, action_type)
            continue

        try:
            config = json.loads(row["config_json"]) if row["config_json"] else {}
        except json.JSONDecodeError:
            logger.warning("Invalid config_json for device=%s action=%s; skipping", device_serial, action_type)
            continue

        if not isinstance(config, dict) or not config:
            continue

        section = result.setdefault(section_key, {})
        section.update(config)

        logger.info(
            "Per-device override applied: device=%s action=%s fields=%s",
            device_serial,
            action_type,
            list(config.keys()),
        )

    return result


def resolve_media_settings_by_device_from_db(
    device_serial: str,
    settings_db_path: str,
    profiles_db_path: str | None = None,
) -> dict[str, Any]:
    """Load global settings from DB, then resolve per-device overrides."""
    global_settings = load_media_auto_action_settings(settings_db_path)
    profiles_db = profiles_db_path or settings_db_path
    return resolve_media_settings_by_device(global_settings, device_serial, profiles_db)
