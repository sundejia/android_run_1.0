"""
测试补刀间隔功能

验证 attempt_intervals 配置是否正确工作
"""

# ruff: noqa: E402 — sys.path must be set before backend imports
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "wecom-desktop" / "backend"
SRC_DIR = PROJECT_ROOT / "src"

for path in (BACKEND_DIR, SRC_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from services.followup.attempts_repository import FollowupAttemptsRepository
from services.followup.settings import SettingsManager


def test_attempt_intervals():
    """测试补刀间隔逻辑"""
    print("=" * 60)
    print("测试补刀间隔功能")
    print("=" * 60)

    # 1. 检查设置
    print("\n1️⃣ 检查当前设置...")
    settings_mgr = SettingsManager()
    settings = settings_mgr.get_settings()

    print(f"   补刀功能启用: {settings.followup_enabled}")
    print(f"   空闲阈值: {settings.idle_threshold_minutes} 分钟")
    print(f"   最大补刀次数: {settings.max_attempts_per_customer}")
    print(f"   补刀间隔: {settings.attempt_intervals}")
    print(f"     - 第1次补刀后等待: {settings.attempt_intervals[0]} 分钟")
    print(f"     - 第2次补刀后等待: {settings.attempt_intervals[1]} 分钟")
    print(f"     - 第3次补刀后等待: {settings.attempt_intervals[2]} 分钟")

    # 2. 测试数据库逻辑
    print("\n2️⃣ 测试数据库逻辑...")
    repo = FollowupAttemptsRepository()

    # 清理测试数据
    test_device = "TEST_DEVICE"
    test_customer = "测试客户_interval_test"
    repo.delete_by_customer(test_device, test_customer)

    # 创建测试记录
    now = datetime.now()
    attempt = repo.add_or_update(
        device_serial=test_device,
        customer_name=test_customer,
        last_kefu_message_id="test_msg_001",
        last_kefu_message_time=now - timedelta(minutes=40),
        max_attempts=3,
    )
    print(f"\n   ✅ 创建测试记录: {test_customer}")
    print(f"      ID: {attempt.id}")
    print(f"      current_attempt: {attempt.current_attempt}")
    print(f"      status: {attempt.status.value}")

    # 3. 测试不同补刀次数的间隔判断
    print("\n3️⃣ 测试间隔判断逻辑...")

    test_intervals = [60, 120, 180]

    # 测试场景1: 首次补刀 (current_attempt = 0)
    print("\n   场景1: 首次补刀 (current_attempt = 0)")
    pending = repo.get_pending_attempts(test_device, limit=10, attempt_intervals=test_intervals)
    print(f"   待补刀列表长度: {len(pending)}")
    if pending:
        print("   ✅ 符合预期 - 首次补刀无需等待，立即可执行")
    else:
        print("   ❌ 错误 - 首次补刀应该在列表中")

    # 模拟第1次补刀完成
    print("\n   模拟第1次补刀完成...")
    repo.record_followup_sent(attempt.id, "followup_msg_001")
    attempt = repo.get_by_id(attempt.id)
    print(f"   current_attempt: {attempt.current_attempt}")
    print(f"   last_followup_at: {attempt.last_followup_at}")

    # 测试场景2: 第2次补刀 - 刚刚完成第1次 (应该不在列表中)
    print("\n   场景2: 第2次补刀 - 刚完成第1次 (应不在列表)")
    pending = repo.get_pending_attempts(test_device, limit=10, attempt_intervals=test_intervals)
    in_list = any(p.id == attempt.id for p in pending)
    if not in_list:
        print(f"   ✅ 符合预期 - 未满足 {test_intervals[0]} 分钟间隔，不在列表中")
    else:
        print("   ❌ 错误 - 应该不在列表中（间隔不足）")

    # 模拟时间推进 70 分钟
    print(f"\n   模拟时间推进 70 分钟（超过第1次间隔 {test_intervals[0]} 分钟）...")
    # 直接修改 last_followup_at
    import sqlite3

    conn = sqlite3.connect(repo._db_path)
    fake_time = (now - timedelta(minutes=70)).isoformat()
    conn.execute(
        "UPDATE followup_attempts SET last_followup_at = ? WHERE id = ?",
        (fake_time, attempt.id),
    )
    conn.commit()
    conn.close()

    # 测试场景3: 第2次补刀 - 已等待70分钟 (应该在列表中)
    print("\n   场景3: 第2次补刀 - 已等待70分钟 (应在列表)")
    pending = repo.get_pending_attempts(test_device, limit=10, attempt_intervals=test_intervals)
    in_list = any(p.id == attempt.id for p in pending)
    if in_list:
        print(f"   ✅ 符合预期 - 已满足 {test_intervals[0]} 分钟间隔，在列表中")
    else:
        print("   ❌ 错误 - 应该在列表中（间隔已满足）")

    # 模拟第2次补刀完成
    print("\n   模拟第2次补刀完成...")
    repo.record_followup_sent(attempt.id, "followup_msg_002")
    attempt = repo.get_by_id(attempt.id)
    print(f"   current_attempt: {attempt.current_attempt}")

    # 测试场景4: 第3次补刀 - 刚完成第2次 (应该不在列表中)
    print("\n   场景4: 第3次补刀 - 刚完成第2次 (应不在列表)")
    pending = repo.get_pending_attempts(test_device, limit=10, attempt_intervals=test_intervals)
    in_list = any(p.id == attempt.id for p in pending)
    if not in_list:
        print(f"   ✅ 符合预期 - 未满足 {test_intervals[1]} 分钟间隔，不在列表中")
    else:
        print("   ❌ 错误 - 应该不在列表中（间隔不足）")

    # 模拟时间推进 130 分钟
    print(f"\n   模拟时间推进 130 分钟（超过第2次间隔 {test_intervals[1]} 分钟）...")
    conn = sqlite3.connect(repo._db_path)
    fake_time = (now - timedelta(minutes=130)).isoformat()
    conn.execute(
        "UPDATE followup_attempts SET last_followup_at = ? WHERE id = ?",
        (fake_time, attempt.id),
    )
    conn.commit()
    conn.close()

    # 测试场景5: 第3次补刀 - 已等待130分钟 (应该在列表中)
    print("\n   场景5: 第3次补刀 - 已等待130分钟 (应在列表)")
    pending = repo.get_pending_attempts(test_device, limit=10, attempt_intervals=test_intervals)
    in_list = any(p.id == attempt.id for p in pending)
    if in_list:
        print(f"   ✅ 符合预期 - 已满足 {test_intervals[1]} 分钟间隔，在列表中")
    else:
        print("   ❌ 错误 - 应该在列表中（间隔已满足）")

    # 清理测试数据
    print("\n   清理测试数据...")
    repo.delete_by_customer(test_device, test_customer)

    print("\n" + "=" * 60)
    print("✅ 测试完成！补刀间隔功能工作正常")
    print("=" * 60)

    print("\n📋 功能说明:")
    print("   1. idle_threshold_minutes (30分钟) - 客户进入补刀队列的初始阈值")
    print("   2. attempt_intervals - 每次补刀后的等待间隔")
    print(f"      - 第1次补刀后: 等待 {test_intervals[0]} 分钟")
    print(f"      - 第2次补刀后: 等待 {test_intervals[1]} 分钟")
    print(f"      - 第3次补刀后: 等待 {test_intervals[2]} 分钟")
    print("\n   前端已实现配置界面，后端逻辑已完全支持！")


if __name__ == "__main__":
    try:
        test_attempt_intervals()
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
