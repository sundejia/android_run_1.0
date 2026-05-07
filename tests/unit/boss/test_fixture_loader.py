"""TDD tests for tests/_fixtures/loader.py.

The loader is the contract between dumped real-device UI snapshots and
unit tests. Tests must be able to load them deterministically, validate
their envelope, and surface clear errors when fixtures drift.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._fixtures.loader import (
    FixtureError,
    UIFixture,
    list_fixtures,
    load_fixture,
)


def _write_fixture(directory: Path, name: str, payload: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _valid_payload(label: str = "demo", page: str = "home") -> dict:
    return {
        "schema_version": 1,
        "captured_at": "2026-05-07T19:00:00+08:00",
        "device": {
            "serial": "EMU-1",
            "model": "Pixel 7",
            "android_version": "14",
            "screen_width": 1080,
            "screen_height": 2400,
        },
        "app": {
            "package_name": "com.hpbr.bosszhipin",
            "version_name": "12.140",
        },
        "label": label,
        "page": page,
        "ui_tree": {
            "className": "android.widget.FrameLayout",
            "packageName": "com.hpbr.bosszhipin",
            "children": [],
        },
        "screenshot_path": None,
    }


class TestLoadFixture:
    def test_loads_valid_fixture_into_typed_object(self, tmp_path: Path) -> None:
        path = _write_fixture(tmp_path, "demo.json", _valid_payload())

        fixture = load_fixture(path)

        assert isinstance(fixture, UIFixture)
        assert fixture.label == "demo"
        assert fixture.page == "home"
        assert fixture.schema_version == 1
        assert fixture.device.serial == "EMU-1"
        assert fixture.device.screen_width == 1080
        assert fixture.app.package_name == "com.hpbr.bosszhipin"
        assert fixture.ui_tree["className"] == "android.widget.FrameLayout"

    def test_missing_file_raises_fixture_error_with_path(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.json"
        with pytest.raises(FixtureError) as exc_info:
            load_fixture(missing)
        assert str(missing) in str(exc_info.value)

    def test_invalid_json_raises_fixture_error(self, tmp_path: Path) -> None:
        broken = tmp_path / "broken.json"
        broken.write_text("not json{", encoding="utf-8")
        with pytest.raises(FixtureError):
            load_fixture(broken)

    def test_missing_required_top_level_field_raises(self, tmp_path: Path) -> None:
        payload = _valid_payload()
        del payload["ui_tree"]
        path = _write_fixture(tmp_path, "incomplete.json", payload)
        with pytest.raises(FixtureError) as exc_info:
            load_fixture(path)
        assert "ui_tree" in str(exc_info.value)

    def test_unsupported_schema_version_raises(self, tmp_path: Path) -> None:
        payload = _valid_payload()
        payload["schema_version"] = 999
        path = _write_fixture(tmp_path, "future.json", payload)
        with pytest.raises(FixtureError) as exc_info:
            load_fixture(path)
        assert "schema_version" in str(exc_info.value)

    def test_wrong_app_package_raises(self, tmp_path: Path) -> None:
        payload = _valid_payload()
        payload["app"]["package_name"] = "com.tencent.wework"
        path = _write_fixture(tmp_path, "wrong_app.json", payload)
        with pytest.raises(FixtureError) as exc_info:
            load_fixture(path)
        assert "package" in str(exc_info.value).lower()


class TestListFixtures:
    def test_returns_empty_list_for_missing_directory(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "nope"
        assert list_fixtures(nonexistent) == []

    def test_lists_all_json_fixtures_in_directory_sorted(self, tmp_path: Path) -> None:
        page_dir = tmp_path / "candidate_card"
        _write_fixture(page_dir, "first_time.json", _valid_payload(label="first_time"))
        _write_fixture(page_dir, "already_greeted.json", _valid_payload(label="already_greeted"))
        # Non-json files should be ignored
        (page_dir / "screenshot.png").write_bytes(b"fake")

        fixtures = list_fixtures(page_dir)

        assert len(fixtures) == 2
        labels = sorted(f.label for f in fixtures)
        assert labels == ["already_greeted", "first_time"]

    def test_skips_invalid_fixture_files_and_collects_errors(self, tmp_path: Path) -> None:
        page_dir = tmp_path / "messages"
        _write_fixture(page_dir, "ok.json", _valid_payload(label="ok"))
        bad = page_dir / "bad.json"
        bad.write_text("{not valid", encoding="utf-8")

        with pytest.raises(FixtureError) as exc_info:
            list_fixtures(page_dir, strict=True)
        assert "bad.json" in str(exc_info.value)

    def test_non_strict_mode_skips_bad_files(self, tmp_path: Path) -> None:
        page_dir = tmp_path / "messages"
        _write_fixture(page_dir, "ok.json", _valid_payload(label="ok"))
        bad = page_dir / "bad.json"
        bad.write_text("{not valid", encoding="utf-8")

        fixtures = list_fixtures(page_dir, strict=False)

        assert len(fixtures) == 1
        assert fixtures[0].label == "ok"
