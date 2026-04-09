"""
Media Auto-Actions module.

Provides an event-driven system for triggering automated actions
when customers send media (images/videos).
"""

from wecom_automation.services.media_actions.event_bus import MediaEventBus
from wecom_automation.services.media_actions.factory import build_media_event_bus
from wecom_automation.services.media_actions.interfaces import (
    ActionResult,
    ActionStatus,
    IMediaAction,
    MediaEvent,
)

__all__ = [
    "ActionResult",
    "ActionStatus",
    "IMediaAction",
    "MediaEvent",
    "MediaEventBus",
    "build_media_event_bus",
]
