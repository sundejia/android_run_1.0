"""Tests for the centralised AnalyticsService facade."""

from __future__ import annotations

from pathlib import Path

import pytest

from wecom_automation.database.schema import init_database
from wecom_automation.services.analytics import (
    AnalyticsService,
    EventType,
    get_default_service,
)
from wecom_automation.services.analytics.service import reset_default_service
from wecom_automation.services.review.storage import ReviewStorage


@pytest.fixture()
def storage(tmp_path: Path) -> ReviewStorage:
    db = tmp_path / "android.db"
    init_database(str(db), force_recreate=True)
    return ReviewStorage(str(db))


class TestAnalyticsService:
    def test_record_persists_and_lists(self, storage: ReviewStorage) -> None:
        svc = AnalyticsService(storage)
        svc.record(EventType.REVIEW_SUBMITTED, trace_id="42", payload={"a": 1})
        rows = svc.list_events()
        assert len(rows) == 1
        assert rows[0].event_type == "review.submitted"
        assert rows[0].trace_id == "42"

    def test_record_swallows_errors(self, storage: ReviewStorage, monkeypatch: pytest.MonkeyPatch) -> None:
        svc = AnalyticsService(storage)
        monkeypatch.setattr(storage, "record_event", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        svc.record(EventType.GOVERNANCE_BLOCKED, trace_id="1")

    def test_string_event_accepted(self, storage: ReviewStorage) -> None:
        svc = AnalyticsService(storage)
        svc.record("custom.event", trace_id="t")
        assert svc.list_events()[0].event_type == "custom.event"


class TestSingleton:
    def test_singleton_initialised_once(self, storage: ReviewStorage) -> None:
        reset_default_service()
        svc1 = get_default_service(storage=storage)
        svc2 = get_default_service()
        assert svc1 is svc2
        reset_default_service()

    def test_singleton_requires_storage_first_time(self) -> None:
        reset_default_service()
        with pytest.raises(RuntimeError):
            get_default_service()
