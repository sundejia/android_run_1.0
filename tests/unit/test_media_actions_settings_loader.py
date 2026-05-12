"""Tests for load_media_auto_action_settings."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path

from wecom_automation.services.media_actions.settings_loader import (
    DEFAULT_IMAGE_REVIEW_TIMEOUT_SECONDS,
    DEFAULT_IMAGE_UPLOAD_ENABLED,
    DEFAULT_MEDIA_AUTO_ACTION_SETTINGS,
    load_general_image_review_settings,
    load_media_auto_action_settings,
)


def _init_settings_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value_type TEXT NOT NULL,
            value_string TEXT,
            value_int INTEGER,
            value_float REAL,
            value_bool INTEGER,
            value_json TEXT,
            UNIQUE(category, key)
        )
        """
    )
    conn.commit()
    conn.close()


def test_load_defaults_when_no_db_table():
    # In-memory DB has no settings table → defaults
    out = load_media_auto_action_settings(":memory:")
    assert out["enabled"] is False
    assert out["auto_blacklist"]["enabled"] is False
    assert out == DEFAULT_MEDIA_AUTO_ACTION_SETTINGS


def test_auto_blacklist_default_does_not_require_review_pass():
    """Regression for 2026-05-07: defaulting require_review_pass=False keeps
    auto-blacklist usable on deployments that never opted into the
    image-rating-server review pipeline. Flipping the default would silently
    re-introduce the 'Skipping auto-blacklist: review data missing' bug."""
    out = load_media_auto_action_settings(":memory:")
    assert out["auto_blacklist"]["require_review_pass"] is False


def test_load_merges_stored_rows():
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_settings_db(Path(p))
        conn = sqlite3.connect(p)
        conn.execute(
            """
            INSERT INTO settings (category, key, value_type, value_bool, value_json)
            VALUES ('media_auto_actions', 'enabled', 'boolean', 1, NULL)
            """
        )
        conn.execute(
            """
            INSERT INTO settings (category, key, value_type, value_bool, value_json)
            VALUES (
                'media_auto_actions', 'auto_blacklist', 'json', NULL,
                ?
            )
            """,
            (
                json.dumps(
                    {"enabled": True, "reason": "x", "skip_if_already_blacklisted": False},
                    ensure_ascii=False,
                ),
            ),
        )
        conn.commit()
        conn.close()

        out = load_media_auto_action_settings(p)
        assert out["enabled"] is True
        assert out["auto_blacklist"]["enabled"] is True
        assert out["auto_blacklist"]["reason"] == "x"
        assert out["auto_blacklist"]["skip_if_already_blacklisted"] is False
    finally:
        Path(p).unlink(missing_ok=True)


def test_load_group_invite_defaults_are_backward_compatible():
    out = load_media_auto_action_settings(":memory:")

    assert out["auto_group_invite"]["member_source"] == "manual"
    assert out["auto_group_invite"]["send_test_message_after_create"] is True
    assert out["auto_group_invite"]["test_message_text"] == "测试"
    assert out["auto_group_invite"]["post_confirm_wait_seconds"] == 1.0
    assert out["auto_group_invite"]["duplicate_name_policy"] == "first"
    assert out["auto_group_invite"]["video_invite_policy"] == "extract_frame"
    assert out["review_gate"]["enabled"] is False
    assert out["review_gate"]["video_review_policy"] == "extract_frame"
    # 2026-05-12 dedup: review_gate no longer carries a server URL of its own.
    # Asserting the negative locks the schema so a future reviewer cannot
    # silently re-introduce the dual-write divergence.
    assert "rating_server_url" not in out["review_gate"]
    assert "upload_timeout_seconds" not in out["review_gate"]
    assert "upload_max_attempts" not in out["review_gate"]


def test_load_merges_new_group_invite_fields():
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_settings_db(Path(p))
        conn = sqlite3.connect(p)
        conn.execute(
            """
            INSERT INTO settings (category, key, value_type, value_bool)
            VALUES ('media_auto_actions', 'enabled', 'boolean', 1)
            """
        )
        conn.execute(
            """
            INSERT INTO settings (category, key, value_type, value_json)
            VALUES (
                'media_auto_actions', 'auto_group_invite', 'json', ?
            )
            """,
            (
                json.dumps(
                    {
                        "enabled": True,
                        "group_members": ["经理A"],
                        "member_source": "resolved",
                        "send_test_message_after_create": False,
                        "test_message_text": "联调消息",
                        "post_confirm_wait_seconds": 2.0,
                        "duplicate_name_policy": "first",
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        conn.commit()
        conn.close()

        out = load_media_auto_action_settings(p)
        assert out["enabled"] is True
        assert out["auto_group_invite"]["enabled"] is True
        assert out["auto_group_invite"]["group_members"] == ["经理A"]
        assert out["auto_group_invite"]["member_source"] == "resolved"
        assert out["auto_group_invite"]["send_test_message_after_create"] is False
        assert out["auto_group_invite"]["test_message_text"] == "联调消息"
        assert out["auto_group_invite"]["post_confirm_wait_seconds"] == 2.0
        assert out["auto_group_invite"]["duplicate_name_policy"] == "first"
    finally:
        Path(p).unlink(missing_ok=True)


def test_load_strips_legacy_review_gate_url_and_timeout():
    """2026-05-12 dedup regression: legacy review_gate.rating_server_url /
    upload_timeout_seconds / upload_max_attempts rows that survive in old
    DBs MUST be silently stripped when loading. The single source for these
    values is now general.image_server_ip / image_review_timeout_seconds.
    Letting them through would re-introduce the dual-source divergence.
    """
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_settings_db(Path(p))
        conn = sqlite3.connect(p)
        conn.execute(
            """
            INSERT INTO settings (category, key, value_type, value_bool)
            VALUES ('media_auto_actions', 'enabled', 'boolean', 1)
            """
        )
        conn.execute(
            """
            INSERT INTO settings (category, key, value_type, value_json)
            VALUES ('media_auto_actions', 'review_gate', 'json', ?)
            """,
            (
                json.dumps(
                    {
                        "enabled": True,
                        "rating_server_url": "http://legacy.local:9999",
                        "upload_timeout_seconds": 45.0,
                        "upload_max_attempts": 2,
                        "video_review_policy": "skip",
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        conn.commit()
        conn.close()

        out = load_media_auto_action_settings(p)
        assert out["review_gate"]["enabled"] is True
        assert out["review_gate"]["video_review_policy"] == "skip"
        # Legacy fields must be dropped at read time even when they exist
        # on disk, otherwise downstream consumers would silently see a
        # different rating-server URL than the realtime path.
        assert "rating_server_url" not in out["review_gate"]
        assert "upload_timeout_seconds" not in out["review_gate"]
        assert "upload_max_attempts" not in out["review_gate"]
    finally:
        Path(p).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# load_general_image_review_settings
# ---------------------------------------------------------------------------


def test_general_image_review_defaults_when_no_table():
    out = load_general_image_review_settings(":memory:")
    assert out["image_server_ip"] == ""
    assert out["image_review_timeout_seconds"] == DEFAULT_IMAGE_REVIEW_TIMEOUT_SECONDS
    assert out["image_upload_enabled"] is DEFAULT_IMAGE_UPLOAD_ENABLED


def test_general_image_review_reads_stored_rows():
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_settings_db(Path(p))
        conn = sqlite3.connect(p)
        conn.execute(
            "INSERT INTO settings (category, key, value_type, value_string) "
            "VALUES ('general', 'image_server_ip', 'string', '  http://review.local:8080  ')"
        )
        conn.execute(
            "INSERT INTO settings (category, key, value_type, value_int) "
            "VALUES ('general', 'image_review_timeout_seconds', 'int', 25)"
        )
        conn.execute(
            "INSERT INTO settings (category, key, value_type, value_bool) "
            "VALUES ('general', 'image_upload_enabled', 'boolean', 0)"
        )
        conn.commit()
        conn.close()

        out = load_general_image_review_settings(p)
        # whitespace is trimmed so consumers do not have to defend against it.
        assert out["image_server_ip"] == "http://review.local:8080"
        assert out["image_review_timeout_seconds"] == 25
        assert out["image_upload_enabled"] is False
    finally:
        Path(p).unlink(missing_ok=True)


def test_general_image_review_clamps_timeout_to_at_least_one():
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_settings_db(Path(p))
        conn = sqlite3.connect(p)
        conn.execute(
            "INSERT INTO settings (category, key, value_type, value_int) "
            "VALUES ('general', 'image_review_timeout_seconds', 'int', 0)"
        )
        conn.commit()
        conn.close()

        out = load_general_image_review_settings(p)
        assert out["image_review_timeout_seconds"] == 1
    finally:
        Path(p).unlink(missing_ok=True)
