"""Centralised telemetry facade for android_run.

Why a dedicated package
-----------------------
The seven-requirements review flagged the original implementation —
``record_event`` bolted onto :class:`ReviewStorage` — as architecturally
"scattered". The functionality was correct but every consumer reached
into the storage object directly, which makes future swap-out (e.g.
moving from SQLite to OpenTelemetry) painful.

This module exposes a thin :class:`AnalyticsService` facade that owns
the canonical event-name vocabulary (:class:`EventType`) and routes
``record`` calls into the existing storage layer. Existing call sites
keep working; new code is encouraged to go through ``AnalyticsService``
instead.
"""

from wecom_automation.services.analytics.service import (
    AnalyticsService,
    EventType,
    get_default_service,
)

__all__ = [
    "AnalyticsService",
    "EventType",
    "get_default_service",
]
