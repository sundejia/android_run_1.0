import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2] / "wecom-desktop" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

PROJECT_ROOT = BACKEND_DIR.parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.mark.asyncio
async def test_scan_device_for_responses_handles_missing_sidecar_client(monkeypatch):
    from services.followup.response_detector import (  # type: ignore[reportMissingImports]
        ResponseDetector,
    )

    class DummyADB:
        async def scroll_to_top(self):
            return None

    class DummyWeComService:
        def __init__(self, config):
            self.config = config
            self.adb = DummyADB()

        async def launch_wecom(self, wait_for_ready=True):
            return None

        async def switch_to_private_chats(self):
            return None

    import wecom_automation.services.wecom_service as wecom_service_module

    monkeypatch.setattr(wecom_service_module, "WeComService", DummyWeComService)

    detector = ResponseDetector(repository=None, settings_manager=None)

    async def fake_detect_first_page_unread(*_args, **_kwargs):
        return []

    monkeypatch.setattr(detector, "_detect_first_page_unread", fake_detect_first_page_unread)

    result = await detector._scan_device_for_responses("serial123")

    assert result["users_processed"] == 0
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_init_media_event_bus_reads_settings_from_control_db(monkeypatch):
    from services.followup.response_detector import ResponseDetector  # type: ignore[reportMissingImports]
    import wecom_automation.services.media_actions.factory as media_factory

    class DummyRepository:
        _db_path = "device-storage.db"

    detector = ResponseDetector(repository=DummyRepository(), settings_manager=None)
    control_db = Path("control.db")

    captured = {}

    def fake_build_media_event_bus(
        db_path,
        settings_db_path=None,
        effects_db_path=None,
        wecom_service=None,
        on_action_results=None,
    ):
        captured["db_path"] = db_path
        captured["settings_db_path"] = settings_db_path
        captured["effects_db_path"] = effects_db_path
        captured["wecom_service"] = wecom_service
        captured["on_action_results"] = on_action_results
        return None, {"enabled": False}

    monkeypatch.setattr(media_factory, "build_media_event_bus", fake_build_media_event_bus)
    monkeypatch.setattr("services.followup.response_detector.get_control_db_path", lambda: control_db)

    wecom = object()
    await detector._init_media_event_bus(wecom, "serial123")

    assert captured["db_path"] == "device-storage.db"
    assert captured["settings_db_path"] == str(control_db)
    assert captured["effects_db_path"] == str(control_db)
    assert captured["wecom_service"] is wecom
