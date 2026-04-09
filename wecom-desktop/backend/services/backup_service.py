"""
Backup Service - Periodic backup of admin_actions.xlsx.

Simple backup: copies admin_actions.xlsx to admin_actions_backup.xlsx every 30 minutes.
"""

import asyncio
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class BackupService:
    """
    Simple backup service that copies source file to backup file periodically.
    """

    def __init__(
        self,
        source_file: Path,
        backup_file: Path,
        interval_minutes: int = 30,
    ):
        """
        Initialize backup service.

        Args:
            source_file: Path to the source file (admin_actions.xlsx)
            backup_file: Path to the backup file (admin_actions_backup.xlsx)
            interval_minutes: Backup interval in minutes (default: 30)
        """
        self.source_file = source_file
        self.backup_file = backup_file
        self.interval_minutes = interval_minutes
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_backup_time: Optional[datetime] = None

    def backup_now(self) -> bool:
        """
        Perform an immediate backup (copy and overwrite).

        Returns:
            True if backup succeeded, False otherwise
        """
        if not self.source_file.exists():
            logger.warning(f"[backup] Source file does not exist: {self.source_file}")
            return False

        try:
            # Ensure parent directory exists
            self.backup_file.parent.mkdir(parents=True, exist_ok=True)

            # Copy and overwrite
            shutil.copy2(self.source_file, self.backup_file)
            self._last_backup_time = datetime.now()

            logger.info(f"[backup] Copied {self.source_file.name} -> {self.backup_file.name}")
            return True

        except Exception as e:
            logger.error(f"[backup] Backup failed: {e}")
            return False

    async def _backup_loop(self) -> None:
        """Background task that performs periodic backups."""
        logger.info(
            f"[backup] Started backup loop: {self.source_file.name} -> {self.backup_file.name} "
            f"(interval: {self.interval_minutes} min)"
        )

        while self._running:
            try:
                # Wait for the interval
                await asyncio.sleep(self.interval_minutes * 60)

                if not self._running:
                    break

                # Perform backup
                self.backup_now()

            except asyncio.CancelledError:
                logger.info("[backup] Backup loop cancelled")
                break
            except Exception as e:
                logger.error(f"[backup] Error in backup loop: {e}")
                await asyncio.sleep(60)  # Wait before retry

        logger.info("[backup] Backup loop stopped")

    def start(self) -> None:
        """Start the background backup task."""
        if self._running:
            logger.warning("[backup] Backup service already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._backup_loop())
        logger.info(f"[backup] Backup service started")

        # Perform initial backup on start
        self.backup_now()

    async def stop(self) -> None:
        """Stop the background backup task."""
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

        logger.info("[backup] Backup service stopped")

    def get_status(self) -> dict:
        """Get current backup service status."""
        status = {
            "running": self._running,
            "source_file": str(self.source_file),
            "backup_file": str(self.backup_file),
            "interval_minutes": self.interval_minutes,
            "source_exists": self.source_file.exists(),
            "backup_exists": self.backup_file.exists(),
            "last_backup_time": self._last_backup_time.isoformat() if self._last_backup_time else None,
        }

        if self.backup_file.exists():
            stat = self.backup_file.stat()
            status["backup_size"] = stat.st_size
            status["backup_modified"] = datetime.fromtimestamp(stat.st_mtime).isoformat()

        return status


# Global instance
_admin_actions_backup: Optional[BackupService] = None


def get_admin_actions_backup_service() -> BackupService:
    """Get or create the admin_actions backup service singleton."""
    global _admin_actions_backup

    if _admin_actions_backup is None:
        from utils.path_utils import get_project_root
        project_root = get_project_root()
        source_file = project_root / "settings" / "admin_actions.xlsx"
        backup_file = project_root / "settings" / "admin_actions_backup.xlsx"

        _admin_actions_backup = BackupService(
            source_file=source_file,
            backup_file=backup_file,
            interval_minutes=30,
        )

    return _admin_actions_backup
