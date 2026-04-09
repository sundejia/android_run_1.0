"""
核心接口定义 - 依赖倒置原则

本模块定义了同步系统的核心抽象接口和数据传输对象(DTO)，
所有具体实现都应依赖这些抽象而非具体类。

设计原则:
- 单一职责原则 (SRP): 每个接口只定义一种能力
- 接口隔离原则 (ISP): 接口尽量小而专注
- 依赖倒置原则 (DIP): 高层模块依赖抽象
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

# =============================================================================
# 枚举类型
# =============================================================================


class VoiceHandlerAction(str, Enum):
    """语音消息处理动作"""

    CAPTION = "caption"  # 用户将在屏幕上显示字幕
    INPUT = "input"  # 用户将输入语音内容
    PLACEHOLDER = "placeholder"  # 使用占位符文本
    SKIP = "skip"  # 跳过此消息


# =============================================================================
# 数据传输对象 (DTO)
# =============================================================================


@dataclass
class SyncOptions:
    """
    同步选项配置

    Attributes:
        send_test_messages: 是否发送测试消息
        response_wait_seconds: 等待响应的秒数
        prioritize_unread: 是否优先同步未读消息用户
        unread_only: 是否仅同步有未读消息的用户
        resume: 是否从断点续传
        timing_multiplier: 延迟时间倍数 (>1 更慢, <1 更快)
        interactive_wait_timeout: 交互式等待超时时间（秒）
        max_interaction_rounds: 单个客户最大交互轮次
        dynamic_unread_detection: 是否启用动态未读检测
    """

    send_test_messages: bool = True
    response_wait_seconds: float = 5.0
    prioritize_unread: bool = False
    unread_only: bool = False
    resume: bool = False
    timing_multiplier: float = 1.0
    interactive_wait_timeout: float = 40.0
    max_interaction_rounds: int = 10
    dynamic_unread_detection: bool = True


@dataclass
class SyncProgress:
    """
    同步进度

    Attributes:
        total_customers: 总客户数
        synced_customers: 已同步客户数
        current_customer: 当前正在同步的客户名
        messages_added: 新增消息数
        messages_skipped: 跳过的重复消息数
        errors: 错误列表
    """

    total_customers: int = 0
    synced_customers: int = 0
    current_customer: str | None = None
    messages_added: int = 0
    messages_skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def percentage(self) -> float:
        """计算完成百分比"""
        if self.total_customers == 0:
            return 0.0
        return (self.synced_customers / self.total_customers) * 100

    @property
    def is_complete(self) -> bool:
        """是否已完成"""
        return self.synced_customers >= self.total_customers


@dataclass
class SyncResult:
    """
    同步结果

    Attributes:
        success: 是否成功
        start_time: 开始时间
        end_time: 结束时间
        customers_synced: 已同步客户数
        messages_added: 新增消息数
        messages_skipped: 跳过消息数
        images_saved: 保存的图片数
        videos_saved: 保存的视频数
        voice_messages: 语音消息数
        errors: 错误列表
    """

    success: bool
    start_time: datetime
    end_time: datetime
    customers_synced: int = 0
    messages_added: int = 0
    messages_skipped: int = 0
    images_saved: int = 0
    videos_saved: int = 0
    voice_messages: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        """计算耗时秒数"""
        return (self.end_time - self.start_time).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_seconds": self.duration_seconds,
            "customers_synced": self.customers_synced,
            "messages_added": self.messages_added,
            "messages_skipped": self.messages_skipped,
            "images_saved": self.images_saved,
            "videos_saved": self.videos_saved,
            "voice_messages": self.voice_messages,
            "errors": self.errors,
        }


@dataclass
class CustomerSyncResult:
    """
    单客户同步结果

    Attributes:
        success: 是否成功
        skipped: 是否被用户手动跳过
        messages_count: 消息总数
        messages_added: 新增消息数
        messages_skipped: 跳过消息数
        images_saved: 保存的图片数
        videos_saved: 保存的视频数
        voice_count: 语音消息数
        error: 错误信息
        user_deleted: 用户是否已删除/拉黑
    """

    success: bool = True
    skipped: bool = False
    messages_count: int = 0
    messages_added: int = 0
    messages_skipped: int = 0
    images_saved: int = 0
    videos_saved: int = 0
    voice_count: int = 0
    error: str | None = None
    user_deleted: bool = False
    replies_sent: int = 0


@dataclass
class MessageContext:
    """
    消息处理上下文

    Attributes:
        customer_id: 客户数据库ID
        customer_name: 客户名称
        channel: 渠道 (如 @WeChat)
        kefu_name: 客服名称
        device_serial: 设备序列号
    """

    customer_id: int
    customer_name: str
    channel: str | None
    kefu_name: str
    device_serial: str


@dataclass
class MessageProcessResult:
    """
    消息处理结果

    Attributes:
        added: 是否新增 (False表示重复)
        message_type: 消息类型
        message_id: 消息数据库ID
        content: 消息内容
        extra: 额外信息
    """

    added: bool
    message_type: str
    message_id: int | None = None
    content: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# 抽象接口
# =============================================================================


class IMessageHandler(ABC):
    """
    消息处理器接口

    实现责任链模式，每种消息类型一个处理器。
    """

    @abstractmethod
    async def can_handle(self, message: Any) -> bool:
        """
        判断是否能处理该消息类型

        Args:
            message: 原始消息对象

        Returns:
            True如果能处理，否则False
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


class ICheckpointManager(ABC):
    """
    断点管理器接口

    提供同步断点的保存和恢复能力。
    """

    @abstractmethod
    def load(self) -> dict[str, Any] | None:
        """
        加载检查点

        Returns:
            检查点数据，不存在则返回None
        """
        pass

    @abstractmethod
    def save(
        self,
        synced_customers: list[str],
        stats: dict[str, int],
        kefu_name: str,
        device_serial: str,
    ) -> bool:
        """
        保存检查点

        Args:
            synced_customers: 已同步的客户列表
            stats: 统计数据
            kefu_name: 客服名称
            device_serial: 设备序列号

        Returns:
            True如果保存成功
        """
        pass

    @abstractmethod
    def clear(self) -> bool:
        """
        清除检查点

        Returns:
            True如果清除成功
        """
        pass

    @abstractmethod
    def exists(self) -> bool:
        """
        检查点是否存在

        Returns:
            True如果存在
        """
        pass


class INotificationService(ABC):
    """
    通知服务接口

    提供各类通知能力。
    """

    @abstractmethod
    async def send(self, subject: str, content: str, **kwargs) -> bool:
        """
        发送通知

        Args:
            subject: 通知主题
            content: 通知内容
            **kwargs: 额外参数

        Returns:
            True如果发送成功
        """
        pass


class IAIReplyService(ABC):
    """
    AI回复服务接口

    提供AI生成回复的能力。
    """

    @abstractmethod
    async def get_reply(
        self, message: str, context: MessageContext, history: list[dict[str, Any]] | None = None
    ) -> str | None:
        """
        获取AI回复

        Args:
            message: 用户消息
            context: 消息上下文
            history: 历史消息列表

        Returns:
            AI生成的回复，失败返回None
        """
        pass

    @abstractmethod
    def is_human_request(self, reply: str) -> bool:
        """
        检查AI回复是否表示用户要求转人工

        Args:
            reply: AI的回复

        Returns:
            True如果用户要求转人工
        """
        pass


class ISyncProgressListener(ABC):
    """
    同步进度监听器接口

    用于接收同步进度更新的回调。
    """

    @abstractmethod
    def on_progress(self, progress: SyncProgress) -> None:
        """
        进度更新回调

        Args:
            progress: 当前进度
        """
        pass

    @abstractmethod
    def on_customer_start(self, customer_name: str) -> None:
        """
        开始同步客户回调

        Args:
            customer_name: 客户名称
        """
        pass

    @abstractmethod
    def on_customer_complete(self, customer_name: str, result: CustomerSyncResult) -> None:
        """
        完成同步客户回调

        Args:
            customer_name: 客户名称
            result: 同步结果
        """
        pass

    @abstractmethod
    def on_error(self, error: str, customer_name: str | None = None) -> None:
        """
        错误回调

        Args:
            error: 错误信息
            customer_name: 相关客户名称 (可选)
        """
        pass


# =============================================================================
# 类型别名
# =============================================================================

# 语音处理回调类型
VoiceHandlerCallback = Callable[[Any], tuple[VoiceHandlerAction, str | None]]

# 客户语音回调类型 (customer_name, channel, serial)
CustomerVoiceCallback = Callable[[str, str | None, str], None]
