"""
Media Auto-Actions interfaces and data models.

Defines the contract for media-triggered actions and the event payload.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ActionStatus(str, Enum):
    """Status of an action execution."""

    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class ActionResult:
    """Result of executing a media action."""

    action_name: str
    status: ActionStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class MediaEvent:
    """
    Event emitted when a customer sends media (image/video).

    Carries all context needed by downstream actions.
    """

    event_type: str
    message_type: str
    customer_id: int
    customer_name: str
    channel: str | None
    device_serial: str
    kefu_name: str
    message_id: int | None
    timestamp: datetime

    @property
    def is_media(self) -> bool:
        return self.message_type in ("image", "video")


class IMediaAction(ABC):
    """
    Interface for media-triggered actions.

    Each action decides whether it should run (should_execute)
    and then performs its work (execute). Actions are independent
    and isolated from each other.
    """

    @property
    @abstractmethod
    def action_name(self) -> str:
        """Unique name identifying this action."""
        ...

    @abstractmethod
    async def should_execute(self, event: MediaEvent, settings: dict) -> bool:
        """
        Determine whether this action should run for the given event.

        Args:
            event: The media event.
            settings: Media auto-action settings dict.

        Returns:
            True if the action should execute.
        """
        ...

    @abstractmethod
    async def execute(self, event: MediaEvent, settings: dict) -> ActionResult:
        """
        Execute the action.

        Args:
            event: The media event.
            settings: Media auto-action settings dict.

        Returns:
            Result of the action execution.
        """
        ...
