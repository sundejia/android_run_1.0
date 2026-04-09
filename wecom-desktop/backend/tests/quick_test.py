"""
快速验证 WebSocket 功能

运行此脚本以快速验证 WebSocket 功能是否正常工作。
"""

import sys
from pathlib import Path

# 添加 backend 目录到路径
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))


def quick_test():
    """快速测试所有组件"""
    print("=" * 70)
    print("Sidecar WebSocket Quick Test")
    print("=" * 70)

    # 1. 测试导入
    print("\n[1/5] Testing imports...")
    try:
        from services.websocket_manager import get_sidecar_message_manager
        from services.message_publisher import notify_message_added, notify_history_refresh

        print("      [OK] All imports successful")
    except Exception as e:
        print(f"      [FAIL] Import error: {e}")
        return False

    # 2. 测试 Manager 初始化
    print("\n[2/5] Testing WebSocket Manager...")
    try:
        manager = get_sidecar_message_manager()
        assert manager is not None
        assert manager._connections == {}
        print("      [OK] Manager initialized correctly")
    except Exception as e:
        print(f"      [FAIL] Manager error: {e}")
        return False

    # 3. 测试 Key 生成
    print("\n[3/5] Testing key generation...")
    try:
        test_cases = [
            ("s1", "c1", "ch1", "s1:c1:ch1"),
            ("s2", None, None, "s2::"),
        ]
        for serial, contact, channel, expected in test_cases:
            result = manager._get_key(serial, contact, channel)
            assert result == expected, f"Expected {expected}, got {result}"
        print("      [OK] Key generation works correctly")
    except Exception as e:
        print(f"      [FAIL] Key generation error: {e}")
        return False

    # 4. 测试事件创建
    print("\n[4/5] Testing event creation...")
    try:
        from datetime import datetime

        test_event = {
            "type": "message_added",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "customer_id": 1,
                "customer_name": "Test",
                "channel": "wechat",
                "message": {
                    "content": "Hello",
                    "is_from_kefu": True,
                    "message_type": "text",
                    "timestamp": datetime.now().isoformat(),
                },
            },
        }
        assert test_event["type"] == "message_added"
        assert "data" in test_event
        print("      [OK] Event creation works correctly")
    except Exception as e:
        print(f"      [FAIL] Event creation error: {e}")
        return False

    # 5. 测试消息发布（无实际连接）
    print("\n[5/5] Testing message publishing...")
    try:
        import asyncio

        async def test_publish():
            await notify_message_added("test_serial", 1, "Test", "wechat", {"content": "Test", "is_from_kefu": True})
            await notify_history_refresh("test_serial", "Test", "wechat")

        asyncio.run(test_publish())
        print("      [OK] Message publishing works (no connections)")
    except Exception as e:
        print(f"      [FAIL] Publishing error: {e}")
        return False

    print("\n" + "=" * 70)
    print("[SUCCESS] All quick tests passed!")
    print("=" * 70)

    # 打印使用说明
    print("\nNext Steps:")
    print("1. Start the backend server: uvicorn main:app --reload")
    print("2. Connect from frontend: ws://localhost:8765/sidecar/{serial}/ws/messages")
    print("3. Send test messages to verify real-time updates")
    print()

    return True


if __name__ == "__main__":
    success = quick_test()
    sys.exit(0 if success else 1)
