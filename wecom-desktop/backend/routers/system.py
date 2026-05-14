"""System-level operations: restart/stop WeCom app on Android devices."""

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system", tags=["system"])

WECOM_PACKAGE = "com.tencent.wework"


class WecomAppOperationResult(BaseModel):
    success: bool
    message: str


@router.post("/restart-wecom-app/{serial}", response_model=WecomAppOperationResult)
async def restart_wecom_app(serial: str):
    """Force-stop then re-launch the WeCom app on the Android device."""
    try:
        from droidrun.tools.adb import AdbTools

        adb = AdbTools(serial=serial)
        await adb.connect()

        # Force stop
        await adb.device.app_stop(WECOM_PACKAGE)
        logger.info("restart_wecom_app: force-stopped %s on %s", WECOM_PACKAGE, serial)

        await asyncio.sleep(2.0)

        # Re-launch
        await adb.start_app(WECOM_PACKAGE)
        logger.info("restart_wecom_app: relaunched %s on %s", WECOM_PACKAGE, serial)

        return WecomAppOperationResult(
            success=True, message=f"WeCom app restarted on {serial}"
        )
    except Exception as e:
        logger.error("restart_wecom_app_error: serial=%s error=%s", serial, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop-wecom-app/{serial}", response_model=WecomAppOperationResult)
async def stop_wecom_app(serial: str):
    """Force-stop the WeCom app on the Android device."""
    try:
        from droidrun.tools.adb import AdbTools

        adb = AdbTools(serial=serial)
        await adb.connect()

        await adb.device.app_stop(WECOM_PACKAGE)
        logger.info("stop_wecom_app: force-stopped %s on %s", WECOM_PACKAGE, serial)

        return WecomAppOperationResult(
            success=True, message=f"WeCom app stopped on {serial}"
        )
    except Exception as e:
        logger.error("stop_wecom_app_error: serial=%s error=%s", serial, e)
        raise HTTPException(status_code=500, detail=str(e))
