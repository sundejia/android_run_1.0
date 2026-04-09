"""
通知模块 - 各类通知服务

模块组成:
- email: 邮件通知服务
"""

from wecom_automation.services.notification.email import EmailNotificationService

__all__ = [
    "EmailNotificationService",
]
