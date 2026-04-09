#!/usr/bin/env python3
"""
迁移脚本：将 followup 分类下的实时回复配置迁移到 realtime 分类

旧配置 (followup):
- default_scan_interval
- use_ai_reply
- send_via_sidecar

新配置 (realtime):
- scan_interval
- use_ai_reply
- send_via_sidecar
"""

import sys
from pathlib import Path

# Add project root to path
from utils.path_utils import get_project_root

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

PROJECT_ROOT = get_project_root()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "wecom-desktop" / "backend"))

from services.settings import get_settings_service, SettingCategory


def migrate_realtime_settings():
    """迁移实时回复配置从 followup 到 realtime 分类"""
    service = get_settings_service()

    print("开始迁移实时回复配置...")

    # 从 followup 分类读取旧配置
    try:
        old_scan_interval = service.get(SettingCategory.FOLLOWUP.value, "default_scan_interval")
        old_use_ai_reply = service.get(SettingCategory.FOLLOWUP.value, "use_ai_reply")
        old_send_via_sidecar = service.get(SettingCategory.FOLLOWUP.value, "send_via_sidecar")

        print(f"  读取旧配置:")
        print(f"    - default_scan_interval: {old_scan_interval}")
        print(f"    - use_ai_reply: {old_use_ai_reply}")
        print(f"    - send_via_sidecar: {old_send_via_sidecar}")

        # 写入到 realtime 分类
        if old_scan_interval is not None:
            service.set(SettingCategory.REALTIME.value, "scan_interval", old_scan_interval, "migration")
            print(f"  ✓ 迁移 scan_interval: {old_scan_interval}")

        if old_use_ai_reply is not None:
            service.set(SettingCategory.REALTIME.value, "use_ai_reply", old_use_ai_reply, "migration")
            print(f"  ✓ 迁移 use_ai_reply: {old_use_ai_reply}")

        if old_send_via_sidecar is not None:
            service.set(SettingCategory.REALTIME.value, "send_via_sidecar", old_send_via_sidecar, "migration")
            print(f"  ✓ 迁移 send_via_sidecar: {old_send_via_sidecar}")

        print("\n✅ 迁移完成！")
        print("\n注意：旧的 followup 配置仍然保留，可以手动删除或留作备份。")

    except Exception as e:
        print(f"❌ 迁移失败: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    migrate_realtime_settings()
