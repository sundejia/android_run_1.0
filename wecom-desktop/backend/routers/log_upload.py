"""
Log upload router.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from services.log_upload_service import get_log_upload_service

router = APIRouter()


class LogUploadStatusResponse(BaseModel):
    running: bool
    enabled: bool
    hostname: str
    device_id: str
    person_name: str
    upload_time: str
    upload_url: str
    has_token: bool
    timezone: str
    is_uploading: bool
    config_error: str | None = None
    next_run_at: str | None = None
    last_run: dict[str, Any] | None = None


class LogUploadTriggerResponse(BaseModel):
    success: bool
    status: str
    message: str
    run_id: int | None = None
    files_total: int | None = None
    files_uploaded: int | None = None
    files_skipped: int | None = None
    errors: list[str] = []
    uploaded_files: list[dict[str, Any]] = []


@router.get("/status", response_model=LogUploadStatusResponse)
async def get_log_upload_status():
    service = get_log_upload_service()
    return LogUploadStatusResponse(**service.get_status())


@router.post("/trigger", response_model=LogUploadTriggerResponse)
async def trigger_log_upload():
    service = get_log_upload_service()
    result = await service.run_once(trigger_source="manual")
    return LogUploadTriggerResponse(**result)
