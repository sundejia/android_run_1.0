"""
Settings 模块

统一的应用设置管理，使用 SQLite 数据库存储。

使用方式：
    from services.settings import get_settings_service, SettingCategory

    # 获取服务实例
    service = get_settings_service()

    # 获取所有设置
    all_settings = service.get_all_settings()

    # 获取特定类别
    ai_settings = service.get_ai_reply_settings()

    # 获取单个值
    timezone = service.get("general", "timezone")

    # 设置值
    service.set("general", "timezone", "Asia/Shanghai")

    # 获取扁平化设置（前端兼容）
    flat = service.get_flat_settings()
"""

from .models import (
    SettingCategory,
    ValueType,
    SettingRecord,
    GeneralSettings,
    SyncSettings,
    MirrorSettings,
    AIReplySettings,
    AIAnalysisSettings,
    VolcengineSettings,
    EmailSettings,
    SidecarSettings,
    RealtimeSettings,
    FollowupSettings,
    AllSettings,
)

from .repository import SettingsRepository

from .service import (
    SettingsService,
    get_settings_service,
    reset_settings_service,
)

from .defaults import (
    SETTING_DEFINITIONS,
    FRONTEND_KEY_MAPPING,
    BACKEND_TO_FRONTEND_MAPPING,
    get_default_value,
    get_value_type,
    get_all_defaults,
    get_category_defaults,
)

__all__ = [
    # Models
    "SettingCategory",
    "ValueType",
    "SettingRecord",
    "GeneralSettings",
    "SyncSettings",
    "MirrorSettings",
    "AIReplySettings",
    "AIAnalysisSettings",
    "VolcengineSettings",
    "EmailSettings",
    "SidecarSettings",
    "RealtimeSettings",
    "FollowupSettings",
    "AllSettings",
    # Repository
    "SettingsRepository",
    # Service
    "SettingsService",
    "get_settings_service",
    "reset_settings_service",
    # Defaults
    "SETTING_DEFINITIONS",
    "FRONTEND_KEY_MAPPING",
    "BACKEND_TO_FRONTEND_MAPPING",
    "get_default_value",
    "get_value_type",
    "get_all_defaults",
    "get_category_defaults",
]
