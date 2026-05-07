"""Tests for routers/boss_monitoring.py.

Drives the monitoring summary endpoint against a seeded SQLite DB so
that frontend/dashboard regressions are caught at the API boundary,
not at the presentation layer.
"""

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
from boss_automation.database.followup_attempts_repository import (  # noqa: E402
    FollowupAttemptsRepository,
)
from boss_automation.database.job_repository import JobRepository  # noqa: E402
from boss_automation.database.message_repository import MessageRepository  # noqa: E402
from boss_automation.database.recruiter_repository import RecruiterRepository  # noqa: E402
from boss_automation.parsers.candidate_card_parser import CandidateCard  # noqa: E402
from boss_automation.parsers.job_list_parser import Job, JobStatus  # noqa: E402
from boss_automation.parsers.recruiter_profile_parser import RecruiterProfile  # noqa: E402
from routers import boss_monitoring  # noqa: E402

NOW = datetime(2026, 5, 7, 18, 0, 0, tzinfo=UTC)


def _job(job_id: str, title: str, status: JobStatus) -> Job:
    return Job(
        boss_job_id=job_id,
        title=title,
        status=status,
        salary_min=None,
        salary_max=None,
        location=None,
        education=None,
        experience=None,
    )


def _card(boss_id: str, name: str) -> CandidateCard:
    return CandidateCard(
        boss_candidate_id=boss_id,
        name=name,
        age=None,
        gender=None,
        education=None,
        experience_years=None,
        current_company=None,
        current_position=None,
    )


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "boss_monitoring_api.db")


@pytest.fixture()
def app(db_path: str) -> FastAPI:
    boss_monitoring.set_db_path_provider(lambda: db_path)
    boss_monitoring.set_clock(lambda: NOW)
    fastapi_app = FastAPI()
    fastapi_app.include_router(boss_monitoring.router)
    yield fastapi_app
    boss_monitoring.reset_db_path_provider()
    boss_monitoring.reset_clock()


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def seeded(db_path: str) -> dict:
    """Seed two recruiters with overlapping but distinct counts.

    Recruiter A (EMU-A):
      - 2 open jobs, 1 closed job
      - 1 candidate (status=greeted), 1 silent eligible (last out 4d ago)
      - 1 sent attempt within last 24h, 1 cancelled within last 24h

    Recruiter B (EMU-B): no jobs, no candidates, no attempts.
    """
    recruiter_repo = RecruiterRepository(db_path)
    rid_a = recruiter_repo.upsert("EMU-A", RecruiterProfile(name="Alice", company="A", position="HR"))
    rid_b = recruiter_repo.upsert("EMU-B", RecruiterProfile(name="Bob", company="B", position="HR"))

    job_repo = JobRepository(db_path)
    job_repo.upsert(rid_a, _job("J1", "iOS Engineer", JobStatus.OPEN))
    job_repo.upsert(rid_a, _job("J2", "Backend Engineer", JobStatus.OPEN))
    job_repo.upsert(rid_a, _job("J3", "Designer", JobStatus.CLOSED))

    cand_repo = CandidateRepository(db_path)
    cand_a1 = cand_repo.upsert_from_card(rid_a, _card("CAND-A1", "李雷"))
    cand_repo.set_status(rid_a, "CAND-A1", "greeted")
    cand_a2 = cand_repo.upsert_from_card(rid_a, _card("CAND-A2", "韩梅梅"))

    conv_repo = ConversationRepository(db_path)
    conv_a1 = conv_repo.upsert(recruiter_id=rid_a, candidate_id=cand_a1)
    conv_a2 = conv_repo.upsert(recruiter_id=rid_a, candidate_id=cand_a2)

    msg_repo = MessageRepository(db_path)
    msg_repo.insert(
        conversation_id=conv_a1,
        direction="out",
        content_type="text",
        text="hi a1",
        sent_at=NOW - timedelta(hours=2),
        sent_by="auto",
    )
    msg_repo.insert(
        conversation_id=conv_a2,
        direction="out",
        content_type="text",
        text="hi a2",
        sent_at=NOW - timedelta(days=4),
        sent_by="auto",
    )

    attempts_repo = FollowupAttemptsRepository(db_path)
    aid_sent = attempts_repo.append_pending(
        candidate_id=cand_a1,
        conversation_id=conv_a1,
        scheduled_at=NOW - timedelta(hours=3),
    )
    attempts_repo.mark_sent(aid_sent, sent_at=NOW - timedelta(hours=2))

    aid_cancel = attempts_repo.append_pending(
        candidate_id=cand_a2,
        conversation_id=conv_a2,
        scheduled_at=NOW - timedelta(hours=5),
    )
    attempts_repo.mark_cancelled(aid_cancel, reason="dry_run")

    return {
        "rid_a": rid_a,
        "rid_b": rid_b,
        "cand_a1": cand_a1,
        "cand_a2": cand_a2,
    }


def test_summary_returns_recruiter_blocks_with_counts(
    client: TestClient,
    seeded: dict,
) -> None:
    response = client.get("/api/boss/monitoring/summary")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "generated_at_iso" in body
    by_serial = {r["device_serial"]: r for r in body["recruiters"]}
    assert set(by_serial) == {"EMU-A", "EMU-B"}

    a = by_serial["EMU-A"]
    assert a["recruiter_id"] == seeded["rid_a"]
    assert a["name"] == "Alice"
    assert a["jobs_by_status"] == {"open": 2, "closed": 1}
    assert a["candidates_by_status"] == {"greeted": 1, "new": 1}
    assert a["greet_attempts_last_24h"] == {"sent": 0, "cancelled": 0, "failed": 0}
    assert a["reengagement_attempts_last_24h"] == {"sent": 1, "cancelled": 1, "failed": 0}
    assert a["silent_candidates_eligible"] == 1


def test_summary_block_for_empty_recruiter_is_zeroed(
    client: TestClient,
    seeded: dict,
) -> None:
    body = client.get("/api/boss/monitoring/summary").json()
    by_serial = {r["device_serial"]: r for r in body["recruiters"]}
    b = by_serial["EMU-B"]
    assert b["jobs_by_status"] == {}
    assert b["candidates_by_status"] == {}
    assert b["greet_attempts_last_24h"] == {"sent": 0, "cancelled": 0, "failed": 0}
    assert b["reengagement_attempts_last_24h"] == {"sent": 0, "cancelled": 0, "failed": 0}
    assert b["silent_candidates_eligible"] == 0


def test_summary_with_no_recruiters_returns_empty_list(
    client: TestClient,
    db_path: str,
) -> None:
    body = client.get("/api/boss/monitoring/summary").json()
    assert body["recruiters"] == []


def test_summary_window_is_rolling_24h(
    client: TestClient,
    db_path: str,
) -> None:
    rid = RecruiterRepository(db_path).upsert(
        "EMU-OLD",
        RecruiterProfile(name="Old", company="C", position="HR"),
    )
    cand = CandidateRepository(db_path).upsert_from_card(rid, _card("CAND-OLD", "Old"))
    conv = ConversationRepository(db_path).upsert(recruiter_id=rid, candidate_id=cand)
    repo = FollowupAttemptsRepository(db_path)
    aid = repo.append_pending(
        candidate_id=cand,
        conversation_id=conv,
        scheduled_at=NOW - timedelta(days=3),
    )
    repo.mark_sent(aid, sent_at=NOW - timedelta(days=3))

    body = client.get("/api/boss/monitoring/summary").json()
    by_serial = {r["device_serial"]: r for r in body["recruiters"]}
    old = by_serial["EMU-OLD"]
    assert old["reengagement_attempts_last_24h"] == {"sent": 0, "cancelled": 0, "failed": 0}
