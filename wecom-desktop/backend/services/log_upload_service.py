"""
Scheduled log upload service for android_run_test.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from services.log_upload_client import LogUploadClient
from services.log_upload_repository import LogUploadRepository
from services.settings.service import get_settings_service
from utils.path_utils import get_project_root
from wecom_automation.core.config import get_default_db_path

logger = logging.getLogger(__name__)


@dataclass
class PendingUploadFile:
    source_path: Path
    upload_path: Path
    upload_kind: str
    original_filename: str
    file_size: int
    mtime: float
    checksum: str
    cleanup_after_upload: bool = False


class LogUploadService:
    """Daily scheduler and manual uploader for log files."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._project_root = get_project_root()
        self._repository = LogUploadRepository(db_path)
        self._client = LogUploadClient()
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._upload_lock = asyncio.Lock()
        self._poll_interval_seconds = 30

    def _settings(self):
        return get_settings_service(self._db_path)

    @staticmethod
    def _sanitize_hostname(hostname: str | None) -> str:
        raw = (hostname or "").strip()
        if not raw:
            return "default"
        return raw.replace("/", "-").replace("\\", "-").replace(" ", "_")

    def _load_config(self) -> dict[str, Any]:
        settings_service = self._settings()
        timezone_name = settings_service.get("general", "timezone", "Asia/Shanghai")
        return {
            "hostname": self._sanitize_hostname(
                settings_service.get_effective_hostname()
            ),
            "device_id": settings_service.get_device_id(),
            "person_name": settings_service.get_effective_person_name(),
            "enabled": bool(
                settings_service.get("general", "log_upload_enabled", False)
            ),
            "upload_time": str(
                settings_service.get("general", "log_upload_time", "02:00")
            ),
            "upload_url": str(
                settings_service.get("general", "log_upload_url", "")
            ).strip(),
            "upload_token": str(
                settings_service.get("general", "log_upload_token", "")
            ).strip(),
            "timezone": timezone_name or "Asia/Shanghai",
        }

    @staticmethod
    def _parse_time(value: str) -> time | None:
        try:
            return time.fromisoformat(value.strip())
        except (TypeError, ValueError, AttributeError):
            return None

    @staticmethod
    def _zoneinfo(name: str) -> ZoneInfo:
        try:
            return ZoneInfo(name)
        except Exception:
            return ZoneInfo("Asia/Shanghai")

    def _now(self, timezone_name: str) -> datetime:
        return datetime.now(self._zoneinfo(timezone_name))

    def _compute_next_run_at(self, config: dict[str, Any]) -> str | None:
        if not config["enabled"]:
            return None
        scheduled_time = self._parse_time(config["upload_time"])
        if scheduled_time is None:
            return None
        tz = self._zoneinfo(config["timezone"])
        now = datetime.now(tz)
        target = datetime.combine(now.date(), scheduled_time, tzinfo=tz)
        if now >= target:
            target += timedelta(days=1)
        return target.isoformat()

    def _get_schedule_validation_error(self, config: dict[str, Any]) -> str | None:
        if not config["enabled"]:
            return "Log upload is disabled"
        if self._parse_time(config["upload_time"]) is None:
            return "Invalid log upload time"
        if not config["upload_url"]:
            return "Log upload URL is not configured"
        if not config["upload_token"]:
            return "Log upload token is not configured"
        return None

    def _collect_pending_files(self, hostname: str) -> list[PendingUploadFile]:
        files: list[PendingUploadFile] = []

        db_path = get_default_db_path()
        if (
            db_path.exists()
            and db_path.is_file()
            and self._looks_like_wecom_database(db_path)
        ):
            snapshot = self._create_database_snapshot(db_path)
            if snapshot is not None:
                files.append(
                    self._build_file_record(
                        db_path,
                        "wecom-db",
                        upload_path=snapshot,
                        cleanup_after_upload=True,
                    )
                )

        metrics_dir = self._project_root / "logs" / "metrics"
        if metrics_dir.exists():
            for path in sorted(metrics_dir.iterdir()):
                if not path.is_file():
                    continue
                if ".jsonl" not in path.name:
                    continue
                if hostname and not path.name.startswith(f"{hostname}-"):
                    continue
                files.append(self._build_file_record(path, "metrics-jsonl"))

        logs_dir = self._project_root / "logs"
        if logs_dir.exists():
            for path in sorted(logs_dir.iterdir()):
                if not path.is_file():
                    continue
                if ".log" not in path.name:
                    continue
                if hostname and not path.name.startswith(f"{hostname}-"):
                    continue
                upload_kind = "scanner-log"
                files.append(self._build_file_record(path, upload_kind))

        files.sort(key=lambda item: (item.upload_kind, item.mtime, item.original_filename))
        return files

    def _build_file_record(
        self,
        path: Path,
        upload_kind: str,
        *,
        upload_path: Path | None = None,
        cleanup_after_upload: bool = False,
    ) -> PendingUploadFile:
        materialized_path = upload_path or path
        stat = materialized_path.stat()
        return PendingUploadFile(
            source_path=path,
            upload_path=materialized_path,
            upload_kind=upload_kind,
            original_filename=path.name,
            file_size=stat.st_size,
            mtime=stat.st_mtime,
            checksum=self._compute_checksum(materialized_path),
            cleanup_after_upload=cleanup_after_upload,
        )

    @staticmethod
    def _compute_checksum(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _looks_like_wecom_database(path: Path) -> bool:
        try:
            conn = sqlite3.connect(str(path))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('customers', 'messages')"
            )
            names = {row[0] for row in cursor.fetchall()}
            conn.close()
            return {"customers", "messages"}.issubset(names)
        except Exception:
            return False

    @staticmethod
    def _create_database_snapshot(path: Path) -> Path | None:
        tmp = tempfile.NamedTemporaryFile(prefix="wecom-upload-", suffix=".db", delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()
        try:
            source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            target = sqlite3.connect(str(tmp_path))
            with target:
                source.backup(target)
            source.close()
            target.close()
            return tmp_path
        except Exception:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            return None

    def get_status(self) -> dict[str, Any]:
        config = self._load_config()
        return {
            "running": self._running,
            "enabled": config["enabled"],
            "hostname": config["hostname"],
            "device_id": config["device_id"],
            "person_name": config["person_name"],
            "upload_time": config["upload_time"],
            "upload_url": config["upload_url"],
            "has_token": bool(config["upload_token"]),
            "timezone": config["timezone"],
            "is_uploading": self._upload_lock.locked(),
            "config_error": self._get_schedule_validation_error(config)
            if config["enabled"]
            else None,
            "next_run_at": self._compute_next_run_at(config),
            "last_run": self._repository.get_last_run(),
        }

    def _should_run_schedule(self, config: dict[str, Any]) -> bool:
        if self._get_schedule_validation_error(config):
            return False

        scheduled_time = self._parse_time(config["upload_time"])
        if scheduled_time is None:
            return False

        tz = self._zoneinfo(config["timezone"])
        now = datetime.now(tz)
        scheduled_at = datetime.combine(now.date(), scheduled_time, tzinfo=tz)
        if now < scheduled_at:
            return False

        last_schedule_run = self._repository.get_last_run("schedule")
        if not last_schedule_run or not last_schedule_run.get("started_at"):
            return True

        try:
            previous = datetime.fromisoformat(last_schedule_run["started_at"])
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=tz)
            else:
                previous = previous.astimezone(tz)
            return previous.date() < now.date()
        except ValueError:
            return True

    async def _scheduler_loop(self) -> None:
        logger.info("[log-upload] Scheduler loop started")
        while self._running:
            try:
                config = self._load_config()
                if self._should_run_schedule(config):
                    await self.run_once(trigger_source="schedule")
                await asyncio.sleep(self._poll_interval_seconds)
            except asyncio.CancelledError:
                logger.info("[log-upload] Scheduler loop cancelled")
                raise
            except Exception as exc:
                logger.exception("[log-upload] Scheduler loop failed: %s", exc)
                await asyncio.sleep(self._poll_interval_seconds)
        logger.info("[log-upload] Scheduler loop stopped")

    def start(self) -> None:
        if self._running:
            logger.warning("[log-upload] Service already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("[log-upload] Service started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("[log-upload] Service stopped")

    async def run_once(self, trigger_source: str = "manual") -> dict[str, Any]:
        if self._upload_lock.locked():
            return {
                "success": False,
                "status": "busy",
                "message": "Log upload is already running",
            }

        async with self._upload_lock:
            config = self._load_config()
            started_at = self._now(config["timezone"])
            run_id = self._repository.start_run(trigger_source, started_at)

            schedule_error = self._get_schedule_validation_error(config)
            if trigger_source == "schedule" and schedule_error:
                completed_at = self._now(config["timezone"])
                self._repository.finish_run(
                    run_id,
                    status="error",
                    completed_at=completed_at,
                    files_total=0,
                    files_uploaded=0,
                    files_skipped=0,
                    error_message=schedule_error,
                )
                return {
                    "success": False,
                    "status": "error",
                    "message": schedule_error,
                    "run_id": run_id,
                }

            if not config["upload_url"]:
                message = "Log upload URL is not configured"
                completed_at = self._now(config["timezone"])
                self._repository.finish_run(
                    run_id,
                    status="error",
                    completed_at=completed_at,
                    files_total=0,
                    files_uploaded=0,
                    files_skipped=0,
                    error_message=message,
                )
                return {
                    "success": False,
                    "status": "error",
                    "message": message,
                    "run_id": run_id,
                }

            if not config["upload_token"]:
                message = "Log upload token is not configured"
                completed_at = self._now(config["timezone"])
                self._repository.finish_run(
                    run_id,
                    status="error",
                    completed_at=completed_at,
                    files_total=0,
                    files_uploaded=0,
                    files_skipped=0,
                    error_message=message,
                )
                return {
                    "success": False,
                    "status": "error",
                    "message": message,
                    "run_id": run_id,
                }

            pending_files = self._collect_pending_files(config["hostname"])
            if not pending_files:
                completed_at = self._now(config["timezone"])
                self._repository.finish_run(
                    run_id,
                    status="success",
                    completed_at=completed_at,
                    files_total=0,
                    files_uploaded=0,
                    files_skipped=0,
                    details={"errors": [], "uploaded_files": []},
                )
                return {
                    "success": True,
                    "status": "success",
                    "message": "No log files found to upload",
                    "run_id": run_id,
                    "files_total": 0,
                    "files_uploaded": 0,
                    "files_skipped": 0,
                    "errors": [],
                }

            uploaded_files: list[dict[str, Any]] = []
            errors: list[str] = []
            files_uploaded = 0
            files_skipped = 0

            for item in pending_files:
                try:
                    if self._repository.has_successful_upload(
                        hostname=config["hostname"],
                        upload_kind=item.upload_kind,
                        original_filename=item.original_filename,
                        checksum=item.checksum,
                    ):
                        files_skipped += 1
                        continue

                    result = await self._client.upload_file(
                        base_url=config["upload_url"],
                        token=config["upload_token"],
                        device_id=config["device_id"],
                        hostname=config["hostname"],
                        person_name=config["person_name"],
                        upload_kind=item.upload_kind,
                        checksum=item.checksum,
                        uploaded_at=started_at,
                        file_path=item.upload_path,
                    )

                    if result["success"]:
                        files_uploaded += 1
                        uploaded_files.append(
                            {
                                "upload_kind": item.upload_kind,
                                "filename": item.original_filename,
                                "stored_path": result["data"].get("stored_path"),
                                "import_status": result["data"].get("import_status"),
                            }
                        )
                        self._repository.upsert_file_result(
                            hostname=config["hostname"],
                            upload_kind=item.upload_kind,
                            original_filename=item.original_filename,
                            file_path=str(item.source_path),
                            checksum=item.checksum,
                            file_size=item.file_size,
                            mtime=item.mtime,
                            status="success",
                            uploaded_at=started_at,
                            run_id=run_id,
                            response=result["data"],
                        )
                    else:
                        error_message = f"{item.original_filename}: {result['error']}"
                        errors.append(error_message)
                        self._repository.upsert_file_result(
                            hostname=config["hostname"],
                            upload_kind=item.upload_kind,
                            original_filename=item.original_filename,
                            file_path=str(item.source_path),
                            checksum=item.checksum,
                            file_size=item.file_size,
                            mtime=item.mtime,
                            status="error",
                            uploaded_at=started_at,
                            run_id=run_id,
                            last_error=error_message,
                            response=result,
                        )
                finally:
                    if item.cleanup_after_upload:
                        try:
                            os.remove(item.upload_path)
                        except OSError:
                            pass

            completed_at = self._now(config["timezone"])
            status = (
                "success"
                if not errors
                else "partial"
                if files_uploaded > 0
                else "error"
            )
            if status == "success" and files_uploaded == 0 and files_skipped > 0:
                message = "All matching log files were already uploaded"
            elif status == "success":
                message = "Log upload completed successfully"
            elif status == "partial":
                message = "Log upload completed with partial failures"
            else:
                message = "Log upload failed"
            details = {
                "errors": errors,
                "uploaded_files": uploaded_files,
            }
            self._repository.finish_run(
                run_id,
                status=status,
                completed_at=completed_at,
                files_total=len(pending_files),
                files_uploaded=files_uploaded,
                files_skipped=files_skipped,
                error_message="\n".join(errors) if errors else None,
                details=details,
            )
            return {
                "success": status != "error",
                "status": status,
                "message": message,
                "run_id": run_id,
                "files_total": len(pending_files),
                "files_uploaded": files_uploaded,
                "files_skipped": files_skipped,
                "errors": errors,
                "uploaded_files": uploaded_files,
            }


_log_upload_service: Optional[LogUploadService] = None


def get_log_upload_service(db_path: Optional[str] = None) -> LogUploadService:
    """Get or create the log upload service singleton."""
    global _log_upload_service

    if _log_upload_service is None:
        resolved_db_path = db_path or str(get_default_db_path())
        _log_upload_service = LogUploadService(resolved_db_path)

    return _log_upload_service


def reset_log_upload_service() -> None:
    """Reset singleton for tests."""
    global _log_upload_service
    _log_upload_service = None
