"""Regression / new-path tests for MessageProcessor + ReviewGate wiring (M8).

These tests cover the M8 rewire:
    * Customer image with review_gate enabled does NOT emit immediately;
      instead, a pending_reviews row is inserted and ReviewSubmissionPort.submit
      is scheduled (fire-and-forget).
    * Customer video uses video_invite_policy:
        - "skip" (default): no emit, analytics event recorded.
        - "always": legacy direct emit on the bus.
    * Legacy fallback: when review_gate is disabled, behavior is unchanged
      (already covered by test_media_action_integration.py — we just keep it
      green by not breaking the no-injection default).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from wecom_automation.core.interfaces import MessageContext, MessageProcessResult
from wecom_automation.database.schema import init_database
from wecom_automation.services.media_actions.event_bus import MediaEventBus
from wecom_automation.services.media_actions.interfaces import (
    ActionResult,
    ActionStatus,
    MediaEvent,
)
from wecom_automation.services.message.processor import MessageProcessor
from wecom_automation.services.review.storage import ReviewStorage


def _ctx() -> MessageContext:
    return MessageContext(
        customer_id=11,
        customer_name="alice",
        channel="@WeChat",
        kefu_name="kefu-A",
        device_serial="dev-1",
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


@pytest.fixture()
def storage(tmp_path: Path) -> ReviewStorage:
    db = tmp_path / "android.db"
    init_database(str(db), force_recreate=True)
    return ReviewStorage(str(db))


def _make_handler(message_type: str, message_id: int, *, image_path: str | None = None):
    handler = AsyncMock()
    handler.can_handle = AsyncMock(return_value=True)
    extra = {"path": image_path} if image_path else {}
    handler.process = AsyncMock(
        return_value=MessageProcessResult(
            added=True,
            message_type=message_type,
            message_id=message_id,
            extra=extra,
        )
    )
    return handler


class TestImageReviewGateRouting:
    @pytest.mark.asyncio
    async def test_customer_image_inserts_pending_and_calls_submitter(
        self, storage: ReviewStorage, tmp_path: Path
    ) -> None:
        repo = MagicMock()
        repo.add_message_if_not_exists = MagicMock(return_value=(True, MagicMock(id=100)))

        bus = MediaEventBus()
        spy = AsyncMock()
        spy.action_name = "spy"
        spy.should_execute = AsyncMock(return_value=True)
        spy.execute = AsyncMock(return_value=ActionResult(action_name="spy", status=ActionStatus.SUCCESS, message="ok"))
        bus.register(spy)

        image_path = str(tmp_path / "img.png")
        handler = _make_handler("image", 100, image_path=image_path)

        submitter = AsyncMock()

        processor = MessageProcessor(
            repository=repo,
            handlers=[handler],
            media_event_bus=bus,
            review_storage=storage,
            review_submitter=submitter,
            review_gate_enabled=True,
        )
        processor.set_media_action_settings(
            {
                "enabled": True,
                "auto_group_invite": {"enabled": True, "video_invite_policy": "skip"},
                "review_gate": {"enabled": True},
            }
        )

        await processor.process(_image_msg(), _ctx())

        # Bus must NOT have been triggered yet (gate is async / driven by webhook).
        spy.should_execute.assert_not_awaited()

        # pending_reviews row was inserted.
        pending = storage.get_pending_review(100)
        assert pending is not None
        assert pending.image_path == image_path
        assert pending.customer_id == 11
        assert pending.customer_name == "alice"
        assert pending.device_serial == "dev-1"
        assert pending.kefu_name == "kefu-A"
        assert pending.status == "pending"

        # Wait for the fire-and-forget submitter task to run.
        for _ in range(50):
            if submitter.await_count >= 1:
                break
            await asyncio.sleep(0.01)
        submitter.assert_awaited_once_with(100, image_path)

        # Analytics event recorded.
        events = storage.list_events(trace_id="100")
        assert any(e.event_type == "review.submitted" for e in events)

    @pytest.mark.asyncio
    async def test_customer_image_without_path_fails_closed(self, storage: ReviewStorage) -> None:
        repo = MagicMock()
        repo.add_message_if_not_exists = MagicMock(return_value=(True, MagicMock(id=101)))
        bus = MediaEventBus()
        spy = AsyncMock()
        spy.action_name = "spy"
        spy.should_execute = AsyncMock(return_value=True)
        spy.execute = AsyncMock(return_value=ActionResult(action_name="spy", status=ActionStatus.SUCCESS, message="ok"))
        bus.register(spy)
        handler = _make_handler("image", 101, image_path=None)

        submitter = AsyncMock()
        processor = MessageProcessor(
            repository=repo,
            handlers=[handler],
            media_event_bus=bus,
            review_storage=storage,
            review_submitter=submitter,
            review_gate_enabled=True,
        )
        processor.set_media_action_settings(
            {"auto_group_invite": {"video_invite_policy": "skip"}, "review_gate": {"enabled": True}}
        )

        await processor.process(_image_msg(), _ctx())
        spy.should_execute.assert_not_awaited()
        submitter.assert_not_awaited()
        events = storage.list_events(trace_id="101")
        assert any(e.event_type == "review.submit_failed" for e in events)

    @pytest.mark.asyncio
    async def test_disabled_review_gate_uses_legacy_direct_emit(self, storage: ReviewStorage, tmp_path: Path) -> None:
        repo = MagicMock()
        repo.add_message_if_not_exists = MagicMock(return_value=(True, MagicMock(id=102)))
        bus = MediaEventBus()
        spy = AsyncMock()
        spy.action_name = "spy"
        spy.should_execute = AsyncMock(return_value=True)
        spy.execute = AsyncMock(return_value=ActionResult(action_name="spy", status=ActionStatus.SUCCESS, message="ok"))
        bus.register(spy)
        handler = _make_handler("image", 102, image_path=str(tmp_path / "x.png"))

        submitter = AsyncMock()
        processor = MessageProcessor(
            repository=repo,
            handlers=[handler],
            media_event_bus=bus,
            review_storage=storage,
            review_submitter=submitter,
            review_gate_enabled=False,
        )
        processor.set_media_action_settings({"auto_group_invite": {"video_invite_policy": "skip"}})

        await processor.process(_image_msg(), _ctx())
        spy.should_execute.assert_awaited_once()
        submitter.assert_not_awaited()
        assert storage.get_pending_review(102) is None


class TestVideoInvitePolicy:
    @pytest.mark.asyncio
    async def test_video_skip_policy_does_not_emit(self, storage: ReviewStorage) -> None:
        repo = MagicMock()
        repo.add_message_if_not_exists = MagicMock(return_value=(True, MagicMock(id=200)))
        bus = MediaEventBus()
        spy = AsyncMock()
        spy.action_name = "spy"
        spy.should_execute = AsyncMock(return_value=True)
        spy.execute = AsyncMock(return_value=ActionResult(action_name="spy", status=ActionStatus.SUCCESS, message="ok"))
        bus.register(spy)
        handler = _make_handler("video", 200)

        submitter = AsyncMock()
        processor = MessageProcessor(
            repository=repo,
            handlers=[handler],
            media_event_bus=bus,
            review_storage=storage,
            review_submitter=submitter,
            review_gate_enabled=True,
        )
        processor.set_media_action_settings(
            {"auto_group_invite": {"video_invite_policy": "skip"}, "review_gate": {"enabled": True}}
        )

        await processor.process(_video_msg(), _ctx())
        spy.should_execute.assert_not_awaited()

        events = storage.list_events(trace_id="200")
        assert any(e.event_type == "video.invite.skipped" for e in events)

    @pytest.mark.asyncio
    async def test_video_extract_frame_policy_submits_frame_for_review(self, storage: ReviewStorage, tmp_path: Path) -> None:
        repo = MagicMock()
        repo.add_message_if_not_exists = MagicMock(return_value=(True, MagicMock(id=202)))
        bus = MediaEventBus()
        spy = AsyncMock()
        spy.action_name = "spy"
        spy.should_execute = AsyncMock(return_value=True)
        spy.execute = AsyncMock(return_value=ActionResult(action_name="spy", status=ActionStatus.SUCCESS, message="ok"))
        bus.register(spy)

        video_path = str(tmp_path / "clip.mp4")
        frame_path = str(tmp_path / "clip.review.jpg")
        handler = _make_handler("video", 202)
        handler.process = AsyncMock(
            return_value=MessageProcessResult(
                added=True,
                message_type="video",
                message_id=202,
                extra={"path": video_path},
            )
        )
        submitter = AsyncMock()
        extractor = MagicMock(return_value=frame_path)
        processor = MessageProcessor(
            repository=repo,
            handlers=[handler],
            media_event_bus=bus,
            review_storage=storage,
            review_submitter=submitter,
            review_gate_enabled=True,
            video_frame_extractor=extractor,
        )
        processor.set_media_action_settings(
            {
                "auto_group_invite": {"enabled": True},
                "review_gate": {"enabled": True, "video_review_policy": "extract_frame"},
            }
        )

        await processor.process(_video_msg(), _ctx())

        spy.should_execute.assert_not_awaited()
        extractor.assert_called_once_with(video_path)
        pending = storage.get_pending_review(202)
        assert pending is not None
        assert pending.image_path == frame_path

        for _ in range(50):
            if submitter.await_count >= 1:
                break
            await asyncio.sleep(0.01)
        submitter.assert_awaited_once_with(202, frame_path)
        events = storage.list_events(trace_id="202")
        assert any(e.event_type == "video.review.frame_extracted" for e in events)

    @pytest.mark.asyncio
    async def test_video_extract_frame_failure_fails_closed(self, storage: ReviewStorage) -> None:
        repo = MagicMock()
        repo.add_message_if_not_exists = MagicMock(return_value=(True, MagicMock(id=203)))
        bus = MediaEventBus()
        spy = AsyncMock()
        spy.action_name = "spy"
        spy.should_execute = AsyncMock(return_value=True)
        bus.register(spy)
        handler = _make_handler("video", 203)
        handler.process = AsyncMock(
            return_value=MessageProcessResult(
                added=True,
                message_type="video",
                message_id=203,
                extra={"path": "/tmp/missing.mp4"},
            )
        )
        submitter = AsyncMock()
        extractor = MagicMock(side_effect=RuntimeError("ffmpeg not found"))
        processor = MessageProcessor(
            repository=repo,
            handlers=[handler],
            media_event_bus=bus,
            review_storage=storage,
            review_submitter=submitter,
            review_gate_enabled=True,
            video_frame_extractor=extractor,
        )
        processor.set_media_action_settings({"review_gate": {"enabled": True, "video_review_policy": "extract_frame"}})

        await processor.process(_video_msg(), _ctx())

        spy.should_execute.assert_not_awaited()
        submitter.assert_not_awaited()
        assert storage.get_pending_review(203) is None
        events = storage.list_events(trace_id="203")
        assert any(e.event_type == "video.review.submit_failed" for e in events)

    @pytest.mark.asyncio
    async def test_video_always_policy_emits_legacy(self, storage: ReviewStorage) -> None:
        repo = MagicMock()
        repo.add_message_if_not_exists = MagicMock(return_value=(True, MagicMock(id=201)))
        bus = MediaEventBus()
        spy = AsyncMock()
        spy.action_name = "spy"
        spy.should_execute = AsyncMock(return_value=True)
        spy.execute = AsyncMock(return_value=ActionResult(action_name="spy", status=ActionStatus.SUCCESS, message="ok"))
        bus.register(spy)
        handler = _make_handler("video", 201)

        submitter = AsyncMock()
        processor = MessageProcessor(
            repository=repo,
            handlers=[handler],
            media_event_bus=bus,
            review_storage=storage,
            review_submitter=submitter,
            review_gate_enabled=True,
        )
        processor.set_media_action_settings(
            {"auto_group_invite": {"video_invite_policy": "always"}, "review_gate": {"enabled": True}}
        )

        await processor.process(_video_msg(), _ctx())
        spy.should_execute.assert_awaited_once()
        ev: MediaEvent = spy.should_execute.call_args[0][0]
        assert ev.message_type == "video"
        assert ev.customer_name == "alice"


class TestKefuMediaIgnoredEvenWithGate:
    @pytest.mark.asyncio
    async def test_kefu_image_does_not_create_pending(self, storage: ReviewStorage) -> None:
        repo = MagicMock()
        repo.add_message_if_not_exists = MagicMock(return_value=(True, MagicMock(id=300)))
        bus = MediaEventBus()
        spy = AsyncMock()
        spy.action_name = "spy"
        spy.should_execute = AsyncMock(return_value=True)
        bus.register(spy)
        handler = _make_handler("image", 300, image_path="/tmp/x.png")

        submitter = AsyncMock()
        processor = MessageProcessor(
            repository=repo,
            handlers=[handler],
            media_event_bus=bus,
            review_storage=storage,
            review_submitter=submitter,
            review_gate_enabled=True,
        )
        processor.set_media_action_settings(
            {"auto_group_invite": {"video_invite_policy": "skip"}, "review_gate": {"enabled": True}}
        )

        kefu = _image_msg()
        kefu.is_self = True
        kefu.is_from_kefu = True
        await processor.process(kefu, _ctx())

        spy.should_execute.assert_not_awaited()
        submitter.assert_not_awaited()
        assert storage.get_pending_review(300) is None
