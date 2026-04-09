"""
WebSocket 连接管理器

管理 Sidecar 消息推送的 WebSocket 连接。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, Set, Optional, Any
from fastapi import WebSocket


logger = logging.getLogger(__name__)


class SidecarMessageManager:
    """Sidecar 消息 WebSocket 管理器"""

    def __init__(self):
        # 按 serial + conversation 分组的连接
        # Key: f"{serial}:{contact_name}:{channel}"
        self._connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    def _get_key(self, serial: str, contact_name: Optional[str] = None, channel: Optional[str] = None) -> str:
        """生成连接 Key"""
        return f"{serial}:{contact_name or ''}:{channel or ''}"

    async def connect(
        self,
        websocket: WebSocket,
        serial: str,
        contact_name: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> None:
        """注册 WebSocket 连接"""
        await websocket.accept()
        key = self._get_key(serial, contact_name, channel)

        async with self._lock:
            if key not in self._connections:
                self._connections[key] = set()
            self._connections[key].add(websocket)

        logger.info(f"[WS] Sidecar message connection added: {key}")

    async def disconnect(
        self,
        websocket: WebSocket,
        serial: str,
        contact_name: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> None:
        """断开 WebSocket 连接"""
        key = self._get_key(serial, contact_name, channel)

        async with self._lock:
            if key in self._connections:
                self._connections[key].discard(websocket)
                if not self._connections[key]:
                    del self._connections[key]

        logger.debug(f"[WS] Sidecar message connection removed: {key}")

    async def broadcast_to_conversation(
        self,
        serial: str,
        contact_name: Optional[str],
        channel: Optional[str],
        message: Dict[str, Any],
    ) -> int:
        """广播消息到特定对话的所有连接"""
        key = self._get_key(serial, contact_name, channel)
        sent_count = 0

        async with self._lock:
            connections = self._connections.get(key, set()).copy()

        for ws in connections:
            try:
                await ws.send_json(message)
                sent_count += 1
            except Exception as e:
                logger.warning(f"[WS] Failed to send message: {e}")
                # 移除失败的连接
                await self.disconnect(ws, serial, contact_name, channel)

        return sent_count

    async def broadcast_to_device(
        self,
        serial: str,
        message: Dict[str, Any],
    ) -> int:
        """广播消息到设备的所有连接（无论对话）"""
        sent_count = 0
        prefix = f"{serial}:"

        async with self._lock:
            matching_keys = [k for k in self._connections.keys() if k.startswith(prefix)]
            all_connections = []
            for key in matching_keys:
                all_connections.extend(self._connections[key])

        for ws in set(all_connections):
            try:
                await ws.send_json(message)
                sent_count += 1
            except Exception:
                pass

        return sent_count


# 单例实例
_manager: Optional[SidecarMessageManager] = None


def get_sidecar_message_manager() -> SidecarMessageManager:
    """获取 WebSocket 管理器单例"""
    global _manager
    if _manager is None:
        _manager = SidecarMessageManager()
    return _manager
