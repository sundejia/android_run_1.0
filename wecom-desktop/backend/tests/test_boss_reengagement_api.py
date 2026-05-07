"""Tests for routers/boss_reengagement.py."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

project_root = backend_dir.parent.parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

from boss_automation.database.candidate_repository import CandidateRepository  # noqa: E402
from boss_automation.database.conversation_repository import ConversationRepository  # noqa: E402
from boss_automation.database.message_repository import MessageRepository  # noqa: E402
from boss_automation.database.recruiter_repository import RecruiterRepository  # noqa: E402
from boss_automation.parsers.candidate_card_parser import CandidateCard  # noqa: E402
from boss_automation.parsers.recruiter_profile_parser import RecruiterProfile  # noqa: E402
from routers import boss_reengagement  # noqa: E402


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "boss_reengage_api.db")


@pytest.fixture()
def app(db_path: str) -> FastAPI:
    boss_reengagement.set_db_path_provider(lambda: db_path)
    boss_reengagement.set_blacklist_check(lambda _: _async(False))
    boss_reengagement.set_clock(lambda: datetime(2026, 5, 7, 18, 0, 0, tzinfo=UTC))
    fastapi_app = FastAPI()
    fastapi_app.include_router(boss_reengagement.router)
    yield fastapi_app
    boss_reengagement.reset_db_path_provider()
    boss_reengagement.reset_blacklist_check()
    boss_reengagement.reset_clock()


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def seed_silent_candidate(db_path: str) -> tuple[int, int, int, str]:
    rid = RecruiterRepository(db_path).upsert("EMU-1", RecruiterProfile(name="X", company="Co", position="HR"))
    cand = CandidateRepository(db_path).upsert_from_card(
        rid,
        CandidateCard(
            boss_candidate_id="CAND-A",
            name="李雷",
            age=None,
            gender=None,
            education=None,
            experience_years=None,
            current_company=None,
            current_position=None,
        ),
    )
    conv = ConversationRepository(db_path).upsert(recruiter_id=rid, candidate_id=cand)
    MessageRepository(db_path).insert(
        conversation_id=conv,
        direction="out",
        content_type="text",
        text="hi",
        sent_at=datetime(2026, 5, 7, 18, 0, 0, tzinfo=UTC) - timedelta(days=4),
        sent_by="auto",
    )
    return rid, cand, conv, "CAND-A"


def test_default_settings_returned_when_unsaved(client: TestClient) -> None:
    response = client.get("/api/boss/reengagement/settings/EMU-X")
    assert response.status_code == 200
    body = response.json()
    assert body["device_serial"] == "EMU-X"
    assert body["silent_for_days"] == 3
    assert body["cooldown_days"] == 7


def test_update_then_get_persists(client: TestClient) -> None:
    response = client.put(
        "/api/boss/reengagement/settings/EMU-X",
        json={"silent_for_days": 5, "daily_cap": 30},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["silent_for_days"] == 5
    assert body["daily_cap"] == 30

    follow = client.get("/api/boss/reengagement/settings/EMU-X").json()
    assert follow["silent_for_days"] == 5
    assert follow["cooldown_days"] == 7


def test_scan_returns_eligible_candidate(
    client: TestClient,
    seed_silent_candidate: tuple[int, int, int, str],
) -> None:
    rid, _cand, _conv, _ = seed_silent_candidate
    response = client.post(
        "/api/boss/reengagement/scan",
        json={"device_serial": "EMU-1"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["recruiter_id"] == rid
    assert len(body["eligible"]) == 1
    assert body["eligible"][0]["boss_candidate_id"] == "CAND-A"


def test_scan_returns_404_when_recruiter_unknown(client: TestClient) -> None:
    response = client.post(
        "/api/boss/reengagement/scan",
        json={"device_serial": "EMU-MISSING"},
    )
    assert response.status_code == 404


def test_run_dry_returns_dry_run(
    client: TestClient,
    seed_silent_candidate: tuple[int, int, int, str],
) -> None:
    response = client.post(
        "/api/boss/reengagement/run",
        json={"device_serial": "EMU-1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "dry_run"
    assert body["boss_candidate_id"] == "CAND-A"
    assert body["attempt_id"] is not None


def test_run_skips_when_blacklisted(
    client: TestClient,
    seed_silent_candidate: tuple[int, int, int, str],
) -> None:
    boss_reengagement.set_blacklist_check(lambda _: _async(True))
    response = client.post(
        "/api/boss/reengagement/run",
        json={"device_serial": "EMU-1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "skipped_blacklisted"


def test_run_returns_no_eligible_when_nothing_to_do(client: TestClient) -> None:
    RecruiterRepository(boss_reengagement.get_db_path()).upsert(
        "EMU-EMPTY",
        RecruiterProfile(name="Empty", company="C", position="HR"),
    )
    response = client.post(
        "/api/boss/reengagement/run",
        json={"device_serial": "EMU-EMPTY"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "no_eligible"


async def _async(value: bool) -> bool:
    return value
