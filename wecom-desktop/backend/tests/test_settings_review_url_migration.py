"""Regression tests for ``SettingsService.migrate_review_gate_url_to_general``.

The 2026-05-12 dedup moved the rating-server URL and upload timeout from
``media_auto_actions.review_gate.{rating_server_url, upload_timeout_seconds}``
to ``general.{image_server_ip, image_review_timeout_seconds}`` so the
realtime image-review path and the review-gate runtime stop drifting.

These tests lock the contract of the one-shot migration:

    1. Promote a non-default legacy URL into ``general.image_server_ip``
       only when the general field is still empty.
    2. Never overwrite a non-empty general value.
    3. Skip the legacy localhost default (``http://127.0.0.1:8080``)
       so untouched installs do not start pointing at localhost.
    4. Always strip the legacy keys from the persisted review_gate JSON
       so the second run becomes a no-op.
    5. Be idempotent: running it twice on the same DB must not change
       anything the second time.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from services.settings.service import SettingsService  # noqa: E402


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "settings.db")


def _make_service(db_path: str) -> SettingsService:
    """Build a fresh SettingsService against an isolated SQLite file.

    ``__init__`` already runs ``initialize_defaults`` and the migration
    once, so caller tests can call ``migrate_review_gate_url_to_general``
    again to assert idempotency.
    """
    return SettingsService(db_path)


class TestMigrationPromotesUrl:
    def test_promotes_non_default_url_when_general_empty(self, db_path: str) -> None:
        # Pre-seed a legacy review_gate row with a real (non-localhost) URL
        # and an empty general.image_server_ip.
        svc = _make_service(db_path)
        svc.set("general", "image_server_ip", "")
        svc.set(
            "media_auto_actions",
            "review_gate",
            {
                "enabled": True,
                "rating_server_url": "http://review.local:8080",
                "video_review_policy": "extract_frame",
            },
        )

        changed = svc.migrate_review_gate_url_to_general()

        assert changed is True
        assert svc.get_image_server_ip() == "http://review.local:8080"
        # legacy keys are stripped from the stored JSON
        review_gate = svc.get("media_auto_actions", "review_gate")
        assert "rating_server_url" not in review_gate
        assert review_gate["enabled"] is True

    def test_does_not_overwrite_existing_general_url(self, db_path: str) -> None:
        svc = _make_service(db_path)
        # General already has a deliberately set value — sacred, do not touch.
        svc.set("general", "image_server_ip", "http://kept.local:8000")
        svc.set(
            "media_auto_actions",
            "review_gate",
            {"enabled": True, "rating_server_url": "http://other.local:9000"},
        )

        svc.migrate_review_gate_url_to_general()

        assert svc.get_image_server_ip() == "http://kept.local:8000"
        # legacy field still gets stripped — convergence still wins.
        review_gate = svc.get("media_auto_actions", "review_gate")
        assert "rating_server_url" not in review_gate

    def test_skips_legacy_localhost_default(self, db_path: str) -> None:
        """The old hard-coded default was http://127.0.0.1:8080. Promoting
        that value would silently point untouched installs at localhost,
        which is exactly the misconfiguration the dedup is meant to fix."""
        svc = _make_service(db_path)
        svc.set("general", "image_server_ip", "")
        svc.set(
            "media_auto_actions",
            "review_gate",
            {"enabled": False, "rating_server_url": "http://127.0.0.1:8080"},
        )

        svc.migrate_review_gate_url_to_general()

        # general.image_server_ip stays empty — operator must explicitly
        # configure a real server URL in System Settings.
        assert svc.get_image_server_ip() == ""
        # legacy field still cleaned up.
        review_gate = svc.get("media_auto_actions", "review_gate")
        assert "rating_server_url" not in review_gate


class TestMigrationPromotesTimeout:
    def test_promotes_tuned_timeout_when_general_at_default(self, db_path: str) -> None:
        svc = _make_service(db_path)
        # general timeout untouched (default 40)
        svc.set("general", "image_review_timeout_seconds", 40)
        svc.set(
            "media_auto_actions",
            "review_gate",
            {"enabled": True, "upload_timeout_seconds": 50.0},
        )

        svc.migrate_review_gate_url_to_general()

        assert svc.get_image_review_timeout_seconds() == 50
        review_gate = svc.get("media_auto_actions", "review_gate")
        assert "upload_timeout_seconds" not in review_gate

    def test_skips_legacy_30s_default_timeout(self, db_path: str) -> None:
        """30s was the old default; carrying it over would falsely look like
        operator intent."""
        svc = _make_service(db_path)
        svc.set("general", "image_review_timeout_seconds", 40)
        svc.set(
            "media_auto_actions",
            "review_gate",
            {"enabled": True, "upload_timeout_seconds": 30.0},
        )

        svc.migrate_review_gate_url_to_general()

        assert svc.get_image_review_timeout_seconds() == 40

    def test_does_not_overwrite_tuned_general_timeout(self, db_path: str) -> None:
        svc = _make_service(db_path)
        svc.set("general", "image_review_timeout_seconds", 90)
        svc.set(
            "media_auto_actions",
            "review_gate",
            {"enabled": True, "upload_timeout_seconds": 25.0},
        )

        svc.migrate_review_gate_url_to_general()

        # operator-tuned general value survives.
        assert svc.get_image_review_timeout_seconds() == 90


class TestIdempotency:
    def test_second_run_is_a_noop(self, db_path: str) -> None:
        svc = _make_service(db_path)
        svc.set("general", "image_server_ip", "")
        svc.set(
            "media_auto_actions",
            "review_gate",
            {
                "enabled": True,
                "rating_server_url": "http://review.local:8080",
                "upload_timeout_seconds": 50.0,
            },
        )

        first = svc.migrate_review_gate_url_to_general()
        second = svc.migrate_review_gate_url_to_general()

        assert first is True
        assert second is False
        # State is stable
        assert svc.get_image_server_ip() == "http://review.local:8080"
        review_gate = svc.get("media_auto_actions", "review_gate")
        for legacy in ("rating_server_url", "upload_timeout_seconds", "upload_max_attempts"):
            assert legacy not in review_gate

    def test_no_legacy_keys_means_no_change(self, db_path: str) -> None:
        """Brand-new installs (or already-migrated DBs) have no legacy keys
        in review_gate. The migration must be a no-op without touching any
        general setting."""
        svc = _make_service(db_path)
        svc.set(
            "media_auto_actions",
            "review_gate",
            {"enabled": False, "video_review_policy": "extract_frame"},
        )
        original_general_url = svc.get_image_server_ip()

        result = svc.migrate_review_gate_url_to_general()

        assert result is False
        assert svc.get_image_server_ip() == original_general_url


class TestSettingsServiceInitRunsMigration:
    def test_init_runs_migration_automatically(self, db_path: str) -> None:
        """Constructing SettingsService must trigger migration so we never
        ship a code path that requires an explicit call site somewhere."""
        # Bootstrap a service and seed legacy state.
        seed = SettingsService(db_path)
        seed.set("general", "image_server_ip", "")
        seed.set(
            "media_auto_actions",
            "review_gate",
            {"enabled": True, "rating_server_url": "http://review.local:8080"},
        )

        # A fresh SettingsService against the same DB should run the
        # migration in __init__ and converge the state.
        SettingsService(db_path)

        verify = SettingsService(db_path)
        assert verify.get_image_server_ip() == "http://review.local:8080"
        review_gate = verify.get("media_auto_actions", "review_gate")
        assert "rating_server_url" not in review_gate
