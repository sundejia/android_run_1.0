"""
集成模块 - 外部服务集成

模块组成:
- sidecar: 边车队列客户端
"""

from wecom_automation.services.integration.sidecar import SidecarQueueClient

__all__ = [
    "SidecarQueueClient",
]
