"""
消息处理器基类

提供消息处理器的基础实现和通用方法。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from wecom_automation.core.interfaces import IMessageHandler, MessageContext, MessageProcessResult
from wecom_automation.database.repository import ConversationRepository
from wecom_automation.services.timestamp_parser import TimestampParser


class BaseMessageHandler(IMessageHandler, ABC):
    """
    消息处理器基类

    提供:
    - 仓库访问
    - 日志记录
    - 通用工具方法
    - 时间戳解析

    子类需要实现:
    - can_handle(): 判断是否能处理该消息
    - process(): 处理消息
    """

    # 共享的时间戳解析器
    _timestamp_parser: TimestampParser | None = None

    def __init__(self, repository: ConversationRepository, logger: logging.Logger | None = None):
        """
        初始化基类

        Args:
            repository: 数据库仓库
            logger: 日志记录器
        """
        self._repository = repository
        self._logger = logger or logging.getLogger(self.__class__.__name__)

        # 初始化共享的时间戳解析器
        if BaseMessageHandler._timestamp_parser is None:
            BaseMessageHandler._timestamp_parser = TimestampParser()
            BaseMessageHandler._timestamp_parser.set_reference_time()

    @property
    def repository(self) -> ConversationRepository:
        """获取仓库实例"""
        return self._repository

    @property
    def logger(self) -> logging.Logger:
        """获取日志记录器"""
        return self._logger

    @abstractmethod
    async def can_handle(self, message: Any) -> bool:
        """
        判断是否能处理该消息类型

        Args:
            message: 原始消息对象

        Returns:
            True如果能处理
        """
        pass

    @abstractmethod
    async def process(self, message: Any, context: MessageContext) -> MessageProcessResult:
        """
        处理消息

        Args:
            message: 原始消息对象
            context: 消息上下文

        Returns:
            处理结果
        """
        pass

    def _get_message_type(self, message: Any) -> str:
        """
        获取消息类型

        Args:
            message: 消息对象

        Returns:
            消息类型字符串
        """
        # 尝试从对象获取类型
        if hasattr(message, "msg_type"):
            return message.msg_type
        if hasattr(message, "message_type"):
            return message.message_type
        if hasattr(message, "type"):
            return message.type

        return "unknown"

    def _get_content(self, message: Any) -> str:
        """
        获取消息内容

        Args:
            message: 消息对象

        Returns:
            消息内容字符串
        """
        if hasattr(message, "content"):
            return str(message.content or "")
        if hasattr(message, "text"):
            return str(message.text or "")

        return ""

    def _is_from_kefu(self, message: Any) -> bool:
        """
        判断消息是否来自客服

        Args:
            message: 消息对象

        Returns:
            True如果来自客服
        """
        if hasattr(message, "is_self"):
            return message.is_self
        if hasattr(message, "is_from_kefu"):
            return message.is_from_kefu

        return False

    def _get_timestamp(self, message: Any) -> str | None:
        """
        获取消息时间戳（原始字符串）

        Args:
            message: 消息对象

        Returns:
            时间戳字符串
        """
        if hasattr(message, "timestamp"):
            return message.timestamp
        if hasattr(message, "timestamp_raw"):
            return message.timestamp_raw
        if hasattr(message, "time"):
            return message.time

        return None

    def _parse_timestamp(self, timestamp_raw: str | None) -> tuple[str | None, datetime | None]:
        """
        解析时间戳字符串为可比较的 datetime

        支持四种格式:
        1. 年/月/日 时:分 (如 "2024/12/25 14:30")
        2. 星期+时分 (如 "星期一 14:30" 或 "周一 下午 2:30")
        3. yesterday 时分 (如 "昨天 14:30")
        4. 直接时分 (如 "14:30" - 表示今天)

        Args:
            timestamp_raw: 原始时间戳字符串

        Returns:
            元组 (原始时间戳, 解析后的datetime)
        """
        if not timestamp_raw:
            return None, None

        # 确保解析器存在并更新参考时间
        if BaseMessageHandler._timestamp_parser is None:
            BaseMessageHandler._timestamp_parser = TimestampParser()

        # 每次解析前刷新参考时间（确保 today/yesterday 计算准确）
        BaseMessageHandler._timestamp_parser.set_reference_time()

        parsed = BaseMessageHandler._timestamp_parser.parse(timestamp_raw)
        return timestamp_raw, parsed

    def _get_parsed_timestamp(self, message: Any) -> tuple[str | None, datetime | None]:
        """
        获取并解析消息时间戳

        结合 _get_timestamp 和 _parse_timestamp 的便捷方法

        Args:
            message: 消息对象

        Returns:
            元组 (原始时间戳, 解析后的datetime)
        """
        timestamp_raw = self._get_timestamp(message)
        return self._parse_timestamp(timestamp_raw)
