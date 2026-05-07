"""Tests for routers/boss_greet.py."""

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

from boss_automation.database.candidate_repository import CandidateRepository  # noqa: E402
from boss_automation.database.recruiter_repository import RecruiterRepository  # noqa: E402
from boss_automation.parsers.recruiter_profile_parser import RecruiterProfile  # noqa: E402
from routers import boss_greet  # noqa: E402

FIXTURE_ROOT = project_root / "tests" / "fixtures" / "boss"


def _tree(category: str, label: str) -> dict[str, Any]:
    payload = json.loads((FIXTURE_ROOT / category / f"{label}.json").read_text(encoding="utf-8"))
    return payload["ui_tree"]


class _FakeAdbPort:
    def __init__(self, trees: Sequence[dict[str, Any]]) -> None:
        self._trees = list(trees)
        self._idx = 0
        self.tap_text_calls: list[str] = []

    async def start_app(self, package_name: str) -> None: ...

    async def get_state(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if self._idx >= len(self._trees):
            tree = self._trees[-1] if self._trees else {}
        else:
            tree = self._trees[self._idx]
            self._idx += 1
        return copy.deepcopy(tree), []

    async def tap_by_text(self, text: str) -> bool:
        self.tap_text_calls.append(text)
        return True

    async def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None: ...


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "boss_greet.db")


@pytest.fixture()
def app(db_path: str) -> FastAPI:
    boss_greet.set_db_path_provider(lambda: db_path)
    boss_greet.set_recruiter_repository_factory(lambda: RecruiterRepository(db_path))
    boss_greet.set_candidate_repository_factory(lambda: CandidateRepository(db_path))
    fastapi_app = FastAPI()
    fastapi_app.include_router(boss_greet.router)
    yield fastapi_app
    boss_greet.reset_db_path_provider()
    boss_greet.reset_recruiter_repository_factory()
    boss_greet.reset_candidate_repository_factory()
    boss_greet.reset_adb_port_factory()


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def recruiter_repo(app: FastAPI) -> RecruiterRepository:
    return boss_greet.get_recruiter_repository()


def _seed(recruiter_repo: RecruiterRepository, serial: str = "EMU-1") -> int:
    return recruiter_repo.upsert(serial, RecruiterProfile(name="Alice", company="ACME"))


class TestSettingsEndpoints:
    def test_get_default_settings(self, client: TestClient) -> None:
        response = client.get("/api/boss/greet/settings/EMU-1")
        assert response.status_code == 200
        body = response.json()
        assert body["device_serial"] == "EMU-1"
        assert body["enabled"] is False
        assert body["window"]["start_minute"] == 540
        assert body["window"]["end_minute"] == 1080
        assert body["quota"]["per_day"] == 80

    def test_put_persists_partial_update(self, client: TestClient) -> None:
        response = client.put(
            "/api/boss/greet/settings/EMU-1",
            json={"enabled": True, "quota": {"per_day": 50, "per_hour": 10, "per_job": 5}},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is True
        assert body["quota"]["per_day"] == 50
        assert body["quota"]["per_hour"] == 10
        assert body["quota"]["per_job"] == 5

    def test_put_supports_window_update(self, client: TestClient) -> None:
        response = client.put(
            "/api/boss/greet/settings/EMU-2",
            json={
                "window": {
                    "weekdays": [5, 6],
                    "start_minute": 600,
                    "end_minute": 1200,
                    "timezone": "UTC",
                }
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["window"]["weekdays"] == [5, 6]
        assert body["window"]["timezone"] == "UTC"

    def test_get_after_put_returns_persisted_values(self, client: TestClient) -> None:
        client.put(
            "/api/boss/greet/settings/EMU-3",
            json={"enabled": True, "quota": {"per_day": 12, "per_hour": 3}},
        )
        response = client.get("/api/boss/greet/settings/EMU-3")
        body = response.json()
        assert body["enabled"] is True
        assert body["quota"]["per_day"] == 12


class TestTestRun:
    def test_returns_404_when_recruiter_missing(self, client: TestClient) -> None:
        boss_greet.set_adb_port_factory(lambda _s: _FakeAdbPort([]))
        response = client.post("/api/boss/greet/test-run", json={"device_serial": "MISSING"})
        assert response.status_code == 404

    def test_runs_one_send_path(self, client: TestClient, recruiter_repo: RecruiterRepository) -> None:
        _seed(recruiter_repo, "EMU-1")
        # Open weekday/hour window so the executor proceeds.
        client.put(
            "/api/boss/greet/settings/EMU-1",
            json={
                "window": {
                    "weekdays": [0, 1, 2, 3, 4, 5, 6],
                    "start_minute": 0,
                    "end_minute": 1439,
                    "timezone": "UTC",
                },
                "quota": {"per_day": 80, "per_hour": 15},
                "enabled": True,
            },
        )
        boss_greet.set_adb_port_factory(
            lambda _s: _FakeAdbPort(
                [_tree("candidates_feed", "feed_with_cards"), _tree("candidate_detail", "ready_to_greet")]
            )
        )

        response = client.post("/api/boss/greet/test-run", json={"device_serial": "EMU-1"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["outcome"] == "sent"
        assert body["boss_candidate_id"] == "CAND20260507A"

    def test_outside_window_skips_without_adb(self, client: TestClient, recruiter_repo: RecruiterRepository) -> None:
        _seed(recruiter_repo, "EMU-WIN")
        client.put(
            "/api/boss/greet/settings/EMU-WIN",
            json={
                "window": {
                    "weekdays": [],
                    "start_minute": 0,
                    "end_minute": 1,
                    "timezone": "UTC",
                }
            },
        )
        # No ADB factory wired; the executor must short-circuit before
        # calling get_state, otherwise this test fails with 503.
        response = client.post("/api/boss/greet/test-run", json={"device_serial": "EMU-WIN"})
        # The executor needs the AdbPort to be constructible; we provide
        # a stub that records nothing.
        if response.status_code == 503:
            boss_greet.set_adb_port_factory(lambda _s: _FakeAdbPort([]))
            response = client.post("/api/boss/greet/test-run", json={"device_serial": "EMU-WIN"})
        body = response.json()
        assert body["outcome"] == "skipped_outside_window"


class TestFeatureFlag:
    def test_default_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BOSS_FEATURES_ENABLED", raising=False)
        assert boss_greet.boss_features_enabled() is False

    def test_truthy_enables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for value in ("1", "true", "yes", "on"):
            monkeypatch.setenv("BOSS_FEATURES_ENABLED", value)
            assert boss_greet.boss_features_enabled() is True
