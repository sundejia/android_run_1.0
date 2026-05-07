"""Loader for dumped BOSS Zhipin UI snapshots.

The dump tool at ``scripts/dump_boss_ui.py`` writes a single JSON file
per page-snapshot. The schema is::

    {
      "schema_version": 1,
      "captured_at": "2026-05-07T19:00:00+08:00",
      "device": {
        "serial": "EMU-1",
        "model": "Pixel 7",
        "android_version": "14",
        "screen_width": 1080,
        "screen_height": 2400
      },
      "app": {
        "package_name": "com.hpbr.bosszhipin",
        "version_name": "12.140"
      },
      "label": "first_time_greet",
      "page": "candidate_card",
      "ui_tree": { ... },
      "screenshot_path": "tests/fixtures/boss/candidate_card/first_time_greet.png"
    }

This module reads, validates, and exposes those snapshots as typed
``UIFixture`` objects to unit tests so we can drive parsers and state
machines without any real-device dependency.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

SUPPORTED_FIXTURE_SCHEMA_VERSIONS: Final[frozenset[int]] = frozenset({1})

EXPECTED_PACKAGE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "com.hpbr.bosszhipin",
        "com.hpbr.directhires",
    }
)


class FixtureError(ValueError):
    """Raised when a UI fixture file cannot be read or violates the schema."""


@dataclass(frozen=True, slots=True)
class FixtureDevice:
    serial: str
    model: str | None
    android_version: str | None
    screen_width: int | None
    screen_height: int | None


@dataclass(frozen=True, slots=True)
class FixtureApp:
    package_name: str
    version_name: str | None


@dataclass(frozen=True, slots=True)
class UIFixture:
    """A single dumped UI snapshot ready for unit tests."""

    path: Path
    schema_version: int
    captured_at: str
    label: str
    page: str
    device: FixtureDevice
    app: FixtureApp
    ui_tree: dict[str, Any]
    screenshot_path: Path | None


_REQUIRED_TOP_LEVEL = (
    "schema_version",
    "captured_at",
    "label",
    "page",
    "device",
    "app",
    "ui_tree",
)


def _require(payload: dict, key: str, source: Path) -> Any:
    if key not in payload:
        raise FixtureError(f"fixture {source} is missing required field: {key}")
    return payload[key]


def _validate_envelope(payload: dict, source: Path) -> None:
    if not isinstance(payload, dict):
        raise FixtureError(f"fixture {source} must be a JSON object, got {type(payload).__name__}")
    for key in _REQUIRED_TOP_LEVEL:
        _require(payload, key, source)

    schema_version = payload["schema_version"]
    if schema_version not in SUPPORTED_FIXTURE_SCHEMA_VERSIONS:
        raise FixtureError(
            f"fixture {source} has unsupported schema_version {schema_version!r}; "
            f"supported: {sorted(SUPPORTED_FIXTURE_SCHEMA_VERSIONS)}"
        )

    app = payload["app"]
    if not isinstance(app, dict) or "package_name" not in app:
        raise FixtureError(f"fixture {source} has malformed 'app' section: {app!r}")
    pkg = app["package_name"]
    if pkg not in EXPECTED_PACKAGE_NAMES:
        raise FixtureError(
            f"fixture {source} has unexpected app package {pkg!r}; expected one of {sorted(EXPECTED_PACKAGE_NAMES)}"
        )

    if not isinstance(payload["device"], dict) or "serial" not in payload["device"]:
        raise FixtureError(f"fixture {source} has malformed 'device' section")

    if not isinstance(payload["ui_tree"], dict):
        raise FixtureError(f"fixture {source} 'ui_tree' must be an object")


def _build_fixture(payload: dict, source: Path) -> UIFixture:
    device_payload = payload["device"]
    app_payload = payload["app"]
    screenshot = payload.get("screenshot_path")
    screenshot_path: Path | None
    if screenshot is None:
        screenshot_path = None
    else:
        screenshot_candidate = Path(screenshot)
        screenshot_path = (
            screenshot_candidate if screenshot_candidate.is_absolute() else (source.parent / screenshot_candidate)
        )

    return UIFixture(
        path=source,
        schema_version=int(payload["schema_version"]),
        captured_at=str(payload["captured_at"]),
        label=str(payload["label"]),
        page=str(payload["page"]),
        device=FixtureDevice(
            serial=str(device_payload["serial"]),
            model=device_payload.get("model"),
            android_version=device_payload.get("android_version"),
            screen_width=device_payload.get("screen_width"),
            screen_height=device_payload.get("screen_height"),
        ),
        app=FixtureApp(
            package_name=str(app_payload["package_name"]),
            version_name=app_payload.get("version_name"),
        ),
        ui_tree=payload["ui_tree"],
        screenshot_path=screenshot_path,
    )


def load_fixture(path: str | Path) -> UIFixture:
    """Load a dumped UI fixture from disk.

    Raises:
        FixtureError: if the file cannot be read or the contents do not
        match the supported envelope.
    """
    source = Path(path)
    if not source.exists():
        raise FixtureError(f"fixture not found: {source}")
    if not source.is_file():
        raise FixtureError(f"fixture path is not a file: {source}")

    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise FixtureError(f"failed to read fixture {source}: {exc}") from exc

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FixtureError(f"fixture {source} is not valid JSON: {exc}") from exc

    _validate_envelope(payload, source)
    return _build_fixture(payload, source)


def list_fixtures(directory: str | Path, *, strict: bool = False) -> list[UIFixture]:
    """List all valid UI fixtures in a directory, sorted by file name.

    Args:
        directory: directory to scan. Returns ``[]`` if it does not exist.
        strict: when ``True``, malformed fixture files raise
            ``FixtureError``. When ``False`` (default), they are silently
            skipped so a single bad file cannot break a test suite.
    """
    base = Path(directory)
    if not base.exists():
        return []

    fixtures: list[UIFixture] = []
    for json_file in sorted(base.glob("*.json")):
        try:
            fixtures.append(load_fixture(json_file))
        except FixtureError:
            if strict:
                raise
            continue
    return fixtures
