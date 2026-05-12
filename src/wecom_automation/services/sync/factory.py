"""
同步服务工厂

提供便捷的方法来创建和配置同步服务组件。
"""

from __future__ import annotations

import logging
from pathlib import Path

from wecom_automation.core.config import Config, get_default_db_path, get_project_root
from wecom_automation.database.repository import ConversationRepository
from wecom_automation.services.media_actions.factory import build_media_event_bus
from wecom_automation.services.message.processor import create_message_processor
from wecom_automation.services.review.runtime import build_review_components
from wecom_automation.services.sync.checkpoint import CheckpointManager
from wecom_automation.services.sync.customer_syncer import CustomerSyncer
from wecom_automation.services.sync.orchestrator import SyncOrchestrator
from wecom_automation.services.user.avatar import AvatarManager
from wecom_automation.services.user.unread_detector import UnreadUserExtractor
from wecom_automation.services.wecom_service import WeComService
from wecom_automation.utils.timing import HumanTiming


def create_sync_orchestrator(
    config: Config | None = None,
    db_path: str | None = None,
    images_dir: str | None = None,
    videos_dir: str | None = None,
    voices_dir: str | None = None,
    avatars_dir: str | None = None,
    timing_multiplier: float = 1.0,
    logger: logging.Logger | None = None,
    log_callback: callable | None = None,
) -> SyncOrchestrator:
    """
    创建完整配置的同步编排器

    这是创建同步服务的主要入口，会自动组装所有依赖。

    Args:
        config: 应用配置
        db_path: 数据库文件路径
        images_dir: 图片保存目录
        videos_dir: 视频保存目录
        voices_dir: 语音保存目录
        avatars_dir: 头像保存目录
        timing_multiplier: 延迟倍数
        logger: 日志记录器

    Returns:
        配置好的 SyncOrchestrator 实例

    Usage:
        orchestrator = create_sync_orchestrator(
            db_path="wecom.db",
            images_dir="./images"
        )

        result = await orchestrator.run(SyncOptions())
    """
    logger = logger or logging.getLogger("wecom_automation.sync")

    # 配置
    config = config or Config()

    # 路径设置 - 使用统一配置
    db_path = db_path or str(get_default_db_path())
    images_dir = images_dir or "conversation_images"
    videos_dir = videos_dir or "conversation_videos"
    voices_dir = voices_dir or "conversation_voices"

    # 头像目录（默认在项目根目录）
    if avatars_dir:
        avatars_path = Path(avatars_dir)
    else:
        # 默认位置
        avatars_path = get_project_root() / "avatars"
    avatars_path.mkdir(parents=True, exist_ok=True)

    # 检查点文件
    checkpoint_path = Path(db_path).parent / f"sync_checkpoint_{config.device_serial}.json"

    # 创建组件
    repository = ConversationRepository(db_path)
    wecom = WeComService(config)
    timing = HumanTiming(timing_multiplier)

    # 检查点管理器
    checkpoint = CheckpointManager(checkpoint_path, logger=logger)

    # 未读检测器
    unread_extractor = UnreadUserExtractor(logger=logger)

    media_bus, media_settings = build_media_event_bus(
        db_path,
        settings_db_path=str(get_default_db_path()),
        effects_db_path=db_path,
        wecom_service=wecom,
    )

    review_storage, review_submitter, review_gate_on = build_review_components(
        db_path=db_path,
        media_settings=media_settings,
        settings_db_path=str(get_default_db_path()),
    )

    # 消息处理器
    message_processor = create_message_processor(
        repository=repository,
        wecom_service=wecom,
        images_dir=images_dir,
        videos_dir=videos_dir,
        voices_dir=voices_dir,
        logger=logger,
        media_event_bus=media_bus,
        media_action_settings=media_settings,
        review_storage=review_storage,
        review_submitter=review_submitter,
        review_gate_enabled=review_gate_on,
    )

    # 头像管理器
    default_avatar = avatars_path / "avatar_default.png"
    avatar_manager = AvatarManager(
        wecom_service=wecom,
        avatars_dir=avatars_path,
        default_avatar=default_avatar if default_avatar.exists() else None,
        logger=logger,
        log_callback=log_callback,  # Pass log callback for frontend logging
    )

    # 客户同步器
    customer_syncer = CustomerSyncer(
        wecom_service=wecom,
        repository=repository,
        message_processor=message_processor,
        avatar_manager=avatar_manager,
        timing=timing,
        logger=logger,
    )

    # 同步编排器
    orchestrator = SyncOrchestrator(
        wecom_service=wecom,
        repository=repository,
        customer_syncer=customer_syncer,
        checkpoint_manager=checkpoint,
        unread_extractor=unread_extractor,
        timing=timing,
        logger=logger,
    )

    return orchestrator


def create_customer_syncer(
    config: Config | None = None,
    repository: ConversationRepository | None = None,
    db_path: str | None = None,
    images_dir: str | None = None,
    videos_dir: str | None = None,
    voices_dir: str | None = None,
    timing_multiplier: float = 1.0,
    logger: logging.Logger | None = None,
) -> CustomerSyncer:
    """
    创建单独的客户同步器

    用于只需要同步单个客户的场景。

    Args:
        config: 应用配置
        repository: 数据库仓库
        db_path: 数据库文件路径
        images_dir: 图片保存目录
        videos_dir: 视频保存目录
        voices_dir: 语音保存目录
        timing_multiplier: 延迟倍数
        logger: 日志记录器

    Returns:
        配置好的 CustomerSyncer 实例
    """
    logger = logger or logging.getLogger("wecom_automation.sync")

    config = config or Config()
    repository = repository or ConversationRepository(db_path)
    wecom = WeComService(config)
    timing = HumanTiming(timing_multiplier)

    resolved_db = db_path or repository.db_path
    media_bus, media_settings = build_media_event_bus(
        str(resolved_db),
        settings_db_path=str(get_default_db_path()),
        effects_db_path=str(resolved_db),
        wecom_service=wecom,
    )

    review_storage, review_submitter, review_gate_on = build_review_components(
        db_path=str(resolved_db),
        media_settings=media_settings,
        settings_db_path=str(get_default_db_path()),
    )

    # 消息处理器
    message_processor = create_message_processor(
        repository=repository,
        wecom_service=wecom,
        images_dir=images_dir,
        videos_dir=videos_dir,
        voices_dir=voices_dir,
        logger=logger,
        media_event_bus=media_bus,
        media_action_settings=media_settings,
        review_storage=review_storage,
        review_submitter=review_submitter,
        review_gate_enabled=review_gate_on,
    )

    return CustomerSyncer(
        wecom_service=wecom,
        repository=repository,
        message_processor=message_processor,
        timing=timing,
        logger=logger,
    )
