"""Governance layer.

The governance layer enforces operator-controlled execution policies in front
of every side-effecting automation step. Policies cannot be overridden from
model output / chat — they live in the operator-managed settings table and
the audit trail goes straight into ``analytics_events``.

Currently exposes:
    * :class:`ExecutionPolicyGuard` — kill-switch + per-device rate limit.
"""

from wecom_automation.services.governance.guard import (
    ExecutionPolicyGuard,
    GovernanceAction,
    GuardDecision,
    GuardOutcome,
)

__all__ = [
    "ExecutionPolicyGuard",
    "GovernanceAction",
    "GuardDecision",
    "GuardOutcome",
]
