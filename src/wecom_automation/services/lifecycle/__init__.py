"""Lifecycle / startup self-healing utilities.

The lifecycle service is the "tomorrow morning still works" answer: it runs
once at backend startup (and may be scheduled periodically) to clean up debris
left behind by crashes / power loss / interrupted automations.

Currently exposes:
    * :class:`LifecycleService` — pending-review recovery, orphan-image
      cleanup, and webhook idempotency garbage collection.
"""

from wecom_automation.services.lifecycle.startup import (
    LifecycleService,
    PendingRecoveryStats,
)

__all__ = ["LifecycleService", "PendingRecoveryStats"]
