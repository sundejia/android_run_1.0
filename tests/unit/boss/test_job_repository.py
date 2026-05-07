"""TDD tests for boss_automation/database/job_repository.py."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from boss_automation.database.job_repository import JobRecord, JobRepository
from boss_automation.database.recruiter_repository import RecruiterRepository
from boss_automation.parsers.job_list_parser import Job, JobStatus
from boss_automation.parsers.recruiter_profile_parser import RecruiterProfile


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "boss.db"


@pytest.fixture()
def recruiter_id(db_path: Path) -> int:
    repo = RecruiterRepository(db_path)
    return repo.upsert(
        "EMU-1",
        RecruiterProfile(name="Alice", company="ACME", position="HRBP"),
    )


@pytest.fixture()
def job_repo(db_path: Path) -> JobRepository:
    return JobRepository(db_path)


def _job(job_id: str, status: JobStatus = JobStatus.OPEN, title: str = "Backend Engineer") -> Job:
    return Job(
        boss_job_id=job_id,
        title=title,
        status=status,
        salary_min=20000,
        salary_max=40000,
        location="上海",
        education="本科",
        experience="3-5年",
    )


class TestUpsertJob:
    def test_inserts_new_job_returns_row_id(self, job_repo: JobRepository, recruiter_id: int) -> None:
        row_id = job_repo.upsert(recruiter_id, _job("JD001"))
        assert row_id > 0

    def test_idempotent_upsert_returns_same_row(self, job_repo: JobRepository, recruiter_id: int) -> None:
        first = job_repo.upsert(recruiter_id, _job("JD002"))
        second = job_repo.upsert(recruiter_id, _job("JD002"))
        assert first == second

    def test_upsert_updates_status_and_metadata(self, job_repo: JobRepository, recruiter_id: int) -> None:
        job_repo.upsert(recruiter_id, _job("JD003", status=JobStatus.OPEN))
        job_repo.upsert(
            recruiter_id,
            _job("JD003", status=JobStatus.CLOSED, title="Backend Engineer (closed)"),
        )
        rows = job_repo.list_for_recruiter(recruiter_id)
        assert len(rows) == 1
        assert rows[0].status == JobStatus.CLOSED
        assert rows[0].title == "Backend Engineer (closed)"

    def test_unique_per_recruiter_not_global(self, db_path: Path, job_repo: JobRepository, recruiter_id: int) -> None:
        other_recruiter = RecruiterRepository(db_path).upsert("EMU-2", RecruiterProfile(name="Bob"))
        a = job_repo.upsert(recruiter_id, _job("JD-SHARED"))
        b = job_repo.upsert(other_recruiter, _job("JD-SHARED"))
        assert a != b

    def test_upsert_sets_last_seen_at(self, job_repo: JobRepository, recruiter_id: int) -> None:
        row_id = job_repo.upsert(recruiter_id, _job("JD-TS"))
        with sqlite3.connect(job_repo.db_path) as conn:
            row = conn.execute("SELECT last_seen_at FROM jobs WHERE id = ?", (row_id,)).fetchone()
        assert row[0] is not None


class TestUpsertManyJobs:
    def test_persists_full_batch(self, job_repo: JobRepository, recruiter_id: int) -> None:
        batch = [_job(f"JD{i:03d}") for i in range(5)]
        ids = job_repo.upsert_many(recruiter_id, batch)
        assert len(ids) == 5
        assert len(set(ids)) == 5
        assert len(job_repo.list_for_recruiter(recruiter_id)) == 5

    def test_empty_batch_returns_empty_list(self, job_repo: JobRepository, recruiter_id: int) -> None:
        assert job_repo.upsert_many(recruiter_id, []) == []


class TestListForRecruiter:
    def test_filters_by_status(self, job_repo: JobRepository, recruiter_id: int) -> None:
        job_repo.upsert(recruiter_id, _job("OPEN-1", status=JobStatus.OPEN))
        job_repo.upsert(recruiter_id, _job("OPEN-2", status=JobStatus.OPEN))
        job_repo.upsert(recruiter_id, _job("CLOSED-1", status=JobStatus.CLOSED))
        opens = job_repo.list_for_recruiter(recruiter_id, status=JobStatus.OPEN)
        closeds = job_repo.list_for_recruiter(recruiter_id, status=JobStatus.CLOSED)
        assert {j.boss_job_id for j in opens} == {"OPEN-1", "OPEN-2"}
        assert {j.boss_job_id for j in closeds} == {"CLOSED-1"}

    def test_returns_empty_for_unknown_recruiter(self, job_repo: JobRepository) -> None:
        assert job_repo.list_for_recruiter(99999) == []

    def test_returns_typed_records(self, job_repo: JobRepository, recruiter_id: int) -> None:
        job_repo.upsert(recruiter_id, _job("X1"))
        rows = job_repo.list_for_recruiter(recruiter_id)
        assert all(isinstance(r, JobRecord) for r in rows)


class TestGetByBossJobId:
    def test_returns_existing_record(self, job_repo: JobRepository, recruiter_id: int) -> None:
        job_repo.upsert(recruiter_id, _job("LOOKUP-1"))
        rec = job_repo.get_by_boss_job_id(recruiter_id, "LOOKUP-1")
        assert rec is not None
        assert rec.boss_job_id == "LOOKUP-1"

    def test_returns_none_for_unknown(self, job_repo: JobRepository, recruiter_id: int) -> None:
        assert job_repo.get_by_boss_job_id(recruiter_id, "missing") is None


class TestSchemaAutoEnsure:
    def test_does_not_require_explicit_ensure_schema(self, db_path: Path) -> None:
        # Pure construction must not raise on a fresh DB path.
        repo = JobRepository(db_path)
        assert repo.list_for_recruiter(1) == []
