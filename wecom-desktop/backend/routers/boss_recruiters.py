"""REST routes for the BOSS recruiters resource.

This router is self-contained and depends only on the BOSS package
(``src/boss_automation``) plus FastAPI/Pydantic. It does NOT import
the legacy WeCom services so it can be unit-tested without spinning
up the full backend.

Mounting policy
---------------
The router is registered into ``main.py`` only when the
``BOSS_FEATURES_ENABLED`` env var is truthy. This keeps the legacy
backend behavior unchanged for users on M0/M1.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from boss_automation.core.config import get_default_db_path  # noqa: E402
from boss_automation.database.recruiter_repository import (  # noqa: E402
    RecruiterRecord,
    RecruiterRepository,
)

router = APIRouter(prefix="/api/boss/recruiters", tags=["boss-recruiters"])


# --------- Pydantic schemas (stable JSON contract) -------------------


class RecruiterResponse(BaseModel):
    id: int
    device_serial: str
    name: str | None = None
    company: str | None = None
    position: str | None = None
    avatar_path: str | None = None

    @classmethod
    def from_record(cls, record: RecruiterRecord) -> RecruiterResponse:
        return cls(
            id=record.id,
            device_serial=record.device_serial,
            name=record.name,
            company=record.company,
            position=record.position,
            avatar_path=record.avatar_path,
        )


class RecruiterListResponse(BaseModel):
    recruiters: list[RecruiterResponse] = Field(default_factory=list)
    total: int = 0


class RecruiterRefreshRequest(BaseModel):
    """Body for POST /refresh.

    Optional name/company fields support an "operator override" when the
    on-device profile detection cannot resolve identity (e.g. recruiter
    just signed up, no company filled in yet). When omitted, the
    refresh is a pure read from the live device — that path is
    implemented in M2 as part of the device manager and exposed by
    extending this router.
    """

    name: str | None = None
    company: str | None = None
    position: str | None = None
    avatar_path: str | None = None


# --------- Dependency wiring ----------------------------------------


_RepositoryFactory = Callable[[], RecruiterRepository]


def _default_repository_factory() -> RecruiterRepository:
    return RecruiterRepository(get_default_db_path())


_repository_factory: _RepositoryFactory = _default_repository_factory


def set_repository_factory(factory: _RepositoryFactory) -> None:
    """Override the repository factory (for tests or feature wiring)."""
    global _repository_factory
    _repository_factory = factory


def reset_repository_factory() -> None:
    set_repository_factory(_default_repository_factory)


def get_repository() -> RecruiterRepository:
    return _repository_factory()


# --------- Routes ---------------------------------------------------


@router.get("", response_model=RecruiterListResponse)
def list_recruiters(
    repo: RecruiterRepository = Depends(get_repository),
) -> RecruiterListResponse:
    """Return every recruiter persisted in the BOSS DB."""
    records = repo.list_all()
    return RecruiterListResponse(
        recruiters=[RecruiterResponse.from_record(r) for r in records],
        total=len(records),
    )


@router.get("/{device_serial}", response_model=RecruiterResponse)
def get_recruiter_by_serial(
    device_serial: str,
    repo: RecruiterRepository = Depends(get_repository),
) -> RecruiterResponse:
    record = repo.get_by_serial(device_serial)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no recruiter bound to device {device_serial!r}",
        )
    return RecruiterResponse.from_record(record)


@router.post(
    "/{device_serial}/refresh",
    response_model=RecruiterResponse,
    status_code=status.HTTP_200_OK,
)
def refresh_recruiter(
    device_serial: str,
    body: RecruiterRefreshRequest,
    repo: RecruiterRepository = Depends(get_repository),
) -> RecruiterResponse:
    """Persist an explicit recruiter snapshot for the given device.

    M1 supports operator-supplied snapshots only. M2 will add a
    "live re-scan via device subprocess" code path; this endpoint will
    then accept an empty body to mean "go talk to the device".
    """
    if not any([body.name, body.company, body.position, body.avatar_path]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="refresh body must include at least one of: name, company, position, avatar_path",
        )
    from boss_automation.parsers.recruiter_profile_parser import RecruiterProfile

    profile = RecruiterProfile(
        name=(body.name or "").strip() or "未命名招聘者",
        company=body.company,
        position=body.position,
        avatar_path=body.avatar_path,
    )
    repo.upsert(device_serial, profile)
    record = repo.get_by_serial(device_serial)
    assert record is not None  # we just upserted it
    return RecruiterResponse.from_record(record)


# --------- Feature-flag aware mounting helper -----------------------


def boss_features_enabled() -> bool:
    raw = os.environ.get("BOSS_FEATURES_ENABLED", "")
    return raw.strip().lower() in ("1", "true", "yes", "on")
