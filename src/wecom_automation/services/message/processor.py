"""
消息处理器

统一处理各类消息的入口，使用责任链模式分发到具体处理器。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from wecom_automation.core.interfaces import (
    IMessageHandler,
    MessageContext,
    MessageProcessResult,
)
from wecom_automation.database.models import MessageRecord, MessageType
from wecom_automation.database.repository import ConversationRepository
from wecom_automation.services.timestamp_parser import TimestampParser


class MessageProcessor:
    """
    消息处理器

    使用责任链模式处理不同类型的消息。

    职责:
    - 注册消息处理器
    - 分发消息到合适的处理器
    - 提供默认的文本消息处理

    Usage:
        processor = MessageProcessor(repository)

        # 注册处理器
        processor.register_handler(ImageMessageHandler(...))
        processor.register_handler(VoiceMessageHandler(...))
        processor.register_handler(VideoMessageHandler(...))

        # 处理消息
        result = await processor.process(message, context)
    """

    def __init__(
        self,
        repository: ConversationRepository,
        handlers: list[IMessageHandler] | None = None,
        logger: logging.Logger | None = None,
        media_event_bus=None,
        review_storage=None,
        review_submitter=None,
        review_gate_enabled: bool = False,
        video_frame_extractor=None,
    ):
        """
        初始化消息处理器

        Args:
            repository: 数据库仓库
            handlers: 预注册的处理器列表
            logger: 日志记录器
            media_event_bus: Optional MediaEventBus for triggering actions on customer media
        """
        self._repository = repository
        self._handlers: list[IMessageHandler] = handlers or []
        self._logger = logger or logging.getLogger(__name__)
        self._media_event_bus = media_event_bus
        self._media_action_settings: dict[str, Any] = {}
        self._review_storage = review_storage
        self._review_submitter = review_submitter
        self._review_gate_enabled = bool(review_gate_enabled)
        self._video_frame_extractor = video_frame_extractor

        # 时间戳解析器
        self._timestamp_parser = TimestampParser()
        self._timestamp_parser.set_reference_time()

        # 统计信息
        self._stats = {
            "total": 0,
            "added": 0,
            "skipped": 0,
            "by_type": {},
        }

    def set_media_action_settings(self, settings: dict[str, Any]) -> None:
        """Update the settings used when emitting media events."""
        self._media_action_settings = settings

    def register_handler(self, handler: IMessageHandler) -> None:
        """
        注册消息处理器

        Args:
            handler: 消息处理器实例
        """
        self._handlers.append(handler)
        self._logger.debug(f"Registered handler: {handler.__class__.__name__}")

    def register_handlers(self, handlers: list[IMessageHandler]) -> None:
        """
        批量注册消息处理器

        Args:
            handlers: 处理器列表
        """
        for handler in handlers:
            self.register_handler(handler)

    def clear_handlers(self) -> None:
        """清空所有处理器"""
        self._handlers.clear()

    async def process(self, message: Any, context: MessageContext) -> MessageProcessResult:
        """
        处理消息

        遍历注册的处理器，找到能处理该消息的处理器执行处理。
        如果没有处理器能处理，则作为文本消息处理。

        After processing, if the message is customer media (image/video, not from kefu)
        and a MediaEventBus is configured, emit a MediaEvent for downstream actions.

        Args:
            message: 原始消息对象
            context: 消息上下文

        Returns:
            处理结果
        """
        self._stats["total"] += 1

        # 遍历处理器
        for handler in self._handlers:
            try:
                if await handler.can_handle(message):
                    result = await handler.process(message, context)
                    self._update_stats(result)
                    await self._maybe_emit_media_event(message, result, context)
                    return result
            except Exception as e:
                self._logger.error(f"Handler {handler.__class__.__name__} failed: {e}")
                # 继续尝试其他处理器
                continue

        # 默认作为文本消息处理
        result = await self._process_as_text(message, context)
        self._update_stats(result)
        return result

    async def process_batch(self, messages: list[Any], context: MessageContext) -> list[MessageProcessResult]:
        """
        批量处理消息

        Args:
            messages: 消息列表
            context: 消息上下文

        Returns:
            处理结果列表
        """
        results = []
        for message in messages:
            result = await self.process(message, context)
            results.append(result)
        return results

    async def _process_as_text(self, message: Any, context: MessageContext) -> MessageProcessResult:
        """
        默认文本消息处理

        Args:
            message: 消息对象
            context: 消息上下文

        Returns:
            处理结果
        """
        # 获取消息内容
        content = self._get_content(message)

        # 解析时间戳
        timestamp_raw, timestamp_parsed = self._parse_timestamp(message)

        # 创建消息记录
        record = MessageRecord(
            customer_id=context.customer_id,
            content=content,
            message_type=MessageType.TEXT.value,
            is_from_kefu=self._is_from_kefu(message),
            timestamp_raw=timestamp_raw,
            timestamp_parsed=timestamp_parsed,
        )

        # 保存到数据库
        added, msg_record = self._repository.add_message_if_not_exists(record)

        return MessageProcessResult(
            added=added,
            message_type="text",
            message_id=msg_record.id if msg_record else None,
            content=content,
        )

    def _get_content(self, message: Any) -> str:
        """获取消息内容"""
        if hasattr(message, "content"):
            return str(message.content or "")
        if hasattr(message, "text"):
            return str(message.text or "")
        return ""

    def _is_from_kefu(self, message: Any) -> bool:
        """判断是否来自客服"""
        if hasattr(message, "is_self"):
            return message.is_self
        if hasattr(message, "is_from_kefu"):
            return message.is_from_kefu
        return False

    def _get_timestamp(self, message: Any) -> str | None:
        """获取时间戳"""
        if hasattr(message, "timestamp"):
            return message.timestamp
        if hasattr(message, "timestamp_raw"):
            return message.timestamp_raw
        return None

    def _parse_timestamp(self, message: Any) -> tuple[str | None, datetime | None]:
        """
        解析时间戳

        支持四种格式:
        1. 年/月/日 时:分 (如 "2024/12/25 14:30")
        2. 星期+时分 (如 "星期一 14:30" 或 "周一 下午 2:30")
        3. yesterday 时分 (如 "昨天 14:30")
        4. 直接时分 (如 "14:30" - 表示今天)

        Args:
            message: 消息对象

        Returns:
            元组 (原始时间戳, 解析后的datetime)
        """
        timestamp_raw = self._get_timestamp(message)
        if not timestamp_raw:
            return None, None

        # 刷新参考时间
        self._timestamp_parser.set_reference_time()

        parsed = self._timestamp_parser.parse(timestamp_raw)
        return timestamp_raw, parsed

    async def _maybe_emit_media_event(
        self, message: Any, result: MessageProcessResult, context: MessageContext
    ) -> None:
        """Route customer media through the review gate (M8) or legacy emit.

        Image flow when review-gate is active:
            1. Insert ``pending_reviews`` row keyed by message_id.
            2. ``asyncio.create_task`` the configured ``review_submitter``
               (fire-and-forget so the realtime pipeline never blocks).
            3. Record a ``review.submitted`` analytics event.
            The actual MediaEventBus emission happens later in ReviewGate
            once the rating-server posts back a verdict.

        Video flow:
            * ``video_invite_policy == "extract_frame"`` (default when the
              review gate is active): extract a representative frame and submit
              it through the same review pipeline as images.
            * ``video_invite_policy == "skip"``: record analytics event and
              stop. No group invite is triggered for raw video.
            * ``video_invite_policy == "always"``: emit on the bus directly
              (legacy behaviour) so existing operators can opt in.

        Falls back to the legacy direct emit when the review gate is
        disabled or the required components were not injected.
        """
        if self._media_event_bus is None:
            return
        if result.message_type not in ("image", "video"):
            return
        if self._is_from_kefu(message):
            return

        gate_active = (
            self._review_gate_enabled and self._review_storage is not None and self._review_submitter is not None
        )

        if result.message_type == "video":
            await self._handle_video_event(result, context, gate_active)
            return

        if gate_active:
            image_path = (result.extra or {}).get("path")
            if image_path:
                await self._submit_for_review(result, context, image_path)
                return
            self._logger.warning(
                "Image without saved path; review gate fails closed (message_id=%s)",
                result.message_id,
            )
            if result.message_id is not None:
                try:
                    self._review_storage.record_event(
                        "review.submit_failed",
                        trace_id=str(result.message_id),
                        payload={
                            "customer_id": context.customer_id,
                            "customer_name": context.customer_name,
                            "reason": "missing image path",
                        },
                    )
                except Exception as exc:
                    self._logger.warning("review submit failure analytics recording failed: %s", exc)
            return

        await self._emit_legacy(result, context)

    async def _handle_video_event(
        self, result: MessageProcessResult, context: MessageContext, gate_active: bool
    ) -> None:
        invite_settings = self._media_action_settings.get("auto_group_invite", {}) or {}
        gate_settings = self._media_action_settings.get("review_gate", {}) or {}
        policy = gate_settings.get("video_review_policy") or invite_settings.get("video_invite_policy", "extract_frame")
        if not gate_active:
            # No gate configured at all → preserve legacy behaviour.
            await self._emit_legacy(result, context)
            return
        if policy == "always":
            await self._emit_legacy(result, context)
            return
        if policy == "extract_frame":
            await self._submit_video_frame_for_review(result, context)
            return
        # Default = skip: log analytics so operators can audit.
        if self._review_storage is not None and result.message_id is not None:
            try:
                self._review_storage.record_event(
                    "video.invite.skipped",
                    trace_id=str(result.message_id),
                    payload={
                        "customer_id": context.customer_id,
                        "customer_name": context.customer_name,
                        "device_serial": context.device_serial,
                        "policy": policy,
                    },
                )
            except Exception as exc:
                self._logger.warning("video skip analytics recording failed: %s", exc)

    async def _submit_video_frame_for_review(self, result: MessageProcessResult, context: MessageContext) -> None:
        video_path = (result.extra or {}).get("path")
        message_id = result.message_id
        if message_id is None:
            self._logger.warning("Video without message_id; cannot submit review frame")
            return
        if not video_path:
            self._record_video_review_failure(message_id, context, "missing video path")
            return

        extractor = self._video_frame_extractor
        if extractor is None:
            from wecom_automation.services.review.video_frames import extract_review_frame

            extractor = extract_review_frame

        try:
            maybe_frame = extractor(video_path)
            if asyncio.iscoroutine(maybe_frame):
                maybe_frame = await maybe_frame
            frame_path = str(maybe_frame)
        except Exception as exc:
            self._record_video_review_failure(message_id, context, str(exc))
            return

        try:
            self._review_storage.record_event(
                "video.review.frame_extracted",
                trace_id=str(message_id),
                payload={
                    "customer_id": context.customer_id,
                    "customer_name": context.customer_name,
                    "device_serial": context.device_serial,
                    "video_path": video_path,
                    "frame_path": frame_path,
                },
            )
        except Exception as exc:
            self._logger.warning("video frame analytics recording failed: %s", exc)

        await self._submit_for_review(result, context, frame_path)

    def _record_video_review_failure(self, message_id: int, context: MessageContext, reason: str) -> None:
        if self._review_storage is None:
            return
        try:
            self._review_storage.record_event(
                "video.review.submit_failed",
                trace_id=str(message_id),
                payload={
                    "customer_id": context.customer_id,
                    "customer_name": context.customer_name,
                    "device_serial": context.device_serial,
                    "reason": reason,
                },
            )
        except Exception as exc:
            self._logger.warning("video review failure analytics recording failed: %s", exc)

    async def _submit_for_review(self, result: MessageProcessResult, context: MessageContext, image_path: str) -> None:
        from wecom_automation.services.review.storage import PendingReviewRow

        message_id = result.message_id
        if message_id is None:
            self._logger.warning("Image without message_id; cannot submit for review")
            return
        try:
            self._review_storage.insert_pending_review(
                PendingReviewRow(
                    message_id=int(message_id),
                    customer_id=context.customer_id,
                    customer_name=context.customer_name,
                    device_serial=context.device_serial,
                    channel=context.channel,
                    kefu_name=context.kefu_name,
                    image_path=image_path,
                )
            )
        except Exception as exc:
            self._logger.error("insert_pending_review failed: %s", exc)
            return

        try:
            self._review_storage.record_event(
                "review.submitted",
                trace_id=str(message_id),
                payload={
                    "customer_id": context.customer_id,
                    "customer_name": context.customer_name,
                    "image_path": image_path,
                },
            )
        except Exception as exc:
            self._logger.warning("review.submitted analytics recording failed: %s", exc)

        async def _safe_submit() -> None:
            try:
                await self._review_submitter(int(message_id), image_path)
            except Exception as exc:
                self._logger.error("review submission failed for message_id=%s: %s", message_id, exc)
                try:
                    self._review_storage.mark_pending_status(int(message_id), "submit_failed", last_error=str(exc))
                except Exception:
                    pass

        try:
            asyncio.get_running_loop().create_task(_safe_submit())
        except RuntimeError:
            # No running loop (sync context — should not happen in production
            # but keeps unit tests robust): run inline.
            await _safe_submit()

    async def _emit_legacy(self, result: MessageProcessResult, context: MessageContext) -> None:
        try:
            from wecom_automation.services.media_actions.interfaces import MediaEvent

            event = MediaEvent(
                event_type="customer_media_detected",
                message_type=result.message_type,
                customer_id=context.customer_id,
                customer_name=context.customer_name,
                channel=context.channel,
                device_serial=context.device_serial,
                kefu_name=context.kefu_name,
                message_id=result.message_id,
                timestamp=datetime.now(),
            )
            await self._media_event_bus.emit(event, self._media_action_settings)
        except Exception as exc:
            self._logger.error("MediaEventBus emit failed (non-blocking): %s", exc)

    def _update_stats(self, result: MessageProcessResult) -> None:
        """更新统计信息"""
        if result.added:
            self._stats["added"] += 1
        else:
            self._stats["skipped"] += 1

        msg_type = result.message_type
        if msg_type not in self._stats["by_type"]:
            self._stats["by_type"][msg_type] = {"added": 0, "skipped": 0}

        if result.added:
            self._stats["by_type"][msg_type]["added"] += 1
        else:
            self._stats["by_type"][msg_type]["skipped"] += 1

    def get_stats(self) -> dict[str, Any]:
        """
        获取处理统计信息

        Returns:
            统计字典
        """
        return self._stats.copy()

    def reset_stats(self) -> None:
        """重置统计信息"""
        self._stats = {
            "total": 0,
            "added": 0,
            "skipped": 0,
            "by_type": {},
        }


def create_message_processor(
    repository: ConversationRepository,
    wecom_service=None,
    images_dir: str | None = None,
    videos_dir: str | None = None,
    voices_dir: str | None = None,
    logger: logging.Logger | None = None,
    media_event_bus=None,
    media_action_settings: dict[str, Any] | None = None,
    review_storage=None,
    review_submitter=None,
    review_gate_enabled: bool = False,
    video_frame_extractor=None,
) -> MessageProcessor:
    """
    创建消息处理器并注册所有默认处理器

    Args:
        repository: 数据库仓库
        wecom_service: WeComService实例
        images_dir: 图片保存目录
        videos_dir: 视频保存目录
        voices_dir: 语音保存目录
        logger: 日志记录器
        media_event_bus: Optional MediaEventBus for customer media auto-actions
        media_action_settings: Settings dict passed to the bus on emit (if bus set)

    Returns:
        配置好的 MessageProcessor 实例
    """
    from pathlib import Path

    from wecom_automation.services.message.handlers.image import ImageMessageHandler
    from wecom_automation.services.message.handlers.sticker import StickerMessageHandler
    from wecom_automation.services.message.handlers.text import TextMessageHandler
    from wecom_automation.services.message.handlers.video import VideoMessageHandler
    from wecom_automation.services.message.handlers.voice import VoiceMessageHandler

    processor = MessageProcessor(
        repository,
        logger=logger,
        media_event_bus=media_event_bus,
        review_storage=review_storage,
        review_submitter=review_submitter,
        review_gate_enabled=review_gate_enabled,
        video_frame_extractor=video_frame_extractor,
    )
    if media_action_settings is not None:
        processor.set_media_action_settings(media_action_settings)

    # 注册文本处理器
    processor.register_handler(TextMessageHandler(repository, logger))

    # 注册表情包处理器（必须在图片处理器之前）
    if images_dir and wecom_service:
        processor.register_handler(StickerMessageHandler(repository, wecom_service, Path(images_dir), logger))

    # 注册图片处理器
    if images_dir and wecom_service:
        processor.register_handler(ImageMessageHandler(repository, wecom_service, Path(images_dir), logger))

    # 注册语音处理器
    processor.register_handler(
        VoiceMessageHandler(repository, wecom_service, Path(voices_dir) if voices_dir else None, logger=logger)
    )

    # 注册视频处理器
    if videos_dir and wecom_service:
        processor.register_handler(VideoMessageHandler(repository, wecom_service, Path(videos_dir), logger))

    return processor
