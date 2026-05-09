"""Tiny protocol over the ADB layer used by BOSS services.

Why this exists
---------------
The BOSS services need to launch the BOSS app, read the UI tree, and
tap by text. We do NOT want to:
- Import DroidRun at unit-test time (heavy, requires a device).
- Import the WeCom-coupled ``ADBService`` and inherit its assumptions.

This module defines a minimal Protocol so production code can wrap
``wecom_automation.services.adb_service.ADBService`` later, while
unit tests provide an in-memory fake. Keep the Protocol small;
expand only when a service genuinely needs another method.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AdbPort(Protocol):
    async def start_app(self, package_name: str) -> None: ...

    async def get_state(self) -> tuple[dict[str, Any], list[dict[str, Any]]]: ...

    async def tap_by_text(self, text: str) -> bool: ...

    async def tap(self, x: int, y: int) -> bool: ...

    async def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
    ) -> None: ...

    async def type_text(self, text: str) -> bool: ...
