"""LifecycleService — startup self-healing for the review-gating subsystem.

Designed to be called once at backend startup; safe to call again on a
periodic schedule (idempotent). Each method is explicit and side-effect
limited so it can be unit-tested without touching the real filesystem or
network.

Responsibilities:
    * ``recover_pending`` — re-submit / expire ``pending_reviews`` rows that
      were stranded by a crash or restart.
    * ``purge_idempotency`` — delete ``webhook_idempotency`` rows older than
      a configurable TTL (default 24h).
    * ``move_orphan_images`` — sweep the on-disk image folder for files that
      have no DB row and move them to a ``.trash`` sub-folder.
"""

from __future__ import annotations

import logging
import shutil
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from wecom_automation.services.review.storage import (
    PendingReviewRow,
    ReviewStorage,
)

logger = logging.getLogger("lifecycle")


@dataclass(frozen=True)
class PendingRecoveryStats:
    resubmitted: int
    expired: int
    skipped: int


_TERMINAL_STATUSES = frozenset({"approved", "rejected", "expired", "blocked", "verdict_received"})


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


class LifecycleService:
    def __init__(self, *, storage: ReviewStorage) -> None:
        self._storage = storage

    async def recover_pending(
        self,
        *,
        submitter: Callable[[int, str], Awaitable[None]],
        expire_minutes: int = 30,
        max_attempts: int = 3,
    ) -> PendingRecoveryStats:
        """Reconcile pending_reviews rows that were left in flight.

        Algorithm per row (status == 'pending' or 'submit_failed'):
            * Compute age = now - created_at.
            * If age > expire_minutes  → mark expired.
            * Elif attempts >= max_attempts → mark expired.
            * Else → call ``submitter(message_id, image_path)`` and
              ``increment_attempts``.
        """
        now = datetime.now(UTC)
        pending: list[PendingReviewRow] = []
        for status in ("pending", "submit_failed"):
            pending.extend(self._storage.list_pending_reviews(status=status))

        resubmitted = 0
        expired = 0
        skipped = 0

        for row in pending:
            if row.status in _TERMINAL_STATUSES:
                skipped += 1
                continue
            try:
                created = _parse_iso(row.created_at) if row.created_at else now
            except ValueError:
                created = now

            age_minutes = (now - created).total_seconds() / 60.0

            if age_minutes >= float(expire_minutes) or row.attempts >= max_attempts:
                self._storage.mark_pending_status(row.message_id, "expired", last_error="lifecycle_expired")
                self._storage.record_event(
                    "lifecycle.pending.expired",
                    trace_id=str(row.message_id),
                    payload={
                        "age_minutes": round(age_minutes, 2),
                        "attempts": row.attempts,
                    },
                )
                expired += 1
                continue

            try:
                await submitter(row.message_id, row.image_path)
                self._storage.increment_attempts(row.message_id)
                self._storage.record_event(
                    "lifecycle.pending.resubmitted",
                    trace_id=str(row.message_id),
                    payload={"attempts": row.attempts + 1},
                )
                resubmitted += 1
            except Exception as exc:
                logger.warning(
                    "lifecycle resubmit failed for message_id=%s: %s",
                    row.message_id,
                    exc,
                )
                self._storage.increment_attempts(row.message_id, last_error=str(exc))
                skipped += 1

        return PendingRecoveryStats(resubmitted=resubmitted, expired=expired, skipped=skipped)

    def purge_idempotency(self, *, ttl_hours: int = 24) -> int:
        cutoff = (datetime.now(UTC) - timedelta(hours=ttl_hours)).isoformat()
        deleted = self._storage.purge_old_idempotency(cutoff)
        if deleted:
            self._storage.record_event(
                "lifecycle.idempotency.purged",
                payload={"deleted": deleted, "ttl_hours": ttl_hours},
            )
        return deleted

    def move_orphan_images(self, images_dir: Path, *, max_files: int = 200) -> int:
        """Move on-disk images with no DB reference to a ``.trash`` folder.

        Returns the number of files moved. Files are NOT deleted — keeping
        them under ``.trash`` lets operators inspect what was lost.
        """
        images_dir = Path(images_dir)
        if not images_dir.exists() or not images_dir.is_dir():
            return 0

        trash_dir = images_dir / ".trash"

        # Collect every image_path mentioned in pending_reviews so we never
        # quarantine a file that's still in flight.
        known: set[str] = set()
        for status in ("pending", "submit_failed", "approved", "rejected", "verdict_received"):
            for row in self._storage.list_pending_reviews(status=status):
                if row.image_path:
                    known.add(str(Path(row.image_path).resolve()))

        moved = 0
        for entry in images_dir.iterdir():
            if moved >= max_files:
                break
            if entry.is_dir():
                continue
            if entry.name.startswith("."):
                continue
            if entry.parent == trash_dir:
                continue
            try:
                resolved = str(entry.resolve())
            except OSError:
                continue
            if resolved in known:
                continue
            trash_dir.mkdir(parents=True, exist_ok=True)
            target = trash_dir / f"{int(time.time())}_{entry.name}"
            try:
                shutil.move(str(entry), str(target))
                moved += 1
            except OSError as exc:
                logger.warning("orphan move failed for %s: %s", entry, exc)

        if moved:
            self._storage.record_event(
                "lifecycle.orphan.moved",
                payload={"moved": moved, "trash": str(trash_dir)},
            )
        return moved
