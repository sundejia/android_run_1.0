"""End-to-end test that POSTing a verdict actually drives ReviewGate.

This was the production wiring gap surfaced during the seven-requirements
audit: the webhook used to persist the verdict but nothing called
``ReviewGate.on_verdict``. After the fix, an accepted webhook MUST
schedule the gate; rejected payloads MUST NOT.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
src_dir = backend_dir.parent.parent / "src"
sys.path.insert(0, str(src_dir))

from main import app  # noqa: E402
from wecom_automation.database.schema import init_database  # noqa: E402
from wecom_automation.services.media_actions.event_bus import MediaEventBus  # noqa: E402
from wecom_automation.services.media_actions.interfaces import (  # noqa: E402
    ActionResult,
    ActionStatus,
)
from wecom_automation.services.review.gate import ReviewGate  # noqa: E402
from wecom_automation.services.review.storage import (  # noqa: E402
    PendingReviewRow,
    ReviewStorage,
)

SECRET = "drive-gate-secret"


def _sign(body: bytes) -> str:
    digest = hmac.new(SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _envelope(message_id: int = 7, decision: str = "合格") -> bytes:
    payload = {
        "event_id": f"evt-{message_id}",
        "event_type": "image_review.completed",
        "idempotency_key": f"drive-{message_id}",
        "occurred_at": datetime.now(UTC).isoformat(),
        "data": {
            "image_id": "img",
            "correlation_id": str(message_id),
            "decision": decision,
            "is_portrait": True,
            "is_real_person": True,
            "face_visible": True,
            "model_name": "qwen3-vl",
            "analyzed_at": datetime.now(UTC).isoformat(),
            "raw_details": {},
        },
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    db = tmp_path / "drive.db"
    init_database(str(db), force_recreate=True)
    storage = ReviewStorage(str(db))
    storage.insert_pending_review(
        PendingReviewRow(
            message_id=7,
            customer_id=1,
            customer_name="x",
            device_serial="d",
            channel=None,
            kefu_name="k",
            image_path="/tmp/x.png",
        )
    )
    return db


@pytest.fixture
def wired(db_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build a real gate against a recording action and inject it as the
    process-singleton the webhook router asks for."""
    monkeypatch.setenv("REVIEW_WEBHOOK_SECRET", SECRET)

    storage = ReviewStorage(str(db_path))
    bus = MediaEventBus()
    action = AsyncMock()
    action.action_name = "spy"
    action.should_execute = AsyncMock(return_value=True)
    action.execute = AsyncMock(return_value=ActionResult(action_name="spy", status=ActionStatus.SUCCESS, message="ok"))
    bus.register(action)
    gate = ReviewGate(storage=storage, bus=bus, settings_provider=lambda: {})

    import routers.webhooks as webhooks_module
    import services.review_gate_runtime as runtime

    runtime.reset_for_tests()
    monkeypatch.setattr(runtime, "get_review_gate", lambda *a, **kw: gate)
    monkeypatch.setattr(webhooks_module, "get_review_gate", lambda *a, **kw: gate)
    monkeypatch.setattr(webhooks_module, "_get_storage", lambda: ReviewStorage(str(db_path)))

    return {
        "client": TestClient(app),
        "action": action,
        "storage": storage,
    }


def test_accepted_webhook_drives_gate_and_emits(wired) -> None:
    body = _envelope(7, decision="合格")
    headers = {
        "X-IRS-Signature": _sign(body),
        "X-IRS-Idempotency-Key": "drive-7",
        "Content-Type": "application/json",
    }
    resp = wired["client"].post("/api/webhooks/image-review", content=body, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"

    # Background task should have run within the TestClient response window.
    wired["action"].should_execute.assert_awaited()
    pending = wired["storage"].get_pending_review(7)
    assert pending is not None
    assert pending.status == "approved"


def test_rejected_verdict_does_not_emit(wired) -> None:
    body = _envelope(7, decision="不合格")
    headers = {
        "X-IRS-Signature": _sign(body),
        "X-IRS-Idempotency-Key": "drive-7-rej",
        "Content-Type": "application/json",
    }
    resp = wired["client"].post("/api/webhooks/image-review", content=body, headers=headers)
    assert resp.status_code == 200
    wired["action"].should_execute.assert_not_awaited()
    assert wired["storage"].get_pending_review(7).status == "rejected"
