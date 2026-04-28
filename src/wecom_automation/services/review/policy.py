"""PolicyEvaluator — dispatches a stored verdict through a versioned skill.

The evaluator is the single point of truth for "is this verdict approved?"
queries. It reads the desired skill version from settings (or the explicit
constructor argument) and forwards the four boolean fields to the matching
skill module. This keeps the runtime (ReviewGate, MessageProcessor, etc.) free
of any approval logic — they only consume the resulting ``ApprovalDecision``.
"""

from __future__ import annotations

from wecom_automation.services.review.storage import ReviewVerdictRow
from wecom_automation.skills import approval_policy
from wecom_automation.skills.approval_policy.v1 import ApprovalDecision

DEFAULT_SKILL_VERSION = "v1"


class UnknownSkillVersionError(KeyError):
    """Raised when a requested skill version is not registered."""


class PolicyEvaluator:
    def __init__(self, skill_version: str = DEFAULT_SKILL_VERSION) -> None:
        self._skill_version = skill_version

    @property
    def skill_version(self) -> str:
        return self._skill_version

    def _load(self):
        try:
            return approval_policy.load(self._skill_version)
        except KeyError as exc:
            raise UnknownSkillVersionError(self._skill_version) from exc

    def evaluate_verdict(self, verdict: ReviewVerdictRow) -> ApprovalDecision:
        skill = self._load()
        return skill.evaluate(
            decision=verdict.decision,
            is_portrait=bool(verdict.is_portrait),
            is_real_person=bool(verdict.is_real_person),
            face_visible=bool(verdict.face_visible),
        )
