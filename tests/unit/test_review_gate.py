"""Tests for the ReviewGate, PolicyEvaluator, and skills/approval_policy/v1.

ReviewGate is the bridge between persisted verdicts (from the inbound webhook)
and the existing MediaEventBus. It loads the pending_review + verdict, asks
PolicyEvaluator (which dispatches to a versioned skill), and either emits a
MediaEvent or marks the pending row as rejected.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from wecom_automation.database.schema import init_database
from wecom_automation.services.media_actions.event_bus import MediaEventBus
from wecom_automation.services.media_actions.interfaces import (
    ActionResult,
    ActionStatus,
    IMediaAction,
    MediaEvent,
)
from wecom_automation.services.review.gate import ReviewGate, ReviewGateOutcome
from wecom_automation.services.review.policy import (
    PolicyEvaluator,
    UnknownSkillVersionError,
)
from wecom_automation.services.review.storage import (
    PendingReviewRow,
    ReviewStorage,
    ReviewVerdictRow,
)
from wecom_automation.skills.approval_policy import v1 as policy_v1

# ---------------------------------------------------------------------------
# skills/approval_policy/v1
# ---------------------------------------------------------------------------


class TestApprovalPolicyV1:
    def test_all_four_true_is_approved(self) -> None:
        decision = policy_v1.evaluate(
            decision="合格",
            is_portrait=True,
            is_real_person=True,
            face_visible=True,
        )
        assert decision.approved is True
        assert decision.skill_version == "v1"
        assert "all_four_true" in decision.reason or "approved" in decision.reason

    @pytest.mark.parametrize(
        "decision,is_portrait,is_real_person,face_visible",
        [
            ("不合格", True, True, True),
            ("合格", False, True, True),
            ("合格", True, False, True),
            ("合格", True, True, False),
        ],
    )
    def test_any_field_false_or_fail_decision_is_rejected(
        self,
        decision: str,
        is_portrait: bool,
        is_real_person: bool,
        face_visible: bool,
    ) -> None:
        result = policy_v1.evaluate(
            decision=decision,
            is_portrait=is_portrait,
            is_real_person=is_real_person,
            face_visible=face_visible,
        )
        assert result.approved is False
        assert result.skill_version == "v1"


# ---------------------------------------------------------------------------
# PolicyEvaluator
# ---------------------------------------------------------------------------


class TestPolicyEvaluator:
    def test_default_uses_v1(self) -> None:
        ev = PolicyEvaluator()
        d = ev.evaluate_verdict(
            ReviewVerdictRow(
                message_id=1,
                image_id="x",
                decision="合格",
                is_portrait=True,
                is_real_person=True,
                face_visible=True,
                final_score=None,
                raw_payload_json=None,
                prompt_version_id=None,
                skill_version=None,
                received_at="t",
            )
        )
        assert d.approved is True
        assert d.skill_version == "v1"

    def test_unknown_skill_raises(self) -> None:
        ev = PolicyEvaluator(skill_version="vX")
        with pytest.raises(UnknownSkillVersionError):
            ev.evaluate_verdict(
                ReviewVerdictRow(
                    message_id=1,
                    image_id="x",
                    decision="合格",
                    is_portrait=True,
                    is_real_person=True,
                    face_visible=True,
                    final_score=None,
                    raw_payload_json=None,
                    prompt_version_id=None,
                    skill_version=None,
                    received_at="t",
                )
            )


# ---------------------------------------------------------------------------
# ReviewGate
# ---------------------------------------------------------------------------


class _RecordingAction(IMediaAction):
    def __init__(self) -> None:
        self.calls: list[MediaEvent] = []

    @property
    def action_name(self) -> str:
        return "recording"

    async def should_execute(self, event: MediaEvent, settings: dict) -> bool:
        return True

    async def execute(self, event: MediaEvent, settings: dict) -> ActionResult:
        self.calls.append(event)
        return ActionResult(
            action_name=self.action_name,
            status=ActionStatus.SUCCESS,
            message="ok",
        )


@pytest.fixture()
def storage(tmp_path: Path) -> ReviewStorage:
    db = tmp_path / "android.db"
    init_database(str(db), force_recreate=True)
    return ReviewStorage(str(db))


def _seed_pending(storage: ReviewStorage, message_id: int = 100) -> None:
    storage.insert_pending_review(
        PendingReviewRow(
            message_id=message_id,
            customer_id=11,
            customer_name="alice",
            device_serial="dev-1",
            channel="wx",
            kefu_name="kefu-A",
            image_path="/tmp/a.png",
        )
    )


def _seed_verdict(
    storage: ReviewStorage,
    *,
    message_id: int = 100,
    decision: str = "合格",
    is_portrait: bool = True,
    is_real_person: bool = True,
    face_visible: bool = True,
) -> None:
    storage.upsert_verdict(
        ReviewVerdictRow(
            message_id=message_id,
            image_id="img-100",
            decision=decision,
            is_portrait=is_portrait,
            is_real_person=is_real_person,
            face_visible=face_visible,
            final_score=8.0,
            raw_payload_json=json.dumps({}),
            prompt_version_id="pv-2",
            skill_version=None,
            received_at="2025-01-01T00:00:00Z",
        )
    )


class TestReviewGate:
    def test_approved_emits_media_event(self, storage: ReviewStorage) -> None:
        _seed_pending(storage)
        _seed_verdict(storage)

        bus = MediaEventBus()
        action = _RecordingAction()
        bus.register(action)

        gate = ReviewGate(
            storage=storage,
            bus=bus,
            settings_provider=lambda: {"enabled": True, "auto_group_invite": {"enabled": True}},
        )

        outcome = asyncio.run(gate.on_verdict(100))
        assert outcome == ReviewGateOutcome.APPROVED
        assert len(action.calls) == 1
        ev = action.calls[0]
        assert ev.event_type == "customer_media_detected"
        assert ev.message_type == "image"
        assert ev.customer_id == 11
        assert ev.customer_name == "alice"
        assert ev.device_serial == "dev-1"
        assert ev.kefu_name == "kefu-A"
        assert ev.message_id == 100

        pr = storage.get_pending_review(100)
        assert pr is not None
        assert pr.status == "approved"

        events = storage.list_events(trace_id="100")
        assert any(e.event_type == "review.gate.approved" for e in events)

    @pytest.mark.parametrize(
        "decision,is_portrait,is_real_person,face_visible",
        [
            ("不合格", True, True, True),
            ("合格", False, True, True),
            ("合格", True, False, True),
            ("合格", True, True, False),
        ],
    )
    def test_rejected_does_not_emit(
        self,
        storage: ReviewStorage,
        decision: str,
        is_portrait: bool,
        is_real_person: bool,
        face_visible: bool,
    ) -> None:
        _seed_pending(storage)
        _seed_verdict(
            storage,
            decision=decision,
            is_portrait=is_portrait,
            is_real_person=is_real_person,
            face_visible=face_visible,
        )

        bus = MediaEventBus()
        action = _RecordingAction()
        bus.register(action)

        gate = ReviewGate(storage=storage, bus=bus, settings_provider=lambda: {})

        outcome = asyncio.run(gate.on_verdict(100))
        assert outcome == ReviewGateOutcome.REJECTED
        assert action.calls == []

        pr = storage.get_pending_review(100)
        assert pr is not None
        assert pr.status == "rejected"

        events = storage.list_events(trace_id="100")
        assert any(e.event_type == "review.gate.rejected" for e in events)

    def test_idempotent_for_same_message_id(self, storage: ReviewStorage) -> None:
        _seed_pending(storage)
        _seed_verdict(storage)
        bus = MediaEventBus()
        action = _RecordingAction()
        bus.register(action)

        gate = ReviewGate(storage=storage, bus=bus, settings_provider=lambda: {})

        async def run_twice() -> tuple[ReviewGateOutcome, ReviewGateOutcome]:
            o1 = await gate.on_verdict(100)
            o2 = await gate.on_verdict(100)
            return o1, o2

        o1, o2 = asyncio.run(run_twice())
        assert o1 == ReviewGateOutcome.APPROVED
        assert o2 == ReviewGateOutcome.ALREADY_PROCESSED
        assert len(action.calls) == 1

    def test_missing_verdict_returns_no_verdict(self, storage: ReviewStorage) -> None:
        _seed_pending(storage)  # no verdict written
        bus = MediaEventBus()
        gate = ReviewGate(storage=storage, bus=bus, settings_provider=lambda: {})
        outcome = asyncio.run(gate.on_verdict(100))
        assert outcome == ReviewGateOutcome.NO_VERDICT
