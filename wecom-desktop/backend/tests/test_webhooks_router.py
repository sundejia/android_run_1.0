"""Router-level integration tests for /api/webhooks/image-review.

These complement the pure-handler tests by exercising the actual FastAPI
adapter, including header parsing, secret resolution, and HTTPException
mapping.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
src_dir = backend_dir.parent.parent / "src"
sys.path.insert(0, str(src_dir))

from main import app  # noqa: E402
from wecom_automation.database.schema import init_database  # noqa: E402
from wecom_automation.services.review.storage import (  # noqa: E402
    PendingReviewRow,
    ReviewStorage,
)

SECRET = "router-secret"


def _sign(body: bytes) -> str:
    digest = hmac.new(SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _envelope(message_id: int = 7) -> bytes:
    payload = {
        "event_id": "evt-r-1",
        "event_type": "image_review.completed",
        "idempotency_key": f"router-{message_id}",
        "occurred_at": datetime.now(UTC).isoformat(),
        "data": {
            "image_id": "img-r",
            "correlation_id": str(message_id),
            "decision": "合格",
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
    db = tmp_path / "router_android.db"
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
def client(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("REVIEW_WEBHOOK_SECRET", SECRET)

    import routers.webhooks as webhooks_module

    monkeypatch.setattr(
        webhooks_module,
        "_get_storage",
        lambda: ReviewStorage(str(db_path)),
    )
    return TestClient(app)


def test_post_valid_payload_returns_accepted(client: TestClient, db_path: Path) -> None:
    body = _envelope(7)
    headers = {
        "X-IRS-Signature": _sign(body),
        "X-IRS-Idempotency-Key": "router-7",
        "Content-Type": "application/json",
    }
    resp = client.post("/api/webhooks/image-review", content=body, headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["message_id"] == 7
    assert data["decision"] == "合格"

    storage = ReviewStorage(str(db_path))
    v = storage.get_verdict(7)
    assert v is not None
    assert v.decision == "合格"


def test_post_bad_signature_returns_401(client: TestClient) -> None:
    body = _envelope(7)
    headers = {
        "X-IRS-Signature": "sha256=00",
        "X-IRS-Idempotency-Key": "router-7",
        "Content-Type": "application/json",
    }
    resp = client.post("/api/webhooks/image-review", content=body, headers=headers)
    assert resp.status_code == 401


def test_post_replay_returns_replay_status(client: TestClient) -> None:
    body = _envelope(7)
    headers = {
        "X-IRS-Signature": _sign(body),
        "X-IRS-Idempotency-Key": "router-7",
        "Content-Type": "application/json",
    }
    r1 = client.post("/api/webhooks/image-review", content=body, headers=headers)
    r2 = client.post("/api/webhooks/image-review", content=body, headers=headers)
    assert r1.json()["status"] == "accepted"
    assert r2.json()["status"] == "replay"


def test_missing_secret_returns_503(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> None:
    monkeypatch.delenv("REVIEW_WEBHOOK_SECRET", raising=False)
    import routers.webhooks as webhooks_module

    monkeypatch.setattr(webhooks_module, "_get_storage", lambda: ReviewStorage(str(db_path)))
    monkeypatch.setattr(webhooks_module, "_get_secret", lambda: "")
    c = TestClient(app)
    body = _envelope(7)
    resp = c.post(
        "/api/webhooks/image-review",
        content=body,
        headers={
            "X-IRS-Signature": _sign(body),
            "X-IRS-Idempotency-Key": "router-7",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 503
