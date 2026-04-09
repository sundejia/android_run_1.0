#!/usr/bin/env python3
"""
图片发送功能测试脚本

这个脚本用于测试图片发送功能的基本流程。

使用方法:
    python test_image_sender.py --serial YOUR_DEVICE_SERIAL
    python test_image_sender.py --serial YOUR_DEVICE_SERIAL --list  # 列出收藏项
    python test_image_sender.py --serial YOUR_DEVICE_SERIAL --index 0  # 发送指定索引的图片
"""

import asyncio
import argparse
import sys
from pathlib import Path

# Add src to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

from wecom_automation.core.config import Config
from wecom_automation.core.logging import get_logger, init_logging
from wecom_automation.services.adb_service import ADBService
from wecom_automation.services.wecom_service import WeComService
from wecom_automation.services.message.image_sender import ImageSender, ElementNotFoundError

logger = get_logger("test_image_sender")


async def test_list_favorites(device_serial: str):
    """测试列出收藏项"""
    logger.info(f"📋 Listing favorites for device: {device_serial}")
    
    try:
        # 创建配置和服务
        config = Config.from_env().with_overrides(device_serial=device_serial)
        adb = ADBService(config)
        wecom = WeComService(config, adb)
        sender = ImageSender(wecom)
        
        # 列出收藏项
        favorites = await sender.list_favorites()
        
        if not favorites:
            logger.warning("⚠️ No favorites found. Please add some images to Favorites first.")
            return
        
        logger.info(f"✅ Found {len(favorites)} favorites:")
        for i, item in enumerate(favorites):
            logger.info(f"  [{i}] Index: {item['index']}, ID: {item['resource_id']}, Text: '{item['text']}'")
        
    except ElementNotFoundError as e:
        logger.error(f"❌ Element not found: {e}")
        logger.error("   Make sure you're in a chat conversation.")
    except Exception as e:
        logger.error(f"❌ Failed to list favorites: {e}")


async def test_send_image(device_serial: str, favorite_index: int = 0):
    """测试发送图片"""
    logger.info(f"📤 Sending image from favorites (device={device_serial}, index={favorite_index})")
    
    try:
        # 创建配置和服务
        config = Config.from_env().with_overrides(device_serial=device_serial)
        adb = ADBService(config)
        wecom = WeComService(config, adb)
        sender = ImageSender(wecom)
        
        # 发送图片
        success = await sender.send_via_favorites(favorite_index=favorite_index)
        
        if success:
            logger.info(f"✅ Image sent successfully (index={favorite_index})")
        else:
            logger.error(f"❌ Failed to send image (index={favorite_index})")
        
        return success
        
    except ElementNotFoundError as e:
        logger.error(f"❌ Element not found: {e}")
        logger.error("   Possible reasons:")
        logger.error("   - Not in a chat conversation")
        logger.error("   - Favorites is empty")
        logger.error("   - Index out of range")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to send image: {e}")
        return False


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Test image sender functionality")
    parser.add_argument("--serial", required=True, help="Device serial number")
    parser.add_argument("--list", action="store_true", help="List all favorite items")
    parser.add_argument("--index", type=int, default=0, help="Favorite index to send (default: 0)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    # 初始化日志
    level = "DEBUG" if args.debug else "INFO"
    init_logging(hostname="test", level=level, console=True)
    
    logger.info("=" * 60)
    logger.info("Image Sender Test Script")
    logger.info("=" * 60)
    
    if args.list:
        await test_list_favorites(args.serial)
    else:
        await test_send_image(args.serial, args.index)
    
    logger.info("=" * 60)
    logger.info("Test completed")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
