"""
Tests for the shared media_actions factory: build_media_event_bus.

TDD red phase: defines expected behavior of the shared factory function
that both full-sync and follow-up paths use to construct a MediaEventBus.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wecom_automation.services.media_actions.factory import build_media_event_bus


def _create_settings_db(db_path: str, enabled: bool = True) -> None:
    """Create a minimal settings table with media_auto_actions config."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value_type TEXT NOT NULL,
            value_string TEXT,
            value_int INTEGER,
            value_float REAL,
            value_bool INTEGER,
            value_json TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO settings (category, key, value_type, value_bool) VALUES (?, ?, ?, ?)",
        ("media_auto_actions", "enabled", "boolean", int(enabled)),
    )
    conn.execute(
        "INSERT INTO settings (category, key, value_type, value_json) VALUES (?, ?, ?, ?)",
        (
            "media_auto_actions",
            "auto_blacklist",
            "json",
            json.dumps({"enabled": True, "reason": "test reason"}),
        ),
    )
    conn.execute(
        "INSERT INTO settings (category, key, value_type, value_json) VALUES (?, ?, ?, ?)",
        (
            "media_auto_actions",
            "auto_group_invite",
            "json",
            json.dumps({"enabled": True, "group_members": ["Manager"]}),
        ),
    )
    conn.commit()
    conn.close()


class TestBuildMediaEventBusDisabled:
    def test_returns_none_bus_when_disabled(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _create_settings_db(db_path, enabled=False)

        bus, settings = build_media_event_bus(db_path)

        assert bus is None
        assert settings["enabled"] is False

    def test_returns_none_bus_when_no_settings_table(self, tmp_path):
        db_path = str(tmp_path / "empty.db")
        sqlite3.connect(db_path).close()

        bus, settings = build_media_event_bus(db_path)

        assert bus is None
        assert settings["enabled"] is False


class TestBuildMediaEventBusEnabled:
    def test_returns_bus_with_three_actions_when_wecom_provided(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _create_settings_db(db_path, enabled=True)
        wecom = MagicMock()

        bus, settings = build_media_event_bus(db_path, wecom_service=wecom)

        assert bus is not None
        assert settings["enabled"] is True
        assert len(bus._actions) == 3
        action_names = [a.action_name for a in bus._actions]
        assert "auto_blacklist" in action_names
        assert "auto_group_invite" in action_names
        assert "auto_contact_share" in action_names

    def test_registers_contact_share_before_blacklist(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _create_settings_db(db_path, enabled=True)

        bus, _ = build_media_event_bus(db_path, wecom_service=MagicMock())

        assert bus is not None
        action_names = [a.action_name for a in bus._actions]
        assert action_names.index("auto_contact_share") < action_names.index("auto_blacklist")
        contact_action = bus._actions[action_names.index("auto_contact_share")]
        assert contact_action._restore_navigation_after_execute is False

    def test_registers_only_blacklist_when_no_wecom(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _create_settings_db(db_path, enabled=True)

        bus, settings = build_media_event_bus(db_path, wecom_service=None)

        assert bus is not None
        assert len(bus._actions) == 1
        assert bus._actions[0].action_name == "auto_blacklist"

    def test_passes_callback_to_bus(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _create_settings_db(db_path, enabled=True)
        callback = AsyncMock()

        bus, _ = build_media_event_bus(db_path, on_action_results=callback)

        assert bus is not None
        assert bus._on_action_results is callback

    def test_loads_settings_from_db(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _create_settings_db(db_path, enabled=True)

        _, settings = build_media_event_bus(db_path)

        assert settings["enabled"] is True
        assert settings["auto_blacklist"]["enabled"] is True
        assert settings["auto_blacklist"]["reason"] == "test reason"
        assert settings["auto_group_invite"]["enabled"] is True
        assert settings["auto_group_invite"]["group_members"] == ["Manager"]

    def test_loads_settings_from_explicit_settings_db(self, tmp_path):
        settings_db = str(tmp_path / "settings.db")
        device_db = str(tmp_path / "device.db")
        _create_settings_db(settings_db, enabled=True)
        sqlite3.connect(device_db).close()

        bus, settings = build_media_event_bus(device_db, settings_db_path=settings_db)

        assert bus is not None
        assert settings["enabled"] is True
        assert settings["auto_blacklist"]["reason"] == "test reason"
        assert settings["auto_group_invite"]["group_members"] == ["Manager"]

    def test_routes_side_effects_to_explicit_effects_db(self, tmp_path):
        settings_db = str(tmp_path / "settings.db")
        device_db = str(tmp_path / "device.db")
        effects_db = str(tmp_path / "effects.db")
        _create_settings_db(settings_db, enabled=True)
        sqlite3.connect(device_db).close()
        sqlite3.connect(effects_db).close()

        fake_blacklist_action = MagicMock(action_name="auto_blacklist")
        fake_group_action = MagicMock(action_name="auto_group_invite")

        with (
            patch("wecom_automation.services.media_actions.factory.BlacklistWriter") as mock_writer_cls,
            patch(
                "wecom_automation.services.media_actions.factory.AutoBlacklistAction",
                return_value=fake_blacklist_action,
            ),
            patch(
                "wecom_automation.services.media_actions.group_chat_service.GroupChatService"
            ) as mock_group_service_cls,
            patch(
                "wecom_automation.services.media_actions.actions.auto_group_invite.AutoGroupInviteAction",
                return_value=fake_group_action,
            ),
        ):
            bus, _ = build_media_event_bus(
                device_db,
                settings_db_path=settings_db,
                effects_db_path=effects_db,
                wecom_service=MagicMock(),
            )

        assert bus is not None
        mock_writer_cls.assert_called_once_with(effects_db)
        mock_group_service_cls.assert_called_once()
        assert mock_group_service_cls.call_args.kwargs["db_path"] == effects_db
