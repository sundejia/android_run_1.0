"""
文本消息处理器

处理普通文本消息的存储。
"""

from typing import Any

from wecom_automation.core.interfaces import MessageContext, MessageProcessResult
from wecom_automation.database.models import MessageRecord, MessageType
from wecom_automation.services.message.handlers.base import BaseMessageHandler


class TextMessageHandler(BaseMessageHandler):
    """
    文本消息处理器

    职责:
    - 识别文本消息
    - 存储文本消息到数据库
    - 处理消息去重
    """

    async def can_handle(self, message: Any) -> bool:
        """
        判断是否为文本消息

        Args:
            message: 消息对象

        Returns:
            True如果是文本消息
        """
        msg_type = self._get_message_type(message)

        # 显式标记为文本
        if msg_type in ("text", "TEXT"):
            return True

        # 没有特殊标记且有内容的消息
        if msg_type in ("unknown", ""):
            content = self._get_content(message)
            if content and not self._has_media(message):
                return True

        return False

    def _has_media(self, message: Any) -> bool:
        """检查消息是否包含媒体"""
        # 检查图片
        if hasattr(message, "image_bounds") and message.image_bounds:
            return True
        # 检查语音
        if hasattr(message, "voice_duration") and message.voice_duration:
            return True
        # 检查视频
        if hasattr(message, "video_bounds") and message.video_bounds:
            return True

        return False

    async def process(self, message: Any, context: MessageContext) -> MessageProcessResult:
        """
        处理文本消息

        Args:
            message: 消息对象
            context: 消息上下文

        Returns:
            处理结果
        """
        content = self._get_content(message)
        is_from_kefu = self._is_from_kefu(message)

        # 对于客服消息，先检查是否已存在相同内容
        # 解决重复同步时，由于时间戳差异导致hash不同而重复写入的问题
        if is_from_kefu and content:
            if self._repository.check_kefu_message_exists(context.customer_id, content, "text"):
                self._logger.debug(f"Kefu message already exists (content match): {content[:30]}...")
                return MessageProcessResult(
                    added=False,
                    message_type="text",
                    message_id=None,
                    content=content,
                )

        # 解析时间戳
        timestamp_raw, timestamp_parsed = self._get_parsed_timestamp(message)

        # 创建消息记录
        record = MessageRecord(
            customer_id=context.customer_id,
            content=content,
            message_type=MessageType.TEXT.value,
            is_from_kefu=is_from_kefu,
            timestamp_raw=timestamp_raw,
            timestamp_parsed=timestamp_parsed,
        )

        # 保存到数据库（自动去重）
        added, msg_record = self._repository.add_message_if_not_exists(record)

        if added:
            self._logger.debug(
                f"Text message saved: {content[:30]}..." if len(content) > 30 else f"Text message saved: {content}"
            )
        else:
            self._logger.debug("Text message skipped (duplicate)")

        return MessageProcessResult(
            added=added,
            message_type="text",
            message_id=msg_record.id if msg_record else None,
            content=content,
        )
