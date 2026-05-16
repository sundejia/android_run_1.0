"""
通知模块 - 各类通知服务

模块组成:
- email: 邮件通知服务
- error_notification: 错误通知服务（带频率限制和去重）
- loguru_sink: Loguru 错误通知 sink
"""

from wecom_automation.services.notification.email import EmailNotificationService
from wecom_automation.services.notification.error_notification import (
    ErrorNotificationService,
)

__all__ = [
    "EmailNotificationService",
    "ErrorNotificationService",
]
