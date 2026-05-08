"""Dump a snapshot of the BOSS Zhipin app UI from a real device.

This is the **only sanctioned way** to capture UI fixtures for the BOSS
automation tests. It pairs an accessibility-tree dump with a screenshot
and rich device/app metadata so unit tests can replay against the
captured state without touching a device.

Usage::

    uv run scripts/dump_boss_ui.py \
        --serial <device-serial> \
        --page candidate_card \
        --label first_time_greet

Outputs (written under ``tests/fixtures/boss/<page>/``):
    <label>.json           # envelope + ui_tree
    <label>.png            # paired screenshot

Refuse-overwrite is the default. Pass ``--force`` to replace an existing
fixture intentionally.

Run with ``--dry-run`` to print the planned output paths without touching
the device or the filesystem.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_PATH = PROJECT_ROOT / "src"
# ``tests/_fixtures/loader.py`` is imported below to share the schema
# constant ``EXPECTED_PACKAGE_NAMES``. Its package lives under the
# project root (not under ``src/``), so PROJECT_ROOT must be on
# sys.path as well. Without this, ``python scripts/dump_boss_ui.py``
# fails with ``ModuleNotFoundError: No module named 'tests'`` unless
# the caller sets ``PYTHONPATH`` manually.
for _extra in (PROJECT_ROOT, SRC_PATH):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from tests._fixtures.loader import EXPECTED_PACKAGE_NAMES  # noqa: E402

DEFAULT_FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "boss"
FIXTURE_SCHEMA_VERSION = 1
DEFAULT_PACKAGE_NAME = "com.hpbr.bosszhipin"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _resolve_output_paths(fixture_root: Path, page: str, label: str) -> tuple[Path, Path]:
    page_dir = fixture_root / page
    return page_dir / f"{label}.json", page_dir / f"{label}.png"


async def _capture_with_droidrun(
    serial: str,
    use_tcp: bool,
    droidrun_port: int,
) -> dict[str, Any]:
    """Capture UI tree, screenshot, and device props via DroidRun."""
    from droidrun import AdbTools  # type: ignore[import-not-found]

    adb = AdbTools(serial=serial, use_tcp=use_tcp, remote_tcp_port=droidrun_port)
    state = await adb.get_state()
    ui_tree = getattr(adb, "raw_tree_cache", None) or state[0] if state else {}
    screenshot_payload: tuple[str, bytes] | None
    try:
        screenshot_payload = await adb.take_screenshot()
    except Exception:
        screenshot_payload = None

    model = await adb.shell("getprop ro.product.model") if hasattr(adb, "shell") else None
    android_version = await adb.shell("getprop ro.build.version.release") if hasattr(adb, "shell") else None
    package_name = DEFAULT_PACKAGE_NAME
    version_name = None
    if hasattr(adb, "shell"):
        try:
            raw = await adb.shell(f"dumpsys package {DEFAULT_PACKAGE_NAME} | grep versionName")
            if raw and "=" in raw:
                version_name = raw.strip().split("=", 1)[-1]
        except Exception:
            version_name = None

    return {
        "ui_tree": ui_tree,
        "screenshot": screenshot_payload,
        "device": {
            "serial": serial,
            "model": (model or "").strip() or None,
            "android_version": (android_version or "").strip() or None,
            "screen_width": None,
            "screen_height": None,
        },
        "app": {
            "package_name": package_name,
            "version_name": version_name,
        },
    }


def _write_envelope(
    json_path: Path,
    label: str,
    page: str,
    ui_tree: dict[str, Any],
    device: dict[str, Any],
    app: dict[str, Any],
    screenshot_path: Path | None,
) -> None:
    envelope = {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "captured_at": _utc_now_iso(),
        "device": device,
        "app": app,
        "label": label,
        "page": page,
        "ui_tree": ui_tree,
        "screenshot_path": (screenshot_path.name if screenshot_path is not None else None),
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_screenshot(screenshot_path: Path, payload: tuple[str, bytes] | None) -> bool:
    if payload is None:
        return False
    _, raw_bytes = payload
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    screenshot_path.write_bytes(raw_bytes)
    return True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="ADB device serial")
    parser.add_argument(
        "--page",
        required=True,
        help="Logical page identifier, e.g. 'candidate_card', 'jobs_list'",
    )
    parser.add_argument(
        "--label",
        required=True,
        help="Scenario label, e.g. 'first_time_greet'",
    )
    parser.add_argument(
        "--fixture-root",
        type=Path,
        default=DEFAULT_FIXTURE_ROOT,
        help="Override fixture output root (default: tests/fixtures/boss)",
    )
    parser.add_argument("--use-tcp", action="store_true", help="Use DroidRun TCP bridge")
    parser.add_argument(
        "--droidrun-port",
        type=int,
        default=8080,
        help="DroidRun TCP port (must be unique per device)",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing fixture files")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned outputs without contacting the device or writing files",
    )
    return parser.parse_args(argv)


async def _async_main(args: argparse.Namespace) -> int:
    json_path, screenshot_path = _resolve_output_paths(args.fixture_root, args.page, args.label)

    if args.dry_run:
        print(f"[dry-run] would write: {json_path}")
        print(f"[dry-run] would write: {screenshot_path}")
        return 0

    if json_path.exists() and not args.force:
        print(
            f"[error] {json_path} already exists; pass --force to overwrite",
            file=sys.stderr,
        )
        return 2

    try:
        captured = await _capture_with_droidrun(args.serial, args.use_tcp, args.droidrun_port)
    except ImportError as exc:
        print(
            f"[error] droidrun is not installed in this environment: {exc}",
            file=sys.stderr,
        )
        return 3
    except Exception as exc:
        print(f"[error] failed to capture device state: {exc}", file=sys.stderr)
        return 4

    pkg = captured["app"]["package_name"]
    if pkg not in EXPECTED_PACKAGE_NAMES:
        print(
            f"[warn] foreground app package {pkg!r} is not in the expected BOSS list "
            f"{sorted(EXPECTED_PACKAGE_NAMES)}; the fixture will be rejected by the loader",
            file=sys.stderr,
        )

    wrote_screenshot = _write_screenshot(screenshot_path, captured["screenshot"])
    _write_envelope(
        json_path=json_path,
        label=args.label,
        page=args.page,
        ui_tree=captured["ui_tree"] or {},
        device=captured["device"],
        app=captured["app"],
        screenshot_path=screenshot_path if wrote_screenshot else None,
    )

    print(f"[ok] wrote {json_path}")
    if wrote_screenshot:
        print(f"[ok] wrote {screenshot_path}")
    else:
        print("[warn] no screenshot captured (DroidRun returned None)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
