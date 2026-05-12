#!/usr/bin/env python3
"""
Realtime Reply Process - 单设备实时回复独立脚本

为单个设备运行实时回复检测和AI回复生成。
可被 RealtimeReplyManager 启动为子进程运行。

Usage:
    python realtime_reply_process.py --serial DEVICE_SERIAL [options]
"""

import argparse
import asyncio
import hashlib
import sys
from pathlib import Path

# 添加项目路径
# IMPORTANT: Configure sys.path BEFORE importing utils.path_utils
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Now we can import from backend
from services.conversation_storage import (
    get_control_db_path,
    get_device_conversation_db_path,
)
from utils.path_utils import get_project_root

PROJECT_ROOT = get_project_root()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "wecom-desktop" / "backend"))


def _get_hostname() -> str:
    """从设置中获取主机名"""
    try:
        from services.settings.service import SettingsService

        db_path = str(get_control_db_path())
        settings_service = SettingsService(db_path)
        return settings_service.get_effective_hostname()
    except Exception:
        return "default"


def setup_logging(serial: str, debug: bool = False):
    """设置日志 - 使用 loguru，同时输出到文件和 stdout（由父进程捕获）"""
    from wecom_automation.core.logging import get_logger, init_logging

    level = "DEBUG" if debug else "INFO"
    hostname = _get_hostname()

    # 初始化 loguru（传入 serial 参数，只写设备专属日志，避免文件锁定冲突）
    # 注意：loguru 默认输出到 stderr，这里我们需要自定义控制台输出到 stdout
    init_logging(hostname=hostname, level=level, console=False, serial=serial)

    # 手动添加 stdout handler（用于父进程捕获）
    from loguru import logger as _loguru_logger

    _loguru_logger.add(
        sys.stdout,
        format="{time:HH:mm:ss} | {level:<8} | {message}",
        level=level,
        colorize=False,  # stdout 不需要颜色
    )

    # 注意：不再需要调用 add_device_sink，因为 init_logging(serial=...) 已自动添加设备日志

    # 确保 stdout 刷新（用于父进程实时捕获）
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    return get_logger("scanner", device=serial)


async def run(args):
    """主执行流程"""
    logger = setup_logging(args.serial, args.debug)

    logger.info("=" * 60)
    logger.info(f"FOLLOW-UP PROCESS STARTED FOR {args.serial}")
    logger.info("=" * 60)
    logger.info("Configuration:")
    logger.info(f"   - Scan Interval: {args.scan_interval}s")
    logger.info(f"   - Use AI Reply: {args.use_ai_reply}")
    logger.info(f"   - Send via Sidecar: {args.send_via_sidecar}")
    logger.info("=" * 60)

    # 导入必要模块
    try:
        # 导入 FollowUp 组件（复用现有逻辑）
        from services.followup.repository import ConversationRepository
        from services.followup.response_detector import ResponseDetector
        from services.followup.settings import SettingsManager
        from wecom_automation.services.ai.reply_service import AIReplyService  # noqa: F401
        from wecom_automation.services.integration.sidecar import SidecarQueueClient
        from wecom_automation.services.wecom_service import WeComService  # noqa: F401
    except ImportError as e:
        # 备用导入路径
        logger.warning(f"Import warning: {e}, trying alternative paths...")
        # PROJECT_ROOT / "wecom-desktop" / "backend" already in path from line 29

        from services.followup.repository import ConversationRepository
        from services.followup.response_detector import ResponseDetector
        from services.followup.settings import SettingsManager

    # 初始化组件
    db_path = str(get_device_conversation_db_path(args.serial))
    logger.info(f"Database: {db_path}")

    repository = ConversationRepository(db_path)
    settings_manager = SettingsManager(db_path)
    detector = ResponseDetector(repository, settings_manager, logger)

    # Sidecar 客户端
    sidecar_client = None
    if args.send_via_sidecar:
        try:
            sidecar_client = SidecarQueueClient(args.serial)
            logger.info("Sidecar client initialized")
        except Exception as e:
            logger.warning(f"Failed to init Sidecar client: {e}")

    # Start periodic AI health checker
    try:
        from services.ai_health_checker import PeriodicAIHealthChecker
        from services.settings.service import SettingsService

        _settings_svc = SettingsService(str(get_control_db_path()))
        _all_settings = _settings_svc.get_flat_settings()
        _ai_url = _all_settings.get("aiServerUrl", "http://47.113.187.234:8000")
        if not _ai_url:
            _ai_url = "http://47.113.187.234:8000"

        _health_checker = PeriodicAIHealthChecker(
            ai_server_url=_ai_url,
            interval_seconds=300.0,
            circuit_breaker=detector._ai_circuit_breaker,
            logger=logger,
        )
        _health_checker.start()
        logger.info(f"AI health checker started (interval=300s, url={_ai_url})")
    except Exception as e:
        logger.warning(f"Failed to start AI health checker: {e}")
        _health_checker = None

    # Per-serial jitter: deterministic offset (in seconds) derived from the
    # device serial so multiple devices' scan loops don't lock onto the same
    # tick. Without this, two devices started seconds apart drift toward the
    # same scan instant over time, which then funnels both AI requests into
    # the (single-worker) AI server simultaneously and makes downstream
    # sidecar replies appear to "batch" together. Range is roughly +/- half
    # of `scan_interval / 6`, capped between [-10s, +10s] so the worst-case
    # jitter stays small relative to the configured interval.
    _jitter_span = max(2, min(20, args.scan_interval // 3))
    _jitter_seed = int(hashlib.md5(args.serial.encode("utf-8")).hexdigest(), 16)
    _scan_jitter_seconds = (_jitter_seed % (_jitter_span + 1)) - (_jitter_span // 2)

    # Heartbeat / lifecycle tracking
    import time as _time

    try:
        from services.heartbeat_service import (
            ensure_tables,
            record_click_health,
            record_heartbeat,
            record_process_event,
        )

        ensure_tables()
        _has_heartbeat = True
    except Exception as _hb_err:
        logger.warning(f"Heartbeat service unavailable: {_hb_err}")
        _has_heartbeat = False
        record_click_health = None  # type: ignore[assignment]

    process_start = _time.monotonic()
    if _has_heartbeat:
        record_process_event(args.serial, "started")

    # 主循环
    scan_count = 0
    # Per-loop running counters used for the periodic summary line so a single
    # `grep "scan_summary"` on the device log gives an at-a-glance health view.
    _summary_ai_failures = 0
    _summary_replies_sent = 0
    _summary_last_error: str | None = None
    while True:
        try:
            scan_count += 1
            scan_start = _time.monotonic()
            logger.info("")
            logger.info(f"[Scan #{scan_count}] Checking for unread messages...")

            # 调用检测器（传递 sidecar_client）
            result = await detector.detect_and_reply(
                device_serial=args.serial,
                interactive_wait_timeout=10,
                sidecar_client=sidecar_client,
                droidrun_port=args.tcp_port,
            )

            scan_duration_ms = (_time.monotonic() - scan_start) * 1000
            queue_size = result.get("users_processed", 0)

            # Record heartbeat
            if _has_heartbeat:
                try:
                    record_heartbeat(
                        device_serial=args.serial,
                        scan_number=scan_count,
                        status="alive",
                        scan_duration_ms=scan_duration_ms,
                        customers_in_queue=queue_size,
                    )
                except Exception as hb_err:
                    logger.warning(f"Failed to write heartbeat: {hb_err}")

            # Record click-health snapshot (dayblock + cooldown surface).
            # Best-effort: failures here MUST NOT break the scan loop. See
            # docs/04-bugs-and-fixes/resolved/2026-05-12-new-friend-false-positive-click-loop.md
            if _has_heartbeat and record_click_health is not None:
                try:
                    snap = detector.get_click_health_snapshot()
                    record_click_health(
                        device_serial=args.serial,
                        scan_number=scan_count,
                        dayblock_day=snap["dayblock_day"],
                        dayblock_size=snap["dayblock_size"],
                        dayblock_keys=snap["dayblock_keys"],
                        active_cooldown_count=snap["active_cooldown_count"],
                        active_cooldowns=snap["active_cooldowns"],
                        unique_customers_clicked=snap.get("unique_customers_clicked"),
                        priority_queue_repeats=snap.get("priority_queue_repeats"),
                    )
                except Exception as ch_err:
                    logger.debug(f"Failed to write click_health sample: {ch_err}")

            # 报告结果
            responses = result.get("responses_detected", 0)
            replies_this_scan = int(result.get("replies_sent", 0) or 0)
            ai_failures_this_scan = int(result.get("ai_failures", 0) or 0)
            scan_error = result.get("last_error")

            _summary_replies_sent += replies_this_scan
            _summary_ai_failures += ai_failures_this_scan
            if scan_error:
                _summary_last_error = str(scan_error)[:120]

            if responses > 0:
                logger.info(f"[Scan #{scan_count}] Processed {responses} response(s)")
            else:
                logger.info(f"[Scan #{scan_count}] No unread messages")

            # Periodic summary: one line per scan that the UI / `grep` can use
            # to spot stalled or AI-down devices without paging through verbose
            # per-customer logs. Circuit-breaker state is included so an
            # operator can immediately tell whether the local replies are
            # paused because of upstream AI failure.
            try:
                _cb_state = detector._ai_circuit_breaker.state.value
            except Exception:
                _cb_state = "unknown"
            logger.info(
                f"[scan_summary] scan=#{scan_count} "
                f"replies={_summary_replies_sent} "
                f"ai_failures={_summary_ai_failures} "
                f"cb={_cb_state} "
                f"last_error={_summary_last_error or 'none'}"
            )

            # 等待下一个扫描周期 (+ per-serial jitter to avoid multi-device
            # scan-loop lock-step; see _scan_jitter_seconds computation above).
            _sleep_seconds = max(1, args.scan_interval + _scan_jitter_seconds)
            logger.info(
                f"Sleeping {_sleep_seconds}s until next scan "
                f"(base={args.scan_interval}s, jitter={_scan_jitter_seconds:+d}s)..."
            )
            await asyncio.sleep(_sleep_seconds)

        except asyncio.CancelledError:
            logger.info("Follow-up process cancelled")
            break
        except KeyboardInterrupt:
            logger.info("Follow-up process interrupted")
            break
        except Exception as e:
            logger.error(f"Error in follow-up loop: {e}")
            import traceback

            logger.error(traceback.format_exc())

            if _has_heartbeat:
                try:
                    record_heartbeat(args.serial, scan_count, status="error")
                except Exception:
                    pass

            logger.info("Waiting 30s before retry...")
            await asyncio.sleep(30)

    # Cleanup
    if _health_checker:
        _health_checker.stop()

    uptime = _time.monotonic() - process_start
    if _has_heartbeat:
        record_process_event(args.serial, "stopped", scan_count=scan_count, uptime_seconds=uptime)
    logger.info("Follow-up process exiting")


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="Follow-up process for a single device")

    parser.add_argument("--serial", required=True, help="Device serial number")

    parser.add_argument("--scan-interval", type=int, default=60, help="Scan interval in seconds (default: 60)")

    parser.add_argument("--use-ai-reply", action="store_true", help="Use AI to generate replies")

    parser.add_argument("--send-via-sidecar", action="store_true", help="Send via Sidecar for human review")

    parser.add_argument("--tcp-port", type=int, default=None, help="DroidRun TCP port for this device")

    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    return parser.parse_args()


def main():
    """入口函数"""
    args = parse_args()

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
