"""
Realtime Reply API Router

管理实时回复系统的设备操作：
- 启动/停止/暂停/恢复设备的实时回复进程
- 查询设备状态
- 设置管理
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/api/realtime", tags=["realtime"])


# ============================================
# Data Models
# ============================================


class DeviceStartRequest(BaseModel):
    """启动设备请求"""

    scan_interval: int = 60
    use_ai_reply: bool = True
    send_via_sidecar: bool = True


class DeviceStatus(BaseModel):
    """单设备状态"""

    serial: str
    status: str  # 'idle', 'starting', 'running', 'paused', 'stopped', 'error'
    message: str
    responses_detected: int
    replies_sent: int
    started_at: str | None = None
    last_scan_at: str | None = None
    errors: list[str] = []


class AllDevicesStatus(BaseModel):
    """所有设备状态"""

    devices: dict[str, DeviceStatus]
    total: int
    running: int


class RealtimeSettings(BaseModel):
    """实时回复设置"""

    model_config = ConfigDict(populate_by_name=True, validate_by_name=True)

    scan_interval: int = Field(60, alias="scanInterval")
    use_ai_reply: bool = Field(True, alias="useAIReply")  # 始终启用
    send_via_sidecar: bool = Field(True, alias="sendViaSidecar")  # 始终启用
    scroll_to_top_enabled: bool = Field(True, alias="scrollToTopEnabled")
    launch_wecom_enabled: bool = Field(True, alias="launchWecomEnabled")
    switch_to_private_chats_enabled: bool = Field(True, alias="switchToPrivateChatsEnabled")


# ============================================
# Settings Endpoints
# ============================================


@router.get("/settings", response_model=RealtimeSettings)
async def get_realtime_settings():
    """获取实时回复设置"""
    try:
        from services.settings import get_settings_service, SettingCategory

        service = get_settings_service()

        # 从 realtime 分类读取配置
        scan_interval = service.get(SettingCategory.REALTIME.value, "scan_interval", 60)
        scroll_to_top_enabled = bool(
            service.get(SettingCategory.REALTIME.value, "scroll_to_top_enabled", True)
        )
        launch_wecom_enabled = bool(
            service.get(SettingCategory.REALTIME.value, "launch_wecom_enabled", True)
        )
        switch_to_private_chats_enabled = bool(
            service.get(SettingCategory.REALTIME.value, "switch_to_private_chats_enabled", True)
        )
        # 强制这两个选项始终为 true (无法关闭)
        use_ai_reply = True
        send_via_sidecar = True

        return RealtimeSettings(
            scan_interval=scan_interval,
            use_ai_reply=use_ai_reply,
            send_via_sidecar=send_via_sidecar,
            scroll_to_top_enabled=scroll_to_top_enabled,
            launch_wecom_enabled=launch_wecom_enabled,
            switch_to_private_chats_enabled=switch_to_private_chats_enabled,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load settings: {str(e)}")


@router.post("/settings")
async def update_realtime_settings(settings: RealtimeSettings):
    """更新实时回复设置"""
    try:
        from services.settings import get_settings_service, SettingCategory

        service = get_settings_service()

        # 强制 use_ai_reply 和 send_via_sidecar 始终为 true (无法关闭)
        updates = {
            "scan_interval": settings.scan_interval,
            "use_ai_reply": True,  # 始终启用
            "send_via_sidecar": True,  # 始终启用
            "scroll_to_top_enabled": bool(settings.scroll_to_top_enabled),
            "launch_wecom_enabled": bool(settings.launch_wecom_enabled),
            "switch_to_private_chats_enabled": bool(settings.switch_to_private_chats_enabled),
        }

        service.set_category(SettingCategory.REALTIME.value, updates, "api")

        return {"success": True, "message": "Settings saved successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save settings: {str(e)}")


# ============================================
# Device Operations
# ============================================


@router.post("/device/{serial}/start")
async def start_device(
    serial: str,
    scan_interval: int = Query(60, ge=10, le=600),
    use_ai_reply: bool = Query(True),
    send_via_sidecar: bool = Query(True),
):
    """
    启动设备的实时回复进程

    独立子进程会：
    - 定期扫描未读消息
    - 检测客户回复
    - 生成 AI 回复（如果启用）
    - 通过 Sidecar 发送（如果启用）
    """
    from routers.devices import ensure_device_kefu_persisted
    from services.realtime_reply_manager import get_realtime_reply_manager

    await ensure_device_kefu_persisted(serial, launch_wecom=False, allow_placeholder=True)

    manager = get_realtime_reply_manager()

    # Pre-check the realtime concurrency cap so we can return a meaningful
    # 429 to the UI before doing anything else. The manager re-checks
    # internally to keep the contract authoritative.
    try:
        from services.settings import get_settings_service

        _settings = get_settings_service()
        _max_concurrent = _settings.get_max_concurrent_realtime_devices()
    except Exception:
        _max_concurrent = 4

    _active = manager.get_active_realtime_count()
    _existing_state = manager.get_state(serial)
    _already_active_for_this_device = _existing_state and _existing_state.status.value in ("running", "starting")

    if _active >= _max_concurrent and not _already_active_for_this_device:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Realtime concurrency limit reached ({_active}/{_max_concurrent}). "
                "Stop another device or raise maxConcurrentRealtimeDevices."
            ),
        )

    success = await manager.start_realtime_reply(
        serial=serial, scan_interval=scan_interval, use_ai_reply=use_ai_reply, send_via_sidecar=send_via_sidecar
    )

    if not success:
        state = manager.get_state(serial)
        if state and state.status.value in ("running", "starting"):
            raise HTTPException(status_code=409, detail="Realtime reply already running for this device")
        else:
            raise HTTPException(status_code=500, detail="Failed to start realtime reply process")

    state = manager.get_state(serial)

    return {
        "success": True,
        "message": f"Realtime reply started for device {serial}",
        "serial": serial,
        "status": state.status.value if state else "unknown",
    }


@router.post("/device/{serial}/stop")
async def stop_device(serial: str):
    """停止设备的实时回复进程"""
    from services.realtime_reply_manager import get_realtime_reply_manager

    manager = get_realtime_reply_manager()
    success = await manager.stop_realtime_reply(serial)

    if not success:
        raise HTTPException(status_code=404, detail="No realtime reply process running for this device")

    return {"success": True, "message": f"Realtime reply stopped for device {serial}", "serial": serial}


@router.post("/device/{serial}/pause")
async def pause_device(serial: str):
    """
    暂停设备的实时回复进程

    Windows: 使用 Job Objects 暂停
    Unix: 发送 SIGSTOP 信号
    """
    from services.realtime_reply_manager import get_realtime_reply_manager

    manager = get_realtime_reply_manager()
    success = await manager.pause_realtime_reply(serial)

    if not success:
        state = manager.get_state(serial)
        if not state:
            raise HTTPException(status_code=404, detail="No realtime reply process for this device")
        if state.status.value != "running":
            raise HTTPException(status_code=400, detail=f"Cannot pause: current status is {state.status.value}")
        raise HTTPException(status_code=500, detail="Failed to pause realtime reply process")

    return {"success": True, "message": f"Realtime reply paused for device {serial}", "serial": serial}


@router.post("/device/{serial}/resume")
async def resume_device(serial: str):
    """
    恢复暂停的实时回复进程

    Windows: 恢复 Job Object
    Unix: 发送 SIGCONT 信号
    """
    from services.realtime_reply_manager import get_realtime_reply_manager

    manager = get_realtime_reply_manager()
    success = await manager.resume_realtime_reply(serial)

    if not success:
        state = manager.get_state(serial)
        if not state:
            raise HTTPException(status_code=404, detail="No realtime reply process for this device")
        if state.status.value != "paused":
            raise HTTPException(status_code=400, detail=f"Cannot resume: current status is {state.status.value}")
        raise HTTPException(status_code=500, detail="Failed to resume realtime reply process")

    return {"success": True, "message": f"Realtime reply resumed for device {serial}", "serial": serial}


@router.post("/device/{serial}/skip")
async def skip_current_message(serial: str):
    """
    请求跳过当前排队的消息

    创建一个跳过标志文件，子进程在下次扫描周期开始时会检查。
    将在下一个扫描周期生效（scan_interval 秒内）。
    """
    from services.realtime_reply_manager import get_realtime_reply_manager

    manager = get_realtime_reply_manager()
    success = await manager.request_skip(serial)

    if not success:
        state = manager.get_state(serial)
        if not state:
            raise HTTPException(status_code=404, detail="No realtime reply process for this device")
        if state.status.value != "running":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot skip: current status is {state.status.value}. Process must be running.",
            )
        raise HTTPException(status_code=500, detail="Failed to request skip")

    return {
        "success": True,
        "message": f"Skip requested for device {serial}. Will take effect on next scan cycle.",
        "serial": serial,
    }


@router.get("/device/{serial}/status", response_model=DeviceStatus)
async def get_device_status(serial: str):
    """获取设备的实时回复状态"""
    from services.realtime_reply_manager import get_realtime_reply_manager

    manager = get_realtime_reply_manager()
    state = manager.get_state(serial)

    if not state:
        return DeviceStatus(
            serial=serial,
            status="idle",
            message="No realtime reply process",
            responses_detected=0,
            replies_sent=0,
            errors=[],
        )

    return DeviceStatus(
        serial=serial,
        status=state.status.value,
        message=state.message,
        responses_detected=state.responses_detected,
        replies_sent=state.replies_sent,
        started_at=state.started_at.isoformat() if state.started_at else None,
        last_scan_at=state.last_scan_at.isoformat() if state.last_scan_at else None,
        errors=state.errors,
    )


@router.get("/devices/status", response_model=AllDevicesStatus)
async def get_all_devices_status():
    """获取所有设备的实时回复状态"""
    from routers.devices import get_discovery_service
    from services.realtime_reply_manager import get_realtime_reply_manager

    manager = get_realtime_reply_manager()
    all_states = manager.get_all_states()

    devices = {}
    running_count = 0

    # 获取所有 ADB 连接的设备
    try:
        discovery = get_discovery_service()
        device_list = await discovery.list_devices(include_properties=False, include_runtime_stats=False)
        adb_devices = [d.serial for d in device_list]
    except Exception:
        adb_devices = []

    # 为所有 ADB 设备添加状态
    for serial in adb_devices:
        if serial in all_states:
            state = all_states[serial]
            device_status = DeviceStatus(
                serial=serial,
                status=state.status.value,
                message=state.message,
                responses_detected=state.responses_detected,
                replies_sent=state.replies_sent,
                started_at=state.started_at.isoformat() if state.started_at else None,
                last_scan_at=state.last_scan_at.isoformat() if state.last_scan_at else None,
                errors=state.errors,
            )
            if state.status.value in ("running", "starting"):
                running_count += 1
        else:
            # 已连接但未启动实时回复
            device_status = DeviceStatus(
                serial=serial,
                status="idle",
                message="Ready to start",
                responses_detected=0,
                replies_sent=0,
                started_at=None,
                last_scan_at=None,
                errors=[],
            )
        devices[serial] = device_status

    return AllDevicesStatus(devices=devices, total=len(devices), running=running_count)


@router.post("/devices/stop-all")
async def stop_all_devices():
    """停止所有设备的实时回复进程"""
    from services.realtime_reply_manager import get_realtime_reply_manager

    manager = get_realtime_reply_manager()

    # 获取当前运行的设备
    all_states = manager.get_all_states()
    running_devices = [
        serial for serial, state in all_states.items() if state.status.value in ("running", "starting", "paused")
    ]

    # 停止所有
    await manager.stop_all()

    return {
        "success": True,
        "message": f"Stopped {len(running_devices)} realtime reply process(es)",
        "stopped_devices": running_devices,
        "count": len(running_devices),
    }
