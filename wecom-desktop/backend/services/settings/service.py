"""
Settings Service - 业务逻辑层

提供设置的高级操作，包括类型化访问和跨类别操作。
"""

import logging
import os
import socket
from dataclasses import fields
from typing import Any, Dict, Optional
from uuid import uuid4

# Use centralized database path config
from wecom_automation.core.config import get_default_db_path

from .defaults import (
    FRONTEND_KEY_MAPPING,
    get_category_defaults,
)
from .models import (
    AIAnalysisSettings,
    AIReplySettings,
    AllSettings,
    DashboardSettings,
    EmailSettings,
    FollowupSettings,
    GeneralSettings,
    MirrorSettings,
    RealtimeSettings,
    SettingCategory,
    SettingRecord,
    SidecarSettings,
    SyncSettings,
    VolcengineSettings,
)
from .repository import SettingsRepository

# Prompt style presets (same as frontend)
PROMPT_STYLE_PRESETS = [
    {"key": "none", "name": "无预设", "description": "不使用预设风格", "prompt": ""},
    {
        "key": "default",
        "name": "默认风格",
        "description": "礼貌大方，有条理",
        "prompt": """语气礼貌大方，使用"您"称呼用户。
回答要直接且有条理，避免冗长。
始终保持耐心，无论用户的情绪如何。""",
    },
    {
        "key": "lively",
        "name": "活泼风格",
        "description": "热情活泼，像朋友一样",
        "prompt": """语气要超级热情，多使用"哈喽"、"亲亲"、"么么哒"或"好哒"等词汇。
适当使用表情符号（如 🌈, 🚀, 😊）来让对话更生动。
把用户当成朋友，除了解决问题，也要给用户提供情绪价值。
遇到用户抱怨时，要用超温柔的方式安抚对方，比如："抱抱亲亲，别生气哦，小趣马上帮你想办法！""",
    },
    {
        "key": "professional",
        "name": "专业风格",
        "description": "正式商务用语",
        "prompt": """使用极其正式的商务用语，确保表达的准确性。
回答问题时，请适度采用"第一步、第二步、第三步"的结构化方式。
引用任何数据或政策时需谨慎核实，确保专业度。
保持绝对客观中立，即使在拒绝用户要求时，也要解释清楚基于的政策条款。""",
    },
    {
        "key": "minimal",
        "name": "极简/高效风格",
        "description": "直接高效，不寒暄",
        "prompt": """拒绝寒暄。直接识别用户意图并给出答案。
使用精炼的短句，不要使用任何修辞手法。
如果问题需要多个步骤，仅提供最直接的解决方案链接或指令。""",
    },
]


class SettingsService:
    """设置服务类"""

    def __init__(self, db_path: str, logger: Optional[logging.Logger] = None):
        self._repository = SettingsRepository(db_path, logger)
        self._logger = logger or logging.getLogger(__name__)

        # 确保初始化默认值（每次启动都检查并添加缺失的键值）
        # initialize_defaults 只会添加不存在的键值，不会覆盖现有值
        self._repository.initialize_defaults()
        self._repository.sync_definition_metadata()
        self.ensure_device_identity()

    # ============================================================================
    # Generic Operations
    # ============================================================================

    def get(self, category: str, key: str, default: Any = None) -> Any:
        """获取单个设置值"""
        return self._repository.get_value(category, key, default)

    def set(self, category: str, key: str, value: Any, changed_by: str = "api") -> SettingRecord:
        """设置单个值"""
        return self._repository.set(category, key, value, changed_by)

    def get_category(self, category: str) -> Dict[str, Any]:
        """获取类别下的所有设置"""
        # 先获取默认值，再覆盖数据库中的值
        defaults = get_category_defaults(category)
        db_values = self._repository.get_category(category)
        return {**defaults, **db_values}

    def set_category(self, category: str, settings: Dict[str, Any], changed_by: str = "api") -> Dict[str, Any]:
        """批量设置类别下的值"""
        return self._repository.set_many(category, settings, changed_by)

    def reset_category(self, category: str, changed_by: str = "reset") -> Dict[str, Any]:
        """重置类别为默认值"""
        return self._repository.reset_category(category, changed_by)

    # ============================================================================
    # Typed Accessors
    # ============================================================================

    def get_general_settings(self) -> GeneralSettings:
        """获取通用设置"""
        data = dict(self.get_category(SettingCategory.GENERAL.value))
        data["hostname"] = self.get_effective_hostname()
        data["device_id"] = self.get_device_id()
        data["person_name"] = self.get_effective_person_name()

        # 兼容旧数据：忽略模型中不存在的字段，避免历史配置导致初始化失败
        allowed_fields = {f.name for f in fields(GeneralSettings)}
        filtered = {k: v for k, v in data.items() if k in allowed_fields}
        return GeneralSettings(**filtered)

    def get_sync_settings(self) -> SyncSettings:
        """获取同步设置"""
        data = self.get_category(SettingCategory.SYNC.value)
        return SyncSettings(**data)

    def get_mirror_settings(self) -> MirrorSettings:
        """获取镜像设置"""
        data = self.get_category(SettingCategory.MIRROR.value)
        return MirrorSettings(**data)

    def get_ai_reply_settings(self) -> AIReplySettings:
        """获取 AI 回复设置"""
        data = self.get_category(SettingCategory.AI_REPLY.value)
        return AIReplySettings(**data)

    def get_ai_analysis_settings(self) -> AIAnalysisSettings:
        """获取 AI 分析设置"""
        data = self.get_category(SettingCategory.AI_ANALYSIS.value)
        return AIAnalysisSettings(**data)

    def get_volcengine_settings(self) -> VolcengineSettings:
        """获取 Volcengine 设置"""
        data = self.get_category(SettingCategory.VOLCENGINE.value)
        return VolcengineSettings(**data)

    def get_email_settings(self) -> EmailSettings:
        """获取邮件设置"""
        data = self.get_category(SettingCategory.EMAIL.value)
        return EmailSettings(**data)

    def get_sidecar_settings(self) -> SidecarSettings:
        """获取 Sidecar 设置"""
        data = self.get_category(SettingCategory.SIDECAR.value)
        return SidecarSettings(**data)

    def get_realtime_settings(self) -> RealtimeSettings:
        """获取实时回复设置"""
        data = self.get_category(SettingCategory.REALTIME.value)
        return RealtimeSettings(**data)

    def get_followup_settings(self) -> FollowupSettings:
        """获取补刀功能设置"""
        data = dict(self.get_category(SettingCategory.FOLLOWUP.value))

        # 数据清洗：确保布尔字段的值有效
        bool_fields = [
            "followup_enabled",
            "use_ai_reply",
            "enable_operating_hours",
        ]
        for field in bool_fields:
            if field in data:
                val = data[field]
                # 处理空字符串、None 等无效值
                if val == "" or val is None:
                    data[field] = False
                elif isinstance(val, str):
                    data[field] = val.lower() in ("true", "1", "yes")
                else:
                    data[field] = bool(val)

        # 仅保留新架构支持的字段，避免未知字段导致初始化失败
        allowed_fields = {f.name for f in fields(FollowupSettings)}
        filtered = {k: v for k, v in data.items() if k in allowed_fields}

        return FollowupSettings(**filtered)

    def get_dashboard_settings(self) -> DashboardSettings:
        """获取监控面板设置"""
        data = self.get_category(SettingCategory.DASHBOARD.value)
        return DashboardSettings(**data)

    def get_all_settings(self) -> AllSettings:
        """获取所有设置"""
        return AllSettings(
            general=self.get_general_settings(),
            sync=self.get_sync_settings(),
            mirror=self.get_mirror_settings(),
            ai_reply=self.get_ai_reply_settings(),
            ai_analysis=self.get_ai_analysis_settings(),
            volcengine=self.get_volcengine_settings(),
            email=self.get_email_settings(),
            sidecar=self.get_sidecar_settings(),
            realtime=self.get_realtime_settings(),
            followup=self.get_followup_settings(),
            dashboard=self.get_dashboard_settings(),
        )

    # ============================================================================
    # Frontend Compatibility
    # ============================================================================

    def get_flat_settings(self) -> Dict[str, Any]:
        """获取扁平化的设置（前端兼容格式）"""
        return self.get_all_settings().to_flat_dict()

    def update_from_flat(self, flat_settings: Dict[str, Any], changed_by: str = "frontend") -> None:
        """从扁平化设置更新（前端兼容）"""
        for frontend_key, value in flat_settings.items():
            if frontend_key in FRONTEND_KEY_MAPPING:
                category, key = FRONTEND_KEY_MAPPING[frontend_key]
                self._repository.set(category, key, value, changed_by)
            else:
                self._logger.warning(f"Unknown frontend key: {frontend_key}")

    def update_from_frontend_partial(self, partial: Dict[str, Any], changed_by: str = "frontend") -> None:
        """从前端部分更新（只更新提供的字段）"""
        for frontend_key, value in partial.items():
            if value is None:
                continue  # 跳过 None 值
            if frontend_key in FRONTEND_KEY_MAPPING:
                category, key = FRONTEND_KEY_MAPPING[frontend_key]
                self._repository.set(category, key, value, changed_by)

    @staticmethod
    def sanitize_hostname(hostname: str | None) -> str:
        raw = (hostname or "").strip()
        if not raw:
            return ""
        return raw.replace("/", "-").replace("\\", "-").replace(" ", "_")

    @staticmethod
    def _detect_system_hostname() -> str:
        candidates = [
            os.environ.get("COMPUTERNAME"),
            os.environ.get("HOSTNAME"),
            socket.gethostname(),
        ]
        for candidate in candidates:
            safe = SettingsService.sanitize_hostname(candidate)
            if safe and safe.lower() != "default":
                return safe
        return "default"

    def default_hostname(self) -> str:
        return self._detect_system_hostname()

    def normalize_hostname_input(self, hostname: str | None) -> str:
        safe = self.sanitize_hostname(hostname)
        return safe or self.default_hostname()

    @staticmethod
    def sanitize_person_name(person_name: str | None) -> str:
        raw = " ".join((person_name or "").strip().split())
        if not raw:
            return ""
        return raw.replace("/", "-").replace("\\", "-")

    def normalize_person_name_input(self, person_name: str | None) -> str:
        safe = self.sanitize_person_name(person_name)
        return safe or self.get_effective_hostname()

    def get_device_id(self) -> str:
        value = self._repository.get_value(
            SettingCategory.GENERAL.value, "device_id", ""
        )
        if isinstance(value, str) and value.strip():
            return value.strip()
        return self._ensure_device_id()

    def _ensure_device_id(self) -> str:
        device_id = str(uuid4())
        self._repository.set(
            SettingCategory.GENERAL.value,
            "device_id",
            device_id,
            changed_by="identity-bootstrap",
        )
        return device_id

    def get_effective_hostname(self) -> str:
        value = self._repository.get_value(
            SettingCategory.GENERAL.value, "hostname", ""
        )
        safe = self.sanitize_hostname(value)
        if safe and safe.lower() != "default":
            return safe
        return self._ensure_hostname()

    def get_effective_person_name(self) -> str:
        value = self._repository.get_value(
            SettingCategory.GENERAL.value, "person_name", ""
        )
        safe = self.sanitize_person_name(value)
        if safe:
            return safe
        return self.get_effective_hostname()

    def _ensure_hostname(self) -> str:
        hostname = self.default_hostname()
        self._repository.set(
            SettingCategory.GENERAL.value,
            "hostname",
            hostname,
            changed_by="identity-bootstrap",
        )
        return hostname

    def ensure_device_identity(self) -> None:
        self.get_device_id()
        self.get_effective_hostname()

    # ============================================================================
    # Convenience Methods
    # ============================================================================

    def get_timezone(self) -> str:
        """获取时区"""
        return self.get(SettingCategory.GENERAL.value, "timezone", "Asia/Shanghai")

    def set_timezone(self, timezone: str, changed_by: str = "api") -> None:
        """设置时区"""
        self.set(SettingCategory.GENERAL.value, "timezone", timezone, changed_by)

    def get_system_prompt(self) -> str:
        """获取系统提示词"""
        return self.get(SettingCategory.AI_REPLY.value, "system_prompt", "")

    def set_system_prompt(self, prompt: str, changed_by: str = "api") -> None:
        """设置系统提示词"""
        self.set(SettingCategory.AI_REPLY.value, "system_prompt", prompt, changed_by)

    def get_combined_system_prompt(self) -> str:
        """获取组合后的系统提示词（自定义提示词 + 预设风格）"""
        # 获取基础设置
        custom_prompt = self.get_system_prompt()
        preset_key = self.get(SettingCategory.AI_REPLY.value, "prompt_style_key", "none")

        # 查找预设
        preset = next((p for p in PROMPT_STYLE_PRESETS if p["key"] == preset_key), None)
        style_prompt = preset["prompt"] if preset else ""

        # 组合提示词：自定义提示词优先，然后是预设风格
        base_prompt = ""
        if custom_prompt and style_prompt:
            base_prompt = f"{custom_prompt}\n\n{style_prompt}"
        else:
            base_prompt = custom_prompt or style_prompt

        return base_prompt

    def is_ai_reply_enabled(self) -> bool:
        """检查是否启用 AI 回复"""
        return self.get(SettingCategory.AI_REPLY.value, "use_ai_reply", False)

    def is_sidecar_enabled(self) -> bool:
        """检查是否启用 Sidecar"""
        return self.get(SettingCategory.SIDECAR.value, "send_via_sidecar", False)

    def is_email_enabled(self) -> bool:
        """检查是否启用邮件通知"""
        return self.get(SettingCategory.EMAIL.value, "enabled", False)

    def get_image_server_ip(self) -> str:
        """获取图片审核服务器地址（空字符串表示未配置）"""
        return self.get(SettingCategory.GENERAL.value, "image_server_ip", "")

    def is_image_upload_enabled(self) -> bool:
        """检查是否启用图片自动上传到审核平台"""
        return bool(self.get(SettingCategory.GENERAL.value, "image_upload_enabled", True))

    def get_image_review_timeout_seconds(self) -> int:
        """Get image review wait timeout in seconds."""
        value = self.get(SettingCategory.GENERAL.value, "image_review_timeout_seconds", 40)
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 40

    def is_low_spec_mode(self) -> bool:
        """Whether low-spec performance mode is enabled."""
        return bool(self.get(SettingCategory.GENERAL.value, "low_spec_mode", False))

    def get_max_concurrent_sync_devices(self) -> int:
        """Maximum sync processes allowed to run concurrently."""
        value = self.get(SettingCategory.SYNC.value, "max_concurrent_devices", 3)
        try:
            parsed = max(1, int(value))
        except (TypeError, ValueError):
            parsed = 3
        if self.is_low_spec_mode():
            return 1
        return parsed

    def get_max_concurrent_realtime_devices(self) -> int:
        """Maximum realtime_reply processes allowed to run concurrently.

        Realtime reply processes share the single ADB host server and (when
        running on the same machine) the local sidecar. Capping concurrency
        avoids the "all devices launch WeCom + scroll-to-top in parallel"
        thundering-herd that briefly starves every other device.
        """
        value = self.get(SettingCategory.REALTIME.value, "max_concurrent_devices", 4)
        try:
            parsed = max(1, int(value))
        except (TypeError, ValueError):
            parsed = 4
        if self.is_low_spec_mode():
            return 1
        return parsed

    def get_realtime_stagger_delay_seconds(self) -> int:
        """Seconds to wait between successive realtime_reply spawns."""
        value = self.get(SettingCategory.REALTIME.value, "stagger_delay_seconds", 10)
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 10

    def get_effective_sidecar_poll_interval(self) -> int:
        """Effective sidecar poll interval with low-spec safeguards.

        Default lowered to 2s so multi-device sidecars discover newly READY
        messages quickly instead of clustering them onto a 10s polling tick
        (which used to make several devices appear to send replies in lockstep).
        """
        value = self.get(SettingCategory.SIDECAR.value, "poll_interval", 2)
        try:
            parsed = max(0, int(value))
        except (TypeError, ValueError):
            parsed = 2
        if parsed == 0:
            return 0
        if self.is_low_spec_mode():
            return max(5, parsed)
        return parsed

    def get_effective_realtime_scan_interval(self) -> int:
        """Effective realtime scan interval with low-spec safeguards."""
        value = self.get(SettingCategory.REALTIME.value, "scan_interval", 60)
        try:
            parsed = max(10, int(value))
        except (TypeError, ValueError):
            parsed = 60
        if self.is_low_spec_mode():
            return max(120, parsed)
        return parsed

    def get_effective_sidecar_max_panels(self) -> int:
        """Effective sidecar panel count with low-spec safeguards."""
        value = self.get(SettingCategory.SIDECAR.value, "max_panels", 3)
        try:
            parsed = max(1, int(value))
        except (TypeError, ValueError):
            parsed = 3
        if self.is_low_spec_mode():
            return 1
        return parsed

    def get_performance_profile(self) -> Dict[str, Any]:
        """Resolved performance settings used by the runtime."""
        low_spec = self.is_low_spec_mode()
        mirror = self.get_mirror_settings()
        image_upload_enabled = self.is_image_upload_enabled()
        return {
            "lowSpecMode": low_spec,
            "effective": {
                "maxConcurrentSyncDevices": self.get_max_concurrent_sync_devices(),
                "sidecarPollInterval": self.get_effective_sidecar_poll_interval(),
                "scanInterval": self.get_effective_realtime_scan_interval(),
                "sidecarMaxPanels": self.get_effective_sidecar_max_panels(),
                "mirrorMaxFps": min(mirror.max_fps, 15) if low_spec else mirror.max_fps,
                "mirrorBitRate": min(mirror.bit_rate, 4) if low_spec else mirror.bit_rate,
                "imageReviewInlineWaitEnabled": image_upload_enabled and not low_spec,
            },
        }


# ============================================================================
# Singleton Instance
# ============================================================================

_settings_service: Optional[SettingsService] = None


def get_settings_service(db_path: Optional[str] = None) -> SettingsService:
    """获取设置服务单例"""
    global _settings_service

    if _settings_service is None:
        if db_path is None:
            # Use centralized database path config
            db_path = str(get_default_db_path())
        _settings_service = SettingsService(db_path)

    return _settings_service


def reset_settings_service() -> None:
    """重置设置服务（用于测试）"""
    global _settings_service
    _settings_service = None
