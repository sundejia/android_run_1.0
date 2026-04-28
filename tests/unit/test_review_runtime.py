"""Tests for the review runtime assembly helper."""

from __future__ import annotations

from pathlib import Path

import pytest

from wecom_automation.database.schema import init_database
from wecom_automation.services.review.runtime import (
    build_review_components,
    review_gate_enabled,
)


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    db = tmp_path / "android.db"
    init_database(str(db), force_recreate=True)
    return str(db)


class TestBuildReviewComponents:
    def test_returns_none_when_disabled(self, db_path: str) -> None:
        storage, sub, on = build_review_components(
            db_path=db_path,
            media_settings={"review_gate": {"enabled": False}},
        )
        assert (storage, sub, on) == (None, None, False)

    def test_returns_components_when_enabled(self, db_path: str) -> None:
        storage, sub, on = build_review_components(
            db_path=db_path,
            media_settings={
                "review_gate": {
                    "enabled": True,
                    "rating_server_url": "http://127.0.0.1:8080",
                }
            },
        )
        assert on is True
        assert storage is not None
        assert callable(sub)

    def test_handles_missing_settings(self, db_path: str) -> None:
        storage, sub, on = build_review_components(db_path=db_path, media_settings=None)
        assert on is False
        assert storage is None
        assert sub is None


class TestEnabledFlag:
    def test_default_false(self) -> None:
        assert review_gate_enabled(None) is False
        assert review_gate_enabled({}) is False
        assert review_gate_enabled({"review_gate": {}}) is False

    def test_true_when_set(self) -> None:
        assert review_gate_enabled({"review_gate": {"enabled": True}}) is True
