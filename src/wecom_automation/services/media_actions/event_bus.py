"""
MediaEventBus - lightweight event bus for media-triggered actions.

Decouples message processing from automated reactions. Each registered
action is evaluated and executed independently with full error isolation.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from wecom_automation.services.media_actions.interfaces import (
    ActionResult,
    ActionStatus,
    IMediaAction,
    MediaEvent,
)

logger = logging.getLogger(__name__)


class MediaEventBus:
    """
    Event bus that dispatches MediaEvents to registered IMediaAction instances.

    Actions are executed sequentially. Errors in one action do not prevent
    subsequent actions from running.
    """

    def __init__(self, on_action_results: Callable | None = None) -> None:
        self._actions: list[IMediaAction] = []
        self._on_action_results = on_action_results

    def register(self, action: IMediaAction) -> None:
        self._actions.append(action)
        logger.debug("Registered media action: %s", action.action_name)

    def unregister(self, action_name: str) -> None:
        self._actions = [a for a in self._actions if a.action_name != action_name]

    def clear(self) -> None:
        self._actions.clear()

    async def emit(self, event: MediaEvent, settings: dict[str, Any]) -> list[ActionResult]:
        """
        Emit an event to all registered actions.

        Each action's should_execute is checked first. If it returns True,
        execute is called. Errors are caught per-action and reported as
        ActionStatus.ERROR results without blocking other actions.
        """
        results: list[ActionResult] = []

        for action in self._actions:
            try:
                should_run = await action.should_execute(event, settings)
            except Exception as exc:
                logger.error("Action %s.should_execute raised: %s", action.action_name, exc)
                results.append(
                    ActionResult(
                        action_name=action.action_name,
                        status=ActionStatus.ERROR,
                        message=f"should_execute error: {exc}",
                    )
                )
                continue

            if not should_run:
                results.append(
                    ActionResult(
                        action_name=action.action_name,
                        status=ActionStatus.SKIPPED,
                        message="Skipped by should_execute",
                    )
                )
                continue

            try:
                result = await action.execute(event, settings)
                results.append(result)
                logger.info("Action %s completed: %s", action.action_name, result.status.value)
            except Exception as exc:
                logger.error("Action %s.execute raised: %s", action.action_name, exc)
                results.append(
                    ActionResult(
                        action_name=action.action_name,
                        status=ActionStatus.ERROR,
                        message=f"execute error: {exc}",
                    )
                )

        if self._on_action_results and any(r.status == ActionStatus.SUCCESS for r in results):
            try:
                await self._on_action_results(event, results)
            except Exception:
                logger.error("on_action_results callback failed", exc_info=True)

        return results
