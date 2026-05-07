"""TDD tests for boss_automation/database/recruiter_repository.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from boss_automation.database.recruiter_repository import (
    RecruiterRecord,
    RecruiterRepository,
)
from boss_automation.database.schema import ensure_schema
from boss_automation.parsers.recruiter_profile_parser import RecruiterProfile


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "boss.db")
    ensure_schema(path)
    return path


class TestUpsert:
    def test_inserts_new_recruiter_returns_row_id(self, db_path: str) -> None:
        repo = RecruiterRepository(db_path)
        profile = RecruiterProfile(name="王经理", company="ACME", position="HRBP")

        row_id = repo.upsert("EMU-1", profile)

        assert isinstance(row_id, int)
        assert row_id > 0

    def test_idempotent_on_same_serial(self, db_path: str) -> None:
        repo = RecruiterRepository(db_path)
        first = repo.upsert("EMU-1", RecruiterProfile(name="A", company="X"))
        second = repo.upsert("EMU-1", RecruiterProfile(name="A", company="X"))
        assert first == second

    def test_updates_existing_recruiter_in_place(self, db_path: str) -> None:
        repo = RecruiterRepository(db_path)
        repo.upsert("EMU-1", RecruiterProfile(name="A", company="X"))

        repo.upsert("EMU-1", RecruiterProfile(name="B", company="Y", position="HRBP"))

        record = repo.get_by_serial("EMU-1")
        assert record is not None
        assert record.name == "B"
        assert record.company == "Y"
        assert record.position == "HRBP"

    def test_separate_serials_create_separate_rows(self, db_path: str) -> None:
        repo = RecruiterRepository(db_path)
        a = repo.upsert("EMU-1", RecruiterProfile(name="A"))
        b = repo.upsert("EMU-2", RecruiterProfile(name="B"))
        assert a != b
        assert len(repo.list_all()) == 2


class TestGetBySerial:
    def test_returns_none_for_unknown_serial(self, db_path: str) -> None:
        assert RecruiterRepository(db_path).get_by_serial("NOPE") is None

    def test_round_trip(self, db_path: str) -> None:
        repo = RecruiterRepository(db_path)
        profile = RecruiterProfile(name="王经理", company="ACME", position="HRBP", avatar_path="/a/b.png")
        repo.upsert("EMU-7", profile)

        record = repo.get_by_serial("EMU-7")
        assert record == RecruiterRecord(
            id=record.id if record else 0,  # id is auto-assigned
            device_serial="EMU-7",
            name="王经理",
            company="ACME",
            position="HRBP",
            avatar_path="/a/b.png",
        )


class TestListAll:
    def test_empty_database_returns_empty_list(self, db_path: str) -> None:
        assert RecruiterRepository(db_path).list_all() == []

    def test_returns_records_sorted_by_serial(self, db_path: str) -> None:
        repo = RecruiterRepository(db_path)
        repo.upsert("EMU-3", RecruiterProfile(name="C"))
        repo.upsert("EMU-1", RecruiterProfile(name="A"))
        repo.upsert("EMU-2", RecruiterProfile(name="B"))

        records = repo.list_all()
        assert [r.device_serial for r in records] == ["EMU-1", "EMU-2", "EMU-3"]
        assert [r.name for r in records] == ["A", "B", "C"]


class TestRepositoryEnsuresSchema:
    def test_works_against_freshly_created_db(self, tmp_path: Path) -> None:
        # Repository must auto-ensure schema so callers don't have to
        # remember the order of operations.
        path = str(tmp_path / "fresh.db")
        repo = RecruiterRepository(path)
        repo.upsert("EMU-1", RecruiterProfile(name="A"))
        assert repo.get_by_serial("EMU-1") is not None
