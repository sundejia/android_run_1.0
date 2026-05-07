"""REST routes for the BOSS re-engagement (复聊跟进) feature.

Three endpoints:

* ``GET / PUT /api/boss/reengagement/settings/{device_serial}`` —
  per-device silent threshold, cooldown, daily cap, scenario template.
* ``POST /api/boss/reengagement/scan`` — return eligible candidates
  without sending. Useful for the desktop "preview" panel.
* ``POST /api/boss/reengagement/run`` — execute one re-engagement
  attempt and return the outcome + persisted attempt id.

All paths share the same in-process state-injection hooks the other
``boss_*`` routers use, so tests can swap the DB path / blacklist
check / clock without monkey-patching globals.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from boss_automation.core.config import get_default_db_path  # noqa: E402
from boss_automation.database.followup_attempts_repository import (  # noqa: E402
    FollowupAttemptsRepository,
)
from boss_automation.database.message_repository import (  # noqa: E402
    MessageRepository,
)
from boss_automation.database.recruiter_repository import (  # noqa: E402
    RecruiterRepository,
)
from boss_automation.database.schema import ensure_schema  # noqa: E402
from boss_automation.services.reengagement.detector import (  # noqa: E402
    EligibleCandidate,
    find_eligible,
)
from boss_automation.services.reengagement.orchestrator import (  # noqa: E402
    ReengagementKind,
    ReengagementOrchestrator,
    ReengagementSettings,
)

router = APIRouter(prefix="/api/boss/reengagement", tags=["boss-reengagement"])

OutcomeLiteral = Literal[
    "sent",
    "dry_run",
    "skipped_candidate_replied",
    "skipped_blacklisted",
    "skipped_daily_cap",
    "no_eligible",
    "failed",
]


# --------- Settings persistence -------------------------------------


_SETTINGS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS reengagement_settings (
    device_serial TEXT PRIMARY KEY,
    silent_for_days INTEGER NOT NULL DEFAULT 3,
    cooldown_days INTEGER NOT NULL DEFAULT 7,
    daily_cap INTEGER NOT NULL DEFAULT 50,
    template_id INTEGER,
    enabled INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _ensure_settings_table(db_path: str) -> None:
    ensure_schema(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_SETTINGS_TABLE_SQL)
        conn.commit()
    finally:
        conn.close()


# --------- Pydantic schemas -----------------------------------------


class ReengagementSettingsModel(BaseModel):
    device_serial: str
    silent_for_days: int = 3
    cooldown_days: int = 7
    daily_cap: int = 50
    template_id: int | None = None
    enabled: bool = False


class ReengagementSettingsUpdateRequest(BaseModel):
    silent_for_days: int | None = None
    cooldown_days: int | None = None
    daily_cap: int | None = None
    template_id: int | None = None
    enabled: bool | None = None


class ScanRequest(BaseModel):
    device_serial: str


class EligibleModel(BaseModel):
    candidate_id: int
    boss_candidate_id: str
    conversation_id: int
    last_outbound_at_iso: str
    silent_for_seconds: int

    @classmethod
    def from_record(cls, record: EligibleCandidate) -> EligibleModel:
        return cls(
            candidate_id=record.candidate_id,
            boss_candidate_id=record.boss_candidate_id,
            conversation_id=record.conversation_id,
            last_outbound_at_iso=record.last_outbound_at_iso,
            silent_for_seconds=record.silent_for_seconds,
        )


class ScanResponse(BaseModel):
    recruiter_id: int
    eligible: list[EligibleModel] = Field(default_factory=list)


class RunRequest(BaseModel):
    device_serial: str


class RunResponse(BaseModel):
    outcome: OutcomeLiteral
    boss_candidate_id: str | None = None
    candidate_id: int | None = None
    attempt_id: int | None = None
    detail: str | None = None


# --------- Dependency wiring ----------------------------------------


_DbPathProvider = Callable[[], str]
_BlacklistChecker = Callable[[str], Awaitable[bool]]
_Clock = Callable[[], datetime]


def _default_db_path() -> str:
    return str(get_default_db_path())


async def _default_blacklist_check(_boss_candidate_id: str) -> bool:
    return False


def _default_clock() -> datetime:
    return datetime.now(tz=UTC)


_db_path_provider: _DbPathProvider = _default_db_path
_blacklist_check: _BlacklistChecker = _default_blacklist_check
_clock: _Clock = _default_clock


def set_db_path_provider(provider: _DbPathProvider) -> None:
    global _db_path_provider
    _db_path_provider = provider


def reset_db_path_provider() -> None:
    set_db_path_provider(_default_db_path)


def set_blacklist_check(check: _BlacklistChecker) -> None:
    global _blacklist_check
    _blacklist_check = check


def reset_blacklist_check() -> None:
    set_blacklist_check(_default_blacklist_check)


def set_clock(clock: _Clock) -> None:
    global _clock
    _clock = clock


def reset_clock() -> None:
    set_clock(_default_clock)


def get_db_path() -> str:
    return _db_path_provider()


# --------- Settings storage helpers ---------------------------------


def _load_settings(db_path: str, device_serial: str) -> ReengagementSettingsModel:
    _ensure_settings_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM reengagement_settings WHERE device_serial = ?",
            (device_serial,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return ReengagementSettingsModel(device_serial=device_serial)
    return ReengagementSettingsModel(
        device_serial=device_serial,
        silent_for_days=int(row["silent_for_days"]),
        cooldown_days=int(row["cooldown_days"]),
        daily_cap=int(row["daily_cap"]),
        template_id=row["template_id"],
        enabled=bool(row["enabled"]),
    )


def _save_settings(db_path: str, current: ReengagementSettingsModel) -> None:
    _ensure_settings_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO reengagement_settings
                (device_serial, silent_for_days, cooldown_days, daily_cap,
                 template_id, enabled)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_serial) DO UPDATE SET
                silent_for_days = excluded.silent_for_days,
                cooldown_days   = excluded.cooldown_days,
                daily_cap       = excluded.daily_cap,
                template_id     = excluded.template_id,
                enabled         = excluded.enabled,
                updated_at      = CURRENT_TIMESTAMP
            """,
            (
                current.device_serial,
                current.silent_for_days,
                current.cooldown_days,
                current.daily_cap,
                current.template_id,
                int(current.enabled),
            ),
        )
        conn.commit()
    finally:
        conn.close()


# --------- Routes ---------------------------------------------------


@router.get("/settings/{device_serial}", response_model=ReengagementSettingsModel)
def get_settings(device_serial: str, db_path: str = Depends(get_db_path)) -> ReengagementSettingsModel:
    return _load_settings(db_path, device_serial)


@router.put("/settings/{device_serial}", response_model=ReengagementSettingsModel)
def update_settings(
    device_serial: str,
    body: ReengagementSettingsUpdateRequest,
    db_path: str = Depends(get_db_path),
) -> ReengagementSettingsModel:
    current = _load_settings(db_path, device_serial)
    next_state = current.model_copy(
        update={
            **({"silent_for_days": body.silent_for_days} if body.silent_for_days is not None else {}),
            **({"cooldown_days": body.cooldown_days} if body.cooldown_days is not None else {}),
            **({"daily_cap": body.daily_cap} if body.daily_cap is not None else {}),
            **({"template_id": body.template_id} if body.template_id is not None else {}),
            **({"enabled": body.enabled} if body.enabled is not None else {}),
        }
    )
    _save_settings(db_path, next_state)
    return _load_settings(db_path, device_serial)


@router.post("/scan", response_model=ScanResponse)
def scan(body: ScanRequest, db_path: str = Depends(get_db_path)) -> ScanResponse:
    recruiter_repo = RecruiterRepository(db_path)
    recruiter = recruiter_repo.get_by_serial(body.device_serial)
    if recruiter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no recruiter bound to device {body.device_serial!r}",
        )

    settings_model = _load_settings(db_path, body.device_serial)
    eligible = find_eligible(
        db_path=db_path,
        recruiter_id=recruiter.id,
        silent_for_days=settings_model.silent_for_days,
        cooldown_days=settings_model.cooldown_days,
        now=_clock(),
    )
    return ScanResponse(
        recruiter_id=recruiter.id,
        eligible=[EligibleModel.from_record(r) for r in eligible],
    )


@router.post("/run", response_model=RunResponse)
async def run_one(body: RunRequest, db_path: str = Depends(get_db_path)) -> RunResponse:
    recruiter_repo = RecruiterRepository(db_path)
    recruiter = recruiter_repo.get_by_serial(body.device_serial)
    if recruiter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no recruiter bound to device {body.device_serial!r}",
        )

    settings_model = _load_settings(db_path, body.device_serial)
    eligible = find_eligible(
        db_path=db_path,
        recruiter_id=recruiter.id,
        silent_for_days=settings_model.silent_for_days,
        cooldown_days=settings_model.cooldown_days,
        now=_clock(),
    )
    if not eligible:
        return RunResponse(outcome="no_eligible")

    target = eligible[0]
    orchestrator = ReengagementOrchestrator(
        attempts_repo=FollowupAttemptsRepository(db_path),
        message_repo=MessageRepository(db_path),
        dispatcher=None,  # M6 will wire the real dispatcher
        is_blacklisted=_blacklist_check,
        settings=ReengagementSettings(
            silent_for_days=settings_model.silent_for_days,
            cooldown_days=settings_model.cooldown_days,
            daily_cap=settings_model.daily_cap,
        ),
        clock=_clock,
    )
    outcome = await orchestrator.run_one(eligible=target)
    return RunResponse(
        outcome=_map_outcome(outcome.kind),
        boss_candidate_id=outcome.boss_candidate_id,
        candidate_id=outcome.candidate_id,
        attempt_id=outcome.attempt_id,
        detail=outcome.detail,
    )


def _map_outcome(kind: ReengagementKind) -> OutcomeLiteral:
    return kind.value  # type: ignore[return-value]


# --------- Feature flag --------------------------------------------


def boss_features_enabled() -> bool:
    raw = os.environ.get("BOSS_FEATURES_ENABLED", "")
    return raw.strip().lower() in ("1", "true", "yes", "on")


__all__ = [
    "router",
    "boss_features_enabled",
    "set_db_path_provider",
    "reset_db_path_provider",
    "set_blacklist_check",
    "reset_blacklist_check",
    "set_clock",
    "reset_clock",
    "get_db_path",
    "ReengagementSettingsModel",
    "ReengagementSettingsUpdateRequest",
    "ScanRequest",
    "ScanResponse",
    "RunRequest",
    "RunResponse",
]
