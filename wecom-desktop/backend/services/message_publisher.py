"""
消息事件发布器

在消息写入数据库后，发布事件通知前端。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime


logger = logging.getLogger(__name__)


class MessagePublisher:
    """消息事件发布器"""

    @staticmethod
    async def publish_message_added(
        serial: str,
        customer_id: int,
        customer_name: str,
        channel: Optional[str],
        message: Dict[str, Any],
    ) -> None:
        """
        发布单条消息添加事件

        Args:
            serial: 设备序列号
            customer_id: 客户 ID
            customer_name: 客户名称
            channel: 渠道
            message: 消息内容
        """
        from services.websocket_manager import get_sidecar_message_manager

        manager = get_sidecar_message_manager()

        event = {
            "type": "message_added",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "customer_id": customer_id,
                "customer_name": customer_name,
                "channel": channel,
                "message": message,
            },
        }

        sent = await manager.broadcast_to_conversation(serial, customer_name, channel, event)

        if sent > 0:
            logger.debug(f"[Publisher] Sent message_added to {sent} clients")

    @staticmethod
    async def publish_message_batch(
        serial: str,
        customer_name: str,
        channel: Optional[str],
        messages: List[Dict[str, Any]],
    ) -> None:
        """
        发布批量消息事件

        Args:
            serial: 设备序列号
            customer_name: 客户名称
            channel: 渠道
            messages: 消息列表
        """
        from services.websocket_manager import get_sidecar_message_manager

        manager = get_sidecar_message_manager()

        event = {
            "type": "message_batch",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "customer_name": customer_name,
                "channel": channel,
                "messages": messages,
                "count": len(messages),
            },
        }

        await manager.broadcast_to_conversation(serial, customer_name, channel, event)

    @staticmethod
    async def publish_history_refresh(
        serial: str,
        customer_name: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> None:
        """
        请求前端刷新完整历史

        Args:
            serial: 设备序列号
            customer_name: 客户名称（可选，为空则广播给设备所有连接）
            channel: 渠道（可选）
        """
        from services.websocket_manager import get_sidecar_message_manager

        manager = get_sidecar_message_manager()

        event = {
            "type": "history_refresh",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "customer_name": customer_name,
                "channel": channel,
            },
        }

        if customer_name:
            await manager.broadcast_to_conversation(serial, customer_name, channel, event)
        else:
            await manager.broadcast_to_device(serial, event)


# 便捷函数
async def notify_message_added(
    serial: str,
    customer_id: int,
    customer_name: str,
    channel: Optional[str],
    message: Dict[str, Any],
) -> None:
    """通知新消息添加"""
    await MessagePublisher.publish_message_added(serial, customer_id, customer_name, channel, message)


async def notify_history_refresh(
    serial: str,
    customer_name: Optional[str] = None,
    channel: Optional[str] = None,
) -> None:
    """通知刷新历史"""
    await MessagePublisher.publish_history_refresh(serial, customer_name, channel)
