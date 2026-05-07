"""Job sync orchestrator for the BOSS Zhipin "我的职位" page.

Iterates the configured set of job-status tabs, scrolls each list
until the UI is stable, parses cards into ``Job`` records, and writes
them to the ``jobs`` table. Errors on one tab never block the rest.

Design notes
------------
- Depends on the small ``AdbPort`` Protocol (no DroidRun import).
- Stability detection uses a hash of the JSON-stringified UI tree.
  Two consecutive identical hashes (configurable) stop scrolling for
  the current tab. ``max_scrolls`` is a hard cap to bound runtime when
  the UI keeps changing (e.g. animations, infinite spinners).
- Progress events are emitted twice per tab: when entering the tab
  (``is_final=False``) and after the final persistence
  (``is_final=True``). This is enough for the desktop frontend to
  render a per-tab progress row without overloading the WebSocket.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Final

from boss_automation.database.job_repository import JobRepository
from boss_automation.parsers.job_list_parser import (
    Job,
    JobStatus,
    parse_job_list,
)
from boss_automation.services.adb_port import AdbPort

DEFAULT_TABS: Final[tuple[JobStatus, ...]] = (JobStatus.OPEN, JobStatus.CLOSED)
DEFAULT_STABLE_THRESHOLD: Final[int] = 2
DEFAULT_MAX_SCROLLS: Final[int] = 30

# Default swipe coordinates suit a 1440x3120 portrait phone. Production
# callers can override per-device by passing ``swipe_coords``.
_DEFAULT_SWIPE: Final[tuple[int, int, int, int]] = (720, 2400, 720, 1000)

_TAB_LABELS: Final[dict[JobStatus, str]] = {
    JobStatus.OPEN: "开放中",
    JobStatus.CLOSED: "已关闭",
    JobStatus.HIDDEN: "仅我可见",
    JobStatus.DRAFT: "草稿",
}


@dataclass(frozen=True, slots=True)
class JobSyncProgress:
    tab: JobStatus
    new_count: int
    total_count: int
    scroll_index: int
    is_final: bool = False


@dataclass(slots=True)
class JobSyncResult:
    counts_per_tab: dict[JobStatus, int] = field(default_factory=dict)
    total_jobs: int = 0
    errors: list[str] = field(default_factory=list)


def _hash_tree(tree: dict) -> str:
    blob = json.dumps(tree, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class JobSyncOrchestrator:
    """Drives one full job-list sync pass across the requested tabs."""

    def __init__(
        self,
        adb: AdbPort,
        jobs_repo: JobRepository,
        *,
        stable_threshold: int = DEFAULT_STABLE_THRESHOLD,
        max_scrolls: int = DEFAULT_MAX_SCROLLS,
        swipe_coords: tuple[int, int, int, int] = _DEFAULT_SWIPE,
    ) -> None:
        if stable_threshold < 1:
            raise ValueError("stable_threshold must be >= 1")
        if max_scrolls < 0:
            raise ValueError("max_scrolls must be >= 0")
        self._adb = adb
        self._repo = jobs_repo
        self._stable_threshold = stable_threshold
        self._max_scrolls = max_scrolls
        self._swipe_coords = swipe_coords

    async def sync_jobs(
        self,
        recruiter_id: int,
        *,
        tabs: Sequence[JobStatus] = DEFAULT_TABS,
        progress: Callable[[JobSyncProgress], None] | None = None,
    ) -> JobSyncResult:
        result = JobSyncResult()
        for tab in tabs:
            try:
                count = await self._sync_one_tab(recruiter_id, tab, progress)
                result.counts_per_tab[tab] = count
                result.total_jobs += count
            except Exception as exc:  # noqa: BLE001 - keep going across tabs
                result.counts_per_tab.setdefault(tab, 0)
                result.errors.append(f"tab={tab.value}: {type(exc).__name__}: {exc}")
        return result

    async def _sync_one_tab(
        self,
        recruiter_id: int,
        tab: JobStatus,
        progress: Callable[[JobSyncProgress], None] | None,
    ) -> int:
        await self._adb.tap_by_text(_TAB_LABELS[tab])

        seen_ids: set[str] = set()
        scroll_index = 0
        stable_count = 0
        last_hash: str | None = None

        if progress is not None:
            progress(
                JobSyncProgress(
                    tab=tab,
                    new_count=0,
                    total_count=0,
                    scroll_index=0,
                    is_final=False,
                )
            )

        while True:
            tree, _ = await self._adb.get_state()
            tree_hash = _hash_tree(tree)
            jobs = parse_job_list(tree)

            new_jobs: list[Job] = []
            for job in jobs:
                if job.boss_job_id in seen_ids:
                    continue
                seen_ids.add(job.boss_job_id)
                # Force the status from the tab being synced; the parser
                # uses whichever tab is "selected" in the tree, which is
                # not always reliable in test fixtures.
                if job.status != tab:
                    job = Job(
                        boss_job_id=job.boss_job_id,
                        title=job.title,
                        status=tab,
                        salary_min=job.salary_min,
                        salary_max=job.salary_max,
                        location=job.location,
                        education=job.education,
                        experience=job.experience,
                    )
                new_jobs.append(job)

            if new_jobs:
                self._repo.upsert_many(recruiter_id, new_jobs)

            if progress is not None:
                progress(
                    JobSyncProgress(
                        tab=tab,
                        new_count=len(new_jobs),
                        total_count=len(seen_ids),
                        scroll_index=scroll_index,
                        is_final=False,
                    )
                )

            if last_hash is not None and tree_hash == last_hash:
                stable_count += 1
            else:
                stable_count = 0
            last_hash = tree_hash

            if stable_count >= self._stable_threshold:
                break
            if scroll_index >= self._max_scrolls:
                break

            await self._adb.swipe(*self._swipe_coords)
            scroll_index += 1

        if progress is not None:
            progress(
                JobSyncProgress(
                    tab=tab,
                    new_count=0,
                    total_count=len(seen_ids),
                    scroll_index=scroll_index,
                    is_final=True,
                )
            )
        return len(seen_ids)
