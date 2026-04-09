"""
补刀队列管理器

负责：
1. 检测哪些客户需要进入补刀队列（kefu 最后消息超过阈值）
2. 检测哪些客户已回复需要移出队列
3. 执行补刀并更新状态

调用时机：实时回复扫描结束后的间隙
"""

import asyncio
import dataclasses
import logging
import random
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from droidrun import AdbTools

from services.conversation_storage import get_control_db_path

from .attempts_repository import (
    AttemptStatus,
    FollowupAttempt,
    FollowupAttemptsRepository,
)
from .executor import FollowupExecutor, FollowupStatus
from .settings import FollowUpSettings, SettingsManager

logger = logging.getLogger("followup.queue_manager")


@dataclass
class ConversationInfo:
    """对话信息（用于判断是否需要补刀）"""

    customer_name: str
    customer_channel: str | None = None
    customer_id: str | None = None
    last_message_id: str = ""
    last_message_time: datetime | None = None
    last_message_sender: str = ""  # "kefu" 或 "customer"


class FollowupQueueManager:
    """
    补刀队列管理器

    使用方式：
        manager = FollowupQueueManager(device_serial)

        # 在实时回复扫描结束后调用
        await manager.process_conversations(conversations)

        # 如果没有红点用户，执行补刀
        if no_red_dot_users:
            await manager.execute_pending_followups()
    """

    def __init__(
        self,
        device_serial: str,
        adb: AdbTools | None = None,
        db_path: str | None = None,
        log_callback: Callable[[str, str], None] | None = None,
    ):
        self.device_serial = device_serial
        self._adb = adb
        self._db_path = db_path
        # Follow-up attempts must live in the shared control DB so the
        # management API and the runtime worker observe the same records.
        self._attempts_db_path = str(get_control_db_path())
        self._log_callback = log_callback

        # 延迟初始化
        self._repository: FollowupAttemptsRepository | None = None
        self._settings_manager: SettingsManager | None = None
        self._executor: FollowupExecutor | None = None
        self._wecom = None  # WeComService，用于屏幕检测和导航
        self._settings_cache: FollowUpSettings | None = None
        self._settings_cache_time: float = 0

    def _log(self, msg: str, level: str = "INFO"):
        """记录日志"""
        if level == "ERROR":
            logger.error(f"[{self.device_serial}] [QueueMgr] {msg}")
        elif level == "WARN":
            logger.warning(f"[{self.device_serial}] [QueueMgr] {msg}")
        elif level == "DEBUG":
            logger.debug(f"[{self.device_serial}] [QueueMgr] {msg}")
        else:
            logger.info(f"[{self.device_serial}] [QueueMgr] {msg}")

        if self._log_callback:
            try:
                self._log_callback(msg, level)
            except Exception:
                pass

    # ==================== 懒加载 ====================

    def _get_repository(self) -> FollowupAttemptsRepository:
        if self._repository is None:
            self._repository = FollowupAttemptsRepository(self._attempts_db_path)
        return self._repository

    def _get_settings_manager(self) -> SettingsManager:
        if self._settings_manager is None:
            self._settings_manager = SettingsManager(self._db_path)
        return self._settings_manager

    def _get_settings(self, force_refresh: bool = False) -> FollowUpSettings:
        """获取设置（带缓存）"""
        import time

        now = time.time()

        if not force_refresh and self._settings_cache is not None and now - self._settings_cache_time < 30:
            return self._settings_cache

        self._settings_cache = self._get_settings_manager().get_settings()
        self._settings_cache_time = now
        return self._settings_cache

    def _get_wecom(self):
        """获取 WeComService 实例（延迟初始化）"""
        if self._wecom is None:
            from wecom_automation.core.config import Config, ScrollConfig
            from wecom_automation.services.wecom_service import WeComService

            custom_scroll = dataclasses.replace(
                ScrollConfig(), max_scrolls=5, stable_threshold=2
            )
            config = Config(scroll=custom_scroll, device_serial=self.device_serial)
            self._wecom = WeComService(config)
        return self._wecom

    def _get_executor(self) -> FollowupExecutor:
        if self._executor is None:
            self._executor = FollowupExecutor(
                device_serial=self.device_serial,
                adb=self._adb,
                log_callback=self._log_callback,
            )
        return self._executor

    def _get_latest_conversation_info(self, customer_name: str) -> ConversationInfo | None:
        """Fetch the latest persisted conversation state for one customer."""
        if not self._db_path:
            return None

        query = """
            SELECT
                c.id AS customer_id,
                c.name AS customer_name,
                c.channel AS customer_channel,
                m.id AS message_id,
                m.is_from_kefu,
                m.timestamp_parsed AS message_time
            FROM customers c
            JOIN messages m ON m.customer_id = c.id
            JOIN kefus k ON c.kefu_id = k.id
            JOIN kefu_devices kd ON k.id = kd.kefu_id
            JOIN devices d ON kd.device_id = d.id
            WHERE d.serial = ?
              AND c.name = ?
            ORDER BY COALESCE(m.timestamp_parsed, m.created_at) DESC, m.id DESC
            LIMIT 1
        """

        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (self.device_serial, customer_name)).fetchone()

        if not row:
            return None

        message_time = None
        raw_message_time = row["message_time"]
        if raw_message_time:
            try:
                message_time = datetime.fromisoformat(str(raw_message_time).replace("Z", "+00:00"))
            except Exception:
                message_time = None

        return ConversationInfo(
            customer_name=row["customer_name"],
            customer_channel=row["customer_channel"],
            customer_id=str(row["customer_id"]),
            last_message_id=str(row["message_id"]),
            last_message_time=message_time,
            last_message_sender="kefu" if row["is_from_kefu"] else "customer",
        )

    def _final_safety_check(
        self,
        attempt: FollowupAttempt,
    ) -> tuple[bool, str]:
        """
        Validate latest runtime state before sending.

        Returns:
            (can_send, reason)
        """
        from wecom_automation.services.blacklist_service import BlacklistChecker

        if BlacklistChecker.is_blacklisted(
            self.device_serial,
            attempt.customer_name,
            attempt.customer_channel,
            use_cache=False,
            fail_closed=True,
        ):
            return False, "blacklisted"

        latest = self._get_latest_conversation_info(attempt.customer_name)
        if latest is None:
            return False, "latest_state_unavailable"

        if latest.last_message_sender == "customer":
            return False, "customer_replied"

        if latest.last_message_id != attempt.last_kefu_message_id:
            return False, "conversation_changed"

        return True, "ok"

    # ==================== 状态检查 ====================

    def is_enabled(self) -> bool:
        """检查补刀功能是否启用"""
        return self._get_settings().followup_enabled

    def is_within_operating_hours(self) -> bool:
        """检查是否在工作时间内"""
        return self._get_settings_manager().is_within_operating_hours()

    def can_execute(self) -> tuple[bool, str]:
        """检查是否可以执行补刀"""
        settings = self._get_settings()

        if not settings.followup_enabled:
            return False, "Followup is disabled"

        if settings.enable_operating_hours:
            if not self.is_within_operating_hours():
                return False, f"Outside operating hours ({settings.start_hour} - {settings.end_hour})"

        return True, "OK"

    # ==================== 队列管理 ====================

    def process_conversations(
        self,
        conversations: list[ConversationInfo],
    ) -> dict[str, Any]:
        """
        处理对话列表，更新补刀队列

        Args:
            conversations: 对话信息列表

        Returns:
            处理结果统计
        """
        self._log("")
        self._log("┌" + "─" * 50 + "┐")
        self._log("│ 补刀队列: 处理对话列表                            │")
        self._log("└" + "─" * 50 + "┘")
        self._log(f"  输入对话数: {len(conversations)}")

        if not self.is_enabled():
            self._log("  ⚠️ 补刀功能未启用，跳过处理")
            return {"enabled": False, "added": 0, "removed": 0}

        settings = self._get_settings()
        repo = self._get_repository()

        idle_threshold = timedelta(minutes=settings.idle_threshold_minutes)
        max_attempts = settings.max_attempts_per_customer
        now = datetime.now()

        self._log("  补刀配置:")
        self._log(f"    - 空闲阈值: {settings.idle_threshold_minutes} 分钟")
        self._log(f"    - 最大补刀次数: {max_attempts}")
        self._log(f"    - 当前时间: {now.strftime('%H:%M:%S')}")

        added = 0
        removed = 0
        skipped_already_pending = 0
        skipped_conversation_continues = 0
        skipped_not_idle = 0
        skipped_blacklisted = 0

        self._log("")
        self._log("  处理每个对话:")

        for idx, conv in enumerate(conversations, 1):
            try:
                # 检查是否已在队列中
                existing = repo.get_by_customer(self.device_serial, conv.customer_name)
                existing_status = existing.status.value if existing else "无"

                self._log("")
                self._log(f"    [{idx}/{len(conversations)}] {conv.customer_name}")
                self._log(f"      - 最后消息发送方: {conv.last_message_sender}")
                self._log(f"      - 最后消息时间: {conv.last_message_time}")
                self._log(f"      - 队列状态: {existing_status}")

                if conv.last_message_sender == "customer":
                    # 客户发了新消息 → 移出队列
                    if existing and existing.status == AttemptStatus.PENDING:
                        repo.mark_customer_replied(self.device_serial, conv.customer_name)
                        self._log("      ✅ 客户已回复，移出补刀队列")
                        removed += 1
                    else:
                        self._log("      ⏭️ 客户消息，但不在待处理队列中")

                elif conv.last_message_sender == "kefu":
                    # Kefu 发的消息，检查是否超过阈值
                    if conv.last_message_time:
                        # 统一时区处理：将 offset-aware 转为 offset-naive
                        last_msg_time = conv.last_message_time
                        if hasattr(last_msg_time, "tzinfo") and last_msg_time.tzinfo is not None:
                            # 转换为本地时间并移除时区信息
                            last_msg_time = last_msg_time.replace(tzinfo=None)

                        time_since = now - last_msg_time
                        idle_minutes = int(time_since.total_seconds() / 60)
                        self._log(f"      - 空闲时长: {idle_minutes} 分钟")

                        if time_since >= idle_threshold:
                            self._log(f"      - 超过阈值 ({settings.idle_threshold_minutes}分钟)")

                            # 检查是否是新消息（不是之前的补刀消息）
                            if existing:
                                # 已存在，检查消息 ID 是否变化
                                if (
                                    existing.last_checked_message_id
                                    and existing.last_checked_message_id != conv.last_message_id
                                ):
                                    # 客户回复后 kefu 又发了消息（不应该触发补刀）
                                    self._log("      ⏭️ 对话继续中（消息ID变化），跳过")
                                    skipped_conversation_continues += 1
                                    continue

                                # 如果已经在队列中且是 pending，保持不变
                                if existing.status == AttemptStatus.PENDING:
                                    self._log("      ⏭️ 已在待处理队列中，保持不变")
                                    skipped_already_pending += 1
                                    continue

                            # 黑名单用户不进入补刀队列
                            try:
                                from wecom_automation.services.blacklist_service import BlacklistChecker

                                if BlacklistChecker.is_blacklisted(
                                    self.device_serial,
                                    conv.customer_name,
                                    conv.customer_channel,
                                    use_cache=False,
                                    fail_closed=True,
                                ):
                                    self._log("      ⛔ 黑名单用户，跳过入队")
                                    skipped_blacklisted += 1
                                    continue
                            except Exception as e:
                                self._log(f"      ⛔ 黑名单检查异常，安全跳过入队: {e}", "WARN")
                                skipped_blacklisted += 1
                                continue

                            # 加入队列
                            repo.add_or_update(
                                device_serial=self.device_serial,
                                customer_name=conv.customer_name,
                                last_kefu_message_id=conv.last_message_id,
                                last_kefu_message_time=conv.last_message_time,
                                max_attempts=max_attempts,
                                customer_id=conv.customer_id,
                                customer_channel=conv.customer_channel,
                            )
                            self._log(f"      ✅ 加入补刀队列 (空闲 {idle_minutes} 分钟)")
                            added += 1
                        else:
                            self._log(
                                f"      ⏭️ 未达到空闲阈值 ({idle_minutes} < {settings.idle_threshold_minutes}分钟)"
                            )
                            skipped_not_idle += 1
                    else:
                        self._log("      ⏭️ 无消息时间信息，跳过")

            except Exception as e:
                self._log(f"      ❌ 处理失败: {e}", "ERROR")
                import traceback

                self._log(f"      错误详情: {traceback.format_exc()}", "DEBUG")

        self._log("")
        self._log("  ┌────────────────────────────────────────────────┐")
        self._log("  │ 处理结果统计                                    │")
        self._log("  ├────────────────────────────────────────────────┤")
        self._log(f"  │  新增入队: {added:<36}│")
        self._log(f"  │  移出队列: {removed:<36}│")
        self._log(f"  │  已在队列(跳过): {skipped_already_pending:<29}│")
        self._log(f"  │  对话继续(跳过): {skipped_conversation_continues:<29}│")
        self._log(f"  │  未达阈值(跳过): {skipped_not_idle:<29}│")
        self._log(f"  │  黑名单(跳过): {skipped_blacklisted:<31}│")
        self._log("  └────────────────────────────────────────────────┘")

        return {
            "enabled": True,
            "added": added,
            "removed": removed,
            "threshold_minutes": settings.idle_threshold_minutes,
        }

    def check_and_update_queue(
        self,
        customer_name: str,
        current_last_message_id: str,
        current_sender: str,
    ) -> bool:
        """
        检查单个客户并更新队列状态

        Args:
            customer_name: 客户名称
            current_last_message_id: 当前最后消息 ID
            current_sender: 当前最后消息发送方 ("kefu" 或 "customer")

        Returns:
            是否需要继续补刀
        """
        repo = self._get_repository()
        existing = repo.get_by_customer(self.device_serial, customer_name)

        if not existing:
            return False

        if existing.status != AttemptStatus.PENDING:
            return False

        # 检查是否有新的客户消息
        if current_sender == "customer":
            # 客户回复了
            repo.mark_customer_replied(self.device_serial, customer_name)
            self._log(f"客户已回复: {customer_name}")
            return False

        # 检查消息 ID 是否变化（客户可能回复后 kefu 又发了）
        if (
            existing.last_checked_message_id
            and existing.last_checked_message_id != current_last_message_id
            and existing.last_kefu_message_id != current_last_message_id
        ):
            # 消息 ID 变化了，但不是补刀消息，可能是对话继续了
            self._log(f"对话继续中，暂不补刀: {customer_name}")
            return False

        return True

    # ==================== 执行补刀 ====================

    async def execute_pending_followups(
        self,
        skip_check: Callable[[], bool] | None = None,
        ai_reply_callback: Callable[[str, str], Awaitable[str | None]] | None = None,
    ) -> dict[str, Any]:
        """
        执行待补刀任务

        Args:
            skip_check: 中断检查函数
            ai_reply_callback: AI 回复回调 (customer_name, prompt) -> awaitable message

        Returns:
            执行结果统计
        """
        self._log("")
        self._log("╔" + "═" * 58 + "╗")
        self._log("║             执行待补刀任务                              ║")
        self._log("╚" + "═" * 58 + "╝")

        can_exec, reason = self.can_execute()
        self._log(f"  执行检查: can_exec={can_exec}, reason={reason}")

        if not can_exec:
            self._log(f"  ❌ 无法执行补刀: {reason}")
            return {"executed": False, "reason": reason}

        settings = self._get_settings()
        repo = self._get_repository()
        executor = self._get_executor()

        self._log("  补刀配置:")
        self._log(f"    - 最大补刀数/次: {settings.max_followups}")
        self._log(f"    - 使用AI回复: {settings.use_ai_reply}")
        self._log(f"    - AI回调: {'已提供' if ai_reply_callback else '未提供'}")
        self._log(f"    - 补刀间隔: {settings.attempt_intervals} 分钟")

        # 获取待补刀列表（传递间隔时间）
        self._log("  获取待补刀列表（考虑间隔时间）...")
        pending = repo.get_pending_attempts(
            self.device_serial,
            limit=settings.max_followups,
            attempt_intervals=settings.attempt_intervals,
        )

        if not pending:
            self._log("  ✅ 无待补刀任务")
            return {"executed": True, "count": 0, "reason": "No pending followups"}

        self._log(f"  找到 {len(pending)} 个待补刀目标:")
        for idx, attempt in enumerate(pending, 1):
            self._log(f"    {idx}. {attempt.customer_name} (第{attempt.current_attempt + 1}/{attempt.max_attempts}次)")

        # 确保连接设备
        self._log("")
        self._log("  连接设备...")
        if not await executor.connect():
            self._log("  ❌ 设备连接失败")
            return {"executed": False, "reason": "Device connection failed"}
        self._log("  ✅ 设备连接成功")

        results = {
            "executed": True,
            "total": len(pending),
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "skipped_blacklisted": 0,  # 新增：黑名单跳过计数
            "details": [],
        }

        try:
            # Defensive screen validation before follow-up execution
            # This is critical after skip operations which may leave us on wrong screen
            # Skip operation may not navigate back properly in some edge cases
            self._log("  🔍 Validating current screen before follow-up...")
            try:
                wecom = self._get_wecom()
                screen = await wecom.get_current_screen()
                self._log(f"     Current screen: {screen}", "DEBUG")

                # Only navigate back if NOT on main page (private_chats list)
                # This handles edge cases: "chat", "other", "unknown", None
                if screen not in ["private_chats"]:
                    self._log(f"  ⚠️ Wrong screen detected: {screen}, navigating back to main page...", "WARN")
                    await wecom.go_back()
                    await asyncio.sleep(0.5)
                    self._log("     ✅ Navigated to main page")
                else:
                    self._log("     ✅ Already on main page (private_chats)")
            except Exception as screen_err:
                # If screen detection fails, defensively try to go back
                self._log(f"  ⚠️ Screen detection failed: {screen_err}, attempting defensive go_back...", "WARN")
                try:
                    await self._get_wecom().go_back()
                    await asyncio.sleep(0.5)
                    self._log("     ✅ Defensive go_back completed")
                except Exception as go_back_err:
                    self._log(f"     ⚠️ Defensive go_back failed: {go_back_err}", "WARN")

            self._log("")
            self._log("  " + "─" * 56)
            self._log("  开始执行补刀任务")
            self._log("  " + "─" * 56)

            for idx, attempt in enumerate(pending, 1):
                self._log("")
                self._log(f"  ┌{'─' * 54}┐")
                self._log(f"  │ [{idx}/{len(pending)}] {attempt.customer_name[:40]:<42}│")
                self._log(f"  │   补刀次数: 第 {attempt.current_attempt + 1}/{attempt.max_attempts} 次{' ' * 30}│")
                self._log(f"  └{'─' * 54}┘")

                # 检查是否需要中断
                if skip_check and skip_check():
                    self._log("  ⛔ 收到中断信号，停止补刀")
                    remaining = len(pending) - results["success"] - results["failed"] - results["skipped"]
                    results["skipped"] += remaining
                    self._log(f"  标记剩余 {remaining} 个为跳过状态")
                    break

                # ✅ 执行前再次检查黑名单
                self._log("  🔍 检查黑名单状态...")
                try:
                    from wecom_automation.services.blacklist_service import BlacklistChecker

                    if BlacklistChecker.is_blacklisted(
                        self.device_serial,
                        attempt.customer_name,
                        attempt.customer_channel,  # 修复: 使用 customer_channel 而非 customer_id
                        use_cache=False,  # 不使用缓存，确保实时性
                        fail_closed=True,
                    ):
                        self._log("  ⛔ 黑名单用户，跳过补刀")
                        results["skipped"] += 1
                        results["skipped_blacklisted"] += 1

                        # 可选：将记录标记为 cancelled
                        try:
                            repo.update_status(attempt.id, AttemptStatus.CANCELLED)
                            self._log("     已将补刀记录标记为 cancelled")
                        except Exception as cancel_err:
                            self._log(f"     ⚠️ 标记 cancelled 失败: {cancel_err}", "DEBUG")

                        results["details"].append(
                            {
                                "customer": attempt.customer_name,
                                "status": "skipped_blacklisted",
                                "error": "User is in blacklist",
                                "duration_ms": 0,
                            }
                        )
                        continue
                except Exception as e:
                    self._log(f"  ⛔ 黑名单检查异常，安全跳过补刀: {e}", "WARN")
                    results["skipped"] += 1
                    results["skipped_blacklisted"] += 1
                    try:
                        repo.update_status(attempt.id, AttemptStatus.CANCELLED)
                    except Exception as cancel_err:
                        self._log(f"     ⚠️ 标记 cancelled 失败: {cancel_err}", "DEBUG")
                    results["details"].append(
                        {
                            "customer": attempt.customer_name,
                            "status": "skipped_blacklist_check_failed",
                            "error": str(e),
                            "duration_ms": 0,
                        }
                    )
                    continue

                self._log("  🔍 校验最新会话状态...")
                try:
                    can_send, reason = self._final_safety_check(attempt)
                except Exception as e:
                    can_send, reason = False, f"safety_check_failed:{e}"

                if not can_send:
                    results["skipped"] += 1
                    self._log(f"  ⛔ 最终校验未通过，跳过补刀: {reason}", "WARN")
                    try:
                        if reason == "customer_replied":
                            repo.mark_customer_replied(self.device_serial, attempt.customer_name)
                            self._log("     已标记客户已回复")
                        else:
                            repo.update_status(attempt.id, AttemptStatus.CANCELLED)
                            self._log("     已将补刀记录标记为 cancelled")
                    except Exception as state_err:
                        self._log(f"     ⚠️ 更新补刀状态失败: {state_err}", "DEBUG")

                    detail_status = "skipped_customer_replied" if reason == "customer_replied" else "skipped_state_changed"
                    results["details"].append(
                        {
                            "customer": attempt.customer_name,
                            "status": detail_status,
                            "error": reason,
                            "duration_ms": 0,
                        }
                    )
                    continue

                self._log("  📝 生成补刀消息...")

                # 生成消息内容
                message = await self._generate_message(
                    attempt.customer_name,
                    settings,
                    ai_reply_callback,
                )
                self._log(f"  消息内容: {message[:50]}{'...' if len(message) > 50 else ''}")

                # 执行补刀
                self._log("  🚀 执行补刀...")
                result = await executor.execute(
                    attempt.customer_name,
                    message,
                    skip_check,
                )

                # 更新数据库
                if result.status == FollowupStatus.SUCCESS:
                    # 补刀成功，更新记录
                    new_message_id = f"followup_{datetime.now().isoformat()}"
                    repo.record_followup_sent(attempt.id, new_message_id)
                    results["success"] += 1
                    self._log(f"  ✅ 补刀成功 (耗时: {result.duration_ms}ms)")
                    self._log(f"     更新数据库: attempt_id={attempt.id}, message_id={new_message_id[:30]}...")

                    # 记录发送的模板（用于去重）
                    if settings.avoid_duplicate_messages and not settings.use_ai_reply:
                        try:
                            from .sent_messages_repository import FollowupSentMessagesRepository

                            sent_repo = FollowupSentMessagesRepository(self._db_path)
                            sent_repo.record_sent_message(self.device_serial, attempt.customer_name, message)
                            self._log(f"     已记录发送模板用于去重: {message[:50]}...")
                        except Exception as e:
                            self._log(f"     ⚠️ 记录发送模板失败（不影响）: {e}", "WARN")

                elif result.status == FollowupStatus.SKIPPED:
                    results["skipped"] += 1
                    self._log(f"  ⏭️ 已跳过: {result.error or '无原因'}")

                else:
                    results["failed"] += 1
                    self._log(f"  ❌ 补刀失败: {result.error}", "ERROR")

                results["details"].append(
                    {
                        "customer": attempt.customer_name,
                        "status": result.status.value,
                        "error": result.error,
                        "duration_ms": result.duration_ms,
                    }
                )

                # 补刀之间稍作等待
                if idx < len(pending):
                    self._log("  等待 1s 后处理下一个...")
                    await asyncio.sleep(1)

        except Exception as e:
            self._log(f"  ❌ 执行过程中出错: {e}", "ERROR")
            import traceback

            self._log(f"  错误详情: {traceback.format_exc()}", "DEBUG")

        finally:
            self._log("")
            self._log("  断开设备连接...")
            await executor.disconnect()

        self._log("")
        self._log("╔" + "═" * 58 + "╗")
        self._log("║             补刀任务执行完成                            ║")
        self._log("╠" + "═" * 58 + "╣")
        self._log(f"║  总计: {results['total']:<50}║")
        self._log(f"║  成功: {results['success']:<50}║")
        self._log(f"║  失败: {results['failed']:<50}║")
        self._log(f"║  跳过: {results['skipped']:<50}║")
        if results.get("skipped_blacklisted", 0) > 0:
            self._log(f"║    - 其中黑名单用户: {results['skipped_blacklisted']:<39}║")
        success_rate = (results["success"] / results["total"] * 100) if results["total"] > 0 else 0
        self._log(f"║  成功率: {success_rate:.1f}%{' ' * (47 - len(f'{success_rate:.1f}%'))}║")
        self._log("╚" + "═" * 58 + "╝")

        return results

    async def _generate_message(
        self,
        customer_name: str,
        settings: FollowUpSettings,
        ai_reply_callback: Callable[[str, str], Awaitable[str | None]] | None = None,
    ) -> str:
        """
        生成补刀消息

        如果启用 AI 回复，使用 AI 生成（拼接 followup_prompt）
        否则从模板随机选择（可选择启用去重功能）
        """
        self._log("  消息生成:")
        self._log(f"    - 客户: {customer_name}")
        self._log(f"    - use_ai_reply: {settings.use_ai_reply}")
        self._log(f"    - avoid_duplicate_messages: {getattr(settings, 'avoid_duplicate_messages', False)}")
        self._log(f"    - ai_callback: {'已提供' if ai_reply_callback else '未提供'}")

        if settings.use_ai_reply and ai_reply_callback:
            try:
                # 使用 AI 生成
                prompt = settings.followup_prompt or "请生成一条友好的跟进消息"
                self._log(f"    - AI提示词: {prompt[:40]}...")
                self._log("    调用 AI 生成消息...")

                message = await ai_reply_callback(customer_name, prompt)
                if message:
                    self._log(f"    ✅ AI 生成成功: {message[:50]}...")
                    return message
                else:
                    self._log("    ⚠️ AI 返回空消息，回退到模板", "WARN")
            except Exception as e:
                self._log(f"    ❌ AI 生成消息失败: {e}", "WARN")
                import traceback

                self._log(f"    错误详情: {traceback.format_exc()}", "DEBUG")

        # 模板路径
        templates = settings.message_templates or []
        self._log(f"    可用模板数: {len(templates)}")

        if not templates:
            default_msg = "你好，请问考虑得怎么样了？"
            self._log(f"    ⚠️ 无可用模板，使用默认消息: {default_msg}")
            return default_msg

        # 检查是否启用去重功能
        if getattr(settings, "avoid_duplicate_messages", False):
            return await self._generate_unique_message(customer_name, templates)

        # 从模板随机选择（原始行为）
        message = random.choice(templates)
        self._log(f"    ✅ 使用模板消息: {message[:50]}...")
        return message

    async def _generate_unique_message(
        self,
        customer_name: str,
        templates: list[str],
    ) -> str:
        """
        生成不重复的消息模板

        查询已发送的模板，过滤后从剩余模板中随机选择

        Args:
            customer_name: 客户名称
            templates: 所有可用模板

        Returns:
            选择的模板消息
        """
        try:
            from .sent_messages_repository import FollowupSentMessagesRepository

            sent_repo = FollowupSentMessagesRepository(self._db_path)
            sent_templates = sent_repo.get_sent_templates(self.device_serial, customer_name)

            # 过滤掉已发送的模板
            available = [t for t in templates if t not in sent_templates]

            self._log(f"    去重选择:")
            self._log(f"      - 总模板数: {len(templates)}")
            self._log(f"      - 已发送: {len(sent_templates)}")
            self._log(f"      - 可用: {len(available)}")

            # 理论上不应该为空（>=3模板，最多3次补刀）
            # 但添加防御性检查
            if not available:
                self._log(f"      ⚠️ 意外：所有模板已用完（不应该发生）", "WARN")
                return templates[0]

            # 从可用模板中随机选择
            message = random.choice(available)
            self._log(f"      ✅ 选择新模板: {message[:50]}...")
            return message

        except Exception as e:
            # 出错时回退到随机选择
            self._log(f"      ❌ 去重选择失败: {e}, 回退到随机选择", "WARN")
            import traceback

            self._log(f"      错误详情: {traceback.format_exc()}", "DEBUG")
            return random.choice(templates)

    # ==================== 统计和查询 ====================

    def get_pending_count(self) -> int:
        """获取待补刀数量"""
        pending = self._get_repository().get_pending_attempts(self.device_serial)
        return len(pending)

    def get_statistics(self) -> dict[str, Any]:
        """获取统计信息"""
        return self._get_repository().get_statistics(self.device_serial)

    def get_pending_list(self, limit: int = 50) -> list[FollowupAttempt]:
        """获取待补刀列表"""
        return self._get_repository().get_pending_attempts(self.device_serial, limit)


# ==================== 工厂函数 ====================

_queue_managers: dict[str, FollowupQueueManager] = {}


def get_followup_queue_manager(
    device_serial: str,
    adb: AdbTools | None = None,
    db_path: str | None = None,
    log_callback: Callable[[str, str], None] | None = None,
) -> FollowupQueueManager:
    """获取指定设备的补刀队列管理器"""
    if device_serial not in _queue_managers:
        _queue_managers[device_serial] = FollowupQueueManager(
            device_serial=device_serial,
            adb=adb,
            db_path=db_path,
            log_callback=log_callback,
        )
    return _queue_managers[device_serial]


def clear_followup_queue_manager(device_serial: str):
    """清除指定设备的队列管理器"""
    if device_serial in _queue_managers:
        del _queue_managers[device_serial]
