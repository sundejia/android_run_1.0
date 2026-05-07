"""TDD tests for boss_automation/database/template_repository.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from boss_automation.database.template_repository import (
    TemplateRecord,
    TemplateRepository,
)


@pytest.fixture
def repo(tmp_path: Path) -> TemplateRepository:
    return TemplateRepository(tmp_path / "boss_test.db")


def test_insert_and_list(repo: TemplateRepository) -> None:
    template_id = repo.insert(
        name="default-reply",
        scenario="reply",
        content="您好 {name}",
        is_default=True,
    )
    assert template_id > 0
    rows = repo.list_by_scenario("reply")
    assert len(rows) == 1
    assert isinstance(rows[0], TemplateRecord)
    assert rows[0].name == "default-reply"
    assert rows[0].is_default is True


def test_get_default_returns_default_for_scenario(
    repo: TemplateRepository,
) -> None:
    repo.insert(name="alt", scenario="reply", content="x", is_default=False)
    repo.insert(name="def", scenario="reply", content="y", is_default=True)
    record = repo.get_default("reply")
    assert record is not None
    assert record.name == "def"


def test_get_default_returns_none_when_no_default(
    repo: TemplateRepository,
) -> None:
    repo.insert(name="a", scenario="reply", content="x", is_default=False)
    assert repo.get_default("reply") is None


def test_unique_constraint_on_name_and_scenario(
    repo: TemplateRepository,
) -> None:
    repo.insert(name="x", scenario="reply", content="a")
    with pytest.raises(Exception):  # noqa: B017
        repo.insert(name="x", scenario="reply", content="b")


def test_update_changes_content_and_default_flag(
    repo: TemplateRepository,
) -> None:
    template_id = repo.insert(name="x", scenario="reply", content="old", is_default=False)
    repo.update(template_id, content="new", is_default=True)
    record = repo.get_by_id(template_id)
    assert record is not None
    assert record.content == "new"
    assert record.is_default is True


def test_delete_removes_template(repo: TemplateRepository) -> None:
    template_id = repo.insert(name="x", scenario="reply", content="a")
    assert repo.delete(template_id) is True
    assert repo.get_by_id(template_id) is None
    assert repo.delete(template_id) is False


def test_invalid_scenario_rejected(repo: TemplateRepository) -> None:
    with pytest.raises(ValueError):
        repo.insert(name="x", scenario="invalid", content="y")


def test_record_is_immutable() -> None:
    from dataclasses import FrozenInstanceError

    record = TemplateRecord(id=1, name="x", scenario="reply", content="y", is_default=False)
    with pytest.raises((AttributeError, FrozenInstanceError)):
        record.content = "z"  # type: ignore[misc]
