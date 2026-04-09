import sys
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from routers.settings import router as settings_router

app = FastAPI()
app.include_router(settings_router, prefix="/settings")


def test_update_settings_persists_scan_interval():
    client = TestClient(app)
    mock_service = Mock()

    with patch("routers.settings.get_settings_service", return_value=mock_service):
        response = client.post("/settings/update", json={"scan_interval": 120})

    assert response.status_code == 200
    mock_service.update_from_frontend_partial.assert_called_once()
    updates, changed_by = mock_service.update_from_frontend_partial.call_args.args
    assert updates["scanInterval"] == 120
    assert changed_by == "frontend"


def test_update_settings_persists_hostname():
    client = TestClient(app)
    mock_service = Mock()
    mock_service.normalize_hostname_input.return_value = "android-node-01"

    with patch("routers.settings.get_settings_service", return_value=mock_service):
        response = client.post("/settings/update", json={"hostname": "android-node-01"})

    assert response.status_code == 200
    mock_service.update_from_frontend_partial.assert_called_once()
    updates, changed_by = mock_service.update_from_frontend_partial.call_args.args
    assert updates["hostname"] == "android-node-01"
    assert changed_by == "frontend"


def test_update_settings_blank_hostname_uses_identity_default():
    client = TestClient(app)
    mock_service = Mock()
    mock_service.normalize_hostname_input.return_value = "WIN-TEST-01"

    with patch("routers.settings.get_settings_service", return_value=mock_service):
        response = client.post("/settings/update", json={"hostname": "   "})

    assert response.status_code == 200
    mock_service.normalize_hostname_input.assert_called_once_with("   ")
    updates, _ = mock_service.update_from_frontend_partial.call_args.args
    assert updates["hostname"] == "WIN-TEST-01"


def test_update_settings_persists_person_name():
    client = TestClient(app)
    mock_service = Mock()
    mock_service.normalize_person_name_input.return_value = "张三"

    with patch("routers.settings.get_settings_service", return_value=mock_service):
        response = client.post("/settings/update", json={"person_name": "  张三  "})

    assert response.status_code == 200
    mock_service.normalize_person_name_input.assert_called_once_with("  张三  ")
    updates, changed_by = mock_service.update_from_frontend_partial.call_args.args
    assert updates["personName"] == "张三"
    assert changed_by == "frontend"


def test_update_settings_blank_person_name_falls_back_to_hostname():
    client = TestClient(app)
    mock_service = Mock()
    mock_service.normalize_person_name_input.return_value = "WIN-TEST-01"

    with patch("routers.settings.get_settings_service", return_value=mock_service):
        response = client.post("/settings/update", json={"person_name": "   "})

    assert response.status_code == 200
    mock_service.normalize_person_name_input.assert_called_once_with("   ")
    updates, _ = mock_service.update_from_frontend_partial.call_args.args
    assert updates["personName"] == "WIN-TEST-01"


def test_update_settings_persists_image_review_timeout():
    client = TestClient(app)
    mock_service = Mock()

    with patch("routers.settings.get_settings_service", return_value=mock_service):
        response = client.post("/settings/update", json={"image_review_timeout_seconds": 55})

    assert response.status_code == 200
    mock_service.update_from_frontend_partial.assert_called_once()
    updates, changed_by = mock_service.update_from_frontend_partial.call_args.args
    assert updates["imageReviewTimeoutSeconds"] == 55
    assert changed_by == "frontend"


def test_update_settings_persists_low_spec_controls():
    client = TestClient(app)
    mock_service = Mock()

    with patch("routers.settings.get_settings_service", return_value=mock_service):
        response = client.post(
            "/settings/update",
            json={
                "low_spec_mode": True,
                "max_concurrent_sync_devices": 2,
                "sidecar_max_panels": 1,
            },
        )

    assert response.status_code == 200
    updates, _changed_by = mock_service.update_from_frontend_partial.call_args.args
    assert updates["lowSpecMode"] is True
    assert updates["maxConcurrentSyncDevices"] == 2
    assert updates["sidecarMaxPanels"] == 1


def test_get_performance_profile_returns_metrics_snapshot():
    client = TestClient(app)
    mock_service = Mock()
    mock_service.get_performance_profile.return_value = {
        "lowSpecMode": True,
        "effective": {
            "maxConcurrentSyncDevices": 1,
            "sidecarPollInterval": 5,
            "scanInterval": 120,
            "sidecarMaxPanels": 1,
            "mirrorMaxFps": 15,
            "mirrorBitRate": 4,
            "imageReviewInlineWaitEnabled": False,
        },
    }

    with patch("routers.settings.get_settings_service", return_value=mock_service), patch(
        "routers.settings.runtime_metrics.snapshot",
        return_value={"adb": {"total_calls": 12}, "sqlite": {"slow_queries": 3}},
    ):
        response = client.get("/settings/performance/profile")

    assert response.status_code == 200
    data = response.json()
    assert data["lowSpecMode"] is True
    assert data["effective"]["maxConcurrentSyncDevices"] == 1
    assert data["metrics"]["adb"]["total_calls"] == 12
