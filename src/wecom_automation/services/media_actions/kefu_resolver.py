"""
Per-kefu media action settings resolver.

.. deprecated:: 2026-05-13 (schema v16)
    Superseded by :mod:`device_resolver` which resolves settings per **device**
    rather than per kefu.  The ``kefu_action_profiles`` table is no longer written
    by any active code path; existing rows were migrated to ``device_action_profiles``
    by the v15→v16 migration.  This module is retained only for backward-compat
    reference.  Do **not** add new callers — use
    :func:`~wecom_automation.services.media_actions.device_resolver.resolve_media_settings_by_device`
    instead.
"""

from __future__ import annotations

import copy
import json
import logging
import sqlite3
from typing import Any

from wecom_automation.services.media_actions.settings_loader import (
    DEFAULT_MEDIA_AUTO_ACTION_SETTINGS,
    load_media_auto_action_settings,
)

logger = logging.getLogger(__name__)

# Action types that support per-kefu overrides and the settings section they map to.
_SUPPORTED_ACTION_TYPES: dict[str, str] = {
    "auto_group_invite": "auto_group_invite",
    "auto_contact_share": "auto_contact_share",
}


def resolve_media_settings(
    global_settings: dict[str, Any],
    kefu_name: str,
    db_path: str,
) -> dict[str, Any]:
    """
    Merge global settings with per-kefu overrides from ``kefu_action_profiles``.

    Resolution order (later wins):
    1. ``DEFAULT_MEDIA_AUTO_ACTION_SETTINGS`` (code defaults)
    2. ``settings`` table global overrides (already baked into *global_settings*)
    3. ``kefu_action_profiles`` rows for this kefu

    When *kefu_name* is empty or no profile rows exist, returns *global_settings*
    unchanged (safe fallback).

    Args:
        global_settings: The already-loaded global media-auto-action settings dict.
        kefu_name: Name of the logged-in kefu to look up overrides for.
        db_path: Path to the SQLite database containing ``kefus`` and
            ``kefu_action_profiles`` tables.

    Returns:
        A new dict with the same shape as *global_settings*, with per-kefu
        fields merged in.
    """
    if not kefu_name or not db_path:
        return global_settings

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")

        # Resolve kefu_name → kefu_id
        cur = conn.execute("SELECT id FROM kefus WHERE name = ? LIMIT 1", (kefu_name,))
        kefu_row = cur.fetchone()
        if not kefu_row:
            conn.close()
            logger.debug("No kefu row found for name=%s; using global settings", kefu_name)
            return global_settings

        kefu_id = kefu_row["id"]

        # Load all profile rows for this kefu
        cur = conn.execute(
            "SELECT action_type, enabled, config_json FROM kefu_action_profiles WHERE kefu_id = ?",
            (kefu_id,),
        )
        rows = cur.fetchall()
        conn.close()
    except Exception as exc:
        logger.debug("Could not load kefu_action_profiles for kefu=%s: %s", kefu_name, exc)
        return global_settings

    if not rows:
        return global_settings

    # Deep-merge: start from a copy of global_settings
    result = copy.deepcopy(global_settings)

    for row in rows:
        action_type = row["action_type"]
        section_key = _SUPPORTED_ACTION_TYPES.get(action_type)
        if not section_key:
            continue

        if not row["enabled"]:
            # Per-kefu disabled: override the section-level enabled flag
            result.setdefault(section_key, {})["enabled"] = False
            logger.info(
                "Per-kefu override: kefu=%s action=%s disabled",
                kefu_name,
                action_type,
            )
            continue

        # Merge config_json fields into the section
        try:
            config = json.loads(row["config_json"]) if row["config_json"] else {}
        except json.JSONDecodeError:
            logger.warning("Invalid config_json for kefu=%s action=%s; skipping", kefu_name, action_type)
            continue

        if not isinstance(config, dict) or not config:
            continue

        section = result.setdefault(section_key, {})
        section.update(config)

        logger.info(
            "Per-kefu override applied: kefu=%s action=%s fields=%s",
            kefu_name,
            action_type,
            list(config.keys()),
        )

    return result


def resolve_media_settings_from_db(
    kefu_name: str,
    settings_db_path: str,
    profiles_db_path: str | None = None,
) -> dict[str, Any]:
    """
    Convenience wrapper that loads global settings from the database and then
    resolves per-kefu overrides in one call.

    Args:
        kefu_name: Name of the logged-in kefu.
        settings_db_path: Path to the DB containing the ``settings`` table.
        profiles_db_path: Path to the DB containing ``kefu_action_profiles``.
            Defaults to ``settings_db_path`` when omitted.

    Returns:
        Fully resolved media-auto-action settings dict.
    """
    global_settings = load_media_auto_action_settings(settings_db_path)
    profiles_db = profiles_db_path or settings_db_path
    return resolve_media_settings(global_settings, kefu_name, profiles_db)
