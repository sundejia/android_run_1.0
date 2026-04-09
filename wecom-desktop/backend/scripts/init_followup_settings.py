#!/usr/bin/env python3
"""
初始化 Followup 补刀功能设置

确保所有 followup 相关的设置键值都存在于数据库中。
"""

import sys
from pathlib import Path

# Add paths
from utils.path_utils import get_project_root

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

project_root = get_project_root()
sys.path.insert(0, str(project_root / "src"))

from services.settings import get_settings_service, SettingCategory


def init_followup_settings():
    """初始化 followup 设置"""
    service = get_settings_service()

    # Followup 设置定义
    followup_settings = [
        ("followup_enabled", False, "启用补刀功能"),
        ("max_followups", 5, "每次扫描最大补刀数量"),
        ("use_ai_reply", False, "补刀使用 AI 回复"),
        ("enable_operating_hours", False, "启用工作时间限制"),
        ("start_hour", "09:00", "开始时间"),
        ("end_hour", "18:00", "结束时间"),
        (
            "message_templates",
            ["Hello, have you considered our offer?", "Feel free to contact me if you have any questions"],
            "消息模板",
        ),
        ("followup_prompt", "", "补刀 AI 提示词"),
        ("idle_threshold_minutes", 30, "空闲阈值（分钟）"),
        ("max_attempts_per_customer", 3, "每客户最大补刀次数"),
    ]

    print("=" * 60)
    print("初始化 Followup 设置")
    print("=" * 60)

    added = 0
    skipped = 0

    for key, default_value, description in followup_settings:
        existing = service.get(SettingCategory.FOLLOWUP.value, key)

        if existing is None:
            service.set(SettingCategory.FOLLOWUP.value, key, default_value, "init_followup")
            print(f"  ✓ 添加: {key} = {default_value}")
            added += 1
        else:
            print(f"  - 已存在: {key} = {existing}")
            skipped += 1

    print("=" * 60)
    print(f"完成: 新增 {added} 项, 跳过 {skipped} 项")
    print("=" * 60)

    # 验证
    print("\n验证 Followup 设置:")
    for key, _, _ in followup_settings:
        value = service.get(SettingCategory.FOLLOWUP.value, key)
        print(f"  {key}: {value}")


if __name__ == "__main__":
    init_followup_settings()
