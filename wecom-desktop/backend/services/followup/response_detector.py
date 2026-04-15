"""
Follow-up 回复检测器

负责检测客户回复并自动回复，复用全量同步的 AIReplyService。

流程：
1. 打开企业微信
2. 切换私聊标签
3. 只检测第一页红点
4. 对有红点的用户：进入聊天 → 提取消息 → 写入数据库 → AI回复 → 等待新消息（40s）
5. 返回后重新检测红点，优先处理新红点
6. 循环直到没有红点
"""

import asyncio
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to path for imports

# Import from backend utils (go up 2 levels: followup -> services -> backend)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from utils.path_utils import get_project_root

PROJECT_ROOT = get_project_root()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Import blacklist checker
from services.conversation_storage import get_control_db_path
from wecom_automation.services.blacklist_service import BlacklistChecker

from .repository import ConversationRepository
from .settings import SettingsManager

# Import AvatarManager for capturing avatars before entering chat
try:
    from wecom_automation.services.user.avatar import AvatarManager

    HAS_AVATAR_MANAGER = True
except ImportError:
    HAS_AVATAR_MANAGER = False

# Import MetricsLogger for business metrics
# Import loguru logger
from wecom_automation.core.logging import get_logger
from wecom_automation.core.metrics_logger import get_metrics_logger

# Import AI Circuit Breaker
from .circuit_breaker import AICircuitBreaker

logger = get_logger("response_detector")


class SkipRequested(Exception):
    """Raised internally to stop processing and handle skip once."""


def _skipped_message_image_hint(msg: Any) -> str:
    """If an image message already has a local file, append path for skip/dedup logs."""
    if getattr(msg, "message_type", "") != "image":
        return ""
    image = getattr(msg, "image", None)
    if not image:
        return ""
    lp = getattr(image, "local_path", None)
    if not lp:
        return ""
    p = Path(lp)
    if p.exists():
        return f" | 图片已下载: {p}"
    return ""


class MessageTracker:
    """
    基于锚点的消息追踪器（增强版）

    核心思想：
    - 用内容识别消息身份（不含 is_self、timestamp）
    - 用位置追踪消息变化
    - 用集合防止重复处理
    - 【增强】记录首次识别的 is_self，防止后续误判

    签名设计：
    - 基础签名: type|content[:80] （用于去重）
    - 上下文签名: type|content[:80]|prev:xxx （用于区分重复消息）
    - 索引签名: type|content[:80]|idx:N （用于追踪位置）

    is_self 一致性保护：
    - 问题：is_self 基于屏幕位置判断，滚动/重渲染后可能误判
    - 解决：首次看到消息时记录 is_self，后续使用记录值而非实时检测值
    - 效果：Agent 发的消息即使被误判为 is_self=False，也不会被当作客户消息
    """

    def __init__(self, max_history: int = 500, serial: str = ""):
        self.max_history = max_history
        self.serial = serial  # 设备序列号，用于日志
        self.last_count: int = 0
        self.last_signatures: set[str] = set()  # 带索引的签名
        self.processed_signatures: set[str] = set()  # 基础签名（已处理过的内容）
        # 【新增】记录首次识别的 is_self: {基础签名: is_self}
        self.is_self_cache: dict[str, bool] = {}
        self._logger = get_logger("message_tracker", device=serial)

    def get_signature(self, msg: Any, prev_msg: Any = None) -> str:
        """
        生成基础签名（不含 is_self 和 timestamp）

        增强：加入 prev_content 来区分同一分钟内的重复消息
        例如：客户连续发两个"好"，签名会不同因为 prev_content 不同
        """
        msg_type = getattr(msg, "message_type", "text")
        content = (getattr(msg, "content", "") or "")[:80]
        # 加入上一条消息内容的前20字符作为上下文
        prev_content = ""
        if prev_msg:
            prev_content = (getattr(prev_msg, "content", "") or "")[:20]
        return f"{msg_type}|{content}|prev:{prev_content}"

    def get_signature_simple(self, msg: Any) -> str:
        """生成简单签名（不含 prev，用于 is_self 缓存）"""
        msg_type = getattr(msg, "message_type", "text")
        content = (getattr(msg, "content", "") or "")[:80]
        return f"{msg_type}|{content}"

    def _is_ambiguous_media_signature(self, msg: Any) -> bool:
        """
        检查消息是否具有不可区分的签名（内容为空或固定模式的媒体消息）

        所有图片消息 simple_sig 都是 "image|"，所有表情包都是 "sticker|[表情包]"，
        这些消息不能作为锚点，因为无法区分新旧消息。
        """
        msg_type = getattr(msg, "message_type", "text")
        if msg_type == "text":
            return False
        content = (getattr(msg, "content", "") or "").strip()
        # 图片/语音无内容
        if not content:
            return True
        # 表情包和视频有固定内容模式
        if content in ("[表情包]", "[图片]", "[Video]") or content.startswith("[Video "):
            return True
        return False

    def get_signature_with_index(self, msg: Any, index: int, prev_msg: Any = None) -> str:
        """生成带索引的签名"""
        base = self.get_signature(msg, prev_msg)
        return f"{base}|idx:{index}"

    def record_current_state(self, messages: list[Any]) -> None:
        """记录当前消息列表状态，并缓存 is_self"""
        prefix = f"[{self.serial}]" if self.serial else "[Tracker]"

        self.last_count = len(messages)
        self.last_signatures = set()
        new_cached_count = 0

        for i, msg in enumerate(messages):
            prev_msg = messages[i - 1] if i > 0 else None
            base_sig = self.get_signature(msg, prev_msg)
            simple_sig = self.get_signature_simple(msg)
            indexed_sig = self.get_signature_with_index(msg, i, prev_msg)

            self.last_signatures.add(indexed_sig)
            self.processed_signatures.add(base_sig)

            # 【关键】首次看到消息时，记录其 is_self 值
            if simple_sig not in self.is_self_cache:
                is_self = getattr(msg, "is_self", False)
                self.is_self_cache[simple_sig] = is_self
                new_cached_count += 1

        self._logger.debug(
            f"{prefix} record_current_state: {len(messages)} msgs, "
            f"新缓存 {new_cached_count} 条, 总缓存 {len(self.is_self_cache)} 条"
        )

        # 限制历史记录大小
        if len(self.processed_signatures) > self.max_history:
            # 保留最近的一半
            to_keep = list(self.processed_signatures)[-self.max_history // 2 :]
            self.processed_signatures = set(to_keep)
            # 同步清理 is_self 缓存
            to_keep_simple = list(self.is_self_cache.keys())[-self.max_history // 2 :]
            self.is_self_cache = {k: self.is_self_cache[k] for k in to_keep_simple if k in self.is_self_cache}
            self._logger.info(f"{prefix} 清理历史记录，保留 {len(self.processed_signatures)} 条签名")

    def get_cached_is_self(self, msg: Any) -> bool:
        """
        获取缓存的 is_self 值

        如果消息已缓存，返回缓存值（首次识别的值）
        否则返回当前检测的值
        """
        simple_sig = self.get_signature_simple(msg)
        if simple_sig in self.is_self_cache:
            return self.is_self_cache[simple_sig]
        return getattr(msg, "is_self", False)

    def find_new_messages(self, current_messages: list[Any]) -> list[Any]:
        """
        找出新消息（增强版：防止滚动回来的老消息被误判）

        策略：
        1. 找到锚点位置（最后一个已知消息）
        2. 只检查锚点之后的消息
        3. 简单签名已存在的消息，只有在列表末尾才认为是新消息（同分钟重复消息）
        4. 完整签名不存在的消息才是新消息

        核心原则：新消息只可能出现在列表底部
        """
        if not current_messages:
            return []

        # 生成当前消息的签名
        current_signatures = []
        for i, msg in enumerate(current_messages):
            prev_msg = current_messages[i - 1] if i > 0 else None
            base_sig = self.get_signature(msg, prev_msg)
            simple_sig = self.get_signature_simple(msg)
            indexed_sig = self.get_signature_with_index(msg, i, prev_msg)
            current_signatures.append((base_sig, simple_sig, indexed_sig, msg))

        # 找锚点位置（使用简单签名从后往前找最后一个已知消息）
        # 【重要】跳过签名不可区分的媒体消息（如图片/表情包），它们不能作为可靠锚点
        anchor_idx = -1
        for i in range(len(current_signatures) - 1, -1, -1):
            _, simple_sig, _, msg = current_signatures[i]
            if self._is_ambiguous_media_signature(msg):
                continue  # 媒体消息签名不唯一，跳过
            if simple_sig in self.is_self_cache:
                anchor_idx = i
                break

        # 收集新消息
        new_messages = []
        total_count = len(current_signatures)
        TAIL_THRESHOLD = 2  # 最后2条消息更宽松

        for i in range(anchor_idx + 1, total_count):
            base_sig, simple_sig, indexed_sig, msg = current_signatures[i]

            # 判断是否在"末尾区域"
            is_in_tail = (total_count - i) <= TAIL_THRESHOLD

            # 简单签名已存在 → 可能是滚动回来的老消息
            if simple_sig in self.is_self_cache:
                if not is_in_tail:
                    continue  # 不在末尾，跳过
                if base_sig in self.processed_signatures:
                    continue  # 完整签名也存在，跳过

            # 完整签名不存在 → 新消息
            if base_sig not in self.processed_signatures:
                new_messages.append(msg)

        # 更新状态
        self.record_current_state(current_messages)

        return new_messages

    def find_new_customer_messages(self, current_messages: list[Any]) -> list[Any]:
        """
        找出新的客户消息（使用缓存的 is_self）

        【关键方法】解决 is_self 误判问题：
        - 使用 get_cached_is_self() 而非直接读取 msg.is_self
        - 如果消息在之前被识别为 Agent 消息，即使现在被误判，也不会返回
        - 滚动回来的老消息不会被误判为新消息
        """
        prefix = f"[{self.serial}]" if self.serial else "[Tracker]"

        if not current_messages:
            self._logger.debug(f"{prefix} find_new_customer_messages: 空消息列表")
            return []

        # ========== 日志: 当前提取到的所有消息 ==========
        self._logger.info(f"{prefix} ========== 消息检测开始 ==========")
        self._logger.info(f"{prefix} 当前提取到 {len(current_messages)} 条消息:")
        for i, msg in enumerate(current_messages):
            content = (getattr(msg, "content", "") or "")[:40]
            is_self = getattr(msg, "is_self", None)
            msg_type = getattr(msg, "message_type", "text")
            sender = "KEFU" if is_self else "CUST"
            self._logger.info(f"{prefix}   [{i}] [{sender}] {msg_type}: {content}...")

        # ========== 日志: 已缓存的消息（去重依据）==========
        self._logger.info(
            f"{prefix} 已缓存消息数: {len(self.is_self_cache)}, 已处理签名数: {len(self.processed_signatures)}"
        )

        # 生成当前消息的签名
        current_signatures = []
        for i, msg in enumerate(current_messages):
            prev_msg = current_messages[i - 1] if i > 0 else None
            base_sig = self.get_signature(msg, prev_msg)
            simple_sig = self.get_signature_simple(msg)
            current_signatures.append((base_sig, simple_sig, msg))

        # 找锚点位置
        # 【重要】跳过签名不可区分的媒体消息（如图片/表情包），它们不能作为可靠锚点
        anchor_idx = -1
        anchor_content = None
        skipped_media_count = 0
        for i in range(len(current_signatures) - 1, -1, -1):
            _, simple_sig, msg = current_signatures[i]
            if self._is_ambiguous_media_signature(msg):
                skipped_media_count += 1
                continue  # 媒体消息签名不唯一，跳过
            if simple_sig in self.is_self_cache:
                anchor_idx = i
                anchor_content = (getattr(msg, "content", "") or "")[:30]
                break

        if skipped_media_count > 0:
            self._logger.info(f"{prefix} 锚点搜索跳过 {skipped_media_count} 条不可区分的媒体消息")
        self._logger.info(f"{prefix} 锚点位置: {anchor_idx} (内容: {anchor_content})")

        # 收集新客户消息
        customer_messages = []
        skipped_messages = []  # 记录被跳过的消息
        total_count = len(current_signatures)
        TAIL_THRESHOLD = 2

        for i in range(anchor_idx + 1, total_count):
            base_sig, simple_sig, msg = current_signatures[i]
            content = (getattr(msg, "content", "") or "")[:40]
            current_is_self = getattr(msg, "is_self", False)
            is_in_tail = (total_count - i) <= TAIL_THRESHOLD

            # 简单签名已存在 → 可能是滚动回来的老消息
            if simple_sig in self.is_self_cache:
                cached_is_self = self.is_self_cache[simple_sig]
                if not is_in_tail:
                    skipped_messages.append(
                        {
                            "idx": i,
                            "content": content,
                            "reason": (
                                f"简单签名已存在且不在末尾 (cached_is_self={cached_is_self}, "
                                f"current_is_self={current_is_self})"
                                f"{_skipped_message_image_hint(msg)}"
                            ),
                        }
                    )
                    continue
                if base_sig in self.processed_signatures:
                    skipped_messages.append(
                        {
                            "idx": i,
                            "content": content,
                            "reason": (
                                f"完整签名已存在 (cached_is_self={cached_is_self}){_skipped_message_image_hint(msg)}"
                            ),
                        }
                    )
                    continue
                # 在末尾且完整签名是新的 → 可能是同分钟重复消息
                self._logger.info(f"{prefix}   [{i}] 末尾区域新消息 (同内容重复): {content}")

            # 完整签名不存在 → 新消息
            if base_sig not in self.processed_signatures:
                # 缓存新消息的 is_self
                if simple_sig not in self.is_self_cache:
                    self.is_self_cache[simple_sig] = current_is_self
                    self._logger.info(f"{prefix}   [{i}] 新消息缓存 is_self={current_is_self}: {content}")

                # 标记为已处理
                self.processed_signatures.add(base_sig)

                # 使用缓存的 is_self 判断是否是客户消息
                cached_is_self = self.is_self_cache.get(simple_sig, current_is_self)

                # 检测 is_self 不一致
                if cached_is_self != current_is_self:
                    self._logger.warning(
                        f"{prefix}   [{i}] is_self 不一致! cached={cached_is_self}, current={current_is_self}, "
                        f"使用缓存值. 内容: {content}"
                    )

                if not cached_is_self:
                    customer_messages.append(msg)
                    self._logger.info(f"{prefix}   [{i}] ✅ 新客户消息: {content}")
                else:
                    self._logger.info(f"{prefix}   [{i}] ⏭️ 新消息但是 is_self=True (Agent消息): {content}")

        # ========== 日志: 被跳过的消息 ==========
        if skipped_messages:
            self._logger.info(f"{prefix} 被跳过的消息 ({len(skipped_messages)} 条):")
            for sm in skipped_messages:
                self._logger.info(f"{prefix}   [{sm['idx']}] {sm['content']} - 原因: {sm['reason']}")

        # ========== 日志: 最终结果 ==========
        self._logger.info(f"{prefix} ========== 检测结果 ==========")
        self._logger.info(f"{prefix} 新客户消息: {len(customer_messages)} 条")
        for i, msg in enumerate(customer_messages):
            content = (getattr(msg, "content", "") or "")[:50]
            self._logger.info(f"{prefix}   [NEW-{i}] {content}")

        # 更新状态（不含新消息的缓存，已在上面处理）
        self.last_count = len(current_messages)
        self.last_signatures = set()
        for i, (base_sig, simple_sig, msg) in enumerate(current_signatures):
            indexed_sig = f"{base_sig}|idx:{i}"
            self.last_signatures.add(indexed_sig)
            self.processed_signatures.add(base_sig)
            if simple_sig not in self.is_self_cache:
                self.is_self_cache[simple_sig] = getattr(msg, "is_self", False)

        self._logger.info(f"{prefix} ========== 消息检测结束 ==========")
        return customer_messages

    def get_stats(self) -> dict[str, int]:
        """获取统计信息"""
        return {
            "last_count": self.last_count,
            "last_signatures_count": len(self.last_signatures),
            "processed_count": len(self.processed_signatures),
            "is_self_cache_count": len(self.is_self_cache),
        }


# Logging setup moved to caller (realtime_reply_process.py)
# Each device process will configure its own loguru sink via init_logging(serial=...)


class ResponseDetector:
    """客户回复检测器"""

    def __init__(
        self,
        repository: ConversationRepository,
        settings_manager: SettingsManager,
        logger=None,
    ):
        self._repository = repository
        self._settings = settings_manager
        self._logger = logger or get_logger("response_detector")
        self._cancel_requested = False
        self._followup_scan_running = False
        self._media_event_bus = None
        self._media_action_settings: dict = {}
        self._ai_circuit_breaker = AICircuitBreaker(
            failure_threshold=3,
            recovery_timeout=120.0,
            half_open_max_calls=1,
            logger=self._logger,
        )
        self._click_fail_cooldown: dict[str, tuple[float, int]] = {}

    def set_followup_scan_running(self, running: bool) -> None:
        """设置跟进扫描是否正在运行（用于跳过响应扫描）"""
        self._followup_scan_running = running

    def request_cancel(self) -> None:
        """请求取消"""
        self._cancel_requested = True

    def reset_cancel(self) -> None:
        """重置取消标志"""
        self._cancel_requested = False

    def _clean_expired_click_cooldowns(self) -> None:
        """Remove expired entries from the click-failure cooldown map."""
        now = time.time()
        expired = [k for k, (until, _) in self._click_fail_cooldown.items() if now >= until]
        for k in expired:
            del self._click_fail_cooldown[k]

    def _get_sidecar_timeout(self) -> float:
        """Return the Sidecar review timeout, reduced during night hours."""
        try:
            from services.settings import get_settings_service

            svc = get_settings_service()
            all_settings = svc.get_all_settings_flat()

            day_timeout = float(all_settings.get("sidecar_timeout", 60))
            night_timeout = float(all_settings.get("night_mode_sidecar_timeout", 30))
            night_start = int(all_settings.get("night_mode_start_hour", 22))
            night_end = int(all_settings.get("night_mode_end_hour", 8))
        except Exception:
            day_timeout, night_timeout, night_start, night_end = 60.0, 30.0, 22, 8

        hour = datetime.now().hour
        if night_start > night_end:
            is_night = hour >= night_start or hour < night_end
        else:
            is_night = night_start <= hour < night_end

        return night_timeout if is_night else day_timeout

    async def _init_media_event_bus(self, wecom, serial: str) -> None:
        """Build and cache the MediaEventBus for this scan cycle.

        Uses the shared factory so behaviour is identical to full-sync.
        Failures are logged but never break the scan.
        """
        try:
            from wecom_automation.services.media_actions.factory import build_media_event_bus

            async def _on_media_results(event, results):
                try:
                    from routers.global_websocket import broadcast_media_action_triggered

                    serialised = [
                        {"action_name": r.action_name, "status": r.status.value, "message": r.message} for r in results
                    ]
                    await broadcast_media_action_triggered(
                        customer_name=event.customer_name,
                        device_serial=event.device_serial,
                        message_type=event.message_type,
                        results=serialised,
                    )
                except Exception as ws_exc:
                    self._logger.debug("Media action WS broadcast failed (non-blocking): %s", ws_exc)

            db_path = self._repository._db_path
            bus, settings = build_media_event_bus(
                db_path,
                settings_db_path=str(get_control_db_path()),
                effects_db_path=str(get_control_db_path()),
                wecom_service=wecom,
                on_action_results=_on_media_results,
            )
            self._media_event_bus = bus
            self._media_action_settings = settings

            if bus is not None:
                self._logger.info(f"[{serial}] Media auto-actions enabled ({len(bus._actions)} actions)")
            else:
                self._logger.debug(f"[{serial}] Media auto-actions disabled")
        except Exception as exc:
            self._logger.warning(f"[{serial}] Failed to build media event bus (non-blocking): {exc}")
            self._media_event_bus = None
            self._media_action_settings = {}

    async def detect_and_reply(
        self,
        device_serial: str | None = None,
        interactive_wait_timeout: int = 40,
        sidecar_client: Any | None = None,
        droidrun_port: int | None = None,
    ) -> dict[str, Any]:
        """
        检测客户回复并自动回复

        流程:
        1. 打开企业微信
        2. 切换到私聊标签
        3. 只检测第一页红点
        4. 对有红点的用户：进入聊天 → 提取消息 → 写入数据库 → AI回复 → 等待新消息
        5. 返回后重新检测红点，优先处理新红点
        6. 循环直到没有红点

        Args:
            device_serial: 设备序列号
            interactive_wait_timeout: 等待用户回复的超时时间（秒）
            sidecar_client: Sidecar 客户端（可选，如果传入则优先使用，否则从设置获取）
        """
        # Check if a follow-up scan is already running
        if self._followup_scan_running:
            self._logger.info("Skipping response scan - follow-up scan is already in progress")
            return {
                "scan_time": datetime.now().isoformat(),
                "devices_scanned": 0,
                "users_with_unread": 0,
                "responses_detected": 0,
                "customers_marked_responded": [],
                "errors": [],
                "skipped": True,
                "reason": "Follow-up scan in progress",
            }

        # Import here to avoid circular dependencies
        import adbutils

        result = {
            "scan_time": datetime.now().isoformat(),
            "devices_scanned": 0,
            "users_with_unread": 0,
            "responses_detected": 0,
            "messages_stored": 0,
            "customers_marked_responded": [],
            "errors": [],
        }

        self._logger.info("")
        self._logger.info("=" * 60)
        self._logger.info("PHASE 1: RESPONSE DETECTION (Red Dot Prioritized)")
        self._logger.info("=" * 60)

        try:
            # Get devices to scan
            devices_to_scan = []
            if device_serial:
                devices_to_scan = [device_serial]
            else:
                try:
                    adb_devices = adbutils.adb.device_list()
                    devices_to_scan = [d.serial for d in adb_devices]
                except Exception as e:
                    self._logger.error(f"Failed to get device list: {e}")
                    result["errors"].append(f"Failed to get device list: {e}")
                    return result

            if not devices_to_scan:
                self._logger.warning("No devices available for scanning")
                result["errors"].append("No devices available")
                return result

            self._logger.info(f"Scanning {len(devices_to_scan)} device(s): {devices_to_scan}")

            # Scan each device
            for serial in devices_to_scan:
                if self._cancel_requested:
                    self._logger.info("Response scan cancelled")
                    break

                device_result = await self._scan_device_for_responses(
                    serial,
                    interactive_wait_timeout,
                    sidecar_client=sidecar_client,
                    droidrun_port=droidrun_port,
                )

                result["devices_scanned"] += 1
                result["users_with_unread"] += device_result.get("users_processed", 0)
                result["responses_detected"] += device_result.get("replies_sent", 0)
                result["messages_stored"] += device_result.get("messages_stored", 0)
                result["customers_marked_responded"].extend(device_result.get("customers_handled", []))
                result["errors"].extend(device_result.get("errors", []))

            # Log summary
            self._logger.info("")
            self._logger.info("=" * 60)
            self._logger.info("PHASE 1 COMPLETE")
            self._logger.info("=" * 60)
            self._logger.info(f"   Devices scanned: {result['devices_scanned']}")
            self._logger.info(f"   Users processed: {result['users_with_unread']}")
            self._logger.info(f"   Replies sent: {result['responses_detected']}")
            self._logger.info(f"   Messages stored: {result['messages_stored']}")
            self._logger.info("=" * 60)

        except Exception as e:
            error_msg = f"Response scan failed: {e}"
            self._logger.error(error_msg)
            result["errors"].append(error_msg)
            import traceback

            self._logger.error(traceback.format_exc())

        # Log session summary
        metrics = get_metrics_logger(device_serial or "all")
        metrics.log_session_summary()

        return result

    async def _scan_device_for_responses(
        self,
        serial: str,
        interactive_wait_timeout: int = 40,
        sidecar_client: Any | None = None,
        droidrun_port: int | None = None,
    ) -> dict[str, Any]:
        """
        扫描单个设备的红点用户

        使用队列动态处理红点，优先处理新红点
        """
        import dataclasses

        from wecom_automation.core.config import Config, ScrollConfig
        from wecom_automation.services.wecom_service import WeComService

        device_result = {
            "users_processed": 0,
            "replies_sent": 0,
            "messages_stored": 0,
            "customers_handled": [],
            "errors": [],
        }

        self._logger.info("")
        self._logger.info(f"[{serial}] Starting response scan...")

        try:
            # Initialize WeComService with per-device DroidRun port
            custom_scroll = dataclasses.replace(ScrollConfig(), max_scrolls=5, stable_threshold=2)
            config_kwargs: dict[str, Any] = {"scroll": custom_scroll, "device_serial": serial}
            if droidrun_port is not None:
                config_kwargs["droidrun_port"] = droidrun_port
            else:
                try:
                    from services.device_manager import PortAllocator
                    port = PortAllocator().get_allocation(serial)
                    if port is not None:
                        config_kwargs["droidrun_port"] = port
                except Exception:
                    pass
            config = Config(**config_kwargs)
            wecom = WeComService(config)

            # Build MediaEventBus for this scan cycle (shared factory, same as full sync)
            await self._init_media_event_bus(wecom, serial)

            # Initialize Sidecar Client (if not provided and enabled in settings)
            # Priority: use provided sidecar_client > fallback to service.get_sidecar_client()
            if sidecar_client is None:
                try:
                    from .service import get_followup_service

                    service = get_followup_service()
                    sidecar_client = service.get_sidecar_client(serial)
                    if sidecar_client:
                        self._logger.info(f"[{serial}] ✅ Sidecar client created from settings")
                    else:
                        self._logger.info(f"[{serial}] ⚠️ Sidecar disabled in settings or failed to initialize")
                except Exception as e:
                    import traceback

                    self._logger.error(f"[{serial}] Failed to init sidecar client: {e}")
                    self._logger.debug(f"[{serial}] Traceback: {traceback.format_exc()}")
                    # Ensure sidecar_client is set to None on exception
                    sidecar_client = None
            else:
                self._logger.info(f"[{serial}] ✅ Using provided sidecar client (from command line)")

            # Context manager wrapper for sidecar if it exists
            # We create a dummy context manager if sidecar_client is None to keep code clean
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def optional_sidecar(client):
                if client:
                    async with client:
                        yield client
                else:
                    yield None

            async with optional_sidecar(sidecar_client) as client:
                if client:
                    self._logger.info(f"[{serial}] 🚀 Sidecar enabled for this scan")

                # Step 1: Launch WeCom
                self._logger.info(f"[{serial}] Step 1: Launching WeCom...")
                await wecom.launch_wecom(wait_for_ready=True)
                await asyncio.sleep(1)

                # Step 2: Switch to Private Chats (updated from External)
                self._logger.info(f"[{serial}] Step 2: Switching to Private Chats...")
                await wecom.switch_to_private_chats()
                await asyncio.sleep(0.5)

                # Step 3: Scroll to top
                self._logger.info(f"[{serial}] Step 3: Scrolling to top...")
                await wecom.adb.scroll_to_top()
                await asyncio.sleep(0.5)

                # Step 4: Initial red dot detection
                self._logger.info(f"[{serial}] Step 4: Detecting red dot users (first page only)...")
                initial_unread = await self._detect_first_page_unread(wecom, serial)

                if not initial_unread:
                    self._logger.info(f"[{serial}] ✅ No red dot users found")
                    self._logger.info(f"[{serial}] 🔄 Triggering one followup check in idle state")
                    try:
                        await self._try_followup_if_idle(wecom, serial, client)
                    except Exception as followup_error:
                        self._logger.warning(f"[{serial}] Followup error: {followup_error}")
                    self._logger.info(f"[{serial}] ✅ Scan complete")
                    return device_result

                self._logger.info(f"[{serial}] 🔴 Found {len(initial_unread)} red dot users, adding to queue")

                # Step 5: Process red dot users with dynamic prioritization
                user_queue: deque = deque(initial_unread)
                queued_names: set[str] = {u.name for u in initial_unread}
                processed_names: set[str] = set()
                skipped_names: set[str] = set()  # Track skipped users (e.g., blacklisted)
                process_count = 0

                # Defensive: Clear any stale skip flags from previous scan cycle before processing users
                if client:
                    try:
                        await client.clear_skip_flag()
                        self._logger.debug(f"[{serial}] 🧹 Skip flag cleared at scan start")
                    except Exception as e:
                        self._logger.warning(f"[{serial}] ⚠️ Failed to clear skip flag at scan start: {e}")

                while user_queue and not self._cancel_requested:
                    # Check for skip flag at start of each user processing
                    # This allows operator to skip current queued message and return to list
                    self._logger.debug(
                        f"[{serial}] 🔍 Checking for skip request... (client available: {client is not None})"
                    )

                    skip_requested = False
                    if client is None:
                        self._logger.warning(f"[{serial}] ⚠️ Skip check skipped: sidecar client is None")
                    else:
                        try:
                            skip_requested = await client.is_skip_requested()
                            self._logger.debug(f"[{serial}] 🔍 Skip check result: {skip_requested}")
                        except Exception as e:
                            # Log detailed error for debugging
                            self._logger.error(f"[{serial}] ❌ Error checking skip flag: {type(e).__name__}: {e}")

                    if skip_requested:
                        self._logger.info(f"[{serial}] ⏭️ Skip requested - clearing queue and returning to chat list")
                        user_queue.clear()  # Clear remaining queue
                        await self._handle_skip_once(wecom, serial, client)
                        break  # Exit while loop

                    # Get user from queue
                    user = user_queue.popleft()
                    user_name = user.name

                    # Skip if already processed
                    if user_name in processed_names:
                        continue

                    process_count += 1
                    self._logger.info(
                        f"[{serial}] [{process_count}] 🔴 Processing: {user_name} (queue: {len(user_queue)} remaining)"
                    )

                    try:
                        # Process this user with interactive wait
                        user_result = await self._process_unread_user_with_wait(
                            wecom, serial, user, interactive_wait_timeout, sidecar_client=client
                        )

                        # Track based on whether user was skipped or processed
                        if user_result.get("skipped"):
                            skipped_names.add(user_name)
                            self._logger.debug(f"[{serial}] ✅ User {user_name} added to skipped list")
                        else:
                            processed_names.add(user_name)
                            device_result["users_processed"] += 1

                        if user_result.get("reply_sent"):
                            device_result["replies_sent"] += 1
                        device_result["messages_stored"] += user_result.get("messages_stored", 0)

                        if user_result.get("reply_sent") or user_result.get("followups_marked"):
                            device_result["customers_handled"].append(user_result)

                    except SkipRequested:
                        # Centralized skip handling (avoid double go_back)
                        self._logger.info(f"[{serial}] ⏭️ Skip requested during user processing - stopping scan")
                        user_queue.clear()
                        await self._handle_skip_once(wecom, serial, client)
                        break
                    except Exception as e:
                        self._logger.error(f"[{serial}] Error processing {user_name}: {e}")
                        device_result["errors"].append(f"{user_name}: {str(e)}")
                        processed_names.add(user_name)
                        try:
                            await wecom.go_back()
                            await asyncio.sleep(0.3)
                        except Exception:
                            pass

                    # After processing, re-detect red dots for prioritization
                    self._logger.debug(f"[{serial}] Checking for new red dots...")
                    new_unread = await self._detect_first_page_unread(wecom, serial)

                    # Find new red dots (not processed, not skipped, and not in queue)
                    new_users = []
                    for u in new_unread:
                        if u.name not in processed_names and u.name not in skipped_names and u.name not in queued_names:
                            new_users.append(u)
                            queued_names.add(u.name)

                    # Check for re-appeared red dots (processed users with new messages)
                    # NOTE: We only reprocess users who were actually processed, not skipped
                    reprocess_users = []
                    for u in new_unread:
                        if u.name in processed_names and u.name not in skipped_names:
                            reprocess_users.append(u)
                            processed_names.discard(u.name)
                            if u.name not in queued_names:
                                queued_names.add(u.name)

                    # Add new/reprocess users to front of queue (priority)
                    if new_users or reprocess_users:
                        priority_users = new_users + reprocess_users
                        self._logger.info(
                            f"[{serial}] 🆕 Found {len(priority_users)} new/reprocess red dots, adding to queue front"
                        )
                        for u in reversed(priority_users):
                            user_queue.appendleft(u)

                if self._cancel_requested:
                    self._logger.info(f"[{serial}] Cancel requested, stopping")
                else:
                    self._logger.info(f"[{serial}] ✅ Queue empty, all red dot users processed")

                    # ========== 补刀功能集成 ==========
                    # 在没有红点用户时，尝试执行补刀
                    try:
                        await self._try_followup_if_idle(wecom, serial, client)
                    except Exception as followup_error:
                        self._logger.warning(f"[{serial}] Followup error: {followup_error}")

        except Exception as e:
            error_msg = f"[{serial}] Response scan error: {e}"
            self._logger.error(error_msg)
            device_result["errors"].append(error_msg)
            import traceback

            self._logger.debug(traceback.format_exc())

        return device_result

    async def _detect_first_page_unread(self, wecom, serial: str) -> list[Any]:
        """
        检测首页优先级用户（不滚动）

        退出对话后检查当前可见的用户列表，找出高优先级用户。
        与 Phase 2 (scanner.py) 的逻辑保持一致。

        高优先级条件：
        1. 有未读消息（红点）
        2. 或者是新好友（消息预览包含欢迎语）

        Args:
            wecom: WeComService 实例
            serial: 设备序列号

        Returns:
            高优先级用户列表
        """
        from wecom_automation.services.sync_service import UnreadUserExtractor

        try:
            # 获取当前 UI 树
            tree, _ = await wecom.adb.get_ui_state()

            if not tree:
                self._logger.debug(f"[{serial}] Could not get UI tree for priority detection")
                return []

            # 提取用户信息
            current_users = UnreadUserExtractor.extract_from_tree(tree)

            # Debug: Log all users found to debug new friend detection
            self._logger.info(f"[{serial}] Extracted {len(current_users)} users from first page:")
            for u in current_users:
                self._logger.info(
                    f"[{serial}]   - User: {u.name} | Preview: '{u.message_preview}' | "
                    f"Unread: {u.unread_count} | NewFriend: {u.is_new_friend} | Priority: {u.is_priority()}"
                )

            # 使用 is_priority() 过滤: 包括未读消息和新好友
            priority_users = [u for u in current_users if u.is_priority()]

            if priority_users:
                unread_count = sum(1 for u in priority_users if u.unread_count > 0)
                new_friend_count = sum(1 for u in priority_users if u.is_new_friend)
                self._logger.info(
                    f"[{serial}] 🔴 Found {len(priority_users)} priority users on first page "
                    f"({unread_count} unread, {new_friend_count} new friends)"
                )
                for u in priority_users[:3]:  # 只显示前3个
                    reason = []
                    if u.unread_count > 0:
                        reason.append(f"{u.unread_count} unread")
                    if u.is_new_friend:
                        reason.append("new friend")
                    self._logger.debug(f"[{serial}]   - {u.name}: {', '.join(reason)}")

            return priority_users

        except Exception as e:
            self._logger.warning(f"[{serial}] Failed to detect first page priority users: {e}")
            return []

    async def _process_unread_user_with_wait(
        self,
        wecom,
        serial: str,
        unread_user,
        interactive_wait_timeout: int = 40,
        sidecar_client: Any | None = None,
    ) -> dict[str, Any]:
        """
        处理有未读消息的用户（带交互等待）
        """
        user_name = unread_user.name
        user_channel = getattr(unread_user, "channel", None)

        # Initialize metrics logger
        metrics = get_metrics_logger(serial)

        self._logger.info("")
        self._logger.info(f"[{serial}] Processing: {user_name}")
        self._logger.info(f"[{serial}]    - Unread count: {getattr(unread_user, 'unread_count', '?')}")

        # Record customer processed
        metrics.record_customer_processed(user_name)

        result = {
            "customer_name": user_name,
            "channel": user_channel,
            "device": serial,
            "reply_sent": False,
            "messages_stored": 0,
            "message_db_ids": [],  # Track message DB IDs for metrics
            "skipped": False,  # Track if user was skipped (e.g., blacklisted)
        }

        try:
            # Ensure user is recorded in blacklist DB (as accepted by default)
            try:
                from wecom_automation.services.blacklist_service import BlacklistWriter

                BlacklistWriter().ensure_user_in_blacklist_table(serial, user_name, user_channel)
            except Exception as e:
                self._logger.warning(f"[{serial}] Failed to record user in blacklist table: {e}")

            # Blacklist check - skip if user is blacklisted
            if BlacklistChecker.is_blacklisted(
                serial,
                user_name,
                user_channel,
                fail_closed=True,
            ):
                self._logger.info(f"[{serial}] ⛔ Skipping blacklisted user: {user_name}")
                result["skipped"] = True
                return result

            # Step 0: Capture avatar BEFORE entering chat (while on list page)
            self._logger.info(f"[{serial}]    Step 0: Capturing avatar before entering chat...")
            avatar_path = await self._capture_avatar_before_click(wecom, serial, user_name)
            if avatar_path:
                result["avatar_path"] = str(avatar_path)
                self._logger.info(
                    f"[{serial}]    ✅ Avatar captured: {avatar_path.name if hasattr(avatar_path, 'name') else avatar_path}"
                )
            else:
                self._logger.info(f"[{serial}]    ⚠️ Avatar capture skipped or failed")

            # P1 修复: 切换用户时清理过期的队列消息，防止误发
            if sidecar_client:
                try:
                    cleared = await sidecar_client.clear_expired_messages()
                    if cleared > 0:
                        self._logger.info(
                            f"[{serial}] 🧹 Cleared {cleared} expired queue messages before processing {user_name}"
                        )
                except Exception as e:
                    self._logger.warning(f"[{serial}] Error clearing expired messages: {e}")

            # Step 1: Enter chat
            self._logger.info(f"[{serial}]    Step 1: Entering chat...")

            # Click cooldown: skip customers that recently failed to click
            self._clean_expired_click_cooldowns()
            cooldown_key = f"{serial}:{user_name}"
            if cooldown_key in self._click_fail_cooldown:
                cooldown_until, fail_count = self._click_fail_cooldown[cooldown_key]
                if time.time() < cooldown_until:
                    self._logger.warning(
                        f"[{serial}]    Click cooldown active for {user_name} "
                        f"(failures={fail_count}, retry in {int(cooldown_until - time.time())}s)"
                    )
                    metrics.log_error(
                        error_type="click_cooldown_skip",
                        error_message=f"Skipping {user_name} due to click cooldown",
                        customer_name=user_name,
                        context={"serial": serial, "fail_count": fail_count},
                    )
                    return result

            # Check for skip before entering chat
            if sidecar_client:
                try:
                    if await sidecar_client.is_skip_requested():
                        self._logger.info(f"[{serial}] ⏭️ Skip requested before entering chat - skipping user")
                        result["skipped"] = True
                        return result
                except Exception as e:
                    # Log detailed error but continue processing (skip check is optional)
                    self._logger.warning(f"[{serial}] Error checking skip before chat: {type(e).__name__}: {e}")

            # Clear skip flag before clicking to prevent stale flags from blocking
            if sidecar_client:
                try:
                    await sidecar_client.clear_skip_flag()
                    self._logger.debug(f"[{serial}] 🧹 Skip flag cleared before clicking {user_name}")
                except Exception as e:
                    self._logger.warning(f"[{serial}] Failed to clear skip flag before click: {e}")

            clicked = await wecom.click_user_in_list(user_name, user_channel)
            if not clicked:
                self._logger.warning(f"[{serial}]    Could not click on {user_name}, skipping")
                prev_until, prev_count = self._click_fail_cooldown.get(cooldown_key, (0.0, 0))
                new_count = prev_count + 1
                if new_count >= 3:
                    cooldown_secs = 600.0
                elif new_count == 2:
                    cooldown_secs = 300.0
                else:
                    cooldown_secs = 120.0
                self._click_fail_cooldown[cooldown_key] = (time.time() + cooldown_secs, new_count)
                self._logger.info(
                    f"[{serial}]    Click cooldown set for {user_name}: {int(cooldown_secs)}s (failure #{new_count})"
                )
                metrics.log_error(
                    error_type="click_failed",
                    error_message=f"Could not click on {user_name}",
                    customer_name=user_name,
                    context={"serial": serial, "fail_count": new_count, "cooldown_seconds": cooldown_secs},
                )
                return result

            # Click succeeded — clear any prior cooldown for this customer
            self._click_fail_cooldown.pop(cooldown_key, None)

            await asyncio.sleep(1.0)

            # Step 2: Extract visible messages (no scrolling)
            self._logger.info(f"[{serial}]    Step 2: Extracting visible messages...")
            messages = await self._extract_visible_messages(wecom, serial)

            if not messages:
                self._logger.warning(f"[{serial}]    No messages extracted, going back")
                await wecom.go_back()
                await asyncio.sleep(0.5)
                return result

            self._logger.info(f"[{serial}]    Extracted {len(messages)} messages")

            # Check if any of these messages indicate the user deleted us
            for msg in messages:
                content = getattr(msg, "content", "") or ""
                if getattr(msg, "message_type", "") == "system" and wecom.ui_parser.is_user_deleted_message(content):
                    self._logger.info(f"[{serial}] 🚫 Detected user deletion message: {content}")
                    from wecom_automation.services.blacklist_service import BlacklistWriter

                    writer = BlacklistWriter()

                    # Log user deletion
                    customer_id = self._repository.find_or_create_customer(user_name, user_channel, serial)
                    metrics.log_user_deleted(
                        customer_db_id=customer_id,
                        customer_name=user_name,
                        channel=user_channel,
                        detected_message=content,
                    )

                    writer.add_to_blacklist(
                        device_serial=serial,
                        customer_name=user_name,
                        customer_channel=user_channel,
                        reason="User deleted/blocked",
                        deleted_by_user=True,
                        customer_db_id=customer_id,
                    )
                    self._logger.info(f"[{serial}] ✅ Automatically added {user_name} to blacklist")

                    # Store this system message and return early
                    await self._store_messages_to_db(user_name, user_channel, [msg], serial, wecom)
                    await wecom.go_back()
                    await asyncio.sleep(0.5)
                    return result

            # Step 3: Store messages to database
            self._logger.info(f"[{serial}]    Step 2b: Preloading media files...")
            await self._preload_media_for_messages(
                wecom, serial, messages, user_name=user_name, user_channel=user_channel
            )

            # Step 3: Store messages to database
            self._logger.info(f"[{serial}]    Step 3: Storing messages to database...")
            stored_count, message_db_ids = await self._store_messages_to_db(
                user_name, user_channel, messages, serial, wecom
            )
            result["messages_stored"] = stored_count
            result["message_db_ids"] = message_db_ids
            # Record metrics
            metrics.record_messages_stored(stored_count)
            self._logger.info(f"[{serial}]    Stored {stored_count} new messages")

            # Get customer_id for metrics
            customer_id = self._repository.find_or_create_customer(user_name, user_channel, serial)

            # Step 4: Find last customer message and reply
            last_customer_msg = None
            for msg in reversed(messages):
                if not getattr(msg, "is_self", False):
                    last_customer_msg = msg
                    break

            if last_customer_msg:
                content = getattr(last_customer_msg, "content", "") or ""
                self._logger.info(f"[{serial}]    Step 4: Last customer message: {content[:40]}...")

                # Get the message DB ID of the last customer message for metrics.
                # message_db_ids is ordered the same as messages (stored in order).
                # Walk backwards through both lists to find the matching customer msg ID.
                last_customer_msg_db_id = None
                if message_db_ids:
                    for i, msg in enumerate(reversed(messages)):
                        if not getattr(msg, "is_self", False):
                            idx = len(message_db_ids) - 1 - i
                            if 0 <= idx < len(message_db_ids):
                                last_customer_msg_db_id = message_db_ids[idx]
                            break

                # Generate AI reply
                # Check for skip before generating AI reply
                if sidecar_client:
                    try:
                        if await sidecar_client.is_skip_requested():
                            self._logger.info(f"[{serial}] ⏭️ Skip requested before AI reply - skipping user")
                            # Bubble up so outer loop can handle skip exactly once
                            raise SkipRequested()
                    except SkipRequested:
                        # Re-raise SkipRequested to propagate it properly
                        raise
                    except Exception as e:
                        # Log detailed error but continue processing (skip check is optional)
                        self._logger.warning(f"[{serial}] Error checking skip before AI: {type(e).__name__}: {e}")

                # Circuit breaker gate: skip AI call when breaker is open
                if not self._ai_circuit_breaker.allow_request():
                    self._logger.warning(f"[{serial}]    AI circuit breaker OPEN — skipping AI call for {user_name}")
                    metrics.log_error(
                        error_type="ai_circuit_open",
                        error_message="AI circuit breaker is open, skipping AI call",
                        customer_name=user_name,
                        context={"serial": serial, "circuit_state": self._ai_circuit_breaker.state.value},
                    )
                    reply = None
                    ai_generation_time = 0.0
                else:
                    ai_start_time = time.time()
                    reply = await self._generate_reply(user_name, messages[-5:], serial, user_channel)
                    ai_generation_time = (time.time() - ai_start_time) * 1000

                    if reply:
                        self._ai_circuit_breaker.record_success()
                    else:
                        self._ai_circuit_breaker.record_failure()

                if reply:
                    self._logger.info(f"[{serial}]    Sending reply: {reply[:40]}...")

                    # Log AI reply generation
                    if last_customer_msg_db_id:
                        metrics.log_ai_reply_generated(
                            customer_db_id=customer_id,
                            customer_name=user_name,
                            reply_to_message_db_id=last_customer_msg_db_id,
                            reply_content=reply,
                            generation_time_ms=ai_generation_time,
                        )
                    # Update counter
                    metrics.record_ai_reply_generated()

                    # Use helper to send via Sidecar or Direct
                    success, sent_text = await self._send_reply_wrapper(
                        wecom, serial, user_name, user_channel, reply, sidecar_client
                    )

                    if success:
                        self._logger.info(
                            f"[{serial}]    ✅ Reply sent (via {'Sidecar' if sidecar_client else 'Direct'})"
                        )
                        result["reply_sent"] = True
                        result["reply_text"] = (sent_text or reply)[:50]

                        # Store sent message and get DB ID
                        reply_db_id = await self._store_sent_message(
                            user_name, user_channel, sent_text or reply, serial
                        )
                        result["messages_stored"] += 1

                        # Log reply sent
                        metrics.log_reply_sent(
                            customer_name=user_name,
                            success=True,
                            method="sidecar" if sidecar_client else "direct",
                            reply_db_id=reply_db_id,
                        )

                        # === Image Sender: 检测固定回复关键词，追加发送收藏图片 ===
                        await self._maybe_send_favorite_image(wecom, serial, sent_text or reply)
                    else:
                        # Log reply failed
                        metrics.log_reply_sent(
                            customer_name=user_name,
                            success=False,
                            method="sidecar" if sidecar_client else "direct",
                            error="Failed to send reply",
                        )
                else:
                    metrics.log_reply_sent(
                        customer_name=user_name,
                        success=False,
                        method="none",
                        error="ai_generation_failed",
                    )
                    metrics.log_error(
                        error_type="ai_no_reply",
                        error_message="AI returned None, customer not replied",
                        customer_name=user_name,
                        context={
                            "ai_generation_time_ms": ai_generation_time,
                            "serial": serial,
                            "circuit_state": self._ai_circuit_breaker.state.value,
                        },
                    )
            else:
                self._logger.info(f"[{serial}]    No customer message found (last message is from agent)")

            # Step 5: Interactive wait loop
            await self._interactive_wait_loop(
                wecom,
                serial,
                user_name,
                user_channel,
                messages,
                result,
                timeout=interactive_wait_timeout,
                sidecar_client=sidecar_client,
            )

            # Step 6: Log conversation context (L4)
            if message_db_ids:
                try:
                    # Build conversation thread (message ID chain)
                    conversation_thread = []
                    conversation_snapshot = []
                    ai_reply_db_ids = []

                    # Get today's messages from database
                    from wecom_automation.database.repository import ConversationRepository

                    repo = ConversationRepository(self._repository._db_path)
                    db_messages = repo.get_recent_messages_for_customer(customer_id, limit=50)

                    # Build thread and snapshot
                    for msg in db_messages:
                        sender = "kefu" if msg.is_from_kefu else "customer"
                        conversation_thread.append(
                            {
                                "db_id": msg.id,
                                "sender": sender,
                            }
                        )

                        # Add to snapshot (last 10 messages)
                        if len(conversation_snapshot) < 10:
                            conversation_snapshot.append(
                                {
                                    "db_id": msg.id,
                                    "sender": sender,
                                    "content": msg.content[:100] if msg.content else "",  # Truncate long content
                                    "type": msg.message_type.value,
                                }
                            )

                        # Track AI replies
                        if msg.is_from_kefu:
                            ai_reply_db_ids.append(msg.id)

                    # Log conversation context
                    metrics.log_conversation_context(
                        customer_db_id=customer_id,
                        customer_name=user_name,
                        channel=user_channel,
                        today_message_db_ids=message_db_ids,
                        today_ai_reply_db_ids=ai_reply_db_ids,
                        conversation_thread=conversation_thread,
                        conversation_snapshot=conversation_snapshot,
                    )
                except Exception as ctx_error:
                    self._logger.debug(f"[{serial}] Failed to log conversation context: {ctx_error}")

            # Step 7: Go back to list and ensure we're on private chats
            self._logger.info(f"[{serial}]    Returning to private chats list...")
            await wecom.go_back()
            await asyncio.sleep(0.5)
            if not await wecom.ensure_on_private_chats():
                self._logger.warning(f"[{serial}]    Could not confirm return to private chats list")

        except SkipRequested:
            # Let caller handle skip once (including go_back + clear skip flag)
            raise
        except Exception as user_error:
            import traceback

            self._logger.error(f"[{serial}]    Error processing {user_name}: {user_error}")
            self._logger.debug(f"[{serial}]    Traceback: {traceback.format_exc()}")
            try:
                await wecom.go_back()
                await asyncio.sleep(0.5)
                await wecom.ensure_on_private_chats()
            except Exception:
                pass

        return result

    async def _interactive_wait_loop(
        self,
        wecom,
        serial: str,
        user_name: str,
        user_channel: str | None,
        initial_messages: list[Any],
        result: dict[str, Any],
        timeout: int = 40,
        sidecar_client: Any | None = None,
    ) -> None:
        """
        交互等待循环 - 使用锚点检测算法

        锚点算法优势：
        1. 不依赖 is_self（避免 UI 解析误判）
        2. 不依赖 timestamp（避免同分钟消息冲突）
        3. 用内容+位置识别新消息
        """
        self._logger.info(f"[{serial}]    ⏳ Waiting for new customer messages (timeout={timeout}s)...")

        # 使用锚点追踪器替代简单签名集合
        tracker = MessageTracker(serial=serial)
        tracker.record_current_state(initial_messages)

        # 日志: 初始消息列表
        self._logger.info(f"[{serial}]    初始消息 ({len(initial_messages)} 条):")
        for i, msg in enumerate(initial_messages):
            content = (getattr(msg, "content", "") or "")[:40]
            is_self = getattr(msg, "is_self", None)
            sender = "KEFU" if is_self else "CUST"
            self._logger.info(f"[{serial}]      [{i}] [{sender}] {content}...")

        stats = tracker.get_stats()
        self._logger.debug(
            f"[{serial}]    Tracker initialized: {stats['last_count']} msgs, {stats['processed_count']} signatures"
        )

        start_time = time.time()
        poll_interval = 3.0
        try:
            from services.settings import get_settings_service

            settings_service = get_settings_service()
            if settings_service.is_low_spec_mode():
                poll_interval = max(poll_interval, 5.0)
        except Exception:
            pass
        max_rounds = 10
        round_count = 0

        while round_count < max_rounds and not self._cancel_requested:
            # Check for skip flag at start of each poll iteration
            if sidecar_client:
                try:
                    if await sidecar_client.is_skip_requested():
                        self._logger.info(f"[{serial}] ⏭️ Skip detected during wait - stopping user processing")
                        raise SkipRequested()
                except SkipRequested:
                    # Re-raise SkipRequested to propagate it properly
                    raise
                except Exception as e:
                    # Log detailed error but continue processing (skip check is optional)
                    self._logger.warning(f"[{serial}] Error checking skip during wait: {type(e).__name__}: {e}")

            elapsed = time.time() - start_time
            if elapsed >= timeout:
                self._logger.info(f"[{serial}]    ⏰ Timeout ({timeout}s), no new customer messages")
                break

            # Wait before polling
            await asyncio.sleep(poll_interval)

            # Extract current visible messages
            current_messages = await self._extract_visible_messages(wecom, serial)
            if not current_messages:
                continue

            # 使用锚点算法找出新的客户消息
            # 【关键】使用 find_new_customer_messages() 而非手动过滤
            # 这样可以利用 is_self 缓存，防止 Agent 消息被误判为客户消息
            new_customer_messages = tracker.find_new_customer_messages(current_messages)

            if new_customer_messages:
                round_count += 1
                self._logger.info(
                    f"[{serial}]    📨 Round {round_count}: Found {len(new_customer_messages)} new customer message(s)"
                )

                # Pre-download media while the message is still visible so handlers can
                # persist the exact file instead of falling back to stale bounds.
                await self._preload_media_for_messages(
                    wecom,
                    serial,
                    new_customer_messages,
                    user_name=user_name,
                    user_channel=user_channel,
                )

                # Store new messages after media preloading
                stored_count, _ = await self._store_messages_to_db(
                    user_name, user_channel, new_customer_messages, serial, wecom
                )
                result["messages_stored"] += stored_count

                # Get the latest customer message
                latest_msg = new_customer_messages[-1]
                content = getattr(latest_msg, "content", "") or ""
                self._logger.info(f"[{serial}]    Customer: {content[:40]}...")

                # Generate and send reply (with circuit breaker)
                loop_metrics = get_metrics_logger(serial)
                if not self._ai_circuit_breaker.allow_request():
                    self._logger.warning(f"[{serial}]    AI circuit breaker OPEN — skipping AI in interactive loop")
                    reply = None
                else:
                    reply = await self._generate_reply(user_name, current_messages[-5:], serial, user_channel)
                    if reply:
                        self._ai_circuit_breaker.record_success()
                    else:
                        self._ai_circuit_breaker.record_failure()

                if reply:
                    success, sent_text = await self._send_reply_wrapper(
                        wecom, serial, user_name, user_channel, reply, sidecar_client
                    )

                    if success:
                        self._logger.info(f"[{serial}]    ✅ Reply sent: {(sent_text or reply)[:40]}...")
                        result["reply_sent"] = True

                        # Store sent message
                        reply_db_id = await self._store_sent_message(
                            user_name, user_channel, sent_text or reply, serial
                        )
                        result["messages_stored"] += 1

                        loop_metrics.log_reply_sent(
                            customer_name=user_name,
                            success=True,
                            method="sidecar" if sidecar_client else "direct",
                            reply_db_id=reply_db_id,
                        )
                        loop_metrics.record_ai_reply_generated()

                        # === Image Sender: 检测固定回复关键词，追加发送收藏图片 ===
                        await self._maybe_send_favorite_image(wecom, serial, sent_text or reply)

                        # 等待消息发送完成，重新获取消息列表，更新追踪器
                        await asyncio.sleep(1)
                        updated_messages = await self._extract_visible_messages(wecom, serial)
                        tracker.record_current_state(updated_messages)
                    else:
                        loop_metrics.log_reply_sent(
                            customer_name=user_name,
                            success=False,
                            method="sidecar" if sidecar_client else "direct",
                            error="send_failed_in_interactive_loop",
                        )
                else:
                    loop_metrics.log_error(
                        error_type="ai_no_reply_interactive",
                        error_message="AI returned None in interactive wait loop",
                        customer_name=user_name,
                        context={"serial": serial, "circuit_state": self._ai_circuit_breaker.state.value},
                    )

                # Reset timeout after customer interaction
                start_time = time.time()

            # Debug: 输出追踪器状态
            stats = tracker.get_stats()
            self._logger.debug(
                f"[{serial}]    Tracker: last={stats['last_count']}, processed={stats['processed_count']}, "
                f"is_self_cache={stats.get('is_self_cache_count', 0)}"
            )

        if round_count >= max_rounds:
            self._logger.warning(f"[{serial}]    ⚠️ Reached max rounds ({max_rounds})")

    async def _handle_skip_once(self, wecom, serial: str, sidecar_client: Any | None) -> None:
        """
        Handle skip request exactly once, avoiding double go_back.

        Behavior:
        - Clear skip flag immediately (so subsequent loops won't re-handle it)
        - Navigate back to main page unless already there
        - This ensures follow-up always starts from the correct page

        Screen states:
        - "private_chats" → Already on main page, skip go_back
        - "chat" → In conversation, go back to main page
        - "other" → On other WeCom screens, go back to main page
        - "unknown"/None → Cannot determine, defensively go back
        """
        # Clear skip flag early to prevent duplicate handling
        if sidecar_client:
            try:
                await sidecar_client.clear_skip_flag()
                self._logger.debug(f"[{serial}] ✅ Skip flag cleared")
            except Exception as e:
                self._logger.warning(f"[{serial}] ⚠️ Failed to clear skip flag: {e}")

        # Detect current screen and navigate back to main page if needed
        # Use inverted logic: go_back for ALL screens except "private_chats" (main page)
        try:
            screen = await wecom.get_current_screen()
            self._logger.info(f"[{serial}] 🔍 Skip handler detected screen: {screen}")
        except Exception as e:
            self._logger.warning(f"[{serial}] Screen detection failed during skip: {e}")
            screen = None  # Treat as unknown, will defensively go back

        # Only skip go_back if we're CONFIRMED to be on private_chats list (main page)
        # All other states (chat, other, unknown, None) should go back
        if screen not in ["private_chats"]:
            try:
                await wecom.go_back()
                await asyncio.sleep(0.5)
                self._logger.info(f"[{serial}] ✅ Navigated back from screen: {screen} → main page")
            except Exception as e:
                self._logger.warning(f"[{serial}] Error during go_back (skip handling): {e}")
        else:
            self._logger.info(f"[{serial}] ✅ Already on main page (private_chats), no go_back needed")

    async def _capture_avatar_before_click(
        self,
        wecom,
        serial: str,
        user_name: str,
    ) -> Path | None:
        """
        在点击用户进入对话之前，在列表页截取用户头像

        头像截取必须在列表页进行，因为点击后会进入对话页，
        对话页无法看到用户头像。

        Args:
            wecom: WeComService 实例
            serial: 设备序列号
            user_name: 用户名

        Returns:
            头像路径，如果失败则返回 None
        """
        if not HAS_AVATAR_MANAGER:
            self._logger.debug(f"[{serial}] AvatarManager not available, skipping avatar capture")
            return None

        try:
            # 获取头像保存目录
            # 使用与主同步相同的目录结构
            db_path = Path(self._repository._db_path)
            project_root = db_path.parent
            avatars_dir = project_root / "avatars"
            avatars_dir.mkdir(parents=True, exist_ok=True)

            self._logger.debug(f"[{serial}] Avatar dir: {avatars_dir}")

            # 创建 AvatarManager 实例
            avatar_manager = AvatarManager(
                wecom_service=wecom,
                avatars_dir=avatars_dir,
                logger=self._logger,
            )

            # 检查是否已缓存
            if avatar_manager.is_cached(user_name):
                cached_path = avatar_manager.get_path(user_name)
                self._logger.info(f"[{serial}]    📷 Avatar already cached: {cached_path}")
                return cached_path

            # 尝试捕获头像（不滚动，当前页面即可）
            avatar_path = await avatar_manager.capture(user_name, max_scroll_attempts=0)

            if avatar_path and avatar_path.exists():
                self._logger.info(f"[{serial}]    📷 Avatar captured: {avatar_path.name}")
                return avatar_path
            else:
                self._logger.debug(f"[{serial}]    📷 Avatar capture failed for: {user_name}")
                return None

        except Exception as e:
            self._logger.warning(f"[{serial}] Avatar capture error: {e}")
            return None

    async def _extract_visible_messages(self, wecom, serial: str) -> list[Any]:
        """提取当前可见消息（不滚动）"""
        try:
            tree, _ = await wecom.adb.get_ui_state()
            if not tree:
                return []
            return wecom.ui_parser.extract_conversation_messages(tree)
        except Exception as e:
            self._logger.warning(f"[{serial}] Failed to extract messages: {e}")
            return []

    async def _preload_media_for_messages(
        self,
        wecom,
        serial: str,
        messages: list[Any],
        *,
        user_name: str | None = None,
        user_channel: str | None = None,
    ) -> None:
        """
        Pre-download image/video files while messages are visible in the current chat view.

        This keeps realtime reply aligned with the verified manual test flow:
        - images use fullscreen capture
        - videos use WeCom "save to phone" + adb pull

        The downloaded paths are attached to the message objects so the existing
        message handlers can store them without falling back to stale bounds.

        Images and videos are saved under conversation_images/customer_{id}/ and
        conversation_videos/customer_{id}/ when user_name is provided so storage matches
        the post-DB layout (videos are renamed to video_{message_id}_* when stored).

        Skips media sent by the current kefu (is_self=True) so we do not open or
        screenshot the agent's own images/videos on the initial full-list preload.

        When customer_id is known, skips download for image/video messages whose
        message_hash already exists in the DB (same logic as add_message_if_not_exists),
        so repeat visits to a chat do not re-download the same media.
        """
        if not messages:
            return

        from wecom_automation.database.repository import ConversationRepository
        from wecom_automation.services.message.dedupe_record import (
            image_message_record_for_dedupe,
            video_message_record_for_dedupe,
        )

        base_images_root = PROJECT_ROOT / "conversation_images"
        base_videos_root = PROJECT_ROOT / "conversation_videos"

        customer_id: int | None = None
        if user_name:
            try:
                customer_id = self._repository.find_or_create_customer(user_name, user_channel, serial)
            except Exception as exc:
                self._logger.warning(f"[{serial}] Preload: could not resolve customer for image folder: {exc}")
        if customer_id is not None:
            image_dir = base_images_root / f"customer_{customer_id}"
            # Same layout as post-DB storage: avoid flat conversation_videos + copy
            video_dir = base_videos_root / f"customer_{customer_id}"
        else:
            image_dir = base_images_root
            video_dir = base_videos_root
        image_dir.mkdir(parents=True, exist_ok=True)
        video_dir.mkdir(parents=True, exist_ok=True)

        dedupe_repo: ConversationRepository | None = None
        if customer_id is not None:
            dedupe_repo = ConversationRepository(self._repository._db_path)

        timestamp_prefix = datetime.now().strftime("%Y%m%d_%H%M%S")
        images_ok = 0
        videos_ok = 0

        for index, msg in enumerate(messages):
            msg_type = getattr(msg, "message_type", "")
            if msg_type in ("image", "video") and getattr(msg, "is_self", False):
                continue

            if msg_type == "image":
                image_info = getattr(msg, "image", None)
                if not image_info or not getattr(image_info, "bounds", None):
                    continue
                if getattr(image_info, "local_path", None):
                    existing_image = Path(image_info.local_path)
                    if existing_image.exists():
                        self._logger.info(f"[{serial}]    图片已下载，跳过预加载: {existing_image}")
                        continue

                if dedupe_repo is not None:
                    probe = image_message_record_for_dedupe(msg, customer_id)
                    if dedupe_repo.message_exists(probe):
                        self._logger.debug(f"[{serial}]    Preload skip image idx {index}: already in database")
                        continue

                output_path = image_dir / f"realtime_{serial}_{timestamp_prefix}_{index}.png"
                try:
                    success = await wecom._download_image_via_fullscreen(image_info, output_path)
                except Exception as exc:
                    self._logger.warning(
                        f"[{serial}] Failed to preload image at index {index}: {type(exc).__name__}: {exc}"
                    )
                    continue

                if success and output_path.exists():
                    image_info.local_path = str(output_path)
                    images_ok += 1
                    self._logger.info(f"[{serial}]    图片预加载已保存: {output_path}")
                else:
                    self._logger.warning(f"[{serial}] Failed to preload image at index {index}")

            elif msg_type == "video":
                existing_video_path = getattr(msg, "video_local_path", None)
                if existing_video_path:
                    existing_video = Path(existing_video_path)
                    if existing_video.exists():
                        continue

                if dedupe_repo is not None:
                    probe = video_message_record_for_dedupe(msg, customer_id)
                    if dedupe_repo.message_exists(probe):
                        self._logger.debug(f"[{serial}]    Preload skip video idx {index}: already in database")
                        continue

                try:
                    video_path = await wecom._download_video_inline(
                        msg,
                        video_dir,
                        index,
                        set(),
                    )
                except Exception as exc:
                    self._logger.warning(
                        f"[{serial}] Failed to preload video at index {index}: {type(exc).__name__}: {exc}"
                    )
                    continue

                if video_path:
                    msg.video_local_path = video_path
                    videos_ok += 1
                else:
                    self._logger.warning(f"[{serial}] Failed to preload video at index {index}")

        if images_ok or videos_ok:
            self._logger.info(f"[{serial}]    Media preload complete: {images_ok} image(s), {videos_ok} video(s)")

    async def _store_messages_to_db(
        self,
        user_name: str,
        user_channel: str | None,
        messages: list[Any],
        serial: str,
        wecom=None,
    ) -> tuple[int, list[int]]:
        """
        将消息存储到数据库 - 使用 MessageProcessor 统一处理

        使用与全量同步相同的 MessageProcessor，确保：
        1. 图片消息自动创建 ImageRecord
        2. 视频消息自动创建 VideoRecord
        3. 语音消息自动创建 VoiceRecord
        4. 与前端 history 界面完全兼容
        5. 正确保存客户和客服的所有消息（增强版）

        Returns:
            (stored_count, message_db_ids) - 存储的消息数量和消息数据库ID列表
        """

        from wecom_automation.core.interfaces import MessageContext
        from wecom_automation.database.repository import ConversationRepository
        from wecom_automation.services.message.processor import MessageProcessor

        stored_count = 0
        skipped_count = 0
        message_db_ids: list[int] = []

        # 统计信息
        customer_msg_count = 0
        kefu_msg_count = 0
        customer_stored = 0
        kefu_stored = 0

        try:
            # Get or create customer (returns int customer_id)
            customer_id = self._repository.find_or_create_customer(user_name, user_channel, serial)
            if not customer_id:
                self._logger.warning(f"[{serial}] Could not find/create customer: {user_name}")
                return 0, []

            # Create repository
            repo = ConversationRepository(self._repository._db_path)

            # Create MessageProcessor with handlers + media event bus
            processor = MessageProcessor(
                repository=repo,
                logger=self._logger,
                media_event_bus=self._media_event_bus,
            )
            if self._media_action_settings:
                processor.set_media_action_settings(self._media_action_settings)

            # Register handlers (same as full sync)
            await self._register_message_handlers(processor, wecom, serial)

            self._logger.info(f"[{serial}] 📊 Processing {len(messages)} messages for {user_name}...")

            # Process each message
            for idx, msg in enumerate(messages):
                try:
                    # Extract message properties for logging
                    is_self = getattr(msg, "is_self", None)
                    content = (getattr(msg, "content", "") or "")[:40]
                    msg_type = getattr(msg, "message_type", "unknown")
                    has_image = hasattr(msg, "image") and msg.image is not None

                    # Debug log for troubleshooting
                    self._logger.debug(
                        f"[{serial}]    [{idx + 1}/{len(messages)}] Processing: "
                        f"is_self={is_self}, type={msg_type}, has_image={has_image}, "
                        f"content={content[:20]}..."
                    )

                    # Count messages by type
                    if is_self:
                        kefu_msg_count += 1
                        msg_label = "👤 KEFU"
                    else:
                        customer_msg_count += 1
                        msg_label = "👨 CUSTOMER"

                    # Create message context
                    context = MessageContext(
                        customer_id=customer_id,
                        customer_name=user_name,
                        channel=user_channel,  # 修复：添加缺失的 channel 参数
                        device_serial=serial,
                        kefu_name="",  # 修复：kefu_name 是必需参数，使用空字符串
                    )

                    # Process message through MessageProcessor
                    result = await processor.process(msg, context)

                    if result.added:
                        stored_count += 1
                        if result.message_id:
                            message_db_ids.append(result.message_id)

                        # Count stored by type
                        if is_self:
                            kefu_stored += 1
                        else:
                            customer_stored += 1

                        self._logger.info(
                            f"[{serial}]    [{idx + 1}/{len(messages)}] ✅ {msg_label} stored: {content}... "
                            f"(type={msg_type}, db_id={result.message_id})"
                        )

                        # Log media storage
                        if result.extra and result.extra.get("path"):
                            self._logger.info(
                                f"[{serial}]       📎 Media: {result.message_type} -> {result.extra.get('path')}"
                            )
                    else:
                        skipped_count += 1
                        self._logger.debug(
                            f"[{serial}]    [{idx + 1}/{len(messages)}] ⏭️ {msg_label} skipped (duplicate): {content}..."
                        )

                except Exception as msg_error:
                    self._logger.warning(f"[{serial}]    [{idx + 1}/{len(messages)}] ❌ Error: {msg_error}")

            # Summary log
            self._logger.info(
                f"[{serial}] 📊 Storage summary for {user_name}:\n"
                f"       Total: {len(messages)} | Stored: {stored_count} | Skipped: {skipped_count}\n"
                f"       Customer messages: {customer_msg_count} total, {customer_stored} stored\n"
                f"       Kefu messages: {kefu_msg_count} total, {kefu_stored} stored"
            )

        except Exception as e:
            self._logger.error(f"[{serial}] Error storing messages: {e}")
            import traceback

            self._logger.debug(f"[{serial}] Traceback: {traceback.format_exc()}")

        # Notify frontend to refresh history if messages were stored
        if stored_count > 0:
            try:
                # 1. 通知全局 WebSocket（History 界面使用）
                from routers.global_websocket import broadcast_history_refresh

                customer_id = self._repository.find_or_create_customer(user_name, user_channel, serial)
                await broadcast_history_refresh(
                    customer_name=user_name,
                    channel=user_channel,
                    customer_id=customer_id,
                )
                self._logger.info(f"[{serial}] → Global WS: history_refresh for {user_name}")

                # 2. 仍然通知 Sidecar（兼容性，保留旧逻辑）
                from services.message_publisher import notify_history_refresh

                await notify_history_refresh(serial, user_name, user_channel)
                self._logger.debug(f"[{serial}] → Sidecar WS: history_refresh for {user_name}")

            except Exception as e:
                self._logger.warning(f"[{serial}] Error publishing refresh event: {e}")
                import traceback

                self._logger.debug(f"[{serial}] Traceback: {traceback.format_exc()}")

        return stored_count, message_db_ids

    async def _register_message_handlers(self, processor, wecom, serial: str):
        """注册消息处理器（与全量同步保持一致）

        注册顺序很重要：
        1. TextHandler 放在第一位，因为大多数消息是文本消息
           TextHandler.can_handle() 会检查 message_type=="text" 或者
           (message_type=="unknown" && 有content && 无媒体属性)
        2. 特殊类型处理器按优先级注册
        3. MediaHandlers 放在后面处理媒体消息
        """
        from wecom_automation.core.config import get_project_root
        from wecom_automation.services.message.handlers.image import ImageMessageHandler
        from wecom_automation.services.message.handlers.sticker import StickerMessageHandler
        from wecom_automation.services.message.handlers.text import TextMessageHandler
        from wecom_automation.services.message.handlers.video import VideoMessageHandler
        from wecom_automation.services.message.handlers.voice import VoiceMessageHandler

        project_root = get_project_root()

        # 1. Register Text Handler FIRST (most common message type)
        # TextHandler checks for message_type=="text" OR (unknown type with content and no media)
        text_handler = TextMessageHandler(
            repository=processor._repository,
            logger=self._logger,
        )
        processor.register_handler(text_handler)

        # 2. Register Sticker Handler (表情包消息)
        sticker_handler = StickerMessageHandler(
            repository=processor._repository,
            wecom_service=wecom,
            images_dir=project_root / "conversation_images",
            logger=self._logger,
        )
        processor.register_handler(sticker_handler)

        # 3. Register Voice Handler (语音消息 - 按时长识别)
        voice_handler = VoiceMessageHandler(
            repository=processor._repository,
            wecom_service=wecom,
            voices_dir=project_root / "conversation_voices",
            logger=self._logger,
        )
        processor.register_handler(voice_handler)

        # 4. Register Video Handler (视频消息 - 按时长或视频特征识别)
        video_handler = VideoMessageHandler(
            repository=processor._repository,
            wecom_service=wecom,
            videos_dir=project_root / "conversation_videos",
            logger=self._logger,
        )
        processor.register_handler(video_handler)

        # 5. Register Image Handler LAST (图片消息 - 需要 image.bounds)
        # 放在最后因为它的 can_handle() 条件比较宽松（检查 message.image.bounds）
        image_handler = ImageMessageHandler(
            repository=processor._repository,
            wecom_service=wecom,
            images_dir=project_root / "conversation_images",
            logger=self._logger,
            wait_for_review=True,
        )
        processor.register_handler(image_handler)

    async def _store_sent_message(
        self,
        user_name: str,
        user_channel: str | None,
        content: str,
        serial: str,
    ) -> int | None:
        """
        存储发送的消息

        Returns:
            消息数据库ID，如果存储失败则返回None
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from wecom_automation.database.models import MessageRecord, MessageType

        try:
            # find_or_create_customer returns int customer_id directly
            customer_id = self._repository.find_or_create_customer(user_name, user_channel, serial)
            if not customer_id:
                return None

            tz = ZoneInfo("Asia/Shanghai")
            now = datetime.now(tz)

            record = MessageRecord(
                customer_id=customer_id,
                content=content,
                message_type=MessageType.TEXT,
                is_from_kefu=True,
                timestamp_raw=now.strftime("%H:%M"),
                timestamp_parsed=now,
            )

            from wecom_automation.database.repository import ConversationRepository

            repo = ConversationRepository(self._repository._db_path)
            added, msg_record = repo.add_message_if_not_exists(record)

            # Notify frontend about the new message
            if added and customer_id and msg_record:
                try:
                    from services.message_publisher import notify_message_added

                    await notify_message_added(
                        serial,
                        customer_id,
                        user_name,
                        user_channel,
                        {
                            "content": content,
                            "is_from_kefu": True,
                            "message_type": "text",
                            "timestamp": now.isoformat(),
                        },
                    )
                except Exception as e:
                    self._logger.debug(f"[{serial}] Error publishing message event: {e}")

                # Return message database ID
                if hasattr(msg_record, "id"):
                    return msg_record.id

        except Exception as e:
            self._logger.debug(f"[{serial}] Error storing sent message: {e}")

        return None

    # ==================== Image Sender Integration ====================

    # 固定回复触发词列表 - 当 AI 回复包含这些关键词时，自动追加发送收藏图片
    # 你可以根据需要修改这个列表
    IMAGE_TRIGGER_KEYWORDS: list[str] = [
        "收入构成图",
    ]

    # 收藏项索引 - 发送 Favorites 中第几个图片（0 = 第一个）
    IMAGE_FAVORITE_INDEX: int = 0

    async def _maybe_send_favorite_image(
        self,
        wecom_service: Any,
        serial: str,
        sent_text: str,
    ) -> bool:
        """
        检测 AI 回复内容，如果包含触发关键词，则追加发送收藏中的图片。

        触发条件：sent_text 中包含 IMAGE_TRIGGER_KEYWORDS 中的任意一个关键词。

        使用方法：
        1. 在 IMAGE_TRIGGER_KEYWORDS 列表中添加你的触发关键词
        2. 设置 IMAGE_FAVORITE_INDEX 为要发送的收藏项索引

        Args:
            wecom_service: WeComService 实例（当前在对话界面中）
            serial: 设备序列号
            sent_text: AI 回复的实际文本内容

        Returns:
            是否成功发送了图片
        """
        if not self.IMAGE_TRIGGER_KEYWORDS:
            return False

        # 检查是否匹配任何触发关键词
        matched_keyword = None
        for keyword in self.IMAGE_TRIGGER_KEYWORDS:
            if keyword and keyword in sent_text:
                matched_keyword = keyword
                break

        if not matched_keyword:
            return False

        self._logger.info(
            f"[{serial}]    🖼️ Trigger keyword detected: '{matched_keyword}' → sending favorite image (index={self.IMAGE_FAVORITE_INDEX})"
        )

        try:
            from wecom_automation.services.message.image_sender import ImageSender

            sender = ImageSender(wecom_service)

            # 等待文本消息发送完成后再发图片
            await asyncio.sleep(1.5)

            success = await sender.send_via_favorites(favorite_index=self.IMAGE_FAVORITE_INDEX)

            if success:
                self._logger.info(f"[{serial}]    🖼️ ✅ Favorite image sent successfully")
            else:
                self._logger.warning(f"[{serial}]    🖼️ ❌ Failed to send favorite image")

            return success

        except Exception as e:
            self._logger.error(f"[{serial}]    🖼️ ❌ Error sending favorite image: {e}")
            return False

    async def _generate_reply(
        self,
        user_name: str,
        messages: list[Any],
        device_serial: str = "",
        user_channel: str | None = None,
        followup_prompt: str | None = None,
    ) -> str | None:
        """
        生成 AI 回复

        复用 AIReplyService 替代原来的 _generate_reply_for_response()

        优先从数据库获取完整的聊天历史记录，以提高回复质量。

        Args:
            followup_prompt: 补刀场景专用提示词，会拼接到 user_prompt 中
        如果数据库不可用，回退到使用传入的 UI 提取消息。
        """
        _gen_metrics = get_metrics_logger(device_serial)

        # Try to get FULL conversation history from database for better context
        context_messages = messages  # Default to UI-extracted messages

        try:
            from types import SimpleNamespace

            from wecom_automation.database.repository import ConversationRepository

            # Get database path from the FollowUp repository
            db_path = self._repository._db_path
            repo = ConversationRepository(db_path)

            # Get customer_id - try with channel first, then without
            customer_id = None
            if user_channel is not None:
                customer_id = self._repository.find_or_create_customer(user_name, user_channel, device_serial)

            if not customer_id:
                # Try without channel
                customer_id = self._repository.find_or_create_customer(user_name, None, device_serial)

            if customer_id:
                # Query ALL messages from database (use large limit to get full history)
                # 获取完整的聊天记录，最多100条
                db_messages = repo.get_recent_messages_for_customer(customer_id, limit=100)

                if db_messages:
                    self._logger.info(
                        f"[{device_serial}] 📚 Using FULL chat history: {len(db_messages)} messages from DB"
                    )
                    # Convert to format expected by AI context building
                    context_messages = [
                        SimpleNamespace(
                            is_self=msg.is_from_kefu,
                            content=msg.content,
                            timestamp=msg.timestamp_raw,
                            message_type=msg.message_type.value
                            if hasattr(msg.message_type, "value")
                            else str(msg.message_type),
                        )
                        for msg in db_messages
                    ]
                else:
                    self._logger.info(
                        f"[{device_serial}] ⚠️ No messages in DB, using UI messages ({len(messages)} msgs)"
                    )
            else:
                self._logger.info(
                    f"[{device_serial}] ⚠️ Customer not found in DB, using UI messages ({len(messages)} msgs)"
                )
        except Exception as e:
            self._logger.warning(f"[{device_serial}] Failed to get DB history: {e}, using UI messages")
            import traceback

            self._logger.debug(f"[{device_serial}] {traceback.format_exc()}")

        ai_server_url = "http://47.113.187.234:8000"

        try:
            # Try to use AIReplyService from full sync module
            from routers.settings import load_settings as load_app_settings

            global_settings = load_app_settings()

            # Get AI configuration
            DEFAULT_AI_SERVER_URL = "http://47.113.187.234:8000"
            DEFAULT_AI_TIMEOUT = 15

            ai_server_url = global_settings.get("aiServerUrl", DEFAULT_AI_SERVER_URL)
            if not ai_server_url:
                ai_server_url = global_settings.get("ai_server_url", DEFAULT_AI_SERVER_URL)

            ai_timeout = global_settings.get("aiReplyTimeout", DEFAULT_AI_TIMEOUT)
            # Use combined system prompt (custom + preset style)
            from services.settings import get_settings_service

            settings_service = get_settings_service()
            system_prompt = settings_service.get_combined_system_prompt()

            # Ensure URL ends with /chat
            if not ai_server_url.endswith("/chat"):
                ai_server_url = ai_server_url.rstrip("/") + "/chat"

            # Build conversation context from context_messages (DB or UI)
            # 使用完整聊天记录构建上下文
            context_lines = []
            for msg in context_messages:
                role = "AGENT" if getattr(msg, "is_self", False) else "CUSTOMER"
                content = getattr(msg, "content", "") or "[media]"
                msg_type = getattr(msg, "message_type", "text")
                # 标注消息类型（如果不是文本）
                if msg_type and msg_type != "text":
                    content = f"[{msg_type}] {content}" if content != "[media]" else f"[{msg_type}]"
                context_lines.append(f"{role}: {content}")

            context = "\n".join(context_lines)

            # 找到最新的客户消息
            last_customer_msg = ""
            for msg in reversed(context_messages):
                if not getattr(msg, "is_self", False):
                    last_customer_msg = getattr(msg, "content", "") or ""
                    break

            # Build XML-structured prompt - 使用完整聊天记录
            # 判断是否为补刀场景
            is_followup_scenario = followup_prompt is not None

            if is_followup_scenario:
                # 补刀场景：客户长时间未回复，需要主动跟进
                final_input = f"""<task>
为客户 {user_name} 生成一条主动跟进消息。该客户已长时间未回复，需要友好地重新激活对话。
</task>

<context>
<scenario>补刀跟进场景</scenario>
<customer_name>{user_name}</customer_name>
<situation>客户已经长时间未回复消息，需要主动发起跟进以重新激活对话。</situation>
<business_background>这是一个直播经纪公司的客服场景，目标是招募主播，需要在保持专业的同时展现诚意。</business_background>
</context>

<conversation_history count="{len(context_messages)}">
{context}
</conversation_history>

<custom_instructions>
{followup_prompt}
</custom_instructions>

<system_prompt>
{system_prompt if system_prompt else "使用礼貌、友好的语气。"}
</system_prompt>

<output_format>
直接输出跟进消息文本，不要包含任何解释、标签或格式标记。
</output_format>"""
            else:
                # 正常回复场景：客户发送了消息，需要回复
                final_input = f"""<task>
为客户 {user_name} 的最新消息生成一条合适的回复。
</task>

<context>
<scenario>实时回复场景</scenario>
<customer_name>{user_name}</customer_name>
<situation>客户发送了新消息，需要及时、恰当地回复。</situation>
<business_background>这是一个直播经纪公司的客服场景，目标是招募主播，同时需要专业地处理各种客户咨询。</business_background>
</context>

<conversation_history count="{len(context_messages)}">
{context}
</conversation_history>

<latest_customer_message>
{last_customer_msg}
</latest_customer_message>

<system_prompt>
{system_prompt if system_prompt else "使用礼貌、友好的语气。"}
</system_prompt>

<constraints>
<special_commands>
如果客户要求转人工、找真人客服、或表示要人工服务，直接返回: command back to user operation
</special_commands>
</constraints>
"""

            # Use aiohttp to call AI service
            import aiohttp

            payload = {
                "chatInput": final_input,
                "sessionId": f"response_{user_name}_{device_serial}",
                "username": "response_system",
                "message_type": "text",
                "metadata": {
                    "source": "followup_response_detector",
                    "serial": device_serial,
                    "customer": user_name,
                    "context_length": len(context),
                },
            }

            # ===== AI Request Logging (XML Structured Prompt) =====
            scenario_type = "补刀跟进" if is_followup_scenario else "实时回复"
            self._logger.info(f"[{device_serial}] " + "=" * 60)
            self._logger.info(f"[{device_serial}] AI REQUEST for {user_name} [{scenario_type}]")
            self._logger.info(f"[{device_serial}] " + "=" * 60)
            self._logger.info(f"[{device_serial}] AI Server: {ai_server_url}")
            self._logger.info(f"[{device_serial}] Timeout: {ai_timeout}s")
            self._logger.info(f"[{device_serial}] Session ID: {payload['sessionId']}")
            self._logger.info(f"[{device_serial}] Prompt Format: XML Structured")
            self._logger.info(f"[{device_serial}] ")

            # 打印 XML 结构摘要
            self._logger.info(f"[{device_serial}] --- XML Prompt Structure ---")
            self._logger.info(
                f"[{device_serial}] <task> 为 {user_name} 生成{'跟进消息' if is_followup_scenario else '回复'}"
            )
            self._logger.info(f"[{device_serial}] <context> 场景={scenario_type}, 客户={user_name}")
            self._logger.info(f"[{device_serial}] <conversation_history> {len(context_messages)} 条消息")
            if is_followup_scenario:
                self._logger.info(f"[{device_serial}] <custom_instructions> {(followup_prompt or 'N/A')[:50]}...")
            else:
                self._logger.info(f"[{device_serial}] <latest_customer_message> {last_customer_msg[:50]}...")
            self._logger.info(f"[{device_serial}] <style_guidelines> {(system_prompt or '默认风格')[:40]}...")
            self._logger.info(f"[{device_serial}] <constraints> special_commands=转人工检测")
            self._logger.info(f"[{device_serial}] ")

            # 显示完整聊天记录摘要
            self._logger.info(f"[{device_serial}] --- 📚 Conversation History ({len(context_messages)} messages) ---")
            display_messages = context_messages
            if len(context_messages) > 20:
                self._logger.info(f"[{device_serial}] (Showing last 20 of {len(context_messages)} messages)")
                display_messages = context_messages[-20:]
                skipped = len(context_messages) - 20
                self._logger.info(f"[{device_serial}] ... ({skipped} earlier messages omitted) ...")

            for idx, msg in enumerate(display_messages):
                role = "👤 AGENT" if getattr(msg, "is_self", False) else "👨 CUSTOMER"
                content = getattr(msg, "content", "") or "[media]"
                msg_type = getattr(msg, "message_type", "text")
                type_indicator = f"[{msg_type}]" if msg_type and msg_type != "text" else ""
                content_display = content[:100] + "..." if len(content) > 100 else content
                self._logger.info(f"[{device_serial}] [{idx + 1}] {role}: {type_indicator}{content_display}")
            self._logger.info(f"[{device_serial}] " + "=" * 60)

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    ai_server_url, json=payload, timeout=aiohttp.ClientTimeout(total=ai_timeout)
                ) as response:
                    # ===== AI Response Logging =====
                    self._logger.info(f"[{device_serial}] " + "=" * 60)
                    self._logger.info(f"[{device_serial}] AI RESPONSE for {user_name}")
                    self._logger.info(f"[{device_serial}] " + "=" * 60)
                    self._logger.info(f"[{device_serial}] HTTP Status: {response.status}")

                    if response.status == 200:
                        data = await response.json()
                        ai_reply = data.get("output", data.get("response", ""))

                        self._logger.info(f"[{device_serial}] Response Data: {data}")
                        self._logger.info(f"[{device_serial}] ")
                        self._logger.info(f"[{device_serial}] --- AI Reply ---")
                        self._logger.info(f"[{device_serial}] {ai_reply}")
                        self._logger.info(f"[{device_serial}] " + "=" * 60)

                        # Check for human request command
                        if ai_reply and "command back to user operation" in ai_reply.lower():
                            self._logger.info(f"[{device_serial}] Human agent requested, stopping auto-reply")
                            _gen_metrics.log_error(
                                error_type="ai_human_transfer",
                                error_message="AI requested transfer to human agent",
                                customer_name=user_name,
                                context={"serial": device_serial},
                            )
                            return None

                        if ai_reply and len(ai_reply.strip()) > 0:
                            # Clean up potential XML tags that AI might include
                            import re

                            cleaned_reply = ai_reply.strip()
                            # Remove common XML wrapper tags that LLMs sometimes include
                            xml_tags_to_remove = [
                                r"</?response>",
                                r"</?output>",
                                r"</?reply>",
                                r"</?answer>",
                                r"</?message>",
                            ]
                            for pattern in xml_tags_to_remove:
                                cleaned_reply = re.sub(pattern, "", cleaned_reply, flags=re.IGNORECASE)
                            cleaned_reply = cleaned_reply.strip()

                            if cleaned_reply != ai_reply.strip():
                                self._logger.info(f"[{device_serial}] 🧹 Cleaned XML tags from AI reply")
                                self._logger.debug(f"[{device_serial}]    Original: {ai_reply[:80]}...")
                                self._logger.debug(f"[{device_serial}]    Cleaned: {cleaned_reply[:80]}...")

                            self._logger.info(f"[{device_serial}] ✅ Generated reply: {cleaned_reply[:50]}...")
                            return cleaned_reply
                        else:
                            self._logger.warning(f"[{device_serial}] AI returned empty reply")
                            self._logger.info(f"[{device_serial}] " + "=" * 60)
                            _gen_metrics.log_error(
                                error_type="ai_empty_reply",
                                error_message="AI returned an empty reply",
                                customer_name=user_name,
                                context={"serial": device_serial, "ai_server_url": ai_server_url},
                            )
                    else:
                        response_text = await response.text()
                        self._logger.warning(f"[{device_serial}] AI server returned {response.status}")
                        self._logger.warning(f"[{device_serial}] Response body: {response_text}")
                        self._logger.info(f"[{device_serial}] " + "=" * 60)
                        _gen_metrics.log_error(
                            error_type="ai_http_error",
                            error_message=f"AI server returned HTTP {response.status}",
                            customer_name=user_name,
                            context={
                                "serial": device_serial,
                                "status_code": response.status,
                                "ai_server_url": ai_server_url,
                            },
                        )

        except TimeoutError:
            self._logger.warning(f"[{device_serial}] " + "=" * 60)
            self._logger.warning(f"[{device_serial}] AI REQUEST TIMEOUT")
            self._logger.warning(f"[{device_serial}] " + "=" * 60)
            self._logger.warning(f"[{device_serial}] Customer: {user_name}")
            self._logger.warning(f"[{device_serial}] Timeout after: {ai_timeout}s")
            self._logger.warning(f"[{device_serial}] AI Server: {ai_server_url}")
            self._logger.warning(f"[{device_serial}] " + "=" * 60)
            _gen_metrics.log_error(
                error_type="ai_timeout",
                error_message=f"AI request timed out after {ai_timeout}s",
                customer_name=user_name,
                context={"serial": device_serial, "timeout_seconds": ai_timeout, "ai_server_url": ai_server_url},
            )
        except Exception as e:
            self._logger.error(f"[{device_serial}] " + "=" * 60)
            self._logger.error(f"[{device_serial}] AI REQUEST ERROR")
            self._logger.error(f"[{device_serial}] " + "=" * 60)
            self._logger.error(f"[{device_serial}] Customer: {user_name}")
            self._logger.error(f"[{device_serial}] Error: {e}")
            self._logger.error(f"[{device_serial}] AI Server: {ai_server_url}")
            import traceback

            self._logger.error(f"[{device_serial}] Traceback:\n{traceback.format_exc()}")
            self._logger.error(f"[{device_serial}] " + "=" * 60)
            _gen_metrics.log_error(
                error_type="ai_connection_error",
                error_message=f"AI request failed: {type(e).__name__}: {e}",
                customer_name=user_name,
                context={"serial": device_serial, "exception_type": type(e).__name__, "ai_server_url": ai_server_url},
            )

        return None

    async def _try_followup_if_idle(
        self,
        wecom,
        serial: str,
        sidecar_client: Any | None = None,
    ) -> None:
        """
        在空闲时尝试执行补刀

        调用时机：实时回复扫描结束后，没有红点用户时

        流程：
        1. 检查补刀功能是否启用
        2. 从数据库获取最近对话，更新补刀队列
        3. 执行待补刀任务
        """
        from datetime import datetime

        from .queue_manager import (
            get_followup_queue_manager,
        )

        self._logger.info(f"[{serial}] ")
        self._logger.info(f"[{serial}] " + "╔" + "═" * 58 + "╗")
        self._logger.info(f"[{serial}] " + "║" + "           补刀检测 (FOLLOWUP CHECK)                      " + "║")
        self._logger.info(f"[{serial}] " + "╠" + "═" * 58 + "╣")
        self._logger.info(f"[{serial}] " + "║" + f"  触发时机: 红点用户处理完毕，进入空闲状态{' ' * 15}" + "║")
        self._logger.info(f"[{serial}] " + "║" + f"  设备: {serial[:48]:<50}" + "║")
        self._logger.info(f"[{serial}] " + "║" + f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):<50}" + "║")
        self._logger.info(f"[{serial}] " + "╚" + "═" * 58 + "╝")

        # 获取队列管理器
        self._logger.info(f"[{serial}] ")
        self._logger.info(f"[{serial}] 📋 获取补刀队列管理器...")
        queue_manager = get_followup_queue_manager(
            device_serial=serial,
            adb=wecom.adb.adb,  # Pass the underlying AdbTools instance, not ADBService
            db_path=self._repository._db_path,
            log_callback=lambda msg, level: self._logger.info(f"[{serial}] [Followup] {msg}"),
        )
        self._logger.info(f"[{serial}]    ✅ 队列管理器已获取")
        self._logger.info(f"[{serial}]    - db_path: {self._repository._db_path}")
        self._logger.info(f"[{serial}]    - attempts_db_path: {queue_manager._attempts_db_path}")

        # 检查是否启用
        self._logger.info(f"[{serial}] ")
        self._logger.info(f"[{serial}] 🔍 检查补刀功能状态...")
        is_enabled = queue_manager.is_enabled()
        self._logger.info(f"[{serial}]    - followup_enabled: {is_enabled}")

        if not is_enabled:
            self._logger.info(f"[{serial}]    ⚠️ 补刀功能未启用，跳过")
            self._logger.info(f"[{serial}] " + "─" * 60)
            return

        # 检查是否在工作时间内
        can_exec, reason = queue_manager.can_execute()
        self._logger.info(f"[{serial}]    - can_execute: {can_exec}")
        self._logger.info(f"[{serial}]    - reason: {reason}")

        if not can_exec:
            self._logger.info(f"[{serial}]    ⚠️ 无法执行补刀: {reason}")
            self._logger.info(f"[{serial}] " + "─" * 60)
            return

        self._logger.info(f"[{serial}]    ✅ 补刀功能已启用且在工作时间内")

        # Step 1: 从数据库获取最近的对话，构建 ConversationInfo 列表
        self._logger.info(f"[{serial}] ")
        self._logger.info(f"[{serial}] ┌{'─' * 56}┐")
        self._logger.info(f"[{serial}] │ Step 1: 构建对话列表 (从数据库)                       │")
        self._logger.info(f"[{serial}] └{'─' * 56}┘")

        conversations = await self._build_conversation_list(serial)

        if conversations:
            self._logger.info(f"[{serial}]    找到 {len(conversations)} 个近期对话")
            for idx, conv in enumerate(conversations[:5], 1):  # 只显示前5个
                sender_icon = "👤" if conv.last_message_sender == "kefu" else "👨"
                self._logger.info(
                    f"[{serial}]    {idx}. {conv.customer_name[:20]} | "
                    f"{sender_icon} {conv.last_message_sender} | "
                    f"{conv.last_message_time.strftime('%H:%M') if conv.last_message_time else 'N/A'}"
                )
            if len(conversations) > 5:
                self._logger.info(f"[{serial}]    ... 还有 {len(conversations) - 5} 个对话")

            # Step 2: 更新补刀队列
            self._logger.info(f"[{serial}] ")
            self._logger.info(f"[{serial}] ┌{'─' * 56}┐")
            self._logger.info(f"[{serial}] │ Step 2: 更新补刀队列                                 │")
            self._logger.info(f"[{serial}] └{'─' * 56}┘")

            queue_result = queue_manager.process_conversations(conversations)
            self._logger.info(f"[{serial}]    队列更新完成:")
            self._logger.info(f"[{serial}]    - 新增入队: {queue_result.get('added', 0)}")
            self._logger.info(f"[{serial}]    - 移出队列: {queue_result.get('removed', 0)}")
            self._logger.info(f"[{serial}]    - 阈值(分钟): {queue_result.get('threshold_minutes', 'N/A')}")
        else:
            self._logger.info(f"[{serial}]    ⚠️ 未找到近期对话")

        # Step 3: 获取待补刀数量
        self._logger.info(f"[{serial}] ")
        self._logger.info(f"[{serial}] ┌{'─' * 56}┐")
        self._logger.info(f"[{serial}] │ Step 3: 检查待补刀队列                               │")
        self._logger.info(f"[{serial}] └{'─' * 56}┘")

        pending_count = queue_manager.get_pending_count()
        self._logger.info(f"[{serial}]    待补刀数量: {pending_count}")

        if pending_count == 0:
            self._logger.info(f"[{serial}]    ✅ 无待补刀任务，补刀检测完成")
            self._logger.info(f"[{serial}] " + "─" * 60)
            return

        # 获取待补刀列表详情
        pending_list = queue_manager.get_pending_list(limit=10)
        self._logger.info(f"[{serial}]    待补刀列表:")
        for idx, attempt in enumerate(pending_list, 1):
            self._logger.info(
                f"[{serial}]    {idx}. {attempt.customer_name[:25]} | "
                f"第{attempt.current_attempt + 1}/{attempt.max_attempts}次"
            )

        # Step 4: 执行补刀
        self._logger.info(f"[{serial}] ")
        self._logger.info(f"[{serial}] ┌{'─' * 56}┐")
        self._logger.info(f"[{serial}] │ Step 4: 执行补刀任务                                 │")
        self._logger.info(f"[{serial}] └{'─' * 56}┘")

        # 定义跳过检查函数
        def skip_check() -> bool:
            return self._cancel_requested

        # 检查 AI 回复设置
        settings = queue_manager._get_settings()
        self._logger.info(f"[{serial}]    补刀配置:")
        self._logger.info(f"[{serial}]    - use_ai_reply: {settings.use_ai_reply}")
        self._logger.info(f"[{serial}]    - followup_prompt: {(settings.followup_prompt or 'N/A')[:40]}...")
        self._logger.info(f"[{serial}]    - message_templates: {len(settings.message_templates or [])} 个")

        # 定义 AI 回复回调（如果启用 AI）
        async def ai_reply_callback(customer_name: str, prompt: str) -> str | None:
            """使用 AI 生成补刀消息"""
            self._logger.info(f"[{serial}]    🤖 AI 回复回调被调用:")
            self._logger.info(f"[{serial}]       - customer: {customer_name}")
            self._logger.info(f"[{serial}]       - prompt: {prompt[:40]}...")

            try:
                # 构建简单的上下文
                from types import SimpleNamespace

                messages = [
                    SimpleNamespace(
                        is_self=False,
                        content=f"[补刀场景] 客户 {customer_name} 长时间未回复",
                    )
                ]

                # 获取补刀设置中的 prompt
                actual_followup_prompt = settings.followup_prompt or prompt
                self._logger.info(f"[{serial}]       调用 _generate_reply...")
                self._logger.info(f"[{serial}]       - 使用的补刀提示词: {actual_followup_prompt[:60]}...")

                # 构建带补刀提示的 AI 请求
                # 复用现有的 AI 回复生成逻辑，传入补刀提示词
                original_reply = await self._generate_reply(
                    customer_name, messages, serial, None, followup_prompt=actual_followup_prompt
                )

                if original_reply:
                    self._logger.info(f"[{serial}]       ✅ AI 生成成功: {original_reply[:40]}...")
                    return original_reply
                else:
                    self._logger.info(f"[{serial}]       ⚠️ AI 返回空回复")

            except Exception as e:
                self._logger.warning(f"[{serial}]       ❌ AI 生成失败: {e}")
                import traceback

                self._logger.debug(f"[{serial}]       {traceback.format_exc()}")

            return None

        # 执行补刀
        self._logger.info(f"[{serial}]    🚀 开始执行补刀...")
        followup_result = await queue_manager.execute_pending_followups(
            skip_check=skip_check,
            ai_reply_callback=ai_reply_callback if settings.use_ai_reply else None,
        )

        # 输出执行结果
        self._logger.info(f"[{serial}] ")
        self._logger.info(f"[{serial}] " + "╔" + "═" * 58 + "╗")
        self._logger.info(f"[{serial}] " + "║" + "           补刀执行结果                                  " + "║")
        self._logger.info(f"[{serial}] " + "╠" + "═" * 58 + "╣")
        self._logger.info(f"[{serial}] " + "║" + f"  executed: {followup_result.get('executed', False):<46}" + "║")
        self._logger.info(f"[{serial}] " + "║" + f"  total: {followup_result.get('total', 0):<49}" + "║")
        self._logger.info(f"[{serial}] " + "║" + f"  success: {followup_result.get('success', 0):<47}" + "║")
        self._logger.info(f"[{serial}] " + "║" + f"  failed: {followup_result.get('failed', 0):<48}" + "║")
        self._logger.info(f"[{serial}] " + "║" + f"  skipped: {followup_result.get('skipped', 0):<47}" + "║")
        self._logger.info(f"[{serial}] " + "╚" + "═" * 58 + "╝")

        # 输出详细结果
        details = followup_result.get("details", [])
        if details:
            self._logger.info(f"[{serial}]    详细结果:")
            for idx, detail in enumerate(details, 1):
                status_icon = (
                    "✅" if detail.get("status") == "success" else "❌" if detail.get("status") == "failed" else "⏭️"
                )
                duration = detail.get("duration_ms", 0)
                self._logger.info(
                    f"[{serial}]    {idx}. {status_icon} {detail.get('customer', 'N/A')[:25]} | "
                    f"{detail.get('status', 'N/A')} | {duration}ms"
                )
                if detail.get("error"):
                    self._logger.info(f"[{serial}]       错误: {detail.get('error')[:50]}")

        self._logger.info(f"[{serial}] " + "─" * 60)

    async def _build_conversation_list(self, serial: str) -> list[Any]:
        """
        从数据库构建最近对话列表

        查询最近有消息的客户，获取每个客户的最后一条消息信息
        """
        from datetime import datetime, timedelta

        from .queue_manager import ConversationInfo

        conversations = []

        self._logger.info(f"[{serial}]    📊 构建对话列表:")
        self._logger.info(f"[{serial}]       - 数据库: {self._repository._db_path}")

        try:
            # 获取最近 24 小时内有消息的客户
            import sqlite3

            conn = sqlite3.connect(self._repository._db_path)
            conn.row_factory = sqlite3.Row

            # 查询最近有消息的客户（最近 24 小时）
            cutoff_time = (datetime.now() - timedelta(hours=24)).isoformat()
            self._logger.info(f"[{serial}]       - 时间范围: 最近 24 小时")
            self._logger.info(f"[{serial}]       - 截止时间: {cutoff_time}")
            self._logger.info(f"[{serial}]       - 设备过滤: {serial}")

            # 通过 devices → kefu_devices → kefus → customers 链接按设备过滤
            query = """
                SELECT
                    c.id as customer_id,
                    c.name as customer_name,
                    c.channel as customer_channel,
                    m.id as message_id,
                    m.content as message_content,
                    m.is_from_kefu,
                    m.timestamp_parsed as message_time
                FROM customers c
                JOIN messages m ON m.customer_id = c.id
                JOIN kefus k ON c.kefu_id = k.id
                JOIN kefu_devices kd ON k.id = kd.kefu_id
                JOIN devices d ON kd.device_id = d.id
                WHERE m.id = (
                    SELECT MAX(m2.id) FROM messages m2
                    WHERE m2.customer_id = c.id
                )
                AND m.timestamp_parsed >= ?
                AND d.serial = ?
                ORDER BY m.timestamp_parsed DESC
                LIMIT 50
            """

            self._logger.info(f"[{serial}]       执行数据库查询...")
            cursor = conn.execute(query, (cutoff_time, serial))
            rows = cursor.fetchall()
            conn.close()

            self._logger.info(f"[{serial}]       ✅ 查询完成，找到 {len(rows)} 条记录")

            kefu_count = 0
            customer_count = 0

            for row in rows:
                # 解析消息时间
                msg_time = None
                if row["message_time"]:
                    try:
                        msg_time = datetime.fromisoformat(row["message_time"].replace("Z", "+00:00"))
                    except Exception as parse_err:
                        self._logger.debug(f"[{serial}]       ⚠️ 时间解析失败: {row['message_time']} - {parse_err}")

                # 确定发送方
                sender = "kefu" if row["is_from_kefu"] else "customer"
                if sender == "kefu":
                    kefu_count += 1
                else:
                    customer_count += 1

                conv = ConversationInfo(
                    customer_name=row["customer_name"],
                    customer_channel=row["customer_channel"],
                    customer_id=str(row["customer_id"]),
                    last_message_id=str(row["message_id"]),
                    last_message_time=msg_time,
                    last_message_sender=sender,
                )
                conversations.append(conv)

                # 详细日志（仅在 DEBUG 级别）
                content_preview = (row["message_content"] or "")[:20]
                self._logger.debug(
                    f"[{serial}]       Conv: {row['customer_name'][:15]} | "
                    f"sender={sender} | time={msg_time} | content={content_preview}..."
                )

            self._logger.info(f"[{serial}]       统计: kefu最后发言={kefu_count}, customer最后发言={customer_count}")
            self._logger.info(f"[{serial}]       💡 kefu最后发言的对话可能需要补刀")

        except Exception as e:
            self._logger.error(f"[{serial}]       ❌ 构建对话列表失败: {e}")
            import traceback

            self._logger.debug(f"[{serial}]       {traceback.format_exc()}")

        return conversations

    async def _send_reply_wrapper(
        self,
        wecom_service: Any,
        serial: str,
        user_name: str,
        user_channel: str | None,
        message: str,
        sidecar_client: Any | None = None,
    ) -> tuple[bool, str | None]:
        """
        发送回复的包装方法，支持 Sidecar 队列和直接发送

        Args:
            wecom_service: WeComService 实例
            serial: 设备序列号
            user_name: 用户名
            user_channel: 频道（可选）
            message: 要发送的消息
            sidecar_client: Sidecar 客户端（如果启用）

        Returns:
            (success, sent_text) - 是否成功和实际发送的文本
        """
        if BlacklistChecker.is_blacklisted(
            serial,
            user_name,
            user_channel,
            use_cache=False,
            fail_closed=True,
        ):
            self._logger.warning(f"[{serial}] ⛔ Final blacklist check blocked reply for {user_name}")
            return False, None

        if sidecar_client:
            # 通过 Sidecar 队列发送（需要人工确认）
            try:
                self._logger.info(f"[{serial}] 📡 Routing message to Sidecar queue for {user_name}")

                # Step 1: 添加消息到队列
                msg_id = await sidecar_client.add_message(
                    customer_name=user_name,
                    channel=user_channel,
                    message=message,
                )

                if not msg_id:
                    self._logger.warning(f"[{serial}] Failed to add message to Sidecar queue")
                    # 回退到直接发送
                else:
                    self._logger.info(f"[{serial}] ✅ Message queued (ID: {msg_id})")

                    # Step 2: 标记消息为就绪（启动10秒倒计时）
                    if not await sidecar_client.set_message_ready(msg_id):
                        self._logger.warning(f"[{serial}] Failed to mark message as ready")
                    else:
                        self._logger.info(f"[{serial}] ⏱️ Countdown started, waiting for send...")

                        # Determine timeout: use night-mode value during off-hours
                        sidecar_timeout = self._get_sidecar_timeout()

                        # Step 3: 等待用户审核/发送
                        result = await sidecar_client.wait_for_send(msg_id, timeout=sidecar_timeout)

                        reason = result.get("reason", "unknown")
                        if result.get("success") or reason == "sent":
                            # 获取实际发送的消息（可能被用户编辑过）
                            actual_message = result.get("message", message)
                            self._logger.info(f"[{serial}] ✅ Reply sent (via Sidecar)")
                            return True, actual_message
                        elif reason == "cancelled":
                            self._logger.info(f"[{serial}] ⏭️ User skipped, message not sent")
                            return False, None
                        elif reason == "expired":
                            self._logger.info(f"[{serial}] ⏰ Message expired, skipping")
                            return False, None
                        else:
                            self._logger.warning(f"[{serial}] Sidecar send failed: {reason}")
                            # P0 修复: 超时后回退到直接发送前，记录 msg_id 用于后续清理

            except Exception as e:
                self._logger.warning(f"[{serial}] Error using Sidecar: {e}, falling back to direct send")
                msg_id = None  # 确保 msg_id 被定义

        # 直接发送（无人工审核）- 使用 Sidecar 的 send API
        try:
            import aiohttp

            # 使用 Sidecar 的 send-and-save API 直接发送
            url = f"http://localhost:8765/sidecar/{serial}/send"

            payload = {
                "message": message,
                "contact_name": user_name,
                "channel": user_channel,
            }

            if BlacklistChecker.is_blacklisted(
                serial,
                user_name,
                user_channel,
                use_cache=False,
                fail_closed=True,
            ):
                self._logger.warning(f"[{serial}] ⛔ Reply blocked before direct send for {user_name}")
                return False, None

            self._logger.info(f"[{serial}] 📤 Sending message directly (no Sidecar review)")

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("success"):
                            self._logger.info(f"[{serial}] ✅ Message sent directly")

                            # P0 修复: 直接发送成功后，标记队列中的消息为已发送
                            if sidecar_client and msg_id:
                                try:
                                    await sidecar_client.mark_as_sent_directly(msg_id)
                                    self._logger.info(f"[{serial}] 🧹 Marked queue message {msg_id} as SENT")
                                except Exception as cleanup_err:
                                    self._logger.warning(f"[{serial}] Failed to cleanup queue message: {cleanup_err}")

                            return True, message
                    self._logger.warning(f"[{serial}] Failed to send message directly: {response.status}")
                    return False, None
        except Exception as e:
            self._logger.error(f"[{serial}] Error sending message directly: {e}")
            return False, None
