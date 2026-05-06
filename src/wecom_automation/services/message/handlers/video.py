"""
视频消息处理器

处理视频消息的识别、下载和存储。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from wecom_automation.core.interfaces import MessageContext, MessageProcessResult
from wecom_automation.database.models import VideoRecord
from wecom_automation.database.repository import ConversationRepository
from wecom_automation.services.message.dedupe_record import video_message_record_for_dedupe
from wecom_automation.services.message.handlers.base import BaseMessageHandler


class VideoMessageHandler(BaseMessageHandler):
    """
    视频消息处理器

    职责:
    - 识别视频消息
    - 下载并保存视频到本地
    - 创建消息和视频记录
    """

    def __init__(
        self,
        repository: ConversationRepository,
        wecom_service,
        videos_dir: Path,
        logger=None,
        wait_for_review: bool = False,
    ):
        """
        初始化视频消息处理器

        Args:
            repository: 数据库仓库
            wecom_service: WeComService实例
            videos_dir: 视频保存目录
            logger: 日志记录器
            wait_for_review: True 时同步等待视频多帧 AI 审核完成（用于 realtime
                门控，需要在 should_execute 之前拿到 ai_review_*）。False
                则保持原有 fire-and-forget，避免阻塞全量同步。
        """
        super().__init__(repository, logger)
        self._wecom = wecom_service
        self._wait_for_review = wait_for_review
        self._videos_dir = Path(videos_dir)
        self._videos_dir.mkdir(parents=True, exist_ok=True)

    async def can_handle(self, message: Any) -> bool:
        """
        判断是否为视频消息

        Args:
            message: 消息对象

        Returns:
            True如果是视频消息
        """
        # 类型标记
        msg_type = self._get_message_type(message)
        if msg_type in ("video", "VIDEO"):
            return True

        # 检查视频bounds（Note: ConversationMessage 没有 video_bounds 字段，使用 raw_bounds 作为容器边界）
        # 前向兼容：如果有 video_bounds 属性则使用
        if hasattr(message, "video_bounds") and message.video_bounds:
            return True
        # 使用 raw_bounds 作为视频容器边界 - 只有在明确是视频类型或者有其他视频特征时才应该处理
        # 仅有 raw_bounds 不足以证明是视频，因为所有消息都有 raw_bounds
        # if hasattr(message, 'raw_bounds') and message.raw_bounds:
        #    return True

        # 检查视频时长
        if hasattr(message, "video_duration") and message.video_duration:
            return True

        return False

    async def process(self, message: Any, context: MessageContext) -> MessageProcessResult:
        """
        处理视频消息

        Args:
            message: 消息对象
            context: 消息上下文

        Returns:
            处理结果
        """
        video_bounds = getattr(message, "video_bounds", None) or getattr(message, "raw_bounds", None)
        video_duration = getattr(message, "video_duration", None)

        record = video_message_record_for_dedupe(message, context.customer_id)

        # 保存到数据库
        added, msg_record = self._repository.add_message_if_not_exists(record)

        if not added:
            self._logger.debug("Video message skipped (duplicate)")
            return MessageProcessResult(
                added=False,
                message_type="video",
                message_id=msg_record.id if msg_record else None,
            )

        # 保存视频文件
        # Priority 1: use pre-downloaded file (set by media download step before DB storage,
        # e.g. via _download_video_inline in realtime/test flows)
        pre_downloaded_path = getattr(message, "video_local_path", None)
        video_path = None

        if pre_downloaded_path and msg_record:
            src = Path(pre_downloaded_path)
            if src.exists():
                self._logger.info(f"Using pre-downloaded video: {src}")
                video_path = await self._use_predownloaded_video(
                    src, context.customer_id, msg_record.id, video_duration
                )
            else:
                self._logger.warning(f"Pre-downloaded video not found: {src}")

        # Priority 2: download via wecom_service (original flow, works during full sync)
        if not video_path and video_bounds and msg_record:
            video_path = await self._save_video(
                message, context.customer_id, msg_record.id, video_bounds, video_duration
            )

        # 根据保存结果显示不同的日志
        if video_path:
            self._logger.info(
                f"Video saved successfully: customer={context.customer_name}, "
                f"duration={video_duration}, path={video_path}"
            )
        else:
            self._logger.warning(
                f"Video NOT saved: customer={context.customer_name}, "
                f"duration={video_duration}, reason={'missing bounds or download failed' if video_bounds else 'missing bounds'}"
            )

        if video_path and msg_record:
            try:
                if self._wait_for_review:
                    from services.video_review_service import run_video_review_for_message

                    await run_video_review_for_message(msg_record.id, None)
                else:
                    from services.video_review_service import schedule_video_review_for_message

                    schedule_video_review_for_message(msg_record.id, None)
            except Exception as exc:
                self._logger.warning(f"Video AI review schedule failed: {exc}")

        return MessageProcessResult(
            added=True,
            message_type="video",
            message_id=msg_record.id if msg_record else None,
            extra={
                "path": str(video_path) if video_path else None,
                "duration": video_duration,
            },
        )

    async def _use_predownloaded_video(
        self,
        source_path: Path,
        customer_id: int,
        message_id: int,
        duration: str | None,
    ) -> Path | None:
        """
        Register a pre-downloaded video file (already on disk) and create the
        VideoRecord in the database.

        If the file is already inside the correct customer directory
        (conversation_videos/customer_{id}/), it is used in-place — no copy or
        rename. Otherwise it is moved there.
        """
        import shutil

        try:
            customer_dir = self._videos_dir / f"customer_{customer_id}"
            customer_dir.mkdir(parents=True, exist_ok=True)

            if source_path.parent.resolve() == customer_dir.resolve():
                final_path = source_path
                self._logger.info(f"Pre-downloaded video already in customer dir: {final_path}")
            else:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"video_{message_id}_{timestamp}{source_path.suffix}"
                final_path = customer_dir / filename
                if final_path.exists():
                    final_path.unlink()
                try:
                    source_path.replace(final_path)
                except OSError:
                    shutil.move(str(source_path), str(final_path))
                self._logger.info(f"Moved pre-downloaded video to: {final_path}")

            duration_seconds = self._parse_duration(duration)
            video_record = VideoRecord(
                message_id=message_id,
                file_path=str(final_path),
                file_name=final_path.name,
                duration=duration,
                duration_seconds=duration_seconds,
            )
            self._repository.create_video(video_record)
            self._repository.update_message_extra_info(message_id, {"video_path": str(final_path)})

            return final_path

        except Exception as e:
            self._logger.error(f"Failed to register pre-downloaded video: {e}")
            return None

    async def _save_video(
        self, message: Any, customer_id: int, message_id: int, bounds: str, duration: str | None
    ) -> Path | None:
        """
        保存视频到本地。

        Legacy note:
        The old fallback called `wecom.download_video(...)`, but WeComService no longer
        exposes that API. Reuse the verified inline save flow instead so followup/realtime
        reply and full sync share the same behavior.

        Args:
            message: 消息对象
            customer_id: 客户ID
            message_id: 消息ID
            bounds: 视频边界坐标
            duration: 视频时长

        Returns:
            保存的文件路径，失败返回None
        """
        try:
            # 创建客户目录
            customer_dir = self._videos_dir / f"customer_{customer_id}"
            customer_dir.mkdir(parents=True, exist_ok=True)

            filepath: Path | None = None

            # Prefer the unified inline-download flow that is already used and tested
            # by full sync and realtime reply.
            if self._wecom and hasattr(self._wecom, "_download_video_inline"):
                downloaded_path = await self._wecom._download_video_inline(
                    message,
                    customer_dir,
                    message_id,
                    set(),
                )
                if downloaded_path:
                    filepath = Path(downloaded_path)

            if filepath is None:
                self._logger.warning(
                    "WeComService does not support inline video download fallback; "
                    f"cannot save video for message {message_id}"
                )
                return None

            if filepath.exists():
                # 创建视频记录
                duration_seconds = self._parse_duration(duration)

                video_record = VideoRecord(
                    message_id=message_id,
                    file_path=str(filepath),
                    file_name=filepath.name,
                    duration=duration,
                    duration_seconds=duration_seconds,
                )
                self._repository.create_video(video_record)

                # 更新消息的extra_info
                self._repository.update_message_extra_info(message_id, {"video_path": str(filepath)})

                return filepath

        except Exception as e:
            self._logger.error(f"Failed to save video: {e}")

        return None

    def _parse_duration(self, duration: str | None) -> float | None:
        """
        解析时长字符串为秒数

        Args:
            duration: 时长字符串 (如 "1:30", "90s", "1分30秒")

        Returns:
            秒数，解析失败返回None
        """
        if not duration:
            return None

        import re

        # 尝试 "MM:SS" 格式
        match = re.match(r"^(\d+):(\d+)$", duration)
        if match:
            minutes, seconds = map(int, match.groups())
            return minutes * 60 + seconds

        # 尝试 "Xs" 或 "X秒" 格式
        match = re.match(r"^(\d+)\s*[s秒]?$", duration)
        if match:
            return float(match.group(1))

        # 尝试 "Xm" 或 "X分" 格式
        match = re.match(r"^(\d+)\s*[m分]$", duration)
        if match:
            return float(match.group(1)) * 60

        # 尝试 "X分Y秒" 格式
        match = re.match(r"^(\d+)\s*分\s*(\d+)\s*秒$", duration)
        if match:
            minutes, seconds = map(int, match.groups())
            return minutes * 60 + seconds

        return None
