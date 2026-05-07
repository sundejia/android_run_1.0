"""Read-only monitoring summary for the BOSS Zhipin pivot.

Single endpoint:

* ``GET /api/boss/monitoring/summary`` — return per-recruiter counters
  the desktop dashboard polls. The response is composed of cheap
  aggregate queries (no UI calls, no writes) so it's safe to poll at
  several seconds per refresh.

The "last 24h" windows are *rolling* clock windows anchored at the
injectable ``_clock``. They are intentionally not calendar-day buckets
because operators care about "what's happened since I last looked",
not about midnight resets.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from boss_automation.core.config import get_default_db_path  # noqa: E402
from boss_automation.database.schema import ensure_schema  # noqa: E402
from boss_automation.services.reengagement.detector import find_eligible  # noqa: E402

router = APIRouter(prefix="/api/boss/monitoring", tags=["boss-monitoring"])


# --------- Pydantic schemas -----------------------------------------


class AttemptCounters(BaseModel):
    sent: int = 0
    cancelled: int = 0
    failed: int = 0


class RecruiterSummary(BaseModel):
    recruiter_id: int
    device_serial: str
    name: str | None = None
    company: str | None = None
    position: str | None = None
    jobs_by_status: dict[str, int] = Field(default_factory=dict)
    candidates_by_status: dict[str, int] = Field(default_factory=dict)
    greet_attempts_last_24h: AttemptCounters = Field(default_factory=AttemptCounters)
    reengagement_attempts_last_24h: AttemptCounters = Field(default_factory=AttemptCounters)
    silent_candidates_eligible: int = 0


class MonitoringSummaryResponse(BaseModel):
    generated_at_iso: str
    window_hours: int = 24
    recruiters: list[RecruiterSummary] = Field(default_factory=list)


# --------- Dependency wiring ----------------------------------------


_DbPathProvider = Callable[[], str]
_Clock = Callable[[], datetime]


def _default_db_path() -> str:
    return str(get_default_db_path())


def _default_clock() -> datetime:
    return datetime.now(tz=UTC)


_db_path_provider: _DbPathProvider = _default_db_path
_clock: _Clock = _default_clock


def set_db_path_provider(provider: _DbPathProvider) -> None:
    global _db_path_provider
    _db_path_provider = provider


def reset_db_path_provider() -> None:
    set_db_path_provider(_default_db_path)


def set_clock(clock: _Clock) -> None:
    global _clock
    _clock = clock


def reset_clock() -> None:
    set_clock(_default_clock)


def get_db_path() -> str:
    return _db_path_provider()


# --------- Routes ---------------------------------------------------


@router.get("/summary", response_model=MonitoringSummaryResponse)
def summary(db_path: str = Depends(get_db_path)) -> MonitoringSummaryResponse:
    ensure_schema(db_path)
    now = _clock()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    window_start = now - timedelta(hours=24)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        recruiters = conn.execute(
            """
            SELECT id, device_serial, name, company, position
            FROM recruiters
            ORDER BY device_serial ASC
            """
        ).fetchall()

        results: list[RecruiterSummary] = []
        for r in recruiters:
            rid = int(r["id"])
            results.append(
                RecruiterSummary(
                    recruiter_id=rid,
                    device_serial=r["device_serial"],
                    name=r["name"],
                    company=r["company"],
                    position=r["position"],
                    jobs_by_status=_jobs_by_status(conn, rid),
                    candidates_by_status=_candidates_by_status(conn, rid),
                    greet_attempts_last_24h=_attempts_in_window(
                        conn,
                        rid,
                        window_start,
                        scenario="greet",
                    ),
                    reengagement_attempts_last_24h=_attempts_in_window(
                        conn,
                        rid,
                        window_start,
                        scenario="reengage",
                    ),
                    silent_candidates_eligible=_silent_eligible_count(db_path, rid, now),
                )
            )
    finally:
        conn.close()

    return MonitoringSummaryResponse(
        generated_at_iso=now.isoformat(),
        recruiters=results,
    )


# --------- Helpers --------------------------------------------------


def _jobs_by_status(conn: sqlite3.Connection, recruiter_id: int) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM jobs WHERE recruiter_id = ? GROUP BY status",
        (recruiter_id,),
    ).fetchall()
    return {row["status"]: int(row["n"]) for row in rows}


def _candidates_by_status(conn: sqlite3.Connection, recruiter_id: int) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM candidates WHERE recruiter_id = ? GROUP BY status",
        (recruiter_id,),
    ).fetchall()
    return {row["status"]: int(row["n"]) for row in rows}


def _attempts_in_window(
    conn: sqlite3.Connection,
    recruiter_id: int,
    window_start: datetime,
    *,
    scenario: str,
) -> AttemptCounters:
    """Count followup_attempts_v2 grouped by status within the 24h window.

    ``scenario`` is reserved for future first-greet vs reengage split.
    Currently only ``followup_attempts_v2`` is wired (re-engagement);
    greet attempts return zeros until M3's executor wires its own
    persistence. The split is on the schema dimension we already have
    (template_id → template scenario) and is intentionally cheap to
    extend later without breaking the response shape.
    """
    if scenario == "reengage":
        rows = conn.execute(
            """
            SELECT fa.status AS status, COUNT(*) AS n
            FROM followup_attempts_v2 fa
            JOIN candidates c ON c.id = fa.candidate_id
            WHERE c.recruiter_id = ?
              AND COALESCE(fa.sent_at, fa.scheduled_at) >= ?
            GROUP BY fa.status
            """,
            (recruiter_id, window_start.isoformat()),
        ).fetchall()
        counters = AttemptCounters()
        for row in rows:
            status = row["status"]
            n = int(row["n"])
            if status == "sent":
                counters.sent = n
            elif status == "cancelled":
                counters.cancelled = n
            elif status == "failed":
                counters.failed = n
        return counters
    return AttemptCounters()


def _silent_eligible_count(db_path: str, recruiter_id: int, now: datetime) -> int:
    """Cheap proxy for "ready-to-followup" using detector defaults."""
    eligible = find_eligible(
        db_path=db_path,
        recruiter_id=recruiter_id,
        silent_for_days=3,
        cooldown_days=7,
        now=now,
    )
    return len(eligible)


# --------- Feature flag --------------------------------------------


def boss_features_enabled() -> bool:
    raw = os.environ.get("BOSS_FEATURES_ENABLED", "")
    return raw.strip().lower() in ("1", "true", "yes", "on")


__all__ = [
    "router",
    "boss_features_enabled",
    "set_db_path_provider",
    "reset_db_path_provider",
    "set_clock",
    "reset_clock",
    "get_db_path",
    "MonitoringSummaryResponse",
    "RecruiterSummary",
    "AttemptCounters",
]
