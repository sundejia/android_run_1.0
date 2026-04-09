#!/usr/bin/env python3
"""
配置日志自动上传设置

将 wecom-desktop 的日志上传功能指向本地运行的 Data-Platform 实例。
需要在 wecom-desktop 后端启动过（数据库已初始化）后运行。

使用方法:
    cd android_run_test
    python scripts/configure_log_upload.py

可选参数:
    --url       Data-Platform 地址 (默认 http://localhost:8085)
    --token     上传鉴权令牌 (需与 Data-Platform .env 中的 ANDROID_LOG_UPLOAD_TOKEN 一致)
    --time      每日上传时间 (默认 02:00)
    --disable   禁用日志上传
"""

import argparse
import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "wecom-desktop" / "backend"))
sys.path.insert(0, str(project_root / "src"))

from wecom_automation.core.config import get_default_db_path
from services.settings.repository import SettingsRepository


def configure_log_upload(
    db_path: str,
    upload_url: str,
    upload_token: str,
    upload_time: str,
    enabled: bool,
) -> None:
    db_file = Path(db_path)
    if not db_file.exists():
        print(f"[ERROR] Database not found: {db_path}")
        print("  Please start wecom-desktop at least once to initialize the database.")
        sys.exit(1)

    repo = SettingsRepository(db_path)

    repo.set("general", "log_upload_enabled", enabled, "script")
    repo.set("general", "log_upload_url", upload_url, "script")
    repo.set("general", "log_upload_token", upload_token, "script")
    repo.set("general", "log_upload_time", upload_time, "script")

    print("Log upload settings configured:")
    print(f"  enabled  = {enabled}")
    print(f"  url      = {upload_url}")
    print(f"  token    = {'*' * 8}...{upload_token[-6:]}" if len(upload_token) > 6 else f"  token    = {upload_token}")
    print(f"  time     = {upload_time}")
    print(f"  db       = {db_path}")
    print()

    if enabled:
        print("Auto-upload is ON. When wecom-desktop starts, it will upload logs")
        print(f"to {upload_url}/api/android-logs/upload daily at {upload_time}.")
        print()
        print("To trigger an upload immediately, POST to:")
        print("  http://localhost:8765/log-upload/trigger")
    else:
        print("Auto-upload is OFF.")


def main():
    parser = argparse.ArgumentParser(description="Configure wecom-desktop log auto-upload")
    parser.add_argument(
        "--url",
        default="http://localhost:8085",
        help="Data-Platform base URL (default: http://localhost:8085)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("ANDROID_LOG_UPLOAD_TOKEN", ""),
        help="Upload auth token (defaults to ANDROID_LOG_UPLOAD_TOKEN env var)",
    )
    parser.add_argument(
        "--time",
        default="02:00",
        help="Daily upload time in HH:MM (default: 02:00)",
    )
    parser.add_argument(
        "--disable",
        action="store_true",
        help="Disable log upload",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Database path (default: auto-detect)",
    )
    args = parser.parse_args()

    if not args.disable and not args.token:
        parser.error(
            "--token is required when enabling log upload "
            "(or set ANDROID_LOG_UPLOAD_TOKEN)"
        )

    db_path = args.db_path or str(get_default_db_path())

    configure_log_upload(
        db_path=db_path,
        upload_url=args.url,
        upload_token=args.token,
        upload_time=args.time,
        enabled=not args.disable,
    )


if __name__ == "__main__":
    main()
