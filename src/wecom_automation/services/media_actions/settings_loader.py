"""
Load media auto-action settings from the desktop settings SQLite table.

Reads category ``media_auto_actions`` from the same ``settings`` table used by
the FastAPI SettingsService (``wecom-desktop/backend``), without importing backend code.
"""

from __future__ import annotations

import copy
import json
import logging
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MEDIA_AUTO_ACTION_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "auto_blacklist": {
        "enabled": False,
        "reason": "Customer sent media (auto)",
        "skip_if_already_blacklisted": True,
        # When False (default) the action blacklists any media-sending
        # customer immediately. When True, blacklist defers to the
        # image-rating-server review verdict via evaluate_gate_pass and
        # mirrors the gate used by auto-group-invite.
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


def _row_value(row: sqlite3.Row) -> Any:
    vt = row["value_type"]
    if vt == "string":
        return row["value_string"]
    if vt == "int":
        return row["value_int"]
    if vt == "float":
        return row["value_float"]
    if vt == "boolean":
        return bool(row["value_bool"])
    if vt == "json":
        raw = row["value_json"]
        if not raw:
            return None
        return json.loads(raw)
    return row["value_string"]


def load_media_auto_action_settings(db_path: str) -> dict[str, Any]:
    """
    Load merged media auto-action settings from the control database.

    If the ``settings`` table is missing or empty for this category, returns defaults.
    """
    result = copy.deepcopy(DEFAULT_MEDIA_AUTO_ACTION_SETTINGS)
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT key, value_type, value_string, value_int, value_float, value_bool, value_json
            FROM settings
            WHERE category = ?
            """,
            ("media_auto_actions",),
        )
        rows = cur.fetchall()
        conn.close()
    except Exception as exc:
        logger.debug("Could not load media_auto_actions settings from %s: %s", db_path, exc)
        return result

    stored: dict[str, Any] = {}
    for row in rows:
        stored[row["key"]] = _row_value(row)

    if "enabled" in stored:
        result["enabled"] = bool(stored["enabled"])

    for section in ("auto_blacklist", "auto_group_invite", "auto_contact_share", "review_gate"):
        if section in stored and isinstance(stored[section], dict):
            result[section] = {**result[section], **stored[section]}

    return result
