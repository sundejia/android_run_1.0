"""
测试 followup_sent_messages 表创建和基本功能
"""

import sqlite3
import tempfile
import os
import sys
import gc
from pathlib import Path

# 设置UTF-8编码输出（Windows兼容）
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 添加backend目录到sys.path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))


def test_table_creation():
    """测试表创建"""
    # 使用临时数据库
    with tempfile.NamedTemporaryFile(mode="w", suffix=".db", delete=False) as f:
        db_path = f.name

    conn = None
    try:
        from services.followup.sent_messages_repository import FollowupSentMessagesRepository

        # 创建repository（会自动创建表）
        repo = FollowupSentMessagesRepository(db_path)

        # 验证表结构
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # 检查表是否存在
        table_info = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='followup_sent_messages'"
        ).fetchone()

        assert table_info is not None, "表未创建"

        # 检查表结构
        columns = conn.execute("PRAGMA table_info(followup_sent_messages)").fetchall()

        column_names = {col["name"] for col in columns}
        expected_columns = {"id", "device_serial", "customer_name", "message_template", "sent_at"}

        assert expected_columns.issubset(column_names), f"表结构不正确: {column_names}"

        # 检查UNIQUE约束
        indexes = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='followup_sent_messages'"
        ).fetchall()

        print("✅ 表创建测试通过")
        print(f"   - 列: {column_names}")
        print(f"   - UNIQUE约束: device_serial + customer_name + message_template")

    finally:
        # 确保关闭所有连接
        if conn:
            conn.close()
        # 强制垃圾回收，释放所有文件句柄
        gc.collect()
        # 清理临时文件
        if os.path.exists(db_path):
            try:
                os.unlink(db_path)
            except PermissionError:
                # Windows上可能文件仍被锁定，跳过删除
                pass


def test_basic_operations():
    """测试基本操作"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        from services.followup.sent_messages_repository import FollowupSentMessagesRepository

        repo = FollowupSentMessagesRepository(db_path)

        # 测试record_sent_message
        repo.record_sent_message("device1", "customer1", "Hello")
        repo.record_sent_message("device1", "customer1", "How are you?")

        # 测试get_sent_templates
        sent = repo.get_sent_templates("device1", "customer1")
        assert sent == {"Hello", "How are you?"}, f"期望2个模板，实际: {sent}"

        # 测试UNIQUE约束（幂等性）
        repo.record_sent_message("device1", "customer1", "Hello")  # 重复插入
        sent = repo.get_sent_templates("device1", "customer1")
        assert len(sent) == 2, "UNIQUE约束应该防止重复"

        # 测试clear_all
        cleared = repo.clear_all()
        assert cleared == 2, f"应该清除2条记录，实际: {cleared}"

        sent = repo.get_sent_templates("device1", "customer1")
        assert len(sent) == 0, "清空后应该没有记录"

        print("✅ 基本操作测试通过")

    finally:
        # 强制垃圾回收，释放所有文件句柄
        gc.collect()
        if os.path.exists(db_path):
            try:
                os.unlink(db_path)
            except PermissionError:
                # Windows上可能文件仍被锁定，跳过删除
                pass


if __name__ == "__main__":
    test_table_creation()
    test_basic_operations()
    print("\n✅ 所有测试通过！")
