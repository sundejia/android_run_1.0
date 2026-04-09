"""
Sync orchestration router.

Provides endpoints for:
- Starting sync operations on devices
- Stopping sync operations
- Getting sync status
"""

import asyncio
from typing import Dict, List, Optional
from enum import Enum

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from services.device_manager import DeviceManager, SyncState, SyncStatus
from services.settings import get_settings_service

router = APIRouter()

# Global device manager instance
_device_manager: Optional[DeviceManager] = None


def get_device_manager() -> DeviceManager:
    """Get or create device manager."""
    global _device_manager
    if _device_manager is None:
        _device_manager = DeviceManager()
    return _device_manager


class SyncOptions(BaseModel):
    """Sync configuration options."""

    db_path: Optional[str] = None
    images_dir: Optional[str] = None
    timing_multiplier: float = 1.0
    auto_placeholder: bool = True
    no_test_messages: bool = False
    send_via_sidecar: bool = False
    countdown_seconds: int = 10
    # AI Reply settings
    use_ai_reply: bool = False
    ai_server_url: str = "http://localhost:8000"
    ai_reply_timeout: int = 10
    system_prompt: str = ""  # System prompt for AI behavior
    # Resume functionality
    resume: bool = False  # Resume from last checkpoint if available


class StartSyncRequest(BaseModel):
    """Request to start sync on multiple devices."""

    serials: List[str]
    options: SyncOptions = SyncOptions()
    stagger_delay: float = 3.0  # Delay between starting each device (seconds)


class SyncStatusResponse(BaseModel):
    """Sync status response."""

    status: str
    progress: int
    message: str
    customers_synced: Optional[int] = None
    messages_added: Optional[int] = None
    errors: Optional[List[str]] = None


async def _start_sync_staggered(
    manager: DeviceManager,
    serials: List[str],
    options: SyncOptions,
    stagger_delay: float,
):
    """Start sync operations with staggered delays to avoid conflicts."""
    for i, serial in enumerate(serials):
        if i > 0:
            # Wait before starting the next device
            await asyncio.sleep(stagger_delay)

        try:
            await manager.start_sync(
                serial=serial,
                db_path=options.db_path,
                images_dir=options.images_dir,
                timing_multiplier=options.timing_multiplier,
                auto_placeholder=options.auto_placeholder,
                no_test_messages=options.no_test_messages,
                send_via_sidecar=options.send_via_sidecar,
                countdown_seconds=options.countdown_seconds,
                use_ai_reply=options.use_ai_reply,
                ai_server_url=options.ai_server_url,
                ai_reply_timeout=options.ai_reply_timeout,
                system_prompt=options.system_prompt,
                resume=options.resume,
            )
        except Exception as e:
            # Log error but continue with other devices
            print(f"Failed to start sync for {serial}: {e}")


@router.post("/start")
async def start_sync(request: StartSyncRequest, background_tasks: BackgroundTasks):
    """
    Start sync operation on one or more devices.

    Each device runs in an isolated subprocess with its own environment.
    When multiple devices are selected, they start with a staggered delay
    to avoid ADB/droidrun conflicts.
    """
    manager = get_device_manager()
    settings_service = get_settings_service()
    max_concurrent = settings_service.get_max_concurrent_sync_devices()
    available_slots = max(0, max_concurrent - manager.get_active_sync_count())

    if available_slots <= 0:
        raise HTTPException(
            status_code=429,
            detail=f"Sync concurrency limit reached ({max_concurrent}). Stop another sync or disable low-spec mode.",
        )

    serials_to_start = request.serials[:available_slots]
    skipped_serials = request.serials[available_slots:]

    if len(serials_to_start) == 1:
        # Single device - start immediately
        serial = serials_to_start[0]
        try:
            success = await manager.start_sync(
                serial=serial,
                db_path=request.options.db_path,
                images_dir=request.options.images_dir,
                timing_multiplier=request.options.timing_multiplier,
                auto_placeholder=request.options.auto_placeholder,
                no_test_messages=request.options.no_test_messages,
                send_via_sidecar=request.options.send_via_sidecar,
                countdown_seconds=request.options.countdown_seconds,
                use_ai_reply=request.options.use_ai_reply,
                ai_server_url=request.options.ai_server_url,
                ai_reply_timeout=request.options.ai_reply_timeout,
                system_prompt=request.options.system_prompt,
                resume=request.options.resume,
            )

            if success:
                return {
                    "message": f"Started sync on {serial}",
                    "started": [serial],
                    "failed": skipped_serials,
                }
            else:
                return {
                    "message": f"Failed to start sync on {serial}",
                    "started": [],
                    "failed": [serial, *skipped_serials],
                }
        except Exception as e:
            return {
                "message": f"Error starting sync: {e}",
                "started": [],
                "failed": [serial, *skipped_serials],
            }
    else:
        # Multiple devices - use staggered start in background
        background_tasks.add_task(
            _start_sync_staggered,
            manager,
            serials_to_start,
            request.options,
            request.stagger_delay,
        )

        return {
            "message": (
                f"Starting sync on {len(serials_to_start)} device(s) with {request.stagger_delay}s delay between each"
            ),
            "started": serials_to_start,  # Will be started in background
            "failed": skipped_serials,
        }


@router.post("/stop/{serial}")
async def stop_sync(serial: str):
    """
    Stop sync operation on a device.

    Args:
        serial: Device serial number
    """
    manager = get_device_manager()

    success = await manager.stop_sync(serial)

    if not success:
        raise HTTPException(status_code=404, detail=f"No active sync found for device {serial}")

    return {"message": f"Stopped sync on {serial}"}


@router.post("/pause/{serial}")
async def pause_sync(serial: str):
    """
    Pause a running sync operation on a device.

    Args:
        serial: Device serial number
    """
    manager = get_device_manager()

    success = await manager.pause_sync(serial)

    if not success:
        raise HTTPException(status_code=400, detail=f"Cannot pause sync for device {serial} - not running or not found")

    return {"message": f"Paused sync on {serial}"}


@router.post("/resume/{serial}")
async def resume_sync(serial: str):
    """
    Resume a paused sync operation on a device.

    Args:
        serial: Device serial number
    """
    manager = get_device_manager()

    success = await manager.resume_sync(serial)

    if not success:
        raise HTTPException(status_code=400, detail=f"Cannot resume sync for device {serial} - not paused or not found")

    return {"message": f"Resumed sync on {serial}"}


@router.get("/status/{serial}", response_model=SyncStatusResponse)
async def get_sync_status(serial: str):
    """
    Get sync status for a specific device.

    Args:
        serial: Device serial number
    """
    manager = get_device_manager()
    state = manager.get_sync_state(serial)

    if state is None:
        return SyncStatusResponse(
            status="idle",
            progress=0,
            message="No sync in progress",
        )

    return SyncStatusResponse(
        status=state.status.value,
        progress=state.progress,
        message=state.message,
        customers_synced=state.customers_synced,
        messages_added=state.messages_added,
        errors=state.errors if state.errors else None,
    )


@router.get("/status", response_model=Dict[str, SyncStatusResponse])
async def get_all_sync_statuses():
    """Get sync status for all devices with active or recent syncs."""
    manager = get_device_manager()
    states = manager.get_all_sync_states()

    return {
        serial: SyncStatusResponse(
            status=state.status.value,
            progress=state.progress,
            message=state.message,
            customers_synced=state.customers_synced,
            messages_added=state.messages_added,
            errors=state.errors if state.errors else None,
        )
        for serial, state in states.items()
    }
