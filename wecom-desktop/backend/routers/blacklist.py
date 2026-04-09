"""
Blacklist Router - API endpoints for blacklist management.

Provides endpoints for:
- Listing blacklist entries
- Adding/removing users from blacklist
- Checking if a user is blacklisted
- Getting customers with blacklist status
"""

import logging
from typing import List, Optional, Set, Tuple
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from wecom_automation.services.blacklist_service import BlacklistChecker, BlacklistWriter

logger = logging.getLogger("blacklist.router")
router = APIRouter()

# ============================================================================
# Pydantic Models
# ============================================================================


class BlacklistEntry(BaseModel):
    """黑名单条目"""

    id: int
    device_serial: str
    customer_name: str
    customer_channel: Optional[str] = None
    reason: Optional[str] = None
    deleted_by_user: bool = False
    is_blacklisted: bool = True
    avatar_url: Optional[str] = None
    created_at: str
    updated_at: str


class BlacklistAddRequest(BaseModel):
    """添加黑名单请求"""

    device_serial: str = Field(..., description="设备序列号")
    customer_name: str = Field(..., description="用户名")
    customer_channel: Optional[str] = Field(None, description="渠道 (如 @WeChat)")
    reason: Optional[str] = Field(None, description="加入原因")
    deleted_by_user: bool = Field(False, description="是否因用户删除而加入")


class BlacklistRemoveRequest(BaseModel):
    """移除黑名单请求"""

    device_serial: str = Field(..., description="设备序列号")
    customer_name: str = Field(..., description="用户名")
    customer_channel: Optional[str] = Field(None, description="渠道 (如 @WeChat)")


class CustomerWithBlacklistStatus(BaseModel):
    """带黑名单状态的用户"""

    customer_name: str
    customer_channel: Optional[str] = None
    is_blacklisted: bool
    blacklist_reason: Optional[str] = None
    deleted_by_user: bool = False
    last_message_at: Optional[str] = None
    message_count: int = 0


class BlacklistCheckResponse(BaseModel):
    """黑名单检查响应"""

    is_blacklisted: bool
    reason: Optional[str] = None


class BatchOperationResult(BaseModel):
    """批量操作结果"""

    success_count: int
    failed_count: int
    errors: List[str] = []


class ScannedUser(BaseModel):
    """扫描到的用户"""

    customer_name: str
    customer_channel: Optional[str] = None
    avatar_url: Optional[str] = None
    reason: Optional[str] = "Auto Scan"


class UpsertScannedUsersRequest(BaseModel):
    """批量插入扫描用户请求"""

    device_serial: str
    users: List[ScannedUser]


class BlacklistUpdateRequest(BaseModel):
    """更新黑名单状态请求"""

    id: int
    is_blacklisted: bool


class BatchUpdateStatusRequest(BaseModel):
    """批量更新黑名单状态请求"""

    ids: List[int]
    is_blacklisted: bool


class BlacklistCopyRequest(BaseModel):
    """复制设备黑名单请求"""

    source_device_serial: str = Field(..., description="源设备序列号")
    target_device_serial: str = Field(..., description="目标设备序列号")
    include_allowed: bool = Field(True, description="是否同时复制放行记录")
    overwrite_existing: bool = Field(True, description="目标设备已存在时是否覆盖状态")


class BlacklistCopyResponse(BaseModel):
    """复制设备黑名单响应"""

    success: bool
    copied_count: int
    updated_count: int
    skipped_count: int
    total_source_entries: int
    message: str


class BlacklistToggleRequest(BaseModel):
    """黑名单切换请求"""

    device_serial: str = Field(..., description="设备序列号")
    customer_name: str = Field(..., description="用户名")
    customer_channel: Optional[str] = Field(None, description="渠道 (如 @WeChat)")


# ============================================================================
# API Endpoints
# ============================================================================


@router.get("/blacklist", response_model=List[BlacklistEntry])
async def list_blacklist(
    device_serial: Optional[str] = Query(None, description="按设备筛选"),
    show_all: bool = Query(False, description="显示所有记录（包括已放行的）"),
) -> List[BlacklistEntry]:
    """获取黑名单列表"""
    try:
        writer = BlacklistWriter()

        # Use new method if show_all is True
        if show_all:
            entries = writer.list_blacklist_with_status(device_serial)
        else:
            # Legacy method for backward compatibility (only returns is_blacklisted=1)
            entries = writer.list_blacklist(device_serial)

        return [
            BlacklistEntry(
                id=e["id"],
                device_serial=e["device_serial"],
                customer_name=e["customer_name"],
                customer_channel=e["customer_channel"],
                reason=e["reason"],
                deleted_by_user=e.get("deleted_by_user", False),
                is_blacklisted=e.get("is_blacklisted", True),
                avatar_url=e.get("avatar_url"),
                created_at=e["created_at"],
                updated_at=e["updated_at"],
            )
            for e in entries
        ]
    except Exception as e:
        logger.error(f"Failed to list blacklist: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/blacklist/customers", response_model=List[CustomerWithBlacklistStatus])
async def list_customers_with_status(
    device_serial: str = Query(..., description="设备序列号"),
    search: Optional[str] = Query(None, description="用户名搜索"),
    filter: Optional[str] = Query("all", description="筛选: all/blacklisted/not_blacklisted"),
) -> List[CustomerWithBlacklistStatus]:
    """获取设备的所有用户及其黑名单状态"""
    try:
        writer = BlacklistWriter()
        customers = writer.list_customers_with_status(device_serial, search, filter)

        return [
            CustomerWithBlacklistStatus(
                customer_name=c["customer_name"],
                customer_channel=c["customer_channel"],
                is_blacklisted=c["is_blacklisted"],
                blacklist_reason=c["blacklist_reason"],
                deleted_by_user=c.get("deleted_by_user", False),
                last_message_at=c["last_message_at"],
                message_count=c["message_count"],
            )
            for c in customers
        ]
    except Exception as e:
        logger.error(f"Failed to list customers with status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/blacklist/add")
async def add_to_blacklist(request: BlacklistAddRequest) -> dict:
    """添加用户到黑名单"""
    try:
        writer = BlacklistWriter()
        success = writer.add_to_blacklist(
            device_serial=request.device_serial,
            customer_name=request.customer_name,
            customer_channel=request.customer_channel,
            reason=request.reason or "",
            deleted_by_user=request.deleted_by_user,
        )

        if success:
            return {"success": True, "message": "Added to blacklist"}
        else:
            return {"success": False, "message": "Already in blacklist or failed"}

    except Exception as e:
        logger.error(f"Failed to add to blacklist: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/blacklist/remove")
async def remove_from_blacklist(request: BlacklistRemoveRequest) -> dict:
    """从黑名单移除用户"""
    try:
        writer = BlacklistWriter()
        success = writer.remove_from_blacklist(
            device_serial=request.device_serial,
            customer_name=request.customer_name,
            customer_channel=request.customer_channel,
        )

        if success:
            return {"success": True, "message": "Removed from blacklist"}
        else:
            return {"success": False, "message": "Not in blacklist or failed"}

    except Exception as e:
        logger.error(f"Failed to remove from blacklist: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/blacklist/check", response_model=BlacklistCheckResponse)
async def check_blacklist(
    device_serial: str = Query(..., description="设备序列号"),
    customer_name: str = Query(..., description="用户名"),
    customer_channel: Optional[str] = Query(None, description="渠道"),
) -> BlacklistCheckResponse:
    """检查用户是否在黑名单中（供运行时调用）"""
    try:
        is_blacklisted = BlacklistChecker.is_blacklisted(
            device_serial=device_serial,
            customer_name=customer_name,
            customer_channel=customer_channel,
        )

        # 获取原因（如果存在）
        reason = None
        if is_blacklisted:
            writer = BlacklistWriter()
            reason = writer.get_blacklist_reason(device_serial, customer_name)

        return BlacklistCheckResponse(is_blacklisted=is_blacklisted, reason=reason)

    except Exception as e:
        logger.error(f"Failed to check blacklist: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/blacklist/toggle")
async def toggle_blacklist(request: BlacklistToggleRequest) -> dict:
    """切换用户黑名单状态

    如果用户当前被拉黑（is_blacklisted=1），则设置为放行（is_blacklisted=0）
    如果用户当前未被拉黑（is_blacklisted=0或不存在），则设置为拉黑（is_blacklisted=1）
    """
    try:
        writer = BlacklistWriter()

        # 检查当前状态
        is_currently_blacklisted = BlacklistChecker.is_blacklisted(
            device_serial=request.device_serial,
            customer_name=request.customer_name,
            customer_channel=request.customer_channel,
        )

        if is_currently_blacklisted:
            # 当前是黑名单，切换为放行
            success = writer.remove_from_blacklist(
                device_serial=request.device_serial,
                customer_name=request.customer_name,
                customer_channel=request.customer_channel,
            )
            if success:
                return {"success": True, "message": "User removed from blacklist", "is_blacklisted": False}
            else:
                return {"success": False, "message": "Failed to remove from blacklist"}
        else:
            # 当前不是黑名单，切换为拉黑
            success = writer.add_to_blacklist(
                device_serial=request.device_serial,
                customer_name=request.customer_name,
                customer_channel=request.customer_channel,
                reason="Toggled via Sidecar",
            )
            if success:
                return {"success": True, "message": "User added to blacklist", "is_blacklisted": True}
            else:
                return {"success": False, "message": "Failed to add to blacklist"}

    except Exception as e:
        logger.error(f"Failed to toggle blacklist: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/blacklist/batch-add", response_model=BatchOperationResult)
async def batch_add_to_blacklist(entries: List[BlacklistAddRequest]) -> BatchOperationResult:
    """批量添加到黑名单"""
    writer = BlacklistWriter()
    success_count = 0
    failed_count = 0
    errors = []

    for entry in entries:
        try:
            success = writer.add_to_blacklist(
                device_serial=entry.device_serial,
                customer_name=entry.customer_name,
                customer_channel=entry.customer_channel,
                reason=entry.reason or "",
            )
            if success:
                success_count += 1
            else:
                failed_count += 1
                errors.append(f"{entry.customer_name}: Already in blacklist")
        except Exception as e:
            failed_count += 1
            errors.append(f"{entry.customer_name}: {str(e)}")

    return BatchOperationResult(
        success_count=success_count,
        failed_count=failed_count,
        errors=errors,
    )


@router.post("/blacklist/batch-remove", response_model=BatchOperationResult)
async def batch_remove_from_blacklist(entries: List[BlacklistRemoveRequest]) -> BatchOperationResult:
    """批量从黑名单移除"""
    writer = BlacklistWriter()
    success_count = 0
    failed_count = 0
    errors = []

    for entry in entries:
        try:
            success = writer.remove_from_blacklist(
                device_serial=entry.device_serial,
                customer_name=entry.customer_name,
                customer_channel=entry.customer_channel,
            )
            if success:
                success_count += 1
            else:
                failed_count += 1
                errors.append(f"{entry.customer_name}: Not in blacklist")
        except Exception as e:
            failed_count += 1
            errors.append(f"{entry.customer_name}: {str(e)}")

    return BatchOperationResult(
        success_count=success_count,
        failed_count=failed_count,
        errors=errors,
    )


@router.post("/blacklist/upsert-scanned")
async def upsert_scanned_users(request: UpsertScannedUsersRequest) -> dict:
    """
    批量插入扫描到的用户

    用于全量同步第一阶段：将所有扫描到的用户写入 blacklist 表。
    - 新记录：插入并设置 is_blacklisted=0（默认放行）
    - 已存在：更新 avatar_url，保持原 is_blacklisted 状态
    """
    try:
        writer = BlacklistWriter()

        # Convert Pydantic models to dicts
        users_list = [user.model_dump() for user in request.users]

        result = writer.upsert_scanned_users(
            device_serial=request.device_serial,
            users_list=users_list,
        )

        return {
            "success": True,
            "inserted": result["inserted"],
            "updated": result["updated"],
            "failed": result["failed"],
        }
    except Exception as e:
        logger.error(f"Failed to upsert scanned users: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/blacklist/whitelist/{device_serial}")
async def get_whitelist(device_serial: str) -> List[dict]:
    """
    获取白名单用户列表（is_blacklisted=0 的用户）

    用于全量同步第二阶段：获取允许同步的用户列表
    """
    try:
        writer = BlacklistWriter()
        whitelist: Set[Tuple[str, Optional[str]]] = writer.get_whitelist(device_serial)

        return [{"customer_name": name, "customer_channel": channel} for name, channel in whitelist]
    except Exception as e:
        logger.error(f"Failed to get whitelist: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/blacklist/copy-device", response_model=BlacklistCopyResponse)
async def copy_blacklist_between_devices(request: BlacklistCopyRequest) -> BlacklistCopyResponse:
    """
    复制一个设备的黑名单/放行状态到另一个设备。

    主要用于更换 Android 设备时迁移 blacklist 表中的设备级状态。
    """
    if request.source_device_serial == request.target_device_serial:
        raise HTTPException(status_code=400, detail="Source and target device serials must be different")

    try:
        writer = BlacklistWriter()
        result = writer.copy_device_entries(
            source_device_serial=request.source_device_serial,
            target_device_serial=request.target_device_serial,
            include_allowed=request.include_allowed,
            overwrite_existing=request.overwrite_existing,
        )

        return BlacklistCopyResponse(
            success=True,
            copied_count=result["copied_count"],
            updated_count=result["updated_count"],
            skipped_count=result["skipped_count"],
            total_source_entries=result["total_source_entries"],
            message=(
                f"Copied {result['copied_count']} rows and updated {result['updated_count']} rows "
                f"from {request.source_device_serial} to {request.target_device_serial}"
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as e:
        logger.error(f"Failed to copy blacklist between devices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/blacklist/update-status")
async def update_blacklist_status(request: BlacklistUpdateRequest) -> dict:
    """
    更新单个黑名单条目的状态

    使用 UPDATE 而非 DELETE，保留记录以防止下次扫描时被误判为新用户
    """
    try:
        writer = BlacklistWriter()
        success = writer.update_status(request.id, request.is_blacklisted)

        if success:
            return {"success": True, "message": "Status updated"}
        else:
            return {"success": False, "message": "Failed to update status"}
    except Exception as e:
        logger.error(f"Failed to update blacklist status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/blacklist/batch-update-status")
async def batch_update_blacklist_status(request: BatchUpdateStatusRequest) -> dict:
    """
    批量更新黑名单状态

    使用 UPDATE 而非 DELETE，保留记录以防止下次扫描时被误判为新用户
    """
    try:
        writer = BlacklistWriter()
        result = writer.batch_update_status(request.ids, request.is_blacklisted)

        return {
            "success": True,
            "success_count": result["success_count"],
            "failed_count": result["failed_count"],
        }
    except Exception as e:
        logger.error(f"Failed to batch update blacklist status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
