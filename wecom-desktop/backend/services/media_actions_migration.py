"""
One-time migration: seed global media-auto-action settings into per-device profiles.

Reads the legacy global settings from the ``settings`` table
(category ``media_auto_actions``) and creates ``device_action_profiles``
rows for every connected device that does not yet have profiles.

Idempotent: skips devices that already have any profile rows.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from wecom_automation.services.media_actions.settings_loader import (
    DEFAULT_MEDIA_AUTO_ACTION_SETTINGS,
    load_media_auto_action_settings,
)


def migrate_global_to_device_profiles(db_path: str) -> dict[str, int]:
    """Seed global media-auto-action settings into per-device profiles.

    Returns a stats dict with counts of rows inserted/skipped.
    """
    stats = {"devices_migrated": 0, "rows_inserted": 0, "skipped_no_global": 0, "skipped_already_has_profiles": 0}

    # Load global settings from settings table (if any overrides exist)
    global_settings = load_media_auto_action_settings(db_path)

    # Check if global settings differ from code defaults at all.
    # If they don't, there's nothing to migrate.
    import copy
    if global_settings == copy.deepcopy(DEFAULT_MEDIA_AUTO_ACTION_SETTINGS):
        stats["skipped_no_global"] = 1
        return stats

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        # Find all device serials that already have profile rows
        cur = conn.execute("SELECT DISTINCT device_serial FROM device_action_profiles")
        existing_serials = {row["device_serial"] for row in cur.fetchall()}

        # Find all known device serials from the devices table
        cur = conn.execute("SELECT serial FROM devices")
        device_serials = [row["serial"] for row in cur.fetchall()]

        if not device_serials:
            return stats

        for serial in device_serials:
            if serial in existing_serials:
                stats["skipped_already_has_profiles"] += 1
                continue

            # Seed all 4 action types + _master from global settings
            _seed_device_profiles(conn, serial, global_settings)
            stats["devices_migrated"] += 1

        conn.commit()
    finally:
        conn.close()

    return stats


def _seed_device_profiles(
    conn: sqlite3.Connection,
    device_serial: str,
    settings: dict[str, Any],
) -> int:
    """Insert profile rows for a device from the given settings dict."""
    rows_inserted = 0

    # Master switch
    master_enabled = 1 if settings.get("enabled", False) else 0
    conn.execute(
        """
        INSERT OR IGNORE INTO device_action_profiles (device_serial, action_type, enabled, config_json)
        VALUES (?, '_master', ?, '{}')
        """,
        (device_serial, master_enabled),
    )
    rows_inserted += 1

    # Per-action-type sections
    action_sections = [
        ("auto_blacklist", "auto_blacklist"),
        ("review_gate", "review_gate"),
        ("auto_group_invite", "auto_group_invite"),
        ("auto_contact_share", "auto_contact_share"),
    ]

    for section_key, action_type in action_sections:
        section = settings.get(section_key, {})
        enabled = 1 if section.get("enabled", False) else 0
        # Store all section fields except 'enabled' in config_json
        config = {k: v for k, v in section.items() if k != "enabled"}
        config_json = json.dumps(config, ensure_ascii=False)
        conn.execute(
            """
            INSERT OR IGNORE INTO device_action_profiles (device_serial, action_type, enabled, config_json)
            VALUES (?, ?, ?, ?)
            """,
            (device_serial, action_type, enabled, config_json),
        )
        rows_inserted += 1

    return rows_inserted
