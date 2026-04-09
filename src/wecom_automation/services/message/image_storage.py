"""
图片存储辅助类

统一的图片保存逻辑，被 ImageMessageHandler 和 sync_service 共同使用。
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from wecom_automation.database.models import ImageRecord
from wecom_automation.database.repository import ConversationRepository


class ImageStorageHelper:
    """
    图片存储辅助类

    职责:
    - 统一的图片保存逻辑
    - 支持从现有文件复制和从 bounds 截图两种模式
    - 创建统一的数据库记录
    """

    def __init__(self, repository: ConversationRepository, images_dir: Path, logger=None):
        """
        初始化图片存储辅助类

        Args:
            repository: 数据库仓库
            images_dir: 图片保存目录
            logger: 日志记录器
        """
        self._repository = repository
        self._images_dir = Path(images_dir)
        self._images_dir.mkdir(parents=True, exist_ok=True)
        self._logger = logger

    def generate_image_path(
        self,
        customer_id: int,
        message_id: int,
    ) -> tuple[Path, str]:
        """
        生成图片保存路径和文件名

        Args:
            customer_id: 客户ID
            message_id: 消息ID

        Returns:
            (filepath, filename) 元组
        """
        # 创建客户目录
        customer_dir = self._images_dir / f"customer_{customer_id}"
        customer_dir.mkdir(parents=True, exist_ok=True)

        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"msg_{message_id}_{timestamp}.png"
        filepath = customer_dir / filename

        return filepath, filename

    def get_image_dimensions(self, filepath: Path) -> tuple[int, int]:
        """
        获取图片尺寸

        Args:
            filepath: 图片文件路径

        Returns:
            (width, height) 元组，失败返回 (0, 0)
        """
        try:
            from PIL import Image

            with Image.open(filepath) as img:
                return img.size
        except Exception as e:
            if self._logger:
                self._logger.warning(f"Could not get image dimensions: {e}")
            return 0, 0

    def create_image_record(
        self,
        message_id: int,
        file_path: str,
        file_name: str,
        original_bounds: str | None = None,
        source_path: Path | None = None,
    ) -> ImageRecord | None:
        """
        创建图片数据库记录

        Args:
            message_id: 消息ID
            file_path: 图片文件路径
            file_name: 文件名
            original_bounds: 原始边界坐标
            source_path: 源文件路径（用于复制时获取尺寸）

        Returns:
            ImageRecord 对象，失败返回 None
        """
        try:
            # 获取图片尺寸
            filepath = Path(file_path)
            width, height = 0, 0

            if filepath.exists():
                width, height = self.get_image_dimensions(filepath)

            # 创建图片记录
            image_record = ImageRecord(
                message_id=message_id,
                file_path=file_path,
                file_name=file_name,
                original_bounds=original_bounds,
                width=width,
                height=height,
                file_size=os.path.getsize(filepath) if filepath.exists() else 0,
            )
            self._repository.create_image(image_record)

            return image_record

        except Exception as e:
            if self._logger:
                self._logger.error(f"Failed to create image record: {e}")
            return None

    def copy_from_source(
        self,
        source_path: Path,
        dest_path: Path,
    ) -> bool:
        """
        从源路径复制图片到目标路径

        Args:
            source_path: 源文件路径
            dest_path: 目标文件路径

        Returns:
            是否成功
        """
        try:
            import shutil

            if not source_path.exists():
                if self._logger:
                    self._logger.warning(f"Source image not found: {source_path}")
                return False

            # 确保目标目录存在
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            # 复制文件
            shutil.copy2(source_path, dest_path)
            return True

        except Exception as e:
            if self._logger:
                self._logger.error(f"Failed to copy image from {source_path} to {dest_path}: {e}")
            return False

    async def save_image_from_bounds(
        self,
        wecom_service,
        customer_id: int,
        message_id: int,
        bounds: str,
    ) -> Path | None:
        """
        通过 bounds 截图保存图片

        Args:
            wecom_service: WeComService 实例
            customer_id: 客户ID
            message_id: 消息ID
            bounds: 图片边界坐标

        Returns:
            保存的文件路径，失败返回 None
        """
        # 验证 bounds 格式
        parsed_bounds = self.parse_bounds(bounds)
        if not parsed_bounds:
            if self._logger:
                self._logger.error(
                    f"Invalid bounds format: '{bounds}'. Expected format: '[x1,y1][x2,y2]'. message_id={message_id}"
                )
            return None

        # 生成文件路径
        filepath, filename = self.generate_image_path(customer_id, message_id)

        try:
            # 截图
            await wecom_service.screenshot_element(bounds, str(filepath))

            if filepath.exists():
                # 创建数据库记录
                self.create_image_record(
                    message_id=message_id,
                    file_path=str(filepath),
                    file_name=filename,
                    original_bounds=bounds,
                )

                # 更新消息的 extra_info
                self._repository.update_message_extra_info(message_id, {"image_path": str(filepath)})

                if self._logger:
                    self._logger.info(f"Image saved from bounds: {filepath}")
                return filepath
            else:
                if self._logger:
                    self._logger.warning(
                        f"Screenshot file not created after capture. bounds={bounds}, filepath={filepath}"
                    )
                return None

        except Exception as e:
            if self._logger:
                self._logger.error(f"Failed to save image from bounds (message_id={message_id}): {e}")
            return None

    def save_image_from_source(
        self,
        source_path: Path,
        customer_id: int,
        message_id: int,
        bounds: str | None = None,
    ) -> Path | None:
        """
        从源文件保存图片到客户目录。

        If the source file is already inside the correct customer directory
        (e.g. preloaded by realtime reply), it is used in-place without
        copying a second file.

        Args:
            source_path: 源文件路径
            customer_id: 客户ID
            message_id: 消息ID
            bounds: 原始边界坐标（可选）

        Returns:
            保存的文件路径，失败返回 None
        """
        customer_dir = self._images_dir / f"customer_{customer_id}"
        customer_dir.mkdir(parents=True, exist_ok=True)

        if source_path.parent.resolve() == customer_dir.resolve():
            final_path = source_path
            filename = source_path.name
            if self._logger:
                self._logger.info(f"Pre-captured image already in customer dir: {final_path}")
        else:
            final_path, filename = self.generate_image_path(customer_id, message_id)
            if not self.copy_from_source(source_path, final_path):
                return None
            if self._logger:
                self._logger.info(f"Image copied from source: {final_path}")

        self.create_image_record(
            message_id=message_id,
            file_path=str(final_path),
            file_name=filename,
            original_bounds=bounds,
            source_path=final_path,
        )

        return final_path

    @staticmethod
    def parse_bounds(bounds: str) -> tuple | None:
        """
        解析 bounds 字符串为坐标元组

        Args:
            bounds: 如 "[100,200][300,400]"

        Returns:
            (x1, y1, x2, y2) 元组
        """
        import re

        if not bounds:
            return None

        match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if match:
            return tuple(map(int, match.groups()))

        return None
