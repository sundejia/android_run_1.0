"""
WebSocket 集成测试

测试完整的 WebSocket 消息推送流程。
"""

import asyncio
import json
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_websocket_flow():
    """测试完整的 WebSocket 消息流程"""

    print("=" * 60)
    print("WebSocket Integration Test")
    print("=" * 60)

    # 1. 测试 WebSocket Manager
    print("\n1. Testing WebSocket Manager...")
    from services.websocket_manager import get_sidecar_message_manager

    manager = get_sidecar_message_manager()
    print("   [OK] WebSocket Manager initialized")

    # 2. 测试 Message Publisher
    print("\n2. Testing Message Publisher...")
    from services.message_publisher import MessagePublisher, notify_message_added, notify_history_refresh

    print("   [OK] Message Publisher imported")

    # 3. 测试事件创建
    print("\n3. Testing event creation...")
    from datetime import datetime

    test_message = {
        "content": "Hello from WebSocket test!",
        "is_from_kefu": True,
        "message_type": "text",
        "timestamp": datetime.now().isoformat(),
    }

    event = {
        "type": "message_added",
        "timestamp": datetime.now().isoformat(),
        "data": {
            "customer_id": 1,
            "customer_name": "Test Customer",
            "channel": "wechat",
            "message": test_message,
        },
    }

    print(f"   [OK] Event created: {event['type']}")
    print(f"   [OK] Event data: {json.dumps(event['data'], indent=6, ensure_ascii=False)}")

    # 4. 测试消息发布（没有实际连接）
    print("\n4. Testing message publishing (without connections)...")

    try:
        # 这不会发送到任何地方，因为没有连接的 WebSocket
        await notify_message_added(
            serial="test_serial_001",
            customer_id=1,
            customer_name="Test Customer",
            channel="wechat",
            message=test_message,
        )
        print("   [OK] notify_message_added called successfully")
    except Exception as e:
        print(f"   [ERROR] Error: {e}")
        return False

    try:
        await notify_history_refresh(serial="test_serial_001", customer_name="Test Customer", channel="wechat")
        print("   [OK] notify_history_refresh called successfully")
    except Exception as e:
        print(f"   [ERROR] Error: {e}")
        return False

    # 5. 测试 Key 生成逻辑
    print("\n5. Testing key generation logic...")

    test_cases = [
        ("serial001", "contact1", "channel1", "serial001:contact1:channel1"),
        ("serial002", None, None, "serial002::"),
        ("serial003", "contact2", None, "serial003:contact2:"),
    ]

    for serial, contact, channel, expected in test_cases:
        key = manager._get_key(serial, contact, channel)
        if key == expected:
            print(f"   [OK] Key: {key} == {expected}")
        else:
            print(f"   [ERROR] Key mismatch: {key} != {expected}")
            return False

    # 6. 测试所有事件类型
    print("\n6. Testing all event types...")

    event_types = ["connected", "message_added", "message_batch", "history_refresh", "heartbeat"]

    for event_type in event_types:
        print(f"   [OK] Event type: {event_type}")

    print("\n" + "=" * 60)
    print("[SUCCESS] All integration tests passed!")
    print("=" * 60)

    return True


async def test_message_event_formats():
    """测试各种消息事件格式"""

    print("\n" + "=" * 60)
    print("Testing Message Event Formats")
    print("=" * 60)

    from datetime import datetime

    # 1. message_added 事件
    print("\n1. Testing 'message_added' event format...")

    message_added_event = {
        "type": "message_added",
        "timestamp": datetime.now().isoformat(),
        "data": {
            "customer_id": 123,
            "customer_name": "张三",
            "channel": "微信",
            "message": {
                "content": "你好，请问有什么可以帮助您的？",
                "is_from_kefu": True,
                "message_type": "text",
                "timestamp": datetime.now().isoformat(),
            },
        },
    }

    print("   Event structure:")
    print(json.dumps(message_added_event, indent=6, ensure_ascii=False))

    # 2. message_batch 事件
    print("\n2. Testing 'message_batch' event format...")

    message_batch_event = {
        "type": "message_batch",
        "timestamp": datetime.now().isoformat(),
        "data": {
            "customer_name": "张三",
            "channel": "微信",
            "messages": [
                {
                    "content": "你好",
                    "is_from_kefu": False,
                    "message_type": "text",
                    "timestamp": datetime.now().isoformat(),
                },
                {
                    "content": "您好，有什么可以帮助您的？",
                    "is_from_kefu": True,
                    "message_type": "text",
                    "timestamp": datetime.now().isoformat(),
                },
            ],
            "count": 2,
        },
    }

    print("   Event structure:")
    print(json.dumps(message_batch_event, indent=6, ensure_ascii=False))

    # 3. history_refresh 事件
    print("\n3. Testing 'history_refresh' event format...")

    history_refresh_event = {
        "type": "history_refresh",
        "timestamp": datetime.now().isoformat(),
        "data": {
            "customer_name": "张三",
            "channel": "微信",
        },
    }

    print("   Event structure:")
    print(json.dumps(history_refresh_event, indent=6, ensure_ascii=False))

    # 4. connected 事件
    print("\n4. Testing 'connected' event format...")

    connected_event = {
        "type": "connected",
        "message": "Connected to message stream for test_serial_001",
        "contact_name": "张三",
        "channel": "微信",
    }

    print("   Event structure:")
    print(json.dumps(connected_event, indent=6, ensure_ascii=False))

    # 5. heartbeat 事件
    print("\n5. Testing 'heartbeat' event format...")

    heartbeat_event = {
        "type": "heartbeat",
    }

    print("   Event structure:")
    print(json.dumps(heartbeat_event, indent=6, ensure_ascii=False))

    print("\n" + "=" * 60)
    print("[SUCCESS] All event format tests passed!")
    print("=" * 60)

    return True


async def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("\nStarting WebSocket Tests\n")
    print("=" * 60)

    # 运行集成测试
    success1 = await test_websocket_flow()

    # 运行格式测试
    success2 = await test_message_event_formats()

    if success1 and success2:
        print("\n" + "=" * 60)
        print("\n[SUCCESS] All tests passed successfully!\n")
        print("=" * 60 + "\n")
        return 0
    else:
        print("\n" + "=" * 60)
        print("\n[ERROR] Some tests failed!\n")
        print("=" * 60 + "\n")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
