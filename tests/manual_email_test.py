#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
QQ 邮件发送测试脚本

使用前请确保：
1. 开启 QQ 邮箱的 SMTP 服务：QQ邮箱 -> 设置 -> 账户 -> POP3/SMTP服务 -> 开启
2. 生成授权码（不是QQ密码）：开启SMTP服务时会提示生成授权码
3. 将下面的配置修改为你的邮箱和授权码
"""

import smtplib
from datetime import datetime
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

# ==================== 配置区域 ====================
# 请修改为你的 QQ 邮箱配置
SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465  # QQ 邮箱 SSL 端口

SENDER_EMAIL = "1754245013@qq.com"  # 发件人邮箱（你的QQ邮箱）
SENDER_PASSWORD = "thybxaxmhiqbbaag"  # QQ邮箱授权码（不是QQ密码！）
SENDER_NAME = "WeCom 同步系统"  # 发件人显示名称

RECEIVER_EMAIL = "zihanzixin@gmail.com"  # 收件人邮箱
RECEIVER_NAME = "管理员"  # 收件人显示名称
# ==================================================


def send_simple_email(
    subject: str,
    content: str,
    to_email: str = None,
    to_name: str = None,
) -> tuple[bool, str]:
    """
    发送简单文本邮件

    Args:
        subject: 邮件主题
        content: 邮件内容（纯文本）
        to_email: 收件人邮箱（可选，默认使用配置）
        to_name: 收件人名称（可选，默认使用配置）

    Returns:
        (success, message) 元组
    """
    to_email = to_email or RECEIVER_EMAIL
    to_name = to_name or RECEIVER_NAME

    try:
        # 创建邮件对象
        msg = MIMEText(content, "plain", "utf-8")
        msg["From"] = formataddr([SENDER_NAME, SENDER_EMAIL])
        msg["To"] = formataddr([to_name, to_email])
        msg["Subject"] = Header(subject, "utf-8")

        # 连接 SMTP 服务器并发送
        print(f"正在连接 SMTP 服务器 {SMTP_SERVER}:{SMTP_PORT}...")
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)

        print(f"正在登录 {SENDER_EMAIL}...")
        server.login(SENDER_EMAIL, SENDER_PASSWORD)

        print(f"正在发送邮件到 {to_email}...")
        server.sendmail(SENDER_EMAIL, [to_email], msg.as_string())

        server.quit()
        print("✅ 邮件发送成功！")
        return True, "邮件发送成功"

    except smtplib.SMTPAuthenticationError as e:
        error_msg = f"认证失败，请检查邮箱和授权码是否正确: {e}"
        print(f"❌ {error_msg}")
        return False, error_msg
    except smtplib.SMTPException as e:
        error_msg = f"SMTP 错误: {e}"
        print(f"❌ {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"发送失败: {e}"
        print(f"❌ {error_msg}")
        return False, error_msg


def send_html_email(
    subject: str,
    html_content: str,
    to_email: str = None,
    to_name: str = None,
) -> tuple[bool, str]:
    """
    发送 HTML 格式邮件

    Args:
        subject: 邮件主题
        html_content: 邮件内容（HTML格式）
        to_email: 收件人邮箱（可选）
        to_name: 收件人名称（可选）

    Returns:
        (success, message) 元组
    """
    to_email = to_email or RECEIVER_EMAIL
    to_name = to_name or RECEIVER_NAME

    try:
        # 创建邮件对象
        msg = MIMEMultipart("alternative")
        msg["From"] = formataddr([SENDER_NAME, SENDER_EMAIL])
        msg["To"] = formataddr([to_name, to_email])
        msg["Subject"] = Header(subject, "utf-8")

        # 添加 HTML 内容
        html_part = MIMEText(html_content, "html", "utf-8")
        msg.attach(html_part)

        # 连接 SMTP 服务器并发送
        print(f"正在连接 SMTP 服务器 {SMTP_SERVER}:{SMTP_PORT}...")
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)

        print(f"正在登录 {SENDER_EMAIL}...")
        server.login(SENDER_EMAIL, SENDER_PASSWORD)

        print(f"正在发送 HTML 邮件到 {to_email}...")
        server.sendmail(SENDER_EMAIL, [to_email], msg.as_string())

        server.quit()
        print("✅ HTML 邮件发送成功！")
        return True, "邮件发送成功"

    except Exception as e:
        error_msg = f"发送失败: {e}"
        print(f"❌ {error_msg}")
        return False, error_msg


def send_followup_reminder(
    customer_name: str,
    channel: str,
    attempt_number: int,
    to_email: str = None,
) -> tuple[bool, str]:
    """
    发送补刀提醒邮件

    Args:
        customer_name: 客户名称
        channel: 渠道
        attempt_number: 补刀次数
        to_email: 收件人邮箱（可选）

    Returns:
        (success, message) 元组
    """
    subject = f"🔔 补刀提醒: {customer_name} (第{attempt_number}次)"

    html_content = f"""
    <html>
    <head>
        <style>
            body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                       color: white; padding: 20px; border-radius: 10px 10px 0 0; }}
            .content {{ background: #f8f9fa; padding: 20px; border-radius: 0 0 10px 10px; }}
            .info-row {{ margin: 10px 0; padding: 10px; background: white; border-radius: 5px; }}
            .label {{ color: #666; font-size: 12px; }}
            .value {{ font-size: 16px; font-weight: bold; color: #333; }}
            .footer {{ text-align: center; margin-top: 20px; color: #999; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2 style="margin: 0;">📨 WeCom 补刀提醒</h2>
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
                    <div class="label">补刀次数</div>
                    <div class="value">第 {attempt_number} 次</div>
                </div>
                <div class="info-row">
                    <div class="label">提醒时间</div>
                    <div class="value">{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
                </div>
            </div>
            <div class="footer">
                此邮件由 WeCom 同步系统自动发送
            </div>
        </div>
    </body>
    </html>
    """

    return send_html_email(subject, html_content, to_email)


def send_sync_complete_notification(
    device_serial: str,
    customers_synced: int,
    messages_added: int,
    errors: list = None,
    to_email: str = None,
) -> tuple[bool, str]:
    """
    发送同步完成通知邮件

    Args:
        device_serial: 设备序列号
        customers_synced: 同步的客户数
        messages_added: 添加的消息数
        errors: 错误列表（可选）
        to_email: 收件人邮箱（可选）

    Returns:
        (success, message) 元组
    """
    errors = errors or []
    status = "⚠️ 完成（有错误）" if errors else "✅ 成功完成"

    subject = f"📊 同步完成通知: {device_serial} - {status}"

    error_html = ""
    if errors:
        error_items = "".join([f"<li>{e}</li>" for e in errors[:5]])
        if len(errors) > 5:
            error_items += f"<li>... 还有 {len(errors) - 5} 个错误</li>"
        error_html = f"""
        <div class="info-row" style="background: #fff3cd;">
            <div class="label">错误信息</div>
            <ul style="margin: 5px 0; padding-left: 20px;">{error_items}</ul>
        </div>
        """

    html_content = f"""
    <html>
    <head>
        <style>
            body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
                       color: white; padding: 20px; border-radius: 10px 10px 0 0; }}
            .content {{ background: #f8f9fa; padding: 20px; border-radius: 0 0 10px 10px; }}
            .info-row {{ margin: 10px 0; padding: 10px; background: white; border-radius: 5px; }}
            .label {{ color: #666; font-size: 12px; }}
            .value {{ font-size: 16px; font-weight: bold; color: #333; }}
            .stats {{ display: flex; gap: 20px; }}
            .stat-box {{ flex: 1; text-align: center; background: white; padding: 15px; border-radius: 5px; }}
            .stat-number {{ font-size: 24px; font-weight: bold; color: #11998e; }}
            .stat-label {{ font-size: 12px; color: #666; }}
            .footer {{ text-align: center; margin-top: 20px; color: #999; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2 style="margin: 0;">📊 同步完成通知</h2>
            </div>
            <div class="content">
                <div class="info-row">
                    <div class="label">设备序列号</div>
                    <div class="value">{device_serial}</div>
                </div>
                <div class="info-row">
                    <div class="label">完成时间</div>
                    <div class="value">{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
                </div>
                <div class="stats" style="margin: 15px 0;">
                    <div class="stat-box">
                        <div class="stat-number">{customers_synced}</div>
                        <div class="stat-label">客户同步</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-number">{messages_added}</div>
                        <div class="stat-label">消息添加</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-number">{len(errors)}</div>
                        <div class="stat-label">错误数</div>
                    </div>
                </div>
                {error_html}
            </div>
            <div class="footer">
                此邮件由 WeCom 同步系统自动发送
            </div>
        </div>
    </body>
    </html>
    """

    return send_html_email(subject, html_content, to_email)


# ==================== 测试代码 ====================
if __name__ == "__main__":
    print("=" * 60)
    print("QQ 邮件发送测试")
    print("=" * 60)

    # 检查配置
    if SENDER_EMAIL == "your_qq@qq.com" or SENDER_PASSWORD == "your_auth_code":
        print("\n⚠️ 请先修改脚本顶部的配置：")
        print("   1. SENDER_EMAIL: 你的 QQ 邮箱")
        print("   2. SENDER_PASSWORD: QQ 邮箱授权码（不是QQ密码）")
        print("   3. RECEIVER_EMAIL: 收件人邮箱")
        print("\n获取授权码方法：")
        print("   QQ邮箱 -> 设置 -> 账户 -> POP3/SMTP服务 -> 开启 -> 生成授权码")
        exit(1)

    print(f"\n发件人: {SENDER_EMAIL}")
    print(f"收件人: {RECEIVER_EMAIL}")

    # 选择测试类型
    print("\n请选择测试类型：")
    print("1. 发送简单文本邮件")
    print("2. 发送 HTML 格式邮件")
    print("3. 发送补刀提醒邮件")
    print("4. 发送同步完成通知")

    choice = input("\n请输入选项 (1-4): ").strip()

    if choice == "1":
        print("\n--- 发送简单文本邮件 ---")
        success, msg = send_simple_email(
            subject="WeCom 系统测试邮件",
            content=f"这是一封测试邮件，发送时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n如果您收到此邮件，说明邮件功能配置正确！",
        )

    elif choice == "2":
        print("\n--- 发送 HTML 格式邮件 ---")
        html = """
        <h1 style="color: #667eea;">WeCom 系统测试</h1>
        <p>这是一封 <strong>HTML 格式</strong> 的测试邮件。</p>
        <p>如果您能看到格式化的内容，说明 HTML 邮件功能正常！</p>
        """
        success, msg = send_html_email(subject="WeCom HTML 测试邮件", html_content=html)

    elif choice == "3":
        print("\n--- 发送补刀提醒邮件 ---")
        success, msg = send_followup_reminder(customer_name="测试客户", channel="抖音", attempt_number=2)

    elif choice == "4":
        print("\n--- 发送同步完成通知 ---")
        success, msg = send_sync_complete_notification(
            device_serial="TEST123456", customers_synced=25, messages_added=156, errors=["测试错误1", "测试错误2"]
        )

    else:
        print("无效的选项")
        exit(1)

    print(f"\n结果: {msg}")
