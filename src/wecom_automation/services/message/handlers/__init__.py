"""
消息处理器集合

包含:
- BaseMessageHandler: 消息处理器基类
- TextMessageHandler: 文本消息处理器
- ImageMessageHandler: 图片消息处理器
- StickerMessageHandler: 表情包消息处理器
- VoiceMessageHandler: 语音消息处理器
- VideoMessageHandler: 视频消息处理器
"""

from wecom_automation.services.message.handlers.base import BaseMessageHandler
from wecom_automation.services.message.handlers.image import ImageMessageHandler
from wecom_automation.services.message.handlers.sticker import StickerMessageHandler
from wecom_automation.services.message.handlers.text import TextMessageHandler
from wecom_automation.services.message.handlers.video import VideoMessageHandler
from wecom_automation.services.message.handlers.voice import (
    VoiceMessageHandler,
    auto_placeholder_handler,
    interactive_voice_handler,
)

__all__ = [
    "BaseMessageHandler",
    "TextMessageHandler",
    "ImageMessageHandler",
    "StickerMessageHandler",
    "VoiceMessageHandler",
    "VideoMessageHandler",
    "auto_placeholder_handler",
    "interactive_voice_handler",
]
