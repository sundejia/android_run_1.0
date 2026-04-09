"""
全局 WebSocket 路由

为所有前端组件提供统一的 WebSocket 连接和事件广播。
解决 History 界面无法实时更新的问题。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import List, Set, Dict, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()


class GlobalConnectionManager:
    """
    全局 WebSocket 连接管理器

    管理所有前端组件的 WebSocket 连接，支持广播消息到所有连接。
    """

    def __init__(self):
        # 存储所有活动连接
        self.active_connections: List[WebSocket] = []

        # 统计信息
        self.stats = {
            "total_connections": 0,
            "total_messages_sent": 0,
            "total_broadcasts": 0,
        }

        # 锁：确保线程安全
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        """接受新的 WebSocket 连接"""
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
            self.stats["total_connections"] += 1

        logger.info(f"[GlobalWS] New connection (total: {len(self.active_connections)})")

        # 发送连接成功消息
        await websocket.send_json(
            {
                "type": "connected",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "connection_id": id(websocket),
                    "total_connections": len(self.active_connections),
                },
            }
        )

    def disconnect(self, websocket: WebSocket):
        """移除断开的 WebSocket 连接"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"[GlobalWS] Connection removed (remaining: {len(self.active_connections)})")

    async def broadcast(self, message: dict) -> int:
        """
        广播消息到所有连接

        Args:
            message: 要广播的消息字典

        Returns:
            成功发送的连接数量
        """
        self.stats["total_broadcasts"] += 1

        # 复制连接列表，避免迭代时修改
        async with self._lock:
            connections = self.active_connections.copy()

        sent_count = 0
        errors = []

        for connection in connections:
            try:
                await connection.send_json(message)
                sent_count += 1
            except Exception as e:
                logger.warning(f"[GlobalWS] Failed to send to connection: {e}")
                errors.append((connection, e))

        # 移除失败的连接
        for connection, error in errors:
            if connection in self.active_connections:
                self.active_connections.remove(connection)

        self.stats["total_messages_sent"] += sent_count

        if sent_count > 0:
            logger.debug(
                f"[GlobalWS] Broadcast '{message.get('type', 'unknown')}' "
                f"to {sent_count}/{len(connections)} connections"
            )

        return sent_count

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self.stats,
            "active_connections": len(self.active_connections),
        }


# 单例实例
_manager: GlobalConnectionManager | None = None


def get_global_ws_manager() -> GlobalConnectionManager:
    """获取全局 WebSocket 管理器单例"""
    global _manager
    if _manager is None:
        _manager = GlobalConnectionManager()
    return _manager


@router.websocket("/ws/global")
async def global_websocket_endpoint(websocket: WebSocket):
    """
    全局 WebSocket 端点

    前端所有组件都可以连接到此端点接收实时更新。
    """
    manager = get_global_ws_manager()

    await manager.connect(websocket)

    try:
        # 保持连接，等待接收客户端消息（如果需要）
        while True:
            # 接收客户端消息（主要用于保持连接活跃）
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # 可以处理客户端发送的消息（如果需要）
                if data:
                    try:
                        message = json.loads(data)
                        logger.debug(f"[GlobalWS] Received from client: {message.get('type', 'unknown')}")
                    except json.JSONDecodeError:
                        logger.warning(f"[GlobalWS] Invalid JSON from client: {data[:100]}")
            except asyncio.TimeoutError:
                # 发送心跳，保持连接活跃
                try:
                    await websocket.send_json(
                        {
                            "type": "heartbeat",
                            "timestamp": datetime.now().isoformat(),
                        }
                    )
                except Exception:
                    break
    except WebSocketDisconnect:
        logger.info("[GlobalWS] Client disconnected")
    except Exception as e:
        logger.error(f"[GlobalWS] Error in websocket loop: {e}")
    finally:
        manager.disconnect(websocket)


@router.get("/ws/global/stats")
async def get_global_ws_stats():
    """
    获取全局 WebSocket 统计信息

    Returns:
        连接统计信息
    """
    manager = get_global_ws_manager()
    return manager.get_stats()


@router.post("/ws/global/test/broadcast")
async def test_broadcast(customer_name: str = "测试客户", channel: str = "wechat", customer_id: int = 1):
    """
    测试 WebSocket 广播

    用于测试前端是否能正确接收 history_refresh 事件。
    """
    sent_count = await broadcast_history_refresh(
        customer_name=customer_name,
        channel=channel,
        customer_id=customer_id,
    )
    return {
        "status": "ok",
        "message": f"Broadcast sent to {sent_count} connection(s)",
        "sent_count": sent_count,
    }


# ==================== 便捷广播函数 ====================


async def broadcast_history_refresh(
    customer_name: str,
    channel: str | None = None,
    customer_id: int | None = None,
    reason: str | None = None,
    extra: dict[str, Any] | None = None,
) -> int:
    """
    广播 history_refresh 事件

    Args:
        customer_name: 客户名称
        channel: 渠道
        customer_id: 客户 ID（可选）

    Returns:
        成功发送的连接数量
    """
    manager = get_global_ws_manager()

    event = {
        "type": "history_refresh",
        "timestamp": datetime.now().isoformat(),
        "data": {
            "customer_name": customer_name,
            "channel": channel,
            "customer_id": customer_id,
            "reason": reason,
            **(extra or {}),
        },
    }

    return await manager.broadcast(event)


async def broadcast_message_added(
    customer_id: int,
    customer_name: str,
    channel: str | None = None,
    message: dict | None = None,
) -> int:
    """
    广播 message_added 事件

    Args:
        customer_id: 客户 ID
        customer_name: 客户名称
        channel: 渠道
        message: 消息内容（可选）

    Returns:
        成功发送的连接数量
    """
    manager = get_global_ws_manager()

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

    return await manager.broadcast(event)


async def broadcast_customer_updated(
    customer_id: int,
    customer_name: str,
    channel: str | None = None,
) -> int:
    """
    广播 customer_updated 事件

    Args:
        customer_id: 客户 ID
        customer_name: 客户名称
        channel: 渠道

    Returns:
        成功发送的连接数量
    """
    manager = get_global_ws_manager()

    event = {
        "type": "customer_updated",
        "timestamp": datetime.now().isoformat(),
        "data": {
            "customer_id": customer_id,
            "customer_name": customer_name,
            "channel": channel,
        },
    }

    return await manager.broadcast(event)


async def broadcast_media_action_triggered(
    customer_name: str,
    device_serial: str,
    message_type: str,
    results: list[dict[str, Any]],
) -> int:
    """
    Broadcast a media_action_triggered event.

    Sent when automated actions fire after a customer sends media.
    """
    manager = get_global_ws_manager()

    event = {
        "type": "media_action_triggered",
        "timestamp": datetime.now().isoformat(),
        "data": {
            "customer_name": customer_name,
            "device_serial": device_serial,
            "message_type": message_type,
            "results": results,
        },
    }

    return await manager.broadcast(event)


async def broadcast_blacklist_updated(
    customer_name: str,
    device_serial: str,
    is_blacklisted: bool,
    reason: str | None = None,
) -> int:
    """
    Broadcast a blacklist_updated event.

    Sent when a customer's blacklist status changes (manual or auto).
    """
    manager = get_global_ws_manager()

    event = {
        "type": "blacklist_updated",
        "timestamp": datetime.now().isoformat(),
        "data": {
            "customer_name": customer_name,
            "device_serial": device_serial,
            "is_blacklisted": is_blacklisted,
            "reason": reason,
        },
    }

    return await manager.broadcast(event)


# ==================== 导出便捷函数 ====================

__all__ = [
    "router",
    "get_global_ws_manager",
    "broadcast_history_refresh",
    "broadcast_message_added",
    "broadcast_customer_updated",
    "broadcast_media_action_triggered",
    "broadcast_blacklist_updated",
]
