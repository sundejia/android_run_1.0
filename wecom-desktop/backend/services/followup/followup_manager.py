"""
补刀功能管理器

整合 FollowupExecutor 和 Settings，提供高级 API。
外部调用入口。
"""

import logging
import random
from collections.abc import Callable

from droidrun import AdbTools

from .executor import (
    BatchFollowupResult,
    FollowupExecutor,
    FollowupResult,
    FollowupStatus,
)
from .settings import FollowUpSettings, SettingsManager

logger = logging.getLogger("followup.manager")


class FollowupManager:
    """
    补刀功能管理器

    整合设置和执行器，提供完整的补刀功能 API。

    使用方式:
        manager = FollowupManager(device_serial)

        # 检查是否启用
        if manager.is_enabled():
            # 执行补刀
            result = await manager.execute_followup("联系人名称")

            # 批量补刀（使用设置中的消息模板）
            result = await manager.execute_batch_followup(["用户1", "用户2"])
    """

    def __init__(
        self,
        device_serial: str,
        adb: AdbTools | None = None,
        db_path: str | None = None,
        log_callback: Callable[[str, str], None] | None = None,
    ):
        """
        初始化补刀管理器

        Args:
            device_serial: 设备序列号
            adb: 可选的 AdbTools 实例
            db_path: 数据库路径（用于读取设置）
            log_callback: 日志回调
        """
        self.device_serial = device_serial
        self._adb = adb
        self._db_path = db_path
        self._log_callback = log_callback

        # 延迟初始化
        self._executor: FollowupExecutor | None = None
        self._settings_manager: SettingsManager | None = None
        self._settings_cache: FollowUpSettings | None = None
        self._settings_cache_time: float = 0

    def _log(self, msg: str, level: str = "INFO"):
        """记录日志"""
        if level == "ERROR":
            logger.error(f"[{self.device_serial}] [FollowupMgr] {msg}")
        elif level == "WARN":
            logger.warning(f"[{self.device_serial}] [FollowupMgr] {msg}")
        elif level == "DEBUG":
            logger.debug(f"[{self.device_serial}] [FollowupMgr] {msg}")
        else:
            logger.info(f"[{self.device_serial}] [FollowupMgr] {msg}")

        if self._log_callback:
            try:
                self._log_callback(msg, level)
            except Exception:
                pass

    def _get_settings_manager(self) -> SettingsManager:
        """获取设置管理器"""
        if self._settings_manager is None:
            self._settings_manager = SettingsManager(self._db_path)
        return self._settings_manager

    def _get_settings(self, force_refresh: bool = False) -> FollowUpSettings:
        """获取设置（带缓存）"""
        import time

        now = time.time()

        # 缓存 30 秒
        if not force_refresh and self._settings_cache is not None and now - self._settings_cache_time < 30:
            return self._settings_cache

        self._settings_cache = self._get_settings_manager().get_settings()
        self._settings_cache_time = now
        return self._settings_cache

    def _get_executor(self) -> FollowupExecutor:
        """获取执行器"""
        if self._executor is None:
            self._executor = FollowupExecutor(
                device_serial=self.device_serial,
                adb=self._adb,
                log_callback=self._log_callback,
            )
        return self._executor

    # ==================== 状态检查 ====================

    def is_enabled(self) -> bool:
        """检查补刀功能是否启用"""
        settings = self._get_settings()
        return settings.followup_enabled

    def is_within_operating_hours(self) -> bool:
        """检查是否在工作时间内"""
        return self._get_settings_manager().is_within_operating_hours()

    def can_execute(self) -> tuple[bool, str]:
        """
        检查是否可以执行补刀

        Returns:
            (can_execute, reason)
        """
        settings = self._get_settings()

        if not settings.followup_enabled:
            return False, "Followup is disabled"

        if settings.enable_operating_hours:
            if not self.is_within_operating_hours():
                return False, f"Outside operating hours ({settings.start_hour} - {settings.end_hour})"

        return True, "OK"

    # ==================== 消息模板 ====================

    def get_message_templates(self) -> list[str]:
        """获取消息模板列表"""
        settings = self._get_settings()
        return settings.message_templates or []

    def get_random_message(self) -> str:
        """随机获取一条消息模板"""
        templates = self.get_message_templates()
        if not templates:
            return "你好，请问考虑得怎么样了？"
        return random.choice(templates)

    def get_max_followups(self) -> int:
        """获取每次扫描最大补刀数"""
        settings = self._get_settings()
        return settings.max_followups

    def should_use_ai_reply(self) -> bool:
        """是否使用 AI 回复（补刀专用）"""
        settings = self._get_settings()
        return settings.use_ai_reply

    # ==================== 执行补刀 ====================

    async def connect(self) -> bool:
        """连接设备"""
        executor = self._get_executor()
        return await executor.connect()

    async def disconnect(self):
        """断开设备"""
        if self._executor:
            await self._executor.disconnect()



    async def execute_followup(
        self,
        target_name: str,
        message: str | None = None,
        skip_check: Callable[[], bool] | None = None,
    ) -> FollowupResult:
        """
        对单个用户执行补刀

        Args:
            target_name: 目标联系人名称
            message: 消息内容（如果不传，使用随机模板或 AI）
            skip_check: 中断检查函数

        Returns:
            FollowupResult
        """
        self._log("")
        self._log("┌" + "─" * 50 + "┐")
        self._log("│ 执行单用户补刀                                    │")
        self._log("└" + "─" * 50 + "┘")
        self._log(f"  目标: {target_name}")
        self._log(f"  消息: {(message or '(自动生成)')[:40]}...")

        # 检查是否可以执行
        can_exec, reason = self.can_execute()
        self._log(f"  执行检查: can_exec={can_exec}, reason={reason}")

        if not can_exec:
            self._log(f"  ⚠️ 无法执行补刀: {reason}", "WARN")
            return FollowupResult(
                target_name=target_name,
                status=FollowupStatus.SKIPPED,
                error=reason,
            )

        # 确定消息内容
        if message is None:
            self._log("  消息为空，需要自动生成...")
            if self.should_use_ai_reply():
                # TODO: 集成 AI 回复
                message = self.get_random_message()
                self._log("  ⚠️ AI 回复功能待实现，使用随机模板", "WARN")
            else:
                message = self.get_random_message()
            self._log(f"  生成的消息: {message[:40]}...")

        # 执行
        self._log("  调用执行器...")
        executor = self._get_executor()
        result = await executor.execute(target_name, message, skip_check)

        # 记录结果
        status_icon = (
            "✅" if result.status == FollowupStatus.SUCCESS else "❌" if result.status == FollowupStatus.FAILED else "⏭️"
        )
        self._log(f"  {status_icon} 执行结果: {result.status.value}")
        if result.error:
            self._log(f"     错误: {result.error}")
        self._log(f"     耗时: {result.duration_ms}ms")

        return result

    async def execute_batch_followup(
        self,
        target_names: list[str],
        message: str | None = None,
        skip_check: Callable[[], bool] | None = None,
        delay_between: float = 1.0,
    ) -> BatchFollowupResult:
        """
        批量补刀

        Args:
            target_names: 目标用户名称列表
            message: 统一消息（如果不传，每个用户使用随机模板）
            skip_check: 中断检查函数
            delay_between: 用户之间的延迟

        Returns:
            BatchFollowupResult
        """
        self._log("")
        self._log("╔" + "═" * 50 + "╗")
        self._log("║ 执行批量补刀                                      ║")
        self._log("╚" + "═" * 50 + "╝")
        self._log(f"  目标用户数: {len(target_names)}")
        self._log(f"  统一消息: {(message or '(每用户随机)')[:30]}...")
        self._log(f"  用户间延迟: {delay_between}s")

        # 检查是否可以执行
        can_exec, reason = self.can_execute()
        self._log(f"  执行检查: can_exec={can_exec}, reason={reason}")

        if not can_exec:
            self._log(f"  ⚠️ 无法执行批量补刀: {reason}", "WARN")
            return BatchFollowupResult(
                total=len(target_names),
                skipped=len(target_names),
                results=[FollowupResult(name, FollowupStatus.SKIPPED, error=reason) for name in target_names],
            )

        # 限制数量
        max_followups = self.get_max_followups()
        self._log(f"  最大补刀数限制: {max_followups}")

        if len(target_names) > max_followups:
            self._log(f"  ⚠️ 目标数量 {len(target_names)} 超过限制 {max_followups}，截断")
            target_names = target_names[:max_followups]

        # 构建目标列表
        self._log("  构建目标列表...")
        targets = []
        for idx, name in enumerate(target_names, 1):
            msg = message if message else self.get_random_message()
            targets.append({"name": name, "message": msg})
            self._log(f"    {idx}. {name} -> {msg[:30]}...")

        # 执行
        self._log("  调用执行器批量执行...")
        executor = self._get_executor()
        result = await executor.execute_batch(targets, skip_check, delay_between)

        # 记录结果
        self._log("")
        self._log("  批量补刀完成:")
        self._log(f"    - 总计: {result.total}")
        self._log(f"    - 成功: {result.success}")
        self._log(f"    - 失败: {result.failed}")
        self._log(f"    - 跳过: {result.skipped}")
        self._log(f"    - 成功率: {result.success_rate * 100:.1f}%")

        return result


# ==================== 工厂函数 ====================

_managers: dict[str, FollowupManager] = {}


def get_followup_manager(
    device_serial: str,
    adb: AdbTools | None = None,
    db_path: str | None = None,
) -> FollowupManager:
    """
    获取指定设备的补刀管理器（单例）

    Args:
        device_serial: 设备序列号
        adb: 可选的 AdbTools 实例
        db_path: 数据库路径

    Returns:
        FollowupManager 实例
    """
    if device_serial not in _managers:
        _managers[device_serial] = FollowupManager(
            device_serial=device_serial,
            adb=adb,
            db_path=db_path,
        )
    return _managers[device_serial]


def clear_followup_manager(device_serial: str):
    """清除指定设备的补刀管理器"""
    if device_serial in _managers:
        del _managers[device_serial]


def clear_all_followup_managers():
    """清除所有补刀管理器"""
    _managers.clear()
