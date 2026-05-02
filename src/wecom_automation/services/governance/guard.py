"""ExecutionPolicyGuard — operator-controlled gate for side-effecting actions.

Why this exists
---------------
Both the rating-server prompt and the customer chat are *untrusted* with
respect to safety controls. We never let either of them silently flip an
action on. Instead, the operator owns three knobs in ``settings.media_auto_actions``::

    governance.kill_switch            # when True, ALL actions are blocked
    governance.invite_rate_limit_seconds  # min gap between two invites/device

The guard reads only this settings dict and an in-memory ``last invocation``
table; it cannot be persuaded by message content, prompt output, or anything
the model produces. Every decision (allowed or blocked) is mirrored to
``analytics_events`` so a forensic trail always exists.

Usage
-----
``ReviewGate`` (and any future side-effecting consumer) calls
``guard.check(...)`` immediately before triggering the action. If the
returned outcome is ``BLOCKED``, the caller MUST short-circuit.
"""

from __future__ import annotations

import enum
import time
from collections.abc import Callable
from dataclasses import dataclass

from wecom_automation.services.review.storage import ReviewStorage


class GovernanceAction(enum.StrEnum):
    GROUP_INVITE = "group_invite"
    CONTACT_SHARE = "contact_share"


class GuardOutcome(enum.StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class GuardDecision:
    outcome: GuardOutcome
    action: GovernanceAction
    device_serial: str
    reason: str


class ExecutionPolicyGuard:
    """In-memory rate-limit + kill-switch enforcer."""

    def __init__(
        self,
        *,
        storage: ReviewStorage | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._storage = storage
        self._clock = clock or time.monotonic
        self._last: dict[tuple[GovernanceAction, str], float] = {}

    @staticmethod
    def _gov_settings(settings: dict) -> dict:
        return (settings or {}).get("governance") or {}

    def check(
        self,
        *,
        action: GovernanceAction,
        device_serial: str,
        settings: dict,
        trace_id: str | None = None,
    ) -> GuardDecision:
        gov = self._gov_settings(settings)

        if bool(gov.get("kill_switch", False)):
            decision = GuardDecision(
                outcome=GuardOutcome.BLOCKED,
                action=action,
                device_serial=device_serial,
                reason="kill_switch",
            )
            self._audit(decision, trace_id, payload={"settings_snapshot": gov})
            return decision

        rate_seconds = max(0, int(gov.get("invite_rate_limit_seconds", 60) or 0))
        key = (action, device_serial)
        now = self._clock()
        last = self._last.get(key)
        if rate_seconds > 0 and last is not None and (now - last) < rate_seconds:
            decision = GuardDecision(
                outcome=GuardOutcome.BLOCKED,
                action=action,
                device_serial=device_serial,
                reason="rate_limit",
            )
            self._audit(
                decision,
                trace_id,
                payload={
                    "rate_seconds": rate_seconds,
                    "elapsed": round(now - last, 3),
                },
            )
            return decision

        self._last[key] = now
        decision = GuardDecision(
            outcome=GuardOutcome.ALLOWED,
            action=action,
            device_serial=device_serial,
            reason="ok",
        )
        self._audit(decision, trace_id, payload={"rate_seconds": rate_seconds})
        return decision

    def _audit(
        self,
        decision: GuardDecision,
        trace_id: str | None,
        *,
        payload: dict | None = None,
    ) -> None:
        if self._storage is None:
            return
        event_type = "governance.allowed" if decision.outcome == GuardOutcome.ALLOWED else "governance.blocked"
        body = {
            "action": decision.action.value,
            "device_serial": decision.device_serial,
            "reason": decision.reason,
        }
        if payload:
            body.update(payload)
        try:
            self._storage.record_event(event_type, trace_id=trace_id, payload=body)
        except Exception:
            # Never let analytics failures interfere with the safety decision.
            pass
