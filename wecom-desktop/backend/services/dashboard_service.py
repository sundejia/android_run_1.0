"""Singleton service managing the dashboard heartbeat client lifecycle."""

from __future__ import annotations

import logging
from typing import Any

from .heartbeat_client import HeartbeatClient

logger = logging.getLogger(__name__)

_instance: DashboardService | None = None


class DashboardService:
    """Manages HeartbeatClient start/stop/replace based on settings changes."""

    def __init__(self, settings_service: Any, device_manager: Any = None) -> None:
        self._settings_service = settings_service
        self._device_manager = device_manager
        self._client: HeartbeatClient | None = None
        self._url: str = ""
        self._enabled: bool = False

    async def reload(self, enabled: bool, url: str) -> None:
        """Stop/start the heartbeat client to match the given settings."""
        url = (url or "").strip()
        url_changed = url != self._url
        enabled_changed = enabled != self._enabled

        if self._client and (not enabled or url_changed):
            await self._client.stop()
            self._client = None

        if enabled and url and self._client is None:
            self._client = HeartbeatClient(
                dashboard_url=url,
                settings_service=self._settings_service,
                device_manager=self._device_manager,
                app_version="1.0.0",
            )
            await self._client.start()

        self._enabled = enabled
        self._url = url

        if enabled_changed or url_changed:
            logger.info(
                "dashboard_service_reloaded: enabled=%s url=%s running=%s",
                enabled,
                url,
                self._client is not None and self._client.is_running,
            )

    def status(self) -> dict:
        """Return current connection status."""
        if self._client and self._client.status == "connected":
            conn_status = "connected"
        elif self._client and self._client.is_running:
            conn_status = "connecting"
        elif not self._enabled:
            conn_status = "disabled"
        else:
            conn_status = "disconnected"

        return {
            "enabled": self._enabled,
            "url": self._url,
            "status": conn_status,
        }

    async def test_connection(self, url: str | None = None) -> dict:
        """One-shot test connection to the given or configured URL."""
        target = (url or "").strip() or self._url
        if not target:
            return {"success": False, "message": "Dashboard URL is not configured"}
        client = HeartbeatClient(
            dashboard_url=target,
            settings_service=self._settings_service,
        )
        return await client.test_connection()


def get_dashboard_service(
    settings_service: Any = None, device_manager: Any = None
) -> DashboardService:
    """Return the process-wide singleton (created on first call with deps)."""
    global _instance
    if _instance is None:
        if settings_service is None:
            raise RuntimeError(
                "DashboardService not yet initialized; pass settings_service on first call"
            )
        _instance = DashboardService(settings_service, device_manager)
    return _instance
