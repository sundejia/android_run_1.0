"""
Load media auto-action settings from the desktop settings SQLite table.

Reads category ``media_auto_actions`` from the same ``settings`` table used by
the FastAPI SettingsService (``wecom-desktop/backend``), without importing backend code.

This module is the **single source of truth** for the media auto-actions
default schema. Both the desktop backend (``settings/defaults.py`` registry
and ``routers/media_actions.py`` API surface) and the python-core
consumers import from here so adding a new field never has to be
synchronised across multiple hard-coded copies.

Note (2026-05-12): ``review_gate`` no longer holds an own
``rating_server_url`` / ``upload_timeout_seconds`` / ``upload_max_attempts``.
Those values are app-level singletons and live under the ``general``
category (``image_server_ip``, ``image_review_timeout_seconds``) — the
same fields the realtime image-review path (``image_review_client``)
already consumed. ``build_review_components`` in
``services/review/runtime.py`` reads them through the SettingsService.
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
        # Whether the review gate is consulted at all. Server URL and
        # upload timeout are read from general.image_server_ip /
        # general.image_review_timeout_seconds (same source as the
        # realtime image-review client).
        "enabled": False,
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
            merged = {**result[section], **stored[section]}
            # Drop legacy keys that have been promoted to general settings
            # (kept on disk for one release for safety; ignored at read time
            # so they cannot accidentally diverge from general.image_*).
            if section == "review_gate":
                for legacy_key in ("rating_server_url", "upload_timeout_seconds", "upload_max_attempts"):
                    merged.pop(legacy_key, None)
            result[section] = merged

    return result


# ---------------------------------------------------------------------------
# General image-review settings (cross-process loader)
# ---------------------------------------------------------------------------

DEFAULT_IMAGE_REVIEW_SERVER_URL = ""
DEFAULT_IMAGE_REVIEW_TIMEOUT_SECONDS = 40
DEFAULT_IMAGE_UPLOAD_ENABLED = True


def load_general_image_review_settings(db_path: str) -> dict[str, Any]:
    """Load the general-category image-review fields used by both the
    realtime image_review_client and the review-gate runtime.

    Reads:
        general.image_server_ip          (str, default "")
        general.image_review_timeout_seconds (int, default 40)
        general.image_upload_enabled     (bool, default True)

    Returns a dict with stable keys regardless of whether the rows exist.
    Used by ``build_review_components`` so the python-core sync path picks
    up the same values that the desktop SettingsView writes.
    """
    result: dict[str, Any] = {
        "image_server_ip": DEFAULT_IMAGE_REVIEW_SERVER_URL,
        "image_review_timeout_seconds": DEFAULT_IMAGE_REVIEW_TIMEOUT_SECONDS,
        "image_upload_enabled": DEFAULT_IMAGE_UPLOAD_ENABLED,
    }

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT key, value_type, value_string, value_int, value_float, value_bool, value_json
            FROM settings
            WHERE category = ? AND key IN (?, ?, ?)
            """,
            (
                "general",
                "image_server_ip",
                "image_review_timeout_seconds",
                "image_upload_enabled",
            ),
        )
        rows = cur.fetchall()
        conn.close()
    except Exception as exc:
        logger.debug("Could not load general image-review settings from %s: %s", db_path, exc)
        return result

    for row in rows:
        key = row["key"]
        value = _row_value(row)
        if value is None:
            continue
        if key == "image_server_ip" and isinstance(value, str):
            result[key] = value.strip()
        elif key == "image_review_timeout_seconds":
            try:
                result[key] = max(1, int(value))
            except (TypeError, ValueError):
                pass
        elif key == "image_upload_enabled":
            result[key] = bool(value)

    return result
