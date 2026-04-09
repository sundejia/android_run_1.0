"""
Integration tests for FollowUp Multi-Device API endpoints

Tests the REST API endpoints for managing multi-device follow-up processes.
"""

import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, Mock, patch

from main import app
from services.realtime_reply_manager import (
    RealtimeReplyStatus,
    RealtimeReplyState,
    get_realtime_reply_manager,
)


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def mock_manager():
    """Create a mock RealtimeReplyManager."""
    manager = Mock()

    # Mock methods
    manager.start_realtime_reply = AsyncMock(return_value=True)
    manager.stop_realtime_reply = AsyncMock(return_value=True)
    manager.pause_realtime_reply = AsyncMock(return_value=True)
    manager.resume_realtime_reply = AsyncMock(return_value=True)
    manager.get_state = Mock(return_value=None)
    manager.get_all_states = Mock(return_value={})
    manager.stop_all = AsyncMock()

    return manager


class TestDeviceStartEndpoint:
    """Test POST /api/followup/device/{serial}/start"""

    def test_start_device_success(self, client, mock_manager):
        """Test starting follow-up for a device."""
        # Set up mock state
        mock_manager.get_state.return_value = RealtimeReplyState(
            status=RealtimeReplyStatus.RUNNING, message="Follow-up running"
        )

        with patch("routers.devices.ensure_device_kefu_persisted", new=AsyncMock()) as ensure_kefu_mock, patch(
            "services.realtime_reply_manager.get_realtime_reply_manager", return_value=mock_manager
        ):
            response = client.post(
                "/api/realtime/device/test_serial/start",
                params={"scan_interval": 60, "use_ai_reply": True, "send_via_sidecar": True},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["serial"] == "test_serial"
            assert data["status"] == "running"

            # Verify manager method was called
            ensure_kefu_mock.assert_awaited_once_with("test_serial", launch_wecom=False, allow_placeholder=True)
            mock_manager.start_realtime_reply.assert_called_once_with(
                serial="test_serial", scan_interval=60, use_ai_reply=True, send_via_sidecar=True
            )

    def test_start_device_already_running(self, client, mock_manager):
        """Test starting when already running."""
        # Set up mock to return False (already running)
        mock_manager.start_realtime_reply.return_value = False
        mock_manager.get_state.return_value = RealtimeReplyState(status=RealtimeReplyStatus.RUNNING)

        with patch("routers.devices.ensure_device_kefu_persisted", new=AsyncMock()), patch(
            "services.realtime_reply_manager.get_realtime_reply_manager", return_value=mock_manager
        ):
            response = client.post("/api/realtime/device/test_serial/start")

            assert response.status_code == 409
            assert "already running" in response.json()["detail"].lower()

    def test_start_device_default_params(self, client, mock_manager):
        """Test starting with default parameters."""
        mock_manager.get_state.return_value = RealtimeReplyState(status=RealtimeReplyStatus.RUNNING)

        with patch("routers.devices.ensure_device_kefu_persisted", new=AsyncMock()), patch(
            "services.realtime_reply_manager.get_realtime_reply_manager", return_value=mock_manager
        ):
            response = client.post("/api/realtime/device/test_serial/start")

            assert response.status_code == 200

            # Verify defaults were used
            call_args = mock_manager.start_realtime_reply.call_args
            assert call_args[1]["scan_interval"] == 60
            assert call_args[1]["use_ai_reply"] is True
            assert call_args[1]["send_via_sidecar"] is True


class TestRealtimeSettingsEndpoints:
    def test_get_realtime_settings_returns_scan_interval_alias(self, client):
        mock_service = Mock()
        mock_service.get.return_value = 120

        with patch("services.settings.get_settings_service", return_value=mock_service):
            response = client.get("/api/realtime/settings")

        assert response.status_code == 200
        data = response.json()
        assert data["scanInterval"] == 120
        assert data["useAIReply"] is True
        assert data["sendViaSidecar"] is True

    def test_post_realtime_settings_accepts_scan_interval_alias(self, client):
        mock_service = Mock()

        with patch("services.settings.get_settings_service", return_value=mock_service):
            response = client.post("/api/realtime/settings", json={"scanInterval": 180})

        assert response.status_code == 200
        mock_service.set_category.assert_called_once()
        args, _kwargs = mock_service.set_category.call_args
        updates = args[1]
        assert updates["scan_interval"] == 180


class TestDeviceStopEndpoint:
    """Test POST /api/followup/device/{serial}/stop"""

    def test_stop_device_success(self, client, mock_manager):
        """Test stopping follow-up for a device."""
        with patch("services.realtime_reply_manager.get_realtime_reply_manager", return_value=mock_manager):
            response = client.post("/api/realtime/device/test_serial/stop")

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["serial"] == "test_serial"

            mock_manager.stop_realtime_reply.assert_called_once_with("test_serial")

    def test_stop_device_not_running(self, client, mock_manager):
        """Test stopping when not running."""
        mock_manager.stop_realtime_reply.return_value = False

        with patch("services.realtime_reply_manager.get_realtime_reply_manager", return_value=mock_manager):
            response = client.post("/api/realtime/device/test_serial/stop")

            assert response.status_code == 404


class TestDevicePauseEndpoint:
    """Test POST /api/followup/device/{serial}/pause"""

    def test_pause_device_success(self, client, mock_manager):
        """Test pausing follow-up for a device."""
        with patch("services.realtime_reply_manager.get_realtime_reply_manager", return_value=mock_manager):
            response = client.post("/api/realtime/device/test_serial/pause")

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

            mock_manager.pause_realtime_reply.assert_called_once_with("test_serial")

    def test_pause_device_no_process(self, client, mock_manager):
        """Test pausing when no process exists."""
        mock_manager.pause_realtime_reply.return_value = False
        mock_manager.get_state.return_value = None

        with patch("services.realtime_reply_manager.get_realtime_reply_manager", return_value=mock_manager):
            response = client.post("/api/realtime/device/test_serial/pause")

            assert response.status_code == 404

    def test_pause_device_invalid_state(self, client, mock_manager):
        """Test pausing when not in running state."""
        mock_manager.pause_realtime_reply.return_value = False
        mock_manager.get_state.return_value = RealtimeReplyState(status=RealtimeReplyStatus.IDLE)

        with patch("services.realtime_reply_manager.get_realtime_reply_manager", return_value=mock_manager):
            response = client.post("/api/realtime/device/test_serial/pause")

            assert response.status_code == 400


class TestDeviceResumeEndpoint:
    """Test POST /api/followup/device/{serial}/resume"""

    def test_resume_device_success(self, client, mock_manager):
        """Test resuming follow-up for a device."""
        with patch("services.realtime_reply_manager.get_realtime_reply_manager", return_value=mock_manager):
            response = client.post("/api/realtime/device/test_serial/resume")

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

            mock_manager.resume_realtime_reply.assert_called_once_with("test_serial")

    def test_resume_device_not_paused(self, client, mock_manager):
        """Test resuming when not paused."""
        mock_manager.resume_realtime_reply.return_value = False
        mock_manager.get_state.return_value = RealtimeReplyState(status=RealtimeReplyStatus.RUNNING)

        with patch("services.realtime_reply_manager.get_realtime_reply_manager", return_value=mock_manager):
            response = client.post("/api/realtime/device/test_serial/resume")

            assert response.status_code == 400


class TestDeviceStatusEndpoint:
    """Test GET /api/followup/device/{serial}/status"""

    def test_get_device_status_running(self, client, mock_manager):
        """Test getting status for running device."""
        from datetime import datetime

        mock_manager.get_state.return_value = RealtimeReplyState(
            status=RealtimeReplyStatus.RUNNING,
            message="Follow-up running",
            responses_detected=10,
            replies_sent=5,
            started_at=datetime.now(),
            last_scan_at=datetime.now(),
            errors=[],
        )

        with patch("services.realtime_reply_manager.get_realtime_reply_manager", return_value=mock_manager):
            response = client.get("/api/realtime/device/test_serial/status")

            assert response.status_code == 200
            data = response.json()
            assert data["serial"] == "test_serial"
            assert data["status"] == "running"
            assert data["responses_detected"] == 10
            assert data["replies_sent"] == 5
            assert data["started_at"] is not None
            assert data["last_scan_at"] is not None

    def test_get_device_status_idle(self, client, mock_manager):
        """Test getting status for idle device."""
        mock_manager.get_state.return_value = None

        with patch("services.realtime_reply_manager.get_realtime_reply_manager", return_value=mock_manager):
            response = client.get("/api/realtime/device/test_serial/status")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "idle"
            assert data["responses_detected"] == 0
            assert data["replies_sent"] == 0


class TestAllDevicesStatusEndpoint:
    """Test GET /api/followup/devices/status"""

    def test_get_all_devices_status_empty(self, client, mock_manager):
        """Test getting all devices status when empty."""
        mock_manager.get_all_states.return_value = {}
        mock_discovery = Mock()
        mock_discovery.list_devices = AsyncMock(return_value=[])

        with patch("services.realtime_reply_manager.get_realtime_reply_manager", return_value=mock_manager), patch(
            "routers.devices.get_discovery_service", return_value=mock_discovery
        ):
            response = client.get("/api/realtime/devices/status")

            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 0
            assert data["running"] == 0
            assert data["devices"] == {}

    def test_get_all_devices_status_multiple(self, client, mock_manager):
        """Test getting all devices status with multiple devices."""
        from datetime import datetime

        # Mock device discovery service to return devices
        mock_discovery = Mock()
        mock_device1 = Mock()
        mock_device1.serial = "device1"
        mock_device2 = Mock()
        mock_device2.serial = "device2"
        mock_discovery.list_devices = AsyncMock(return_value=[mock_device1, mock_device2])

        mock_manager.get_all_states.return_value = {
            "device1": RealtimeReplyState(
                status=RealtimeReplyStatus.RUNNING, message="Running", responses_detected=5, replies_sent=3
            ),
            "device2": RealtimeReplyState(
                status=RealtimeReplyStatus.PAUSED, message="Paused", responses_detected=2, replies_sent=1
            ),
        }

        with patch("services.realtime_reply_manager.get_realtime_reply_manager", return_value=mock_manager), \
             patch("routers.devices.get_discovery_service", return_value=mock_discovery):
            response = client.get("/api/realtime/devices/status")

            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 2
            assert data["running"] == 1  # Only device1 is running
            assert "device1" in data["devices"]
            assert "device2" in data["devices"]
            assert data["devices"]["device1"]["status"] == "running"
            assert data["devices"]["device2"]["status"] == "paused"


class TestStopAllEndpoint:
    """Test POST /api/followup/devices/stop-all"""

    def test_stop_all_devices(self, client, mock_manager):
        """Test stopping all devices."""
        mock_manager.get_all_states.return_value = {
            "device1": RealtimeReplyState(status=RealtimeReplyStatus.RUNNING),
            "device2": RealtimeReplyState(status=RealtimeReplyStatus.PAUSED),
        }

        with patch("services.realtime_reply_manager.get_realtime_reply_manager", return_value=mock_manager):
            response = client.post("/api/realtime/devices/stop-all")

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["count"] == 2
            assert "device1" in data["stopped_devices"]
            assert "device2" in data["stopped_devices"]

            mock_manager.stop_all.assert_called_once()

    def test_stop_all_devices_empty(self, client, mock_manager):
        """Test stopping all devices when none are running."""
        mock_manager.get_all_states.return_value = {}

        with patch("services.realtime_reply_manager.get_realtime_reply_manager", return_value=mock_manager):
            response = client.post("/api/realtime/devices/stop-all")

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 0
            assert data["stopped_devices"] == []


class TestPydanticModels:
    """Test Pydantic model validation."""

    def test_device_followup_status_model(self):
        """Test DeviceStatus model."""
        from routers.realtime_reply import DeviceStatus

        status = DeviceStatus(
            serial="test",
            status="running",
            message="Running",
            responses_detected=10,
            replies_sent=5,
            errors=["Error 1", "Error 2"],
        )

        assert status.serial == "test"
        assert status.status == "running"
        assert len(status.errors) == 2

    def test_all_devices_status_model(self):
        """Test AllDevicesStatus model."""
        from routers.realtime_reply import AllDevicesStatus, DeviceStatus

        all_status = AllDevicesStatus(
            devices={
                "device1": DeviceStatus(
                    serial="device1",
                    status="running",
                    message="Running",
                    responses_detected=5,
                    replies_sent=3,
                    errors=[],
                )
            },
            total=1,
            running=1,
        )

        assert all_status.total == 1
        assert all_status.running == 1
        assert len(all_status.devices) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
