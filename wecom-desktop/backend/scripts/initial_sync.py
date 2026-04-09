#!/usr/bin/env python3
# ruff: noqa: E402
"""
Initial Conversation Database Sync for WeCom

使用新模块化架构的同步入口脚本。

主要特性：
- 使用 SyncOrchestrator 进行同步编排
- 使用 SyncOptions 配置选项
- 清晰的模块化结构
- 支持进度监听器

Usage Examples:
    # 基本同步
    uv run initial_sync.py

    # 指定设备
    uv run initial_sync.py --serial ABC123XYZ

    # 启用 AI 回复
    uv run initial_sync.py --use-ai-reply

    # 通过 Sidecar 发送
    uv run initial_sync.py --send-via-sidecar --use-ai-reply
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# Ensure local package imports work when the script is executed directly
# Import path_utils from backend
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.path_utils import get_project_root
from services.conversation_storage import (
    get_control_db_path,
    get_device_conversation_db_path,
)

PROJECT_ROOT = get_project_root()
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Import new modular components
from wecom_automation.core.config import Config
from wecom_automation.core.interfaces import (
    CustomerSyncResult,
    ISyncProgressListener,
    SyncProgress,
)
from wecom_automation.services.ai.reply_service import AIReplyService

# Import AI and Sidecar services (reuse from original)
from wecom_automation.services.integration.sidecar import SidecarQueueClient
from wecom_automation.services.sync import (
    create_sync_orchestrator,
    options_from_args,
)

# =============================================================================
# PROGRESS LISTENER
# =============================================================================


class ConsoleProgressListener(ISyncProgressListener):
    """控制台进度监听器 - 显示同步进度到控制台"""

    def __init__(self, logger):
        self.logger = logger
        self._last_progress_time = None

    def on_progress(self, progress: SyncProgress) -> None:
        """进度更新回调"""
        now = datetime.now()
        # 限制更新频率（每2秒最多一次）
        if self._last_progress_time and (now - self._last_progress_time).total_seconds() < 2:
            return
        self._last_progress_time = now

        pct = progress.percentage
        self.logger.info(
            f"📊 Progress: {progress.synced_customers}/{progress.total_customers} "
            f"({pct:.1f}%) | Messages: +{progress.messages_added} | "
            f"Current: {progress.current_customer or 'N/A'}"
        )

    def on_customer_start(self, customer_name: str) -> None:
        """开始同步客户回调"""
        self.logger.info(f"▶️ Starting sync: {customer_name}")

    def on_customer_complete(self, customer_name: str, result: CustomerSyncResult) -> None:
        """完成同步客户回调"""
        if result.skipped:
            # User was manually skipped
            self.logger.info(
                f"⏭️ Skipped: {customer_name} | "
                f"Messages: {result.messages_added} added, {result.messages_skipped} skipped"
            )
        else:
            status = "✅" if result.success else "❌"
            self.logger.info(
                f"{status} Completed: {customer_name} | "
                f"Messages: {result.messages_added} added, {result.messages_skipped} skipped"
            )

    def on_error(self, error: str, customer_name: str | None = None) -> None:
        """错误回调"""
        if customer_name:
            self.logger.error(f"❌ Error with {customer_name}: {error}")
        else:
            self.logger.error(f"❌ Error: {error}")


# =============================================================================
# LOGGING SETUP
# =============================================================================


def _get_hostname() -> str:
    """从设置中获取主机名"""
    try:
        from services.settings.service import SettingsService

        db_path = str(get_control_db_path())
        settings_service = SettingsService(db_path)
        return settings_service.get_effective_hostname()
    except Exception:
        return "default"


def setup_logging(serial: str, debug: bool = False, log_file: str | None = None):
    """配置日志系统 - 使用 loguru，同时输出到文件和 stdout（由父进程捕获）"""
    from loguru import logger as _loguru_logger

    from wecom_automation.core.logging import get_logger, init_logging

    level = "DEBUG" if debug else "INFO"
    hostname = _get_hostname()

    # 初始化 loguru（传入 serial 参数，只写设备专属日志，避免文件锁定冲突）
    # 注意：loguru 默认输出到 stderr，这里我们需要自定义输出到 stdout
    init_logging(hostname=hostname, level=level, console=False, serial=serial)

    # 手动添加 stdout handler（用于父进程捕获并转发到前端 WebSocket）
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

    # log_file 参数已弃用，统一使用设备 sink
    if log_file:
        print("[warning] log_file parameter is deprecated, using device sink instead")

    return get_logger("sync", device=serial)


def _resolve_storage_paths(args: argparse.Namespace) -> tuple[str, str, str, str]:
    """Resolve consistent media directories from explicit args or an output root."""
    output_root = Path(args.output_root).expanduser().resolve() if args.output_root else None

    images_dir = args.images_dir
    videos_dir = args.videos_dir
    voices_dir = args.voices_dir

    if output_root is None:
        if images_dir:
            image_path = Path(images_dir).expanduser().resolve()
            output_root = image_path.parent
        elif videos_dir:
            video_path = Path(videos_dir).expanduser().resolve()
            output_root = video_path.parent
        elif voices_dir:
            voice_path = Path(voices_dir).expanduser().resolve()
            output_root = voice_path.parent
        else:
            output_root = Path(".").resolve()

    images_dir = images_dir or str(output_root / "conversation_images")
    videos_dir = videos_dir or str(output_root / "conversation_videos")
    voices_dir = voices_dir or str(output_root / "conversation_voices")

    return str(output_root), images_dir, videos_dir, voices_dir


# =============================================================================
# MAIN EXECUTION
# =============================================================================


async def run(args: argparse.Namespace) -> int:
    """主执行流程"""
    if not args.db:
        args.db = str(get_device_conversation_db_path(args.serial)) if args.serial else str(get_control_db_path())

    output_root, images_dir, videos_dir, voices_dir = _resolve_storage_paths(args)

    # Initialize configuration first to get device serial
    config = Config(
        device_serial=args.serial,
        use_tcp=args.prefer_tcp,
        droidrun_port=args.tcp_port,  # Use allocated port for multi-device support
        debug=args.debug,
        output_dir=output_root,
    )

    # Setup logging with device serial
    logger = setup_logging(serial=config.device_serial, debug=args.debug, log_file=args.log_file)

    logger.info("=" * 60)
    logger.info("WeCom Initial Sync v2 (Modular Architecture)")
    logger.info("=" * 60)
    logger.info(f"Started at: {datetime.now().isoformat()}")
    logger.info(f"Debug mode: {args.debug}")
    logger.info(f"Database: {args.db}")
    logger.info(f"Output root: {output_root}")
    logger.info(f"Images directory: {images_dir}")
    logger.info(f"Videos directory: {videos_dir}")
    logger.info(f"Voices directory: {voices_dir}")
    logger.info(f"Timing multiplier: {args.timing_multiplier}")
    logger.info(f"Test messages: {not args.no_test_messages}")
    logger.info(f"Response wait: {args.response_wait}s")
    logger.info(f"Interactive wait timeout: {args.wait_timeout}s")
    logger.info(f"Max interaction rounds: {args.max_rounds}")
    logger.info(f"Prioritize unread: {args.prioritize_unread}")
    logger.info(f"Unread only: {args.unread_only}")
    logger.info(f"Resume from checkpoint: {args.resume}")

    # Create sync orchestrator using factory
    logger.info("\n📦 Creating sync orchestrator with new modular architecture...")

    orchestrator = create_sync_orchestrator(
        config=config,
        db_path=args.db,
        images_dir=images_dir,
        videos_dir=videos_dir,
        voices_dir=voices_dir,
        timing_multiplier=args.timing_multiplier,
        logger=logger,
    )

    # Add progress listener
    progress_listener = ConsoleProgressListener(logger)
    orchestrator.add_listener(progress_listener)

    # Create sync options from command line arguments
    options = options_from_args(args)

    logger.info(f"📋 Sync options: {options}")

    # Initialize AI service if enabled
    ai_service: AIReplyService | None = None
    if args.use_ai_reply:
        logger.info(f"🤖 AI Reply enabled - using {args.ai_server_url}")

        # Decode base64 system prompt if provided
        system_prompt = args.system_prompt
        if args.system_prompt_b64:
            try:
                import base64

                system_prompt = base64.b64decode(args.system_prompt_b64).decode("utf-8")
                logger.info(f"System prompt (from b64): {system_prompt[:80]}...")
            except Exception as e:
                logger.warning(f"Failed to decode base64 system prompt: {e}")

        # Load email config
        email_config = None
        try:
            # Use project root to locate email settings
            settings_file = PROJECT_ROOT / "wecom-desktop" / "backend" / "email_settings.json"
            if settings_file.exists():
                with open(settings_file, encoding="utf-8") as f:
                    email_config = json.load(f)
        except Exception as e:
            logger.warning(f"Could not load email settings: {e}")

        ai_service = AIReplyService(
            server_url=args.ai_server_url,
            timeout=args.ai_reply_timeout,
            logger=logger,
            system_prompt=system_prompt,
            email_config=email_config,
        )

        # Set AI service on customer syncer
        orchestrator._customer_syncer.set_ai_service(ai_service)

    # Initialize Sidecar client if enabled
    sidecar_client: SidecarQueueClient | None = None
    if args.send_via_sidecar:
        logger.info("📡 Sidecar mode enabled - messages will be routed through sidecar")
        sidecar_client = SidecarQueueClient(args.serial, args.backend_url)

        # Set sidecar client on customer syncer
        orchestrator._customer_syncer.set_sidecar_client(sidecar_client)

    logger.info("✅ Sync orchestrator initialized")

    # Run the sync
    logger.info("\n" + "=" * 60)
    logger.info("🚀 Starting initial sync")
    logger.info("=" * 60)

    try:
        if sidecar_client:
            async with sidecar_client:
                if ai_service:
                    async with ai_service:
                        await sidecar_client.clear_queue()
                        result = await orchestrator.run(options)
                else:
                    await sidecar_client.clear_queue()
                    result = await orchestrator.run(options)
        else:
            if ai_service:
                async with ai_service:
                    result = await orchestrator.run(options)
            else:
                result = await orchestrator.run(options)

    except KeyboardInterrupt:
        logger.info("⏹️ Sync cancelled by user")
        return 130
    except Exception as e:
        logger.error(f"❌ Sync failed with error: {e}")
        if args.debug:
            import traceback

            traceback.print_exc()
        return 1

    # Display results
    logger.info("\n" + "=" * 60)
    logger.info("📊 SYNC RESULTS")
    logger.info("=" * 60)

    print("\n" + "=" * 60)
    print("SYNC COMPLETE")
    print("=" * 60)
    print(f"Start time: {result.start_time.isoformat()}")
    print(f"End time: {result.end_time.isoformat()}")
    print(f"Duration: {result.duration_seconds:.1f}s")
    print(f"Success: {result.success}")
    print(f"Customers synced: {result.customers_synced}")
    print(f"Messages added: {result.messages_added}")
    print(f"Messages skipped (duplicates): {result.messages_skipped}")
    print(f"Images saved: {result.images_saved}")
    print(f"Voice messages: {result.voice_messages}")

    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for error in result.errors[:10]:
            print(f"  - {error}")
        if len(result.errors) > 10:
            print(f"  ... and {len(result.errors) - 10} more")

    print("=" * 60)

    # Export stats to JSON if requested
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)

        logger.info(f"📄 Stats exported to: {args.output_json}")

    return 0 if result.success else 1


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="WeCom Initial Sync v2 - 使用新模块化架构",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic sync
  python initial_sync_v2.py

  # Sync specific device
  python initial_sync_v2.py --serial ABC123XYZ

  # With AI reply
  python initial_sync_v2.py --use-ai-reply

  # Via sidecar with AI
  python initial_sync_v2.py --send-via-sidecar --use-ai-reply
        """,
    )

    # Device options
    parser.add_argument("--serial", help="ADB serial of the target device")
    parser.add_argument("--prefer-tcp", action="store_true", help="Prefer TCP bridge")
    parser.add_argument(
        "--tcp-port",
        type=int,
        default=8080,
        help="DroidRun TCP port for this device (must be unique for multi-device sync, default: 8080)",
    )

    # Database options
    parser.add_argument("--db", type=str, default="", help="Path to SQLite database file")
    parser.add_argument(
        "--output-root",
        type=str,
        help="Root directory for device-local sync outputs (images/videos/voices)",
    )
    parser.add_argument("--images-dir", type=str, help="Directory to store images")
    parser.add_argument("--videos-dir", type=str, help="Directory to store videos")
    parser.add_argument("--voices-dir", type=str, help="Directory to store voices")

    # Sync behavior
    parser.add_argument("--no-test-messages", action="store_true", help="Don't send test messages")
    parser.add_argument("--response-wait", type=float, default=5.0, help="Seconds to wait for responses")
    parser.add_argument("--auto-placeholder", action="store_true", help="Auto-placeholder for voice messages")

    # Unread message prioritization
    parser.add_argument("--prioritize-unread", action="store_true", help="Sync users with unread messages first")
    parser.add_argument("--unread-only", action="store_true", help="Only sync users with unread messages")

    # Resume functionality
    parser.add_argument("--resume", action="store_true", help="Resume from last checkpoint")

    # Interactive waiting (v2 feature)
    parser.add_argument(
        "--wait-timeout", type=float, default=10.0, help="Seconds to wait for new messages (default: 10.0)"
    )
    parser.add_argument("--max-rounds", type=int, default=10, help="Max conversation rounds per customer (default: 10)")
    parser.add_argument(
        "--dynamic-unread", action="store_true", default=True, help="Enable dynamic unread detection (default: True)"
    )

    # Timing
    parser.add_argument("--timing-multiplier", type=float, default=1.0, help="Multiply all delays by this factor")

    # Sidecar options
    parser.add_argument("--send-via-sidecar", action="store_true", help="Route messages through sidecar")
    parser.add_argument(
        "--countdown-seconds", type=int, default=10, help="Countdown duration in sidecar before auto-sending"
    )
    parser.add_argument(
        "--backend-url", type=str, default="http://localhost:8765", help="Backend server URL for sidecar API"
    )

    # AI Reply options
    parser.add_argument("--use-ai-reply", action="store_true", help="Use AI server for generating replies")
    parser.add_argument("--ai-server-url", type=str, default="http://localhost:8000", help="AI server URL")
    parser.add_argument("--ai-reply-timeout", type=int, default=10, help="Timeout for AI reply")
    parser.add_argument("--system-prompt", type=str, default="", help="System prompt for AI")
    parser.add_argument("--system-prompt-b64", type=str, default="", help="Base64-encoded system prompt")

    # Output options
    parser.add_argument("--output-json", type=str, help="Export sync statistics to JSON file")

    # Debug options
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--log-file", type=str, help="Write logs to file")

    return parser.parse_args()


def main() -> None:
    """Entry point"""
    args = parse_args()
    try:
        exit_code = asyncio.run(run(args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(130)


if __name__ == "__main__":
    main()
