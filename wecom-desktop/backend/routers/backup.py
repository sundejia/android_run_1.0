"""
Backup Router - API endpoints for backup management.

Provides endpoints for:
- Checking backup status
- Triggering manual backups
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from services.backup_service import get_admin_actions_backup_service

router = APIRouter()


class BackupStatusResponse(BaseModel):
    """Response for backup status endpoint."""

    running: bool
    source_file: str
    backup_file: str
    interval_minutes: int
    source_exists: bool
    backup_exists: bool
    last_backup_time: Optional[str] = None
    backup_size: Optional[int] = None
    backup_modified: Optional[str] = None


class BackupTriggerResponse(BaseModel):
    """Response for manual backup trigger."""

    success: bool
    message: str


@router.get("/status", response_model=BackupStatusResponse)
async def get_backup_status():
    """
    Get current backup service status.

    Returns:
    - Whether service is running
    - Source and backup file paths
    - Backup interval
    - Last backup time and file info
    """
    service = get_admin_actions_backup_service()
    status = service.get_status()

    return BackupStatusResponse(**status)


@router.post("/trigger", response_model=BackupTriggerResponse)
async def trigger_backup():
    """
    Trigger an immediate backup.

    Copies admin_actions.xlsx to admin_actions_backup.xlsx now.
    """
    service = get_admin_actions_backup_service()

    if not service.source_file.exists():
        return BackupTriggerResponse(
            success=False,
            message=f"Source file does not exist: {service.source_file.name}",
        )

    success = service.backup_now()

    if success:
        return BackupTriggerResponse(
            success=True,
            message="Backup completed successfully",
        )
    else:
        return BackupTriggerResponse(
            success=False,
            message="Backup failed - check server logs for details",
        )
