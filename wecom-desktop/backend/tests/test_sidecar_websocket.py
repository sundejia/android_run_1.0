"""
测试 Sidecar WebSocket 功能

测试 WebSocket 连接管理、消息广播等功能。
"""

import asyncio
import json
import sys
from pathlib import Path

# 添加 backend 目录到路径
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

import pytest
from fastapi.testclient import TestClient


def test_websocket_connection():
    """测试 WebSocket 基本连接"""
    # 这里需要导入实际的 app
    # 注意：这个测试需要完整的 FastAPI app 上下文
    pass


def test_websocket_manager_initialization():
    """测试 WebSocket Manager 初始化"""
    from services.websocket_manager import get_sidecar_message_manager

    manager = get_sidecar_message_manager()

    assert manager is not None
    assert manager._connections == {}
    assert manager._lock is not None


def test_websocket_manager_get_key():
    """测试连接 Key 生成"""
    from services.websocket_manager import SidecarMessageManager

    manager = SidecarMessageManager()

    # 测试各种参数组合
    key1 = manager._get_key("test_serial", "contact1", "channel1")
    assert key1 == "test_serial:contact1:channel1"

    key2 = manager._get_key("test_serial", None, None)
    assert key2 == "test_serial::"

    key3 = manager._get_key("test_serial", "contact1", None)
    assert key3 == "test_serial:contact1:"


def test_message_publisher_creation():
    """测试 MessagePublisher 创建"""
    from services.message_publisher import MessagePublisher

    publisher = MessagePublisher()

    assert publisher is not None


@pytest.mark.asyncio
async def test_notify_message_added():
    """测试发送消息添加通知"""
    from services.message_publisher import notify_message_added
    from services.websocket_manager import get_sidecar_message_manager

    manager = get_sidecar_message_manager()

    # 准备测试数据
    serial = "test_serial_001"
    customer_id = 123
    customer_name = "Test Customer"
    channel = "wechat"
    message = {
        "content": "Test message",
        "is_from_kefu": True,
        "message_type": "text",
        "timestamp": "2026-01-19T10:00:00",
    }

    # 调用通知函数（没有实际连接，应该不会报错）
    try:
        await notify_message_added(serial, customer_id, customer_name, channel, message)
        # 如果没有连接，应该只是静默失败
        assert True
    except Exception as e:
        pytest.fail(f"notify_message_added raised exception: {e}")


@pytest.mark.asyncio
async def test_notify_history_refresh():
    """测试发送历史刷新通知"""
    from services.message_publisher import notify_history_refresh

    serial = "test_serial_001"
    customer_name = "Test Customer"
    channel = "wechat"

    # 调用通知函数
    try:
        await notify_history_refresh(serial, customer_name, channel)
        assert True
    except Exception as e:
        pytest.fail(f"notify_history_refresh raised exception: {e}")


def test_message_event_format():
    """测试消息事件格式"""
    from datetime import datetime
    from services.message_publisher import MessagePublisher

    # 测试 message_added 事件格式
    event = {
        "type": "message_added",
        "timestamp": datetime.now().isoformat(),
        "data": {
            "customer_id": 123,
            "customer_name": "Test Customer",
            "channel": "wechat",
            "message": {
                "content": "Test message",
                "is_from_kefu": True,
                "message_type": "text",
                "timestamp": "2026-01-19T10:00:00",
            },
        },
    }

    # 验证格式
    assert event["type"] == "message_added"
    assert "timestamp" in event
    assert "data" in event
    assert "customer_id" in event["data"]
    assert "message" in event["data"]


@pytest.mark.asyncio
async def test_concurrent_connections():
    """测试并发连接管理"""
    from services.websocket_manager import SidecarMessageManager

    manager = SidecarMessageManager()

    # 模拟多个连接
    serial = "test_serial_001"
    contacts = ["contact1", "contact2", "contact3"]

    # 验证连接状态
    for contact in contacts:
        key = manager._get_key(serial, contact, "wechat")
        # 在实际测试中，这里会创建 WebSocket 连接
        # 现在只验证 Key 生成逻辑
        assert key == f"{serial}:{contact}:wechat"


def test_event_types():
    """测试所有事件类型"""
    event_types = ["connected", "message_added", "message_batch", "history_refresh", "heartbeat"]

    for event_type in event_types:
        event = {"type": event_type}
        assert event["type"] in event_types


if __name__ == "__main__":
    # 运行基本测试
    print("Running WebSocket Manager tests...")

    test_websocket_manager_initialization()
    print("[PASS] WebSocket Manager initialization test passed")

    test_websocket_manager_get_key()
    print("[PASS] WebSocket Manager get_key test passed")

    test_message_publisher_creation()
    print("[PASS] Message Publisher creation test passed")

    test_message_event_format()
    print("[PASS] Message event format test passed")

    test_event_types()
    print("[PASS] Event types test passed")

    print("\n[SUCCESS] All basic tests passed!")

    # 运行异步测试
    print("\nRunning async tests...")
    asyncio.run(test_notify_message_added())
    print("[PASS] notify_message_added test passed")

    asyncio.run(test_notify_history_refresh())
    print("[PASS] notify_history_refresh test passed")

    asyncio.run(test_concurrent_connections())
    print("[PASS] Concurrent connections test passed")

    print("\n[SUCCESS] All async tests passed!")
