"""Tests for routers/boss_jobs.py."""

from __future__ import annotations

import copy
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

project_root = backend_dir.parent.parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

from boss_automation.database.job_repository import JobRepository  # noqa: E402
from boss_automation.database.recruiter_repository import RecruiterRepository  # noqa: E402
from boss_automation.parsers.job_list_parser import Job, JobStatus  # noqa: E402
from boss_automation.parsers.recruiter_profile_parser import RecruiterProfile  # noqa: E402
from routers import boss_jobs  # noqa: E402

FIXTURE_ROOT = project_root / "tests" / "fixtures" / "boss"


def _tree(label: str) -> dict[str, Any]:
    """Load a UI tree directly from a fixture JSON.

    We do not import ``tests._fixtures.loader`` here because the backend
    test directory has its own ``tests`` package that shadows the
    repository-root tests package on ``sys.path``.
    """
    path = FIXTURE_ROOT / "jobs_list" / f"{label}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["ui_tree"]


class _FakeAdbPort:
    """Tab-aware AdbPort used to drive the orchestrator from the API."""

    def __init__(self, trees_per_tab: dict[str, Sequence[dict[str, Any]]]) -> None:
        self._trees_per_tab = {k: list(v) for k, v in trees_per_tab.items()}
        self._current_tab: str | None = None
        self._idx_per_tab: dict[str, int] = {}

    async def start_app(self, package_name: str) -> None: ...

    async def get_state(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if self._current_tab is None:
            return {}, []
        queue = self._trees_per_tab.get(self._current_tab, [])
        if not queue:
            return {}, []
        idx = self._idx_per_tab.get(self._current_tab, 0)
        tree = queue[min(idx, len(queue) - 1)]
        self._idx_per_tab[self._current_tab] = idx + 1
        return copy.deepcopy(tree), []

    async def tap_by_text(self, text: str) -> bool:
        if text in self._trees_per_tab:
            self._current_tab = text
        return True

    async def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None: ...


@pytest.fixture()
def app(tmp_path: Path) -> FastAPI:
    db_path = str(tmp_path / "boss_test.db")
    boss_jobs.set_job_repository_factory(lambda: JobRepository(db_path))
    boss_jobs.set_recruiter_repository_factory(lambda: RecruiterRepository(db_path))
    fastapi_app = FastAPI()
    fastapi_app.include_router(boss_jobs.router)
    yield fastapi_app
    boss_jobs.reset_job_repository_factory()
    boss_jobs.reset_recruiter_repository_factory()
    boss_jobs.reset_adb_port_factory()


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def job_repo(app: FastAPI) -> JobRepository:
    return boss_jobs.get_job_repository()


@pytest.fixture()
def recruiter_repo(app: FastAPI) -> RecruiterRepository:
    return boss_jobs.get_recruiter_repository()


def _seed_recruiter(recruiter_repo: RecruiterRepository, serial: str = "EMU-1") -> int:
    return recruiter_repo.upsert(serial, RecruiterProfile(name="Alice", company="ACME"))


def _make_job(boss_id: str, status: JobStatus = JobStatus.OPEN) -> Job:
    return Job(
        boss_job_id=boss_id,
        title=f"Engineer {boss_id}",
        status=status,
        salary_min=20000,
        salary_max=40000,
        location="上海",
        experience="3-5年",
        education="本科",
    )


class TestListJobs:
    def test_returns_empty_for_unknown_recruiter(self, client: TestClient) -> None:
        response = client.get("/api/boss/jobs", params={"recruiter_id": 999})
        assert response.status_code == 200
        assert response.json() == {"jobs": [], "total": 0}

    def test_lists_all_jobs_for_recruiter(
        self, client: TestClient, job_repo: JobRepository, recruiter_repo: RecruiterRepository
    ) -> None:
        recruiter_id = _seed_recruiter(recruiter_repo)
        job_repo.upsert(recruiter_id, _make_job("J1"))
        job_repo.upsert(recruiter_id, _make_job("J2", JobStatus.CLOSED))

        response = client.get("/api/boss/jobs", params={"recruiter_id": recruiter_id})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2

    def test_filters_by_status(
        self, client: TestClient, job_repo: JobRepository, recruiter_repo: RecruiterRepository
    ) -> None:
        recruiter_id = _seed_recruiter(recruiter_repo)
        job_repo.upsert(recruiter_id, _make_job("J1"))
        job_repo.upsert(recruiter_id, _make_job("J2", JobStatus.CLOSED))

        response = client.get(
            "/api/boss/jobs",
            params={"recruiter_id": recruiter_id, "status_filter": "open"},
        )
        body = response.json()
        assert body["total"] == 1
        assert body["jobs"][0]["boss_job_id"] == "J1"


class TestGetJob:
    def test_returns_404_when_missing(self, client: TestClient) -> None:
        response = client.get("/api/boss/jobs/9999")
        assert response.status_code == 404

    def test_returns_job_when_found(
        self, client: TestClient, job_repo: JobRepository, recruiter_repo: RecruiterRepository
    ) -> None:
        recruiter_id = _seed_recruiter(recruiter_repo)
        row_id = job_repo.upsert(recruiter_id, _make_job("J-LOOKUP"))
        response = client.get(f"/api/boss/jobs/{row_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["boss_job_id"] == "J-LOOKUP"
        assert body["status"] == "open"


class TestSyncJobs:
    def test_returns_404_when_recruiter_missing(self, client: TestClient) -> None:
        boss_jobs.set_adb_port_factory(lambda _serial: _FakeAdbPort({"开放中": [_tree("open_tab")]}))
        response = client.post(
            "/api/boss/jobs/sync",
            json={"device_serial": "MISSING-DEVICE"},
        )
        assert response.status_code == 404

    def test_runs_sync_against_injected_adb_port(
        self,
        client: TestClient,
        recruiter_repo: RecruiterRepository,
        job_repo: JobRepository,
    ) -> None:
        recruiter_id = _seed_recruiter(recruiter_repo, "EMU-1")
        boss_jobs.set_adb_port_factory(
            lambda _serial: _FakeAdbPort(
                {
                    "开放中": [_tree("open_tab")],
                    "已关闭": [_tree("closed_tab")],
                }
            )
        )

        response = client.post(
            "/api/boss/jobs/sync",
            json={"device_serial": "EMU-1", "tabs": ["open", "closed"]},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["recruiter_id"] == recruiter_id
        assert body["total_jobs"] == 4
        per_tab = {entry["tab"]: entry["count"] for entry in body["per_tab"]}
        assert per_tab == {"open": 3, "closed": 1}
        # Persisted by the orchestrator
        assert len(job_repo.list_for_recruiter(recruiter_id)) == 4

    def test_default_tabs_are_open_and_closed(
        self,
        client: TestClient,
        recruiter_repo: RecruiterRepository,
    ) -> None:
        _seed_recruiter(recruiter_repo, "EMU-2")
        boss_jobs.set_adb_port_factory(
            lambda _serial: _FakeAdbPort(
                {
                    "开放中": [_tree("open_tab")],
                    "已关闭": [_tree("closed_tab")],
                }
            )
        )

        response = client.post("/api/boss/jobs/sync", json={"device_serial": "EMU-2"})
        body = response.json()
        per_tab = {entry["tab"]: entry["count"] for entry in body["per_tab"]}
        assert per_tab == {"open": 3, "closed": 1}


class TestFeatureFlag:
    def test_default_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BOSS_FEATURES_ENABLED", raising=False)
        assert boss_jobs.boss_features_enabled() is False

    def test_truthy_values_enable_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for value in ("1", "true", "TRUE", "yes", "on"):
            monkeypatch.setenv("BOSS_FEATURES_ENABLED", value)
            assert boss_jobs.boss_features_enabled() is True
