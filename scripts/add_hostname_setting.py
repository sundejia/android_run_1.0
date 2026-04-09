#!/usr/bin/env python3
"""
数据库迁移脚本：添加 hostname 设置

将 hostname 设置项添加到 system_settings 表中。
如果已存在则跳过。

使用方法:
    python scripts/add_hostname_setting.py
"""

import sqlite3
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
from wecom_automation.core.config import get_project_root, get_default_db_path

project_root = get_project_root()
sys.path.insert(0, str(project_root))


def add_hostname_setting(db_path: str) -> None:
    """
    添加 hostname 设置到数据库
    
    Args:
        db_path: 数据库文件路径
    """
    print(f"📁 数据库路径: {db_path}")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # 检查表是否存在
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='system_settings'
        """)
        
        if not cursor.fetchone():
            print("❌ 错误: system_settings 表不存在")
            print("   请先运行主程序初始化数据库")
            return
        
        # 检查 hostname 设置是否已存在
        cursor.execute("""
            SELECT * FROM system_settings 
            WHERE category = 'general' AND key = 'hostname'
        """)
        
        existing = cursor.fetchone()
        
        if existing:
            print(f"✅ hostname 设置已存在: {existing['value_string']}")
            print("   无需迁移")
        else:
            # 插入新设置
            cursor.execute("""
                INSERT INTO system_settings 
                (category, key, value_type, value_string, value_int, value_float, value_bool, value_json, 
                 description, is_sensitive, created_at, updated_at)
                VALUES (?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, ?, datetime('now'), datetime('now'))
            """, (
                'general',
                'hostname',
                'string',
                'default',
                '主机名称（用于日志文件前缀）',
                0  # is_sensitive = False
            ))
            
            conn.commit()
            print("✅ 成功添加 hostname 设置")
            print(f"   category: general")
            print(f"   key: hostname")
            print(f"   value: default")
        
        # 显示当前所有 general 类别的设置
        cursor.execute("""
            SELECT key, value_type, value_string, value_int, value_float, value_bool 
            FROM system_settings 
            WHERE category = 'general'
            ORDER BY key
        """)
        
        print("\n📋 当前 general 类别的所有设置:")
        for row in cursor.fetchall():
            key = row['key']
            value_type = row['value_type']
            
            if value_type == 'string':
                value = row['value_string']
            elif value_type == 'int':
                value = row['value_int']
            elif value_type == 'float':
                value = row['value_float']
            elif value_type == 'boolean':
                value = bool(row['value_bool'])
            else:
                value = '(unknown)'
            
            print(f"   - {key}: {value} ({value_type})")
    
    except Exception as e:
        print(f"❌ 迁移失败: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
    finally:
        conn.close()


def main():
    """主函数"""
    print("=" * 60)
    print("数据库迁移：添加 hostname 设置")
    print("=" * 60)
    print()
    
    db_path = str(get_default_db_path())
    
    if not Path(db_path).exists():
        print(f"❌ 错误: 数据库文件不存在: {db_path}")
        print("   请先运行主程序初始化数据库")
        sys.exit(1)
    
    add_hostname_setting(db_path)
    
    print()
    print("=" * 60)
    print("迁移完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
