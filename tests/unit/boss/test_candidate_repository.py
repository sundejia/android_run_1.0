"""TDD tests for boss_automation/database/candidate_repository.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from boss_automation.database.candidate_repository import (
    CandidateRecord,
    CandidateRepository,
)
from boss_automation.database.recruiter_repository import RecruiterRepository
from boss_automation.parsers.candidate_card_parser import CandidateCard
from boss_automation.parsers.recruiter_profile_parser import RecruiterProfile


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "boss.db"


@pytest.fixture()
def recruiter_id(db_path: Path) -> int:
    return RecruiterRepository(db_path).upsert("EMU-1", RecruiterProfile(name="Alice"))


@pytest.fixture()
def repo(db_path: Path) -> CandidateRepository:
    return CandidateRepository(db_path)


def _card(boss_id: str = "C1", **overrides) -> CandidateCard:
    base: dict = {
        "boss_candidate_id": boss_id,
        "name": f"name-{boss_id}",
        "gender": "男",
        "age": 28,
        "education": "本科",
        "experience_years": 5,
        "current_position": "工程师",
        "current_company": "ACME",
        "matched_job_title": "Backend",
    }
    base.update(overrides)
    return CandidateCard(**base)  # type: ignore[arg-type]


class TestUpsertFromCard:
    def test_inserts_new_candidate(self, repo: CandidateRepository, recruiter_id: int) -> None:
        row_id = repo.upsert_from_card(recruiter_id, _card("C-NEW"))
        assert row_id > 0

    def test_idempotent(self, repo: CandidateRepository, recruiter_id: int) -> None:
        a = repo.upsert_from_card(recruiter_id, _card("C-IDEMP"))
        b = repo.upsert_from_card(recruiter_id, _card("C-IDEMP"))
        assert a == b

    def test_unique_per_recruiter(self, db_path: Path, repo: CandidateRepository, recruiter_id: int) -> None:
        other = RecruiterRepository(db_path).upsert("EMU-2", RecruiterProfile(name="Bob"))
        a = repo.upsert_from_card(recruiter_id, _card("C-SHARED"))
        b = repo.upsert_from_card(other, _card("C-SHARED"))
        assert a != b

    def test_updates_metadata_on_repeat(self, repo: CandidateRepository, recruiter_id: int) -> None:
        repo.upsert_from_card(recruiter_id, _card("C-UPD", name="OLD"))
        repo.upsert_from_card(recruiter_id, _card("C-UPD", name="NEW"))
        rec = repo.get_by_boss_candidate_id(recruiter_id, "C-UPD")
        assert rec is not None
        assert rec.name == "NEW"


class TestStatusUpdate:
    def test_mark_status(self, repo: CandidateRepository, recruiter_id: int) -> None:
        repo.upsert_from_card(recruiter_id, _card("C-S1"))
        repo.set_status(recruiter_id, "C-S1", "greeted")
        rec = repo.get_by_boss_candidate_id(recruiter_id, "C-S1")
        assert rec is not None
        assert rec.status == "greeted"

    def test_invalid_status_raises(self, repo: CandidateRepository, recruiter_id: int) -> None:
        repo.upsert_from_card(recruiter_id, _card("C-S2"))
        with pytest.raises(ValueError):
            repo.set_status(recruiter_id, "C-S2", "totally_made_up")


class TestQueries:
    def test_list_for_recruiter_returns_typed_records(self, repo: CandidateRepository, recruiter_id: int) -> None:
        repo.upsert_from_card(recruiter_id, _card("C-A"))
        repo.upsert_from_card(recruiter_id, _card("C-B"))
        records = repo.list_for_recruiter(recruiter_id)
        assert {r.boss_candidate_id for r in records} == {"C-A", "C-B"}
        assert all(isinstance(r, CandidateRecord) for r in records)

    def test_get_by_boss_candidate_id_returns_none_when_missing(
        self, repo: CandidateRepository, recruiter_id: int
    ) -> None:
        assert repo.get_by_boss_candidate_id(recruiter_id, "missing") is None

    def test_count_by_status(self, repo: CandidateRepository, recruiter_id: int) -> None:
        for i in range(3):
            repo.upsert_from_card(recruiter_id, _card(f"NEW-{i}"))
        for i in range(2):
            repo.upsert_from_card(recruiter_id, _card(f"GR-{i}"))
            repo.set_status(recruiter_id, f"GR-{i}", "greeted")
        counts = repo.count_by_status(recruiter_id)
        assert counts.get("new") == 3
        assert counts.get("greeted") == 2
