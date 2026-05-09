"""REST routes for the BOSS greet (打招呼) feature.

Exposes a typed schedule + quota configuration that the desktop app
edits, plus a synchronous "test run" endpoint that exercises one
greet attempt against an injected ``AdbPort``. The full background
runner (one greet attempt every N seconds, controlled by start/stop
buttons) lands in M6 alongside the ``DeviceManager`` wiring.

This router is mounted only when ``BOSS_FEATURES_ENABLED`` is truthy.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from boss_automation.core.config import get_default_db_path  # noqa: E402
from boss_automation.database.candidate_repository import (  # noqa: E402
    CandidateRepository,
)
from boss_automation.database.recruiter_repository import (  # noqa: E402
    RecruiterRepository,
)
from boss_automation.database.schema import ensure_schema  # noqa: E402
from boss_automation.services.adb_port import AdbPort  # noqa: E402
from boss_automation.services.boss_navigator import BossNavigator  # noqa: E402
from boss_automation.services.greet.greet_executor import (  # noqa: E402
    GreetExecutor,
    GreetOutcome,
    OutcomeKind,
)
from boss_automation.services.greet.quota_guard import (  # noqa: E402
    GreetQuota,
    QuotaGuard,
)
from boss_automation.services.greet.schedule import (  # noqa: E402
    GreetSchedule,
    weekday_mask_for,
)

router = APIRouter(prefix="/api/boss/greet", tags=["boss-greet"])

OutcomeLiteral = Literal[
    "sent",
    "skipped_already_greeted",
    "skipped_blacklisted",
    "skipped_quota_day",
    "skipped_quota_hour",
    "skipped_quota_job",
    "skipped_outside_window",
    "skipped_no_candidates",
    "halted_risk_control",
    "halted_unknown_ui",
]


# --------- Schedule + quota persistence ----------------------------
# We store the operator's schedule + quota in a tiny standalone table
# inside the BOSS DB. The table is auto-created on first read.

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS greet_settings (
    device_serial TEXT PRIMARY KEY,
    weekday_mask INTEGER NOT NULL DEFAULT 31,
    start_minute INTEGER NOT NULL DEFAULT 540,
    end_minute INTEGER NOT NULL DEFAULT 1080,
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    per_day INTEGER NOT NULL DEFAULT 80,
    per_hour INTEGER NOT NULL DEFAULT 15,
    per_job INTEGER,
    enabled INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _ensure_settings_table(db_path: str) -> None:
    ensure_schema(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_TABLE_SQL)
        conn.commit()
    finally:
        conn.close()


# --------- Pydantic schemas -----------------------------------------


class GreetWindowModel(BaseModel):
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    start_minute: int = 9 * 60
    end_minute: int = 18 * 60
    timezone: str = "Asia/Shanghai"


class GreetQuotaModel(BaseModel):
    per_day: int = 80
    per_hour: int = 15
    per_job: int | None = None


class GreetSettingsResponse(BaseModel):
    device_serial: str
    enabled: bool
    window: GreetWindowModel
    quota: GreetQuotaModel


class GreetSettingsUpdateRequest(BaseModel):
    enabled: bool | None = None
    window: GreetWindowModel | None = None
    quota: GreetQuotaModel | None = None


class TestRunRequest(BaseModel):
    device_serial: str


class TestRunResponse(BaseModel):
    outcome: OutcomeLiteral
    boss_candidate_id: str | None = None
    candidate_name: str | None = None
    detail: str | None = None

    @classmethod
    def from_outcome(cls, outcome: GreetOutcome) -> TestRunResponse:
        return cls(
            outcome=outcome.kind.value,  # type: ignore[arg-type]
            boss_candidate_id=outcome.boss_candidate_id,
            candidate_name=outcome.candidate_name,
            detail=outcome.detail,
        )


# --------- Dependency wiring ----------------------------------------


_AdbPortFactory = Callable[[str], AdbPort]
_RecruiterFactory = Callable[[], RecruiterRepository]
_CandidateFactory = Callable[[], CandidateRepository]
_DbPathProvider = Callable[[], str]


def _default_db_path() -> str:
    return str(get_default_db_path())


def _default_recruiter_factory() -> RecruiterRepository:
    return RecruiterRepository(_default_db_path())


def _default_candidate_factory() -> CandidateRepository:
    return CandidateRepository(_default_db_path())


def _default_adb_factory(_serial: str) -> AdbPort:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="ADB port factory not wired (M6 will install device-manager wiring)",
    )


_db_path_provider: _DbPathProvider = _default_db_path
_recruiter_factory: _RecruiterFactory = _default_recruiter_factory
_candidate_factory: _CandidateFactory = _default_candidate_factory
_adb_factory: _AdbPortFactory = _default_adb_factory


def set_db_path_provider(provider: _DbPathProvider) -> None:
    global _db_path_provider
    _db_path_provider = provider


def reset_db_path_provider() -> None:
    set_db_path_provider(_default_db_path)


def set_recruiter_repository_factory(factory: _RecruiterFactory) -> None:
    global _recruiter_factory
    _recruiter_factory = factory


def reset_recruiter_repository_factory() -> None:
    set_recruiter_repository_factory(_default_recruiter_factory)


def set_candidate_repository_factory(factory: _CandidateFactory) -> None:
    global _candidate_factory
    _candidate_factory = factory


def reset_candidate_repository_factory() -> None:
    set_candidate_repository_factory(_default_candidate_factory)


def set_adb_port_factory(factory: _AdbPortFactory) -> None:
    global _adb_factory
    _adb_factory = factory


def reset_adb_port_factory() -> None:
    set_adb_port_factory(_default_adb_factory)


def get_db_path() -> str:
    return _db_path_provider()


def get_recruiter_repository() -> RecruiterRepository:
    return _recruiter_factory()


def get_candidate_repository() -> CandidateRepository:
    return _candidate_factory()


# --------- Settings storage helpers ---------------------------------


def _load_settings(db_path: str, device_serial: str) -> GreetSettingsResponse:
    _ensure_settings_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM greet_settings WHERE device_serial = ?",
            (device_serial,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        # Return defaults; do not persist until the operator saves.
        return GreetSettingsResponse(
            device_serial=device_serial,
            enabled=False,
            window=GreetWindowModel(),
            quota=GreetQuotaModel(),
        )

    return GreetSettingsResponse(
        device_serial=device_serial,
        enabled=bool(row["enabled"]),
        window=GreetWindowModel(
            weekdays=_decode_weekdays(int(row["weekday_mask"])),
            start_minute=int(row["start_minute"]),
            end_minute=int(row["end_minute"]),
            timezone=row["timezone"],
        ),
        quota=GreetQuotaModel(
            per_day=int(row["per_day"]),
            per_hour=int(row["per_hour"]),
            per_job=row["per_job"],
        ),
    )


def _save_settings(db_path: str, device_serial: str, current: GreetSettingsResponse) -> None:
    _ensure_settings_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO greet_settings (
                device_serial, weekday_mask, start_minute, end_minute,
                timezone, per_day, per_hour, per_job, enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_serial) DO UPDATE SET
                weekday_mask = excluded.weekday_mask,
                start_minute = excluded.start_minute,
                end_minute = excluded.end_minute,
                timezone = excluded.timezone,
                per_day = excluded.per_day,
                per_hour = excluded.per_hour,
                per_job = excluded.per_job,
                enabled = excluded.enabled,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                device_serial,
                weekday_mask_for(current.window.weekdays),
                current.window.start_minute,
                current.window.end_minute,
                current.window.timezone,
                current.quota.per_day,
                current.quota.per_hour,
                current.quota.per_job,
                int(current.enabled),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _decode_weekdays(mask: int) -> list[int]:
    return [i for i in range(7) if mask & (1 << i)]


# --------- Routes ---------------------------------------------------


@router.get("/settings/{device_serial}", response_model=GreetSettingsResponse)
def get_settings(device_serial: str, db_path: str = Depends(get_db_path)) -> GreetSettingsResponse:
    return _load_settings(db_path, device_serial)


@router.put("/settings/{device_serial}", response_model=GreetSettingsResponse)
def update_settings(
    device_serial: str,
    body: GreetSettingsUpdateRequest,
    db_path: str = Depends(get_db_path),
) -> GreetSettingsResponse:
    current = _load_settings(db_path, device_serial)
    next_state = current.model_copy(
        update={
            **({"enabled": body.enabled} if body.enabled is not None else {}),
            **({"window": body.window} if body.window is not None else {}),
            **({"quota": body.quota} if body.quota is not None else {}),
        }
    )
    _save_settings(db_path, device_serial, next_state)
    return _load_settings(db_path, device_serial)


@router.post("/test-run", response_model=TestRunResponse)
async def test_run(
    body: TestRunRequest,
    db_path: str = Depends(get_db_path),
    recruiter_repo: RecruiterRepository = Depends(get_recruiter_repository),
    candidate_repo: CandidateRepository = Depends(get_candidate_repository),
) -> TestRunResponse:
    recruiter = recruiter_repo.get_by_serial(body.device_serial)
    if recruiter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no recruiter bound to device {body.device_serial!r}",
        )

    settings = _load_settings(db_path, body.device_serial)
    schedule = GreetSchedule(
        weekday_mask=weekday_mask_for(settings.window.weekdays),
        start_minute=settings.window.start_minute,
        end_minute=settings.window.end_minute,
        timezone=settings.window.timezone,
    )
    quota_guard = QuotaGuard(
        GreetQuota(
            per_day=settings.quota.per_day,
            per_hour=settings.quota.per_hour,
            per_job=settings.quota.per_job,
        )
    )

    adb = _adb_factory(body.device_serial)
    navigator = BossNavigator(adb)
    executor = GreetExecutor(
        adb=adb,
        candidate_repo=candidate_repo,
        recruiter_id=recruiter.id,
        schedule=schedule,
        quota_guard=quota_guard,
        navigator=navigator,
    )
    outcome = await executor.execute_one()
    # When the outcome was SENT we deliberately do not mock messages
    # here; M5 will record full message rows.
    return TestRunResponse.from_outcome(outcome)


# --------- Feature flag -----------------------------------------------


def boss_features_enabled() -> bool:
    raw = os.environ.get("BOSS_FEATURES_ENABLED", "")
    return raw.strip().lower() in ("1", "true", "yes", "on")


# Re-export OutcomeKind so tests can assert against it without
# importing through the router module path.
__all__ = [
    "router",
    "boss_features_enabled",
    "set_adb_port_factory",
    "set_recruiter_repository_factory",
    "set_candidate_repository_factory",
    "set_db_path_provider",
    "reset_adb_port_factory",
    "reset_recruiter_repository_factory",
    "reset_candidate_repository_factory",
    "reset_db_path_provider",
    "get_db_path",
    "get_recruiter_repository",
    "get_candidate_repository",
    "OutcomeKind",
    # Pydantic models
    "GreetSettingsResponse",
    "GreetSettingsUpdateRequest",
    "GreetWindowModel",
    "GreetQuotaModel",
    "TestRunRequest",
    "TestRunResponse",
]


# json import is used to keep pydantic / sqlite mapping inspectable.
_ = json
