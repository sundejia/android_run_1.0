"""TDD tests for boss_automation/parsers/job_list_parser.py."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from boss_automation.parsers.job_list_parser import (
    Job,
    JobStatus,
    detect_active_tab,
    is_empty_state,
    parse_job_list,
    parse_salary_range,
)
from tests._fixtures.loader import load_fixture

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "boss"


def _tree(label: str) -> dict:
    return load_fixture(FIXTURE_ROOT / "jobs_list" / f"{label}.json").ui_tree


class TestParseJobList:
    def test_open_tab_yields_three_jobs(self) -> None:
        tree = _tree("open_tab")
        jobs = parse_job_list(tree)
        assert len(jobs) == 3
        assert all(isinstance(j, Job) for j in jobs)

    def test_open_tab_first_job_has_full_metadata(self) -> None:
        tree = _tree("open_tab")
        jobs = parse_job_list(tree)
        first = jobs[0]
        assert first.title == "Senior Backend Engineer"
        assert first.boss_job_id == "JD20260507001"
        assert first.salary_min == 30000
        assert first.salary_max == 60000
        assert first.location == "上海·浦东新区"
        assert first.experience == "5-10年"
        assert first.education == "本科"

    def test_open_tab_second_job_handles_complex_salary(self) -> None:
        tree = _tree("open_tab")
        jobs = parse_job_list(tree)
        second = jobs[1]
        assert second.title == "前端工程师"
        # "20K-35K·14薪" must still parse the K range
        assert second.salary_min == 20000
        assert second.salary_max == 35000

    def test_open_tab_third_job_handles_negotiable_salary(self) -> None:
        tree = _tree("open_tab")
        jobs = parse_job_list(tree)
        third = jobs[2]
        assert third.title == "数据分析师"
        assert third.salary_min is None
        assert third.salary_max is None

    def test_closed_tab_yields_one_job(self) -> None:
        tree = _tree("closed_tab")
        jobs = parse_job_list(tree)
        assert len(jobs) == 1
        assert jobs[0].title == "运维工程师 (已关闭)"
        assert jobs[0].salary_min == 15000
        assert jobs[0].salary_max == 25000

    def test_empty_state_yields_no_jobs(self) -> None:
        tree = _tree("empty_state")
        assert parse_job_list(tree) == []

    def test_handles_completely_empty_tree(self) -> None:
        assert parse_job_list({}) == []

    def test_deduplicates_by_boss_job_id(self) -> None:
        # long_list_page1 includes Senior Backend Engineer twice;
        # the parser must dedupe by job ID, keeping the first.
        tree = _tree("long_list_page1")
        jobs = parse_job_list(tree)
        ids = [j.boss_job_id for j in jobs]
        assert len(ids) == len(set(ids))


class TestDetectActiveTab:
    def test_open_tab_detected(self) -> None:
        tree = _tree("open_tab")
        assert detect_active_tab(tree) == JobStatus.OPEN

    def test_closed_tab_detected(self) -> None:
        tree = _tree("closed_tab")
        assert detect_active_tab(tree) == JobStatus.CLOSED

    def test_returns_none_when_no_tab_marked(self) -> None:
        tree = {
            "className": "android.widget.FrameLayout",
            "packageName": "com.hpbr.bosszhipin",
            "children": [],
        }
        assert detect_active_tab(tree) is None


class TestIsEmptyState:
    def test_empty_state_fixture_returns_true(self) -> None:
        assert is_empty_state(_tree("empty_state")) is True

    def test_open_tab_with_jobs_returns_false(self) -> None:
        assert is_empty_state(_tree("open_tab")) is False


class TestParseSalaryRange:
    @pytest.mark.parametrize(
        "raw,expected_min,expected_max",
        [
            ("30K-60K", 30000, 60000),
            ("20K-35K·14薪", 20000, 35000),
            ("15K-25K", 15000, 25000),
            ("8k-12k", 8000, 12000),
            ("面议", None, None),
            ("", None, None),
            (None, None, None),
            ("8000-12000", 8000, 12000),
            ("不限", None, None),
        ],
    )
    def test_various_inputs(
        self,
        raw: str | None,
        expected_min: int | None,
        expected_max: int | None,
    ) -> None:
        result_min, result_max = parse_salary_range(raw)
        assert result_min == expected_min
        assert result_max == expected_max


class TestJobDataclass:
    def test_is_frozen(self) -> None:
        job = Job(boss_job_id="X", title="Y", status=JobStatus.OPEN)
        with pytest.raises((AttributeError, FrozenInstanceError)):
            job.title = "Z"  # type: ignore[misc]

    def test_status_is_string_enum(self) -> None:
        assert JobStatus.OPEN == "open"
        assert JobStatus.CLOSED == "closed"
        assert JobStatus.HIDDEN == "hidden"
        assert JobStatus.DRAFT == "draft"
