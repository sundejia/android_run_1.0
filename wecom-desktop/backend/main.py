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


def _emit(phase: str, name: str, message: str, *, level: str = "INFO", **payload) -> None:
    """Print a [startup]/[shutdown] line AND record it in runtime_metrics.

    This is a thin shim so we keep the operator-friendly stdout that
    everyone is used to grepping while *also* feeding structured lifecycle
    events into ``runtime_metrics``. The admin dashboard reads those events
    via ``GET /settings/performance/profile`` (full snapshot) or
    ``GET /api/monitoring/runtime-hygiene`` (lifecycle + hygiene only) so
    operators can answer "what happened at the last boot" without SSH.

    ``level`` maps to "[OK]" / "[WARN]" / "[FAIL]" prefixes that previous
    revisions of this file used inline; passing it through here keeps the
    output identical so log-scraping tooling does not break."""
    prefix_map = {"INFO": "", "WARNING": "[WARN] ", "ERROR": "[FAIL] ", "OK": "[OK] "}
    prefix = prefix_map.get(level.upper(), "")
    print(f"[{phase}] {prefix}{message}")
    try:
        # Normalise OK -> INFO for telemetry; the prefix is purely cosmetic.
        recorded_level = "INFO" if level.upper() == "OK" else level.upper()
        runtime_metrics.record_lifecycle_event(
            phase, name, level=recorded_level, message=message, **payload
        )
    except Exception:
        # Telemetry must never block lifecycle progress.
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.

    On startup: Start background follow-up scanner if enabled in settings.
    On shutdown: Stop background scanner gracefully.
    """
    # ========== STARTUP ==========
    startup_started_at = time.perf_counter()
    _emit("startup", "logging", "Setting up backend logging...")
    setup_backend_logging()

    _emit("startup", "directories", "Ensuring required directories exist...")
    ensure_directories()

    # Run database migrations
    try:
        from services.media_action_state_migration import migrate_media_action_state_to_control
        from wecom_automation.database.schema import run_migrations

        control_db_path = str(get_control_db_path())
        _emit("startup", "db_migrations_control", f"Running control DB migrations: {control_db_path}")
        run_migrations(control_db_path)

        device_targets = list_device_conversation_targets()
        for target in device_targets:
            _emit(
                "startup",
                "db_migrations_device",
                f"Running device DB migrations: {target.device_serial} -> {target.db_path}",
                serial=target.device_serial,
            )
            run_migrations(str(target.db_path))

        migration_stats = migrate_media_action_state_to_control(control_db_path)
        _emit(
            "startup",
            "media_action_migration",
            (
                "Media action state migration: "
                f"blacklist inserted={migration_stats['blacklist_inserted']}, "
                f"blacklist updated={migration_stats['blacklist_updated']}, "
                f"groups inserted={migration_stats['groups_inserted']}, "
                f"groups updated={migration_stats['groups_updated']}, "
                f"sources={migration_stats['source_dbs_scanned']}"
            ),
            level="OK",
            **migration_stats,
        )
        _emit("startup", "db_migrations", "Database migrations completed", level="OK")
    except Exception as e:
        _emit("startup", "db_migrations", f"Database migration failed: {e}", level="ERROR", error=str(e))
        try:
            from wecom_automation.database.schema import repair_blacklist_schema

            repairs = repair_blacklist_schema(str(get_control_db_path()))
            if repairs:
                _emit(
                    "startup",
                    "blacklist_repair",
                    f"Applied blacklist fallback repairs: {', '.join(repairs)}",
                    level="OK",
                    repairs=list(repairs),
                )
        except Exception as repair_error:
            _emit(
                "startup",
                "blacklist_repair",
                f"Blacklist fallback repair failed: {repair_error}",
                level="ERROR",
                error=str(repair_error),
            )

    # Ensure monitoring tables exist
    try:
        from services.heartbeat_service import ensure_tables as ensure_monitoring_tables

        ensure_monitoring_tables()
        _emit("startup", "monitoring_tables", "Monitoring tables ensured", level="OK")
    except Exception as e:
        _emit("startup", "monitoring_tables", f"Monitoring table setup failed: {e}", level="ERROR", error=str(e))

    # Runtime hygiene: kill orphan realtime/droidrun/scrcpy subprocesses
    # left by a previous crash, sweep stale wecom-upload-*.db tempfiles,
    # and reset the local ADB daemon so we never inherit a wedged server.
    # All steps are best-effort; failures are reported but never block start.
    try:
        from services.runtime_hygiene import startup_hygiene

        hygiene_summary = await startup_hygiene()
        orphan = hygiene_summary.get("orphans", {})
        fs = hygiene_summary.get("fs", {})
        adb = hygiene_summary.get("adb", {})
        _emit(
            "startup",
            "runtime_hygiene",
            (
                "Runtime hygiene: "
                f"orphans killed={orphan.get('killed_from_pidfiles', 0)}+"
                f"{orphan.get('killed_from_scan', 0)}, "
                f"temp files removed={fs.get('deleted_temp_files', 0)} "
                f"({fs.get('freed_bytes', 0)} bytes), "
                f"adb reset kill={adb.get('kill_ok')}/start={adb.get('start_ok')}"
            ),
            level="OK",
            orphans_killed_pidfiles=orphan.get("killed_from_pidfiles", 0),
            orphans_killed_scan=orphan.get("killed_from_scan", 0),
            temp_files_removed=fs.get("deleted_temp_files", 0),
            temp_bytes_freed=fs.get("freed_bytes", 0),
            adb_kill_ok=adb.get("kill_ok"),
            adb_start_ok=adb.get("start_ok"),
        )
        # Persist the full structured report separately so the dashboard can
        # render the watched-directory sizes and the (capped) error list.
        runtime_metrics.record_hygiene_report(hygiene_summary)
    except Exception as e:
        _emit("startup", "runtime_hygiene", f"Runtime hygiene failed: {e}", level="ERROR", error=str(e))

    _emit(
        "startup",
        "followup_note",
        "Follow-up system uses multi-device processes; no global startup needed.",
    )

    # Start backup service for admin_actions.xlsx
    from services.backup_service import get_admin_actions_backup_service
    from services.log_upload_service import get_log_upload_service

    backup_service = get_admin_actions_backup_service()
    backup_service.start()
    _emit(
        "startup",
        "backup_service",
        f"Backup service started (interval: {backup_service.interval_minutes} min)",
        level="OK",
        interval_minutes=backup_service.interval_minutes,
    )

    log_upload_service = get_log_upload_service()
    log_upload_service.start()
    _emit("startup", "log_upload_service", "Log upload service started", level="OK")
    runtime_metrics.mark_startup_complete()
    _emit(
        "startup",
        "runtime_metrics_ready",
        f"Runtime metrics ready ({round((time.perf_counter() - startup_started_at) * 1000, 2)} ms)",
        level="OK",
        startup_duration_ms=round((time.perf_counter() - startup_started_at) * 1000, 2),
    )

    yield  # Application is running

    # ========== SHUTDOWN ==========
    await log_upload_service.stop()
    _emit("shutdown", "log_upload_service", "Log upload service stopped")

    # Stop backup service
    await backup_service.stop()
    _emit("shutdown", "backup_service", "Backup service stopped")

    # Bring down all per-device realtime_reply subprocesses BEFORE clearing
    # PID files. Previously this branch only printed a "should be stopped"
    # comment, which is what caused orphan ``realtime_reply_process`` /
    # ``droidrun`` / ``scrcpy`` processes to survive backend restarts and
    # accumulate as silent leaks.
    try:
        from services.realtime_reply_manager import get_realtime_reply_manager

        manager = get_realtime_reply_manager()
        device_count = manager.get_active_realtime_count()
        await manager.stop_all()
        _emit(
            "shutdown",
            "realtime_stop_all",
            "All realtime reply processes stopped",
            level="OK",
            stopped_count=device_count,
        )
    except Exception as e:
        _emit(
            "shutdown",
            "realtime_stop_all",
            f"Failed to stop realtime reply processes: {e}",
            level="WARNING",
            error=str(e),
        )

    try:
        from services.runtime_hygiene import shutdown_hygiene

        shutdown_hygiene()
        _emit("shutdown", "runtime_hygiene", "Runtime hygiene cleared")
    except Exception as e:
        _emit(
            "shutdown",
            "runtime_hygiene",
            f"Runtime hygiene shutdown failed: {e}",
            level="WARNING",
            error=str(e),
        )


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
    )
