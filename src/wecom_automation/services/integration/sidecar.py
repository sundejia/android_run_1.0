"""
边车队列客户端

与边车队列API交互，用于消息审核和手动发送流程。
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

# Transient errors worth retrying
_RETRYABLE_ERRORS = (
    aiohttp.ServerDisconnectedError,
    aiohttp.ClientConnectorError,
    aiohttp.ClientOSError,
    ConnectionResetError,
    ConnectionRefusedError,
)

_MAX_RETRIES = 2
_RETRY_DELAY = 0.5  # seconds


class SidecarQueueClient:
    """
    边车队列客户端

    用于与后端边车队列API交互，支持:
    - 添加消息到队列
    - 标记消息为就绪
    - 等待消息发送
    - 管理队列状态
    - 自动重连和重试

    Usage:
        async with SidecarQueueClient(serial, backend_url) as client:
            msg_id = await client.add_message("客户", None, "消息内容")
            await client.set_message_ready(msg_id)
            result = await client.wait_for_send(msg_id)
    """

    def __init__(self, serial: str, backend_url: str = "http://localhost:8765", logger: Any = None):
        """
        初始化边车队列客户端

        Args:
            serial: 设备序列号
            backend_url: 后端服务URL
            logger: 日志记录器（支持 loguru 或 stdlib logging）
        """
        self.serial = serial
        self.backend_url = backend_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None

        # Always use loguru logger to avoid format errors
        if logger is None:
            from wecom_automation.core.logging import get_logger

            self._logger = get_logger(__name__)
        else:
            # If a logger is provided, wrap it in a loguru logger with proper module binding
            # to avoid KeyError when format expects extra[module]
            # Check if it's a stdlib logger
            import logging

            from wecom_automation.core.logging import get_logger

            if isinstance(logger, logging.Logger):
                # Use loguru logger instead, borrowing the name
                self._logger = get_logger(logger.name or "sidecar")
            else:
                # Assume it's already a loguru logger, but ensure module is bound
                self._logger = logger

    async def __aenter__(self):
        """进入异步上下文"""
        await self._ensure_session()
        return self

    async def __aexit__(self, *args):
        """退出异步上下文"""
        if self._session:
            await self._session.close()
            self._session = None

    def _create_session(self) -> aiohttp.ClientSession:
        """创建带合理默认超时的 HTTP 会话"""
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        connector = aiohttp.TCPConnector(
            limit=10,
            enable_cleanup_closed=True,
        )
        return aiohttp.ClientSession(timeout=timeout, connector=connector)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """确保 session 可用，如果已关闭则重新创建"""
        if self._session is None or self._session.closed:
            if self._session is not None:
                self._logger.debug("Session was closed, recreating...")
            self._session = self._create_session()
        return self._session

    @property
    def session(self) -> aiohttp.ClientSession:
        """获取HTTP会话（同步属性，优先使用 _ensure_session）"""
        if not self._session or self._session.closed:
            raise RuntimeError("SidecarQueueClient not initialized. Use 'async with' context manager.")
        return self._session

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        max_retries: int = _MAX_RETRIES,
        **kwargs,
    ) -> aiohttp.ClientResponse:
        """
        带自动重连和重试的请求方法

        Args:
            method: HTTP 方法 (get, post, put, delete)
            url: 请求 URL
            max_retries: 最大重试次数
            **kwargs: 传给 aiohttp 的额外参数

        Returns:
            aiohttp.ClientResponse

        Raises:
            最后一次异常（如果所有重试都失败）
        """
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                session = await self._ensure_session()
                resp = await session.request(method, url, **kwargs)
                return resp
            except _RETRYABLE_ERRORS as e:
                last_error = e
                if attempt < max_retries:
                    self._logger.warning(
                        f"Transient error (attempt {attempt + 1}/{max_retries + 1}): {e}, "
                        f"reconnecting in {_RETRY_DELAY}s..."
                    )
                    # Force session recreation on next attempt
                    if self._session and not self._session.closed:
                        await self._session.close()
                    self._session = None
                    await asyncio.sleep(_RETRY_DELAY)
                else:
                    raise
        # Should not reach here, but just in case
        raise last_error  # type: ignore[misc]

    async def add_message(self, customer_name: str, channel: str | None, message: str) -> str | None:
        """
        添加消息到队列

        Args:
            customer_name: 客户名称
            channel: 渠道
            message: 消息内容

        Returns:
            消息ID，失败返回None
        """
        url = f"{self.backend_url}/sidecar/{self.serial}/queue/add"
        payload = {
            "customerName": customer_name,
            "channel": channel,
            "message": message,
        }

        try:
            resp = await self._request_with_retry("POST", url, json=payload)
            async with resp:
                if resp.status == 200:
                    data = await resp.json()
                    msg_id = data.get("id")
                    self._logger.debug(f"Message added to queue: {msg_id}")
                    return msg_id
                else:
                    text = await resp.text()
                    self._logger.warning(f"Failed to add message: {resp.status} - {text}")
                    return None
        except Exception as e:
            self._logger.error(f"Error adding message to queue: {e}")
            return None

    async def set_message_ready(self, message_id: str) -> bool:
        """
        标记消息为就绪（可发送）

        Args:
            message_id: 消息ID

        Returns:
            是否成功
        """
        url = f"{self.backend_url}/sidecar/{self.serial}/queue/ready/{message_id}"

        try:
            resp = await self._request_with_retry("POST", url)
            async with resp:
                success = resp.status == 200
                if success:
                    self._logger.debug(f"Message marked as ready: {message_id}")
                else:
                    self._logger.warning(f"Failed to mark message ready: {resp.status}")
                return success
        except Exception as e:
            self._logger.error(f"Error marking message ready: {e}")
            return False

    async def wait_for_send(self, message_id: str, timeout: float = 60.0) -> dict:
        """
        等待消息发送完成

        Args:
            message_id: 消息ID
            timeout: 超时时间（秒）

        Returns:
            结果字典，包含:
            - success: 是否成功
            - reason: 原因 (sent, cancelled, timeout, error)
        """
        url = f"{self.backend_url}/sidecar/{self.serial}/queue/wait/{message_id}"
        params = {"timeout": timeout}

        try:
            # Long timeout for wait — user may take time to review
            resp = await self._request_with_retry(
                "POST",
                url,
                params=params,
                timeout=aiohttp.ClientTimeout(total=timeout + 10),
            )
            async with resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._logger.debug(f"Wait result: {data}")
                    return data
                else:
                    return {"success": False, "reason": "error"}

        except TimeoutError:
            self._logger.warning(f"Wait for send timed out: {message_id}")
            return {"success": False, "reason": "timeout"}
        except Exception as e:
            self._logger.error(f"Error waiting for send: {e}")
            return {"success": False, "reason": "error"}

    async def get_queue_state(self) -> dict:
        """
        获取当前队列状态

        Returns:
            队列状态字典
        """
        url = f"{self.backend_url}/sidecar/{self.serial}/queue"

        try:
            resp = await self._request_with_retry("GET", url)
            async with resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    return {"queue": [], "syncState": None}
        except Exception as e:
            self._logger.error(f"Error getting queue state: {e}")
            return {"queue": [], "syncState": None}

    async def is_skip_requested(self) -> bool:
        """
        检查是否有跳过请求

        优先检查专用 skip flag API，回退到检查队列状态

        Returns:
            True 如果跳过被请求
        """
        # First check the dedicated skip flag API
        try:
            url = f"{self.backend_url}/sidecar/{self.serial}/skip"
            self._logger.debug(f"🔍 Checking skip flag API: {url}")
            resp = await self._request_with_retry(
                "GET",
                url,
                timeout=aiohttp.ClientTimeout(total=5.0),
            )
            async with resp:
                self._logger.debug(f"🔍 Skip flag API response status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    self._logger.debug(f"🔍 Skip flag API response body: {data}")
                    if data.get("skip_requested", False):
                        self._logger.info("✅ Skip requested via skip flag API")
                        return True
                    else:
                        self._logger.debug("🔍 Skip flag API returned: skip_requested=False")
        except TimeoutError:
            self._logger.warning("⚠️ Skip flag API check timed out after 5s")
        except RuntimeError as e:
            # Session not initialized or closed - log warning and return False
            self._logger.warning(f"⚠️ Skip flag check failed (session error): {e}")
            return False
        except Exception as e:
            self._logger.warning(f"⚠️ Skip flag check failed, falling back to queue: {e}")

        # Fallback: check if any message is cancelled
        try:
            state = await self.get_queue_state()
            queue = state.get("queue", [])

            for msg in queue:
                if msg.get("status") == "cancelled":
                    self._logger.debug("✅ Skip detected via cancelled queue message")
                    return True
        except RuntimeError as e:
            # Session not initialized or closed - log warning and return False
            self._logger.warning(f"⚠️ Queue state check failed (session error): {e}")
            return False
        except Exception as e:
            self._logger.warning(f"⚠️ Queue state check failed: {e}")

        self._logger.debug("🔍 No skip request detected")
        return False

    async def request_skip(self) -> bool:
        """
        请求跳过当前用户

        Returns:
            是否成功
        """
        url = f"{self.backend_url}/sidecar/{self.serial}/skip"

        try:
            resp = await self._request_with_retry("POST", url)
            async with resp:
                success = resp.status == 200
                if success:
                    self._logger.info("Skip requested successfully")
                else:
                    text = await resp.text()
                    self._logger.warning(f"Failed to request skip: {resp.status} - {text}")
                return success
        except Exception as e:
            self._logger.error(f"Error requesting skip: {e}")
            return False

    async def clear_skip_flag(self) -> bool:
        """
        清除跳过标志

        在完成跳过操作后调用，准备处理下一个用户

        Returns:
            是否成功
        """
        url = f"{self.backend_url}/sidecar/{self.serial}/skip"

        try:
            resp = await self._request_with_retry("DELETE", url)
            async with resp:
                success = resp.status == 200
                if success:
                    self._logger.debug("Skip flag cleared")
                return success
        except Exception as e:
            self._logger.error(f"Error clearing skip flag: {e}")
            return False

    async def clear_queue(self) -> bool:
        """
        清空队列

        Returns:
            是否成功
        """
        url = f"{self.backend_url}/sidecar/{self.serial}/queue"

        try:
            resp = await self._request_with_retry("DELETE", url)
            async with resp:
                success = resp.status == 200
                if success:
                    self._logger.debug("Queue cleared")
                return success
        except Exception as e:
            self._logger.error(f"Error clearing queue: {e}")
            return False

    async def cancel_message(self, message_id: str) -> bool:
        """
        取消消息

        Args:
            message_id: 消息ID

        Returns:
            是否成功
        """
        url = f"{self.backend_url}/sidecar/{self.serial}/queue/cancel/{message_id}"

        try:
            resp = await self._request_with_retry("POST", url)
            async with resp:
                success = resp.status == 200
                if success:
                    self._logger.debug(f"Message cancelled: {message_id}")
                return success
        except Exception as e:
            self._logger.error(f"Error cancelling message: {e}")
            return False

    async def update_message(self, message_id: str, new_message: str) -> bool:
        """
        更新消息内容

        Args:
            message_id: 消息ID
            new_message: 新消息内容

        Returns:
            是否成功
        """
        url = f"{self.backend_url}/sidecar/{self.serial}/queue/update/{message_id}"
        payload = {"message": new_message}

        try:
            resp = await self._request_with_retry("PUT", url, json=payload)
            async with resp:
                success = resp.status == 200
                if success:
                    self._logger.debug(f"Message updated: {message_id}")
                return success
        except Exception as e:
            self._logger.error(f"Error updating message: {e}")
            return False

    async def mark_as_sent_directly(self, message_id: str) -> bool:
        """
        标记消息为已通过直接发送方式发送

        当 Sidecar 超时后回退到直接发送成功时调用此方法，
        将队列中的消息标记为已发送，防止后续误发。

        Args:
            message_id: 消息ID

        Returns:
            是否成功
        """
        url = f"{self.backend_url}/sidecar/{self.serial}/queue/mark-sent/{message_id}"

        try:
            resp = await self._request_with_retry("POST", url)
            async with resp:
                success = resp.status == 200
                if success:
                    self._logger.info(f"Message {message_id} marked as SENT (direct send)")
                else:
                    text = await resp.text()
                    self._logger.warning(f"Failed to mark message as sent: {resp.status} - {text}")
                return success
        except Exception as e:
            self._logger.error(f"Error marking message as sent: {e}")
            return False

    async def clear_expired_messages(self) -> int:
        """
        清理过期的队列消息

        删除所有 EXPIRED、CANCELLED、SENT 状态的消息，
        防止队列积累垃圾消息。

        Returns:
            清理的消息数量
        """
        url = f"{self.backend_url}/sidecar/{self.serial}/queue/clear-expired"

        try:
            resp = await self._request_with_retry("POST", url)
            async with resp:
                if resp.status == 200:
                    data = await resp.json()
                    cleared = data.get("cleared", 0)
                    if cleared > 0:
                        self._logger.info(f"Cleared {cleared} expired messages from queue")
                    return cleared
                return 0
        except Exception as e:
            self._logger.error(f"Error clearing expired messages: {e}")
            return 0
