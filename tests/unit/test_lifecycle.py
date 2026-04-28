"""Tests for the M10 lifecycle/self-healing service.

LifecycleService is invoked once at backend startup and (optionally) on a
periodic schedule. It is responsible for clearing crash-time debris so the
next-day-OS-survives-overnight requirement actually holds.

Concerns covered:
    * Pending review recovery: pending rows older than ``expire_minutes`` are
      either resubmitted (attempts left) or marked expired.
    * Orphan image cleanup: image files on disk that have no corresponding DB
      row are moved into a ``.trash`` folder (kept, not deleted, for forensics).
    * Idempotency-key GC: webhook_idempotency rows older than ``ttl_hours`` are
      deleted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from wecom_automation.database.schema import init_database
from wecom_automation.services.lifecycle.startup import (
    LifecycleService,
    PendingRecoveryStats,
)
from wecom_automation.services.review.storage import (
    PendingReviewRow,
    ReviewStorage,
)


def _iso_minutes_ago(minutes: int) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()


def _iso_hours_ago(hours: int) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours)).isoformat()


@pytest.fixture()
def storage(tmp_path: Path) -> ReviewStorage:
    db = tmp_path / "android.db"
    init_database(str(db), force_recreate=True)
    return ReviewStorage(str(db))


def _seed_pending(
    storage: ReviewStorage,
    *,
    message_id: int,
    minutes_ago: int,
    image_path: str = "/tmp/x.png",
    attempts: int = 0,
) -> None:
    storage.insert_pending_review(
        PendingReviewRow(
            message_id=message_id,
            customer_id=1,
            customer_name="x",
            device_serial="d",
            channel=None,
            kefu_name="k",
            image_path=image_path,
            attempts=attempts,
            created_at=_iso_minutes_ago(minutes_ago),
        )
    )


class TestRecoverPending:
    @pytest.mark.asyncio
    async def test_resubmits_recent_pending_rows(self, storage: ReviewStorage) -> None:
        _seed_pending(storage, message_id=1, minutes_ago=5, image_path="/tmp/a.png")
        _seed_pending(storage, message_id=2, minutes_ago=10, image_path="/tmp/b.png")
        submitter = AsyncMock()

        svc = LifecycleService(storage=storage)
        stats = await svc.recover_pending(
            submitter=submitter,
            expire_minutes=30,
            max_attempts=3,
        )

        assert isinstance(stats, PendingRecoveryStats)
        assert stats.resubmitted == 2
        assert stats.expired == 0
        # Submitter called for each
        assert submitter.await_count == 2

    @pytest.mark.asyncio
    async def test_expires_when_too_old(self, storage: ReviewStorage) -> None:
        _seed_pending(storage, message_id=10, minutes_ago=120)
        submitter = AsyncMock()
        svc = LifecycleService(storage=storage)
        stats = await svc.recover_pending(
            submitter=submitter,
            expire_minutes=30,
            max_attempts=3,
        )
        assert stats.resubmitted == 0
        assert stats.expired == 1
        submitter.assert_not_awaited()
        pr = storage.get_pending_review(10)
        assert pr is not None
        assert pr.status == "expired"

    @pytest.mark.asyncio
    async def test_skips_already_terminal(self, storage: ReviewStorage) -> None:
        _seed_pending(storage, message_id=20, minutes_ago=5)
        storage.mark_pending_status(20, "approved")
        submitter = AsyncMock()
        svc = LifecycleService(storage=storage)
        stats = await svc.recover_pending(
            submitter=submitter,
            expire_minutes=30,
            max_attempts=3,
        )
        assert stats.resubmitted == 0
        submitter.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_attempts_exceeded_marks_expired(self, storage: ReviewStorage) -> None:
        _seed_pending(storage, message_id=30, minutes_ago=5, attempts=3)
        submitter = AsyncMock()
        svc = LifecycleService(storage=storage)
        stats = await svc.recover_pending(
            submitter=submitter,
            expire_minutes=30,
            max_attempts=3,
        )
        assert stats.expired == 1
        assert stats.resubmitted == 0
        submitter.assert_not_awaited()


class TestPurgeIdempotency:
    def test_deletes_old_keys(self, storage: ReviewStorage) -> None:
        # Old key (manually written with stale received_at)
        storage.try_register_idempotency_key("old", _iso_hours_ago(48))
        storage.try_register_idempotency_key("recent", _iso_hours_ago(1))

        svc = LifecycleService(storage=storage)
        deleted = svc.purge_idempotency(ttl_hours=24)
        assert deleted == 1


class TestOrphanImages:
    def test_moves_orphans_to_trash(self, storage: ReviewStorage, tmp_path: Path) -> None:
        images_dir = tmp_path / "images"
        images_dir.mkdir()
        # File with corresponding pending_review row
        kept = images_dir / "kept.png"
        kept.write_bytes(b"x")
        _seed_pending(storage, message_id=1, minutes_ago=1, image_path=str(kept))
        # Orphan file
        orphan = images_dir / "orphan.png"
        orphan.write_bytes(b"y")

        svc = LifecycleService(storage=storage)
        moved = svc.move_orphan_images(images_dir, max_files=100)

        assert moved == 1
        assert kept.exists()
        assert not orphan.exists()
        trash = images_dir / ".trash"
        assert trash.exists()
        assert any(trash.iterdir())

    def test_ignores_subdirs_named_trash(self, storage: ReviewStorage, tmp_path: Path) -> None:
        images_dir = tmp_path / "images"
        images_dir.mkdir()
        trash = images_dir / ".trash"
        trash.mkdir()
        (trash / "old.png").write_bytes(b"z")
        svc = LifecycleService(storage=storage)
        moved = svc.move_orphan_images(images_dir, max_files=100)
        assert moved == 0
