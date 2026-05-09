"""
Settings 默认值定义

定义所有设置的默认值、类型和描述信息。
"""

from typing import Any

from .models import SettingCategory, ValueType

# 设置定义: (category, key, value_type, default_value, description, is_sensitive)
SETTING_DEFINITIONS: list[tuple[str, str, str, Any, str, bool]] = [
    (
        SettingCategory.GENERAL.value,
        "image_review_timeout_seconds",
        ValueType.INT.value,
        40,
        "图片审核等待超时(秒)",
        False,
    ),
    # ============================================================================
    # General Settings
    # ============================================================================
    (SettingCategory.GENERAL.value, "hostname", ValueType.STRING.value, "", "主机名称（用于日志文件前缀）", False),
    (SettingCategory.GENERAL.value, "device_id", ValueType.STRING.value, "", "稳定设备 ID（用于上传身份识别）", False),
    (
        SettingCategory.GENERAL.value,
        "person_name",
        ValueType.STRING.value,
        "",
        "人员姓名（用于上传业务身份展示）",
        False,
    ),
    (SettingCategory.GENERAL.value, "timezone", ValueType.STRING.value, "Asia/Shanghai", "IANA 时区标识", False),
    (
        SettingCategory.GENERAL.value,
        "backend_url",
        ValueType.STRING.value,
        "http://localhost:8765",
        "后端服务地址",
        False,
    ),
    (SettingCategory.GENERAL.value, "auto_refresh_interval", ValueType.INT.value, 5000, "自动刷新间隔(毫秒)", False),
    (SettingCategory.GENERAL.value, "log_max_entries", ValueType.INT.value, 1000, "日志最大条目数", False),
    (
        SettingCategory.GENERAL.value,
        "log_upload_enabled",
        ValueType.BOOLEAN.value,
        False,
        "是否启用日志定时上传",
        False,
    ),
    (SettingCategory.GENERAL.value, "log_upload_time", ValueType.STRING.value, "02:00", "日志每日上传时间", False),
    (SettingCategory.GENERAL.value, "log_upload_url", ValueType.STRING.value, "", "日志上传平台地址", False),
    (SettingCategory.GENERAL.value, "log_upload_token", ValueType.STRING.value, "", "日志上传鉴权令牌", True),
    (SettingCategory.GENERAL.value, "image_server_ip", ValueType.STRING.value, "", "图片审核服务器地址", False),
    (
        SettingCategory.GENERAL.value,
        "image_upload_enabled",
        ValueType.BOOLEAN.value,
        True,
        "是否启用图片自动上传到审核平台",
        False,
    ),
    (SettingCategory.GENERAL.value, "low_spec_mode", ValueType.BOOLEAN.value, False, "低配机器性能模式", False),
    # ============================================================================
    # Sync Settings
    # ============================================================================
    (SettingCategory.SYNC.value, "timing_multiplier", ValueType.FLOAT.value, 1.0, "时间乘数(避免检测)", False),
    (SettingCategory.SYNC.value, "auto_placeholder", ValueType.BOOLEAN.value, True, "语音消息自动占位符", False),
    (SettingCategory.SYNC.value, "no_test_messages", ValueType.BOOLEAN.value, False, "跳过测试消息", False),
    (SettingCategory.SYNC.value, "max_concurrent_devices", ValueType.INT.value, 3, "最大并发同步设备数", False),
    # ============================================================================
    # Mirror Settings
    # ============================================================================
    (SettingCategory.MIRROR.value, "max_size", ValueType.INT.value, 1080, "最大分辨率", False),
    (SettingCategory.MIRROR.value, "bit_rate", ValueType.INT.value, 8, "比特率(Mbps)", False),
    (SettingCategory.MIRROR.value, "max_fps", ValueType.INT.value, 60, "最大帧率", False),
    (SettingCategory.MIRROR.value, "stay_awake", ValueType.BOOLEAN.value, True, "保持唤醒", False),
    (SettingCategory.MIRROR.value, "turn_screen_off", ValueType.BOOLEAN.value, False, "关闭屏幕", False),
    (SettingCategory.MIRROR.value, "show_touches", ValueType.BOOLEAN.value, False, "显示触摸点", False),
    # ============================================================================
    # AI Reply Settings
    # ============================================================================
    (SettingCategory.AI_REPLY.value, "use_ai_reply", ValueType.BOOLEAN.value, False, "是否使用 AI 回复", False),
    (
        SettingCategory.AI_REPLY.value,
        "server_url",
        ValueType.STRING.value,
        "http://localhost:8000",
        "AI 服务器地址",
        False,
    ),
    (SettingCategory.AI_REPLY.value, "reply_timeout", ValueType.INT.value, 10, "AI 回复超时(秒)", False),
    (SettingCategory.AI_REPLY.value, "system_prompt", ValueType.STRING.value, "", "系统提示词", False),
    (SettingCategory.AI_REPLY.value, "prompt_style_key", ValueType.STRING.value, "none", "提示词风格预设", False),
    (SettingCategory.AI_REPLY.value, "reply_max_length", ValueType.INT.value, 50, "AI 回复最大长度", False),
    (
        SettingCategory.AI_REPLY.value,
        "max_retries",
        ValueType.INT.value,
        3,
        "AI 请求最大重试次数（仅对连接断开/超时类瞬时错误重试）",
        False,
    ),
    (
        SettingCategory.AI_REPLY.value,
        "retry_backoff_ms",
        ValueType.INT.value,
        500,
        "AI 请求重试基础退避时间(毫秒)，每次按指数递增并加入随机抖动",
        False,
    ),
    # ============================================================================
    # AI Analysis Settings
    # ============================================================================
    (SettingCategory.AI_ANALYSIS.value, "enabled", ValueType.BOOLEAN.value, True, "启用 AI 分析", False),
    (SettingCategory.AI_ANALYSIS.value, "provider", ValueType.STRING.value, "deepseek", "AI 供应商", False),
    (SettingCategory.AI_ANALYSIS.value, "api_key", ValueType.STRING.value, "", "API Key", True),  # 敏感信息
    (
        SettingCategory.AI_ANALYSIS.value,
        "base_url",
        ValueType.STRING.value,
        "https://api.deepseek.com",
        "API 地址",
        False,
    ),
    (SettingCategory.AI_ANALYSIS.value, "model", ValueType.STRING.value, "deepseek-chat", "模型名称", False),
    (SettingCategory.AI_ANALYSIS.value, "max_tokens", ValueType.INT.value, 4096, "最大 Token 数", False),
    # ============================================================================
    # Volcengine ASR Settings
    # ============================================================================
    (SettingCategory.VOLCENGINE.value, "enabled", ValueType.BOOLEAN.value, True, "启用语音转写", False),
    (SettingCategory.VOLCENGINE.value, "api_key", ValueType.STRING.value, "", "API Key", True),  # 敏感信息
    (SettingCategory.VOLCENGINE.value, "resource_id", ValueType.STRING.value, "volc.seedasr.auc", "资源 ID", False),
    # ============================================================================
    # Email Settings
    # ============================================================================
    (SettingCategory.EMAIL.value, "enabled", ValueType.BOOLEAN.value, False, "启用邮件通知", False),
    (SettingCategory.EMAIL.value, "smtp_server", ValueType.STRING.value, "smtp.qq.com", "SMTP 服务器", False),
    (SettingCategory.EMAIL.value, "smtp_port", ValueType.INT.value, 465, "SMTP 端口", False),
    (SettingCategory.EMAIL.value, "sender_email", ValueType.STRING.value, "", "发件人邮箱", False),
    (SettingCategory.EMAIL.value, "sender_password", ValueType.STRING.value, "", "发件人密码/授权码", True),  # 敏感信息
    (SettingCategory.EMAIL.value, "sender_name", ValueType.STRING.value, "WeCom 同步系统", "发件人名称", False),
    (SettingCategory.EMAIL.value, "receiver_email", ValueType.STRING.value, "", "收件人邮箱", False),
    (SettingCategory.EMAIL.value, "notify_on_voice", ValueType.BOOLEAN.value, True, "语音消息通知", False),
    (SettingCategory.EMAIL.value, "notify_on_human_request", ValueType.BOOLEAN.value, True, "转人工通知", False),
    # ============================================================================
    # Sidecar Settings
    # ============================================================================
    (SettingCategory.SIDECAR.value, "send_via_sidecar", ValueType.BOOLEAN.value, False, "通过 Sidecar 发送", False),
    (SettingCategory.SIDECAR.value, "countdown_seconds", ValueType.INT.value, 0, "倒计时秒数", False),
    (SettingCategory.SIDECAR.value, "poll_interval", ValueType.INT.value, 2, "轮询间隔(秒)", False),
    (SettingCategory.SIDECAR.value, "show_logs", ValueType.BOOLEAN.value, True, "Sidecar 是否显示日志面板", False),
    (SettingCategory.SIDECAR.value, "max_panels", ValueType.INT.value, 3, "Sidecar 最大并排面板数量", False),
    (SettingCategory.SIDECAR.value, "sidecar_timeout", ValueType.INT.value, 120, "Sidecar 审核超时(秒)", False),
    (SettingCategory.SIDECAR.value, "night_mode_sidecar_timeout", ValueType.INT.value, 60, "夜间审核超时(秒)", False),
    (SettingCategory.SIDECAR.value, "night_mode_start_hour", ValueType.INT.value, 22, "夜间模式开始时间(时)", False),
    (SettingCategory.SIDECAR.value, "night_mode_end_hour", ValueType.INT.value, 8, "夜间模式结束时间(时)", False),
    (SettingCategory.SIDECAR.value, "sidecar_grace_seconds", ValueType.INT.value, 30, "Sidecar 超时后等待 SENDING 完成的宽限时间(秒)", False),
    # ============================================================================
    # Realtime Reply Settings
    # ============================================================================
    (SettingCategory.REALTIME.value, "scan_interval", ValueType.INT.value, 60, "扫描间隔(秒)", False),
    (SettingCategory.REALTIME.value, "use_ai_reply", ValueType.BOOLEAN.value, True, "使用 AI 回复 (始终启用)", False),
    (
        SettingCategory.REALTIME.value,
        "send_via_sidecar",
        ValueType.BOOLEAN.value,
        True,
        "通过 Sidecar 发送 (始终启用)",
        False,
    ),
    (
        SettingCategory.REALTIME.value,
        "max_concurrent_devices",
        ValueType.INT.value,
        4,
        "实时回复最大并发设备数",
        False,
    ),
    (
        SettingCategory.REALTIME.value,
        "stagger_delay_seconds",
        ValueType.INT.value,
        10,
        "实时回复设备启动错峰间隔(秒)，避免多设备同时撞 ADB",
        False,
    ),
    (
        SettingCategory.REALTIME.value,
        "scroll_to_top_enabled",
        ValueType.BOOLEAN.value,
        True,
        "扫描前是否滚动到会话列表顶部（关闭可省 ~20s/scan，但可能错过滚动后才出现的红点）",
        False,
    ),
    (
        SettingCategory.REALTIME.value,
        "launch_wecom_enabled",
        ValueType.BOOLEAN.value,
        True,
        "扫描前是否主动启动/前置企微（关闭可省 ~5s/scan；仅当你保证企微始终前台时安全）",
        False,
    ),
    (
        SettingCategory.REALTIME.value,
        "switch_to_private_chats_enabled",
        ValueType.BOOLEAN.value,
        True,
        "扫描前是否切到“私聊”tab（关闭可省 ~4s/scan；仅当你保证已停留在私聊 tab 时安全）",
        False,
    ),
    # ============================================================================
    # Followup Settings (补刀功能专用配置)
    # ============================================================================
    # Note: These are for the followup feature (补刀), not realtime reply
    (SettingCategory.FOLLOWUP.value, "followup_enabled", ValueType.BOOLEAN.value, False, "启用补刀功能", False),
    (SettingCategory.FOLLOWUP.value, "max_followups", ValueType.INT.value, 5, "最大补刀数量", False),
    (SettingCategory.FOLLOWUP.value, "use_ai_reply", ValueType.BOOLEAN.value, False, "补刀使用 AI 回复", False),
    (
        SettingCategory.FOLLOWUP.value,
        "enable_operating_hours",
        ValueType.BOOLEAN.value,
        False,
        "启用工作时间限制",
        False,
    ),
    (SettingCategory.FOLLOWUP.value, "start_hour", ValueType.STRING.value, "09:00", "开始时间", False),
    (SettingCategory.FOLLOWUP.value, "end_hour", ValueType.STRING.value, "18:00", "结束时间", False),
    (
        SettingCategory.FOLLOWUP.value,
        "message_templates",
        ValueType.JSON.value,
        ["Hello, have you considered our offer?", "Feel free to contact me if you have any questions"],
        "消息模板",
        False,
    ),
    (SettingCategory.FOLLOWUP.value, "followup_prompt", ValueType.STRING.value, "", "补刀 AI 提示词", False),
    (SettingCategory.FOLLOWUP.value, "idle_threshold_minutes", ValueType.INT.value, 30, "空闲阈值（分钟）", False),
    (SettingCategory.FOLLOWUP.value, "max_attempts_per_customer", ValueType.INT.value, 3, "每客户最大补刀次数", False),
    (
        SettingCategory.FOLLOWUP.value,
        "attempt_intervals",
        ValueType.JSON.value,
        [60, 120, 180],
        "补刀间隔时间（分钟）",
        False,
    ),
    # ============================================================================
    # Media auto-actions (customer image/video -> optional blacklist + group invite)
    # ============================================================================
    ("media_auto_actions", "enabled", ValueType.BOOLEAN.value, False, "启用客户发图/视频后的自动动作", False),
    (
        "media_auto_actions",
        "auto_blacklist",
        ValueType.JSON.value,
        {
            "enabled": False,
            "reason": "Customer sent media (auto)",
            "skip_if_already_blacklisted": True,
            # False (default): customer-sent media → blacklist immediately.
            # True: defer to the image-rating-server review verdict so the
            # blacklist gate mirrors auto-group-invite. Flip on only when the
            # rating pipeline is actually wired in.
            "require_review_pass": False,
        },
        "自动拉黑子配置",
        False,
    ),
    (
        "media_auto_actions",
        "auto_group_invite",
        ValueType.JSON.value,
        {
            "enabled": False,
            "group_members": [],
            "group_name_template": "{customer_name}-服务群",
            "skip_if_group_exists": True,
            "member_source": "manual",
            "send_test_message_after_create": True,
            "test_message_text": "测试",
            "post_confirm_wait_seconds": 1.0,
            "duplicate_name_policy": "first",
            "video_invite_policy": "extract_frame",
        },
        "自动拉群子配置",
        False,
    ),
    (
        "media_auto_actions",
        "auto_contact_share",
        ValueType.JSON.value,
        {
            "enabled": False,
            "contact_name": "",
            "skip_if_already_shared": True,
            "cooldown_seconds": 0,
            "kefu_overrides": {},
            "send_message_before_share": False,
            "pre_share_message_text": "",
        },
        "自动发名片子配置",
        False,
    ),
    (
        "media_auto_actions",
        "review_gate",
        ValueType.JSON.value,
        {
            "enabled": False,
            "rating_server_url": "http://127.0.0.1:8080",
            "upload_timeout_seconds": 30.0,
            "upload_max_attempts": 3,
            "video_review_policy": "extract_frame",
        },
        "媒体动作图片审核门配置",
        False,
    ),
    # ============================================================================
    # Dashboard Settings (监控面板)
    # ============================================================================
    (SettingCategory.DASHBOARD.value, "enabled", ValueType.BOOLEAN.value, False, "是否启用监控面板上报", False),
    (SettingCategory.DASHBOARD.value, "url", ValueType.STRING.value, "", "监控面板 WebSocket 地址", False),
]


# 前端键名映射 (前端 camelCase -> 后端 category.key)
FRONTEND_KEY_MAPPING: dict[str, tuple[str, str]] = {
    # General
    "hostname": (SettingCategory.GENERAL.value, "hostname"),
    "deviceId": (SettingCategory.GENERAL.value, "device_id"),
    "personName": (SettingCategory.GENERAL.value, "person_name"),
    "timezone": (SettingCategory.GENERAL.value, "timezone"),
    "backendUrl": (SettingCategory.GENERAL.value, "backend_url"),
    "autoRefreshInterval": (SettingCategory.GENERAL.value, "auto_refresh_interval"),
    "logMaxEntries": (SettingCategory.GENERAL.value, "log_max_entries"),
    "logUploadEnabled": (SettingCategory.GENERAL.value, "log_upload_enabled"),
    "logUploadTime": (SettingCategory.GENERAL.value, "log_upload_time"),
    "logUploadUrl": (SettingCategory.GENERAL.value, "log_upload_url"),
    "logUploadToken": (SettingCategory.GENERAL.value, "log_upload_token"),
    "imageServerIp": (SettingCategory.GENERAL.value, "image_server_ip"),
    "imageUploadEnabled": (SettingCategory.GENERAL.value, "image_upload_enabled"),
    "imageReviewTimeoutSeconds": (SettingCategory.GENERAL.value, "image_review_timeout_seconds"),
    "lowSpecMode": (SettingCategory.GENERAL.value, "low_spec_mode"),
    # Sync
    "timingMultiplier": (SettingCategory.SYNC.value, "timing_multiplier"),
    "autoPlaceholder": (SettingCategory.SYNC.value, "auto_placeholder"),
    "noTestMessages": (SettingCategory.SYNC.value, "no_test_messages"),
    "maxConcurrentSyncDevices": (SettingCategory.SYNC.value, "max_concurrent_devices"),
    # Mirror
    "mirrorMaxSize": (SettingCategory.MIRROR.value, "max_size"),
    "mirrorBitRate": (SettingCategory.MIRROR.value, "bit_rate"),
    "mirrorMaxFps": (SettingCategory.MIRROR.value, "max_fps"),
    "mirrorStayAwake": (SettingCategory.MIRROR.value, "stay_awake"),
    "mirrorTurnScreenOff": (SettingCategory.MIRROR.value, "turn_screen_off"),
    "mirrorShowTouches": (SettingCategory.MIRROR.value, "show_touches"),
    # AI Reply
    "useAIReply": (SettingCategory.AI_REPLY.value, "use_ai_reply"),
    "aiServerUrl": (SettingCategory.AI_REPLY.value, "server_url"),
    "aiReplyTimeout": (SettingCategory.AI_REPLY.value, "reply_timeout"),
    "systemPrompt": (SettingCategory.AI_REPLY.value, "system_prompt"),
    "promptStyleKey": (SettingCategory.AI_REPLY.value, "prompt_style_key"),
    "aiReplyMaxLength": (SettingCategory.AI_REPLY.value, "reply_max_length"),
    "aiReplyMaxRetries": (SettingCategory.AI_REPLY.value, "max_retries"),
    "aiReplyRetryBackoffMs": (SettingCategory.AI_REPLY.value, "retry_backoff_ms"),
    # AI Analysis
    "aiAnalysisEnabled": (SettingCategory.AI_ANALYSIS.value, "enabled"),
    "aiAnalysisProvider": (SettingCategory.AI_ANALYSIS.value, "provider"),
    "aiAnalysisApiKey": (SettingCategory.AI_ANALYSIS.value, "api_key"),
    "aiAnalysisBaseUrl": (SettingCategory.AI_ANALYSIS.value, "base_url"),
    "aiAnalysisModel": (SettingCategory.AI_ANALYSIS.value, "model"),
    "aiAnalysisMaxTokens": (SettingCategory.AI_ANALYSIS.value, "max_tokens"),
    # Volcengine
    "volcengineAsrEnabled": (SettingCategory.VOLCENGINE.value, "enabled"),
    "volcengineAsrApiKey": (SettingCategory.VOLCENGINE.value, "api_key"),
    "volcengineAsrResourceId": (SettingCategory.VOLCENGINE.value, "resource_id"),
    # Email
    "emailEnabled": (SettingCategory.EMAIL.value, "enabled"),
    "emailSmtpServer": (SettingCategory.EMAIL.value, "smtp_server"),
    "emailSmtpPort": (SettingCategory.EMAIL.value, "smtp_port"),
    "emailSenderEmail": (SettingCategory.EMAIL.value, "sender_email"),
    "emailSenderPassword": (SettingCategory.EMAIL.value, "sender_password"),
    "emailSenderName": (SettingCategory.EMAIL.value, "sender_name"),
    "emailReceiverEmail": (SettingCategory.EMAIL.value, "receiver_email"),
    "emailNotifyOnVoice": (SettingCategory.EMAIL.value, "notify_on_voice"),
    "emailNotifyOnHumanRequest": (SettingCategory.EMAIL.value, "notify_on_human_request"),
    # Sidecar
    "sendViaSidecar": (SettingCategory.SIDECAR.value, "send_via_sidecar"),
    "countdownSeconds": (SettingCategory.SIDECAR.value, "countdown_seconds"),
    "sidecarPollInterval": (SettingCategory.SIDECAR.value, "poll_interval"),
    "sidecarShowLogs": (SettingCategory.SIDECAR.value, "show_logs"),
    "sidecarMaxPanels": (SettingCategory.SIDECAR.value, "max_panels"),
    # Realtime Reply
    "scanInterval": (SettingCategory.REALTIME.value, "scan_interval"),
    "realtimeUseAIReply": (SettingCategory.REALTIME.value, "use_ai_reply"),
    "realtimeSendViaSidecar": (SettingCategory.REALTIME.value, "send_via_sidecar"),
    "maxConcurrentRealtimeDevices": (SettingCategory.REALTIME.value, "max_concurrent_devices"),
    "realtimeStaggerDelaySeconds": (SettingCategory.REALTIME.value, "stagger_delay_seconds"),
    "realtimeScrollToTopEnabled": (SettingCategory.REALTIME.value, "scroll_to_top_enabled"),
    "realtimeLaunchWecomEnabled": (SettingCategory.REALTIME.value, "launch_wecom_enabled"),
    "realtimeSwitchToPrivateChatsEnabled": (SettingCategory.REALTIME.value, "switch_to_private_chats_enabled"),
    # Followup (补刀功能)
    "followupEnabled": (SettingCategory.FOLLOWUP.value, "followup_enabled"),
    "maxFollowupPerScan": (SettingCategory.FOLLOWUP.value, "max_followups"),
    "followupUseAIReply": (SettingCategory.FOLLOWUP.value, "use_ai_reply"),
    "enableOperatingHours": (SettingCategory.FOLLOWUP.value, "enable_operating_hours"),
    "startHour": (SettingCategory.FOLLOWUP.value, "start_hour"),
    "endHour": (SettingCategory.FOLLOWUP.value, "end_hour"),
    "followupMessageTemplates": (SettingCategory.FOLLOWUP.value, "message_templates"),
    "followupPrompt": (SettingCategory.FOLLOWUP.value, "followup_prompt"),
    "idleThresholdMinutes": (SettingCategory.FOLLOWUP.value, "idle_threshold_minutes"),
    "maxAttemptsPerCustomer": (SettingCategory.FOLLOWUP.value, "max_attempts_per_customer"),
    "attemptIntervals": (SettingCategory.FOLLOWUP.value, "attempt_intervals"),
    # Dashboard
    "dashboardEnabled": (SettingCategory.DASHBOARD.value, "enabled"),
    "dashboardUrl": (SettingCategory.DASHBOARD.value, "url"),
}


# 反向映射 (category.key -> 前端 camelCase)
BACKEND_TO_FRONTEND_MAPPING: dict[tuple[str, str], str] = {v: k for k, v in FRONTEND_KEY_MAPPING.items()}


def get_default_value(category: str, key: str) -> Any:
    """获取指定设置的默认值"""
    for cat, k, _, default, _, _ in SETTING_DEFINITIONS:
        if cat == category and k == key:
            return default
    return None


def get_value_type(category: str, key: str) -> str:
    """获取指定设置的值类型"""
    for cat, k, vtype, _, _, _ in SETTING_DEFINITIONS:
        if cat == category and k == key:
            return vtype
    return ValueType.STRING.value


def get_all_defaults() -> dict[str, dict[str, Any]]:
    """获取所有默认值，按类别分组"""
    result: dict[str, dict[str, Any]] = {}
    for cat, key, _, default, _, _ in SETTING_DEFINITIONS:
        if cat not in result:
            result[cat] = {}
        result[cat][key] = default
    return result


def get_category_defaults(category: str) -> dict[str, Any]:
    """获取指定类别的所有默认值"""
    result = {}
    for cat, key, _, default, _, _ in SETTING_DEFINITIONS:
        if cat == category:
            result[key] = default
    return result
