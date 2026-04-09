"""
用户管理模块 - 用户相关功能

模块组成:
- unread_detector: 未读消息检测器
- avatar: 头像管理器

Note: 黑名单功能已迁移到数据库，见 services/blacklist_service.py
"""

from wecom_automation.services.user.avatar import AvatarManager
from wecom_automation.services.user.unread_detector import UnreadUserExtractor, UnreadUserInfo

__all__ = [
    "UnreadUserExtractor",
    "UnreadUserInfo",
    "AvatarManager",
]
