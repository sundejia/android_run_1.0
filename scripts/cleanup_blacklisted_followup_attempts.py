#!/usr/bin/env python3
"""
清理黑名单用户的补刀队列记录

用途：
1. 清理历史遗留的黑名单用户补刀记录
2. 在部署黑名单过滤修复后运行一次

运行方式：
    python scripts/cleanup_blacklisted_followup_attempts.py
    python scripts/cleanup_blacklisted_followup_attempts.py --dry-run  # 仅查看，不修改
"""

import argparse
import sqlite3
import sys
from pathlib import Path

# 添加项目根目录到 sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from wecom_automation.core.config import get_default_db_path
from wecom_desktop.backend.services.followup.attempts_repository import (
    FollowupAttemptsRepository,
)
# Note: This script uses raw SQL queries and doesn't need the blacklist service


def find_blacklisted_pending_attempts(db_path: str) -> list[dict]:
    """
    查找黑名单用户的待补刀记录
    
    Returns:
        包含 attempt_id, device_serial, customer_name 的字典列表
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            fa.id as attempt_id,
            fa.device_serial,
            fa.customer_name,
            fa.customer_id,
            fa.current_attempt,
            fa.max_attempts,
            fa.created_at,
            fa.last_followup_at,
            b.reason as blacklist_reason,
            b.is_blacklisted
        FROM followup_attempts fa
        INNER JOIN blacklist b 
          ON fa.device_serial = b.device_serial 
          AND fa.customer_name = b.customer_name
        WHERE fa.status = 'pending'
          AND b.is_blacklisted = 1
        ORDER BY fa.device_serial, fa.customer_name
    """)
    
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return results


def cleanup_blacklisted_attempts(db_path: str, dry_run: bool = False) -> int:
    """
    清理黑名单用户的补刀记录
    
    Args:
        db_path: 数据库路径
        dry_run: 如果为 True，只打印不实际修改
        
    Returns:
        被清理的记录数量
    """
    # 查找黑名单用户的待补刀记录
    blacklisted_attempts = find_blacklisted_pending_attempts(db_path)
    
    if not blacklisted_attempts:
        print("✅ 没有找到需要清理的记录（所有黑名单用户都已被正确过滤）")
        return 0
    
    print(f"\n🔍 找到 {len(blacklisted_attempts)} 条黑名单用户的待补刀记录:\n")
    print("┌─────────────────────────────────────────────────────────────────────────────┐")
    print("│ Device Serial        │ Customer Name        │ Attempts │ Blacklist Reason │")
    print("├─────────────────────────────────────────────────────────────────────────────┤")
    
    for attempt in blacklisted_attempts:
        device = attempt["device_serial"][:18] + "..." if len(attempt["device_serial"]) > 18 else attempt["device_serial"]
        name = attempt["customer_name"][:18] + "..." if len(attempt["customer_name"]) > 18 else attempt["customer_name"]
        attempts = f"{attempt['current_attempt']}/{attempt['max_attempts']}"
        reason = (attempt["blacklist_reason"] or "N/A")[:14] + "..." if attempt["blacklist_reason"] and len(attempt["blacklist_reason"]) > 14 else (attempt["blacklist_reason"] or "N/A")
        
        print(f"│ {device:<20} │ {name:<20} │ {attempts:<8} │ {reason:<16} │")
    
    print("└─────────────────────────────────────────────────────────────────────────────┘")
    
    if dry_run:
        print("\n⚠️  DRY RUN 模式 - 不会实际修改数据库")
        print(f"   如果执行清理，将取消 {len(blacklisted_attempts)} 条待补刀记录")
        return 0
    
    # 确认操作
    print(f"\n❓ 是否继续清理这 {len(blacklisted_attempts)} 条记录？")
    print("   这将把这些记录的状态设置为 'cancelled'")
    response = input("   输入 'yes' 确认继续: ").strip().lower()
    
    if response != "yes":
        print("❌ 操作已取消")
        return 0
    
    # 执行清理
    print("\n🚀 开始清理...")
    repo = FollowupAttemptsRepository(db_path)
    cancelled_count = 0
    
    # 按用户分组清理
    users_to_cancel = {}
    for attempt in blacklisted_attempts:
        key = (attempt["device_serial"], attempt["customer_name"])
        if key not in users_to_cancel:
            users_to_cancel[key] = []
        users_to_cancel[key].append(attempt)
    
    for (device_serial, customer_name), attempts in users_to_cancel.items():
        try:
            count = repo.cancel_attempts_by_customer(
                device_serial=device_serial,
                customer_name=customer_name,
                reason="Cleanup: User is blacklisted",
            )
            cancelled_count += count
            print(f"   ✅ {customer_name} on {device_serial}: 取消 {count} 条记录")
        except Exception as e:
            print(f"   ❌ {customer_name} on {device_serial}: 失败 - {e}")
    
    print(f"\n🎉 清理完成！共取消 {cancelled_count} 条待补刀记录")
    return cancelled_count


def main():
    parser = argparse.ArgumentParser(
        description="清理黑名单用户的补刀队列记录",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 查看需要清理的记录（不修改）
  python scripts/cleanup_blacklisted_followup_attempts.py --dry-run
  
  # 执行清理
  python scripts/cleanup_blacklisted_followup_attempts.py
  
  # 使用自定义数据库路径
  python scripts/cleanup_blacklisted_followup_attempts.py --db-path /path/to/db.sqlite
        """
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅查看需要清理的记录，不实际修改数据库"
    )
    
    parser.add_argument(
        "--db-path",
        type=str,
        help="数据库路径（默认使用配置的路径）"
    )
    
    args = parser.parse_args()
    
    # 获取数据库路径
    db_path = args.db_path or str(get_default_db_path())
    
    print("╔═══════════════════════════════════════════════════════════════╗")
    print("║       清理黑名单用户的补刀队列记录                              ║")
    print("╚═══════════════════════════════════════════════════════════════╝")
    print(f"\n📁 数据库路径: {db_path}")
    
    if args.dry_run:
        print("⚠️  模式: DRY RUN（仅查看，不修改）\n")
    else:
        print("⚠️  模式: 实际执行（将修改数据库）\n")
    
    try:
        cancelled_count = cleanup_blacklisted_attempts(db_path, dry_run=args.dry_run)
        
        if cancelled_count > 0 and not args.dry_run:
            print("\n✨ 建议：")
            print("   1. 检查日志确认清理正确")
            print("   2. 在下次补刀执行前，验证黑名单用户不再被补刀")
            print("   3. 监控补刀日志中的 '黑名单用户，跳过补刀' 消息")
        
        return 0
    
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
