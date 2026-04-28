"""Tests for the android-side mirror of the review/webhook contracts.

The contract MUST stay structurally identical to the rating-server version at
``image-rating-server/backend/app/services/webhook/contracts.py``. Any change
here that alters the on-the-wire JSON requires a coordinated change there.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from wecom_automation.services.review.contracts import (
    IMAGE_REVIEW_COMPLETED_EVENT,
    DECISION_FAIL,
    DECISION_PASS,
    ReviewVerdict,
    WebhookEnvelope,
    is_approved,
    parse_envelope,
)


def _verdict_dict(**overrides):
    base = {
        "image_id": "img-123",
        "correlation_id": "msg-456",
        "decision": "合格",
        "is_portrait": True,
        "is_real_person": True,
        "face_visible": True,
        "final_score": 7.5,
        "model_name": "qwen3-vl",
        "prompt_version_id": "pv-1",
        "prompt_version_number": 2,
        "analyzed_at": datetime(2026, 4, 28, 12, 0, 0, tzinfo=timezone.utc).isoformat(),
        "raw_details": {"foo": "bar"},
    }
    base.update(overrides)
    return base


class TestVerdictRoundTrip:
    def test_from_dict_to_dict_preserves_all_fields(self) -> None:
        d = _verdict_dict()
        v = ReviewVerdict.from_dict(d)
        assert v.to_dict() == d

    def test_missing_required_field_raises(self) -> None:
        d = _verdict_dict()
        d.pop("decision")
        with pytest.raises((KeyError, ValueError, TypeError)):
            ReviewVerdict.from_dict(d)

    def test_invalid_decision_value_rejected(self) -> None:
        with pytest.raises(ValueError):
            ReviewVerdict.from_dict(_verdict_dict(decision="pass"))

    def test_optional_raw_details_defaults_to_empty(self) -> None:
        d = _verdict_dict()
        d.pop("raw_details")
        v = ReviewVerdict.from_dict(d)
        assert v.raw_details == {}


class TestEnvelope:
    def test_event_type_constant(self) -> None:
        assert IMAGE_REVIEW_COMPLETED_EVENT == "image_review.completed"

    def test_decision_constants(self) -> None:
        assert DECISION_PASS == "合格"
        assert DECISION_FAIL == "不合格"

    def test_round_trip_via_json_string(self) -> None:
        env = WebhookEnvelope(
            event_id="evt-1",
            event_type=IMAGE_REVIEW_COMPLETED_EVENT,
            idempotency_key="msg-456",
            occurred_at="2026-04-28T12:00:00+00:00",
            data=ReviewVerdict.from_dict(_verdict_dict()),
        )
        body = json.dumps(env.to_dict(), ensure_ascii=False)
        restored = parse_envelope(body)
        assert restored == env

    def test_parse_envelope_rejects_unknown_event_type(self) -> None:
        bad = {
            "event_id": "x",
            "event_type": "something.else",
            "idempotency_key": "k",
            "occurred_at": "2026-04-28T12:00:00+00:00",
            "data": _verdict_dict(),
        }
        with pytest.raises(ValueError):
            parse_envelope(json.dumps(bad))


class TestApprovalRule:
    def test_all_four_true_means_approved(self) -> None:
        assert is_approved(ReviewVerdict.from_dict(_verdict_dict())) is True

    @pytest.mark.parametrize(
        "field,value",
        [
            ("decision", "不合格"),
            ("is_portrait", False),
            ("is_real_person", False),
            ("face_visible", False),
        ],
    )
    def test_any_one_false_means_rejected(self, field: str, value) -> None:
        v = ReviewVerdict.from_dict(_verdict_dict(**{field: value}))
        assert is_approved(v) is False
