"""End-to-end pipeline test (M11).

Simulates one full cycle in-process to prove the M5–M10 components compose
correctly:

    customer image / video
      → MessageProcessor (M8) inserts pending_review + schedules submitter
      → fake rating-server returns a verdict
      → webhook receiver (M6) verifies signature + persists verdict
      → ReviewGate (M7) consults skill v1
      → governance ExecutionPolicyGuard (M9) checks kill_switch / rate limit
      → MediaEventBus emits MediaEvent → mock AutoGroupInviteAction observes

Three paths verified: approve, reject, video-skip.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure the wecom-desktop backend services dir is importable so we can call
# the real webhook handler in-process.
_repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_repo / "wecom-desktop" / "backend"))

from services.webhook_receiver import handle_image_review  # noqa: E402
from wecom_automation.core.interfaces import MessageContext, MessageProcessResult  # noqa: E402
from wecom_automation.database.schema import init_database  # noqa: E402
from wecom_automation.services.governance import ExecutionPolicyGuard  # noqa: E402
from wecom_automation.services.media_actions.event_bus import MediaEventBus  # noqa: E402
from wecom_automation.services.media_actions.interfaces import (  # noqa: E402
    ActionResult,
    ActionStatus,
    MediaEvent,
)
from wecom_automation.services.message.processor import MessageProcessor  # noqa: E402
from wecom_automation.services.review.gate import (  # noqa: E402
    ReviewGate,
)
from wecom_automation.services.review.storage import ReviewStorage  # noqa: E402

SECRET = "e2e-secret"


def _ctx() -> MessageContext:
    return MessageContext(
        customer_id=42,
        customer_name="bob",
        channel="@WeChat",
        kefu_name="kefu-A",
        device_serial="dev-7",
    )


def _image_msg():
    msg = MagicMock()
    msg.is_self = False
    msg.is_from_kefu = False
    msg.message_type = "image"
    return msg


def _video_msg():
    msg = MagicMock()
    msg.is_self = False
    msg.is_from_kefu = False
    msg.message_type = "video"
    return msg


def _make_handler(message_type: str, message_id: int, image_path: str | None):
    h = AsyncMock()
    h.can_handle = AsyncMock(return_value=True)
    h.process = AsyncMock(
        return_value=MessageProcessResult(
            added=True,
            message_type=message_type,
            message_id=message_id,
            extra={"path": image_path} if image_path else {},
        )
    )
    return h


def _build_envelope(
    *,
    message_id: int,
    decision: str,
    is_portrait: bool = True,
    is_real_person: bool = True,
    face_visible: bool = True,
) -> bytes:
    payload = {
        "event_id": f"evt-{message_id}",
        "event_type": "image_review.completed",
        "idempotency_key": f"e2e-{message_id}",
        "occurred_at": datetime.now(UTC).isoformat(),
        "data": {
            "image_id": f"img-{message_id}",
            "correlation_id": str(message_id),
            "decision": decision,
            "is_portrait": is_portrait,
            "is_real_person": is_real_person,
            "face_visible": face_visible,
            "model_name": "qwen3-vl-fake",
            "analyzed_at": datetime.now(UTC).isoformat(),
            "raw_details": {},
        },
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _sign(body: bytes) -> str:
    digest = hmac.new(SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.fixture()
def storage(tmp_path: Path) -> ReviewStorage:
    db = tmp_path / "android.db"
    init_database(str(db), force_recreate=True)
    return ReviewStorage(str(db))


def _build_pipeline(
    storage: ReviewStorage,
    *,
    fake_verdict: dict,
    settings: dict,
):
    """Wire up the full pipeline. Returns ``(processor, gate, action)``.

    The ``submitter`` used by ``MessageProcessor`` synchronously simulates
    the rating-server: it builds + signs an envelope and feeds it into the
    real webhook handler, then triggers ``ReviewGate.on_verdict`` — i.e. the
    same code paths the production system uses.
    """
    bus = MediaEventBus()
    action = AsyncMock()
    action.action_name = "group_invite"
    action.should_execute = AsyncMock(return_value=True)
    action.execute = AsyncMock(
        return_value=ActionResult(action_name="group_invite", status=ActionStatus.SUCCESS, message="ok")
    )
    bus.register(action)

    guard = ExecutionPolicyGuard(storage=storage)
    gate = ReviewGate(
        storage=storage,
        bus=bus,
        settings_provider=lambda: settings,
        guard=guard,
    )

    async def submitter(message_id: int, image_path: str) -> None:
        # Simulate rating-server response.
        body = _build_envelope(message_id=message_id, **fake_verdict)
        handle_image_review(
            body=body,
            headers={
                "X-IRS-Signature": _sign(body),
                "X-IRS-Idempotency-Key": f"e2e-{message_id}",
            },
            secret=SECRET,
            storage=storage,
        )
        # Bridge into the gate as the real webhook router would (M11 wires this
        # in routers/webhooks.py via a background task; here we await directly).
        await gate.on_verdict(message_id)

    repo = MagicMock()
    repo.add_message_if_not_exists = MagicMock(return_value=(True, MagicMock(id=1)))

    processor = MessageProcessor(
        repository=repo,
        media_event_bus=bus,
        review_storage=storage,
        review_submitter=submitter,
        review_gate_enabled=True,
    )
    processor.set_media_action_settings(settings)
    return processor, gate, action


class TestE2EPipeline:
    @pytest.mark.asyncio
    async def test_approve_path_triggers_group_invite(self, storage: ReviewStorage, tmp_path: Path) -> None:
        message_id = 1001
        image_path = str(tmp_path / "ok.png")
        Path(image_path).write_bytes(b"fake")

        settings = {
            "auto_group_invite": {
                "enabled": True,
                "video_invite_policy": "skip",
            },
            "review_gate": {"enabled": True},
            "governance": {"kill_switch": False, "invite_rate_limit_seconds": 0},
        }
        fake_verdict = {
            "decision": "合格",
            "is_portrait": True,
            "is_real_person": True,
            "face_visible": True,
        }
        processor, _gate, action = _build_pipeline(storage, fake_verdict=fake_verdict, settings=settings)
        repo = processor._repository
        repo.add_message_if_not_exists = MagicMock(return_value=(True, MagicMock(id=message_id)))

        h = _make_handler("image", message_id, image_path)
        processor.register_handler(h)

        await processor.process(_image_msg(), _ctx())
        for _ in range(50):
            if action.should_execute.await_count >= 1:
                break
            await asyncio.sleep(0.01)

        action.should_execute.assert_awaited()
        ev: MediaEvent = action.should_execute.call_args[0][0]
        assert ev.message_type == "image"
        assert ev.customer_name == "bob"
        assert ev.message_id == message_id

        pending = storage.get_pending_review(message_id)
        assert pending is not None
        assert pending.status == "approved"

        verdict = storage.get_verdict(message_id)
        assert verdict is not None
        assert verdict.decision == "合格"

    @pytest.mark.asyncio
    async def test_reject_path_does_not_trigger_invite(self, storage: ReviewStorage, tmp_path: Path) -> None:
        message_id = 1002
        image_path = str(tmp_path / "bad.png")
        Path(image_path).write_bytes(b"fake")

        settings = {
            "auto_group_invite": {"video_invite_policy": "skip"},
            "review_gate": {"enabled": True},
        }
        fake_verdict = {
            "decision": "合格",
            "is_portrait": True,
            "is_real_person": False,  # rejected
            "face_visible": True,
        }
        processor, _gate, action = _build_pipeline(storage, fake_verdict=fake_verdict, settings=settings)
        repo = processor._repository
        repo.add_message_if_not_exists = MagicMock(return_value=(True, MagicMock(id=message_id)))

        h = _make_handler("image", message_id, image_path)
        processor.register_handler(h)

        await processor.process(_image_msg(), _ctx())
        await asyncio.sleep(0.05)

        action.should_execute.assert_not_awaited()

        pending = storage.get_pending_review(message_id)
        assert pending is not None
        assert pending.status == "rejected"

        events = storage.list_events(trace_id=str(message_id))
        assert any(e.event_type == "review.gate.rejected" for e in events)

    @pytest.mark.asyncio
    async def test_video_skip_policy_short_circuits(self, storage: ReviewStorage) -> None:
        message_id = 1003

        settings = {
            "auto_group_invite": {"video_invite_policy": "skip"},
            "review_gate": {"enabled": True},
        }
        fake_verdict = {
            "decision": "合格",
            "is_portrait": True,
            "is_real_person": True,
            "face_visible": True,
        }
        processor, _gate, action = _build_pipeline(storage, fake_verdict=fake_verdict, settings=settings)
        repo = processor._repository
        repo.add_message_if_not_exists = MagicMock(return_value=(True, MagicMock(id=message_id)))

        h = _make_handler("video", message_id, image_path=None)
        processor.register_handler(h)

        await processor.process(_video_msg(), _ctx())
        await asyncio.sleep(0.05)

        action.should_execute.assert_not_awaited()

        events = storage.list_events(trace_id=str(message_id))
        assert any(e.event_type == "video.invite.skipped" for e in events)
