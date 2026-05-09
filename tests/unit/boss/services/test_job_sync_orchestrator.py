"""TDD tests for boss_automation/services/job_sync_orchestrator.py."""

from __future__ import annotations

import copy
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from boss_automation.database.job_repository import JobRepository
from boss_automation.database.recruiter_repository import RecruiterRepository
from boss_automation.parsers.job_list_parser import JobStatus
from boss_automation.parsers.recruiter_profile_parser import RecruiterProfile
from boss_automation.services.job_sync_orchestrator import (
    JobSyncOrchestrator,
    JobSyncProgress,
    JobSyncResult,
)
from tests._fixtures.loader import load_fixture

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "boss"


def _tree(label: str) -> dict[str, Any]:
    return load_fixture(FIXTURE_ROOT / "jobs_list" / f"{label}.json").ui_tree


class FakeAdbPort:
    """In-memory AdbPort with optional tab-aware tree serving.

    Two modes:

    1. ``trees=[t1, t2, ...]``: each ``get_state()`` advances the queue.
       When exhausted the last tree is repeated forever.
    2. ``trees_per_tab={"开放中": [...], "已关闭": [...]}``: the most
       recent ``tap_by_text(label)`` selects which queue to serve from.
       This mirrors the real BOSS app: tapping a tab changes which list
       the recycler view shows.

    Either mode may be used; mode 2 takes precedence when set.
    """

    def __init__(
        self,
        trees: Sequence[dict[str, Any]] | None = None,
        *,
        trees_per_tab: dict[str, Sequence[dict[str, Any]]] | None = None,
    ) -> None:
        self._trees = list(trees or [])
        self._idx = 0
        self._trees_per_tab = {label: list(seq) for label, seq in (trees_per_tab or {}).items()}
        self._idx_per_tab: dict[str, int] = {}
        self._current_tab: str | None = None
        self.start_app_calls: list[str] = []
        self.tap_text_calls: list[str] = []
        self.swipe_calls: list[tuple[int, int, int, int, int]] = []

    async def start_app(self, package_name: str) -> None:
        self.start_app_calls.append(package_name)

    async def get_state(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if self._trees_per_tab and self._current_tab is not None:
            queue = self._trees_per_tab.get(self._current_tab, [])
            if queue:
                idx = self._idx_per_tab.get(self._current_tab, 0)
                tree = queue[min(idx, len(queue) - 1)]
                self._idx_per_tab[self._current_tab] = idx + 1
                return copy.deepcopy(tree), []
            return {}, []

        if self._idx >= len(self._trees):
            tree = self._trees[-1] if self._trees else {}
        else:
            tree = self._trees[self._idx]
            self._idx += 1
        return copy.deepcopy(tree), []

    async def tap_by_text(self, text: str) -> bool:
        self.tap_text_calls.append(text)
        if self._trees_per_tab and text in self._trees_per_tab:
            self._current_tab = text
        return True

    async def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
    ) -> None:
        self.swipe_calls.append((x1, y1, x2, y2, duration_ms))

    async def tap(self, x: int, y: int) -> bool:
        return True

    async def type_text(self, text: str) -> bool:
        return True

    async def press_back(self) -> None:
        pass


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "boss.db"


@pytest.fixture()
def recruiter_id(db_path: Path) -> int:
    return RecruiterRepository(db_path).upsert(
        "EMU-1",
        RecruiterProfile(name="Alice", company="ACME"),
    )


@pytest.fixture()
def repo(db_path: Path) -> JobRepository:
    return JobRepository(db_path)


class TestSingleTabSync:
    @pytest.mark.asyncio
    async def test_persists_three_jobs_from_open_tab(self, repo: JobRepository, recruiter_id: int) -> None:
        # Open tab tree, then immediately stable (same tree returned)
        # so the orchestrator finishes after stable_threshold scrolls.
        adb = FakeAdbPort(trees=[_tree("open_tab")])
        orch = JobSyncOrchestrator(adb=adb, jobs_repo=repo, stable_threshold=1, max_scrolls=3)

        result = await orch.sync_jobs(recruiter_id=recruiter_id, tabs=(JobStatus.OPEN,))

        assert isinstance(result, JobSyncResult)
        rows = repo.list_for_recruiter(recruiter_id, status=JobStatus.OPEN)
        assert {r.boss_job_id for r in rows} == {
            "JD20260507001",
            "JD20260507002",
            "JD20260507003",
        }
        assert result.counts_per_tab[JobStatus.OPEN] == 3
        assert result.total_jobs == 3
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_taps_correct_tab_label_for_each_status(self, repo: JobRepository, recruiter_id: int) -> None:
        adb = FakeAdbPort(
            trees_per_tab={
                "开放中": [_tree("open_tab")],
                "已关闭": [_tree("closed_tab")],
            }
        )
        orch = JobSyncOrchestrator(adb=adb, jobs_repo=repo, stable_threshold=1)

        await orch.sync_jobs(
            recruiter_id=recruiter_id,
            tabs=(JobStatus.OPEN, JobStatus.CLOSED),
        )

        assert "开放中" in adb.tap_text_calls
        assert "已关闭" in adb.tap_text_calls

    @pytest.mark.asyncio
    async def test_handles_empty_state_without_persisting(self, repo: JobRepository, recruiter_id: int) -> None:
        adb = FakeAdbPort(trees=[_tree("empty_state")])
        orch = JobSyncOrchestrator(adb=adb, jobs_repo=repo, stable_threshold=1)

        result = await orch.sync_jobs(recruiter_id=recruiter_id, tabs=(JobStatus.OPEN,))

        assert repo.list_for_recruiter(recruiter_id) == []
        assert result.counts_per_tab[JobStatus.OPEN] == 0
        assert result.total_jobs == 0


class TestMultiTabSync:
    @pytest.mark.asyncio
    async def test_visits_open_then_closed(self, repo: JobRepository, recruiter_id: int) -> None:
        adb = FakeAdbPort(
            trees_per_tab={
                "开放中": [_tree("open_tab")],
                "已关闭": [_tree("closed_tab")],
            }
        )
        orch = JobSyncOrchestrator(adb=adb, jobs_repo=repo, stable_threshold=1)

        result = await orch.sync_jobs(
            recruiter_id=recruiter_id,
            tabs=(JobStatus.OPEN, JobStatus.CLOSED),
        )

        assert result.counts_per_tab[JobStatus.OPEN] == 3
        assert result.counts_per_tab[JobStatus.CLOSED] == 1
        assert result.total_jobs == 4
        # Open jobs and the closed job should both exist.
        assert {j.boss_job_id for j in repo.list_for_recruiter(recruiter_id)} == {
            "JD20260507001",
            "JD20260507002",
            "JD20260507003",
            "JD20260301001",
        }


class TestProgressCallback:
    @pytest.mark.asyncio
    async def test_emits_progress_event_per_tab(self, repo: JobRepository, recruiter_id: int) -> None:
        adb = FakeAdbPort(
            trees_per_tab={
                "开放中": [_tree("open_tab")],
                "已关闭": [_tree("closed_tab")],
            }
        )
        orch = JobSyncOrchestrator(adb=adb, jobs_repo=repo, stable_threshold=1)

        events: list[JobSyncProgress] = []
        await orch.sync_jobs(
            recruiter_id=recruiter_id,
            tabs=(JobStatus.OPEN, JobStatus.CLOSED),
            progress=events.append,
        )

        per_tab_finals = {(e.tab, e.is_final): e.total_count for e in events if e.is_final}
        assert per_tab_finals[(JobStatus.OPEN, True)] == 3
        assert per_tab_finals[(JobStatus.CLOSED, True)] == 1


class TestStability:
    @pytest.mark.asyncio
    async def test_stops_scrolling_when_ui_hash_stable(self, repo: JobRepository, recruiter_id: int) -> None:
        # Same tree returned forever → orchestrator must stop after
        # stable_threshold consecutive identical hashes, well before
        # max_scrolls is exhausted.
        adb = FakeAdbPort(trees=[_tree("open_tab")])
        orch = JobSyncOrchestrator(
            adb=adb,
            jobs_repo=repo,
            stable_threshold=2,
            max_scrolls=20,
        )

        await orch.sync_jobs(recruiter_id=recruiter_id, tabs=(JobStatus.OPEN,))

        # Should have stopped scrolling far below max_scrolls=20.
        assert len(adb.swipe_calls) <= 5

    @pytest.mark.asyncio
    async def test_respects_max_scrolls_when_ui_keeps_changing(self, repo: JobRepository, recruiter_id: int) -> None:
        # Every scroll returns a different "tree" by mutating a
        # field, so the hash never stabilizes; orchestrator must hit
        # max_scrolls and stop.
        trees: list[dict[str, Any]] = []
        for i in range(50):
            t = copy.deepcopy(_tree("open_tab"))
            # Mutate a benign field to keep hash changing.
            t["__sentinel"] = i
            trees.append(t)

        adb = FakeAdbPort(trees=trees)
        orch = JobSyncOrchestrator(adb=adb, jobs_repo=repo, stable_threshold=2, max_scrolls=4)

        await orch.sync_jobs(recruiter_id=recruiter_id, tabs=(JobStatus.OPEN,))

        assert len(adb.swipe_calls) <= 4


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_tab_failure_does_not_block_other_tabs(self, repo: JobRepository, recruiter_id: int) -> None:
        # First tap raises mid-sync, but the orchestrator should
        # continue with the next tab and surface the error in result.
        class FlakyAdb(FakeAdbPort):
            async def tap_by_text(self, text: str) -> bool:
                self.tap_text_calls.append(text)
                if text == "开放中":
                    raise RuntimeError("simulated tap failure")
                return True

        adb = FlakyAdb(trees=[_tree("closed_tab")])
        orch = JobSyncOrchestrator(adb=adb, jobs_repo=repo, stable_threshold=1)

        result = await orch.sync_jobs(
            recruiter_id=recruiter_id,
            tabs=(JobStatus.OPEN, JobStatus.CLOSED),
        )

        assert result.counts_per_tab[JobStatus.OPEN] == 0
        assert result.counts_per_tab[JobStatus.CLOSED] == 1
        assert any("open" in e.lower() for e in result.errors)
