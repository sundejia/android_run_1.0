"""
Email notification router.

Provides API endpoints for email configuration and testing.
"""

import asyncio
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from email.header import Header
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


router = APIRouter(prefix="/settings/email", tags=["email"])


class EmailConfig(BaseModel):
    """Email configuration for testing."""

    smtp_server: str = "smtp.qq.com"
    smtp_port: int = 465
    sender_email: str
    sender_password: str
    sender_name: str = "WeCom 同步系统"
    receiver_email: str


class EmailTestResponse(BaseModel):
    """Response for email test."""

    success: bool
    message: str


def send_email(
    config: EmailConfig,
    subject: str,
    content: str,
    html_content: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Send an email using the provided configuration.

    Args:
        config: Email configuration
        subject: Email subject
        content: Plain text content
        html_content: Optional HTML content

    Returns:
        Tuple of (success, message)
    """
    try:
        # Create message
        if html_content:
            msg = MIMEMultipart("alternative")
            msg.attach(MIMEText(content, "plain", "utf-8"))
            msg.attach(MIMEText(html_content, "html", "utf-8"))
        else:
            msg = MIMEText(content, "plain", "utf-8")

        msg["From"] = formataddr([config.sender_name, config.sender_email])
        msg["To"] = formataddr(["", config.receiver_email])
        msg["Subject"] = Header(subject, "utf-8")

        # Connect and send
        if config.smtp_port == 465:
            # SSL
            server = smtplib.SMTP_SSL(config.smtp_server, config.smtp_port, timeout=10)
        else:
            # TLS
            server = smtplib.SMTP(config.smtp_server, config.smtp_port, timeout=10)
            server.starttls()

        server.login(config.sender_email, config.sender_password)
        server.sendmail(config.sender_email, [config.receiver_email], msg.as_string())
        server.quit()

        return True, "邮件发送成功"

    except smtplib.SMTPAuthenticationError as e:
        return False, f"认证失败，请检查邮箱和授权码: {str(e)}"
    except smtplib.SMTPConnectError as e:
        return False, f"连接服务器失败: {str(e)}"
    except smtplib.SMTPException as e:
        return False, f"SMTP错误: {str(e)}"
    except Exception as e:
        return False, f"发送失败: {str(e)}"


@router.post("/test", response_model=EmailTestResponse)
async def test_email(config: EmailConfig):
    """
    Test email configuration by sending a test email.
    """
    subject = "WeCom 系统 - 邮件测试"

    html_content = f"""
    <html>
    <head>
        <style>
            body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                       color: white; padding: 20px; border-radius: 10px 10px 0 0; text-align: center; }}
            .content {{ background: #f8f9fa; padding: 20px; border-radius: 0 0 10px 10px; }}
            .info-row {{ margin: 10px 0; padding: 10px; background: white; border-radius: 5px; }}
            .label {{ color: #666; font-size: 12px; }}
            .value {{ font-size: 14px; color: #333; }}
            .footer {{ text-align: center; margin-top: 20px; color: #999; font-size: 12px; }}
            .success {{ color: #28a745; font-size: 24px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="success">✅</div>
                <h2 style="margin: 10px 0 0 0;">邮件配置测试成功</h2>
            </div>
            <div class="content">
                <p style="text-align: center; color: #666;">
                    如果您收到此邮件，说明邮件通知功能已正确配置！
                </p>
                <div class="info-row">
                    <div class="label">发送时间</div>
                    <div class="value">{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
                </div>
                <div class="info-row">
                    <div class="label">SMTP 服务器</div>
                    <div class="value">{config.smtp_server}:{config.smtp_port}</div>
                </div>
                <div class="info-row">
                    <div class="label">发件人</div>
                    <div class="value">{config.sender_name} &lt;{config.sender_email}&gt;</div>
                </div>
            </div>
            <div class="footer">
                此邮件由 WeCom 同步系统自动发送
            </div>
        </div>
    </body>
    </html>
    """

    plain_content = f"""
WeCom 系统 - 邮件测试成功

如果您收到此邮件，说明邮件通知功能已正确配置！

发送时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
SMTP 服务器: {config.smtp_server}:{config.smtp_port}
发件人: {config.sender_name} <{config.sender_email}>

此邮件由 WeCom 同步系统自动发送
    """

    success, message = send_email(config, subject, plain_content, html_content)

    return EmailTestResponse(success=success, message=message)


class EmailSettings(BaseModel):
    """Full email settings for persistence."""

    enabled: bool = False
    smtp_server: str = "smtp.qq.com"
    smtp_port: int = 465
    sender_email: str = ""
    sender_password: str = ""
    sender_name: str = "WeCom 同步系统"
    receiver_email: str = ""
    notify_on_voice: bool = True
    notify_on_human_request: bool = True


# Import the settings service
from services.settings import get_settings_service, SettingCategory


@router.get("/settings")
async def get_email_settings():
    """Get saved email settings from database."""
    try:
        service = get_settings_service()
        email = service.get_email_settings()
        return {
            "enabled": email.enabled,
            "smtp_server": email.smtp_server,
            "smtp_port": email.smtp_port,
            "sender_email": email.sender_email,
            "sender_password": email.sender_password,
            "sender_name": email.sender_name,
            "receiver_email": email.receiver_email,
            "notify_on_voice": email.notify_on_voice,
            "notify_on_human_request": email.notify_on_human_request,
        }
    except Exception:
        return EmailSettings().model_dump()


@router.put("/settings")
async def save_email_settings(settings: EmailSettings):
    """Save email settings to database."""
    try:
        service = get_settings_service()
        data = settings.model_dump()
        service.set_category(SettingCategory.EMAIL.value, data, "api")

        return {"success": True, "message": "Settings saved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# Human Request Notification & Blacklist
# ==========================================

from pathlib import Path

# Import database blacklist service
from wecom_automation.services.blacklist_service import BlacklistChecker, BlacklistWriter


class HumanRequestNotification(BaseModel):
    """Request to add user to blacklist and send notification."""

    customer_name: str
    channel: Optional[str] = None
    serial: str
    reason: str = "Requested human agent"


def _add_to_blacklist(customer_name: str, channel: Optional[str], serial: str, reason: str) -> bool:
    """Add a user to the blacklist (database version)."""
    try:
        # Check if already blacklisted
        if BlacklistChecker.is_blacklisted(serial, customer_name, channel):
            return False  # Already blacklisted

        # Add to blacklist
        writer = BlacklistWriter()
        writer.add_to_blacklist(
            device_serial=serial,
            customer_name=customer_name,
            customer_channel=channel,
            reason=reason,
            deleted_by_user=False,  # This is a human request, not user deletion
        )
        return True
    except Exception as e:
        print(f"Failed to add to blacklist: {e}")
        return False


@router.post("/human-request", response_model=EmailTestResponse)
async def handle_human_request(request: HumanRequestNotification):
    """
    Handle human request: add user to blacklist and send email notification.

    This endpoint is called when AI detects that a user wants to speak with a human agent.
    """
    # Add to blacklist (sync DB work — dispatch off the event loop so other
    # devices' sidecar/HTTP traffic isn't stalled by SQLite contention).
    added = await asyncio.to_thread(
        _add_to_blacklist,
        request.customer_name,
        request.channel,
        request.serial,
        request.reason,
    )

    # Load email settings from database
    try:
        service = get_settings_service()
        email_settings = service.get_email_settings()
        if not email_settings.enabled or not email_settings.notify_on_human_request:
            return EmailTestResponse(
                success=True,
                message=f"User {request.customer_name} added to blacklist. Email notification disabled.",
            )

        config = EmailConfig(
            smtp_server=email_settings.smtp_server,
            smtp_port=email_settings.smtp_port,
            sender_email=email_settings.sender_email,
            sender_password=email_settings.sender_password,
            sender_name=email_settings.sender_name,
            receiver_email=email_settings.receiver_email,
        )
    except Exception as e:
        return EmailTestResponse(
            success=False,
            message=f"Failed to load email settings: {str(e)}"
        )

    subject = f"🙋 用户转人工通知 - {request.customer_name}"
    content = f"""
用户转人工请求

用户名称：{request.customer_name}
渠道/平台：{request.channel or "未知"}
设备：{request.serial}
原因：{request.reason}
时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

该用户已自动加入黑名单，后续同步将跳过此用户。
"""

    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #ff6b6b, #ee5a52); color: white; padding: 20px; border-radius: 10px 10px 0 0; }}
        .content {{ background: #f8f9fa; padding: 20px; border: 1px solid #e9ecef; }}
        .footer {{ background: #e9ecef; padding: 15px; border-radius: 0 0 10px 10px; font-size: 12px; color: #6c757d; }}
        .info-item {{ margin: 10px 0; padding: 10px; background: white; border-radius: 5px; }}
        .label {{ color: #6c757d; font-size: 12px; }}
        .value {{ font-weight: bold; color: #333; }}
        .warning {{ background: #fff3cd; border: 1px solid #ffc107; padding: 10px; border-radius: 5px; margin-top: 15px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2 style="margin: 0;">🙋 用户转人工通知</h2>
        </div>
        <div class="content">
            <div class="info-item">
                <div class="label">用户名称</div>
                <div class="value">{request.customer_name}</div>
            </div>
            <div class="info-item">
                <div class="label">渠道/平台</div>
                <div class="value">{request.channel or "未知"}</div>
            </div>
            <div class="info-item">
                <div class="label">设备</div>
                <div class="value">{request.serial}</div>
            </div>
            <div class="info-item">
                <div class="label">时间</div>
                <div class="value">{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
            </div>
            <div class="warning">
                ⚠️ 该用户已自动加入黑名单，后续同步将跳过此用户。
            </div>
        </div>
        <div class="footer">
            此邮件由 WeCom 同步系统自动发送
        </div>
    </div>
</body>
</html>
"""

    success, message = send_email(config, subject, content, html_content)

    status_msg = "已添加到黑名单" if added else "已在黑名单中"
    email_msg = "邮件已发送" if success else f"邮件发送失败: {message}"

    return EmailTestResponse(success=True, message=f"{status_msg}，{email_msg}")


@router.post("/voice-message", response_model=EmailTestResponse)
async def handle_voice_message(request: HumanRequestNotification):
    """
    Handle voice message: add user to blacklist and send email notification.

    This endpoint is called when a customer sends a voice message.
    """
    # Add to blacklist (sync DB work — dispatch off the event loop so other
    # devices' sidecar/HTTP traffic isn't stalled by SQLite contention).
    added = await asyncio.to_thread(
        _add_to_blacklist,
        request.customer_name,
        request.channel,
        request.serial,
        request.reason or "Sent voice message",
    )

    # Load email settings from database
    try:
        service = get_settings_service()
        email_settings = service.get_email_settings()
        if not email_settings.enabled or not email_settings.notify_on_voice:
            return EmailTestResponse(
                success=True,
                message=f"User {request.customer_name} added to blacklist. Voice email notification disabled.",
            )

        config = EmailConfig(
            smtp_server=email_settings.smtp_server,
            smtp_port=email_settings.smtp_port,
            sender_email=email_settings.sender_email,
            sender_password=email_settings.sender_password,
            sender_name=email_settings.sender_name,
            receiver_email=email_settings.receiver_email,
        )
    except Exception as e:
        return EmailTestResponse(
            success=False,
            message=f"Failed to load email settings: {str(e)}"
        )

    subject = f"🎤 用户发语音通知 - {request.customer_name}"
    content = f"""
用户发语音通知

用户名称：{request.customer_name}
渠道/平台：{request.channel or "未知"}
设备：{request.serial}
时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

该用户发送了语音消息，已自动加入黑名单。
"""

    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #4CAF50, #45a049); color: white; padding: 20px; border-radius: 10px 10px 0 0; }}
        .content {{ background: #f8f9fa; padding: 20px; border: 1px solid #e9ecef; }}
        .footer {{ background: #e9ecef; padding: 15px; border-radius: 0 0 10px 10px; font-size: 12px; color: #6c757d; }}
        .info-item {{ margin: 10px 0; padding: 10px; background: white; border-radius: 5px; }}
        .label {{ color: #6c757d; font-size: 12px; }}
        .value {{ font-weight: bold; color: #333; }}
        .warning {{ background: #fff3cd; border: 1px solid #ffc107; padding: 10px; border-radius: 5px; margin-top: 15px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2 style="margin: 0;">🎤 用户发语音通知</h2>
        </div>
        <div class="content">
            <div class="info-item">
                <div class="label">用户名称</div>
                <div class="value">{request.customer_name}</div>
            </div>
            <div class="info-item">
                <div class="label">渠道/平台</div>
                <div class="value">{request.channel or "未知"}</div>
            </div>
            <div class="info-item">
                <div class="label">设备</div>
                <div class="value">{request.serial}</div>
            </div>
            <div class="info-item">
                <div class="label">时间</div>
                <div class="value">{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
            </div>
            <div class="warning">
                ⚠️ 该用户发送了语音消息，已自动加入黑名单。
            </div>
        </div>
        <div class="footer">
            此邮件由 WeCom 同步系统自动发送
        </div>
    </div>
</body>
</html>
"""

    success, message = send_email(config, subject, content, html_content)

    status_msg = "已添加到黑名单" if added else "已在黑名单中"
    email_msg = "邮件已发送" if success else f"邮件发送失败: {message}"

    return EmailTestResponse(success=True, message=f"{status_msg}，{email_msg}")

# Utility function for other services to send notifications
async def send_notification_email(
    smtp_server: str,
    smtp_port: int,
    sender_email: str,
    sender_password: str,
    sender_name: str,
    receiver_email: str,
    subject: str,
    content: str,
    html_content: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Send a notification email.

    This function can be imported and used by other services.
    """
    config = EmailConfig(
        smtp_server=smtp_server,
        smtp_port=smtp_port,
        sender_email=sender_email,
        sender_password=sender_password,
        sender_name=sender_name,
        receiver_email=receiver_email,
    )

    return send_email(config, subject, content, html_content)
