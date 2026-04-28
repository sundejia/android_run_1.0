"""Cross-process HTTP E2E for the inbound review pipeline.

This test boots the actual webhook router *as a separate uvicorn
process* on an ephemeral port and drives it with a real, HMAC-signed
HTTP POST. It is the highest-fidelity E2E in the test suite; everything
short of "real Qwen + real ADB" is exercised:

    test process ──HTTP─▶ uvicorn subprocess
                         (real FastAPI app)
                         (real webhook_receiver / signature / idempotency)
                         (real ReviewGate / PolicyEvaluator / MediaEventBus)
                         (real RecordingAction → sentinel file)

Pass criteria:
    1. Approved verdict ⇒ pending row reaches status="approved" AND the
       recording action is invoked exactly once (sentinel file written).
    2. Rejected verdict ⇒ status="rejected" AND no sentinel write.
    3. Replay of the same idempotency key ⇒ subprocess returns
       status="replay" without re-invoking the action.

This is the test the operator needs to trust before any production roll.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_ready(url: str, timeout_seconds: float = 20.0) -> None:
    deadline = time.time() + timeout_seconds
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=1.0)
            if r.status_code < 500:
                return
        except Exception as e:
            last_err = e
        time.sleep(0.2)
    raise RuntimeError(f"server not ready within {timeout_seconds}s: {last_err}")


def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _envelope(
    *,
    message_id: int,
    decision: str,
    is_portrait: bool = True,
    is_real_person: bool = True,
    face_visible: bool = True,
    idempotency_key: str | None = None,
) -> bytes:
    payload = {
        "event_id": str(uuid.uuid4()),
        "event_type": "image_review.completed",
        "idempotency_key": idempotency_key or f"e2e-{message_id}-{uuid.uuid4()}",
        "occurred_at": datetime.now(UTC).isoformat(),
        "data": {
            "image_id": f"img-{message_id}",
            "correlation_id": str(message_id),
            "decision": decision,
            "is_portrait": is_portrait,
            "is_real_person": is_real_person,
            "face_visible": face_visible,
            "model_name": "qwen3-vl",
            "analyzed_at": datetime.now(UTC).isoformat(),
            "raw_details": {},
        },
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _wait_until(predicate, timeout_seconds: float = 6.0, interval: float = 0.1):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.fixture()
def server(tmp_path: Path):
    """Spawn the e2e subprocess app. Yields ``(base_url, secret, db_path, sentinel_path)``."""
    db_path = tmp_path / "e2e.db"
    sentinel = tmp_path / "sentinel.txt"
    secret = "cross-proc-e2e-secret"
    pending_id = 4242
    port = _free_port()

    repo_root = Path(__file__).resolve().parents[2]
    app_module = "tests.integration._e2e_subprocess_app"

    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{repo_root / 'src'}{os.pathsep}{repo_root}{os.pathsep}{repo_root / 'wecom-desktop' / 'backend'}"
    )
    env["E2E_DB_PATH"] = str(db_path)
    env["E2E_SECRET"] = secret
    env["E2E_SENTINEL"] = str(sentinel)
    env["E2E_PENDING_ID"] = str(pending_id)
    env["REVIEW_WEBHOOK_SECRET"] = secret
    # Critical: align the webhook router's storage path with the seeded DB.
    # webhook_receiver / review_gate_runtime both call get_control_db_path()
    # which honors WECOM_DB_PATH.
    env["WECOM_DB_PATH"] = str(db_path)
    env["PYTHONIOENCODING"] = "utf-8"

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        f"{app_module}:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]

    log_path = tmp_path / "uvicorn.log"
    log_fh = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        cwd=str(repo_root),
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_ready(f"{base_url}/openapi.json")
        yield {
            "base_url": base_url,
            "secret": secret,
            "db_path": str(db_path),
            "sentinel": sentinel,
            "pending_id": pending_id,
            "log_path": log_path,
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        log_fh.close()
        # Surface the subprocess log when a test fails so debugging is possible.
        if log_path.exists():
            try:
                tail = log_path.read_text(encoding="utf-8", errors="replace")
                print("\n----- uvicorn subprocess log -----")
                print(tail[-4000:])
                print("----- end -----")
            except Exception:
                pass


def _post_verdict(server_info: dict, body: bytes, idempotency_key: str) -> httpx.Response:
    return httpx.post(
        f"{server_info['base_url']}/api/webhooks/image-review",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-IRS-Signature": _sign(body, server_info["secret"]),
            "X-IRS-Idempotency-Key": idempotency_key,
        },
        timeout=10.0,
    )


class TestCrossProcessHappyPath:
    def test_approved_webhook_drives_action_over_real_http(self, server) -> None:
        from wecom_automation.services.review.storage import ReviewStorage

        idem = "e2e-approved-1"
        body = _envelope(
            message_id=server["pending_id"],
            decision="合格",
            idempotency_key=idem,
        )
        r = _post_verdict(server, body, idem)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "accepted"

        sentinel: Path = server["sentinel"]
        assert _wait_until(lambda: sentinel.exists() and sentinel.stat().st_size > 0), (
            "RecordingAction sentinel was never written; gate did not emit"
        )
        line = sentinel.read_text(encoding="utf-8").splitlines()[0]
        # event_type|message_id|customer_id|device_serial
        parts = line.split("|")
        assert parts[1] == str(server["pending_id"])
        assert parts[2] == "1"  # seeded customer_id
        assert parts[3] == "e2e-dev"  # seeded device_serial

        storage = ReviewStorage(server["db_path"])
        pending = storage.get_pending_review(server["pending_id"])
        assert pending is not None
        assert pending.status == "approved"


class TestCrossProcessRejectPath:
    def test_rejected_verdict_does_not_invoke_action(self, server) -> None:
        from wecom_automation.services.review.storage import ReviewStorage

        idem = "e2e-rejected-1"
        body = _envelope(
            message_id=server["pending_id"],
            decision="不合格",
            is_real_person=False,
            face_visible=False,
            idempotency_key=idem,
        )
        r = _post_verdict(server, body, idem)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "accepted"

        # Give the background task time to finish; sentinel must remain absent.
        time.sleep(0.8)
        sentinel: Path = server["sentinel"]
        assert not sentinel.exists() or sentinel.stat().st_size == 0, (
            "Action was invoked on a rejected verdict (should not happen)"
        )

        storage = ReviewStorage(server["db_path"])
        pending = storage.get_pending_review(server["pending_id"])
        assert pending is not None
        assert pending.status == "rejected"


class TestCrossProcessIdempotency:
    def test_replay_returns_replay_and_no_extra_action(self, server) -> None:
        from wecom_automation.services.review.storage import ReviewStorage

        idem = "e2e-replay-1"
        body = _envelope(
            message_id=server["pending_id"],
            decision="合格",
            idempotency_key=idem,
        )
        r1 = _post_verdict(server, body, idem)
        assert r1.json()["status"] == "accepted"

        sentinel: Path = server["sentinel"]
        assert _wait_until(lambda: sentinel.exists() and sentinel.stat().st_size > 0)
        first_size = sentinel.stat().st_size

        r2 = _post_verdict(server, body, idem)
        assert r2.status_code == 200
        assert r2.json()["status"] == "replay"

        time.sleep(0.6)
        assert sentinel.stat().st_size == first_size, "Replay caused the action to fire a second time"

        storage = ReviewStorage(server["db_path"])
        assert storage.get_pending_review(server["pending_id"]).status == "approved"


class TestCrossProcessSecurity:
    def test_bad_signature_rejected(self, server) -> None:
        from wecom_automation.services.review.storage import ReviewStorage

        body = _envelope(message_id=server["pending_id"], decision="合格")
        r = httpx.post(
            f"{server['base_url']}/api/webhooks/image-review",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-IRS-Signature": "sha256=00",
                "X-IRS-Idempotency-Key": "bad-sig",
            },
            timeout=5.0,
        )
        assert r.status_code == 401

        time.sleep(0.4)
        sentinel: Path = server["sentinel"]
        assert not sentinel.exists() or sentinel.stat().st_size == 0, "Bad signature still invoked the action"

        storage = ReviewStorage(server["db_path"])
        # Pending must remain in its initial state.
        assert storage.get_pending_review(server["pending_id"]).status == "pending"
