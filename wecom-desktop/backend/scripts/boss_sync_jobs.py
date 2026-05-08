"""CLI: run a BOSS Zhipin job sync pass for one device.

Usage:
    uv run wecom-desktop/backend/scripts/boss_sync_jobs.py \
        --serial <SERIAL> --recruiter-id <ID> [--tabs open,closed]

The script wraps ``JobSyncOrchestrator`` so a parent process (typically
the FastAPI backend's ``DeviceManager`` in M6) can run job sync
out-of-process per device. Stdout receives one JSON line per progress
event so the parent can stream WS updates without tight coupling.

Exit codes
----------
- 0: success.
- 2: invalid arguments.
- 3: device unreachable (DroidRun/AdbTools could not connect).
- 4: partial success (one or more tabs failed).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# Layout: wecom-desktop/backend/scripts/boss_sync_jobs.py
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent.parent
SRC_DIR = PROJECT_ROOT / "src"

# sys.path setup must come BEFORE any project imports.
for path in (str(SRC_DIR), str(BACKEND_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from boss_automation.core.config import get_default_db_path  # noqa: E402
from boss_automation.database.job_repository import JobRepository  # noqa: E402
from boss_automation.parsers.job_list_parser import JobStatus  # noqa: E402
from boss_automation.services.adb_port import AdbPort  # noqa: E402
from boss_automation.services.droidrun_adapter import DroidRunAdapter  # noqa: E402
from boss_automation.services.job_sync_orchestrator import (  # noqa: E402
    JobSyncOrchestrator,
    JobSyncProgress,
)


def _parse_tabs(raw: str | None) -> Sequence[JobStatus]:
    if not raw:
        return (JobStatus.OPEN, JobStatus.CLOSED)
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    out: list[JobStatus] = []
    for p in parts:
        try:
            out.append(JobStatus(p))
        except ValueError:
            raise SystemExit(2) from None
    return tuple(out)


def _emit(event: str, **payload: Any) -> None:
    print(json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


async def _run(
    serial: str,
    recruiter_id: int,
    tabs: Sequence[JobStatus],
    db_path: str,
    use_tcp: bool,
    droidrun_port: int,
) -> int:
    repo = JobRepository(db_path)
    try:
        adb: AdbPort = DroidRunAdapter(serial=serial, use_tcp=use_tcp, droidrun_port=droidrun_port)
    except Exception as exc:  # noqa: BLE001
        _emit("error", stage="adb_init", message=str(exc))
        return 3

    orch = JobSyncOrchestrator(adb=adb, jobs_repo=repo)

    def on_progress(evt: JobSyncProgress) -> None:
        _emit(
            "progress",
            tab=evt.tab.value,
            new_count=evt.new_count,
            total_count=evt.total_count,
            scroll_index=evt.scroll_index,
            is_final=evt.is_final,
        )

    result = await orch.sync_jobs(recruiter_id=recruiter_id, tabs=tabs, progress=on_progress)
    _emit(
        "done",
        total=result.total_jobs,
        per_tab={status.value: count for status, count in result.counts_per_tab.items()},
        errors=list(result.errors),
    )
    return 4 if result.errors else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BOSS Zhipin job sync for one device.")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--recruiter-id", type=int, required=True)
    parser.add_argument("--tabs", default=None, help="Comma-separated subset of open,closed,hidden,draft")
    parser.add_argument("--db-path", default=get_default_db_path())
    parser.add_argument("--use-tcp", action="store_true", default=False)
    parser.add_argument("--tcp-port", type=int, default=8080)
    args = parser.parse_args(argv)

    tabs = _parse_tabs(args.tabs)
    return asyncio.run(
        _run(
            serial=args.serial,
            recruiter_id=args.recruiter_id,
            tabs=tabs,
            db_path=str(args.db_path),
            use_tcp=args.use_tcp,
            droidrun_port=args.tcp_port,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
