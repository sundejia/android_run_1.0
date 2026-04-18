"""
Follow-up Service - 精简版（LEGACY）

⚠️ DEPRECATED: This service is legacy code.
   New architecture uses realtime_reply_process.py and RealtimeReplyManager for multi-device management.

仅保留数据库操作和工具方法，移除 BackgroundScheduler 相关代码。
新架构使用 realtime_reply_process.py 和 RealtimeReplyManager 进行多设备管理。
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from services.conversation_storage import get_control_db_path, open_shared_sqlite
from wecom_automation.database.repository import ConversationRepository as SyncConversationRepository

from .repository import ConversationRepository

# Phase 2 models removed - will be reimplemented in new follow-up system
from .settings import SettingsManager

# Database path from centralized config
DB_PATH = get_control_db_path()

# Setup logging with loguru
from wecom_automation.core.logging import get_logger
from loguru import logger as _loguru_logger

logger = get_logger("followup_service")


class FollowUpService:
    """Follow-up 服务 (精简版) - 仅提供数据库操作"""

    MAX_LOG_HISTORY = 500

    def __init__(self, db_path: str | None = None):
        self._db_path = str(db_path or DB_PATH)

        # Initialize components (lazy loading)
        self._settings_manager: SettingsManager | None = None
        self._repository: ConversationRepository | None = None  # 本模块会话仓库（客户/消息）
        self._conversation_repo: SyncConversationRepository | None = None  # 复用全量同步的仓库

        # Logging system
        self._log_callbacks: list[Callable[[dict], Any]] = []
        self._log_history: list[dict[str, Any]] = []
        self._sink_ids: list[int] = []

        # Setup loguru sink for file logging and frontend forwarding
        self._setup_loguru_sinks()

    def _setup_loguru_sinks(self):
        """
        Setup loguru sinks for frontend forwarding.

        Note: File logging is now handled by the unified logging system in
        wecom_automation.core.logging. This method only sets up the frontend
        log forwarding sink, which is specific to FollowUpService.
        """
        try:
            # Add custom sink for frontend forwarding (this is FollowUpService-specific)
            def frontend_sink(message):
                """Custom sink to forward logs to frontend."""
                try:
                    record = message.record
                    log_entry = {
                        "timestamp": record["time"].isoformat(),
                        "level": record["level"].name,
                        "message": record["message"],
                        "source": "followup",
                    }

                    # Add to history
                    self._log_history.append(log_entry)
                    if len(self._log_history) > FollowUpService.MAX_LOG_HISTORY:
                        self._log_history = self._log_history[-FollowUpService.MAX_LOG_HISTORY :]

                    # Broadcast to callbacks
                    try:
                        loop = asyncio.get_running_loop()
                        asyncio.ensure_future(self._broadcast_log(log_entry), loop=loop)
                    except RuntimeError:
                        # No running event loop
                        self._broadcast_log_sync(log_entry)
                except Exception:
                    pass  # Silently ignore errors in sink

            frontend_sink_id = _loguru_logger.add(
                frontend_sink,
                format="{message}",
                filter=lambda record: record["extra"].get("module") == "followup_service",
            )
            self._sink_ids.append(frontend_sink_id)

        except Exception as e:
            # If sink setup fails, continue without it
            logger.warning(f"Failed to setup loguru frontend sink: {e}")

    def __del__(self):
        """Cleanup: Remove loguru sinks."""
        try:
            for sink_id in self._sink_ids:
                try:
                    _loguru_logger.remove(sink_id)
                except Exception:
                    pass
        except Exception:
            # Silently ignore errors during cleanup
            pass


    def _broadcast_log_sync(self, log_entry: dict):
        """Synchronously broadcast log to all registered callbacks."""
        import inspect

        # Check if callbacks are async
        for callback in self._log_callbacks:
            try:
                if inspect.iscoroutinefunction(callback):
                    # Async callback - try to get loop and schedule it
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.ensure_future(callback(log_entry), loop=loop)
                        else:
                            # Loop exists but not running - skip
                            pass
                    except RuntimeError:
                        # No event loop - skip async callbacks from non-async threads
                        pass
                else:
                    # Sync callback - call directly
                    callback(log_entry)
            except Exception:
                pass

    async def _broadcast_log(self, log_entry: dict):
        """Broadcast log to all registered callbacks."""
        for callback in self._log_callbacks:
            try:
                await callback(log_entry)
            except Exception:
                pass

    # ==================== Lazy Loading ====================

    def _get_settings_manager(self) -> SettingsManager:
        if not self._settings_manager:
            self._settings_manager = SettingsManager(self._db_path)
        return self._settings_manager

    def _get_repository(self) -> ConversationRepository:
        if not self._repository:
            self._repository = ConversationRepository(self._db_path, self._get_settings_manager())
        return self._repository

    def _get_conversation_repo(self) -> SyncConversationRepository:
        """获取全量同步的 ConversationRepository（用于消息存储）"""
        if not self._conversation_repo:
            self._conversation_repo = SyncConversationRepository(self._db_path)
        return self._conversation_repo

    def get_sidecar_client(self, device_serial: str) -> Any | None:
        """获取指定设备的 Sidecar 客户端"""
        # NOTE: Since SidecarQueueClient needs a session context, usually it's used within an async context manager.
        # The actual instantiation should happen in ResponseDetector or Scheduler where the loop is valid.
        from wecom_automation.services.integration.sidecar import SidecarQueueClient

        # Sidecar 路由开关已归属 Realtime Reply 设置（不是 FollowUp/补刀设置）
        try:
            settings_service = self._get_settings_manager_service()
            if not settings_service:
                logger.error("[Sidecar] Failed to load unified settings service")
                return None

            realtime_settings = settings_service.get_realtime_settings()
            send_via_sidecar = realtime_settings.send_via_sidecar
            logger.info(f"[Sidecar] Realtime settings: send_via_sidecar={send_via_sidecar}")
        except Exception as e:
            logger.error(f"[Sidecar] Failed to get Realtime settings: {e}")
            return None

        # 如果 Realtime 设置明确禁用，直接返回 None
        if not send_via_sidecar:
            logger.info("[Sidecar] Disabled in FollowUp settings (send_via_sidecar=False)")
            return None

        # 从全局设置获取 backendUrl
        global_settings = settings_service.get_flat_settings()
        server_url = global_settings.get("backendUrl", "http://localhost:8765")

        logger.info(f"[Sidecar] ✅ Creating SidecarQueueClient for {device_serial} (server_url={server_url})")
        return SidecarQueueClient(device_serial, server_url, logger=logger)

    def _get_settings_manager_service(self):
        """Helper to get the global unified settings service to read sidecar config"""
        try:
            from services.settings import get_settings_service

            return get_settings_service()
        except ImportError:
            return None

    # ==================== Settings ====================

    def get_settings(self) -> dict[str, Any]:
        """获取设置（向后兼容，返回字典）"""
        settings = self._get_settings_manager().get_settings()
        return settings.to_dict()

    def is_within_operating_hours(self, settings: dict[str, Any]) -> bool:
        """检查是否在工作时间内"""
        return self._get_settings_manager().is_within_operating_hours()

    def calculate_required_delay(self, attempt_number: int, settings: dict[str, Any]) -> int:
        """计算所需延迟"""
        return self._get_settings_manager().calculate_required_delay(attempt_number)

    # ==================== Repository ====================
    # Note: Phase 2 methods (find_followup_candidates, get_pending_followup_customers)
    # have been removed. Phase 1 (instant response) uses the methods below.

    def find_or_create_customer(
        self, name: str, channel: str | None = None, device_serial: str | None = None
    ) -> int:
        """查找或创建客户"""
        return self._get_repository().find_or_create_customer(name, channel, device_serial)

    # ==================== Follow-up Attempts Methods Removed ====================
    # The following methods have been removed (now managed by followup_manage.py router):
    # - get_customer_attempt_count(): Get pending follow-up attempt count
    # - record_attempt(): Record follow-up attempt
    # - mark_customer_responded(): Mark customer as responded
    #
    # These were Phase 2 (follow-up management) features.
    # Follow-up management now uses its own repository in followup_manage.py.

    # ==================== Logging ====================

    def register_log_callback(self, callback: Callable[[dict], Any]):
        """注册日志回调"""
        if callback not in self._log_callbacks:
            self._log_callbacks.append(callback)

    def unregister_log_callback(self, callback: Callable[[dict], Any]):
        """取消注册日志回调"""
        if callback in self._log_callbacks:
            self._log_callbacks.remove(callback)

    def get_log_history(self) -> list[dict[str, Any]]:
        """获取日志历史"""
        return self._log_history.copy()

    def clear_log_history(self):
        """清除日志历史"""
        self._log_history = []

    # ==================== Database Connection ====================

    def get_db_connection(self):
        """获取数据库连接（向后兼容，带 busy_timeout/WAL 容错）"""
        return open_shared_sqlite(self._db_path, row_factory=True)


# ==================== Singleton ====================

_followup_service_instance: FollowUpService | None = None


def get_followup_service() -> FollowUpService:
    """获取 FollowUpService 单例"""
    global _followup_service_instance
    if _followup_service_instance is None:
        _followup_service_instance = FollowUpService()
    return _followup_service_instance
