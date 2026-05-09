"""
图片消息处理器

处理图片消息的识别、保存和存储。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from wecom_automation.core.interfaces import MessageContext, MessageProcessResult
from wecom_automation.database.repository import ConversationRepository
from wecom_automation.services.message.dedupe_record import image_message_record_for_dedupe
from wecom_automation.services.message.handlers.base import BaseMessageHandler
from wecom_automation.services.message.image_storage import ImageStorageHelper


class ImageMessageHandler(BaseMessageHandler):
    """
    图片消息处理器

    职责:
    - 识别图片消息
    - 下载并保存图片到本地
    - 创建消息和图片记录
    """

    def __init__(
        self,
        repository: ConversationRepository,
        wecom_service,
        images_dir: Path,
        logger=None,
        wait_for_review: bool = False,
    ):
        """
        初始化图片消息处理器

        Args:
            repository: 数据库仓库
            wecom_service: WeComService实例
            images_dir: 图片保存目录
            logger: 日志记录器
        """
        super().__init__(repository, logger)
        self._wecom = wecom_service
        self._wait_for_review = wait_for_review
        _images_dir = Path(images_dir)
        _images_dir.mkdir(parents=True, exist_ok=True)

        # 使用统一的图片存储辅助类
        self._storage = ImageStorageHelper(repository=repository, images_dir=_images_dir, logger=logger)

    async def _trigger_image_review(self, image_path: Path, message_id: int) -> None:
        """Upload the saved image for review without blocking realtime storage by default."""
        from services.image_review_client import upload_image_for_review

        # Persist review verdict back to the conversation DB that owns this
        # message row. Without this, image_review_client would fall back to
        # ``get_default_db_path()`` (the control DB), and the per-device
        # ``images`` row (which actually backs ``evaluate_gate_pass``) would
        # never get its ``ai_review_*`` columns populated, causing the review
        # gate to permanently report ``image_row_missing``.
        # ``wecom_automation.database.repository.ConversationRepository`` exposes
        # ``db_path`` while ``followup.repository.ConversationRepository`` uses
        # ``_db_path``. Probe both so the path resolves regardless of which
        # repo flavour the caller wired in.
        review_db_path = getattr(self._repository, "db_path", None) or getattr(
            self._repository, "_db_path", None
        )

        if self._wait_for_review:
            await upload_image_for_review(
                image_path,
                auto_analyze=True,
                local_message_id=message_id,
                db_path=review_db_path,
            )
            return

        asyncio.create_task(
            upload_image_for_review(
                image_path,
                auto_analyze=True,
                local_message_id=message_id,
                db_path=review_db_path,
            )
        )

    async def can_handle(self, message: Any) -> bool:
        """
        判断是否为图片消息

        Args:
            message: 消息对象

        Returns:
            True如果是图片消息
        """
        # 类型标记
        msg_type = self._get_message_type(message)
        if msg_type in ("image", "IMAGE", "photo"):
            return True

        # 检查是否有图片（通过 message.image 对象）
        # Note: ConversationMessage.image 是 ImageInfo 对象，不是直接的 bounds 字符串
        if hasattr(message, "image") and message.image and message.image.bounds:
            return True

        return False

    async def process(self, message: Any, context: MessageContext) -> MessageProcessResult:
        """
        处理图片消息

        Args:
            message: 消息对象
            context: 消息上下文

        Returns:
            处理结果
        """
        # Note: ConversationMessage.image 是 ImageInfo 对象，通过 .bounds 访问坐标
        image_bounds = message.image.bounds if (message.image and hasattr(message.image, "bounds")) else None

        record = image_message_record_for_dedupe(message, context.customer_id)

        # 保存到数据库
        added, msg_record = self._repository.add_message_if_not_exists(record)

        if not added:
            self._logger.debug("Image message skipped (duplicate)")
            return MessageProcessResult(
                added=False,
                message_type="image",
                message_id=msg_record.id if msg_record else None,
            )

        # 保存图片文件
        image_path = None

        # 检查是否有图片bounds
        if not image_bounds:
            self._logger.warning(
                f"No image_bounds for message, cannot save image. "
                f"customer={context.customer_name}, message_id={msg_record.id if msg_record else 'N/A'}"
            )
        elif not msg_record:
            self._logger.warning(f"No message record created, cannot save image. customer={context.customer_name}")
        else:
            # Check if image was already captured inline during scrolling
            existing_path = None
            if hasattr(message, "image") and message.image and hasattr(message.image, "local_path"):
                if message.image.local_path:
                    existing_path = Path(message.image.local_path)
                    if existing_path.exists():
                        self._logger.info(f"Using pre-captured image: {existing_path}")

            if existing_path and existing_path.exists():
                # Copy pre-captured image to the correct customer_id directory
                image_path = self._storage.save_image_from_source(
                    source_path=existing_path,
                    customer_id=context.customer_id,
                    message_id=msg_record.id,
                    bounds=image_bounds,
                )
            elif image_bounds:
                # Fallback: use bounds to screenshot (may be inaccurate if scrolled)
                self._logger.warning("Falling back to bounds-based capture (may be inaccurate)")
                image_path = await self._storage.save_image_from_bounds(
                    wecom_service=self._wecom,
                    customer_id=context.customer_id,
                    message_id=msg_record.id,
                    bounds=image_bounds,
                )
            else:
                image_path = None

        # 根据保存结果显示不同的日志
        if image_path:
            self._logger.info(f"Image saved successfully: customer={context.customer_name}, path={image_path}")
            if msg_record:
                try:
                    await self._trigger_image_review(image_path, msg_record.id)
                except Exception as exc:
                    self._logger.warning(f"Image review upload failed: message_id={msg_record.id}, error={exc}")
        else:
            self._logger.warning(
                f"Image NOT saved: customer={context.customer_name}, "
                f"reason={'missing bounds or capture failed' if image_bounds else 'missing image_bounds attribute'}"
            )

        return MessageProcessResult(
            added=True,
            message_type="image",
            message_id=msg_record.id if msg_record else None,
            extra={"path": str(image_path) if image_path else None},
        )
