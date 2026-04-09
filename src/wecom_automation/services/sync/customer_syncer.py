"""
客户同步器

负责同步单个客户的完整对话，支持交互式等待回复。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from wecom_automation.core.exceptions import SkipUserException, is_device_disconnected_error
from wecom_automation.core.interfaces import (
    CustomerSyncResult,
    IAIReplyService,
    MessageContext,
    SyncOptions,
)
from wecom_automation.database.repository import ConversationRepository
from wecom_automation.services.message.processor import MessageProcessor
from wecom_automation.services.user.avatar import AvatarManager
from wecom_automation.utils.timing import HumanTiming

# Import MetricsLogger for business metrics
try:
    from wecom_automation.core.metrics_logger import get_metrics_logger

    HAS_METRICS = True
except ImportError:
    HAS_METRICS = False


class CustomerSyncer:
    """
    客户同步器

    负责同步单个客户的完整对话，包括:
    - 进入客户对话
    - 提取历史消息
    - 处理各类消息（文本、图片、语音、视频）
    - 处理头像
    - 交互式等待回复（发送消息后等待客户回复，有回复继续聊）

    Usage:
        syncer = CustomerSyncer(
            wecom_service=wecom,
            repository=repo,
            message_processor=processor
        )

        result = await syncer.sync(user, options, kefu_id, device_serial)
    """

    def __init__(
        self,
        wecom_service,
        repository: ConversationRepository,
        message_processor: MessageProcessor,
        avatar_manager: AvatarManager | None = None,
        ai_service: IAIReplyService | None = None,
        timing: HumanTiming | None = None,
        logger: logging.Logger | None = None,
    ):
        """
        初始化客户同步器

        Args:
            wecom_service: WeComService实例
            repository: 数据库仓库
            message_processor: 消息处理器
            avatar_manager: 头像管理器（可选）
            ai_service: AI回复服务（可选）
            timing: 延迟模拟器（可选）
            logger: 日志记录器
        """
        self._wecom = wecom_service
        self._repository = repository
        self._message_processor = message_processor
        self._avatar_manager = avatar_manager
        self._ai_service = ai_service
        self._timing = timing or HumanTiming()
        self._logger = logger or logging.getLogger(__name__)

        # 当前同步上下文
        self._current_kefu_name: str = ""

        # 可选的 Sidecar 客户端
        self._sidecar_client = None

        # Metrics logger (lazy init)
        self._metrics = None

    def set_kefu_name(self, name: str) -> None:
        """设置当前客服名称"""
        self._current_kefu_name = name

    def set_ai_service(self, ai_service) -> None:
        """设置 AI 回复服务"""
        self._ai_service = ai_service
        self._logger.info("AI service configured")

    def set_sidecar_client(self, client) -> None:
        """设置 Sidecar 客户端"""
        self._sidecar_client = client
        self._logger.info("Sidecar client configured")

        # Set up cancel checker on wecom_service for Skip support during long operations
        if client and hasattr(self._wecom, "set_cancel_checker"):

            async def check_skip():
                """Check if skip was requested via sidecar queue."""
                if await client.is_skip_requested():
                    self._logger.info("⏭️ Skip requested - interrupting operation")
                    raise SkipUserException("Skip requested via sidecar")

            self._wecom.set_cancel_checker(check_skip)
            self._logger.debug("Cancel checker configured on wecom_service")

    async def sync(
        self,
        user: Any,
        options: SyncOptions,
        kefu_id: int,
        device_serial: str,
    ) -> CustomerSyncResult:
        """
        同步单个客户的对话（支持交互式等待）

        流程:
        1. 进入对话，提取历史消息，存储
        2. 如果最后一条消息是客户发的，发送回复
        3. 等待 interactive_wait_timeout 秒检测新消息
        4. 如果有新客户消息，处理并回复，继续等待
        5. 如果超时无新消息，退出对话

        Args:
            user: 用户信息对象
            options: 同步选项
            kefu_id: 客服数据库ID
            device_serial: 设备序列号

        Returns:
            CustomerSyncResult: 同步结果
        """
        # Initialize metrics logger
        if HAS_METRICS and self._metrics is None:
            self._metrics = get_metrics_logger(device_serial)

        start_time = time.time()
        result = CustomerSyncResult(success=True)
        user_name = getattr(user, "name", str(user))
        user_channel = getattr(user, "channel", None)

        self._logger.info(f"Syncing customer: {user_name}")

        try:
            # 1. 获取或创建客户记录
            customer = self._repository.get_or_create_customer(
                name=user_name,
                kefu_id=kefu_id,
                channel=user_channel,
            )
            if getattr(user, "is_new_friend", False):
                self._repository.mark_customer_friend_added(customer.id)
                refreshed_customer = self._repository.get_customer_by_id(customer.id)
                if refreshed_customer is not None:
                    customer = refreshed_customer

            # 2. 进入对话（头像会在点击用户前捕获，此时用户在可见区域）
            if not await self._enter_conversation(user_name, user_channel):
                self._logger.warning(f"Failed to enter conversation with {user_name}")
                result.success = False
                result.error = "Failed to enter conversation"
                return result

            # 3. 提取历史消息
            messages = await self._extract_messages()

            # 4. 创建消息上下文
            context = MessageContext(
                customer_id=customer.id,
                customer_name=user_name,
                channel=user_channel,
                kefu_name=self._current_kefu_name,
                device_serial=device_serial,
            )

            # 5. 处理每条消息
            for msg in messages:
                try:
                    # ========== 检测用户删除消息 ==========
                    msg_type = getattr(msg, "message_type", "text")
                    msg_content = getattr(msg, "content", "") or ""

                    if msg_type == "system" and self._wecom.ui_parser.is_user_deleted_message(msg_content):
                        self._logger.warning(f"🚫 Detected user deletion message: {msg_content}")

                        # Log user deletion
                        if HAS_METRICS and self._metrics:
                            self._metrics.log_user_deleted(
                                customer_db_id=customer.id,
                                customer_name=user_name,
                                channel=user_channel,
                                detected_message=msg_content,
                            )

                        # 导入黑名单服务并加入黑名单
                        from wecom_automation.services.blacklist_service import BlacklistWriter

                        writer = BlacklistWriter()
                        writer.add_to_blacklist(
                            device_serial=device_serial,
                            customer_name=user_name,
                            customer_channel=user_channel,
                            reason="User deleted/blocked",
                            deleted_by_user=True,
                            customer_db_id=customer.id,
                        )
                        self._logger.info(f"✅ Automatically added {user_name} to blacklist")

                        # 仍然存储这条系统消息（用于记录）
                        process_result = await self._message_processor.process(msg, context)
                        if process_result.added:
                            result.messages_added += 1

                        # 标记为用户被删除，退出对话
                        result.user_deleted = True
                        await self._exit_conversation()
                        return result
                    # ========== 检测结束 ==========

                    process_result = await self._message_processor.process(msg, context)

                    if process_result.added:
                        result.messages_added += 1
                    else:
                        result.messages_skipped += 1

                    # Log message processing
                    if HAS_METRICS and self._metrics:
                        processing_time = (time.time() - start_time) * 1000
                        sender = "kefu" if getattr(msg, "is_self", False) else "customer"
                        msg_type = getattr(msg, "message_type", "text")

                        self._metrics.log_message_processed(
                            customer_db_id=customer.id,
                            customer_name=user_name,
                            message_db_id=getattr(process_result, "message_db_id", 0),
                            message_type=msg_type,
                            sender=sender,
                            added=process_result.added,
                            processing_duration_ms=processing_time,
                            ai_generated=False,
                            ai_reply_length=0,
                            reply_sent_success=False,
                        )

                    # 统计媒体类型
                    if process_result.message_type == "image":
                        result.images_saved += 1
                    elif process_result.message_type == "video":
                        result.videos_saved += 1
                    elif process_result.message_type == "voice":
                        result.voice_count += 1

                except Exception as e:
                    self._logger.warning(f"Failed to process message: {e}")

            result.messages_count = len(messages)

            # 6. 交互式等待回复循环
            if options.send_test_messages:
                await self._interactive_reply_loop(
                    customer=customer,
                    context=context,
                    messages=messages,
                    options=options,
                    result=result,
                )

            # 7. 退出对话
            await self._exit_conversation()

            self._logger.info(
                f"✅ Synced {user_name}: {result.messages_added} added, {result.messages_skipped} skipped"
            )

            # Log customer updated
            if HAS_METRICS and self._metrics:
                latest_customer = self._repository.get_customer_by_id(customer.id) or customer
                derived_tags = []
                if latest_customer.friend_added_at:
                    derived_tags.append("friend_added")
                if latest_customer.has_customer_media:
                    derived_tags.extend(["sent_media", "sent_photo_or_video"])
                self._metrics.log_customer_updated(
                    customer_db_id=customer.id,
                    customer_name=user_name,
                    channel=user_channel,
                    message_count=result.messages_added,
                    ai_reply_count=result.replies_sent,
                    is_blacklisted=False,
                    is_deleted=result.user_deleted,
                    friend_added_at=latest_customer.friend_added_at,
                    first_customer_media_at=latest_customer.first_customer_media_at,
                    has_customer_media=latest_customer.has_customer_media,
                    derived_tags=derived_tags,
                )

        except SkipUserException:
            self._logger.info(f"⏭️ Skipping user {user_name} by request")
            result.skipped = True  # Mark as skipped
            try:
                await self._exit_conversation()
            except Exception:
                pass

            # Clear the skip flag after handling, ready for next user
            if self._sidecar_client:
                try:
                    await self._sidecar_client.clear_skip_flag()
                    self._logger.debug("Skip flag cleared after skip")
                except Exception as e:
                    self._logger.debug(f"Failed to clear skip flag: {e}")

            return result

        except Exception as e:
            result.success = False
            result.error = str(e)
            self._logger.error(f"Failed to sync {user_name}: {e}")

            # 检测设备断开 - 重新抛出异常让上层处理
            if is_device_disconnected_error(e):
                self._logger.error(f"🔌 Device disconnected while syncing {user_name}")
                raise  # 重新抛出，让 orchestrator 处理

            # 尝试恢复到列表页（仅在设备未断开时）
            try:
                await self._exit_conversation()
            except Exception as exit_err:
                # 退出时也检测设备断开
                if is_device_disconnected_error(exit_err):
                    self._logger.error("🔌 Device disconnected while exiting conversation")
                    raise exit_err

        return result

    # =========================================================================
    # 交互式等待回复
    # =========================================================================

    async def _interactive_reply_loop(
        self,
        customer: Any,
        context: MessageContext,
        messages: list[Any],
        options: SyncOptions,
        result: CustomerSyncResult,
    ) -> None:
        """
        交互式回复循环

        1. 检查最后一条消息是否是客户发的，如果是则回复
        2. 等待新消息，如果有新客户消息则处理并回复
        3. 超时无新消息则退出
        """
        timeout = options.interactive_wait_timeout
        max_rounds = options.max_interaction_rounds

        self._logger.info(f"⏳ Entering interactive mode (timeout={timeout}s, max_rounds={max_rounds})")

        # 获取最后一条消息的签名
        last_seen_signature = None
        if messages:
            last_seen_signature = self._get_message_signature(messages[-1])

        # 检查最后一条消息是否需要回复
        last_customer_msg = None
        if messages:
            for msg in reversed(messages):
                if not getattr(msg, "is_self", True):
                    last_customer_msg = msg
                    break

        # 发送初始回复
        if last_customer_msg:
            reply_sent = await self._send_reply_to_customer(last_customer_msg, customer, context)
            if reply_sent:
                result.replies_sent += 1
                # 更新签名为发送后的状态（只获取可见消息，不滚动）
                await asyncio.sleep(1)
                new_messages = await self._extract_visible_messages()
                if new_messages:
                    last_seen_signature = self._get_message_signature(new_messages[-1])

        # 交互等待循环
        round_count = 0
        while round_count < max_rounds:
            round_count += 1

            # Check for skip request each round
            if self._sidecar_client:
                if await self._sidecar_client.is_skip_requested():
                    self._logger.info("⏭️ Skip requested during interactive loop")
                    raise SkipUserException("Skip requested via sidecar")

            # 等待新的客户消息
            has_new, new_messages = await self._wait_for_new_customer_messages(
                last_seen_signature=last_seen_signature,
                timeout=timeout,
                poll_interval=3.0,
            )

            if not has_new:
                # 超时，退出循环
                self._logger.info(f"⏰ No new customer messages after {timeout}s, exiting")
                break

            # 处理新消息
            self._logger.info(f"📨 Round {round_count}: Processing {len(new_messages)} new messages")

            last_customer_msg = None
            for msg in new_messages:
                try:
                    process_result = await self._message_processor.process(msg, context)
                    if process_result.added:
                        result.messages_added += 1
                    else:
                        result.messages_skipped += 1

                    # 记录最后一条客户消息
                    if not getattr(msg, "is_self", True):
                        last_customer_msg = msg

                except Exception as e:
                    self._logger.warning(f"Failed to process new message: {e}")

            # 回复最后一条客户消息
            if last_customer_msg:
                reply_sent = await self._send_reply_to_customer(last_customer_msg, customer, context)
                if reply_sent:
                    result.replies_sent += 1
                    # 更新签名（只获取可见消息，不滚动）
                    await asyncio.sleep(1)
                    current_msgs = await self._extract_visible_messages()
                    if current_msgs:
                        last_seen_signature = self._get_message_signature(current_msgs[-1])
            else:
                # 更新签名
                if new_messages:
                    last_seen_signature = self._get_message_signature(new_messages[-1])

        if round_count >= max_rounds:
            self._logger.warning(f"⚠️ Reached max interaction rounds ({max_rounds})")

    def _get_message_signature(self, msg: Any) -> str:
        """生成消息签名用于去重检测"""
        is_self = getattr(msg, "is_self", False)
        msg_type = getattr(msg, "message_type", "text")
        content = (getattr(msg, "content", "") or "")[:50]
        timestamp = getattr(msg, "timestamp", "") or ""
        return f"{is_self}|{msg_type}|{content}|{timestamp}"

    async def _wait_for_new_customer_messages(
        self,
        last_seen_signature: str | None,
        timeout: float = 40.0,
        poll_interval: float = 3.0,
    ) -> tuple[bool, list[Any]]:
        """
        等待新的客户消息

        只检测客户发的消息（is_self=False），忽略自己发的消息。

        Args:
            last_seen_signature: 最后看到的消息签名
            timeout: 超时时间（秒）
            poll_interval: 轮询间隔（秒）

        Returns:
            (是否有新客户消息, 所有新消息列表)
        """
        start_time = time.time()

        self._logger.debug(f"Waiting for customer messages (timeout={timeout}s)")

        while (time.time() - start_time) < timeout:
            elapsed = time.time() - start_time

            # Check for skip request each poll
            if self._sidecar_client:
                if await self._sidecar_client.is_skip_requested():
                    self._logger.info("⏭️ Skip requested during wait")
                    raise SkipUserException("Skip requested via sidecar")

            # 提取当前可见消息（不滚动）
            current_messages = await self._extract_visible_messages()

            if not current_messages:
                await asyncio.sleep(poll_interval)
                continue

            # 找出新消息
            new_messages = []
            found_last_seen = False

            if last_seen_signature is None:
                new_messages = current_messages
                found_last_seen = True
            else:
                for msg in current_messages:
                    msg_sig = self._get_message_signature(msg)
                    if found_last_seen:
                        new_messages.append(msg)
                    elif msg_sig == last_seen_signature:
                        found_last_seen = True

                # 如果没找到签名，可能是消息已滚出屏幕
                if not found_last_seen and current_messages:
                    last_sig = self._get_message_signature(current_messages[-1])
                    if last_sig != last_seen_signature:
                        new_messages = current_messages[-3:]

            # 只检测客户消息
            customer_messages = [m for m in new_messages if not getattr(m, "is_self", True)]

            if customer_messages:
                self._logger.debug(f"Found {len(customer_messages)} new customer message(s) after {elapsed:.1f}s")
                return True, new_messages

            # 每10秒打印一次进度
            if int(elapsed) % 10 == 0 and int(elapsed) > 0:
                remaining = int(timeout - elapsed)
                self._logger.debug(f"Still waiting... {remaining}s remaining")

            await asyncio.sleep(poll_interval)

        self._logger.debug(f"Timeout after {timeout}s - no new customer messages")
        return False, []

    async def _send_reply_to_customer(
        self,
        customer_msg: Any,
        customer: Any,
        context: MessageContext,
    ) -> bool:
        """
        回复客户消息

        Args:
            customer_msg: 客户的消息
            customer: 客户记录
            context: 消息上下文

        Returns:
            是否发送成功
        """
        try:
            message_type = getattr(customer_msg, "message_type", "text")
            message_content = getattr(customer_msg, "content", "") or ""

            # 处理非文本消息类型（图片、视频）
            if not message_content:
                if message_type == "image":
                    message_content = "[客户发送了一张图片]"
                    self._logger.debug("Image message detected, generating AI reply")
                elif message_type == "video":
                    message_content = "[客户发送了一个视频]"
                    self._logger.debug("Video message detected, generating AI reply")
                else:
                    self._logger.debug(f"Empty message (type={message_type}), skipping reply")
                    return False

            # 生成回复
            final_message = f"收到您的消息: {message_content[:20]}..."

            # 如果有AI服务，获取AI回复
            if self._ai_service:
                history = self._get_conversation_history(customer.id)
                try:
                    ai_reply = await self._ai_service.get_reply(message_content, context, history)
                    if ai_reply:
                        if self._ai_service.is_human_request(ai_reply):
                            self._logger.warning(f"🙋 User {context.customer_name} requested human agent")
                            return False
                        final_message = ai_reply
                        self._logger.info(f"[AI] Reply: {final_message[:50]}...")
                except Exception as e:
                    self._logger.warning(f"AI reply failed: {e}")

            # 发送消息
            success = False
            sent_message = final_message  # 默认使用原始消息

            if self._sidecar_client:
                success, sent_message = await self._send_via_sidecar(final_message, context)
            elif hasattr(self._wecom, "send_message"):
                success, _ = await self._wecom.send_message(final_message)

            # 将发送的消息写入数据库（使用实际发送的消息，可能被用户编辑过）
            if success:
                await self._store_sent_message(sent_message, context)

            return success

        except Exception as e:
            if isinstance(e, SkipUserException):
                raise
            self._logger.error(f"Failed to send reply: {e}")
            return False

    async def _store_sent_message(
        self,
        message_content: str,
        context: MessageContext,
    ) -> None:
        """
        将客服发送的消息写入数据库

        Args:
            message_content: 消息内容
            context: 消息上下文
        """
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            from wecom_automation.database.models import MessageRecord, MessageType

            # 获取当前时间（带时区，与 TimestampParser 一致）
            tz = ZoneInfo("Asia/Shanghai")
            now = datetime.now(tz)
            timestamp_raw = now.strftime("%H:%M")  # 格式: 14:30

            record = MessageRecord(
                customer_id=context.customer_id,
                content=message_content,
                message_type=MessageType.TEXT,
                is_from_kefu=True,  # 客服发送的消息
                timestamp_raw=timestamp_raw,
                timestamp_parsed=now,  # 带时区的时间戳，格式: 2025-12-28 17:40:00+08:00
            )

            added, _ = self._repository.add_message_if_not_exists(record)
            if added:
                self._logger.debug(f"💾 Stored sent message: {message_content[:30]}...")

        except Exception as e:
            self._logger.warning(f"Failed to store sent message: {e}")

    # =========================================================================
    # 辅助方法
    # =========================================================================

    async def _try_capture_avatar(self, name: str) -> None:
        """尝试捕获头像"""
        if not self._avatar_manager:
            self._logger.warning(f"[avatar] avatar_manager is None, skipping capture for {name}")
            return

        self._logger.info(f"[avatar] 🎯 Calling capture_if_needed for: {name}")
        try:
            await self._avatar_manager.capture_if_needed(name)
        except Exception as e:
            self._logger.warning(f"[avatar] Capture failed for {name}: {e}")

    async def _enter_conversation(self, user_name: str, channel: str = None) -> bool:
        """
        进入用户对话

        在点击用户之前会先尝试捕获头像（此时用户在可见区域）
        """
        success = False
        if hasattr(self._wecom, "click_user_in_list"):
            # 使用 pre_click_callback 在点击前捕获头像
            # 这样头像捕获时用户一定在屏幕可见区域
            success = await self._wecom.click_user_in_list(
                user_name, channel, pre_click_callback=self._try_capture_avatar if self._avatar_manager else None
            )
        elif hasattr(self._wecom, "tap_on_user"):
            # 旧方法不支持回调，先捕获头像
            if self._avatar_manager:
                await self._try_capture_avatar(user_name)
            success = await self._wecom.tap_on_user(user_name)

        await self._human_delay("tap")
        return success

    async def _extract_messages(self, with_scroll: bool = True) -> list[Any]:
        """
        提取对话消息

        Args:
            with_scroll: 是否滚动获取全部消息（初次进入时True，检测新消息时False）
        """
        if with_scroll:
            # 完整提取：滚动到顶部，再滚动下来获取全部消息
            if hasattr(self._wecom, "extract_conversation_messages"):
                result = await self._wecom.extract_conversation_messages()
                if hasattr(result, "messages"):
                    return result.messages
                return result if isinstance(result, list) else []
            elif hasattr(self._wecom, "get_messages"):
                return await self._wecom.get_messages()
        else:
            # 快速提取：只获取当前屏幕可见的消息（不滚动）
            return await self._extract_visible_messages()
        return []

    async def _extract_visible_messages(self) -> list[Any]:
        """
        提取当前屏幕可见的消息（不滚动）

        用于交互式等待循环中检测新消息。
        """
        try:
            # 获取当前 UI 树
            tree = None
            if hasattr(self._wecom, "adb") and hasattr(self._wecom.adb, "get_ui_tree"):
                tree = await self._wecom.adb.get_ui_tree()
            elif hasattr(self._wecom, "get_ui_tree"):
                tree = await self._wecom.get_ui_tree()

            if not tree:
                return []

            # 直接从 UI 树解析消息（不滚动）
            if hasattr(self._wecom, "ui_parser") and hasattr(self._wecom.ui_parser, "extract_conversation_messages"):
                return self._wecom.ui_parser.extract_conversation_messages(tree)

            return []
        except Exception as e:
            self._logger.warning(f"Failed to extract visible messages: {e}")
            return []

    async def _exit_conversation(self) -> None:
        """退出对话，返回列表"""
        if hasattr(self._wecom, "go_back"):
            await self._wecom.go_back()
        elif hasattr(self._wecom, "press_back"):
            await self._wecom.press_back()

        await self._human_delay("tap")

    async def _send_via_sidecar(self, message: str, context: MessageContext) -> tuple[bool, str]:
        """
        通过 Sidecar 发送消息

        Returns:
            (success, actual_message): 发送是否成功，以及实际发送的消息（可能被用户编辑过）
        """
        if not self._sidecar_client:
            return False, message

        try:
            self._logger.info(f"📡 Routing message to sidecar: {message[:50]}...")

            msg_id = await self._sidecar_client.add_message(
                customer_name=context.customer_name,
                channel=context.channel,
                message=message,
            )

            if not msg_id:
                self._logger.error("Failed to add message to sidecar queue")
                return False, message

            if not await self._sidecar_client.set_message_ready(msg_id):
                self._logger.error("Failed to mark message as ready")
                return False, message

            self._logger.info(f"Message queued (ID: {msg_id}), waiting for send...")

            result = await self._sidecar_client.wait_for_send(msg_id, timeout=300.0)

            reason = result.get("reason", "unknown")
            if result.get("success") or reason == "sent":
                # 获取实际发送的消息（可能被用户编辑过）
                actual_message = result.get("message", message)
                self._logger.info("✅ Message sent via sidecar")
                return True, actual_message
            elif reason == "cancelled":
                self._logger.info("⏭️ Sync skip requested by user")
                raise SkipUserException("Sync skipped via sidecar")
            else:
                self._logger.error(f"❌ Sidecar send failed: {reason}")
                return False, message

        except KeyboardInterrupt:
            raise
        except Exception as e:
            self._logger.error(f"Sidecar send error: {e}")
            return False, message

    def _get_conversation_history(self, customer_id: int, limit: int = 10) -> list[dict]:
        """获取会话历史用于AI上下文"""
        try:
            messages = self._repository.get_messages_for_customer(customer_id)
            recent = messages[-limit:] if len(messages) > limit else messages
            return [{"content": m.content, "is_from_kefu": m.is_from_kefu} for m in recent if m.content]
        except Exception:
            return []

    async def _human_delay(self, delay_type: str) -> None:
        """人类行为延迟"""
        delay = self._timing.get_delay_by_type(delay_type)
        await asyncio.sleep(delay)
