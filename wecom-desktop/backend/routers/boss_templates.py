"""REST routes for the BOSS reply / greeting templates.

CRUD on the ``greeting_templates`` table from the M0 schema, plus a
small ``/preview`` endpoint that renders an ad-hoc template against a
JSON context using the same engine the dispatcher uses. This keeps the
desktop app's "测试模板" preview deterministic and dependency-free.

Mounted only when ``BOSS_FEATURES_ENABLED`` is truthy.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from boss_automation.core.config import get_default_db_path  # noqa: E402
from boss_automation.database.template_repository import (  # noqa: E402
    TemplateRecord,
    TemplateRepository,
)
from boss_automation.services.template_engine import render_template  # noqa: E402

router = APIRouter(prefix="/api/boss/templates", tags=["boss-templates"])

ScenarioLiteral = Literal["first_greet", "reply", "reengage"]


# --------- Pydantic schemas ----------------------------------------


class TemplateModel(BaseModel):
    id: int
    name: str
    scenario: ScenarioLiteral
    content: str
    is_default: bool
    variables_json: str | None = None

    @classmethod
    def from_record(cls, record: TemplateRecord) -> TemplateModel:
        return cls(
            id=record.id,
            name=record.name,
            scenario=record.scenario,  # type: ignore[arg-type]
            content=record.content,
            is_default=record.is_default,
            variables_json=record.variables_json,
        )


class TemplatesListResponse(BaseModel):
    templates: list[TemplateModel] = Field(default_factory=list)


class TemplateCreateRequest(BaseModel):
    name: str
    scenario: ScenarioLiteral
    content: str
    is_default: bool = False
    variables_json: str | None = None


class TemplateUpdateRequest(BaseModel):
    content: str | None = None
    is_default: bool | None = None
    variables_json: str | None = None


class PreviewRequest(BaseModel):
    content: str
    context: dict[str, str | None] = Field(default_factory=dict)
    max_length: int = 480


class PreviewResponse(BaseModel):
    text: str
    warnings: list[str]


# --------- Dependency wiring ---------------------------------------


_DbPathProvider = Callable[[], str]


def _default_db_path() -> str:
    return str(get_default_db_path())


_db_path_provider: _DbPathProvider = _default_db_path


def set_db_path_provider(provider: _DbPathProvider) -> None:
    global _db_path_provider
    _db_path_provider = provider


def reset_db_path_provider() -> None:
    set_db_path_provider(_default_db_path)


def get_db_path() -> str:
    return _db_path_provider()


def get_repository(db_path: str = Depends(get_db_path)) -> TemplateRepository:
    return TemplateRepository(db_path)


# --------- Routes --------------------------------------------------


@router.get("/", response_model=TemplatesListResponse)
def list_templates(
    scenario: ScenarioLiteral,
    repo: TemplateRepository = Depends(get_repository),
) -> TemplatesListResponse:
    rows = repo.list_by_scenario(scenario)
    return TemplatesListResponse(templates=[TemplateModel.from_record(r) for r in rows])


@router.get("/{template_id}", response_model=TemplateModel)
def get_template(
    template_id: int,
    repo: TemplateRepository = Depends(get_repository),
) -> TemplateModel:
    record = repo.get_by_id(template_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return TemplateModel.from_record(record)


@router.post("/", response_model=TemplateModel, status_code=status.HTTP_201_CREATED)
def create_template(
    body: TemplateCreateRequest,
    repo: TemplateRepository = Depends(get_repository),
) -> TemplateModel:
    try:
        template_id = repo.insert(
            name=body.name,
            scenario=body.scenario,
            content=body.content,
            is_default=body.is_default,
            variables_json=body.variables_json,
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    record = repo.get_by_id(template_id)
    assert record is not None
    return TemplateModel.from_record(record)


@router.put("/{template_id}", response_model=TemplateModel)
def update_template(
    template_id: int,
    body: TemplateUpdateRequest,
    repo: TemplateRepository = Depends(get_repository),
) -> TemplateModel:
    if repo.get_by_id(template_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    repo.update(
        template_id,
        content=body.content,
        is_default=body.is_default,
        variables_json=body.variables_json,
    )
    record = repo.get_by_id(template_id)
    assert record is not None
    return TemplateModel.from_record(record)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int,
    repo: TemplateRepository = Depends(get_repository),
) -> Response:
    if not repo.delete(template_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/preview", response_model=PreviewResponse)
def preview(body: PreviewRequest) -> PreviewResponse:
    result = render_template(body.content, body.context, max_length=body.max_length)
    return PreviewResponse(text=result.text, warnings=list(result.warnings))


# --------- Feature flag --------------------------------------------


def boss_features_enabled() -> bool:
    raw = os.environ.get("BOSS_FEATURES_ENABLED", "")
    return raw.strip().lower() in ("1", "true", "yes", "on")


__all__ = [
    "router",
    "boss_features_enabled",
    "set_db_path_provider",
    "reset_db_path_provider",
    "get_db_path",
    "get_repository",
    "TemplateModel",
    "TemplatesListResponse",
    "TemplateCreateRequest",
    "TemplateUpdateRequest",
    "PreviewRequest",
    "PreviewResponse",
]
