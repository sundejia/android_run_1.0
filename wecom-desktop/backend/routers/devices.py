"""
Device management router.

Provides endpoints for:
- Listing connected devices
- Getting device details
- Refreshing device list
- Initializing devices (launch WeCom, get kefu info)
- Taking device screenshots
"""

import asyncio
import base64
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from droidrun.tools.adb import AdbTools

# Import from wecom_automation
from services.conversation_storage import get_device_conversation_db_path
from wecom_automation.database.repository import ConversationRepository
from wecom_automation.services.device_service import DeviceDiscoveryService
from wecom_automation.core.models import DeviceInfo

# Import kefu extraction function
from pathlib import Path

from utils.kefu_extraction import extract_kefu_from_tree

router = APIRouter()
logger = logging.getLogger(__name__)

# Device discovery service instance
_discovery_service: Optional[DeviceDiscoveryService] = None

# Cache for kefu info per device (serial -> KefuInfoModel)
_kefu_cache: Dict[str, "KefuInfoModel"] = {}

# Package name for WeCom
WECOM_PACKAGE = "com.tencent.wework"

# ADB path for Windows - use local adb.exe bundled with the app
_ADB_PATH: Optional[str] = None


def _get_adb_path() -> Optional[str]:
    """Get the path to adb executable, preferring local bundled version."""
    global _ADB_PATH
    if _ADB_PATH is not None:
        return _ADB_PATH

    import os
    import platform
    import shutil

    # Check for environment variable first
    env_adb = os.environ.get("ADB_PATH")
    if env_adb and os.path.isfile(env_adb):
        _ADB_PATH = env_adb
        return _ADB_PATH

    # Check for local bundled adb.exe (relative to this file: backend/routers -> backend -> wecom-desktop/adb)
    if platform.system() == "Windows":
        from utils.path_utils import get_project_root
        local_adb = get_project_root() / "wecom-desktop" / "adb" / "adb.exe"
        if local_adb.is_file():
            _ADB_PATH = str(local_adb)
            return _ADB_PATH

    # Fall back to system PATH
    _ADB_PATH = shutil.which("adb")
    return _ADB_PATH


def get_discovery_service() -> DeviceDiscoveryService:
    """Get or create device discovery service."""
    global _discovery_service
    if _discovery_service is None:
        adb_path = _get_adb_path()
        _discovery_service = DeviceDiscoveryService(adb_path=adb_path)
    return _discovery_service


async def _extract_kefu_for_device(serial: str, launch_wecom: bool = False) -> Optional["KefuInfoModel"]:
    """Extract current kefu info from the device UI."""
    adb = AdbTools(serial=serial)

    if launch_wecom:
        await adb.start_app(WECOM_PACKAGE)
        await asyncio.sleep(2.0)

    await adb.get_state()
    tree = getattr(adb, "raw_tree_cache", None)
    if not tree:
        return None

    kefu_info = extract_kefu_from_tree(tree)
    if not kefu_info:
        return None

    return KefuInfoModel(
        name=kefu_info.name,
        department=kefu_info.department,
        verification_status=kefu_info.verification_status,
    )


async def ensure_device_kefu_persisted(
    serial: str,
    *,
    launch_wecom: bool = False,
    allow_placeholder: bool = True,
) -> Optional["KefuInfoModel"]:
    """
    Ensure the device has a persisted kefu-device mapping before sidecar/realtime flows.
    """
    repo = ConversationRepository(str(get_device_conversation_db_path(serial)))
    device = repo.get_or_create_device(serial)
    existing_kefus = repo.list_kefus_for_device(device.id)
    if existing_kefus:
        current = existing_kefus[0]
        return KefuInfoModel(
            name=current.name,
            department=current.department,
            verification_status=current.verification_status,
        )

    kefu_model = _kefu_cache.get(serial)
    if kefu_model is None:
        kefu_model = await _extract_kefu_for_device(serial, launch_wecom=launch_wecom)
        if kefu_model is not None:
            _kefu_cache[serial] = kefu_model

    if kefu_model is not None:
        repo.get_or_create_kefu(
            kefu_model.name,
            device.id,
            kefu_model.department,
            kefu_model.verification_status,
        )
        return kefu_model

    if allow_placeholder:
        created = repo.get_or_create_kefu(f"Kefu-{serial[:8]}", device.id, None, None)
        logger.info(
            "Realtime reply startup: no persisted kefu for device %s, created placeholder kefu %s (id=%s)",
            serial,
            created.name,
            created.id,
        )
        placeholder = KefuInfoModel(
            name=created.name,
            department=created.department,
            verification_status=created.verification_status,
        )
        _kefu_cache.setdefault(serial, placeholder)
        return placeholder

    return None


class KefuInfoModel(BaseModel):
    """Kefu (customer service rep) information model."""

    name: str
    department: Optional[str] = None
    verification_status: Optional[str] = None


class DeviceResponse(BaseModel):
    """Device response model."""

    serial: str
    state: str
    product: Optional[str] = None
    model: Optional[str] = None
    device: Optional[str] = None
    transport_id: Optional[int] = None
    usb: Optional[str] = None
    features: Optional[str] = None
    manufacturer: Optional[str] = None
    brand: Optional[str] = None
    android_version: Optional[str] = None
    sdk_version: Optional[str] = None
    security_patch: Optional[str] = None
    build_id: Optional[str] = None
    hardware: Optional[str] = None
    abi: Optional[str] = None
    battery_level: Optional[str] = None
    battery_status: Optional[str] = None
    screen_resolution: Optional[str] = None
    screen_density: Optional[str] = None
    memory_total: Optional[str] = None
    usb_debugging: Optional[bool] = None
    wifi_mac: Optional[str] = None
    internal_storage: Optional[str] = None
    connection_type: Optional[str] = None
    ip_address: Optional[str] = None
    tcp_port: Optional[int] = None
    endpoint: Optional[str] = None
    extra_props: dict[str, str] = Field(default_factory=dict)
    is_online: bool
    # Kefu information (populated after initialization)
    kefu: Optional[KefuInfoModel] = None

    @classmethod
    def from_device_info(cls, info: DeviceInfo, kefu: Optional[KefuInfoModel] = None) -> "DeviceResponse":
        """Create from DeviceInfo."""
        return cls(
            serial=info.serial,
            state=info.state,
            product=info.product,
            model=info.model,
            device=info.device,
            transport_id=info.transport_id,
            usb=info.usb,
            features=info.features,
            manufacturer=info.manufacturer,
            brand=info.brand,
            android_version=info.android_version,
            sdk_version=info.sdk_version,
            security_patch=info.security_patch,
            build_id=info.build_id,
            hardware=info.hardware,
            abi=info.abi,
            battery_level=info.battery_level,
            battery_status=info.battery_status,
            screen_resolution=info.screen_resolution,
            screen_density=info.screen_density,
            memory_total=info.memory_total,
            usb_debugging=info.usb_debugging,
            wifi_mac=info.wifi_mac,
            internal_storage=info.internal_storage,
            connection_type=info.connection_type,
            ip_address=info.ip_address,
            tcp_port=info.tcp_port,
            endpoint=info.endpoint,
            extra_props=info.extra_props,
            is_online=info.is_online,
            kefu=kefu,
        )


def get_kefu_for_device(serial: str) -> Optional[KefuInfoModel]:
    """Get cached kefu info for a device."""
    return _kefu_cache.get(serial)


@router.get("", response_model=List[DeviceResponse])
async def list_devices():
    """
    List all connected Android devices.

    Returns device information including model, manufacturer, status, and kefu info.
    """
    try:
        service = get_discovery_service()
        devices = await service.list_devices(
            include_properties=True,
            include_runtime_stats=True,
        )
        return [DeviceResponse.from_device_info(d, kefu=get_kefu_for_device(d.serial)) for d in devices]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/refresh", response_model=List[DeviceResponse])
async def refresh_devices():
    """
    Refresh the device list.

    Forces a new scan for connected devices.
    """
    try:
        service = get_discovery_service()
        devices = await service.list_devices(
            include_properties=True,
            include_runtime_stats=True,
        )
        return [DeviceResponse.from_device_info(d, kefu=get_kefu_for_device(d.serial)) for d in devices]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{serial}", response_model=DeviceResponse)
async def get_device(serial: str):
    """
    Get details for a specific device.

    Args:
        serial: Device serial number
    """
    try:
        service = get_discovery_service()
        device = await service.get_device(
            serial,
            include_properties=True,
            include_runtime_stats=True,
        )

        if device is None:
            raise HTTPException(status_code=404, detail=f"Device {serial} not found")

        return DeviceResponse.from_device_info(device, kefu=get_kefu_for_device(serial))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class InitDeviceResponse(BaseModel):
    """Response for device initialization."""

    success: bool
    kefu: Optional[KefuInfoModel] = None
    wecom_launched: bool = False
    error: Optional[str] = None


@router.post("/{serial}/init", response_model=InitDeviceResponse)
async def init_device(serial: str, launch_wecom: bool = True):
    """
    Initialize a device: launch WeCom and retrieve kefu info.

    This should be called once when a device connects to set up the kefu info.
    The kefu info is cached and will be included in subsequent device listings.

    Kefu extraction is intended to run from WeCom's main page, where the
    profile/sidebar block is visible in the upper-left area. This endpoint
    currently reads the current UI tree as-is and caches the best-effort
    extraction result from that tree.

    Args:
        serial: Device serial number
        launch_wecom: Whether to launch WeCom before getting kefu info (default: True)
    """
    try:
        # Check if we already have kefu info cached
        if serial in _kefu_cache:
            return InitDeviceResponse(
                success=True,
                kefu=_kefu_cache[serial],
                wecom_launched=False,  # Didn't need to launch
            )

        kefu_model = await _extract_kefu_for_device(serial, launch_wecom=launch_wecom)
        wecom_launched = launch_wecom

        if kefu_model:
            # Cache the kefu info
            _kefu_cache[serial] = kefu_model

            return InitDeviceResponse(
                success=True,
                kefu=kefu_model,
                wecom_launched=wecom_launched,
            )
        return InitDeviceResponse(success=False, wecom_launched=wecom_launched, error="Could not extract kefu info from UI")

    except Exception as e:
        return InitDeviceResponse(success=False, error=str(e))


@router.delete("/{serial}/kefu-cache")
async def clear_kefu_cache(serial: str):
    """Clear cached kefu info for a device."""
    if serial in _kefu_cache:
        del _kefu_cache[serial]
        return {"success": True, "message": f"Kefu cache cleared for {serial}"}
    return {"success": True, "message": f"No kefu cache found for {serial}"}


@router.get("/{serial}/screenshot")
async def get_device_screenshot(serial: str):
    """
    Take a screenshot of the device screen.

    Args:
        serial: Device serial number

    Returns:
        The screenshot image as PNG binary data
    """
    try:
        adb = AdbTools(serial=serial)
        result = await adb.take_screenshot()

        # result is a tuple of (filename/format, bytes)
        _, img_bytes = result

        return Response(
            content=img_bytes,
            media_type="image/png",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to take screenshot: {str(e)}")
