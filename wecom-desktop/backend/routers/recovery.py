"""
Recovery API Router - 无感恢复 API

提供恢复状态查询和管理接口。
"""

import asyncio
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Set
from datetime import datetime
import json

from services.recovery.manager import get_recovery_manager
from services.recovery.models import TaskStatus

router = APIRouter(prefix="/api/recovery", tags=["recovery"])

# WebSocket 连接管理
_recovery_ws_connections: Set[WebSocket] = set()


async def broadcast_recovery_event(event_type: str, data: Dict[str, Any]):
    """
    广播恢复相关事件到所有连接的 WebSocket 客户端

    Args:
        event_type: 事件类型 (device_connected, device_disconnected, task_resumable)
        data: 事件数据
    """
    if not _recovery_ws_connections:
        return

    message = json.dumps(
        {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }
    )

    disconnected = set()
    for ws in _recovery_ws_connections:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)

    # 清理断开的连接
    _recovery_ws_connections.difference_update(disconnected)


# ============================================
# Pydantic Models
# ============================================


class RecoveryTaskResponse(BaseModel):
    """恢复任务响应"""

    task_id: str
    task_type: str
    status: str
    device_serial: str
    progress_percent: int
    started_at: Optional[str]
    last_checkpoint_at: Optional[str]
    pending_count: int
    completed_count: int
    last_error: Optional[str]


class RecoveryStatusResponse(BaseModel):
    """恢复状态响应"""

    has_pending_tasks: bool
    pending_count: int
    pending_tasks: List[Dict[str, Any]]
    can_resume: bool
    status_counts: Dict[str, int]


class ResumeResponse(BaseModel):
    """恢复操作响应"""

    success: bool
    message: str
    resumed_tasks: List[str]


class DiscardResponse(BaseModel):
    """放弃任务响应"""

    success: bool
    message: str
    task_id: str


# ============================================
# API Endpoints
# ============================================


@router.get("/status", response_model=RecoveryStatusResponse)
async def get_recovery_status():
    """
    获取恢复系统状态

    返回是否有待恢复任务、待恢复任务列表等信息。
    """
    manager = get_recovery_manager()
    status = manager.get_status()

    return RecoveryStatusResponse(
        has_pending_tasks=status["has_pending_tasks"],
        pending_count=status["pending_count"],
        pending_tasks=status["pending_tasks"],
        can_resume=status["can_resume"],
        status_counts=status["status_counts"],
    )


@router.get("/tasks")
async def get_pending_tasks(task_type: Optional[str] = None):
    """
    获取待恢复任务列表

    Args:
        task_type: 可选，过滤特定类型的任务
    """
    manager = get_recovery_manager()
    tasks = manager.get_pending_tasks(task_type)

    return {"success": True, "count": len(tasks), "tasks": [t.to_dict() for t in tasks]}


@router.get("/tasks/{task_id}")
async def get_task_detail(task_id: str):
    """
    获取特定任务详情

    Args:
        task_id: 任务ID
    """
    manager = get_recovery_manager()
    task = manager.get_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    return {"success": True, "task": task.to_dict()}


@router.post("/resume")
async def resume_all_tasks():
    """
    恢复所有待恢复任务

    注意：这只是标记任务为可恢复状态，实际恢复需要重新启动扫描。
    """
    manager = get_recovery_manager()
    pending = manager.get_pending_tasks()

    resumed = []
    for task in pending:
        if task.status in [TaskStatus.PAUSED, TaskStatus.FAILED]:
            manager.mark_pending_recovery(task.task_id)
            resumed.append(task.task_id)

    return ResumeResponse(success=True, message=f"Marked {len(resumed)} tasks for recovery", resumed_tasks=resumed)


@router.post("/discard/{task_id}")
async def discard_task(task_id: str):
    """
    放弃特定任务

    Args:
        task_id: 任务ID
    """
    manager = get_recovery_manager()
    success = manager.discard_task(task_id)

    if not success:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    return DiscardResponse(success=True, message=f"Task {task_id} discarded", task_id=task_id)


@router.delete("/tasks")
async def clear_all_tasks():
    """
    清除所有恢复任务（慎用）
    """
    manager = get_recovery_manager()
    count = manager.clear_all_tasks()

    return {"success": True, "message": f"Cleared {count} tasks"}


@router.delete("/completed")
async def clear_completed_tasks(days_old: int = 7):
    """
    清理已完成的旧任务

    Args:
        days_old: 清理多少天前的任务，默认7天
    """
    manager = get_recovery_manager()
    count = manager.clear_completed_tasks(days_old)

    return {"success": True, "message": f"Cleared {count} completed tasks older than {days_old} days"}


@router.get("/check")
async def check_should_resume(task_type: str, device_serial: Optional[str] = None):
    """
    检查是否应该恢复任务

    Args:
        task_type: 任务类型
        device_serial: 设备序列号（可选）
    """
    manager = get_recovery_manager()
    should_resume = manager.should_resume(task_type, device_serial)

    task = None
    if should_resume:
        resumable = manager.get_resumable_task(task_type, device_serial)
        if resumable:
            task = resumable.to_dict()

    return {"should_resume": should_resume, "task": task}


# ============================================
# 通用恢复 API - 任意界面恢复
# ============================================


class ResumableTaskDetail(BaseModel):
    """可恢复任务详情"""

    task_id: str
    task_type: str
    device_serial: str
    status: str
    progress_percent: int
    synced_count: int
    total_count: int
    messages_added: int
    started_at: Optional[str]
    last_checkpoint_at: Optional[str]
    ui_state: Optional[Dict[str, Any]] = None


class UniversalRecoveryResponse(BaseModel):
    """通用恢复检查响应"""

    has_resumable: bool
    resumable_count: int
    tasks: List[ResumableTaskDetail]


@router.get("/check-all", response_model=UniversalRecoveryResponse)
async def check_all_resumable():
    """
    检查所有可恢复任务（应用启动时调用）

    返回所有可以恢复的任务，包含详细的进度信息和 UI 状态。
    用于在应用启动或任意界面显示恢复对话框。
    """
    manager = get_recovery_manager()

    # 首先将所有 running 状态的任务标记为 pending_recovery
    # （这些是应用异常退出时遗留的任务）
    manager.mark_all_running_as_pending()

    # 获取所有可恢复任务详情
    tasks = manager.get_resumable_tasks_with_details()

    task_responses = []
    for task in tasks:
        task_responses.append(
            ResumableTaskDetail(
                task_id=task["task_id"],
                task_type=task["task_type"],
                device_serial=task["device_serial"] or "",
                status=task["status"],
                progress_percent=task["progress_percent"],
                synced_count=task["synced_count"],
                total_count=task["total_count"],
                messages_added=task["messages_added"],
                started_at=task["started_at"],
                last_checkpoint_at=task["last_checkpoint_at"],
                ui_state=task["ui_state"],
            )
        )

    return UniversalRecoveryResponse(
        has_resumable=len(task_responses) > 0, resumable_count=len(task_responses), tasks=task_responses
    )


@router.get("/device/{device_serial}/tasks")
async def get_device_resumable_tasks(device_serial: str):
    """
    获取指定设备的可恢复任务

    Args:
        device_serial: 设备序列号
    """
    manager = get_recovery_manager()
    tasks = manager.get_tasks_by_device(device_serial)

    return {"device_serial": device_serial, "has_resumable": len(tasks) > 0, "tasks": tasks}


@router.post("/task/{task_id}/ui-state")
async def save_task_ui_state(task_id: str, ui_state: Dict[str, Any]):
    """
    保存任务的 UI 状态

    用于在同步过程中定期保存界面状态，以便恢复时能还原。

    Args:
        task_id: 任务ID
        ui_state: UI状态数据
    """
    manager = get_recovery_manager()

    task = manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    manager.save_ui_state(task_id, ui_state)

    return {"success": True, "message": f"UI state saved for task {task_id}"}


@router.post("/resume-task/{task_id}")
async def resume_single_task(task_id: str):
    """
    恢复单个任务

    将任务标记为 pending_recovery 状态，等待扫描器恢复。

    Args:
        task_id: 任务ID
    """
    manager = get_recovery_manager()

    task = manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    manager.mark_pending_recovery(task_id)

    return {
        "success": True,
        "message": f"Task {task_id} marked for recovery",
        "task_id": task_id,
        "device_serial": task.device_serial,
        "task_type": task.task_type,
        "redirect_to": "/devices",  # 前端可以根据这个跳转
    }


@router.post("/discard-all/{device_serial}")
async def discard_all_device_tasks(device_serial: str):
    """
    放弃指定设备的所有恢复任务

    Args:
        device_serial: 设备序列号
    """
    manager = get_recovery_manager()
    tasks = manager.get_tasks_by_device(device_serial)

    discarded = []
    for task in tasks:
        if manager.discard_task(task["task_id"]):
            discarded.append(task["task_id"])

    return {
        "success": True,
        "message": f"Discarded {len(discarded)} tasks for device {device_serial}",
        "discarded_tasks": discarded,
    }


# ============================================
# WebSocket 端点 - 实时恢复通知
# ============================================


@router.websocket("/ws")
async def recovery_websocket(websocket: WebSocket):
    """
    恢复系统 WebSocket 连接

    用于实时推送:
    - 设备连接/断开事件
    - 可恢复任务通知
    - 任务状态变化

    消息格式:
    {
        "type": "device_connected" | "device_disconnected" | "task_resumable" | "task_status_changed",
        "data": { ... },
        "timestamp": "ISO timestamp"
    }
    """
    await websocket.accept()
    _recovery_ws_connections.add(websocket)

    try:
        # 发送当前状态
        manager = get_recovery_manager()
        tasks = manager.get_resumable_tasks_with_details()

        await websocket.send_json(
            {
                "type": "initial_state",
                "data": {
                    "resumable_tasks": tasks,
                    "count": len(tasks),
                },
                "timestamp": datetime.now().isoformat(),
            }
        )

        # 保持连接，等待客户端消息或断开
        while True:
            try:
                # 等待客户端消息（心跳或命令）
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)

                # 处理客户端命令
                try:
                    message = json.loads(data)
                    if message.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                    elif message.get("type") == "refresh":
                        # 刷新任务列表
                        tasks = manager.get_resumable_tasks_with_details()
                        await websocket.send_json(
                            {
                                "type": "refresh_response",
                                "data": {
                                    "resumable_tasks": tasks,
                                    "count": len(tasks),
                                },
                                "timestamp": datetime.now().isoformat(),
                            }
                        )
                except json.JSONDecodeError:
                    pass

            except asyncio.TimeoutError:
                # 发送心跳
                try:
                    await websocket.send_json({"type": "heartbeat"})
                except Exception:
                    break

    except WebSocketDisconnect:
        pass
    finally:
        _recovery_ws_connections.discard(websocket)
