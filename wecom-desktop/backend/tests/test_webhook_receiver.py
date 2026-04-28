"""Tests for the inbound image-review webhook handler.

The handler is a pure function operating on (body, headers, secret, db_path,
storage). Tests don't need a real FastAPI server; they verify HMAC, replay
protection, idempotency, and verdict persistence in isolation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

src_dir = backend_dir.parent.parent / "src"
sys.path.insert(0, str(src_dir))

from services.webhook_receiver import (  # noqa: E402
    WebhookValidationError,
    handle_image_review,
)
from wecom_automation.database.schema import init_database  # noqa: E402
from wecom_automation.services.review.storage import (  # noqa: E402
    PendingReviewRow,
    ReviewStorage,
)

SECRET = "supersecret"


def _sign(body: bytes, secret: str = SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _envelope_body(message_id: int = 42, decision: str = "合格") -> bytes:
    payload = {
        "event_id": "evt-1",
        "event_type": "image_review.completed",
        "idempotency_key": str(message_id),
        "occurred_at": datetime.now(UTC).isoformat(),
        "data": {
            "image_id": "img-1",
            "correlation_id": str(message_id),
            "decision": decision,
            "is_portrait": True,
            "is_real_person": True,
            "face_visible": True,
            "final_score": 7.5,
            "model_name": "qwen3-vl",
            "prompt_version_id": "pv-2",
            "prompt_version_number": 2,
            "analyzed_at": datetime.now(UTC).isoformat(),
            "raw_details": {"foo": "bar"},
        },
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


@pytest.fixture
def storage(tmp_path: Path) -> ReviewStorage:
    db = tmp_path / "android.db"
    init_database(str(db), force_recreate=True)
    s = ReviewStorage(str(db))
    s.insert_pending_review(
        PendingReviewRow(
            message_id=42,
            customer_id=1,
            customer_name="x",
            device_serial="d",
            channel=None,
            kefu_name="k",
            image_path="/tmp/x.png",
        )
    )
    return s


def test_valid_signature_persists_verdict_and_marks_pending(storage: ReviewStorage) -> None:
    body = _envelope_body(message_id=42, decision="合格")
    headers = {
        "X-IRS-Signature": _sign(body),
        "X-IRS-Idempotency-Key": "42",
    }
    result = handle_image_review(
        body=body,
        headers=headers,
        secret=SECRET,
        storage=storage,
    )
    assert result.status == "accepted"
    v = storage.get_verdict(42)
    assert v is not None
    assert v.decision == "合格"
    pr = storage.get_pending_review(42)
    assert pr is not None
    assert pr.status == "verdict_received"


def test_invalid_signature_rejected(storage: ReviewStorage) -> None:
    body = _envelope_body()
    headers = {
        "X-IRS-Signature": "sha256=deadbeef",
        "X-IRS-Idempotency-Key": "42",
    }
    with pytest.raises(WebhookValidationError) as excinfo:
        handle_image_review(
            body=body,
            headers=headers,
            secret=SECRET,
            storage=storage,
        )
    assert excinfo.value.status_code == 401


def test_missing_signature_rejected(storage: ReviewStorage) -> None:
    body = _envelope_body()
    with pytest.raises(WebhookValidationError) as excinfo:
        handle_image_review(
            body=body,
            headers={},
            secret=SECRET,
            storage=storage,
        )
    assert excinfo.value.status_code == 401


def test_duplicate_idempotency_key_returns_replay(storage: ReviewStorage) -> None:
    body = _envelope_body()
    headers = {
        "X-IRS-Signature": _sign(body),
        "X-IRS-Idempotency-Key": "42",
    }
    first = handle_image_review(body=body, headers=headers, secret=SECRET, storage=storage)
    assert first.status == "accepted"
    second = handle_image_review(body=body, headers=headers, secret=SECRET, storage=storage)
    assert second.status == "replay"
    # Verdict was written once
    v = storage.get_verdict(42)
    assert v is not None


def test_invalid_json_body_rejected(storage: ReviewStorage) -> None:
    body = b"not json"
    headers = {
        "X-IRS-Signature": _sign(body),
        "X-IRS-Idempotency-Key": "42",
    }
    with pytest.raises(WebhookValidationError) as excinfo:
        handle_image_review(body=body, headers=headers, secret=SECRET, storage=storage)
    assert excinfo.value.status_code == 400


def test_wrong_event_type_rejected(storage: ReviewStorage) -> None:
    payload = {
        "event_id": "x",
        "event_type": "something.else",
        "idempotency_key": "42",
        "occurred_at": datetime.now(UTC).isoformat(),
        "data": {
            "image_id": "i",
            "correlation_id": "42",
            "decision": "合格",
            "is_portrait": True,
            "is_real_person": True,
            "face_visible": True,
            "model_name": "m",
            "analyzed_at": "t",
        },
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "X-IRS-Signature": _sign(body),
        "X-IRS-Idempotency-Key": "42",
    }
    with pytest.raises(WebhookValidationError) as excinfo:
        handle_image_review(body=body, headers=headers, secret=SECRET, storage=storage)
    assert excinfo.value.status_code == 400


def test_pending_status_marked_rejected_on_fail_decision(storage: ReviewStorage) -> None:
    body = _envelope_body(decision="不合格")
    headers = {
        "X-IRS-Signature": _sign(body),
        "X-IRS-Idempotency-Key": "42",
    }
    handle_image_review(body=body, headers=headers, secret=SECRET, storage=storage)
    v = storage.get_verdict(42)
    assert v is not None
    assert v.decision == "不合格"
    # Still the verdict_received status (gate decides the rest)
    pr = storage.get_pending_review(42)
    assert pr is not None
    assert pr.status == "verdict_received"


def test_no_matching_pending_review_still_stores_verdict(storage: ReviewStorage) -> None:
    body = _envelope_body(message_id=999)  # not in pending_reviews
    headers = {
        "X-IRS-Signature": _sign(body),
        "X-IRS-Idempotency-Key": "999",
    }
    result = handle_image_review(body=body, headers=headers, secret=SECRET, storage=storage)
    assert result.status == "accepted"
    v = storage.get_verdict(999)
    assert v is not None
