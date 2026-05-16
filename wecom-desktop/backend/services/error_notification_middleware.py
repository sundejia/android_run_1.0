"""
FastAPI middleware for error notification.

Intercepts unhandled exceptions in route handlers and 5xx responses,
then dispatches them to ``ErrorNotificationService`` for email delivery.

This covers errors that may not flow through loguru (Pydantic validation
errors, Starlette routing errors, etc.).
"""

from __future__ import annotations

import logging
import time
import traceback
from typing import Any, Callable, MutableMapping

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Re-read settings from DB every 5 minutes so runtime changes take effect.
_REFRESH_INTERVAL = 300


class ErrorNotificationMiddleware:
    """Starlette ASGI middleware that notifies on unhandled 5xx errors."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status_code: int | None = None

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            await self._notify(scope, exc)
            raise

        if status_code is not None and status_code >= 500:
            await self._notify_status(scope, status_code)

    async def _notify(self, scope: Scope, exc: Exception) -> None:
        path = scope.get("path", "unknown")
        method = scope.get("method", "unknown")
        try:
            service = _get_service()
            if service is None:
                return
            await service.notify_error_async(
                message=f"Unhandled exception in {method} {path}: {exc}",
                level="CRITICAL",
                source="fastapi.middleware",
                traceback_str=traceback.format_exc(),
                extra={"path": path, "method": method},
            )
        except Exception:
            pass

    async def _notify_status(self, scope: Scope, status_code: int) -> None:
        path = scope.get("path", "unknown")
        method = scope.get("method", "unknown")
        try:
            service = _get_service()
            if service is None:
                return
            await service.notify_error_async(
                message=f"HTTP {status_code} from {method} {path}",
                level="ERROR",
                source="fastapi.middleware",
                extra={"path": path, "method": method, "status_code": status_code},
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Lazy service accessor with periodic refresh
# ---------------------------------------------------------------------------

_service_instance: Any | None = None
_last_refresh: float = 0


def _get_service():
    global _service_instance, _last_refresh

    now = time.monotonic()
    if _service_instance is not None and (now - _last_refresh) < _REFRESH_INTERVAL:
        return _service_instance

    try:
        from services.settings.service import get_settings_service
        from wecom_automation.services.notification.error_notification import (
            ErrorNotificationService,
        )

        settings_svc = get_settings_service()
        email_settings = settings_svc.get_email_settings()
        _service_instance = ErrorNotificationService.from_settings(email_settings)
        _last_refresh = now
        return _service_instance
    except Exception:
        return None
