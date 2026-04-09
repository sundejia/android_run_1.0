"""
消息处理模块 - 处理各类消息的统一入口

模块组成:
- processor: 消息处理器，分发消息到具体处理器
- handlers: 各类消息处理器 (文本、图片、语音、视频)
- image_sender: 图片发送服务（通过 Favorites 发送）
"""

from wecom_automation.services.message.image_sender import (
    ElementNotFoundError,
    ImageSender,
)
from wecom_automation.services.message.processor import (
    MessageProcessor,
    create_message_processor,
)

__all__ = [
    "MessageProcessor",
    "create_message_processor",
    "ImageSender",
    "ElementNotFoundError",
]
