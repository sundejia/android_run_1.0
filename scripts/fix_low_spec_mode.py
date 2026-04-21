#!/usr/bin/env python3
"""Fix the multi-device sync halt caused by ``low_spec_mode`` being on.

This is the *settings*-side companion to the code fixes for the "three
devices serialize" bug. When ``general.low_spec_mode`` is ``True`` in the
control database, ``SettingsService.get_max_concurrent_sync_devices()``
silently caps concurrency to ``1`` regardless of ``sync.max_concurrent_devices``.
The sync router then rejects (does **not** queue) the over-limit devices, so
the user sees "device 1 starts, devices 2 and 3 fail / sit idle".

This script:

1. Resolves the control DB via ``get_control_db_path()`` so it touches the
   same file the FastAPI backend uses.
2. Prints the current values for ``general.low_spec_mode`` and
   ``sync.max_concurrent_devices``.
3. Sets ``low_spec_mode = False`` and ``max_concurrent_devices = 3`` (or the
   value passed via ``--max-concurrent``) using ``SettingsService.set`` so
   the typed-column write semantics (``value_bool`` / ``value_int``) stay
   consistent with the application.

Usage::

    python scripts/fix_low_spec_mode.py
    python scripts/fix_low_spec_mode.py --max-concurrent 5
    python scripts/fix_low_spec_mode.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _bootstrap_sys_path() -> None:
    """Make ``src/`` and ``wecom-desktop/backend/`` importable."""
    project_root = Path(__file__).resolve().parent.parent
    candidates = [
        project_root / "src",
        project_root / "wecom-desktop" / "backend",
    ]
    for path in candidates:
        if path.exists() and str(path) not in sys.path:
            sys.path.insert(0, str(path))


_bootstrap_sys_path()

# Imports must happen after sys.path bootstrap.
from services.conversation_storage import get_control_db_path  # noqa: E402
from services.settings.service import SettingsService  # noqa: E402


def _format(value: object) -> str:
    if value is None:
        return "<unset>"
    return repr(value)


def _run(max_concurrent: int, dry_run: bool) -> int:
    db_path = get_control_db_path()
    print(f"Control DB path: {db_path}")

    if not db_path.exists():
        print(f"ERROR: control database does not exist at {db_path}.", file=sys.stderr)
        print(
            "Start the backend at least once so the database is created, then re-run.",
            file=sys.stderr,
        )
        return 2

    service = SettingsService(str(db_path))

    current_low_spec = service.get("general", "low_spec_mode", default=False)
    current_max = service.get("sync", "max_concurrent_devices", default=3)

    print()
    print("Current values:")
    print(f"  general.low_spec_mode        = {_format(current_low_spec)}")
    print(f"  sync.max_concurrent_devices  = {_format(current_max)}")
    print()

    needs_low_spec = bool(current_low_spec) is not False
    try:
        needs_max = int(current_max) != int(max_concurrent)
    except (TypeError, ValueError):
        needs_max = True

    if not needs_low_spec and not needs_max:
        print("Already correct. No changes needed.")
        return 0

    print("Planned changes:")
    if needs_low_spec:
        print("  general.low_spec_mode        -> False")
    if needs_max:
        print(f"  sync.max_concurrent_devices  -> {max_concurrent}")
    print()

    if dry_run:
        print("Dry run: no changes written.")
        return 0

    if needs_low_spec:
        service.set("general", "low_spec_mode", False, changed_by="fix_low_spec_mode")
        print("OK: general.low_spec_mode = False")
    if needs_max:
        service.set(
            "sync",
            "max_concurrent_devices",
            int(max_concurrent),
            changed_by="fix_low_spec_mode",
        )
        print(f"OK: sync.max_concurrent_devices = {max_concurrent}")

    print()
    print("Done. Restart the backend (or wait for the next read) and start sync on all devices.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=3,
        help="Target value for sync.max_concurrent_devices (default: 3).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print current values and intended changes without writing.",
    )
    args = parser.parse_args()

    if args.max_concurrent < 1:
        print("ERROR: --max-concurrent must be >= 1.", file=sys.stderr)
        return 2

    return _run(max_concurrent=args.max_concurrent, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
