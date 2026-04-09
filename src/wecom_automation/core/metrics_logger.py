"""
业务指标日志记录器

专门用于收集和记录业务指标，采用JSON Lines格式输出。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger as _loguru_logger

from wecom_automation.core.config import get_project_root


@dataclass
class MetricEvent:
    """指标事件"""

    timestamp: str
    level: str
    event: str
    session_id: str
    device_serial: str
    data: dict[str, Any]


def _get_hostname() -> str:
    """从设置中获取主机名"""
    try:
        from services.settings.service import SettingsService
        from wecom_automation.core.config import get_default_db_path

        db_path = str(get_default_db_path())
        settings_service = SettingsService(db_path)
        hostname = settings_service.get("general", "hostname", "default")

        if not hostname or not hostname.strip():
            return "default"

        hostname = hostname.strip().replace("/", "-").replace("\\", "-").replace(" ", "_")
        return hostname
    except Exception:
        return "default"


class MetricsLogger:
    """业务指标日志记录器 - 使用 loguru sink"""

    def __init__(
        self,
        log_dir: Path | None = None,
        device_serial: str = "unknown",
        hostname: str | None = None,
    ):
        self._device_serial = device_serial
        self._session_id = str(uuid.uuid4())[:8]

        # 确定日志目录
        if log_dir is None:
            log_dir = get_project_root() / "logs" / "metrics"

        log_dir.mkdir(parents=True, exist_ok=True)

        # 获取主机名
        if hostname is None:
            hostname = _get_hostname()

        # 创建专用 loguru sink（JSON Lines 格式）
        log_file = log_dir / f"{hostname}-{device_serial}.jsonl"

        # 添加一个专用的 sink 用于指标日志
        # 使用 filter 确保只记录这个 MetricsLogger 的消息
        self._sink_id = _loguru_logger.add(
            log_file,
            format="{message}",  # 只输出消息本身（JSON）
            rotation="00:00",  # 午夜轮转
            retention="30 days",
            encoding="utf-8",
            enqueue=True,  # 多进程安全
            filter=lambda r: r["extra"].get("metrics_session") == self._session_id,
            level="INFO",
        )

        # 绑定 context，用于 filter
        self._logger = _loguru_logger.bind(metrics_session=self._session_id, device=device_serial)

        # 统计计数器
        self._counters = {
            "messages_added": 0,
            "messages_skipped": 0,
            "ai_replies_generated": 0,
            "ai_replies_sent": 0,
            "ai_replies_failed": 0,
            "blacklist_additions": 0,
            "user_deleted_detected": 0,
            "errors": 0,
            "customers_processed": set(),
            "customers_engaged": set(),  # 有回复的客户
        }

        self._start_time = datetime.now()

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        """输出一条指标日志"""
        metric = MetricEvent(
            timestamp=datetime.now().isoformat(),
            level="METRIC",
            event=event,
            session_id=self._session_id,
            device_serial=self._device_serial,
            data=data,
        )
        self._logger.info(json.dumps(asdict(metric), ensure_ascii=False))

    # =========================================================================
    # L3 消息级别事件
    # =========================================================================

    def log_message_received(
        self,
        customer_name: str,
        message_type: str,
        sender: str,
        content_length: int = 0,
    ) -> None:
        """记录收到消息"""
        self._emit(
            "message_received",
            {
                "customer_name": customer_name,
                "message_type": message_type,
                "sender": sender,
                "content_length": content_length,
            },
        )

    def log_message_processed(
        self,
        customer_db_id: int,
        customer_name: str,
        message_db_id: int,  # 消息在数据库中的ID
        message_type: str,
        sender: str,
        added: bool,
        processing_duration_ms: float,
        ai_generated: bool = False,
        ai_reply_length: int = 0,
        ai_reply_db_id: int | None = None,  # AI回复的数据库ID
        reply_to_message_db_id: int | None = None,  # 回复的是哪条消息
        reply_sent_success: bool = False,
        error_message: str | None = None,
    ) -> None:
        """记录消息处理完成"""
        if added:
            self._counters["messages_added"] += 1
        else:
            self._counters["messages_skipped"] += 1

        self._counters["customers_processed"].add(customer_name)

        if ai_generated:
            self._counters["ai_replies_generated"] += 1
            if reply_sent_success:
                self._counters["ai_replies_sent"] += 1
                self._counters["customers_engaged"].add(customer_name)
            else:
                self._counters["ai_replies_failed"] += 1

        if error_message:
            self._counters["errors"] += 1

        self._emit(
            "message_processed",
            {
                "customer_db_id": customer_db_id,
                "customer_name": customer_name,
                "message_db_id": message_db_id,
                "message_type": message_type,
                "sender": sender,
                "added": added,
                "processing_duration_ms": processing_duration_ms,
                "ai_generated": ai_generated,
                "ai_reply_length": ai_reply_length,
                "ai_reply_db_id": ai_reply_db_id,
                "reply_to_message_db_id": reply_to_message_db_id,
                "reply_sent_success": reply_sent_success,
                "error_message": error_message,
            },
        )

    def log_ai_reply_generated(
        self,
        customer_db_id: int,
        customer_name: str,
        reply_to_message_db_id: int,  # 回复的是哪条消息
        reply_content: str,
        generation_time_ms: float,
    ) -> None:
        """记录AI回复生成"""
        self._emit(
            "ai_reply_generated",
            {
                "customer_db_id": customer_db_id,
                "customer_name": customer_name,
                "reply_to_message_db_id": reply_to_message_db_id,
                "reply_length": len(reply_content),
                "generation_time_ms": generation_time_ms,
            },
        )

    def log_reply_sent(
        self,
        customer_name: str,
        success: bool,
        method: str,  # "sidecar" or "direct"
        reply_db_id: int | None = None,  # 回复消息的数据库ID
        error: str | None = None,
    ) -> None:
        """记录回复发送结果"""
        if success:
            self._counters["ai_replies_sent"] += 1
            self._counters["customers_engaged"].add(customer_name)
        else:
            self._counters["ai_replies_failed"] += 1

        self._emit(
            "reply_sent",
            {
                "customer_name": customer_name,
                "success": success,
                "method": method,
                "reply_db_id": reply_db_id,
                "error": error,
            },
        )

    def record_messages_stored(self, added: int, skipped: int = 0) -> None:
        """记录批量存储的消息数量"""
        self._counters["messages_added"] += added
        self._counters["messages_skipped"] += skipped

    def record_customer_processed(self, customer_name: str) -> None:
        """记录处理过的客户（用于统计覆盖率）"""
        self._counters["customers_processed"].add(customer_name)

    def record_ai_reply_generated(self) -> None:
        """记录AI回复已生成（计数）"""
        self._counters["ai_replies_generated"] += 1

    # =========================================================================
    # L2 客户级别事件
    # =========================================================================

    def log_customer_updated(
        self,
        customer_db_id: int,
        customer_name: str,
        channel: str | None,
        message_count: int,
        ai_reply_count: int,
        is_blacklisted: bool,
        is_deleted: bool,
        friend_added_at: str | None = None,
        first_customer_media_at: str | None = None,
        has_customer_media: bool = False,
        derived_tags: list[str] | None = None,
    ) -> None:
        """记录客户状态更新"""
        self._emit(
            "customer_updated",
            {
                "customer_db_id": customer_db_id,
                "customer_name": customer_name,
                "channel": channel,
                "message_count": message_count,
                "ai_reply_count": ai_reply_count,
                "is_blacklisted": is_blacklisted,
                "is_deleted": is_deleted,
                "friend_added_at": friend_added_at,
                "first_customer_media_at": first_customer_media_at,
                "has_customer_media": has_customer_media,
                "derived_tags": derived_tags or [],
            },
        )

    def log_blacklist_added(
        self,
        customer_db_id: int | None,
        customer_name: str,
        channel: str | None,
        reason: str,
        deleted_by_user: bool = False,
    ) -> None:
        """记录加入黑名单"""
        self._counters["blacklist_additions"] += 1

        self._emit(
            "blacklist_added",
            {
                "customer_db_id": customer_db_id,
                "customer_name": customer_name,
                "channel": channel,
                "reason": reason,
                "deleted_by_user": deleted_by_user,
            },
        )

    def log_user_deleted(
        self,
        customer_db_id: int | None,
        customer_name: str,
        channel: str | None,
        detected_message: str,
    ) -> None:
        """记录检测到用户删除"""
        self._counters["user_deleted_detected"] += 1

        self._emit(
            "user_deleted",
            {
                "customer_db_id": customer_db_id,
                "customer_name": customer_name,
                "channel": channel,
                "detected_message": detected_message,
            },
        )

    # =========================================================================
    # L4 对话记录级别事件
    # =========================================================================

    def log_conversation_context(
        self,
        customer_db_id: int,
        customer_name: str,
        channel: str | None,
        today_message_db_ids: list[int],
        today_ai_reply_db_ids: list[int],
        conversation_thread: list[dict[str, Any]],
        conversation_snapshot: list[dict[str, Any]],
    ) -> None:
        """
        记录完整对话上下文

        在处理完一个客户后调用，记录当天的完整聊天记录ID链。

        Args:
            customer_db_id: 客户数据库ID
            customer_name: 客户名称
            channel: 渠道
            today_message_db_ids: 当天所有消息的数据库ID列表
            today_ai_reply_db_ids: 当天AI回复的数据库ID列表
            conversation_thread: 对话线索 [{"db_id": 1, "sender": "customer"}, {"db_id": 2, "sender": "kefu"}, ...]
            conversation_snapshot: 最近N条消息快照 [{"db_id": 1, "sender": "customer", "content": "...", "type": "text"}, ...]
        """
        self._emit(
            "conversation_context",
            {
                "customer_db_id": customer_db_id,
                "customer_name": customer_name,
                "channel": channel,
                "today_message_count": len(today_message_db_ids),
                "today_message_db_ids": today_message_db_ids,
                "today_ai_reply_count": len(today_ai_reply_db_ids),
                "today_ai_reply_db_ids": today_ai_reply_db_ids,
                "conversation_thread": conversation_thread,
                "conversation_snapshot": conversation_snapshot,
            },
        )

    # =========================================================================
    # L1 汇总级别事件
    # =========================================================================

    def log_session_summary(self) -> None:
        """记录会话结束汇总"""
        duration = (datetime.now() - self._start_time).total_seconds()
        total_messages = self._counters["messages_added"] + self._counters["messages_skipped"]
        total_customers = len(self._counters["customers_processed"])
        engaged_customers = len(self._counters["customers_engaged"])

        self._emit(
            "session_summary",
            {
                "duration_seconds": duration,
                "total_messages": total_messages,
                "messages_added": self._counters["messages_added"],
                "messages_skipped": self._counters["messages_skipped"],
                "ai_replies_generated": self._counters["ai_replies_generated"],
                "ai_replies_sent": self._counters["ai_replies_sent"],
                "ai_replies_failed": self._counters["ai_replies_failed"],
                "blacklist_additions": self._counters["blacklist_additions"],
                "user_deleted_detected": self._counters["user_deleted_detected"],
                "errors": self._counters["errors"],
                "total_customers": total_customers,
                "engaged_customers": engaged_customers,
                "engagement_rate": engaged_customers / total_customers if total_customers > 0 else 0,
            },
        )

    def log_error(
        self,
        error_type: str,
        error_message: str,
        customer_name: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """记录错误"""
        self._counters["errors"] += 1

        self._emit(
            "error_occurred",
            {
                "error_type": error_type,
                "error_message": error_message,
                "customer_name": customer_name,
                "context": context or {},
            },
        )


# 全局实例管理
_metrics_loggers: dict[str, MetricsLogger] = {}


def get_metrics_logger(device_serial: str = "default", hostname: str | None = None) -> MetricsLogger:
    """获取指定设备的指标记录器"""
    if device_serial not in _metrics_loggers:
        _metrics_loggers[device_serial] = MetricsLogger(
            device_serial=device_serial,
            hostname=hostname,
        )
    return _metrics_loggers[device_serial]
