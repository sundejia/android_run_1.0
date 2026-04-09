"""
Settings 数据模型定义

提供统一的设置数据结构，支持多种值类型和分类管理。
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class SettingCategory(str, Enum):
    """设置类别枚举"""

    GENERAL = "general"
    SYNC = "sync"
    MIRROR = "mirror"
    AI_REPLY = "ai_reply"
    AI_ANALYSIS = "ai_analysis"
    VOLCENGINE = "volcengine"
    EMAIL = "email"
    SIDECAR = "sidecar"
    REALTIME = "realtime"
    FOLLOWUP = "followup"


class ValueType(str, Enum):
    """值类型枚举"""

    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOLEAN = "boolean"
    JSON = "json"


@dataclass
class SettingRecord:
    """单个设置记录"""

    category: str
    key: str
    value_type: str
    value: Any
    id: Optional[int] = None
    description: Optional[str] = None
    is_sensitive: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "category": self.category,
            "key": self.key,
            "value_type": self.value_type,
            "value": self.value,
            "description": self.description,
            "is_sensitive": self.is_sensitive,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_row(cls, row: Any) -> "SettingRecord":
        """从数据库行创建实例"""
        value_type = row["value_type"]

        # 根据类型获取值
        if value_type == ValueType.STRING.value:
            value = row["value_string"]
        elif value_type == ValueType.INT.value:
            value = row["value_int"]
        elif value_type == ValueType.FLOAT.value:
            value = row["value_float"]
        elif value_type == ValueType.BOOLEAN.value:
            value = bool(row["value_bool"])
        elif value_type == ValueType.JSON.value:
            value = json.loads(row["value_json"]) if row["value_json"] else None
        else:
            value = row["value_string"]

        # Helper to safely get optional fields from row
        def safe_get(key: str, default: Any = None) -> Any:
            try:
                return row[key]
            except (KeyError, IndexError):
                return default

        return cls(
            id=row["id"],
            category=row["category"],
            key=row["key"],
            value_type=value_type,
            value=value,
            description=safe_get("description"),
            is_sensitive=bool(safe_get("is_sensitive", 0)),
            created_at=datetime.fromisoformat(row["created_at"]) if safe_get("created_at") else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if safe_get("updated_at") else None,
        )


# ============================================================================
# 各类别的设置数据类
# ============================================================================


@dataclass
class GeneralSettings:
    """通用设置"""

    hostname: str = ""
    device_id: str = ""
    person_name: str = ""
    timezone: str = "Asia/Shanghai"
    backend_url: str = "http://localhost:8765"
    auto_refresh_interval: int = 5000
    log_max_entries: int = 1000
    log_upload_enabled: bool = False
    log_upload_time: str = "02:00"
    log_upload_url: str = ""
    log_upload_token: str = ""
    image_server_ip: str = ""
    image_upload_enabled: bool = True
    image_review_timeout_seconds: int = 40
    low_spec_mode: bool = False


@dataclass
class SyncSettings:
    """同步设置"""

    timing_multiplier: float = 1.0
    auto_placeholder: bool = True
    no_test_messages: bool = False
    max_concurrent_devices: int = 3


@dataclass
class MirrorSettings:
    """镜像设置"""

    max_size: int = 1080
    bit_rate: int = 8
    max_fps: int = 60
    stay_awake: bool = True
    turn_screen_off: bool = False
    show_touches: bool = False


@dataclass
class AIReplySettings:
    """AI 回复设置"""

    use_ai_reply: bool = False
    server_url: str = "http://localhost:8000"
    reply_timeout: int = 10
    system_prompt: str = ""
    prompt_style_key: str = "none"
    reply_max_length: int = 50


@dataclass
class AIAnalysisSettings:
    """AI 分析设置"""

    enabled: bool = True
    provider: str = "deepseek"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    max_tokens: int = 4096


@dataclass
class VolcengineSettings:
    """Volcengine ASR 设置"""

    enabled: bool = True
    api_key: str = ""
    resource_id: str = "volc.seedasr.auc"


@dataclass
class EmailSettings:
    """邮件通知设置"""

    enabled: bool = False
    smtp_server: str = "smtp.qq.com"
    smtp_port: int = 465
    sender_email: str = ""
    sender_password: str = ""
    sender_name: str = "WeCom 同步系统"
    receiver_email: str = ""
    notify_on_voice: bool = True
    notify_on_human_request: bool = True


@dataclass
class SidecarSettings:
    """Sidecar 设置"""

    send_via_sidecar: bool = False
    countdown_seconds: int = 0
    poll_interval: int = 10
    show_logs: bool = True
    max_panels: int = 3


@dataclass
class RealtimeSettings:
    """实时回复设置"""

    scan_interval: int = 60  # 扫描间隔（秒）
    use_ai_reply: bool = True  # 是否使用 AI 回复 (始终启用)
    send_via_sidecar: bool = True  # 是否通过 Sidecar 发送 (始终启用)


@dataclass
class FollowupSettings:
    """补刀功能设置（真正的补刀功能）"""

    followup_enabled: bool = False  # 是否启用补刀功能
    max_followups: int = 5  # 每次扫描最大补刀数量
    use_ai_reply: bool = False  # 补刀是否使用 AI 回复
    enable_operating_hours: bool = False  # 是否启用工作时间限制
    start_hour: str = "09:00"  # 开始时间
    end_hour: str = "18:00"  # 结束时间
    message_templates: list = field(
        default_factory=lambda: [
            "Hello, have you considered our offer?",
            "Feel free to contact me if you have any questions",
        ]
    )  # 消息模板列表
    followup_prompt: str = ""  # 补刀 AI 提示词
    idle_threshold_minutes: int = 30  # 空闲多久后进入补刀队列（分钟）
    max_attempts_per_customer: int = 3  # 每个客户最大补刀次数
    attempt_intervals: list = field(
        default_factory=lambda: [60, 120, 180]
    )  # 第1/2/3次补刀后的等待时间（分钟）
    avoid_duplicate_messages: bool = False  # 是否避免重复消息（去重功能）
    templates_hash: str = ""  # 模板hash（用于检测模板修改）


@dataclass
class AllSettings:
    """完整的应用设置"""

    general: GeneralSettings = field(default_factory=GeneralSettings)
    sync: SyncSettings = field(default_factory=SyncSettings)
    mirror: MirrorSettings = field(default_factory=MirrorSettings)
    ai_reply: AIReplySettings = field(default_factory=AIReplySettings)
    ai_analysis: AIAnalysisSettings = field(default_factory=AIAnalysisSettings)
    volcengine: VolcengineSettings = field(default_factory=VolcengineSettings)
    email: EmailSettings = field(default_factory=EmailSettings)
    sidecar: SidecarSettings = field(default_factory=SidecarSettings)
    realtime: RealtimeSettings = field(default_factory=RealtimeSettings)
    followup: FollowupSettings = field(default_factory=FollowupSettings)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于 API 响应）"""
        from dataclasses import asdict

        return {
            "general": asdict(self.general),
            "sync": asdict(self.sync),
            "mirror": asdict(self.mirror),
            "ai_reply": asdict(self.ai_reply),
            "ai_analysis": asdict(self.ai_analysis),
            "volcengine": asdict(self.volcengine),
            "email": asdict(self.email),
            "sidecar": asdict(self.sidecar),
            "realtime": asdict(self.realtime),
            "followup": asdict(self.followup),
        }

    def to_flat_dict(self) -> Dict[str, Any]:
        """转换为扁平字典（用于前端兼容）"""
        return {
            # General
            "hostname": self.general.hostname,
            "deviceId": self.general.device_id,
            "personName": self.general.person_name,
            "timezone": self.general.timezone,
            "backendUrl": self.general.backend_url,
            "autoRefreshInterval": self.general.auto_refresh_interval,
            "logMaxEntries": self.general.log_max_entries,
            "logUploadEnabled": self.general.log_upload_enabled,
            "logUploadTime": self.general.log_upload_time,
            "logUploadUrl": self.general.log_upload_url,
            "logUploadToken": self.general.log_upload_token,
            "imageServerIp": self.general.image_server_ip,
            "imageUploadEnabled": self.general.image_upload_enabled,
            "imageReviewTimeoutSeconds": self.general.image_review_timeout_seconds,
            "lowSpecMode": self.general.low_spec_mode,
            # Sync
            "timingMultiplier": self.sync.timing_multiplier,
            "autoPlaceholder": self.sync.auto_placeholder,
            "noTestMessages": self.sync.no_test_messages,
            "maxConcurrentSyncDevices": self.sync.max_concurrent_devices,
            # Mirror
            "mirrorMaxSize": self.mirror.max_size,
            "mirrorBitRate": self.mirror.bit_rate,
            "mirrorMaxFps": self.mirror.max_fps,
            "mirrorStayAwake": self.mirror.stay_awake,
            "mirrorTurnScreenOff": self.mirror.turn_screen_off,
            "mirrorShowTouches": self.mirror.show_touches,
            # AI Reply
            "useAIReply": self.ai_reply.use_ai_reply,
            "aiServerUrl": self.ai_reply.server_url,
            "aiReplyTimeout": self.ai_reply.reply_timeout,
            "systemPrompt": self.ai_reply.system_prompt,
            "promptStyleKey": self.ai_reply.prompt_style_key,
            "aiReplyMaxLength": self.ai_reply.reply_max_length,
            # AI Analysis
            "aiAnalysisEnabled": self.ai_analysis.enabled,
            "aiAnalysisProvider": self.ai_analysis.provider,
            "aiAnalysisApiKey": self.ai_analysis.api_key,
            "aiAnalysisBaseUrl": self.ai_analysis.base_url,
            "aiAnalysisModel": self.ai_analysis.model,
            "aiAnalysisMaxTokens": self.ai_analysis.max_tokens,
            # Volcengine
            "volcengineAsrEnabled": self.volcengine.enabled,
            "volcengineAsrApiKey": self.volcengine.api_key,
            "volcengineAsrResourceId": self.volcengine.resource_id,
            # Email
            "emailEnabled": self.email.enabled,
            "emailSmtpServer": self.email.smtp_server,
            "emailSmtpPort": self.email.smtp_port,
            "emailSenderEmail": self.email.sender_email,
            "emailSenderPassword": self.email.sender_password,
            "emailSenderName": self.email.sender_name,
            "emailReceiverEmail": self.email.receiver_email,
            "emailNotifyOnVoice": self.email.notify_on_voice,
            "emailNotifyOnHumanRequest": self.email.notify_on_human_request,
            # Sidecar
            "sendViaSidecar": self.sidecar.send_via_sidecar,
            "countdownSeconds": self.sidecar.countdown_seconds,
            "sidecarPollInterval": self.sidecar.poll_interval,
            "sidecarShowLogs": self.sidecar.show_logs,
            "sidecarMaxPanels": self.sidecar.max_panels,
            # Realtime Reply
            "scanInterval": self.realtime.scan_interval,
            "realtimeUseAIReply": self.realtime.use_ai_reply,
            "realtimeSendViaSidecar": self.realtime.send_via_sidecar,
            # Followup (补刀功能)
            "followupEnabled": self.followup.followup_enabled,
            "maxFollowupPerScan": self.followup.max_followups,
            "followupUseAIReply": self.followup.use_ai_reply,
            "enableOperatingHours": self.followup.enable_operating_hours,
            "startHour": self.followup.start_hour,
            "endHour": self.followup.end_hour,
            "followupMessageTemplates": self.followup.message_templates,
            "followupPrompt": self.followup.followup_prompt,
            "idleThresholdMinutes": self.followup.idle_threshold_minutes,
            "maxAttemptsPerCustomer": self.followup.max_attempts_per_customer,
            "attemptIntervals": self.followup.attempt_intervals,
            "avoidDuplicateMessages": self.followup.avoid_duplicate_messages,
            "templatesHash": self.followup.templates_hash,
        }
