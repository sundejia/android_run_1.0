"""
邮件通知服务

发送邮件通知，用于转人工请求、语音消息等场景。
"""

from __future__ import annotations

import json
import logging
import smtplib
from datetime import datetime
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from typing import Any

from wecom_automation.core.interfaces import INotificationService


class EmailNotificationService(INotificationService):
    """
    邮件通知服务

    支持:
    - 转人工请求通知
    - 语音消息通知
    - 自定义邮件通知

    Usage:
        service = EmailNotificationService.from_config_file("email_settings.json")

        await service.send(
            subject="转人工请求",
            content="用户张三请求转人工",
            customer_name="张三",
            channel="@WeChat"
        )
    """

    def __init__(
        self,
        smtp_server: str = "smtp.qq.com",
        smtp_port: int = 465,
        sender_email: str = "",
        sender_password: str = "",
        sender_name: str = "WeCom 系统",
        receiver_email: str = "",
        enabled: bool = True,
        logger: logging.Logger | None = None,
    ):
        """
        初始化邮件通知服务

        Args:
            smtp_server: SMTP服务器地址
            smtp_port: SMTP端口
            sender_email: 发送者邮箱
            sender_password: 发送者密码/授权码
            sender_name: 发送者名称
            receiver_email: 接收者邮箱
            enabled: 是否启用
            logger: 日志记录器
        """
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.sender_email = sender_email
        self.sender_password = sender_password
        self.sender_name = sender_name
        self.receiver_email = receiver_email
        self.enabled = enabled
        self._logger = logger or logging.getLogger(__name__)

    @classmethod
    def from_config_file(cls, config_file: Path, logger: logging.Logger | None = None) -> EmailNotificationService:
        """
        从配置文件创建服务实例

        Args:
            config_file: JSON配置文件路径
            logger: 日志记录器

        Returns:
            EmailNotificationService实例
        """
        config_path = Path(config_file)

        if not config_path.exists():
            return cls(enabled=False, logger=logger)

        try:
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)

            return cls(
                smtp_server=config.get("smtp_server", "smtp.qq.com"),
                smtp_port=config.get("smtp_port", 465),
                sender_email=config.get("sender_email", ""),
                sender_password=config.get("sender_password", ""),
                sender_name=config.get("sender_name", "WeCom 系统"),
                receiver_email=config.get("receiver_email", ""),
                enabled=config.get("enabled", False),
                logger=logger,
            )
        except Exception as e:
            if logger:
                logger.warning(f"Failed to load email config: {e}")
            return cls(enabled=False, logger=logger)

    @classmethod
    def from_dict(cls, config: dict[str, Any], logger: logging.Logger | None = None) -> EmailNotificationService:
        """
        从字典创建服务实例

        Args:
            config: 配置字典
            logger: 日志记录器

        Returns:
            EmailNotificationService实例
        """
        return cls(
            smtp_server=config.get("smtp_server", "smtp.qq.com"),
            smtp_port=config.get("smtp_port", 465),
            sender_email=config.get("sender_email", ""),
            sender_password=config.get("sender_password", ""),
            sender_name=config.get("sender_name", "WeCom 系统"),
            receiver_email=config.get("receiver_email", ""),
            enabled=config.get("enabled", False),
            logger=logger,
        )

    async def send(self, subject: str, content: str, **kwargs) -> bool:
        """
        发送邮件通知

        Args:
            subject: 邮件主题
            content: 邮件内容（纯文本或HTML）
            **kwargs: 额外参数
                - html: 是否为HTML内容
                - customer_name: 客户名称
                - channel: 渠道
                - serial: 设备序列号

        Returns:
            是否发送成功
        """
        if not self.enabled:
            self._logger.debug("Email notification disabled")
            return False

        if not self.sender_email or not self.receiver_email:
            self._logger.warning("Email configuration incomplete")
            return False

        is_html = kwargs.get("html", False)

        try:
            # 创建邮件
            msg = MIMEMultipart("alternative")
            msg["From"] = formataddr([self.sender_name, self.sender_email])
            msg["To"] = formataddr(["", self.receiver_email])
            msg["Subject"] = Header(subject, "utf-8")

            # 添加内容
            if is_html:
                msg.attach(MIMEText(content, "html", "utf-8"))
            else:
                msg.attach(MIMEText(content, "plain", "utf-8"))

            # 发送
            if self.smtp_port == 465:
                server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, timeout=10)
            else:
                server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=10)
                server.starttls()

            server.login(self.sender_email, self.sender_password)
            server.sendmail(self.sender_email, [self.receiver_email], msg.as_string())
            server.quit()

            self._logger.info(f"Email sent: {subject}")
            return True

        except Exception as e:
            self._logger.error(f"Failed to send email: {e}")
            return False

    async def send_human_request_notification(
        self, customer_name: str, channel: str | None = None, serial: str | None = None
    ) -> bool:
        """
        发送转人工请求通知

        Args:
            customer_name: 客户名称
            channel: 渠道
            serial: 设备序列号

        Returns:
            是否发送成功
        """
        subject = f"🙋 用户请求转人工: {customer_name}"

        html_content = f"""
        <html>
        <head>
            <style>
                body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
                           color: white; padding: 20px; border-radius: 10px 10px 0 0; text-align: center; }}
                .content {{ background: #f8f9fa; padding: 20px; border-radius: 0 0 10px 10px; }}
                .info-row {{ margin: 10px 0; padding: 10px; background: white; border-radius: 5px; }}
                .label {{ color: #666; font-size: 12px; }}
                .value {{ font-size: 16px; font-weight: bold; color: #333; }}
                .warning {{ background: #fff3cd; border: 1px solid #ffc107; border-radius: 5px; padding: 10px; margin-top: 15px; }}
                .footer {{ text-align: center; margin-top: 20px; color: #999; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2 style="margin: 0;">🙋 用户请求转人工</h2>
                </div>
                <div class="content">
                    <div class="info-row">
                        <div class="label">客户名称</div>
                        <div class="value">{customer_name}</div>
                    </div>
                    <div class="info-row">
                        <div class="label">渠道</div>
                        <div class="value">{channel or "未知"}</div>
                    </div>
                    <div class="info-row">
                        <div class="label">设备</div>
                        <div class="value">{serial or "未知"}</div>
                    </div>
                    <div class="info-row">
                        <div class="label">时间</div>
                        <div class="value">{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
                    </div>
                    <div class="warning">
                        <strong>⚠️ 系统已自动将该用户加入黑名单</strong><br>
                        <span style="font-size: 12px; color: #666;">
                            后续同步将跳过此用户，请手动处理该客户的对话。
                        </span>
                    </div>
                </div>
                <div class="footer">
                    此邮件由 WeCom 同步系统自动发送
                </div>
            </div>
        </body>
        </html>
        """

        return await self.send(subject, html_content, html=True)

    async def send_voice_notification(
        self, customer_name: str, channel: str | None = None, serial: str | None = None
    ) -> bool:
        """
        发送语音消息通知

        Args:
            customer_name: 客户名称
            channel: 渠道
            serial: 设备序列号

        Returns:
            是否发送成功
        """
        subject = f"🎤 用户发语音通知 - {customer_name}"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="utf-8"></head>
        <body style="font-family: sans-serif;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #4CAF50, #45a049); color: white; padding: 20px; border-radius: 10px 10px 0 0;">
        <h2 style="margin: 0;">🎤 用户发语音通知</h2>
        </div>
        <div style="background: #f8f9fa; padding: 20px; border: 1px solid #e9ecef;">
        <p><strong>用户名称：</strong>{customer_name}</p>
        <p><strong>渠道/平台：</strong>{channel or "未知"}</p>
        <p><strong>设备：</strong>{serial or "未知"}</p>
        <p><strong>时间：</strong>{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        <div style="background: #fff3cd; border: 1px solid #ffc107; padding: 10px; border-radius: 5px; margin-top: 15px;">
        ⚠️ 该用户发送了语音消息，已自动加入黑名单。
        </div>
        </div>
        <div style="background: #e9ecef; padding: 15px; border-radius: 0 0 10px 10px; font-size: 12px; color: #6c757d;">
        此邮件由 WeCom 同步系统自动发送
        </div>
        </div>
        </body>
        </html>
        """

        return await self.send(subject, html_content, html=True)
