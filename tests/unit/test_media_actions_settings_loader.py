"""Tests for load_media_auto_action_settings."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path

from wecom_automation.services.media_actions.settings_loader import (
    DEFAULT_MEDIA_AUTO_ACTION_SETTINGS,
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


def test_load_merges_review_gate_fields():
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
                        "rating_server_url": "http://review.local:8080",
                        "upload_timeout_seconds": 45.0,
                        "upload_max_attempts": 2,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        conn.commit()
        conn.close()

        out = load_media_auto_action_settings(p)
        assert out["review_gate"]["enabled"] is True
        assert out["review_gate"]["rating_server_url"] == "http://review.local:8080"
        assert out["review_gate"]["upload_timeout_seconds"] == 45.0
        assert out["review_gate"]["upload_max_attempts"] == 2
        assert out["review_gate"]["video_review_policy"] == "extract_frame"
    finally:
        Path(p).unlink(missing_ok=True)
