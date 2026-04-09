from __future__ import annotations

from types import SimpleNamespace


def test_create_sync_orchestrator_uses_control_db_for_media_actions(monkeypatch, tmp_path):
    import wecom_automation.services.sync.factory as factory

    control_db = tmp_path / "control.db"
    device_db = tmp_path / "device.db"
    captured: dict[str, object] = {}

    class DummyConfig:
        device_serial = "SER123"

    class DummyRepository:
        def __init__(self, db_path):
            self.db_path = db_path

    class DummyWeComService:
        def __init__(self, config):
            self.config = config
            self.device_serial = config.device_serial

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
        return "media-bus", {"enabled": True}

    monkeypatch.setattr(factory, "Config", DummyConfig)
    monkeypatch.setattr(factory, "get_default_db_path", lambda: control_db)
    monkeypatch.setattr(factory, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(factory, "ConversationRepository", DummyRepository)
    monkeypatch.setattr(factory, "WeComService", DummyWeComService)
    monkeypatch.setattr(factory, "HumanTiming", lambda multiplier: SimpleNamespace(multiplier=multiplier))
    monkeypatch.setattr(factory, "CheckpointManager", lambda *args, **kwargs: SimpleNamespace())
    monkeypatch.setattr(factory, "UnreadUserExtractor", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(factory, "AvatarManager", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(factory, "CustomerSyncer", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(factory, "SyncOrchestrator", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(factory, "create_message_processor", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(factory, "build_media_event_bus", fake_build_media_event_bus)

    orchestrator = factory.create_sync_orchestrator(db_path=str(device_db))

    assert captured["db_path"] == str(device_db)
    assert captured["settings_db_path"] == str(control_db)
    assert captured["effects_db_path"] == str(control_db)
    assert isinstance(captured["wecom_service"], DummyWeComService)
    assert orchestrator.customer_syncer.message_processor.media_event_bus == "media-bus"
    assert orchestrator.customer_syncer.message_processor.media_action_settings == {"enabled": True}


def test_create_customer_syncer_uses_control_db_for_media_actions(monkeypatch, tmp_path):
    import wecom_automation.services.sync.factory as factory

    control_db = tmp_path / "control.db"
    device_db = tmp_path / "device.db"
    captured: dict[str, object] = {}

    class DummyConfig:
        device_serial = "SER123"

    class DummyRepository:
        def __init__(self):
            self.db_path = str(device_db)

    class DummyWeComService:
        def __init__(self, config):
            self.config = config
            self.device_serial = config.device_serial

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
        return "media-bus", {"enabled": True}

    monkeypatch.setattr(factory, "Config", DummyConfig)
    monkeypatch.setattr(factory, "get_default_db_path", lambda: control_db)
    monkeypatch.setattr(factory, "WeComService", DummyWeComService)
    monkeypatch.setattr(factory, "HumanTiming", lambda multiplier: SimpleNamespace(multiplier=multiplier))
    monkeypatch.setattr(factory, "CustomerSyncer", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(factory, "create_message_processor", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(factory, "build_media_event_bus", fake_build_media_event_bus)

    repository = DummyRepository()
    syncer = factory.create_customer_syncer(repository=repository)

    assert captured["db_path"] == str(device_db)
    assert captured["settings_db_path"] == str(control_db)
    assert captured["effects_db_path"] == str(control_db)
    assert isinstance(captured["wecom_service"], DummyWeComService)
    assert syncer.message_processor.media_event_bus == "media-bus"
    assert syncer.message_processor.media_action_settings == {"enabled": True}
