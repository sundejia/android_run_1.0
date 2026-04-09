"""
图片发送路由 - 提供通过 Favorites 发送图片的 API 接口

这个模块提供了发送收藏图片的 REST API，可以：
- 发送指定索引的收藏图片
- 列出所有可用的收藏项
- 支持多设备操作

作者: Claude Sonnet 4.5
日期: 2026-02-06
"""

import asyncio
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# Add project root to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from wecom_automation.core.config import Config
from wecom_automation.core.logging import get_logger
from wecom_automation.services.adb_service import ADBService
from wecom_automation.services.message.image_sender import ImageSender
from wecom_automation.services.wecom_service import WeComService

logger = get_logger("image_sender_router")

router = APIRouter(prefix="/image-sender", tags=["image-sender"])


# ==================== Request Models ====================


class SendImageRequest(BaseModel):
    """发送图片请求"""

    device_serial: str = Field(..., description="设备序列号")
    favorite_index: int = Field(0, description="收藏项索引（从 0 开始）", ge=0)


class ListFavoritesRequest(BaseModel):
    """列出收藏项请求"""

    device_serial: str = Field(..., description="设备序列号")


# ==================== Response Models ====================


class SendImageResponse(BaseModel):
    """发送图片响应"""

    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="响应消息")
    favorite_index: int = Field(..., description="使用的收藏项索引")


class FavoriteItem(BaseModel):
    """收藏项信息"""

    index: int = Field(..., description="UI 索引")
    resource_id: str = Field(..., description="资源 ID")
    text: str = Field(..., description="文本")
    bounds: str = Field(..., description="边界坐标")


class ListFavoritesResponse(BaseModel):
    """列出收藏项响应"""

    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="响应消息")
    favorites: list[FavoriteItem] = Field(default_factory=list, description="收藏项列表")


# ==================== Helper Functions ====================


async def _create_image_sender(device_serial: str) -> ImageSender:
    """
    创建 ImageSender 实例

    Args:
        device_serial: 设备序列号

    Returns:
        ImageSender 实例

    Raises:
        HTTPException: 设备连接失败或初始化失败
    """
    try:
        # 创建配置
        config = Config.from_env().with_overrides(device_serial=device_serial)

        # 创建 ADB 服务
        adb = ADBService(config)

        # 创建 WeComService
        wecom = WeComService(config, adb)

        # 创建 ImageSender
        sender = ImageSender(wecom)

        return sender

    except Exception as e:
        logger.error(f"Failed to create ImageSender for device {device_serial}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to initialize device: {str(e)}")


# ==================== API Endpoints ====================


@router.post("/send", response_model=SendImageResponse)
async def send_image(request: SendImageRequest) -> SendImageResponse:
    """
    发送收藏的图片

    这个接口会：
    1. 打开附件菜单
    2. 点击 Favorites
    3. 选择指定索引的收藏项
    4. 点击发送

    注意:
    - 调用前必须确保设备已进入对话界面
    - 确保 Favorites 中已有收藏的图片
    - favorite_index 从 0 开始计数
    """
    logger.info(f"📤 Sending image from favorites (device={request.device_serial}, index={request.favorite_index})")

    try:
        # 创建 ImageSender
        sender = await _create_image_sender(request.device_serial)

        # 发送图片
        success = await sender.send_via_favorites(favorite_index=request.favorite_index)

        if success:
            logger.info(f"✅ Image sent successfully (index={request.favorite_index})")
            return SendImageResponse(
                success=True, message="Image sent successfully", favorite_index=request.favorite_index
            )
        else:
            logger.error(f"❌ Failed to send image (index={request.favorite_index})")
            return SendImageResponse(
                success=False, message="Failed to send image", favorite_index=request.favorite_index
            )

    except Exception as e:
        logger.error(f"❌ Error sending image: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/list-favorites", response_model=ListFavoritesResponse)
async def list_favorites(request: ListFavoritesRequest) -> ListFavoritesResponse:
    """
    列出所有收藏项

    这个接口会：
    1. 打开附件菜单
    2. 点击 Favorites
    3. 列出所有收藏项及其信息
    4. 自动关闭菜单

    返回的每个收藏项包含：
    - index: UI 元素索引
    - resource_id: 资源 ID
    - text: 显示文本（如果有）
    - bounds: 边界坐标
    """
    logger.info(f"📋 Listing favorites (device={request.device_serial})")

    try:
        # 创建 ImageSender
        sender = await _create_image_sender(request.device_serial)

        # 列出收藏项
        favorites_raw = await sender.list_favorites()

        # 转换为响应模型
        favorites = [
            FavoriteItem(
                index=item["index"],
                resource_id=item["resource_id"],
                text=item["text"],
                bounds=item["bounds"],
            )
            for item in favorites_raw
        ]

        logger.info(f"✅ Found {len(favorites)} favorites")
        return ListFavoritesResponse(
            success=True, message=f"Found {len(favorites)} favorites", favorites=favorites
        )

    except Exception as e:
        logger.error(f"❌ Error listing favorites: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "image-sender"}
