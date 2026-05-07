"""
WeCom Desktop Backend - FastAPI server for device management and sync orchestration.

This backend provides:
- Device discovery and management via ADB
- Sync orchestration with subprocess isolation per device
- Real-time log streaming via WebSocket
- Integration with existing wecom_automation package
"""

import os
import platform
import sys
import time
from pathlib import Path


# Configure ADB path before importing any modules that use it
# This is important for Windows where adb may not be in the system PATH
def _configure_adb_path():
    """Configure ADB path for async_adbutils and other ADB-using libraries."""
    # Skip if already configured
    if os.environ.get("ADBUTILS_ADB_PATH"):
        return

    # On Windows, use the bundled adb.exe
    if platform.system() == "Windows":
        backend_dir = Path(__file__).parent
        local_adb = backend_dir.parent / "adb" / "adb.exe"
        if local_adb.is_file():
            adb_path = str(local_adb)
            os.environ["ADBUTILS_ADB_PATH"] = adb_path
            os.environ["ADB_PATH"] = adb_path  # Also set for other libs
            print(f"[startup] Using bundled ADB: {adb_path}")
            return

    # On other platforms, try to find adb in PATH
    import shutil

    system_adb = shutil.which("adb")
    if system_adb:
        os.environ["ADBUTILS_ADB_PATH"] = system_adb
        os.environ["ADB_PATH"] = system_adb
        print(f"[startup] Using system ADB: {system_adb}")


_configure_adb_path()

# Add parent directory to path for wecom_automation imports
from utils.path_utils import get_project_root

project_root = get_project_root()

_proj_root_lower = str(project_root).lower()
sys.path = [p for p in sys.path if p.lower().startswith(_proj_root_lower) or "android_run_test" not in p.lower()]
sys.path.insert(0, str(project_root / "src"))

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import (
    ai_config,
    avatars,
    backup,
    blacklist,
    customers,
    dashboard,
    devices,
    email,
    followup_manage,
    global_websocket,
    i18n,
    image_sender,
    kefus,
    log_upload,
    logs,
    media_actions,
    monitoring,
    realtime_reply,
    resources,
    settings,
    sidecar,
    streamers,
    sync,
    webhooks,
)
from services.conversation_storage import DEVICE_STORAGE_ROOT, get_control_db_path, list_device_conversation_targets
from wecom_automation.core.performance import runtime_metrics


def ensure_directories():
    """在应用启动时确保所有必需目录存在"""
    from utils.path_utils import get_project_root

    project_root = get_project_root()

    directories = [
        project_root / "avatars",
        project_root / "conversation_images",
        project_root / "conversation_videos",
        project_root / "conversation_voices",
        DEVICE_STORAGE_ROOT,
        project_root / "logs",  # 全局日志目录
        project_root / "logs" / "metrics",  # 指标日志目录
    ]

    for dir_path in directories:
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
            print(f"[startup] [OK] Ensured directory exists: {dir_path.relative_to(project_root)}")
        except Exception as e:
            print(f"[startup] [FAIL] Failed to create directory {dir_path}: {e}")

    runtime_metrics.set_metrics_dir(project_root / "logs" / "metrics")


def _get_hostname() -> str:
    """从设置中获取主机名"""
    try:
        from services.settings.service import SettingsService

        db_path = str(get_control_db_path())
        settings_service = SettingsService(db_path)
        return settings_service.get_effective_hostname()
    except Exception:
        return "default"


def setup_backend_logging():
    """配置后端服务日志（使用 loguru）"""
    from wecom_automation.core.logging import init_logging

    hostname = _get_hostname()
    print(f"[startup] Initializing logging for hostname: {hostname}")
    init_logging(hostname=hostname, level="INFO", console=True)
    print(f"[startup] Logging: console; per-device file logs/{hostname}-<serial>.log from sync/realtime subprocesses")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.

    On startup: Start background follow-up scanner if enabled in settings.
    On shutdown: Stop background scanner gracefully.
    """
    # ========== STARTUP ==========
    startup_started_at = time.perf_counter()
    print("[startup] Setting up backend logging...")
    setup_backend_logging()

    print("[startup] Ensuring required directories exist...")
    ensure_directories()

    # Layer 2 safety net: clean up realtime-reply subprocess trees left
    # over from a previous uvicorn --reload cycle or an ungraceful
    # shutdown. Because those subprocesses are launched with
    # ``shell=True`` + ``CREATE_NEW_PROCESS_GROUP``, they survive worker
    # restarts and would otherwise fight the fresh subprocess trees that
    # this worker will spawn, causing [Errno 22] swipe failures and the
    # "left/right log alternates freezing" symptom when multiple devices
    # are active.
    try:
        from utils.orphan_process_cleaner import kill_realtime_reply_orphans

        stats = kill_realtime_reply_orphans()
        if stats.get("trees_killed"):
            print(
                f"[startup] [OK] Cleaned up {stats['trees_killed']} orphan "
                f"realtime-reply tree(s) ({stats['processes_killed']} procs)"
            )
        else:
            print("[startup] [OK] No orphan realtime-reply processes found")
    except Exception as e:
        print(f"[startup] [WARN] Orphan realtime-reply cleanup skipped: {e}")

    # Run database migrations
    try:
        from services.media_action_state_migration import migrate_media_action_state_to_control
        from wecom_automation.database.schema import run_migrations

        control_db_path = str(get_control_db_path())
        print(f"[startup] Running control DB migrations: {control_db_path}")
        run_migrations(control_db_path)

        device_targets = list_device_conversation_targets()
        for target in device_targets:
            print(f"[startup] Running device DB migrations: {target.device_serial} -> {target.db_path}")
            run_migrations(str(target.db_path))

        migration_stats = migrate_media_action_state_to_control(control_db_path)
        print(
            "[startup] [OK] Media action state migration: "
            f"blacklist inserted={migration_stats['blacklist_inserted']}, "
            f"blacklist updated={migration_stats['blacklist_updated']}, "
            f"groups inserted={migration_stats['groups_inserted']}, "
            f"groups updated={migration_stats['groups_updated']}, "
            f"sources={migration_stats['source_dbs_scanned']}"
        )
        print("[startup] [OK] Database migrations completed")
    except Exception as e:
        print(f"[startup] [FAIL] Database migration failed: {e}")
        try:
            from wecom_automation.database.schema import repair_blacklist_schema

            repairs = repair_blacklist_schema(str(get_control_db_path()))
            if repairs:
                print(f"[startup] [OK] Applied blacklist fallback repairs: {', '.join(repairs)}")
        except Exception as repair_error:
            print(f"[startup] [FAIL] Blacklist fallback repair failed: {repair_error}")

    # Ensure monitoring tables exist
    try:
        from services.heartbeat_service import ensure_tables as ensure_monitoring_tables

        ensure_monitoring_tables()
        print("[startup] [OK] Monitoring tables ensured")
    except Exception as e:
        print(f"[startup] [FAIL] Monitoring table setup failed: {e}")

    print("[startup] Follow-up system uses multi-device processes; no global startup needed.")

    # Review-gate lifecycle self-healing: pending_reviews recovery,
    # webhook idempotency GC, orphan-image quarantine. Best-effort: any
    # failure is logged and skipped so legacy deployments still boot.
    try:
        from wecom_automation.services.lifecycle import LifecycleService
        from wecom_automation.services.review.storage import ReviewStorage

        review_storage = ReviewStorage(str(get_control_db_path()))
        lifecycle = LifecycleService(storage=review_storage)
        purged = lifecycle.purge_idempotency(ttl_hours=24)
        print(f"[startup] [OK] Webhook idempotency GC purged {purged} stale row(s)")
        # NOTE: orphan image scan and pending recovery rely on per-device
        # state and are scheduled by sync subprocesses to avoid races.
    except Exception as e:
        print(f"[startup] [WARN] Lifecycle self-healing skipped: {e}")

    # Start backup service for admin_actions.xlsx
    from services.backup_service import get_admin_actions_backup_service
    from services.log_upload_service import get_log_upload_service

    backup_service = get_admin_actions_backup_service()
    backup_service.start()
    print(f"[startup] [OK] Backup service started (interval: {backup_service.interval_minutes} min)")

    log_upload_service = get_log_upload_service()
    log_upload_service.start()
    print("[startup] [OK] Log upload service started")
    runtime_metrics.mark_startup_complete()
    print(f"[startup] [OK] Runtime metrics ready ({round((time.perf_counter() - startup_started_at) * 1000, 2)} ms)")

    yield  # Application is running

    # ========== SHUTDOWN ==========
    await log_upload_service.stop()
    print("[shutdown] Log upload service stopped")

    # Stop backup service
    await backup_service.stop()
    print("[shutdown] Backup service stopped")

    print("[shutdown] Follow-up processes should be stopped via device manager if needed")


# Create FastAPI app with lifespan handler
app = FastAPI(
    title="WeCom Desktop Backend",
    description="Backend API for WeCom Desktop application",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware for Electron app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for local development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(avatars.router, prefix="/avatars", tags=["avatars"])
app.include_router(devices.router, prefix="/devices", tags=["devices"])
app.include_router(sync.router, prefix="/sync", tags=["sync"])
app.include_router(logs.router, tags=["logs"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
app.include_router(customers.router, prefix="/customers", tags=["customers"])
app.include_router(kefus.router, prefix="/kefus", tags=["kefus"])
app.include_router(sidecar.router, prefix="/sidecar", tags=["sidecar"])
app.include_router(settings.router, prefix="/settings", tags=["settings"])
app.include_router(streamers.router, prefix="/streamers", tags=["streamers"])
app.include_router(resources.router, prefix="/resources", tags=["resources"])
app.include_router(blacklist.router, prefix="/api", tags=["blacklist"])  # Blacklist system
app.include_router(realtime_reply.router)  # Realtime reply system (has its own prefix /api/realtime)
app.include_router(followup_manage.router)  # Follow-up management (has its own prefix /api/followup)
app.include_router(email.router)  # Email notification (has its own prefix /settings/email)
app.include_router(i18n.router)  # Internationalization (has its own prefix /api/settings)
app.include_router(ai_config.router, prefix="/api/ai", tags=["ai"])  # AI configuration and learning
# Image sender service (send images via Favorites)
app.include_router(image_sender.router, prefix="/api", tags=["image-sender"])
# Global WebSocket for real-time updates across all components
app.include_router(global_websocket.router, tags=["global_websocket"])
# Backup service management
app.include_router(backup.router, prefix="/api/backup", tags=["backup"])
# Log upload service management
app.include_router(log_upload.router, prefix="/api/log-upload", tags=["log-upload"])
# Media auto-actions (auto-blacklist, auto-group-invite on customer media)
app.include_router(media_actions.router, prefix="/api/media-actions", tags=["media-actions"])
# Monitoring endpoints (heartbeat, AI health, process events)
app.include_router(monitoring.router, prefix="/api/monitoring", tags=["monitoring"])
app.include_router(webhooks.router, prefix="/api/webhooks", tags=["webhooks"])

# BOSS Zhipin pivot routers (gated by BOSS_FEATURES_ENABLED env var so the
# legacy backend behavior stays bit-for-bit identical when the flag is off).
from routers import boss_greet as _boss_greet  # noqa: E402
from routers import boss_jobs as _boss_jobs  # noqa: E402
from routers import boss_recruiters as _boss_recruiters  # noqa: E402

if _boss_recruiters.boss_features_enabled():
    app.include_router(_boss_recruiters.router)
if _boss_jobs.boss_features_enabled():
    app.include_router(_boss_jobs.router)
if _boss_greet.boss_features_enabled():
    app.include_router(_boss_greet.router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": "1.0.0",
    }


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "name": "WeCom Desktop Backend",
        "version": "1.0.0",
        "docs": "/docs",
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8765,
        reload=True,
        log_level="info",
        ws_ping_interval=20.0,
        ws_ping_timeout=30.0,
    )
