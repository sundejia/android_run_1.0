"""
Tests for the Media Auto-Actions API endpoints.

Tests cover:
- GET /api/media-actions/settings
- PUT /api/media-actions/settings
- POST /api/media-actions/test-trigger
- GET /api/media-actions/logs
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
src_dir = backend_dir.parent.parent / "src"
sys.path.insert(0, str(src_dir))

from main import app

client = TestClient(app)


def _mock_ws_manager():
    """Create a mock GlobalConnectionManager."""
    mgr = MagicMock()
    mgr.broadcast = AsyncMock(return_value=0)
    return mgr


class TestGetSettings:
    def test_get_settings_returns_defaults(self):
        with patch("routers.media_actions.get_settings_service") as mock_svc:
            mock_svc.return_value.get_category.return_value = {}
            response = client.get("/api/media-actions/settings")

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False
        assert "auto_blacklist" in data
        assert "auto_group_invite" in data
        assert "auto_contact_share" in data
        assert "review_gate" in data
        assert data["auto_blacklist"]["enabled"] is False
        # Regression: 2026-05-07 fix locks the default to False so deployments
        # without the image-rating pipeline still get auto-blacklist working.
        assert data["auto_blacklist"]["require_review_pass"] is False
        assert data["auto_group_invite"]["enabled"] is False
        assert data["auto_group_invite"]["send_test_message_after_create"] is True
        assert data["auto_group_invite"]["test_message_text"] == "测试"
        assert data["auto_group_invite"]["video_invite_policy"] == "extract_frame"
        assert data["review_gate"]["enabled"] is False
        assert data["review_gate"]["video_review_policy"] == "extract_frame"

    def test_get_settings_returns_stored_values(self):
        stored = {
            "enabled": True,
            "auto_blacklist": {
                "enabled": True,
                "reason": "Custom reason",
                "skip_if_already_blacklisted": False,
            },
            "auto_group_invite": {
                "enabled": True,
                "group_members": ["经理A"],
                "group_name_template": "{customer_name}-VIP",
                "skip_if_group_exists": True,
                "send_test_message_after_create": False,
                "test_message_text": "欢迎 {customer_name}",
                "duplicate_name_policy": "first",
                "post_confirm_wait_seconds": 2.5,
            },
            "review_gate": {
                "enabled": True,
                "video_review_policy": "extract_frame",
            },
        }
        with patch("routers.media_actions.get_settings_service") as mock_svc:
            mock_svc.return_value.get_category.return_value = stored
            response = client.get("/api/media-actions/settings")

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True
        assert data["auto_blacklist"]["reason"] == "Custom reason"
        assert data["auto_group_invite"]["group_members"] == ["经理A"]
        assert data["auto_group_invite"]["send_test_message_after_create"] is False
        assert data["auto_group_invite"]["test_message_text"] == "欢迎 {customer_name}"
        assert data["auto_group_invite"]["post_confirm_wait_seconds"] == 2.5
        assert data["review_gate"]["enabled"] is True
        assert data["review_gate"]["video_review_policy"] == "extract_frame"
        # 2026-05-12 dedup regression: response payload must NOT include the
        # legacy server URL/timeout fields. They live under general.* now.
        assert "rating_server_url" not in data["review_gate"]
        assert "upload_timeout_seconds" not in data["review_gate"]
        assert "upload_max_attempts" not in data["review_gate"]

    def test_get_settings_strips_legacy_review_gate_fields(self):
        """If a legacy DB still has rating_server_url stored, the API must
        not echo it back to clients (the field is removed from the Pydantic
        response model)."""
        stored = {
            "enabled": True,
            "review_gate": {
                "enabled": True,
                "rating_server_url": "http://legacy.local:9999",
                "upload_timeout_seconds": 45,
                "upload_max_attempts": 2,
                "video_review_policy": "skip",
            },
        }
        with patch("routers.media_actions.get_settings_service") as mock_svc:
            mock_svc.return_value.get_category.return_value = stored
            response = client.get("/api/media-actions/settings")

        assert response.status_code == 200
        data = response.json()
        assert data["review_gate"]["enabled"] is True
        assert data["review_gate"]["video_review_policy"] == "skip"
        assert "rating_server_url" not in data["review_gate"]
        assert "upload_timeout_seconds" not in data["review_gate"]
        assert "upload_max_attempts" not in data["review_gate"]


class TestUpdateSettings:
    def test_update_settings_partial(self):
        with patch("routers.media_actions.get_settings_service") as mock_svc:
            mock_svc.return_value.get_category.return_value = {}
            mock_svc.return_value.set_category.return_value = {}

            with patch("routers.global_websocket.get_global_ws_manager", return_value=_mock_ws_manager()):
                response = client.put(
                    "/api/media-actions/settings",
                    json={"enabled": True},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True

    def test_update_blacklist_settings(self):
        with patch("routers.media_actions.get_settings_service") as mock_svc:
            mock_svc.return_value.get_category.return_value = {}
            mock_svc.return_value.set_category.return_value = {}

            with patch("routers.global_websocket.get_global_ws_manager", return_value=_mock_ws_manager()):
                response = client.put(
                    "/api/media-actions/settings",
                    json={
                        "auto_blacklist": {
                            "enabled": True,
                            "reason": "Sent photo",
                            "skip_if_already_blacklisted": True,
                        }
                    },
                )

        assert response.status_code == 200
        data = response.json()
        assert data["auto_blacklist"]["enabled"] is True
        assert data["auto_blacklist"]["reason"] == "Sent photo"

    def test_update_group_invite_settings(self):
        with patch("routers.media_actions.get_settings_service") as mock_svc:
            mock_svc.return_value.get_category.return_value = {}
            mock_svc.return_value.set_category.return_value = {}

            with patch("routers.global_websocket.get_global_ws_manager", return_value=_mock_ws_manager()):
                response = client.put(
                    "/api/media-actions/settings",
                    json={
                        "auto_group_invite": {
                            "enabled": True,
                            "group_members": ["经理A", "主管B"],
                            "group_name_template": "{customer_name}-服务群",
                            "skip_if_group_exists": True,
                            "send_test_message_after_create": True,
                            "test_message_text": "您好 {customer_name}",
                            "duplicate_name_policy": "first",
                            "post_confirm_wait_seconds": 3.0,
                        }
                    },
                )

        assert response.status_code == 200
        data = response.json()
        assert data["auto_group_invite"]["group_members"] == ["经理A", "主管B"]
        assert data["auto_group_invite"]["test_message_text"] == "您好 {customer_name}"
        assert data["auto_group_invite"]["send_test_message_after_create"] is True
        assert data["auto_group_invite"]["post_confirm_wait_seconds"] == 3.0

    def test_update_review_gate_settings(self):
        with patch("routers.media_actions.get_settings_service") as mock_svc:
            mock_svc.return_value.get_category.return_value = {}
            mock_svc.return_value.set_category.return_value = {}

            with patch("routers.global_websocket.get_global_ws_manager", return_value=_mock_ws_manager()):
                response = client.put(
                    "/api/media-actions/settings",
                    json={
                        "review_gate": {
                            "enabled": True,
                            "video_review_policy": "extract_frame",
                        }
                    },
                )

        assert response.status_code == 200
        data = response.json()
        assert data["review_gate"]["enabled"] is True
        assert data["review_gate"]["video_review_policy"] == "extract_frame"

    def test_update_review_gate_ignores_legacy_url_in_request(self):
        """2026-05-12 dedup regression: if a stale frontend (or external
        caller) sends rating_server_url in the PUT body, it must be
        silently discarded so it never leaks into the persisted JSON."""
        captured: dict = {}

        def _fake_set_category(category, settings, *a, **kw):
            captured.setdefault("calls", []).append((category, settings))
            return settings

        with patch("routers.media_actions.get_settings_service") as mock_svc:
            mock_svc.return_value.get_category.return_value = {}
            mock_svc.return_value.set_category.side_effect = _fake_set_category

            with patch("routers.global_websocket.get_global_ws_manager", return_value=_mock_ws_manager()):
                response = client.put(
                    "/api/media-actions/settings",
                    json={
                        "review_gate": {
                            "enabled": True,
                            "video_review_policy": "extract_frame",
                            # Legacy fields a stale frontend might still send.
                            "rating_server_url": "http://legacy.local:9999",
                            "upload_timeout_seconds": 99,
                            "upload_max_attempts": 7,
                        }
                    },
                )

        assert response.status_code == 200
        # Pydantic's default extra="ignore" strips the legacy fields; the
        # router writes only the recognised attributes.
        assert captured["calls"], "set_category was not called"
        _, persisted = captured["calls"][0]
        assert "rating_server_url" not in persisted["review_gate"]
        assert "upload_timeout_seconds" not in persisted["review_gate"]
        assert "upload_max_attempts" not in persisted["review_gate"]


class TestGetLogs:
    def test_get_logs_empty(self):
        response = client.get("/api/media-actions/logs")
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
        assert isinstance(data["logs"], list)


class TestTestTrigger:
    def test_trigger_with_disabled_settings(self):
        with patch("routers.media_actions.get_settings_service") as mock_svc:
            mock_svc.return_value.get_category.return_value = {"enabled": False}

            with patch("routers.global_websocket.get_global_ws_manager", return_value=_mock_ws_manager()):
                response = client.post(
                    "/api/media-actions/test-trigger",
                    params={
                        "device_serial": "test_device",
                        "customer_name": "测试客户",
                        "message_type": "image",
                    },
                )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert isinstance(data["results"], list)
        assert {r["action_name"] for r in data["results"]} == {
            "auto_blacklist",
            "auto_group_invite",
            "auto_contact_share",
        }
        for r in data["results"]:
            assert r["status"] == "skipped"

    def test_trigger_validates_message_type(self):
        with patch("routers.media_actions.get_settings_service") as mock_svc:
            mock_svc.return_value.get_category.return_value = {
                "enabled": True,
                "auto_blacklist": {"enabled": True, "reason": "test", "skip_if_already_blacklisted": True},
                "auto_group_invite": {"enabled": False},
            }

            with patch("routers.global_websocket.get_global_ws_manager", return_value=_mock_ws_manager()):
                with patch("wecom_automation.services.blacklist_service.BlacklistWriter") as mock_writer_cls:
                    mock_writer_instance = MagicMock()
                    mock_writer_instance.is_blacklisted_by_name.return_value = False
                    mock_writer_instance.add_to_blacklist.return_value = True
                    mock_writer_cls.return_value = mock_writer_instance

                    response = client.post(
                        "/api/media-actions/test-trigger",
                        params={
                            "device_serial": "dev1",
                            "customer_name": "客户A",
                            "message_type": "image",
                        },
                    )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


class TestContactSharePreShareMessageSettings:
    """Tests for the new pre-share message settings fields in auto_contact_share."""

    def test_get_settings_includes_pre_share_message_fields(self):
        """Default settings should include send_message_before_share and pre_share_message_text."""
        with patch("routers.media_actions.get_settings_service") as mock_svc:
            mock_svc.return_value.get_category.return_value = {}
            response = client.get("/api/media-actions/settings")

        assert response.status_code == 200
        data = response.json()
        cs = data["auto_contact_share"]
        assert "send_message_before_share" in cs
        assert cs["send_message_before_share"] is False
        assert "pre_share_message_text" in cs
        assert cs["pre_share_message_text"] == ""

    def test_update_contact_share_pre_share_message_settings(self):
        """PUT should accept and persist the new pre-share message fields."""
        with patch("routers.media_actions.get_settings_service") as mock_svc:
            mock_svc.return_value.get_category.return_value = {}
            mock_svc.return_value.set_category.return_value = {}

            with patch("routers.global_websocket.get_global_ws_manager", return_value=_mock_ws_manager()):
                response = client.put(
                    "/api/media-actions/settings",
                    json={
                        "auto_contact_share": {
                            "enabled": True,
                            "contact_name": "主管王",
                            "skip_if_already_shared": True,
                            "cooldown_seconds": 0,
                            "kefu_overrides": {},
                            "send_message_before_share": True,
                            "pre_share_message_text": "你好{customer_name}，推荐主管给你",
                        }
                    },
                )

        assert response.status_code == 200
        data = response.json()
        cs = data["auto_contact_share"]
        assert cs["send_message_before_share"] is True
        assert cs["pre_share_message_text"] == "你好{customer_name}，推荐主管给你"

    def test_get_settings_returns_stored_pre_share_values(self):
        """When DB has stored pre-share values, they should be returned."""
        stored = {
            "enabled": True,
            "auto_contact_share": {
                "enabled": True,
                "contact_name": "主管",
                "skip_if_already_shared": True,
                "cooldown_seconds": 0,
                "kefu_overrides": {},
                "send_message_before_share": True,
                "pre_share_message_text": "这是主管名片",
            },
        }
        with patch("routers.media_actions.get_settings_service") as mock_svc:
            mock_svc.return_value.get_category.return_value = stored
            response = client.get("/api/media-actions/settings")

        assert response.status_code == 200
        data = response.json()
        cs = data["auto_contact_share"]
        assert cs["send_message_before_share"] is True
        assert cs["pre_share_message_text"] == "这是主管名片"
