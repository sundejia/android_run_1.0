"""Tests for routers/boss_recruiters.py.

Use a stand-alone FastAPI app with only this router mounted so we
never trigger the heavy main.py initialization (DB migrations, log
upload, backup scheduler, etc.) during unit tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

src_path = backend_dir.parent.parent / "src"
sys.path.insert(0, str(src_path))

from boss_automation.database.recruiter_repository import RecruiterRepository  # noqa: E402
from boss_automation.parsers.recruiter_profile_parser import RecruiterProfile  # noqa: E402
from routers import boss_recruiters  # noqa: E402


@pytest.fixture()
def app(tmp_path: Path) -> FastAPI:
    db_path = str(tmp_path / "boss_test.db")
    boss_recruiters.set_repository_factory(lambda: RecruiterRepository(db_path))
    fastapi_app = FastAPI()
    fastapi_app.include_router(boss_recruiters.router)
    yield fastapi_app
    boss_recruiters.reset_repository_factory()


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def repo(app: FastAPI) -> RecruiterRepository:
    return boss_recruiters.get_repository()


class TestListRecruiters:
    def test_empty_database_returns_zero_total(self, client: TestClient) -> None:
        response = client.get("/api/boss/recruiters")
        assert response.status_code == 200
        assert response.json() == {"recruiters": [], "total": 0}

    def test_lists_existing_recruiters(self, client: TestClient, repo: RecruiterRepository) -> None:
        repo.upsert("EMU-1", RecruiterProfile(name="A", company="X"))
        repo.upsert("EMU-2", RecruiterProfile(name="B"))

        response = client.get("/api/boss/recruiters")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        serials = sorted(r["device_serial"] for r in body["recruiters"])
        assert serials == ["EMU-1", "EMU-2"]


class TestGetRecruiterBySerial:
    def test_returns_404_when_not_found(self, client: TestClient) -> None:
        response = client.get("/api/boss/recruiters/UNKNOWN")
        assert response.status_code == 404
        assert "UNKNOWN" in response.json()["detail"]

    def test_returns_recruiter_when_found(self, client: TestClient, repo: RecruiterRepository) -> None:
        repo.upsert(
            "EMU-7",
            RecruiterProfile(name="王经理", company="ACME", position="HRBP"),
        )
        response = client.get("/api/boss/recruiters/EMU-7")
        assert response.status_code == 200
        body = response.json()
        assert body["device_serial"] == "EMU-7"
        assert body["name"] == "王经理"
        assert body["company"] == "ACME"
        assert body["position"] == "HRBP"


class TestRefreshRecruiter:
    def test_rejects_empty_body(self, client: TestClient) -> None:
        response = client.post("/api/boss/recruiters/EMU-1/refresh", json={})
        assert response.status_code == 400
        assert "at least one" in response.json()["detail"].lower()

    def test_creates_recruiter_on_first_refresh(self, client: TestClient, repo: RecruiterRepository) -> None:
        response = client.post(
            "/api/boss/recruiters/EMU-9/refresh",
            json={"name": "张猎头", "company": "北辰科技"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["device_serial"] == "EMU-9"
        assert body["name"] == "张猎头"
        assert body["company"] == "北辰科技"
        # Persisted
        record = repo.get_by_serial("EMU-9")
        assert record is not None
        assert record.name == "张猎头"

    def test_updates_existing_recruiter(self, client: TestClient, repo: RecruiterRepository) -> None:
        repo.upsert("EMU-3", RecruiterProfile(name="OLD", company="OLD-CO"))

        response = client.post(
            "/api/boss/recruiters/EMU-3/refresh",
            json={"name": "NEW", "company": "NEW-CO", "position": "HRBP"},
        )

        assert response.status_code == 200
        record = repo.get_by_serial("EMU-3")
        assert record is not None
        assert record.name == "NEW"
        assert record.company == "NEW-CO"
        assert record.position == "HRBP"

    def test_blank_name_falls_back_to_placeholder(self, client: TestClient, repo: RecruiterRepository) -> None:
        response = client.post(
            "/api/boss/recruiters/EMU-X/refresh",
            json={"name": "   ", "company": "X"},
        )
        assert response.status_code == 200
        record = repo.get_by_serial("EMU-X")
        assert record is not None
        assert record.name == "未命名招聘者"


class TestFeatureFlag:
    def test_feature_flag_off_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BOSS_FEATURES_ENABLED", raising=False)
        assert boss_recruiters.boss_features_enabled() is False

    def test_feature_flag_on_when_set_truthy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for value in ("1", "true", "TRUE", "yes", "on"):
            monkeypatch.setenv("BOSS_FEATURES_ENABLED", value)
            assert boss_recruiters.boss_features_enabled() is True

    def test_feature_flag_off_for_non_truthy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for value in ("0", "false", "no", "off", ""):
            monkeypatch.setenv("BOSS_FEATURES_ENABLED", value)
            assert boss_recruiters.boss_features_enabled() is False
