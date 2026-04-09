"""
表情包消息处理器

处理表情包消息的识别、保存和存储。
表情包按照图片方式存储，但 message_type 标记为 'sticker'。
"""

import json
from pathlib import Path
from typing import Any

from wecom_automation.core.interfaces import MessageContext, MessageProcessResult
from wecom_automation.database.models import MessageRecord, MessageType
from wecom_automation.database.repository import ConversationRepository
from wecom_automation.services.message.handlers.base import BaseMessageHandler
from wecom_automation.services.message.image_storage import ImageStorageHelper


class StickerMessageHandler(BaseMessageHandler):
    """
    表情包消息处理器

    职责:
    - 识别表情包消息
    - 截图保存表情包到本地（复用图片存储逻辑）
    - 创建消息和图片记录，message_type 为 'sticker'
    """

    def __init__(self, repository: ConversationRepository, wecom_service, images_dir: Path, logger=None):
        """
        初始化表情包消息处理器

        Args:
            repository: 数据库仓库
            wecom_service: WeComService 实例
            images_dir: 图片/表情包保存目录
            logger: 日志记录器
        """
        super().__init__(repository, logger)
        self._wecom = wecom_service
        self._images_dir = Path(images_dir)
        self._images_dir.mkdir(parents=True, exist_ok=True)

        # 复用图片存储辅助类
        self._storage = ImageStorageHelper(repository=repository, images_dir=self._images_dir, logger=logger)

    async def can_handle(self, message: Any) -> bool:
        """
        判断是否为表情包消息

        Args:
            message: 消息对象

        Returns:
            True 如果是表情包消息
        """
        msg_type = self._get_message_type(message)
        return msg_type in ("sticker", "STICKER", "表情包")

    async def process(self, message: Any, context: MessageContext) -> MessageProcessResult:
        """
        处理表情包消息

        Args:
            message: 消息对象
            context: 消息上下文

        Returns:
            处理结果
        """
        # 获取表情包 bounds（复用 image 属性）
        sticker_bounds = None
        if hasattr(message, "image") and message.image:
            sticker_bounds = message.image.bounds if hasattr(message.image, "bounds") else None

        # 解析时间戳
        timestamp_raw, timestamp_parsed = self._get_parsed_timestamp(message)

        # 创建消息记录
        extra_info = {}
        if sticker_bounds:
            extra_info["original_bounds"] = sticker_bounds
        extra_info["is_sticker"] = True  # 标记为表情包

        record = MessageRecord(
            customer_id=context.customer_id,
            content="[表情包]",  # 表情包内容标识
            message_type=MessageType.STICKER.value,  # 使用 sticker 类型
            is_from_kefu=self._is_from_kefu(message),
            timestamp_raw=timestamp_raw,
            timestamp_parsed=timestamp_parsed,
            extra_info=json.dumps(extra_info) if extra_info else None,
        )

        # 保存到数据库
        added, msg_record = self._repository.add_message_if_not_exists(record)

        if not added:
            self._logger.debug("Sticker message skipped (duplicate)")
            return MessageProcessResult(
                added=False,
                message_type="sticker",
                message_id=msg_record.id if msg_record else None,
            )

        # 保存表情包文件（截图方式，复用图片存储逻辑）
        sticker_path = None

        if not sticker_bounds:
            self._logger.warning(
                f"No sticker_bounds for message, cannot save sticker. "
                f"customer={context.customer_name}, message_id={msg_record.id if msg_record else 'N/A'}"
            )
        elif not msg_record:
            self._logger.warning(f"No message record created, cannot save sticker. customer={context.customer_name}")
        else:
            # 检查是否有预捕获的图片
            existing_path = None
            if hasattr(message, "image") and message.image and hasattr(message.image, "local_path"):
                if message.image.local_path:
                    existing_path = Path(message.image.local_path)
                    if existing_path.exists():
                        self._logger.info(f"Using pre-captured sticker: {existing_path}")

            if existing_path and existing_path.exists():
                # 复制预捕获的表情包到正确目录
                sticker_path = self._storage.save_image_from_source(
                    source_path=existing_path,
                    customer_id=context.customer_id,
                    message_id=msg_record.id,
                    bounds=sticker_bounds,
                )
            elif sticker_bounds:
                # 使用 bounds 截图
                self._logger.warning("Falling back to bounds-based capture for sticker")
                sticker_path = await self._storage.save_image_from_bounds(
                    wecom_service=self._wecom,
                    customer_id=context.customer_id,
                    message_id=msg_record.id,
                    bounds=sticker_bounds,
                )

        # 日志
        if sticker_path:
            self._logger.info(f"Sticker saved successfully: customer={context.customer_name}, path={sticker_path}")
        else:
            self._logger.warning(
                f"Sticker NOT saved: customer={context.customer_name}, "
                f"reason={'missing bounds or capture failed' if sticker_bounds else 'missing sticker_bounds'}"
            )

        return MessageProcessResult(
            added=True,
            message_type="sticker",
            message_id=msg_record.id if msg_record else None,
            extra={"path": str(sticker_path) if sticker_path else None},
        )
