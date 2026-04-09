#!/usr/bin/env python3
"""
快速测试图片发送功能

前提：手机已经在聊天界面
用法：python quick_test_image_sender.py --serial YOUR_DEVICE_SERIAL
"""

import asyncio
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

from wecom_automation.core.config import Config
from wecom_automation.core.logging import init_logging, get_logger
from wecom_automation.services.wecom_service import WeComService
from wecom_automation.services.message.image_sender import ImageSender


async def main():
    """主测试函数"""
    # 解析命令行参数
    import argparse
    parser = argparse.ArgumentParser(description="Quick test image sender")
    parser.add_argument("--serial", required=True, help="Device serial number")
    parser.add_argument("--index", type=int, default=0, help="Favorite index (default: 0)")
    args = parser.parse_args()

    # 初始化日志
    init_logging(hostname="test", level="INFO", console=True)
    logger = get_logger("quick_test")

    logger.info("=" * 60)
    logger.info("快速测试图片发送功能")
    logger.info("=" * 60)
    logger.info(f"设备: {args.serial}")
    logger.info(f"收藏索引: {args.index}")
    logger.info("前提：手机已在聊天界面")
    logger.info("=" * 60)

    try:
        # 创建配置
        logger.info("创建配置...")
        config = Config.from_env().with_overrides(device_serial=args.serial)

        # 创建 WeComService（内部会创建 ADBService）
        logger.info("初始化 WeComService...")
        wecom = WeComService(config)

        # 创建 ImageSender
        logger.info("创建 ImageSender...")
        sender = ImageSender(wecom)

        # 发送图片
        logger.info(f"开始发送收藏中第 {args.index} 个图片...")
        success = await sender.send_via_favorites(favorite_index=args.index)

        logger.info("=" * 60)
        if success:
            logger.info("✅ 测试成功！图片已发送")
        else:
            logger.error("❌ 测试失败！图片发送失败")
        logger.info("=" * 60)

        return success

    except Exception as e:
        logger.error(f"❌ 测试出错: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
