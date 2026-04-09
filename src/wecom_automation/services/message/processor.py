"""
消息处理器

统一处理各类消息的入口，使用责任链模式分发到具体处理器。
"""

from __future__ import annotations

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
        """Emit a MediaEvent if the result is customer media and a bus is configured."""
        if self._media_event_bus is None:
            return

        if result.message_type not in ("image", "video"):
            return

        if self._is_from_kefu(message):
            return

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

    processor = MessageProcessor(repository, logger=logger, media_event_bus=media_event_bus)
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
