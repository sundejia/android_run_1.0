"""
Follow-up 补刀功能设置管理

负责管理补刀功能的配置，使用统一设置服务。
注意：此文件不再处理实时回复配置，实时回复配置已迁移到 realtime 分类。
"""

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger("followup.settings")


def calculate_templates_hash(templates: list[str]) -> str:
    """
    计算模板列表的hash值（用于检测模板修改）

    Args:
        templates: 消息模板列表

    Returns:
        hash字符串（16位十六进制）
    """
    # 排序后标准化，确保顺序不影响hash
    normalized = json.dumps(sorted(templates), ensure_ascii=False)
    # 计算SHA256 hash并取前16位
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


@dataclass
class FollowUpSettings:
    """补刀功能设置"""

    followup_enabled: bool = False
    max_followups: int = 5  # 每次扫描最大补刀数量
    use_ai_reply: bool = False  # 是否使用 AI 生成补刀消息
    enable_operating_hours: bool = False
    start_hour: str = "09:00"
    end_hour: str = "18:00"
    message_templates: list[str] = None
    followup_prompt: str = ""  # 补刀 AI 提示词
    idle_threshold_minutes: int = 30  # 空闲多久后进入补刀队列
    max_attempts_per_customer: int = 3  # 每个客户最大补刀次数
    attempt_intervals: list[int] = None  # 第1/2/3次补刀后的等待时间（分钟）
    avoid_duplicate_messages: bool = False  # 是否避免重复消息（去重功能）
    templates_hash: str = ""  # 模板hash（用于检测模板修改）

    def __post_init__(self):
        if self.message_templates is None:
            self.message_templates = [
                "Hello, have you considered our offer?",
                "Feel free to contact me if you have any questions",
            ]
        if self.attempt_intervals is None:
            self.attempt_intervals = [60, 120, 180]

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FollowUpSettings":
        """从字典创建"""
        return cls(
            followup_enabled=bool(data.get("followup_enabled", False)),
            max_followups=int(data.get("max_followups", 5)),
            use_ai_reply=bool(data.get("use_ai_reply", False)),
            enable_operating_hours=bool(data.get("enable_operating_hours", False)),
            start_hour=str(data.get("start_hour", "09:00")),
            end_hour=str(data.get("end_hour", "18:00")),
            message_templates=data.get(
                "message_templates",
                ["Hello, have you considered our offer?", "Feel free to contact me if you have any questions"],
            ),
            followup_prompt=str(data.get("followup_prompt", "")),
            idle_threshold_minutes=int(data.get("idle_threshold_minutes", 30)),
            max_attempts_per_customer=int(data.get("max_attempts_per_customer", 3)),
            attempt_intervals=data.get("attempt_intervals", [60, 120, 180]),
            avoid_duplicate_messages=bool(data.get("avoid_duplicate_messages", False)),
            templates_hash=str(data.get("templates_hash", "")),
        )


class SettingsManager:
    """设置管理器 - 使用统一设置服务"""

    def __init__(self, db_path: str = None):
        # db_path 保留用于向后兼容，但不再直接使用
        self._db_path = db_path

    def get_settings(self) -> FollowUpSettings:
        """获取补刀功能设置 - 从统一设置服务读取"""
        try:
            from services.settings import get_settings_service

            svc = get_settings_service()
            followup = svc.get_followup_settings()

            return FollowUpSettings(
                followup_enabled=followup.followup_enabled,
                max_followups=followup.max_followups,
                use_ai_reply=followup.use_ai_reply,
                enable_operating_hours=followup.enable_operating_hours,
                start_hour=followup.start_hour,
                end_hour=followup.end_hour,
                message_templates=followup.message_templates,
                followup_prompt=getattr(followup, "followup_prompt", ""),
                idle_threshold_minutes=getattr(followup, "idle_threshold_minutes", 30),
                max_attempts_per_customer=getattr(followup, "max_attempts_per_customer", 3),
                attempt_intervals=getattr(followup, "attempt_intervals", [60, 120, 180]),
                avoid_duplicate_messages=getattr(followup, "avoid_duplicate_messages", False),
                templates_hash=getattr(followup, "templates_hash", ""),
            )
        except Exception as e:
            logger.error(f"[settings] Failed to read from unified settings service: {e}")
            # 返回默认设置
            return FollowUpSettings()

    def save_settings(self, settings: FollowUpSettings) -> None:
        """保存设置 - 写入统一设置服务"""
        try:
            from services.settings import SettingCategory, get_settings_service

            # 计算新hash（用于检测模板修改）
            new_hash = calculate_templates_hash(settings.message_templates)

            # 获取旧hash以检测变化
            old_settings = self.get_settings()
            old_hash = getattr(old_settings, "templates_hash", "") or ""

            # 检测模板变化
            templates_changed = old_hash != new_hash

            svc = get_settings_service()
            svc.set_category(
                SettingCategory.FOLLOWUP.value,
                {
                    "followup_enabled": settings.followup_enabled,
                    "max_followups": settings.max_followups,
                    "use_ai_reply": settings.use_ai_reply,
                    "enable_operating_hours": settings.enable_operating_hours,
                    "start_hour": settings.start_hour,
                    "end_hour": settings.end_hour,
                    "message_templates": settings.message_templates,
                    "followup_prompt": settings.followup_prompt,
                    "idle_threshold_minutes": settings.idle_threshold_minutes,
                    "max_attempts_per_customer": settings.max_attempts_per_customer,
                    "attempt_intervals": settings.attempt_intervals,
                    "avoid_duplicate_messages": settings.avoid_duplicate_messages,
                    "templates_hash": new_hash,
                },
                "followup_service",
            )

            # 如果模板发生变化，清空所有跟踪记录
            if templates_changed:
                try:
                    from .sent_messages_repository import FollowupSentMessagesRepository

                    sent_repo = FollowupSentMessagesRepository(self._db_path)
                    cleared = sent_repo.clear_all()
                    logger.info(
                        f"[settings] Templates changed (hash: {old_hash[:8]}... → {new_hash[:8]}...), "
                        f"cleared {cleared} sent message tracking records"
                    )
                except Exception as e:
                    logger.error(f"[settings] Failed to clear sent messages: {e}")
                    # 不中断保存流程，只记录错误

            logger.info("Followup settings saved successfully")
        except Exception as e:
            logger.error(f"[settings] Failed to save to unified settings service: {e}")
            raise

    def is_within_operating_hours(self) -> bool:
        """检查是否在工作时间内"""
        settings = self.get_settings()
        if not settings.enable_operating_hours:
            return True

        current_time = datetime.now().time()

        # 解析时间字符串
        try:
            start_hour, start_min = map(int, settings.start_hour.split(":"))
            end_hour, end_min = map(int, settings.end_hour.split(":"))

            start_time = datetime.now().replace(hour=start_hour, minute=start_min, second=0).time()
            end_time = datetime.now().replace(hour=end_hour, minute=end_min, second=0).time()

            if start_time <= end_time:
                return start_time <= current_time < end_time
            else:
                # Handle overnight hours (e.g., 22:00 - 06:00)
                return current_time >= start_time or current_time < end_time
        except Exception as e:
            logger.error(f"Failed to parse operating hours: {e}")
            return True  # 解析失败时默认允许
