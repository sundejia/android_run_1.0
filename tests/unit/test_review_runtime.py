"""Tests for the review runtime assembly helper.

Locks the 2026-05-12 dedup contract: the rating-server URL and upload
timeout come from ``general.image_server_ip`` /
``general.image_review_timeout_seconds`` (the same source the realtime
``image_review_client`` already used), NOT from
``media_auto_actions.review_gate``.
"""

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
            media_settings={"review_gate": {"enabled": True}},
            general_settings={
                "image_server_ip": "http://review.local:8080",
                "image_review_timeout_seconds": 25,
                "image_upload_enabled": True,
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

    def test_disabled_when_image_upload_disabled(self, db_path: str) -> None:
        """Even with the gate switched on, disabling the system-level image
        upload toggle must short-circuit the gate so the realtime path and
        the gate path stay in lock-step."""
        storage, sub, on = build_review_components(
            db_path=db_path,
            media_settings={"review_gate": {"enabled": True}},
            general_settings={
                "image_server_ip": "http://review.local:8080",
                "image_review_timeout_seconds": 30,
                "image_upload_enabled": False,
            },
        )
        assert (storage, sub, on) == (None, None, False)

    def test_disabled_when_server_url_blank(self, db_path: str) -> None:
        """No URL configured -> short-circuit. Prevents the silent
        fallback-to-localhost behaviour the legacy default produced."""
        storage, sub, on = build_review_components(
            db_path=db_path,
            media_settings={"review_gate": {"enabled": True}},
            general_settings={"image_server_ip": "   "},
        )
        assert (storage, sub, on) == (None, None, False)

    def test_legacy_review_gate_url_is_ignored(self, db_path: str) -> None:
        """Locks the dedup contract: rating_server_url under review_gate is
        no longer consulted; only general.image_server_ip drives the URL."""
        storage, sub, on = build_review_components(
            db_path=db_path,
            media_settings={
                "review_gate": {
                    "enabled": True,
                    # Legacy field — should be ignored.
                    "rating_server_url": "http://legacy.local:9999",
                }
            },
            general_settings={"image_server_ip": ""},
        )
        # general URL is empty, so even with the legacy field set the gate
        # must short-circuit. If this regresses, the legacy field will
        # silently re-introduce the dual-write divergence the dedup fixed.
        assert (storage, sub, on) == (None, None, False)


class TestEnabledFlag:
    def test_default_false(self) -> None:
        assert review_gate_enabled(None) is False
        assert review_gate_enabled({}) is False
        assert review_gate_enabled({"review_gate": {}}) is False

    def test_true_when_set(self) -> None:
        assert review_gate_enabled({"review_gate": {"enabled": True}}) is True
