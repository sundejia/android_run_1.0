#!/usr/bin/env python3
"""
初始化 Realtime Reply 设置到数据库

将 Realtime Reply 的默认设置写入数据库的 settings 表。
如果设置已存在，则跳过（不会被覆盖）。
"""

import sys
from pathlib import Path

# 添加 src 目录和 backend 目录到 Python 路径
from utils.path_utils import get_project_root

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

project_root = get_project_root()
src_dir = project_root / "src"

sys.path.insert(0, str(src_dir))

from wecom_automation.core.config import get_default_db_path
from services.settings.repository import SettingsRepository
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def init_realtime_settings():
    """初始化 Realtime Reply 设置"""
    # 获取数据库路径
    db_path = str(get_default_db_path())
    logger.info(f"使用数据库: {db_path}")

    # 创建 repository
    repo = SettingsRepository(db_path, logger)

    # 定义 Realtime Reply 设置
    realtime_settings = [
        # (category, key, value, description, is_sensitive)
        ("realtime", "scan_interval", 60, "扫描间隔(秒)", False),
        ("realtime", "use_ai_reply", False, "使用 AI 生成回复", False),
        ("realtime", "send_via_sidecar", True, "通过 Sidecar 发送以供人工审核", False),
    ]

    logger.info("开始初始化 Realtime Reply 设置...")

    updated_count = 0
    skipped_count = 0

    for category, key, value, description, is_sensitive in realtime_settings:
        # 检查设置是否已存在
        existing = repo.get(category, key)

        if existing is not None:
            logger.info(f"跳过已存在的设置: {category}.{key} = {existing.value}")
            skipped_count += 1
        else:
            # 创建新设置
            repo.set(category, key, value, "init", description, is_sensitive)
            logger.info(f"创建设置: {category}.{key} = {value}")
            updated_count += 1

    logger.info("=" * 50)
    logger.info(f"初始化完成: 创建 {updated_count} 个新设置, 跳过 {skipped_count} 个已存在的设置")
    logger.info("=" * 50)

    # 验证设置
    logger.info("\n验证 Realtime Reply 设置:")
    all_realtime = repo.get_category("realtime")
    for key, value in sorted(all_realtime.items()):
        logger.info(f"  {key}: {value}")


if __name__ == "__main__":
    try:
        init_realtime_settings()
        print("\n[OK] Realtime Reply settings initialized successfully")
    except Exception as e:
        logger.error(f"初始化失败: {e}", exc_info=True)
        sys.exit(1)
