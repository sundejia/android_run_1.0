"""
同步编排器

协调整个同步流程，是同步模块的核心入口。
支持交互式等待和动态未读检测。
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime
from typing import Any

from wecom_automation.core.exceptions import is_device_disconnected_error
from wecom_automation.core.interfaces import (
    CustomerSyncResult,
    ICheckpointManager,
    ISyncProgressListener,
    SyncOptions,
    SyncProgress,
    SyncResult,
)
from wecom_automation.database.repository import ConversationRepository
from wecom_automation.services.blacklist_service import BlacklistChecker
from wecom_automation.services.sync.customer_syncer import CustomerSyncer
from wecom_automation.services.user.unread_detector import UnreadUserExtractor, UnreadUserInfo
from wecom_automation.utils.timing import HumanTiming


class SyncOrchestrator:
    """
    同步编排器

    负责协调整个同步流程，包括:
    - 初始化同步环境
    - 获取待同步客户列表
    - 协调各组件完成同步
    - 管理同步进度和状态
    - 处理断点续传
    - 动态未读检测和优先处理

    这是同步模块的主入口。

    Usage:
        orchestrator = SyncOrchestrator(...)
        result = await orchestrator.run(options)
    """

    def __init__(
        self,
        wecom_service,
        repository: ConversationRepository,
        customer_syncer: CustomerSyncer,
        checkpoint_manager: ICheckpointManager,
        unread_extractor: UnreadUserExtractor | None = None,
        timing: HumanTiming | None = None,
        progress_listeners: list[ISyncProgressListener] | None = None,
        logger: logging.Logger | None = None,
    ):
        self._wecom = wecom_service
        self._repository = repository
        self._customer_syncer = customer_syncer
        self._checkpoint = checkpoint_manager
        self._unread_extractor = unread_extractor or UnreadUserExtractor()
        self._timing = timing or HumanTiming()
        self._listeners = progress_listeners or []
        self._logger = logger or logging.getLogger(__name__)

        # 运行时状态
        self._progress = SyncProgress()
        self._current_device = None
        self._current_kefu = None
        self._synced_customers: list[str] = []
        self._current_customer: str | None = None  # 当前正在同步的客户（用于断点恢复）
        self._is_running = False
        self._device_disconnected = False  # 设备断开标志

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def progress(self) -> SyncProgress:
        return self._progress

    def add_listener(self, listener: ISyncProgressListener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: ISyncProgressListener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    async def run(self, options: SyncOptions) -> SyncResult:
        """
        执行同步流程（Two-Phase Strategy）

        流程:
        1. Phase 1: Robust Extraction (Get ALL users)
        2. Phase 2: Sequential Sync (Scroll to top, sync one by one)
        """
        if self._is_running:
            raise RuntimeError("Sync is already running")

        self._is_running = True
        start_time = datetime.now()
        errors: list[str] = []

        # 重置进度
        self._progress = SyncProgress()
        self._synced_customers = []

        try:
            # ============================================
            # RESUME SYNC: 从 checkpoint 恢复
            # ============================================
            if options.resume and self._checkpoint.exists():
                self._logger.info("=" * 50)
                self._logger.info("RESUME SYNC - Recovering from checkpoint")
                self._logger.info("=" * 50)

                await self._initialize_from_checkpoint()
                await self._ensure_wecom_open()
                await self._ensure_on_private_chats()
                await self._complete_interrupted_customer(options)

                self._synced_customers = list(self._checkpoint.get_synced_customers())
            else:
                # 正常同步
                await self._initialize()

            # =========================================================
            # Phase 1: 获取全量客户列表
            # =========================================================
            self._logger.info("Starting Phase 1: Robust User Extraction...")
            customers = await self._get_customers(options)
            self._progress.total_customers = len(customers)
            self._logger.info(f"Phase 1 Complete. Found {len(customers)} total customers.")

            # =========================================================
            # Phase 1.5: 从 blacklist 表读取黑名单用户并过滤
            # =========================================================
            # 只同步没有被拉黑的用户（is_blacklisted=0 或不在表中）
            # 默认情况下，新用户是 is_blacklisted=0（允许同步）
            self._logger.info("Phase 1.5: Filtering out blacklisted users...")
            try:
                from wecom_automation.services.blacklist_service import BlacklistWriter

                device_serial = self._wecom.device_serial if hasattr(self._wecom, "device_serial") else ""
                if device_serial:
                    blacklist_writer = BlacklistWriter()
                    whitelist_names = blacklist_writer.get_whitelist_names(device_serial)

                    # 过滤：只保留在白名单中的用户（is_blacklisted=0）
                    # 新扫描的用户默认在白名单中
                    non_blacklisted_customers = []
                    for customer in customers:
                        name = getattr(customer, "name", str(customer))
                        if name in whitelist_names:
                            non_blacklisted_customers.append(customer)

                    blacklisted_count = len(customers) - len(non_blacklisted_customers)

                    self._logger.info(
                        f"📋 Filtered out {blacklisted_count} blacklisted users, "
                        f"{len(non_blacklisted_customers)} users will be synced"
                    )

                    customers = non_blacklisted_customers
                    self._progress.total_customers = len(customers)

                    if blacklisted_count > 0:
                        self._logger.info(
                            f"ℹ️ {blacklisted_count} users are blocked and will be skipped. "
                            f"Use the blacklist management page to unblock them if needed."
                        )
                else:
                    self._logger.warning("No device serial available, skipping blacklist filtering")

            except Exception as e:
                self._logger.error(f"Failed to filter blacklisted users: {e}")
                import traceback

                self._logger.debug(traceback.format_exc())
                # 如果过滤失败，继续使用所有用户（向后兼容）
                self._logger.info("⚠️ Blacklist filtering failed, syncing all scanned users")

            # =========================================================
            # Phase 1.5 End
            # =========================================================

            # 3. 处理断点续传（跳过已完成的客户）
            if options.resume and self._checkpoint.exists():
                customers = self._filter_resumed_customers(customers)
                self._logger.info(f"Resuming: {len(customers)} customers remaining")

            # 使用队列处理客户
            customer_queue = deque(customers)
            processed_names: set[str] = set()

            # =========================================================
            # Phase 2: 顺序同步
            # =========================================================
            # 重要：提取完后，列表在底部，必须回顶
            self._logger.info("Resetting position to top for sync...")
            if hasattr(self._wecom, "adb"):
                # Ensure we are at top - force high scroll count for deep lists
                await self._wecom.adb.scroll_to_top(scroll_count=1000)
                # Double check top like in extraction
                for _ in range(3):
                    if self._wecom.adb.is_tree_unchanged():
                        break
                    await self._wecom.adb.scroll_to_top(scroll_count=1)
                    await self._wecom.adb.wait(0.5)

            self._logger.info("Starting Phase 2: Sequential Sync...")

            while True:
                # =========================================================
                # 动态未读检测：优先检查首页红点
                # =========================================================
                if options.dynamic_unread_detection:
                    # 先滑动到顶部，确保能检测到所有未读用户
                    if hasattr(self._wecom, "adb") and hasattr(self._wecom.adb, "scroll_to_top"):
                        await self._wecom.adb.scroll_to_top(scroll_count=3)
                        await asyncio.sleep(0.3)  # 等待UI稳定

                    new_unread = await self._detect_first_page_unread()

                    if new_unread:
                        # 获取所有有红点的用户名（包括已处理过的，因为可能有新消息）
                        all_unread_names = {u.name for u in new_unread}

                        # 检查是否有已处理用户又有了新红点（需要重新处理）
                        reprocess_names = all_unread_names & processed_names
                        if reprocess_names:
                            self._logger.info(
                                f"🔄 Found {len(reprocess_names)} processed users with NEW unread, will reprocess: {reprocess_names}"
                            )
                            # 从已处理集合中移除，允许重新处理
                            processed_names -= reprocess_names

                        # 现在计算需要优先处理的用户
                        unread_names = {u.name for u in new_unread if u.name not in processed_names}

                        if unread_names:
                            self._logger.info(f"🔴 Found {len(unread_names)} users with unread, prioritizing...")

                            # 重新排序队列：红点用户放前面
                            remaining = list(customer_queue)
                            customer_queue.clear()

                            # 分成两组：有红点的和没红点的
                            priority_users = []
                            normal_users = []

                            for c in remaining:
                                c_name = getattr(c, "name", str(c))
                                if c_name in unread_names:
                                    priority_users.append(c)
                                else:
                                    normal_users.append(c)

                            # 检查是否有新用户或需要重新处理的用户（不在队列中）
                            existing_names = {getattr(c, "name", str(c)) for c in remaining}
                            for u in new_unread:
                                if u.name not in processed_names and u.name not in existing_names:
                                    user_obj = type(
                                        "UserDetail",
                                        (),
                                        {
                                            "name": u.name,
                                            "channel": u.channel,
                                        },
                                    )()
                                    priority_users.append(user_obj)

                            # 红点用户优先，然后是普通用户
                            customer_queue.extend(priority_users)
                            customer_queue.extend(normal_users)

                # 队列为空则退出
                if not customer_queue:
                    break

                customer = customer_queue.popleft()
                customer_name = getattr(customer, "name", str(customer))
                customer_channel = getattr(customer, "channel", None)

                # 跳过已处理的
                if customer_name in processed_names:
                    continue

                # 检查黑名单（使用数据库）
                device_serial = self._wecom.device_serial if hasattr(self._wecom, "device_serial") else ""
                if device_serial and BlacklistChecker.is_blacklisted(device_serial, customer_name, customer_channel):
                    self._logger.info(f"⏭️ Skipping blacklisted user: {customer_name} (database)")
                    processed_names.add(customer_name)
                    continue

                # 通知监听器：开始
                self._progress.current_customer = customer_name
                self._current_customer = customer_name  # 记录当前客户（用于断点恢复）
                self._notify_customer_start(customer_name)

                try:
                    # 同步单个客户（包含交互式等待）
                    result = await self._customer_syncer.sync(
                        customer,
                        options,
                        self._current_kefu.id,
                        self._wecom.device_serial if hasattr(self._wecom, "device_serial") else "",
                    )

                    # 更新进度
                    self._update_progress(result)
                    self._synced_customers.append(customer_name)
                    processed_names.add(customer_name)
                    self._current_customer = None  # 清除当前客户（已完成）

                    # 保存检查点
                    self._save_checkpoint()

                    # 通知监听器：完成
                    self._notify_customer_complete(customer_name, result)

                except Exception as e:
                    error_msg = f"{customer_name}: {str(e)}"
                    errors.append(error_msg)
                    self._progress.errors.append(error_msg)
                    self._notify_error(str(e), customer_name)
                    self._logger.error(f"Failed to sync {customer_name}: {e}")

                    # 检测设备断开 - 保存检查点并停止
                    if is_device_disconnected_error(e):
                        self._device_disconnected = True
                        self._logger.error("🔌 Device disconnected! Saving checkpoint and stopping...")
                        self._save_checkpoint()  # 保存当前进度（包含未完成的客户）
                        break  # 退出同步循环

                    processed_names.add(customer_name)

                # 用户切换延迟
                if customer_queue:
                    await self._human_delay("user_switch")

            # 5. 清理检查点（仅在正常完成时，设备断开时保留）
            if not self._device_disconnected:
                self._checkpoint.clear()
                self._logger.info("Sync completed, checkpoint cleared")
            else:
                self._logger.warning(
                    f"⚠️ Sync interrupted due to device disconnection. "
                    f"Progress: {self._progress.synced_customers}/{self._progress.total_customers} customers. "
                    f"Use 'Resume Sync' to continue."
                )

        except Exception as e:
            error_msg = f"Fatal error: {str(e)}"
            errors.append(error_msg)
            self._logger.error(error_msg)

            # 检查是否是设备断开导致的异常
            if is_device_disconnected_error(e):
                self._device_disconnected = True
                self._save_checkpoint()
                self._logger.warning("⚠️ Sync stopped due to device disconnection. Checkpoint saved.")

        finally:
            self._is_running = False
            self._current_customer = None

        return SyncResult(
            success=len(errors) == 0 and not self._device_disconnected,
            start_time=start_time,
            end_time=datetime.now(),
            customers_synced=self._progress.synced_customers,
            messages_added=self._progress.messages_added,
            messages_skipped=self._progress.messages_skipped,
            images_saved=0,
            errors=errors,
        )

    # =========================================================================
    # Resume Sync 辅助方法
    # =========================================================================

    async def _ensure_on_private_chats(self) -> None:
        """确保在私聊列表界面"""
        self._logger.info("Step 1: Detecting current screen state...")

        if hasattr(self._wecom, "get_current_screen"):
            try:
                screen_state = await self._wecom.get_current_screen()
                self._logger.info(f"Current screen: {screen_state}")

                if screen_state == "chat":
                    self._logger.info("In chat screen, going back...")
                    await self._wecom.go_back()
                    await asyncio.sleep(0.5)

                elif screen_state in ("other", "unknown"):
                    self._logger.info("Navigating to private chats...")
                    if hasattr(self._wecom, "ensure_on_private_chats"):
                        await self._wecom.ensure_on_private_chats()
                    elif hasattr(self._wecom, "switch_to_private_chats"):
                        await self._wecom.switch_to_private_chats()
                    await asyncio.sleep(0.5)
            except Exception as e:
                self._logger.warning(f"Failed to detect/navigate screen: {e}")
                # 继续尝试，可能已经在正确的界面

    async def _complete_interrupted_customer(self, options: SyncOptions) -> None:
        """完成中断的客户"""
        # 从 checkpoint 获取中断时的客户
        current_customer = None
        checkpoint = self._checkpoint.load()
        if checkpoint:
            stats = checkpoint.get("stats", {})
            current_customer = stats.get("current_customer")

        # 获取已同步的客户列表
        synced_customers = list(self._checkpoint.get_synced_customers())
        self._synced_customers = synced_customers

        self._logger.info(f"Loaded {len(synced_customers)} synced customers from checkpoint")

        if not current_customer:
            self._logger.info("Step 2: No interrupted customer to complete")
            return

        if current_customer in synced_customers:
            self._logger.info(f"Step 2: Interrupted customer '{current_customer}' already synced")
            return

        self._logger.info(f"Step 2: Completing interrupted customer: {current_customer}")

        try:
            # 找到并点击该客户
            if hasattr(self._wecom, "click_user_in_list"):
                success = await self._wecom.click_user_in_list(current_customer)
            else:
                self._logger.warning("WeComService does not have click_user_in_list method")
                return

            if success:
                # 创建临时用户对象
                user_obj = type(
                    "UserDetail",
                    (),
                    {
                        "name": current_customer,
                        "channel": None,
                    },
                )()

                # 完成该客户的同步
                result = await self._customer_syncer.sync(
                    user_obj,
                    options,
                    self._current_kefu.id if self._current_kefu else 0,
                    self._wecom.device_serial if hasattr(self._wecom, "device_serial") else "",
                )

                if result.success:
                    self._synced_customers.append(current_customer)
                    self._current_customer = None
                    self._save_checkpoint()
                    self._logger.info(f"✅ Completed interrupted customer: {current_customer}")
                else:
                    self._logger.warning(f"Failed to sync interrupted customer: {current_customer}")
            else:
                self._logger.warning(f"Could not find interrupted customer: {current_customer}")

        except Exception as e:
            self._logger.error(f"Failed to complete interrupted customer: {e}")
            if is_device_disconnected_error(e):
                raise  # 重新抛出让上层处理

    # =========================================================================
    # Resume Sync (断点恢复) - 独立方法
    # =========================================================================

    async def resume_sync(self, options: SyncOptions) -> SyncResult:
        """
        从检查点恢复同步

        流程:
        1. 检测当前界面状态
        2. 如果在聊天界面，先返回
        3. 加载检查点，找到未完成的客户
        4. 完成中断的客户
        5. 继续正常同步流程

        Args:
            options: 同步选项

        Returns:
            SyncResult: 同步结果
        """
        if self._is_running:
            raise RuntimeError("Sync is already running")

        self._logger.info("=" * 50)
        self._logger.info("RESUME SYNC - Starting recovery")
        self._logger.info("=" * 50)

        # 重置状态
        self._device_disconnected = False

        # ========== 步骤1: 检测并恢复到正确界面 ==========
        self._logger.info("Step 1: Detecting current screen state...")

        if hasattr(self._wecom, "get_current_screen"):
            screen_state = await self._wecom.get_current_screen()
            self._logger.info(f"Current screen: {screen_state}")

            if screen_state == "chat":
                self._logger.info("In chat screen, going back...")
                await self._wecom.go_back()
                await asyncio.sleep(0.5)

            elif screen_state in ("other", "unknown"):
                self._logger.info("Navigating to private chats...")
                if hasattr(self._wecom, "ensure_on_private_chats"):
                    await self._wecom.ensure_on_private_chats()
                else:
                    await self._wecom.switch_to_private_chats()
                await asyncio.sleep(0.5)

        # ========== 步骤2: 加载检查点 ==========
        self._logger.info("Step 2: Loading checkpoint data...")

        if not self._checkpoint.exists():
            self._logger.warning("No checkpoint found, starting fresh sync")
            return await self.run(options)

        # 从 checkpoint 恢复客服信息
        await self._initialize_from_checkpoint()

        # 打开 WeCom App
        await self._ensure_wecom_open()

        # 加载 checkpoint 数据
        checkpoint = self._checkpoint.load()
        synced_customers = checkpoint.get("synced_customers", []) if checkpoint else []
        self._synced_customers = list(synced_customers)
        self._logger.info(f"Loaded {len(synced_customers)} synced customers from checkpoint")

        # 获取中断时的客户
        current_customer = None
        if checkpoint:
            stats = checkpoint.get("stats", {})
            current_customer = stats.get("current_customer")

        # ========== 步骤3: 处理中断的客户 ==========
        if current_customer and current_customer not in synced_customers:
            self._logger.info(f"Step 3: Completing interrupted customer: {current_customer}")

            try:
                # 找到并点击该客户
                success = await self._wecom.click_user_in_list(current_customer)
                if success:
                    # 创建临时用户对象
                    user_obj = type(
                        "UserDetail",
                        (),
                        {
                            "name": current_customer,
                            "channel": None,
                        },
                    )()

                    # 完成该客户的同步
                    result = await self._customer_syncer.sync(
                        user_obj,
                        options,
                        self._current_kefu.id if self._current_kefu else 0,
                        self._wecom.device_serial if hasattr(self._wecom, "device_serial") else "",
                    )

                    if result.success:
                        self._synced_customers.append(current_customer)
                        self._save_checkpoint()
                        self._logger.info(f"✅ Completed interrupted customer: {current_customer}")
                else:
                    self._logger.warning(f"Could not find interrupted customer: {current_customer}")

            except Exception as e:
                self._logger.error(f"Failed to complete interrupted customer: {e}")
                if is_device_disconnected_error(e):
                    self._device_disconnected = True
                    self._save_checkpoint()
                    return SyncResult(
                        success=False,
                        start_time=datetime.now(),
                        end_time=datetime.now(),
                        customers_synced=len(self._synced_customers),
                        messages_added=0,
                        messages_skipped=0,
                        images_saved=0,
                        errors=[f"Device disconnected: {e}"],
                    )
        else:
            self._logger.info("Step 3: No interrupted customer to complete")

        # ========== 步骤4: 继续正常同步流程 ==========
        self._logger.info("Step 4: Resuming normal sync flow...")

        # 强制使用 resume 模式
        resume_options = SyncOptions(
            resume=True,
            max_users=options.max_users,
            prioritize_unread=options.prioritize_unread,
            unread_only=options.unread_only,
            send_test_messages=options.send_test_messages,
            dynamic_unread_detection=options.dynamic_unread_detection,
            interactive_wait_timeout=options.interactive_wait_timeout,
            max_interaction_rounds=options.max_interaction_rounds,
        )

        # 执行同步（会自动跳过已同步的客户）
        return await self.run(resume_options)

    # =========================================================================
    # 动态未读检测
    # =========================================================================

    async def _detect_first_page_unread(self) -> list[UnreadUserInfo]:
        """
        检测首页未读用户（不滚动）

        注意：调用此方法前应确保已滑动到列表顶部。

        Returns:
            有未读消息的用户列表
        """
        self._logger.debug("Checking first page for new unread messages...")

        try:
            # 获取当前 UI 树
            tree = None
            if hasattr(self._wecom, "adb") and hasattr(self._wecom.adb, "get_ui_tree"):
                tree = await self._wecom.adb.get_ui_tree()
            elif hasattr(self._wecom, "get_ui_tree"):
                tree = await self._wecom.get_ui_tree()

            if not tree:
                self._logger.warning("Could not get UI tree for unread detection")
                return []

            # 提取未读信息
            current_unread = self._unread_extractor.extract_from_tree(tree)

            # 过滤只有未读的
            unread_users = [u for u in current_unread if u.unread_count > 0]

            if unread_users:
                self._logger.info(f"🔴 Found {len(unread_users)} users with unread on first page")
                for u in unread_users[:3]:  # 只显示前3个
                    self._logger.debug(f"  - {u.name}: {u.unread_count} unread")

            return unread_users

        except Exception as e:
            self._logger.warning(f"Failed to detect first page unread: {e}")
            return []

    # =========================================================================
    # 初始化
    # =========================================================================

    async def _initialize_from_checkpoint(self) -> None:
        """从 checkpoint 恢复客服信息（Resume Sync 专用）"""
        self._logger.info("Initializing from checkpoint...")

        # 加载 checkpoint
        checkpoint = self._checkpoint.load()
        if not checkpoint:
            raise RuntimeError("Failed to load checkpoint for resume")

        # 获取客服信息
        stats = checkpoint.get("stats", {})
        kefu_id = stats.get("kefu_id")
        kefu_name = checkpoint.get("kefu_name") or stats.get("kefu_name")
        device_serial = checkpoint.get("device_serial", "unknown")

        if not kefu_name:
            raise RuntimeError("Checkpoint missing kefu_name")

        self._logger.info(f"Restored from checkpoint: kefu={kefu_name}, kefu_id={kefu_id}")

        # 设置设备
        self._current_device = self._repository.get_or_create_device(device_serial)

        # 恢复客服信息
        if kefu_id:
            # 有 kefu_id，直接通过 ID 获取
            self._current_kefu = self._repository.get_kefu_by_id(kefu_id)
            if not self._current_kefu:
                # ID 对应的记录不存在，用名称重新创建
                self._logger.warning(f"Kefu ID {kefu_id} not found, creating by name")
                self._current_kefu = self._repository.get_or_create_kefu(kefu_name, self._current_device.id, None)
        else:
            # 没有 kefu_id，通过名称获取或创建
            self._current_kefu = self._repository.get_or_create_kefu(kefu_name, self._current_device.id, None)

        # 设置客户同步器的客服名称
        self._customer_syncer.set_kefu_name(kefu_name)

        self._logger.info(f"Resume initialized: device={device_serial}, kefu={kefu_name} (id={self._current_kefu.id})")

    async def _ensure_wecom_open(self) -> None:
        """确保 WeCom App 已打开（不获取客服信息）"""
        self._logger.info("Ensuring WeCom app is open...")

        if hasattr(self._wecom, "launch_wecom"):
            await self._wecom.launch_wecom(wait_for_ready=True)
        elif hasattr(self._wecom, "ensure_open"):
            await self._wecom.ensure_open()
        elif hasattr(self._wecom, "open_wecom"):
            await self._wecom.open_wecom()

        self._logger.info("WeCom app is open")

    async def _initialize(self) -> None:
        """初始化同步环境"""
        self._logger.info("Initializing sync environment...")

        # 确保WeCom已打开
        if hasattr(self._wecom, "launch_wecom"):
            await self._wecom.launch_wecom(wait_for_ready=True)
        elif hasattr(self._wecom, "ensure_open"):
            await self._wecom.ensure_open()
        elif hasattr(self._wecom, "open_wecom"):
            await self._wecom.open_wecom()

        # 获取当前客服信息
        kefu_info = None
        if hasattr(self._wecom, "get_kefu_name"):
            kefu_info = await self._wecom.get_kefu_name()
        elif hasattr(self._wecom, "get_current_kefu"):
            kefu_info = await self._wecom.get_current_kefu()
        elif hasattr(self._wecom, "get_kefu_info"):
            kefu_info = await self._wecom.get_kefu_info()

        if not kefu_info:
            self._logger.error("Failed to get kefu information - make sure WeCom is open and logged in")
            raise RuntimeError("Failed to get kefu information")

        kefu_name = getattr(kefu_info, "name", str(kefu_info))
        kefu_department = getattr(kefu_info, "department", None)

        # 设置设备和客服
        device_serial = self._wecom.device_serial if hasattr(self._wecom, "device_serial") else "unknown"

        self._current_device = self._repository.get_or_create_device(device_serial)
        self._current_kefu = self._repository.get_or_create_kefu(kefu_name, self._current_device.id, kefu_department)

        # 设置客户同步器的客服名称
        self._customer_syncer.set_kefu_name(kefu_name)

        self._logger.info(f"Initialized: device={device_serial}, kefu={kefu_name}")

    async def _get_customers(self, options: SyncOptions) -> list[Any]:
        """获取待同步客户列表并写入 blacklist 表"""
        self._logger.info("Getting customer list...")

        # 导航到私聊列表
        if hasattr(self._wecom, "switch_to_private_chats"):
            await self._wecom.switch_to_private_chats()
        elif hasattr(self._wecom, "navigate_to_private_chats"):
            await self._wecom.navigate_to_private_chats()
        elif hasattr(self._wecom, "go_to_messages"):
            await self._wecom.go_to_messages()

        # 提取用户列表
        users = []
        if hasattr(self._wecom, "extract_private_chat_users"):
            result = await self._wecom.extract_private_chat_users()
            users = result.users if hasattr(result, "users") else result
        elif hasattr(self._wecom, "extract_all_users"):
            users = await self._wecom.extract_all_users()
        elif hasattr(self._wecom, "get_user_list"):
            users = await self._wecom.get_user_list()

        # === 新增：将扫描到的用户写入 blacklist 表 ===
        try:
            from wecom_automation.services.blacklist_service import BlacklistWriter

            device_serial = self._wecom.device_serial if hasattr(self._wecom, "device_serial") else ""
            if not device_serial:
                self._logger.warning("No device serial available, skipping blacklist upsert")
            else:
                blacklist_writer = BlacklistWriter()

                # 转换为 upsert_scanned_users 需要的格式
                users_list = []
                for user in users:
                    users_list.append(
                        {
                            "customer_name": getattr(user, "name", str(user)),
                            "customer_channel": getattr(user, "channel", None),
                            "avatar_url": None,  # TODO: 可以在扫描时捕获头像
                            "reason": "Auto Scan",
                        }
                    )

                result = blacklist_writer.upsert_scanned_users(device_serial, users_list)

                self._logger.info(
                    f"✅ Blacklist Phase 1 Complete: "
                    f"{result['inserted']} new users (default allowed), "
                    f"{result['updated']} existing users (status preserved)"
                )

                # 提示用户可以在黑名单管理页面选择要拉黑的用户
                if result["inserted"] > 0:
                    self._logger.info(
                        f"📋 {result['inserted']} new users added to database (default allowed). "
                        f"Use the blacklist management page to block specific users if needed."
                    )

        except Exception as e:
            self._logger.error(f"Failed to upsert scanned users to blacklist: {e}")
            import traceback

            self._logger.debug(traceback.format_exc())
        # === 新增结束 ===

        # 未读优先/仅未读处理
        if options.prioritize_unread or options.unread_only:
            unread_users = await self._get_unread_users()
            users = self._sort_or_filter_by_unread(users, unread_users, options)

        return users

    async def _get_unread_users(self) -> list[UnreadUserInfo]:
        """获取未读用户列表"""
        try:
            tree = None
            if hasattr(self._wecom, "adb") and hasattr(self._wecom.adb, "get_ui_tree"):
                tree = await self._wecom.adb.get_ui_tree()
            elif hasattr(self._wecom, "get_ui_tree"):
                tree = await self._wecom.get_ui_tree()

            if tree:
                return self._unread_extractor.extract_from_tree(tree)
        except Exception as e:
            self._logger.warning(f"Failed to extract unread users: {e}")
        return []

    def _sort_or_filter_by_unread(
        self, users: list[Any], unread_users: list[UnreadUserInfo], options: SyncOptions
    ) -> list[Any]:
        """根据未读状态排序或过滤用户"""
        unread_names = {u.name for u in unread_users if u.has_unread()}

        if options.unread_only:
            result = [u for u in users if getattr(u, "name", str(u)) in unread_names]
            self._logger.info(f"Filtered to {len(result)} users with unread messages")
            return result

        if options.prioritize_unread:
            unread_list = [u for u in users if getattr(u, "name", str(u)) in unread_names]
            read_list = [u for u in users if getattr(u, "name", str(u)) not in unread_names]
            result = unread_list + read_list
            self._logger.info(f"Prioritized {len(unread_list)} users with unread messages")
            return result

        return users

    def _filter_resumed_customers(self, customers: list[Any]) -> list[Any]:
        """过滤已同步的客户（断点续传）"""
        synced = set(self._checkpoint.get_synced_customers())
        return [c for c in customers if getattr(c, "name", str(c)) not in synced]

    # =========================================================================
    # 进度管理
    # =========================================================================

    def _update_progress(self, result: CustomerSyncResult) -> None:
        self._progress.synced_customers += 1
        self._progress.messages_added += result.messages_added
        self._progress.messages_skipped += result.messages_skipped

        # 处理用户删除标记
        if result.user_deleted:
            self._logger.info("⛔ User deleted/blocked detected, skipping further processing")

    def _save_checkpoint(self) -> None:
        if not self._current_kefu:
            return

        stats = {
            "messages_added": self._progress.messages_added,
            "messages_skipped": self._progress.messages_skipped,
            "customers_synced": self._progress.synced_customers,
            "total_customers": self._progress.total_customers,
            "progress_percent": int(
                (self._progress.synced_customers / self._progress.total_customers * 100)
                if self._progress.total_customers > 0
                else 0
            ),
            # 记录当前正在处理的客户（用于断点恢复）
            "current_customer": self._current_customer,
            # 记录是否因设备断开而停止
            "device_disconnected": self._device_disconnected,
            # 记录客服信息（用于恢复时不需要从UI获取）
            "kefu_id": self._current_kefu.id,
            "kefu_name": self._current_kefu.name,
        }

        self._checkpoint.save(
            synced_customers=self._synced_customers,
            stats=stats,
            kefu_name=self._current_kefu.name,
            device_serial=self._current_device.serial if self._current_device else "",
        )

        if self._device_disconnected:
            self._logger.info(
                f"📍 Checkpoint saved: {len(self._synced_customers)} customers synced, "
                f"current_customer={self._current_customer}"
            )

    def _notify_customer_start(self, name: str) -> None:
        for listener in self._listeners:
            try:
                listener.on_customer_start(name)
                listener.on_progress(self._progress)
            except Exception as e:
                self._logger.warning(f"Listener error: {e}")

    def _notify_customer_complete(self, name: str, result: CustomerSyncResult) -> None:
        for listener in self._listeners:
            try:
                listener.on_customer_complete(name, result)
                listener.on_progress(self._progress)
            except Exception as e:
                self._logger.warning(f"Listener error: {e}")

    def _notify_error(self, error: str, customer_name: str | None = None) -> None:
        for listener in self._listeners:
            try:
                listener.on_error(error, customer_name)
            except Exception as e:
                self._logger.warning(f"Listener error: {e}")

    async def _human_delay(self, delay_type: str) -> None:
        delay = self._timing.get_delay_by_type(delay_type)
        await asyncio.sleep(delay)
