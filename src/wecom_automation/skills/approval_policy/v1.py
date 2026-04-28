"""Approval-policy skill, version 1 (V1).

Rule (frozen for V1): a verdict is approved iff *all four* fields are true:

    decision == "合格"
    is_portrait
    is_real_person
    face_visible

Any single false → rejected. The skill is intentionally pure (no I/O) so the
PolicyEvaluator can call it during webhook handling without taking locks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from wecom_automation.services.review.contracts import DECISION_PASS

SKILL_VERSION: Final[str] = "v1"


@dataclass(frozen=True)
class ApprovalDecision:
    approved: bool
    reason: str
    skill_version: str


def evaluate(
    *,
    decision: str,
    is_portrait: bool,
    is_real_person: bool,
    face_visible: bool,
) -> ApprovalDecision:
    failures: list[str] = []
    if decision != DECISION_PASS:
        failures.append(f"decision={decision!r}")
    if not is_portrait:
        failures.append("not_portrait")
    if not is_real_person:
        failures.append("not_real_person")
    if not face_visible:
        failures.append("face_not_visible")

    if failures:
        return ApprovalDecision(
            approved=False,
            reason="rejected:" + ",".join(failures),
            skill_version=SKILL_VERSION,
        )
    return ApprovalDecision(
        approved=True,
        reason="approved:all_four_true",
        skill_version=SKILL_VERSION,
    )
