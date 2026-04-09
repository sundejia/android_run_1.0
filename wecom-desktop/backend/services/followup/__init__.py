"""
Follow-up 服务模块

架构组成:
- models: 数据模型
- settings: 补刀功能设置管理
- repository: 数据库操作（对话记录）
- attempts_repository: 补刀尝试记录仓库
- response_detector: 红点检测和AI回复（实时回复核心逻辑）
- service: 数据库服务
- executor: 补刀执行器（搜索联系人并发送消息）
- followup_manager: 补刀管理器（整合设置和执行器）
- queue_manager: 补刀队列管理器（管理补刀队列状态）

模块职责分离:
- 实时回复 (Realtime Reply): 扫描红点用户并回复，使用 realtime_reply_process.py
- 补刀功能 (Followup): 主动搜索联系人发送消息，使用 FollowupExecutor + FollowupQueueManager
"""

from .attempts_repository import (
    AttemptStatus,
    FollowupAttempt,
    FollowupAttemptsRepository,
)
from .executor import (
    BatchFollowupResult,
    FollowupExecutor,
    FollowupResult,
    FollowupStatus,
)
from .followup_manager import (
    FollowupManager,
    clear_all_followup_managers,
    clear_followup_manager,
    get_followup_manager,
)
from .models import ScanResult
from .queue_manager import (
    ConversationInfo,
    FollowupQueueManager,
    clear_followup_queue_manager,
    get_followup_queue_manager,
)
from .repository import ConversationRepository
from .response_detector import ResponseDetector
from .service import FollowUpService, get_followup_service
from .settings import FollowUpSettings, SettingsManager

__all__ = [
    # 数据模型
    "ScanResult",
    "FollowupAttempt",
    "AttemptStatus",
    "ConversationInfo",
    # 设置
    "FollowUpSettings",
    "SettingsManager",
    # 核心组件
    "ConversationRepository",
    "ResponseDetector",
    "FollowUpService",
    # 补刀执行器
    "FollowupExecutor",
    "FollowupResult",
    "BatchFollowupResult",
    "FollowupStatus",
    # 补刀管理器
    "FollowupManager",
    "get_followup_manager",
    "clear_followup_manager",
    "clear_all_followup_managers",
    # 补刀队列管理器
    "FollowupQueueManager",
    "FollowupAttemptsRepository",
    "get_followup_queue_manager",
    "clear_followup_queue_manager",
    # 工厂方法
    "get_followup_service",
]
