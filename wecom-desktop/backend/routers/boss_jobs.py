"""REST routes for the BOSS jobs resource.

Self-contained router. Uses the same feature-flag mounting pattern as
``boss_recruiters`` so legacy backend behavior stays unchanged when the
flag is off.

This module exposes three routes for M2:

- ``GET    /api/boss/jobs?recruiter_id=&status=`` — list / filter jobs.
- ``GET    /api/boss/jobs/{job_id}`` — fetch a single job by row id.
- ``POST   /api/boss/jobs/sync``      — synchronously run a job sync
  pass against an injected ``AdbPort`` factory. Production wiring (real
  device subprocess via ``DeviceManager``) is added in M6; for now this
  endpoint is the integration seam used by tests and by the desktop
  app's internal "test sync" workflow.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from boss_automation.core.config import get_default_db_path  # noqa: E402
from boss_automation.database.job_repository import (  # noqa: E402
    JobRecord,
    JobRepository,
)
from boss_automation.database.recruiter_repository import (  # noqa: E402
    RecruiterRepository,
)
from boss_automation.parsers.job_list_parser import JobStatus  # noqa: E402
from boss_automation.services.adb_port import AdbPort  # noqa: E402
from boss_automation.services.job_sync_orchestrator import (  # noqa: E402
    JobSyncOrchestrator,
    JobSyncResult,
)

router = APIRouter(prefix="/api/boss/jobs", tags=["boss-jobs"])

JobStatusLiteral = Literal["open", "closed", "hidden", "draft"]


# --------- Pydantic schemas -----------------------------------------


class JobResponse(BaseModel):
    id: int
    recruiter_id: int
    boss_job_id: str
    title: str
    status: JobStatusLiteral
    salary_min: int | None = None
    salary_max: int | None = None
    location: str | None = None
    education: str | None = None
    experience: str | None = None

    @classmethod
    def from_record(cls, record: JobRecord) -> JobResponse:
        return cls(
            id=record.id,
            recruiter_id=record.recruiter_id,
            boss_job_id=record.boss_job_id,
            title=record.title,
            status=record.status.value,  # type: ignore[arg-type]
            salary_min=record.salary_min,
            salary_max=record.salary_max,
            location=record.location,
            education=record.education,
            experience=record.experience,
        )


class JobListResponse(BaseModel):
    jobs: list[JobResponse] = Field(default_factory=list)
    total: int = 0


class JobSyncRequest(BaseModel):
    device_serial: str
    tabs: list[JobStatusLiteral] | None = None


class JobSyncTabResult(BaseModel):
    tab: JobStatusLiteral
    count: int


class JobSyncResponse(BaseModel):
    recruiter_id: int
    total_jobs: int
    per_tab: list[JobSyncTabResult] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @classmethod
    def from_result(cls, recruiter_id: int, result: JobSyncResult) -> JobSyncResponse:
        return cls(
            recruiter_id=recruiter_id,
            total_jobs=result.total_jobs,
            per_tab=[
                JobSyncTabResult(tab=status.value, count=count)  # type: ignore[arg-type]
                for status, count in result.counts_per_tab.items()
            ],
            errors=list(result.errors),
        )


# --------- Dependency wiring ----------------------------------------


_JobRepoFactory = Callable[[], JobRepository]
_RecruiterRepoFactory = Callable[[], RecruiterRepository]
_AdbPortFactory = Callable[[str], AdbPort]


def _default_job_repository_factory() -> JobRepository:
    return JobRepository(get_default_db_path())


def _default_recruiter_repository_factory() -> RecruiterRepository:
    return RecruiterRepository(get_default_db_path())


def _default_adb_port_factory(_device_serial: str) -> AdbPort:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "ADB port factory not wired. M6 will install the device-manager "
            "wiring; tests inject a fake via set_adb_port_factory()."
        ),
    )


_job_repo_factory: _JobRepoFactory = _default_job_repository_factory
_recruiter_repo_factory: _RecruiterRepoFactory = _default_recruiter_repository_factory
_adb_port_factory: _AdbPortFactory = _default_adb_port_factory


def set_job_repository_factory(factory: _JobRepoFactory) -> None:
    global _job_repo_factory
    _job_repo_factory = factory


def reset_job_repository_factory() -> None:
    set_job_repository_factory(_default_job_repository_factory)


def set_recruiter_repository_factory(factory: _RecruiterRepoFactory) -> None:
    global _recruiter_repo_factory
    _recruiter_repo_factory = factory


def reset_recruiter_repository_factory() -> None:
    set_recruiter_repository_factory(_default_recruiter_repository_factory)


def set_adb_port_factory(factory: _AdbPortFactory) -> None:
    global _adb_port_factory
    _adb_port_factory = factory


def reset_adb_port_factory() -> None:
    set_adb_port_factory(_default_adb_port_factory)


def get_job_repository() -> JobRepository:
    return _job_repo_factory()


def get_recruiter_repository() -> RecruiterRepository:
    return _recruiter_repo_factory()


# --------- Routes ---------------------------------------------------


@router.get("", response_model=JobListResponse)
def list_jobs(
    recruiter_id: int,
    status_filter: JobStatusLiteral | None = None,
    repo: JobRepository = Depends(get_job_repository),
) -> JobListResponse:
    job_status = JobStatus(status_filter) if status_filter else None
    records = repo.list_for_recruiter(recruiter_id, status=job_status)
    return JobListResponse(
        jobs=[JobResponse.from_record(r) for r in records],
        total=len(records),
    )


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: int,
    repo: JobRepository = Depends(get_job_repository),
) -> JobResponse:
    # Repo doesn't currently expose a get_by_id; scan instead.
    # Trade-off: O(N_jobs_per_recruiter) but acceptable for M2.
    # If a hot path emerges, add JobRepository.get_by_id().
    raise_if_not_found = HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"job id {job_id} not found",
    )
    # Try direct query rather than scan-all-recruiters.
    import sqlite3

    with sqlite3.connect(repo.db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id, recruiter_id, boss_job_id, title, status,
                   salary_min, salary_max, location, education, experience
            FROM jobs WHERE id = ?
            """,
            (job_id,),
        ).fetchone()
    if row is None:
        raise raise_if_not_found
    record = JobRecord(
        id=int(row["id"]),
        recruiter_id=int(row["recruiter_id"]),
        boss_job_id=row["boss_job_id"],
        title=row["title"],
        status=JobStatus(row["status"]),
        salary_min=row["salary_min"],
        salary_max=row["salary_max"],
        location=row["location"],
        education=row["education"],
        experience=row["experience"],
    )
    return JobResponse.from_record(record)


@router.post("/sync", response_model=JobSyncResponse)
async def sync_jobs(
    body: JobSyncRequest,
    job_repo: JobRepository = Depends(get_job_repository),
    recruiter_repo: RecruiterRepository = Depends(get_recruiter_repository),
) -> JobSyncResponse:
    recruiter = recruiter_repo.get_by_serial(body.device_serial)
    if recruiter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"no recruiter bound to device {body.device_serial!r}; "
                "register one via /api/boss/recruiters/.../refresh first"
            ),
        )

    adb = _adb_port_factory(body.device_serial)
    orchestrator = JobSyncOrchestrator(adb=adb, jobs_repo=job_repo)
    tabs: Sequence[JobStatus]
    if body.tabs:
        tabs = tuple(JobStatus(t) for t in body.tabs)
    else:
        tabs = (JobStatus.OPEN, JobStatus.CLOSED)
    result = await orchestrator.sync_jobs(recruiter_id=recruiter.id, tabs=tabs)
    return JobSyncResponse.from_result(recruiter.id, result)


# --------- Feature-flag mounting helper ------------------------------


def boss_features_enabled() -> bool:
    raw = os.environ.get("BOSS_FEATURES_ENABLED", "")
    return raw.strip().lower() in ("1", "true", "yes", "on")
