"""
Follow-up Management API Router

管理补刀跟进系统（Phase 2）：
- 设置管理（Settings）
- 统计分析（Analytics）
- 跟进尝试记录（Attempts）
- 数据导出（Export）
- 候选客户管理（未来开发）
"""

import sqlite3
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from services.conversation_storage import get_control_db_path

router = APIRouter(prefix="/api/followup", tags=["followup"])

DB_PATH = get_control_db_path()


# ============================================
# Settings Models
# ============================================


class FollowUpSettingsModel(BaseModel):
    """补刀功能设置"""

    followupEnabled: bool = False
    maxFollowupPerScan: int = 5
    useAIReply: bool = False
    enableOperatingHours: bool = False
    startHour: str = "09:00"
    endHour: str = "18:00"
    followupMessageTemplates: list[str] = [
        "Hello, have you considered our offer?",
        "Feel free to contact me if you have any questions",
    ]
    followupPrompt: str = ""
    idleThresholdMinutes: int = 30
    maxAttemptsPerCustomer: int = 3
    attemptIntervals: list[int] = [60, 120, 180]
    avoidDuplicateMessages: bool = False


# ============================================
# Settings Endpoints
# ============================================


@router.get("/settings", response_model=FollowUpSettingsModel)
async def get_followup_settings():
    """获取补刀功能设置"""
    try:
        from services.settings import get_settings_service

        service = get_settings_service()
        followup = service.get_followup_settings()

        return FollowUpSettingsModel(
            followupEnabled=followup.followup_enabled,
            maxFollowupPerScan=followup.max_followups,
            useAIReply=followup.use_ai_reply,
            enableOperatingHours=followup.enable_operating_hours,
            startHour=followup.start_hour,
            endHour=followup.end_hour,
            followupMessageTemplates=followup.message_templates or [],
            followupPrompt=getattr(followup, "followup_prompt", ""),
            idleThresholdMinutes=getattr(followup, "idle_threshold_minutes", 30),
            maxAttemptsPerCustomer=getattr(followup, "max_attempts_per_customer", 3),
            attemptIntervals=getattr(followup, "attempt_intervals", [60, 120, 180]),
            avoidDuplicateMessages=getattr(followup, "avoid_duplicate_messages", False),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load followup settings: {str(e)}")


@router.post("/settings")
async def update_followup_settings(settings: FollowUpSettingsModel):
    """更新补刀功能设置"""
    try:
        from services.settings import SettingCategory, get_settings_service

        service = get_settings_service()

        updates = {
            "followup_enabled": settings.followupEnabled,
            "max_followups": settings.maxFollowupPerScan,
            "use_ai_reply": settings.useAIReply,
            "enable_operating_hours": settings.enableOperatingHours,
            "start_hour": settings.startHour,
            "end_hour": settings.endHour,
            "message_templates": settings.followupMessageTemplates,
            "followup_prompt": settings.followupPrompt,
            "idle_threshold_minutes": settings.idleThresholdMinutes,
            "max_attempts_per_customer": settings.maxAttemptsPerCustomer,
            "attempt_intervals": settings.attemptIntervals,
            "avoid_duplicate_messages": settings.avoidDuplicateMessages,
        }

        service.set_category(SettingCategory.FOLLOWUP.value, updates, "api")

        return {"success": True, "message": "Followup settings saved successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save followup settings: {str(e)}")


# ============================================
# Data Models
# ============================================


class FollowUpAttempt(BaseModel):
    """跟进尝试记录"""

    id: int
    userId: str
    attemptNumber: int
    status: str  # pending / in_progress / completed / cancelled
    messagePreview: str
    createdAt: str
    responded: bool
    responseTime: int | None = None


class FollowUpAnalytics(BaseModel):
    """跟进系统统计分析"""

    totalAttempts: int
    responseRate: float
    avgResponseTime: float | None
    successful: int
    failed: int
    attemptBreakdown: dict
    trends7Days: list
    trends30Days: list
    responseRateTrend: list


class AttemptListResponse(BaseModel):
    """跟进尝试列表响应"""

    items: list[FollowUpAttempt]
    total: int
    page: int
    pageSize: int


# ============================================
# Database Helper
# ============================================

_tables_initialized = False


def _ensure_followup_tables(conn):
    """确保跟进相关表存在

    注意：表的实际创建由 attempts_repository.py 负责
    这里只做兼容性检查，不再重复创建表以避免结构冲突

    正确的表结构在 attempts_repository.py 中定义：
    - device_serial TEXT (设备序列号)
    - customer_name TEXT (客户名称)
    - current_attempt INTEGER (当前尝试次数)
    - max_attempts INTEGER (最大尝试次数)
    - status TEXT (状态: pending/completed/cancelled)
    - last_kefu_message_id TEXT
    - last_followup_at DATETIME
    等
    """
    global _tables_initialized
    if _tables_initialized:
        return

    cursor = conn.cursor()

    # 检查表是否存在，如果不存在则创建（使用正确的结构）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS followup_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_serial TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            customer_id TEXT,

            last_kefu_message_id TEXT NOT NULL,
            last_kefu_message_time DATETIME,
            last_checked_message_id TEXT,

            max_attempts INTEGER NOT NULL DEFAULT 3,
            current_attempt INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',

            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_followup_at DATETIME,

            UNIQUE(device_serial, customer_name)
        )
    """)

    # 检查表是否有正确的列结构
    # 如果是旧表，可能缺少 device_serial 等列
    cursor.execute("PRAGMA table_info(followup_attempts)")
    columns = {row[1] for row in cursor.fetchall()}

    # 只有当表有正确的列时才创建索引
    if "device_serial" in columns and "status" in columns:
        try:
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_followup_attempts_device_status
                ON followup_attempts(device_serial, status)
            """)
        except sqlite3.OperationalError as e:
            # 索引创建失败，记录但不阻止初始化
            import logging

            logging.getLogger("followup_manage").warning(f"Failed to create device_status index: {e}")

    if "created_at" in columns:
        try:
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_followup_attempts_date
                ON followup_attempts(created_at)
            """)
        except sqlite3.OperationalError as e:
            import logging

            logging.getLogger("followup_manage").warning(f"Failed to create date index: {e}")
    else:
        # 旧表结构，记录警告
        import logging

        logging.getLogger("followup_manage").warning(
            "followup_attempts table has old structure, some features may not work. "
            "Consider deleting the old table to let the system recreate it."
        )

    conn.commit()
    _tables_initialized = True


def get_db_connection():
    """获取数据库连接（带 busy_timeout/WAL 容错，避免与多设备 realtime_reply 互踩）"""
    from services.conversation_storage import open_shared_sqlite

    conn = open_shared_sqlite(str(DB_PATH), row_factory=True)
    _ensure_followup_tables(conn)
    return conn


def _normalize_attempt_status_filter(status: str) -> str:
    """Map legacy frontend filters onto persisted attempt statuses."""
    legacy_aliases = {
        "sent": "completed",
        "skipped": "cancelled",
    }
    return legacy_aliases.get(status, status)


# ============================================
# Analytics Endpoints
# ============================================


@router.get("/analytics", response_model=FollowUpAnalytics)
async def get_analytics():
    """获取跟进系统统计分析

    注意：使用正确的字段名匹配 attempts_repository.py 创建的表结构
    - current_attempt 替代 attempt_number
    - status='completed' 替代 responded=1
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 总尝试次数（current_attempt > 0 表示至少尝试过一次）
        cursor.execute("SELECT COUNT(*) FROM followup_attempts WHERE current_attempt > 0")
        total = cursor.fetchone()[0]

        # 成功完成（status = completed，表示客户已回复或达到上限）
        cursor.execute("SELECT COUNT(*) FROM followup_attempts WHERE status = 'completed'")
        successful = cursor.fetchone()[0]

        # 取消/失败
        cursor.execute("SELECT COUNT(*) FROM followup_attempts WHERE status = 'cancelled'")
        failed = cursor.fetchone()[0]

        # 已回复数量（completed 状态视为已回复）
        responded_count = successful

        # 回复率
        response_rate = (responded_count / total * 100) if total > 0 else 0.0

        # 平均回复时间（从最后补刀到完成的时间差）
        cursor.execute("""
            SELECT AVG(
                CAST((julianday(updated_at) - julianday(last_followup_at)) * 86400 AS INTEGER)
            )
            FROM followup_attempts
            WHERE status = 'completed' AND last_followup_at IS NOT NULL
        """)
        avg_response_time = cursor.fetchone()[0]

        # 按尝试次数分组统计（使用 current_attempt）
        cursor.execute("SELECT COUNT(*) FROM followup_attempts WHERE current_attempt = 1")
        first_attempts = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM followup_attempts WHERE current_attempt = 2")
        second_attempts = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM followup_attempts WHERE current_attempt >= 3")
        third_attempts = cursor.fetchone()[0]

        # 7天趋势
        trends_7days = []
        for i in range(7):
            date = datetime.now() - timedelta(days=6 - i)
            date_str = date.strftime("%Y-%m-%d")
            display_date = date.strftime("%m-%d")

            cursor.execute(
                """
                SELECT
                    COUNT(*) as attempts,
                    SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as failed
                FROM followup_attempts
                WHERE date(created_at) = ? AND current_attempt > 0
            """,
                (date_str,),
            )
            row = cursor.fetchone()

            trends_7days.append(
                {
                    "date": display_date,
                    "scans": 0,
                    "attempts": row[0] if row else 0,
                    "failed": row[1] if row and row[1] else 0,
                }
            )

        # 30天趋势
        trends_30days = []
        for i in range(30):
            date = datetime.now() - timedelta(days=29 - i)
            date_str = date.strftime("%Y-%m-%d")
            display_date = date.strftime("%m-%d")

            cursor.execute(
                """
                SELECT
                    COUNT(*) as attempts,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as responses
                FROM followup_attempts
                WHERE date(created_at) = ? AND current_attempt > 0
            """,
                (date_str,),
            )
            row = cursor.fetchone()

            trends_30days.append(
                {"date": display_date, "attempts": row[0] if row else 0, "responses": row[1] if row and row[1] else 0}
            )

        # 回复率趋势（最近7天）
        response_trend = []
        for i in range(7):
            date = datetime.now() - timedelta(days=6 - i)
            date_str = date.strftime("%Y-%m-%d")
            display_date = date.strftime("%m-%d")

            cursor.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as responded
                FROM followup_attempts
                WHERE date(created_at) = ? AND current_attempt > 0
            """,
                (date_str,),
            )
            row = cursor.fetchone()

            day_total = row[0] if row else 0
            day_responded = row[1] if row and row[1] else 0
            day_rate = (day_responded / day_total * 100) if day_total > 0 else 0

            response_trend.append({"date": display_date, "rate": round(day_rate, 1)})

        return FollowUpAnalytics(
            totalAttempts=total,
            responseRate=round(response_rate, 1),
            avgResponseTime=round(avg_response_time, 1) if avg_response_time else None,
            successful=successful,
            failed=failed,
            attemptBreakdown={"first": first_attempts, "second": second_attempts, "third": third_attempts},
            trends7Days=trends_7days,
            trends30Days=trends_30days,
            responseRateTrend=response_trend,
        )
    finally:
        conn.close()


@router.get("/attempts", response_model=AttemptListResponse)
async def get_attempts(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    status: str = Query("All"),
    responded: str = Query("All"),
    dateFrom: str | None = None,
    dateTo: str | None = None,
    userId: str | None = None,
    device_serial: str | None = None,
):
    """获取跟进尝试记录列表（分页+过滤）

    注意：此 API 从 followup_attempts 表读取数据，
    该表由 attempts_repository.py 写入，字段映射如下：
    - customer_name -> userId (直接存储客户名称)
    - current_attempt -> attemptNumber
    - status -> status (pending/completed/cancelled)
    - last_kefu_message_id -> messagePreview (暂用消息ID作为预览)
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 构建查询条件
        where_clauses = []
        params = []

        # 必须指定设备
        if device_serial:
            where_clauses.append("fa.device_serial = ?")
            params.append(device_serial)

        normalized_status = _normalize_attempt_status_filter(status)
        if normalized_status != "All":
            where_clauses.append("fa.status = ?")
            params.append(normalized_status)

        # 注意：实际表中没有 responded 字段，补刀完成后 status 变为 completed
        # 这里我们将 completed 视为"已收到回复"
        if responded == "yes":
            where_clauses.append("fa.status = 'completed'")
        elif responded == "no":
            where_clauses.append("fa.status != 'completed'")

        if dateFrom:
            where_clauses.append("date(fa.created_at) >= ?")
            params.append(dateFrom)

        if dateTo:
            where_clauses.append("date(fa.created_at) <= ?")
            params.append(dateTo)

        if userId:
            where_clauses.append("fa.customer_name LIKE ?")
            params.append(f"%{userId}%")

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        # 总数
        count_sql = f"""
            SELECT COUNT(*)
            FROM followup_attempts fa
            WHERE {where_sql}
        """
        cursor.execute(count_sql, params)
        total = cursor.fetchone()[0]

        # 分页查询 - 使用正确的字段名
        offset = (page - 1) * pageSize
        query_sql = f"""
            SELECT
                fa.id,
                fa.customer_name,
                fa.current_attempt,
                fa.max_attempts,
                fa.status,
                fa.last_kefu_message_id,
                fa.created_at,
                fa.updated_at,
                fa.last_followup_at
            FROM followup_attempts fa
            WHERE {where_sql}
            ORDER BY fa.updated_at DESC
            LIMIT ? OFFSET ?
        """
        cursor.execute(query_sql, params + [pageSize, offset])

        items = []
        for row in cursor.fetchall():
            created_at = row["created_at"]
            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    created_at = dt.strftime("%Y/%m/%d %H:%M")
                except Exception:
                    pass

            # 计算响应时间（如果已完成且有 last_followup_at）
            response_time = None
            if row["status"] == "completed" and row["last_followup_at"] and row["updated_at"]:
                try:
                    followup_time = datetime.fromisoformat(row["last_followup_at"])
                    updated_time = datetime.fromisoformat(row["updated_at"])
                    response_time = int((updated_time - followup_time).total_seconds())
                except Exception:
                    pass

            # 生成消息预览（基于状态）
            status_val = row["status"]
            if status_val == "pending":
                msg_preview = f"等待第 {row['current_attempt'] + 1}/{row['max_attempts']} 次补刀"
            elif status_val == "completed":
                msg_preview = f"已完成 {row['current_attempt']}/{row['max_attempts']} 次补刀"
            else:
                msg_preview = f"状态: {status_val}"

            items.append(
                FollowUpAttempt(
                    id=row["id"],
                    userId=row["customer_name"],
                    attemptNumber=row["current_attempt"],
                    status=row["status"],
                    messagePreview=msg_preview,
                    createdAt=created_at or "-",
                    responded=(row["status"] == "completed"),
                    responseTime=response_time,
                )
            )

        return AttemptListResponse(items=items, total=total, page=page, pageSize=pageSize)
    finally:
        conn.close()


@router.delete("/attempts")
async def delete_all_attempts(device_serial: str | None = None):
    """删除跟进尝试记录，可按设备删除"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if device_serial:
            cursor.execute("DELETE FROM followup_attempts WHERE device_serial = ?", (device_serial,))
            message = f"Attempts deleted for device {device_serial}"
        else:
            cursor.execute("DELETE FROM followup_attempts")
            message = "All attempts deleted"
        conn.commit()
        return {"success": True, "message": message}
    finally:
        conn.close()


@router.delete("/attempts/{attempt_id}")
async def delete_attempt(attempt_id: int):
    """删除单条跟进尝试记录"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM followup_attempts WHERE id = ?", (attempt_id,))
        conn.commit()

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Attempt not found")

        return {"success": True, "message": "Attempt deleted successfully"}
    finally:
        conn.close()


@router.get("/export")
async def export_data(format: str = Query("csv"), device_serial: str | None = None):
    """导出跟进数据为 CSV 或 Excel

    使用正确的字段名匹配 attempts_repository.py 创建的表结构
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 构建查询条件
        where_clause = ""
        params = []
        if device_serial:
            where_clause = "WHERE fa.device_serial = ?"
            params.append(device_serial)

        cursor.execute(
            f"""
            SELECT
                fa.id,
                fa.device_serial,
                fa.customer_name,
                fa.current_attempt,
                fa.max_attempts,
                fa.status,
                fa.last_kefu_message_id,
                fa.created_at,
                fa.updated_at,
                fa.last_followup_at
            FROM followup_attempts fa
            {where_clause}
            ORDER BY fa.updated_at DESC
            LIMIT 10000
        """,
            params,
        )

        rows = cursor.fetchall()

        if format == "csv":
            headers = "ID,Device,Customer,Attempt,Max Attempts,Status,Created At,Updated At,Last Followup At\n"
            csv_rows = []
            for row in rows:
                # 处理日期格式
                created_at = row["created_at"] or ""
                updated_at = row["updated_at"] or ""
                last_followup = row["last_followup_at"] or ""

                # 生成消息预览
                status = row["status"]
                msg_preview = f"{row['current_attempt']}/{row['max_attempts']} 次补刀 ({status})"

                csv_rows.append(
                    f"{row['id']},{row['device_serial']},{row['customer_name']},"
                    f"{row['current_attempt']},{row['max_attempts']},{status},"
                    f"{created_at},{updated_at},{last_followup}"
                )

            content = headers + "\n".join(csv_rows)

            return Response(
                content=content,
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=followup_export.csv"},
            )

        elif format == "xlsx":
            # Excel 格式（生产环境可使用 openpyxl）
            headers = "ID,Device,Customer,Attempt,Max Attempts,Status,Created At,Updated At,Last Followup At\n"
            csv_rows = []
            for row in rows:
                created_at = row["created_at"] or ""
                updated_at = row["updated_at"] or ""
                last_followup = row["last_followup_at"] or ""
                status = row["status"]

                csv_rows.append(
                    f"{row['id']},{row['device_serial']},{row['customer_name']},"
                    f"{row['current_attempt']},{row['max_attempts']},{status},"
                    f"{created_at},{updated_at},{last_followup}"
                )

            content = headers + "\n".join(csv_rows)

            return Response(
                content=content,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": "attachment; filename=followup_export.xlsx"},
            )

        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")
    finally:
        conn.close()


# ============================================
# Candidate Management (Phase 2 - 未来开发)
# ============================================


@router.get("/candidates")
async def get_candidates():
    """
    获取补刀候选客户列表（Phase 2 - 待实现）

    未来功能：
    - 查询冷却期结束的客户
    - 返回候选人列表和优先级
    - 支持设备/客服过滤
    """
    # 占位实现，返回空列表
    return {"candidates": [], "total": 0, "message": "Phase 2 feature - not yet implemented"}


@router.post("/trigger/{customer_id}")
async def trigger_followup(customer_id: int):
    """
    手动触发补刀跟进（Phase 2 - 待实现）

    未来功能：
    - 手动为特定客户触发补刀
    - 支持自定义消息
    - 记录手动触发的历史
    """
    raise HTTPException(status_code=501, detail="Phase 2 feature - not yet implemented")
