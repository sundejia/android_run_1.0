"""Tests for the BOSS end-to-end smoke script.

The script (`scripts/boss_smoke.py`) drives the full BOSS data path
(recruiter → job → candidate → message → re-engagement) against an
ephemeral SQLite DB to act as a deployment regression gate.

These tests treat the script as a library: they call the same
``run_smoke()`` function the CLI entry point invokes so we don't pay
subprocess overhead in CI but still exercise the public contract.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "boss_smoke.py"

# Ensure src is importable for the script body's deferred imports.
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def _load_smoke_module():
    if "boss_smoke" in sys.modules:
        return sys.modules["boss_smoke"]
    spec = importlib.util.spec_from_file_location("boss_smoke", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["boss_smoke"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def smoke():
    return _load_smoke_module()


def test_run_smoke_returns_summary_with_expected_counts(tmp_path: Path, smoke) -> None:
    db_path = tmp_path / "smoke.db"
    summary = smoke.run_smoke(db_path=str(db_path))
    assert summary.recruiters == 1
    assert summary.jobs == 1
    assert summary.candidates == 1
    assert summary.eligible == 1
    assert summary.attempts == 1
    assert summary.outcome == "dry_run"
    assert summary.ok is True


def test_run_smoke_format_summary_is_human_readable(tmp_path: Path, smoke) -> None:
    db_path = tmp_path / "smoke.db"
    summary = smoke.run_smoke(db_path=str(db_path))
    text = smoke.format_summary(summary)
    assert "BOSS smoke OK" in text
    assert "recruiters=1" in text
    assert "jobs=1" in text
    assert "candidates=1" in text
    assert "attempts=1" in text


def test_run_smoke_is_idempotent(tmp_path: Path, smoke) -> None:
    db_path = tmp_path / "smoke.db"
    first = smoke.run_smoke(db_path=str(db_path))
    second = smoke.run_smoke(db_path=str(db_path))
    assert first.recruiters == second.recruiters == 1
    assert first.jobs == second.jobs == 1
    assert first.candidates == second.candidates == 1
    assert second.attempts >= 1


def test_main_returns_zero_on_success(tmp_path: Path, smoke) -> None:
    db_path = tmp_path / "smoke.db"
    rc = smoke.main(["--db-path", str(db_path)])
    assert rc == 0
