"""
语音消息处理器

处理语音消息的识别、转写和存储。
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from wecom_automation.core.interfaces import (
    CustomerVoiceCallback,
    MessageContext,
    MessageProcessResult,
    VoiceHandlerAction,
    VoiceHandlerCallback,
)
from wecom_automation.database.models import VoiceRecord
from wecom_automation.database.repository import ConversationRepository
from wecom_automation.services.message.dedupe_record import voice_message_record_for_dedupe
from wecom_automation.services.message.handlers.base import BaseMessageHandler


class VoiceMessageHandler(BaseMessageHandler):
    """
    语音消息处理器

    职责:
    - 识别语音消息
    - 处理语音转文字（字幕或用户输入）
    - 下载语音文件（可选）
    - 触发客户语音通知回调
    """

    def __init__(
        self,
        repository: ConversationRepository,
        wecom_service=None,
        voices_dir: Path | None = None,
        on_customer_voice: CustomerVoiceCallback | None = None,
        logger=None,
    ):
        """
        初始化语音消息处理器

        Args:
            repository: 数据库仓库
            wecom_service: WeComService实例（用于下载语音）
            voices_dir: 语音文件保存目录
            on_customer_voice: 客户发送语音时的回调
            logger: 日志记录器
        """
        super().__init__(repository, logger)
        self._wecom = wecom_service
        self._voices_dir = Path(voices_dir) if voices_dir else None
        self._on_customer_voice = on_customer_voice
        self._interactive_handler: VoiceHandlerCallback | None = None

        if self._voices_dir:
            self._voices_dir.mkdir(parents=True, exist_ok=True)

    def set_interactive_handler(self, handler: VoiceHandlerCallback) -> None:
        """
        设置交互式语音处理回调

        当语音消息没有字幕时，调用此回调让用户选择如何处理。

        Args:
            handler: 回调函数，接收消息对象，返回 (动作, 可选文本)
        """
        self._interactive_handler = handler

    def set_customer_voice_callback(self, callback: CustomerVoiceCallback) -> None:
        """
        设置客户语音回调

        当客户发送语音消息时触发此回调。

        Args:
            callback: 回调函数 (customer_name, channel, serial) -> None
        """
        self._on_customer_voice = callback

    async def can_handle(self, message: Any) -> bool:
        """
        判断是否为语音消息

        Args:
            message: 消息对象

        Returns:
            True如果是语音消息
        """
        # 类型标记
        msg_type = self._get_message_type(message)
        if msg_type in ("voice", "VOICE", "audio"):
            return True

        # 检查语音时长
        if hasattr(message, "voice_duration") and message.voice_duration:
            return True

        return False

    async def process(self, message: Any, context: MessageContext) -> MessageProcessResult:
        """
        处理语音消息

        Args:
            message: 消息对象
            context: 消息上下文

        Returns:
            处理结果
        """
        # 获取语音内容
        content, skipped = await self._get_voice_content(message, context)

        if skipped:
            self._logger.debug("Voice message skipped by user")
            return MessageProcessResult(
                added=False,
                message_type="voice",
                extra={"skipped": True},
            )

        voice_duration = getattr(message, "voice_duration", None)

        record = voice_message_record_for_dedupe(message, context.customer_id, content=content)

        added, msg_record = self._repository.add_message_if_not_exists(record)

        if not added:
            self._logger.debug("Voice message skipped (duplicate)")
            return MessageProcessResult(
                added=False,
                message_type="voice",
                message_id=msg_record.id if msg_record else None,
            )

        voice_path = None
        if msg_record and getattr(message, "voice_local_path", None) and self._voices_dir:
            voice_path = await self._save_voice_file(
                message=message,
                customer_id=context.customer_id,
                message_id=msg_record.id,
            )
        elif getattr(message, "voice_local_path", None) and not self._voices_dir:
            self._logger.warning("Voice has local path but voices_dir is not configured; skipping file registration")

        if not self._is_from_kefu(message) and self._on_customer_voice:
            try:
                self._on_customer_voice(context.customer_name, context.channel, context.device_serial)
            except Exception as e:
                self._logger.warning(f"Customer voice callback failed: {e}")

        preview = content if len(content) <= 30 else f"{content[:30]}..."
        self._logger.info(
            f"Voice message saved: customer={context.customer_name}, "
            f"duration={voice_duration}, content={preview}, path={voice_path!s}"
        )

        return MessageProcessResult(
            added=True,
            message_type="voice",
            message_id=msg_record.id if msg_record else None,
            content=content,
            extra={"duration": voice_duration, "path": str(voice_path) if voice_path else None},
        )

    async def _save_voice_file(self, message: Any, customer_id: int, message_id: int) -> Path | None:
        """
        Copy inline-downloaded voice into customer directory, create voices row,
        and merge voice_file_path / voice_file_size into messages.extra_info (desktop API).
        """
        local_path = getattr(message, "voice_local_path", None)
        if not local_path or not self._voices_dir:
            return None

        try:
            source_path = Path(local_path)
            if not source_path.exists():
                self._logger.warning(f"Voice file not found: {source_path}")
                return None

            customer_dir = self._voices_dir / f"customer_{customer_id}"
            customer_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            extension = source_path.suffix or ".wav"
            filename = f"voice_{message_id}_{timestamp}{extension}"
            dest_path = customer_dir / filename

            shutil.copy2(source_path, dest_path)
            file_size = dest_path.stat().st_size

            duration_seconds = self._parse_voice_duration_seconds(getattr(message, "voice_duration", None))

            voice_rec = VoiceRecord(
                message_id=message_id,
                file_path=str(dest_path),
                file_name=filename,
                duration=getattr(message, "voice_duration", None),
                duration_seconds=duration_seconds,
                file_size=file_size,
            )
            self._repository.create_voice(voice_rec)

            self._repository.update_message_extra_info(
                message_id,
                {"voice_file_path": str(dest_path), "voice_file_size": file_size},
            )

            try:
                message.voice_local_path = str(dest_path)
            except Exception:
                pass
            return dest_path

        except Exception as e:
            self._logger.error(f"Failed to save voice file: {e}")
            return None

    @staticmethod
    def _parse_voice_duration_seconds(voice_duration: str | None) -> int | None:
        """Parse UI duration like 2\" or 5 into seconds."""
        if not voice_duration:
            return None
        try:
            duration_str = str(voice_duration).replace('"', "").replace("'", "").strip()
            return int(duration_str)
        except (ValueError, AttributeError):
            return None

    async def _get_voice_content(self, message: Any, context: MessageContext) -> tuple[str, bool]:
        """
        获取语音内容

        Args:
            message: 消息对象
            context: 消息上下文

        Returns:
            (内容字符串, 是否跳过)
        """
        # UI 解析器把转写放在 content（与 legacy sync_service 一致）
        raw_content = getattr(message, "content", None)
        if raw_content and str(raw_content).strip():
            return str(raw_content).strip(), False

        voice_caption = getattr(message, "voice_caption", None)
        if voice_caption:
            return voice_caption, False

        # 使用交互式处理器
        if self._interactive_handler:
            try:
                action, text = self._interactive_handler(message)

                if action == VoiceHandlerAction.SKIP:
                    return "", True

                elif action == VoiceHandlerAction.INPUT:
                    if text:
                        return text, False
                    return "[语音消息]", False

                elif action == VoiceHandlerAction.PLACEHOLDER:
                    return "[语音消息]", False

                elif action == VoiceHandlerAction.CAPTION:
                    # 用户选择显示字幕，可能需要重新提取
                    # 这里返回占位符，实际实现可能需要等待
                    return "[语音消息 - 待转写]", False

            except Exception as e:
                self._logger.warning(f"Interactive handler failed: {e}")

        # 默认使用占位符
        return "[语音消息]", False


def auto_placeholder_handler(message: Any) -> tuple[VoiceHandlerAction, str | None]:
    """
    自动占位符处理器

    非交互式处理，总是使用占位符。

    Args:
        message: 语音消息对象

    Returns:
        (PLACEHOLDER, None)
    """
    return VoiceHandlerAction.PLACEHOLDER, None


def interactive_voice_handler(message: Any) -> tuple[VoiceHandlerAction, str | None]:
    """
    交互式语音处理器

    提示用户选择如何处理语音消息。

    Args:
        message: 语音消息对象

    Returns:
        用户选择的 (动作, 可选文本)
    """
    print("\n" + "=" * 60)
    print("语音消息 (无字幕)")
    print("=" * 60)

    duration = getattr(message, "voice_duration", "未知")
    is_self = getattr(message, "is_self", False)

    print(f"时长: {duration}")
    print(f"发送者: {'客服' if is_self else '客户'}")
    print("-" * 60)
    print("选项:")
    print("  [c] 字幕 - 我将在屏幕上显示字幕")
    print("  [i] 输入 - 我将输入语音内容")
    print("  [p] 占位 - 使用 [语音消息] 占位符")
    print("  [s] 跳过 - 跳过此消息")
    print("-" * 60)

    while True:
        choice = input("你的选择 [c/i/p/s]: ").strip().lower()

        if choice == "c":
            print("请在设备上显示语音字幕...")
            print("完成后按回车...")
            input()
            return VoiceHandlerAction.CAPTION, None

        elif choice == "i":
            text = input("输入语音内容: ").strip()
            if text:
                return VoiceHandlerAction.INPUT, text
            print("内容不能为空，请重试或选择其他选项。")

        elif choice == "p":
            return VoiceHandlerAction.PLACEHOLDER, None

        elif choice == "s":
            return VoiceHandlerAction.SKIP, None

        else:
            print("无效选择，请输入 c, i, p 或 s。")
