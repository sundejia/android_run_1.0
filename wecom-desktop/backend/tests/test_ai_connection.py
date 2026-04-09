"""
Tests for AI Service Connection.

TDD tests to verify wecom-desktop can connect to the AI brain (ai-services).
These tests verify:
1. AI server health check
2. Chat endpoint connectivity
3. Response parsing
"""

import sys
import pytest
import asyncio
from pathlib import Path
from unittest.mock import MagicMock

# Mock droidrun before importing
mock_droidrun = MagicMock()
mock_droidrun.tools = MagicMock()
mock_droidrun.tools.adb = MagicMock()
mock_droidrun.tools.adb.AdbTools = MagicMock()
sys.modules["droidrun"] = mock_droidrun
sys.modules["droidrun.tools"] = mock_droidrun.tools
sys.modules["droidrun.tools.adb"] = mock_droidrun.tools.adb

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

# AI Server configuration
AI_SERVER_URL = "http://localhost:8000"


class TestAIServerHealth:
    """Tests for AI server health check."""

    def test_health_endpoint_accessible(self):
        """Test that the /health endpoint is accessible."""
        response = httpx.get(f"{AI_SERVER_URL}/health", timeout=5.0)
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        print(f"✅ Health check passed: {data['status']}")

    def test_health_endpoint_returns_valid_json(self):
        """Test that health endpoint returns valid JSON with expected fields."""
        response = httpx.get(f"{AI_SERVER_URL}/health", timeout=5.0)
        data = response.json()

        # Check required fields
        assert "status" in data
        assert "version" in data
        assert "components" in data

        print(f"✅ Health response: status={data['status']}, version={data['version']}")
        print(f"   Components: {data['components']}")


class TestAIChatEndpoint:
    """Tests for AI chat endpoint connectivity."""

    def test_chat_endpoint_accessible(self):
        """Test that the /chat endpoint is accessible."""
        payload = {
            "chatInput": "测试连接",
            "sessionId": "test_connection_check",
            "username": "test_user",
            "message_type": "text",
        }

        response = httpx.post(f"{AI_SERVER_URL}/chat", json=payload, timeout=30.0)

        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        print(f"✅ Chat endpoint accessible, success={data.get('success')}")

    def test_chat_returns_valid_response(self):
        """Test that chat returns a valid response structure."""
        payload = {
            "chatInput": "你好",
            "sessionId": "test_response_structure",
            "username": "test_user",
            "message_type": "text",
        }

        response = httpx.post(f"{AI_SERVER_URL}/chat", json=payload, timeout=30.0)

        data = response.json()

        # Check required response fields
        assert "output" in data, "Response should contain 'output' field"
        assert "session_id" in data, "Response should contain 'session_id' field"
        assert "success" in data, "Response should contain 'success' field"
        assert "timestamp" in data, "Response should contain 'timestamp' field"

        print(f"✅ Valid response structure:")
        print(f"   - success: {data['success']}")
        print(f"   - session_id: {data['session_id']}")
        print(f"   - output length: {len(data.get('output', ''))}")

    def test_chat_with_sidecar_format(self):
        """Test chat with the format used by sidecar (wecom-desktop)."""
        payload = {
            "chatInput": "主播没有回复上次的信息，请在生成一个补刀信息",
            "sessionId": "sidecar_test_12345",
            "username": "sidecar_test",
            "message_type": "text",
            "metadata": {"source": "sidecar", "serial": "test_device", "timestamp": "2025-12-23T00:00:00Z"},
        }

        response = httpx.post(f"{AI_SERVER_URL}/chat", json=payload, timeout=30.0)

        assert response.status_code == 200
        data = response.json()

        # Sidecar expects these fields
        assert data.get("success") is True, f"Chat should succeed, got: {data}"
        assert data.get("output"), "Should return non-empty output"

        print(f"✅ Sidecar format test passed:")
        print(f"   - success: {data['success']}")
        print(f"   - output preview: {data['output'][:100]}...")


class TestAIServiceIntegration:
    """Integration tests for AI service with wecom-desktop patterns."""

    def test_followup_message_pattern(self):
        """Test the follow-up message pattern used by sync service."""
        # This is the pattern used when kefu sent last message
        payload = {
            "chatInput": "想的怎么样了?",  # Follow-up prompt
            "sessionId": "followup_test",
            "username": "kefu_test",
        }

        response = httpx.post(f"{AI_SERVER_URL}/chat", json=payload, timeout=30.0)

        data = response.json()
        assert data.get("success") is True
        assert data.get("output")

        print(f"✅ Follow-up pattern test passed")
        print(f"   Output: {data['output'][:100]}...")

    def test_reply_message_pattern(self):
        """Test the reply message pattern used by sync service."""
        # This is the pattern used when customer sent last message
        customer_message = "我对这个产品很感兴趣，能详细介绍一下吗？"
        payload = {"chatInput": customer_message, "sessionId": "reply_test", "username": "kefu_test"}

        response = httpx.post(f"{AI_SERVER_URL}/chat", json=payload, timeout=30.0)

        data = response.json()
        assert data.get("success") is True
        assert data.get("output")

        print(f"✅ Reply pattern test passed")
        print(f"   Input: {customer_message}")
        print(f"   Output: {data['output'][:100]}...")

    def test_connection_timeout_handling(self):
        """Test that connection handles timeout gracefully."""
        # Use a very short timeout to simulate network issues
        payload = {"chatInput": "test", "sessionId": "timeout_test"}

        # This should either succeed quickly or timeout gracefully
        try:
            response = httpx.post(
                f"{AI_SERVER_URL}/chat",
                json=payload,
                timeout=1.0,  # Very short timeout
            )
            # If we get here, the server responded quickly
            assert response.status_code == 200
            print(f"✅ Fast response received (< 1s)")
        except httpx.TimeoutException:
            # Timeout is acceptable - it means the connection works but AI takes time
            print(f"✅ Timeout handling works correctly")


class TestAIServerNoFcntlError:
    """Test that the fcntl fix is working (no Windows compatibility errors)."""

    def test_no_fcntl_error_in_response(self):
        """Verify that chat doesn't return fcntl-related errors."""
        payload = {"chatInput": "test fcntl fix", "sessionId": "fcntl_test"}

        response = httpx.post(f"{AI_SERVER_URL}/chat", json=payload, timeout=30.0)

        data = response.json()

        # Check that there's no fcntl error
        metadata = data.get("metadata", {})
        error = metadata.get("error", "")

        assert "fcntl" not in error.lower(), f"fcntl error still present: {error}"
        assert data.get("success") is True, f"Chat should succeed without fcntl error: {data}"

        print(f"✅ No fcntl error - Windows compatibility fix verified")
        print(f"   success: {data['success']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
