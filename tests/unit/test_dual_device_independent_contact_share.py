"""
Tests for per-device independent media action settings.

Verifies that when two devices are connected simultaneously, each device
resolves its own independent contact share configuration from
``device_action_profiles``, and the factory / action layer correctly
uses the device-specific settings.

Covers:
- resolve_device_settings_from_profiles_only with multiple devices
- build_media_event_bus resolves per-device settings independently
- AutoContactShareAction.should_execute gates on per-device settings
- Full isolation: device A's config never leaks to device B
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

# Mock heavy dependencies that may not be available in all environments
# (droidrun → mobilerun chain). These mocks allow the test to run without
# the full Android automation stack installed.
_MOCK_MODULES = [
    "mobilerun", "mobilerun.async_mobilerun",
    "droidrun", "droidrun.agent", "droidrun.agent.droid",
    "droidrun.agent.droid.events", "droidrun.agent.codeact",
    "droidrun.agent.codeact.codeact_agent", "droidrun.agent.utils",
    "droidrun.agent.utils.chat_utils", "droidrun.agent.utils.tools",
    "droidrun.agent.oneflows", "droidrun.agent.oneflows.app_starter_workflow",
    "droidrun.tools", "droidrun.tools.tools",
    "droidrun.tools.ios", "droidrun.tools.driver",
    "droidrun.tools.driver.ios", "droidrun.tools.driver.cloud",
]
for _mod in _MOCK_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from wecom_automation.services.media_actions.actions.auto_contact_share import (
    AutoContactShareAction,
)
from wecom_automation.services.media_actions.device_resolver import (
    resolve_device_settings_from_profiles_only,
)
from wecom_automation.services.media_actions.factory import build_media_event_bus
from wecom_automation.services.media_actions.interfaces import (
    ActionStatus,
    MediaEvent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEVICE_A = "device_a_serial_001"
DEVICE_B = "device_b_serial_002"
DEVICE_C = "device_c_serial_003"  # Has no profiles — should get code defaults


def _create_db_with_profiles(tmp_path, profiles: list[dict] | None = None) -> str:
    """Create an SQLite DB with device_action_profiles table + _master rows.

    Each profile dict: {device_serial, action_type, enabled, config_json}
    """
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS device_action_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_serial TEXT NOT NULL,
            action_type TEXT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT 1,
            config_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(device_serial, action_type)
        )
        """
    )
    for p in (profiles or []):
        config_json = p.get("config_json", "{}")
        if isinstance(config_json, dict):
            config_json = json.dumps(config_json)
        conn.execute(
            """
            INSERT INTO device_action_profiles (device_serial, action_type, enabled, config_json)
            VALUES (?, ?, ?, ?)
            """,
            (p["device_serial"], p["action_type"], int(p.get("enabled", True)), config_json),
        )
    conn.commit()
    conn.close()
    return db_path


def _seed_two_devices(db_path: str) -> None:
    """Seed two devices with different contact share configs."""
    conn = sqlite3.connect(db_path)

    # Device A: contact share enabled, contact_name = "Alice"
    conn.execute(
        "INSERT INTO device_action_profiles (device_serial, action_type, enabled, config_json) VALUES (?, ?, ?, ?)",
        (DEVICE_A, "_master", 1, "{}"),
    )
    conn.execute(
        "INSERT INTO device_action_profiles (device_serial, action_type, enabled, config_json) VALUES (?, ?, ?, ?)",
        (DEVICE_A, "auto_contact_share", 1, json.dumps({
            "contact_name": "Alice",
            "skip_if_already_shared": True,
            "cooldown_seconds": 0,
            "send_message_before_share": True,
            "pre_share_message_text": "Hi from Device A",
        })),
    )
    conn.execute(
        "INSERT INTO device_action_profiles (device_serial, action_type, enabled, config_json) VALUES (?, ?, ?, ?)",
        (DEVICE_A, "auto_blacklist", 0, "{}"),
    )
    conn.execute(
        "INSERT INTO device_action_profiles (device_serial, action_type, enabled, config_json) VALUES (?, ?, ?, ?)",
        (DEVICE_A, "review_gate", 0, "{}"),
    )
    conn.execute(
        "INSERT INTO device_action_profiles (device_serial, action_type, enabled, config_json) VALUES (?, ?, ?, ?)",
        (DEVICE_A, "auto_group_invite", 0, "{}"),
    )

    # Device B: contact share enabled, contact_name = "Bob", different cooldown
    conn.execute(
        "INSERT INTO device_action_profiles (device_serial, action_type, enabled, config_json) VALUES (?, ?, ?, ?)",
        (DEVICE_B, "_master", 1, "{}"),
    )
    conn.execute(
        "INSERT INTO device_action_profiles (device_serial, action_type, enabled, config_json) VALUES (?, ?, ?, ?)",
        (DEVICE_B, "auto_contact_share", 1, json.dumps({
            "contact_name": "Bob",
            "skip_if_already_shared": False,
            "cooldown_seconds": 60,
            "send_message_before_share": False,
            "pre_share_message_text": "",
        })),
    )
    conn.execute(
        "INSERT INTO device_action_profiles (device_serial, action_type, enabled, config_json) VALUES (?, ?, ?, ?)",
        (DEVICE_B, "auto_blacklist", 0, "{}"),
    )
    conn.execute(
        "INSERT INTO device_action_profiles (device_serial, action_type, enabled, config_json) VALUES (?, ?, ?, ?)",
        (DEVICE_B, "review_gate", 0, "{}"),
    )
    conn.execute(
        "INSERT INTO device_action_profiles (device_serial, action_type, enabled, config_json) VALUES (?, ?, ?, ?)",
        (DEVICE_B, "auto_group_invite", 0, "{}"),
    )

    conn.commit()
    conn.close()


def _make_event(device_serial: str, message_type: str = "image") -> MediaEvent:
    return MediaEvent(
        event_type="customer_media_detected",
        message_type=message_type,
        customer_id=1,
        customer_name="测试客户",
        channel="@WeChat",
        device_serial=device_serial,
        kefu_name="客服A",
        message_id=100,
        timestamp=datetime(2026, 5, 17, 12, 0, 0),
    )


# ===================================================================
# Part 1: device_resolver isolation
# ===================================================================


class TestDeviceResolverProfilesOnly:
    """Tests for resolve_device_settings_from_profiles_only."""

    def test_device_a_gets_own_contact_share_config(self, tmp_path):
        db_path = _create_db_with_profiles(tmp_path)
        _seed_two_devices(db_path)

        settings = resolve_device_settings_from_profiles_only(DEVICE_A, db_path)

        assert settings["enabled"] is True
        cs = settings["auto_contact_share"]
        assert cs["enabled"] is True
        assert cs["contact_name"] == "Alice"
        assert cs["skip_if_already_shared"] is True
        assert cs["cooldown_seconds"] == 0
        assert cs["send_message_before_share"] is True
        assert cs["pre_share_message_text"] == "Hi from Device A"

    def test_device_b_gets_own_contact_share_config(self, tmp_path):
        db_path = _create_db_with_profiles(tmp_path)
        _seed_two_devices(db_path)

        settings = resolve_device_settings_from_profiles_only(DEVICE_B, db_path)

        assert settings["enabled"] is True
        cs = settings["auto_contact_share"]
        assert cs["enabled"] is True
        assert cs["contact_name"] == "Bob"
        assert cs["skip_if_already_shared"] is False
        assert cs["cooldown_seconds"] == 60
        assert cs["send_message_before_share"] is False

    def test_devices_have_completely_different_configs(self, tmp_path):
        db_path = _create_db_with_profiles(tmp_path)
        _seed_two_devices(db_path)

        settings_a = resolve_device_settings_from_profiles_only(DEVICE_A, db_path)
        settings_b = resolve_device_settings_from_profiles_only(DEVICE_B, db_path)

        # Contact share configs must be different
        assert settings_a["auto_contact_share"]["contact_name"] == "Alice"
        assert settings_b["auto_contact_share"]["contact_name"] == "Bob"
        assert settings_a["auto_contact_share"]["cooldown_seconds"] == 0
        assert settings_b["auto_contact_share"]["cooldown_seconds"] == 60

        # Verify these are truly independent objects
        assert settings_a is not settings_b
        assert settings_a["auto_contact_share"] is not settings_b["auto_contact_share"]

    def test_device_without_profiles_gets_code_defaults(self, tmp_path):
        db_path = _create_db_with_profiles(tmp_path)
        _seed_two_devices(db_path)

        settings_c = resolve_device_settings_from_profiles_only(DEVICE_C, db_path)

        # Should get code defaults (enabled=False, contact_name="")
        assert settings_c["enabled"] is False
        assert settings_c["auto_contact_share"]["enabled"] is False
        assert settings_c["auto_contact_share"]["contact_name"] == ""

    def test_device_without_profiles_does_not_leak_other_device_config(self, tmp_path):
        db_path = _create_db_with_profiles(tmp_path)
        _seed_two_devices(db_path)

        settings_c = resolve_device_settings_from_profiles_only(DEVICE_C, db_path)

        # Must NOT have Alice or Bob's contact names
        assert settings_c["auto_contact_share"]["contact_name"] != "Alice"
        assert settings_c["auto_contact_share"]["contact_name"] != "Bob"

    def test_empty_db_returns_defaults(self, tmp_path):
        db_path = _create_db_with_profiles(tmp_path)

        settings = resolve_device_settings_from_profiles_only(DEVICE_A, db_path)

        assert settings["enabled"] is False
        assert settings["auto_contact_share"]["enabled"] is False
        assert settings["auto_contact_share"]["contact_name"] == ""

    def test_master_switch_off_disables_all(self, tmp_path):
        db_path = _create_db_with_profiles(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO device_action_profiles (device_serial, action_type, enabled, config_json) VALUES (?, ?, ?, ?)",
            (DEVICE_A, "_master", 0, "{}"),
        )
        conn.execute(
            "INSERT INTO device_action_profiles (device_serial, action_type, enabled, config_json) VALUES (?, ?, ?, ?)",
            (DEVICE_A, "auto_contact_share", 1, json.dumps({"contact_name": "Alice"})),
        )
        conn.commit()
        conn.close()

        settings = resolve_device_settings_from_profiles_only(DEVICE_A, db_path)
        assert settings["enabled"] is False
        # Section-level enabled is still True, but master is off
        assert settings["auto_contact_share"]["enabled"] is True
        assert settings["auto_contact_share"]["contact_name"] == "Alice"


# ===================================================================
# Part 2: factory builds independent bus per device
# ===================================================================


class TestBuildMediaEventBusPerDevice:
    """Tests that build_media_event_bus resolves settings per device_serial."""

    def test_factory_resolves_device_a_settings(self, tmp_path):
        db_path = _create_db_with_profiles(tmp_path)
        _seed_two_devices(db_path)

        bus, settings = build_media_event_bus(db_path, device_serial=DEVICE_A)

        assert bus is not None
        assert settings["enabled"] is True
        assert settings["auto_contact_share"]["contact_name"] == "Alice"

    def test_factory_resolves_device_b_settings(self, tmp_path):
        db_path = _create_db_with_profiles(tmp_path)
        _seed_two_devices(db_path)

        bus, settings = build_media_event_bus(db_path, device_serial=DEVICE_B)

        assert bus is not None
        assert settings["enabled"] is True
        assert settings["auto_contact_share"]["contact_name"] == "Bob"

    def test_factory_returns_none_for_unconfigured_device(self, tmp_path):
        db_path = _create_db_with_profiles(tmp_path)
        _seed_two_devices(db_path)

        bus, settings = build_media_event_bus(db_path, device_serial=DEVICE_C)

        # Device C has no _master row → enabled defaults to False → bus is None
        assert bus is None
        assert settings["enabled"] is False

    def test_two_buses_have_independent_settings(self, tmp_path):
        db_path = _create_db_with_profiles(tmp_path)
        _seed_two_devices(db_path)

        _, settings_a = build_media_event_bus(db_path, device_serial=DEVICE_A)
        _, settings_b = build_media_event_bus(db_path, device_serial=DEVICE_B)

        # Verify complete independence
        assert settings_a["auto_contact_share"]["contact_name"] != settings_b["auto_contact_share"]["contact_name"]
        assert settings_a["auto_contact_share"]["contact_name"] == "Alice"
        assert settings_b["auto_contact_share"]["contact_name"] == "Bob"

        # Cooldown values differ
        assert settings_a["auto_contact_share"]["cooldown_seconds"] == 0
        assert settings_b["auto_contact_share"]["cooldown_seconds"] == 60

        # Modifying one does not affect the other
        settings_a["auto_contact_share"]["contact_name"] = "MODIFIED"
        assert settings_b["auto_contact_share"]["contact_name"] == "Bob"


# ===================================================================
# Part 3: AutoContactShareAction uses per-device settings
# ===================================================================


class TestAutoContactSharePerDevice:
    """Tests that AutoContactShareAction.should_execute respects per-device config."""

    @pytest.mark.asyncio
    async def test_action_executes_for_device_a_with_alice(self):
        service = AsyncMock()
        service.contact_already_shared = AsyncMock(return_value=False)
        action = AutoContactShareAction(contact_share_service=service)

        settings_a = {
            "enabled": True,
            "auto_contact_share": {
                "enabled": True,
                "contact_name": "Alice",
                "skip_if_already_shared": True,
                "cooldown_seconds": 0,
            },
        }
        event = _make_event(DEVICE_A, "image")

        assert await action.should_execute(event, settings_a) is True

    @pytest.mark.asyncio
    async def test_action_executes_for_device_b_with_bob(self):
        service = AsyncMock()
        service.contact_already_shared = AsyncMock(return_value=False)
        action = AutoContactShareAction(contact_share_service=service)

        settings_b = {
            "enabled": True,
            "auto_contact_share": {
                "enabled": True,
                "contact_name": "Bob",
                "skip_if_already_shared": False,
                "cooldown_seconds": 60,
            },
        }
        event = _make_event(DEVICE_B, "video")

        assert await action.should_execute(event, settings_b) is True

    @pytest.mark.asyncio
    async def test_action_skips_for_device_with_no_contact_name(self):
        service = AsyncMock()
        action = AutoContactShareAction(contact_share_service=service)

        # Device C: default settings — no contact name configured
        settings_c = {
            "enabled": True,
            "auto_contact_share": {
                "enabled": True,
                "contact_name": "",
                "skip_if_already_shared": True,
                "cooldown_seconds": 0,
            },
        }
        event = _make_event(DEVICE_C, "image")

        assert await action.should_execute(event, settings_c) is False

    @pytest.mark.asyncio
    async def test_action_skips_when_master_switch_off(self):
        service = AsyncMock()
        action = AutoContactShareAction(contact_share_service=service)

        settings = {
            "enabled": False,  # Master switch OFF
            "auto_contact_share": {
                "enabled": True,
                "contact_name": "Alice",
            },
        }
        event = _make_event(DEVICE_A, "image")

        assert await action.should_execute(event, settings) is False

    @pytest.mark.asyncio
    async def test_action_skips_when_section_disabled(self):
        service = AsyncMock()
        action = AutoContactShareAction(contact_share_service=service)

        settings = {
            "enabled": True,
            "auto_contact_share": {
                "enabled": False,  # Section disabled
                "contact_name": "Alice",
            },
        }
        event = _make_event(DEVICE_A, "image")

        assert await action.should_execute(event, settings) is False


# ===================================================================
# Part 4: End-to-end dual-device scenario
# ===================================================================


class TestDualDeviceContactShareScenario:
    """
    Simulates the full scenario: two devices connected simultaneously,
    each with independent contact share config.

    Device A: enabled, contact_name=Alice, skip_if_already_shared=True
    Device B: enabled, contact_name=Bob, skip_if_already_shared=False, cooldown=60

    When a media event arrives for each device, the system must:
    1. Resolve settings independently per device
    2. Only trigger contact share for the correct contact on each device
    """

    def test_full_dual_device_resolution(self, tmp_path):
        db_path = _create_db_with_profiles(tmp_path)
        _seed_two_devices(db_path)

        # Resolve settings for both devices
        settings_a = resolve_device_settings_from_profiles_only(DEVICE_A, db_path)
        settings_b = resolve_device_settings_from_profiles_only(DEVICE_B, db_path)

        # Both are enabled
        assert settings_a["enabled"] is True
        assert settings_b["enabled"] is True

        # Each has its own contact name
        assert settings_a["auto_contact_share"]["contact_name"] == "Alice"
        assert settings_b["auto_contact_share"]["contact_name"] == "Bob"

        # Different sharing policies
        assert settings_a["auto_contact_share"]["skip_if_already_shared"] is True
        assert settings_b["auto_contact_share"]["skip_if_already_shared"] is False

    @pytest.mark.asyncio
    async def test_device_a_event_uses_alice_device_b_event_uses_bob(self, tmp_path):
        db_path = _create_db_with_profiles(tmp_path)
        _seed_two_devices(db_path)

        settings_a = resolve_device_settings_from_profiles_only(DEVICE_A, db_path)
        settings_b = resolve_device_settings_from_profiles_only(DEVICE_B, db_path)

        service_a = AsyncMock()
        service_a.contact_already_shared = AsyncMock(return_value=False)
        service_a.share_contact_card = AsyncMock(return_value=True)
        action_a = AutoContactShareAction(contact_share_service=service_a)

        service_b = AsyncMock()
        service_b.contact_already_shared = AsyncMock(return_value=False)
        service_b.share_contact_card = AsyncMock(return_value=True)
        action_b = AutoContactShareAction(contact_share_service=service_b)

        event_a = _make_event(DEVICE_A, "image")
        event_b = _make_event(DEVICE_B, "video")

        # Both should execute
        assert await action_a.should_execute(event_a, settings_a) is True
        assert await action_b.should_execute(event_b, settings_b) is True

        # Execute both
        result_a = await action_a.execute(event_a, settings_a)
        result_b = await action_b.execute(event_b, settings_b)

        assert result_a.status == ActionStatus.SUCCESS
        assert result_b.status == ActionStatus.SUCCESS

        # Verify each service received the correct contact name
        call_a = service_a.share_contact_card.call_args
        call_b = service_b.share_contact_card.call_args

        req_a = call_a[0][0] if call_a[0] else call_a.kwargs.get("request")
        req_b = call_b[0][0] if call_b[0] else call_b.kwargs.get("request")

        # The contact share request should carry the correct contact name
        # from each device's independent settings
        assert req_a.contact_name == "Alice"
        assert req_b.contact_name == "Bob"
        assert req_a.contact_name != req_b.contact_name

    def test_adding_device_b_profile_does_not_affect_device_a(self, tmp_path):
        db_path = _create_db_with_profiles(tmp_path)
        _seed_two_devices(db_path)

        # Read A's settings
        settings_a_before = resolve_device_settings_from_profiles_only(DEVICE_A, db_path)

        # Modify B's profile in DB
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE device_action_profiles SET config_json = ? WHERE device_serial = ? AND action_type = ?",
            (json.dumps({"contact_name": "Charlie", "cooldown_seconds": 999}), DEVICE_B, "auto_contact_share"),
        )
        conn.commit()
        conn.close()

        # Read A's settings again — must be unchanged
        settings_a_after = resolve_device_settings_from_profiles_only(DEVICE_A, db_path)

        assert settings_a_after["auto_contact_share"]["contact_name"] == "Alice"
        assert settings_a_after["auto_contact_share"]["cooldown_seconds"] == 0
        assert settings_a_before["auto_contact_share"] == settings_a_after["auto_contact_share"]

        # Verify B got the update
        settings_b = resolve_device_settings_from_profiles_only(DEVICE_B, db_path)
        assert settings_b["auto_contact_share"]["contact_name"] == "Charlie"
        assert settings_b["auto_contact_share"]["cooldown_seconds"] == 999

    def test_deleting_device_a_profile_does_not_affect_device_b(self, tmp_path):
        db_path = _create_db_with_profiles(tmp_path)
        _seed_two_devices(db_path)

        # Delete all of device A's profiles
        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM device_action_profiles WHERE device_serial = ?", (DEVICE_A,))
        conn.commit()
        conn.close()

        # A should fall back to defaults
        settings_a = resolve_device_settings_from_profiles_only(DEVICE_A, db_path)
        assert settings_a["enabled"] is False
        assert settings_a["auto_contact_share"]["contact_name"] == ""

        # B should be unaffected
        settings_b = resolve_device_settings_from_profiles_only(DEVICE_B, db_path)
        assert settings_b["enabled"] is True
        assert settings_b["auto_contact_share"]["contact_name"] == "Bob"
        assert settings_b["auto_contact_share"]["cooldown_seconds"] == 60
