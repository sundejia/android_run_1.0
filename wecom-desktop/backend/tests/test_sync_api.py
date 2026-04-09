import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from routers.sync import router as sync_router

app = FastAPI()
app.include_router(sync_router, prefix="/sync")


def test_start_sync_respects_low_spec_concurrency_limit():
    client = TestClient(app)
    mock_manager = Mock()
    mock_manager.get_active_sync_count.return_value = 0
    mock_manager.start_sync = AsyncMock(return_value=True)

    mock_settings_service = Mock()
    mock_settings_service.get_max_concurrent_sync_devices.return_value = 1

    with patch("routers.sync.get_device_manager", return_value=mock_manager), patch(
        "routers.sync.get_settings_service", return_value=mock_settings_service
    ):
        response = client.post(
            "/sync/start",
            json={
                "serials": ["device-1", "device-2"],
                "options": {},
                "stagger_delay": 0,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["started"] == ["device-1"]
    assert data["failed"] == ["device-2"]


def test_start_sync_returns_429_when_no_slots_available():
    client = TestClient(app)
    mock_manager = Mock()
    mock_manager.get_active_sync_count.return_value = 1
    mock_settings_service = Mock()
    mock_settings_service.get_max_concurrent_sync_devices.return_value = 1

    with patch("routers.sync.get_device_manager", return_value=mock_manager), patch(
        "routers.sync.get_settings_service", return_value=mock_settings_service
    ):
        response = client.post(
            "/sync/start",
            json={"serials": ["device-1"], "options": {}},
        )

    assert response.status_code == 429
